"""
Feed interface — every data source implements this.

THE RULE THIS FILE EXISTS TO ENFORCE:

    No price is ever returned without its freshness attached.

On 2026-08-05 a DAX trade was set up on a 16-minute-delayed index that looked
identical on screen to live data. The market had already gapped 0.5% past the
trigger and was rolling over before the delayed feed showed it arriving. Every
panel in this terminal therefore renders its own latency, and that is only
possible if the feed reports it.

`Quote.age_min` and `FeedStatus` are not optional metadata. They are the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import pandas as pd


class Freshness(str, Enum):
    REALTIME = "realtime"    # < 2 min behind
    DELAYED = "delayed"      # 2-30 min behind (still tradeable, but know it)
    CLOSED = "closed"        # market shut — old data is CORRECT, not broken
    STALE = "stale"          # market open but data missing — do NOT trade
    UNKNOWN = "unknown"


# Market sessions in local exchange time, keyed by symbol suffix/prefix.
# CLOSED vs STALE is the distinction that matters: after the European close a
# 60-minute-old bar is right, not broken. Without this the terminal would cry
# wolf every evening and the warning would stop meaning anything.
_SESSIONS = {
    "EU": ("Europe/Stockholm", (9, 0), (17, 30)),
    "UK": ("Europe/London", (8, 0), (16, 30)),
    "US": ("America/New_York", (9, 30), (16, 0)),
    "IN": ("Asia/Kolkata", (9, 15), (15, 30)),
}
_SUFFIX = {".ST": "EU", ".DE": "EU", ".PA": "EU", ".AS": "EU", ".MI": "EU",
           ".MC": "EU", ".SW": "EU", ".L": "UK", ".NS": "IN"}
_INDEX = {"^OMX": "EU", "^GDAXI": "EU", "^FCHI": "EU", "^STOXX50E": "EU",
          "^FTSE": "UK", "^NSEI": "IN", "^NSEBANK": "IN"}


def market_for(symbol: str) -> str | None:
    """Which session governs this symbol. None = 24h (crypto, futures, FX)."""
    if symbol in _INDEX:
        return _INDEX[symbol]
    for suf, mkt in _SUFFIX.items():
        if symbol.endswith(suf):
            return mkt
    if symbol.endswith("=F") or symbol.endswith("-USD") or "=X" in symbol:
        return None                      # trades ~24h
    if symbol.startswith("^"):
        return "US"
    return "US"


def is_market_open(symbol: str) -> bool:
    mkt = market_for(symbol)
    if mkt is None:
        return True
    from zoneinfo import ZoneInfo
    tzname, (oh, om), (ch, cm) = _SESSIONS[mkt]
    now = datetime.now(ZoneInfo(tzname))
    if now.weekday() >= 5:
        return False
    return now.replace(hour=oh, minute=om, second=0) <= now <= now.replace(hour=ch, minute=cm, second=0)


# Where the line sits between "live enough" and "delayed".
REALTIME_CUTOFF_MIN = 2.0
STALE_CUTOFF_MIN = 30.0


@dataclass
class Quote:
    symbol: str
    price: float
    ts: datetime                 # timestamp OF THE DATA, not of the request
    change_pct: float = float("nan")
    volume: float = float("nan")
    source: str = ""

    @property
    def age_min(self) -> float:
        now = datetime.now(timezone.utc)
        ts = self.ts if self.ts.tzinfo else self.ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 60.0

    @property
    def freshness(self) -> Freshness:
        a = self.age_min
        if a != a:
            return Freshness.UNKNOWN
        if a < REALTIME_CUTOFF_MIN:
            return Freshness.REALTIME
        if a < STALE_CUTOFF_MIN:
            return Freshness.DELAYED
        # Old data with the market shut is correct, not broken.
        return Freshness.STALE if is_market_open(self.symbol) else Freshness.CLOSED

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "ts": self.ts.isoformat(),
            "change_pct": None if self.change_pct != self.change_pct else self.change_pct,
            "volume": None if self.volume != self.volume else self.volume,
            "source": self.source,
            "age_min": round(self.age_min, 1),
            "freshness": self.freshness.value,
        }


@dataclass
class Bars:
    """OHLCV history plus provenance of the newest bar."""
    symbol: str
    df: pd.DataFrame                     # index=datetime, cols Open/High/Low/Close/Volume
    source: str = ""
    interval: str = "1d"

    @property
    def last_ts(self) -> datetime | None:
        if self.df is None or self.df.empty:
            return None
        ts = self.df.index[-1]
        return ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts

    def to_candles(self) -> list[dict]:
        """Lightweight Charts wants {time, open, high, low, close} with epoch secs."""
        if self.df is None or self.df.empty:
            return []
        out = []
        for ts, r in self.df.iterrows():
            t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            out.append({
                "time": int(t.timestamp()),
                "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]),
            })
        return out


class Feed(Protocol):
    """Sources are swappable without the UI knowing which one it is."""

    name: str

    def quote(self, symbol: str) -> Quote | None: ...

    def bars(self, symbol: str, interval: str = "1d", lookback: str = "1y") -> Bars | None: ...
