"""
The ticker strip across the top of every page (`/api/market-line`).

Freshness is mapped from `Quote.freshness` (terminal/feeds/base.py), with one
rename: the feed says "realtime", the front end says "live". Gold is the one
special case. Real-time SPOT comes from the Avanza ETC (terminal/feeds/spot.py)
and is used only when a session is ALREADY authenticated -- this endpoint never
triggers a login. Otherwise GC=F futures are served, and marked at least
"delayed": Yahoo's futures data is ~11 minutes behind even when the bar
timestamp looks fresh, and futures sit ~1.4% above spot on carry.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

CACHE_TTL_S = 15

# key, label, yahoo symbol
ITEMS = [
    ("omxs30", "OMXS30",   "^OMX"),
    ("spx",    "S&P 500",  "^GSPC"),
    ("ndx",    "Nasdaq 100", "^NDX"),
    ("gold",   "Gold",     None),          # resolved at request time
    ("usdsek", "USD/SEK",  "USDSEK=X"),
]

_FRESH = {"realtime": "live", "delayed": "delayed", "closed": "closed",
          "stale": "stale", "unknown": "unknown"}


def _num(x, nd=None):
    if x is None or x != x:
        return None
    return round(float(x), nd) if nd is not None else float(x)


def _item(key: str, label: str, symbol: str, q, *, force_delayed: bool = False,
          error: str | None = None, source: str | None = None) -> dict:
    if q is None:
        return {"key": key, "label": label, "symbol": symbol, "last": None,
                "change_pct": None, "freshness": "unknown", "age_min": None,
                "source": source, "error": error or "no quote returned"}
    fr = _FRESH.get(getattr(q.freshness, "value", str(q.freshness)), "unknown")
    if force_delayed and fr == "live":
        fr = "delayed"
    return {"key": key, "label": label, "symbol": symbol,
            "last": _num(q.price, 4), "change_pct": _num(q.change_pct, 3),
            "freshness": fr, "age_min": _num(q.age_min, 1),
            "source": source or q.source}


def build(feed, yf_feed, avanza) -> dict:
    """feed = routed QuoteRouter, yf_feed = plain yfinance, avanza = AvanzaFeed."""
    gold_spot = bool(avanza is not None and getattr(avanza, "authenticated", False))

    def one(spec):
        key, label, sym = spec
        try:
            if key == "gold":
                if gold_spot:
                    q = feed.quote("XAUUSD")     # router -> avanza-spot
                    if q is not None and q.source == "avanza-spot":
                        return _item(key, label, "XAUUSD", q)
                q = yf_feed.quote("GC=F")
                return _item(key, label, "GC=F", q, force_delayed=True,
                             source="yfinance-futures")
            return _item(key, label, sym, feed.quote(sym))
        except Exception as e:
            return _item(key, label, sym or "GC=F", None,
                         error=f"{type(e).__name__}: {e}"[:160])

    with ThreadPoolExecutor(max_workers=len(ITEMS)) as pool:
        items = list(pool.map(one, ITEMS))
    return {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items": items}


class MarketLine:
    def __init__(self, ttl: float = CACHE_TTL_S):
        self.ttl = ttl
        self._hit: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def get(self, feed, yf_feed, avanza) -> dict:
        with self._lock:
            if self._hit and time.time() - self._hit[0] < self.ttl:
                return self._hit[1]
        data = build(feed, yf_feed, avanza)
        with self._lock:
            self._hit = (time.time(), data)
        return data
