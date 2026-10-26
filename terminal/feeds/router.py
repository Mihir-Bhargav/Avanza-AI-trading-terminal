"""
Quote router — Avanza first where it is real-time, yfinance everywhere else.

WHY. On 2026-08-06 at 15:00 CET, with Stockholm open, every Swedish name in the
watchlist carried an identical age of 320.9 minutes. Identical ages across
unrelated symbols is not per-symbol staleness -- it is one source that stopped.
A direct yfinance fetch, bypassing every cache, confirmed it: the last 1-minute
bar for ERIC-B.ST and ^OMX was 09:40 CET, over five hours earlier. Gold's last
bar was 03:30 ET. Same class of failure as 2026-08-04, when yfinance withdrew a
completed session for 78 of 86 European names.

No amount of cache tuning fixes a source that has stopped publishing. The fix is
a second source, and the terminal already had one: an authenticated Avanza
session, which returns is_realtime=True for Nordic equities. Measured side by
side at that moment -- Avanza 95.96 live, yfinance 96.24 from five hours ago.

WHAT THIS ROUTES
    Nordic equities and indices  -> Avanza (real-time, verified per instrument)
    Gold                         -> Avanza physical ETC, converted to spot
    Everything else              -> yfinance, unchanged

WHAT IT DOES NOT DO
Bars still come from yfinance. Daily bars were never the problem -- levels were
correctly dated to the prior completed session throughout the outage. Only the
live quote was stale, so only the live quote is rerouted. Replacing bars too
would be a much larger change for no observed defect.

Avanza is used ONLY when it says is_realtime. A delayed Avanza quote is not
better than a delayed Yahoo one, and preferring it on faith would swap a known
problem for an unmeasured one.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .base import Freshness, Quote, is_market_open

# yfinance suffixes that Avanza covers well. Nordic only -- Avanza carries US and
# German names too, but yfinance is not failing there and every reroute is a
# mapping that can silently point at the wrong instrument.
NORDIC_SUFFIXES = (".ST", ".HE", ".CO", ".OL")

# Indices have no ticker to derive, so they are named explicitly.
INDEX_MAP = {"^OMX": "OMXS30", "^OMXSPI": "OMX Stockholm PI"}


def _ts_from_ms(ms) -> datetime | None:
    """Epoch milliseconds -> aware datetime. None when Avanza gives no clock."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class QuoteRouter:
    def __init__(self, yf_feed, avanza_feed):
        self.yf = yf_feed
        self.av = avanza_feed
        self._ids: dict[str, str | None] = {}     # yf symbol -> avanza orderbook id
        self._lock = threading.Lock()
        self._stats = {"avanza": 0, "yfinance": 0, "avanza_miss": 0}

    # ------------------------------------------------------------- resolution
    def _avanza_query(self, symbol: str) -> str | None:
        if symbol in INDEX_MAP:
            return INDEX_MAP[symbol]
        if symbol.endswith(NORDIC_SUFFIXES):
            # yfinance writes share classes with a hyphen (ERIC-B.ST); Avanza
            # writes them with a space (ERIC B).
            base = symbol.rsplit(".", 1)[0]
            return base.replace("-", " ")
        return None

    def _orderbook_id(self, symbol: str) -> str | None:
        with self._lock:
            if symbol in self._ids:
                return self._ids[symbol]
        q = self._avanza_query(symbol)
        oid = None
        if q:
            try:
                for h in self.av.search(q, limit=8):
                    if h.get("type") in ("STOCK", "INDEX") and h.get("orderbook_id"):
                        oid = h["orderbook_id"]
                        break
            except Exception:
                oid = None
        with self._lock:
            self._ids[symbol] = oid
        return oid

    # ------------------------------------------------------------------ quote
    def quote(self, symbol: str) -> Quote | None:
        sp = self._spot_quote(symbol)
        if sp is not None:
            self._stats["spot"] = self._stats.get("spot", 0) + 1
            return sp
        av = self._avanza_quote(symbol)
        if av is not None:
            self._stats["avanza"] += 1
            return av
        self._stats["yfinance"] += 1
        return self.yf.quote(symbol)

    def _avanza_quote(self, symbol: str) -> Quote | None:
        # Check CONFIGURED, not authenticated. Gating on `authenticated` was a
        # deadlock: login is lazy and fires inside AvanzaFeed._get, so bailing
        # out first meant login never happened and the router never engaged --
        # it reported 0 Avanza quotes with credentials sitting right there.
        if self.av is None:
            return None
        auth = getattr(self.av, "auth", None)
        if auth is None or not getattr(auth, "configured", False):
            return None
        oid = self._orderbook_id(symbol)
        if not oid:
            return None
        try:
            d = self.av.instrument(oid)
        except Exception:
            return None
        if not d or d.get("last") is None:
            return None
        # The whole point. Anything less than real-time falls through.
        if not d.get("is_realtime"):
            self._stats["avanza_miss"] += 1
            return None
        # THE DATA'S timestamp, never now(). Stamping with now() made every
        # Avanza quote report age 0.0 and freshness REALTIME forever -- verified
        # at 23:20 CEST with Stockholm shut since 17:30: the price sat frozen at
        # 366.9 across repeated fetches while the age never moved off zero.
        # That is precisely the "a whole source stalled" failure this terminal
        # exists to make visible, and the detector was structurally blind to it.
        ts = _ts_from_ms(d.get("updated_ms")) or _ts_from_ms(d.get("last_trade_ms"))
        if ts is None:
            # No usable clock from Avanza -> do not claim freshness we cannot
            # support. Fall through to yfinance rather than assert realtime.
            self._stats["no_timestamp"] = self._stats.get("no_timestamp", 0) + 1
            return None
        return Quote(
            symbol=symbol,
            price=float(d["last"]),
            ts=ts,
            change_pct=(None if d.get("change_pct") is None
                        or d["change_pct"] != d["change_pct"] else float(d["change_pct"])),
            volume=float("nan"),
            source="avanza-rt",
        )

    def _spot_quote(self, symbol: str) -> Quote | None:
        """Gold futures were 11 minutes delayed and Yahoo's socket carries no
        futures at all. The physical ETC is real-time, so spot is derived from
        it -- and spot is what a gold certificate actually tracks.

        Deliberately reported as XAUUSD-equivalent, NOT as the futures price:
        the two differ by ~1.4% carry, and silently swapping one for the other
        would be the same confusion this router was built to end.
        """
        from . import spot as SPOT
        metal = {"GC=F": "XAUUSD", "MGC=F": "XAUUSD", "XAUUSD": "XAUUSD"}.get(symbol.upper())
        if not metal:
            return None
        auth = getattr(self.av, "auth", None)
        if auth is None or not getattr(auth, "configured", False):
            return None
        try:
            d = SPOT.spot(metal, self.av, self.yf)
        except Exception:
            return None
        # Only verified ratios are allowed to REPLACE a quote. An unverified
        # one is still exposed on /api/spot for eyeballing, but it must not
        # silently become the number the watchlist trades off.
        if not d or not d.get("trusted"):
            return None
        ts = _ts_from_ms(d.get("etc_updated_ms"))
        return Quote(symbol=symbol, price=float(d["price"]),
                     # Same rule: the ETC's own clock, or nothing.
                     ts=ts or datetime.now(timezone.utc),
                     change_pct=float("nan"), volume=float("nan"),
                     source="avanza-spot")

    def bars(self, *a, **k):
        return self.yf.bars(*a, **k)

    def stats(self) -> dict:
        return dict(self._stats, mapped=sum(1 for v in self._ids.values() if v))
