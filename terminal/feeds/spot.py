"""
Real-time SPOT commodity prices, derived from Avanza's physically-backed ETCs.

THE PROBLEM THIS SOLVES
-----------------------
The terminal showed gold at 4322 while TradingView showed 4262. That looked
like a 60-point staleness bug. It was two separate things, and only one of them
was a bug:

  1. GC=F is COMEX FUTURES, XAUUSD is SPOT. They are different instruments and
     the gap is contango -- carry, not lag. Measured 2026-08-06: +61.25 USD,
     about 1.4%, which is the cost of carry out to the active contract. No feed
     change can make one equal the other, and quietly relabelling futures as
     "gold" is how you end up trading a number you did not mean.

  2. GC=F really was 11 minutes delayed, and Yahoo's live socket does not carry
     futures at all -- verified, zero ticks on GC=F/SI=F/HG=F/CL=F/BZ=F.

So spot comes from somewhere else entirely: the authenticated Avanza session,
which quotes physically-backed ETCs in real time.

HOW THE CONVERSION WORKS
------------------------
Xetra-Gold (4GLD) is defined as ONE GRAM of gold per unit, quoted in EUR:

    spot_usd_per_oz = eur_per_gram * 31.1034768 * EURUSD

Verified end to end on 2026-08-06:

    Xetra-Gold      118.63 EUR/gram   (Avanza, realtime)
    EURUSD          1.15473
    implied spot    4,260.75 USD/oz
    TradingView     4,262           -> 0.03% apart

That 0.03% is the ETC's bid/ask and the FX tick, which is as close as two
independent sources get. The same trick works for any ETC with a published
metal-per-unit ratio; each one has to be entered deliberately, because a wrong
ratio produces a plausible number rather than an obvious error.
"""

from __future__ import annotations

TROY_OZ_GRAMS = 31.1034768

# metal grams per ETC unit, and the quote currency.
#
# These ratios are structural, not guesses -- Xetra-Gold is contractually 1g per
# certificate. They do drift down very slowly as the issuer sells metal to cover
# fees (~0.3%/yr), so `verified` records when each was last checked against an
# independent source. Anything more than a year stale should be re-verified
# rather than trusted.
ETC_SPOT = {
    "XAUUSD": {
        "query": "Xetra-Gold",
        "grams_per_unit": 1.0,
        "currency": "EUR",
        "label": "Gold spot USD/oz",
        "verified": "2026-08-06 (0.03% vs TradingView OANDA:XAUUSD)",
    },
    # UNVERIFIED. WisdomTree Core Physical Silver looks like 1 troy oz per unit
    # -- against the stale SI=F future it implies 0.987 oz, and futures sit
    # ~1.4% above spot on carry, which lands it on 1.001. That is inference, not
    # a measurement: the only reference available was itself stale. Gold was
    # confirmed to 0.03% against an independent quote and silver has not been,
    # so it ships flagged and the flag travels in the response.
    "XAGUSD": {
        "query": "WisdomTree Core Physical Silver",
        "grams_per_unit": TROY_OZ_GRAMS,      # i.e. 1 troy ounce per unit
        "currency": "EUR",
        "label": "Silver spot USD/oz",
        "verified": None,
        "unverified_note": ("ratio inferred, not measured — compare once against "
                            "TradingView OANDA:XAGUSD and correct if it differs"),
    },
}


def _fx(pair: str, feed) -> float | None:
    q = feed.quote(pair)
    return q.price if q else None


def spot(metal: str, avanza, yf_feed) -> dict | None:
    """Live spot for `metal` (e.g. "XAUUSD"), or None.

    Returns None rather than a guess whenever any leg is missing -- an
    unlabelled fallback to delayed futures is exactly the confusion this module
    exists to remove.
    """
    cfg = ETC_SPOT.get(metal.upper())
    if not cfg or avanza is None:
        return None

    oid = _find_etc(cfg["query"], avanza)
    if not oid:
        return None
    d = avanza.instrument(oid)
    if not d or d.get("last") is None:
        return None
    # Only real-time is worth having here; a delayed ETC is no better than the
    # delayed future it is replacing, and pretending otherwise is the bug.
    if not d.get("is_realtime"):
        return None

    per_oz = float(d["last"]) * TROY_OZ_GRAMS / cfg["grams_per_unit"]
    ccy = cfg["currency"]
    if ccy == "USD":
        usd = per_oz
        rate = 1.0
    else:
        rate = _fx(f"{ccy}USD=X", yf_feed)
        if not rate:
            return None
        usd = per_oz * rate

    return {
        "metal": metal.upper(),
        "price": round(usd, 2),
        "label": cfg["label"],
        "source": f"avanza:{d['name']}",
        "freshness": "realtime",
        "etc_price": d["last"],
        "etc_currency": ccy,
        "fx": round(rate, 5),
        "etc_updated_ms": d.get("updated_ms"),
        "ratio_verified": cfg["verified"],
        "trusted": bool(cfg["verified"]),
        "warning": cfg.get("unverified_note"),
    }


_CACHE: dict[str, str] = {}


def _find_etc(query: str, avanza) -> str | None:
    """Resolve the ETC's orderbook id once and remember it."""
    if query in _CACHE:
        return _CACHE[query]
    try:
        for h in avanza.search(query, limit=6):
            if h.get("orderbook_id"):
                _CACHE[query] = h["orderbook_id"]
                return _CACHE[query]
    except Exception:
        pass
    return None


def annotate(symbol: str, avanza, yf_feed) -> dict | None:
    """Spot companion for a futures symbol, with the basis spelled out.

    Attached to the futures quote rather than replacing it: the futures price is
    correct for what it is, and the useful thing is seeing both plus the gap.
    """
    metal = {"GC=F": "XAUUSD", "MGC=F": "XAUUSD"}.get(symbol.upper())
    if not metal:
        return None
    s = spot(metal, avanza, yf_feed)
    if not s:
        return None
    fq = yf_feed.quote(symbol)
    if fq:
        s["futures"] = fq.price
        s["futures_age_min"] = fq.age_min
        s["basis"] = round(fq.price - s["price"], 2)
        s["basis_pct"] = round((fq.price / s["price"] - 1) * 100, 2)
        s["note"] = ("futures trade above spot on carry; the gap is contango, "
                     "not staleness")
    return s
