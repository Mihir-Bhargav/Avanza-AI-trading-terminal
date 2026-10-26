"""
yfinance feed.

Measured latencies on 2026-08-05 (why this feed is used for Sweden and nothing
time-critical elsewhere):

    Swedish stocks + OMXS30   ~1 min    <- genuinely near real-time
    Crypto                    ~1 min
    US equities               varies
    DAX / EuroStoxx / EU eq   ~16 min
    Metals / oil futures      ~11 min

KNOWN FAILURE MODE, seen live: yfinance silently WITHDREW the completed
2026-08-04 session for 78 of 86 European names — bars that had been fetched and
validated the previous evening returned NaN through every access path. Two
guards below exist because of that day:

  1. drop rows with NaN OHLC (an unsettled bar carries volume but no prices)
  2. optionally drop today's bar, since a forming bar is not a completed session
     and CPR built from it describes tomorrow, not today
"""

from __future__ import annotations

import time
import warnings
from datetime import date, datetime, timezone

import pandas as pd

from .base import Bars, Feed, Quote

warnings.filterwarnings("ignore")

# TTL cache. Without this the terminal rate-limits ITSELF: the websocket polls
# every symbol on a timer, the watchlist rescans, and every chart load refetches
# -- which produced a real YFRateLimitError on 2026-08-05 and made the whole app
# return None for everything. Intraday data is cached briefly, daily bars for
# much longer since a completed session does not change.
_CACHE: dict = {}
_TTL = {"1m": 45, "5m": 60, "15m": 120, "1h": 300, "1d": 900}


def _cached(key, ttl, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    # Never cache a failure -- otherwise one rate-limited call poisons the key
    # for its whole TTL and the panel silently shows nothing.
    if val is not None:
        _CACHE[key] = (now, val)
        return val
    return hit[1] if hit else None


class YFinanceFeed:
    name = "yfinance"

    def _history(self, symbol: str, period: str, interval: str) -> pd.DataFrame | None:
        import yfinance as yf

        def _fetch():
            try:
                df = yf.Ticker(symbol).history(period=period, interval=interval)
                return df if df is not None and not df.empty else None
            except Exception:
                return None

        df = _cached((symbol, period, interval), _TTL.get(interval, 300), _fetch)
        if df is None:
            return None
        if df is None or df.empty:
            return None
        # Guard 1: unsettled bars carry volume but NaN prices.
        df = df.dropna(subset=["High", "Low", "Close"])
        return df if not df.empty else None

    def quote(self, symbol: str) -> Quote | None:
        df = self._history(symbol, "1d", "1m")
        if df is None:
            df = self._history(symbol, "5d", "1d")
            if df is None:
                return None
        last = df.iloc[-1]
        ts = df.index[-1]
        ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Day change measured against the previous COMPLETED session, not the
        # first bar of today — otherwise a gap disappears from the number.
        chg = float("nan")
        daily = self._history(symbol, "5d", "1d")
        if daily is not None and len(daily) >= 2:
            prev = daily[[i.date() < datetime.now().date() for i in daily.index]]
            if len(prev):
                chg = (float(last["Close"]) / float(prev["Close"].iloc[-1]) - 1) * 100

        return Quote(
            symbol=symbol, price=float(last["Close"]), ts=ts, change_pct=chg,
            volume=float(last.get("Volume", float("nan"))), source=self.name,
        )

    def bars(self, symbol: str, interval: str = "1d", lookback: str = "1y",
             exclude_today: bool = True) -> Bars | None:
        df = self._history(symbol, lookback, interval)
        if df is None:
            return None
        # Guard 2: a bar dated today is still forming. Levels derived from it
        # would describe tomorrow's session, not today's.
        if exclude_today and interval == "1d":
            today = date.today()
            keep = [i.date() < today for i in df.index]
            if any(keep):
                df = df[keep]
        return Bars(symbol=symbol, df=df, source=self.name, interval=interval)
