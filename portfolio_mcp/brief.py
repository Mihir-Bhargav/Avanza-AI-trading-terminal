"""
Deterministic numbers for the portfolio brief.

Every figure the brief quotes is computed here, not by the model: weights,
concentration, currency exposure, movers, stale prices, days to earnings.
Adds public yfinance data only -- no new Avanza endpoints, so the read-only
allowlist is unchanged.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from .portfolio import Portfolio

BIG_DAY_MOVE_PCT = 3.0
DEEP_LOSS_PCT = -10.0
STALE_DAYS = 3


def _next_earnings(ticker: str) -> tuple[str, dict]:
    import yfinance as yf
    try:
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        future = sorted(d for d in (dates or []) if d >= date.today())
        return ticker, ({"date": future[0].isoformat(),
                         "days_until": (future[0] - date.today()).days} if future
                        else {"date": None, "days_until": None})
    except Exception as e:
        return ticker, {"error": type(e).__name__}


def _r(x, n=2):
    return None if x is None else round(x, n)


def brief_data(pf: Portfolio, earnings_within_days: int = 30) -> dict:
    summ = pf.account_summary()
    pos = pf.positions()
    rows = [r for r in pos["positions"] if r["market_value_sek"] is not None]

    invested = sum(r["market_value_sek"] for r in rows)
    cash = sum(c["cash"] or 0 for c in pos["cash"] if c["unit"] == "SEK")
    total = invested + cash

    holdings = []
    for r in sorted(rows, key=lambda r: -r["market_value_sek"]):
        holdings.append({
            "name": r["name"], "ticker": r["yahoo_ticker"], "type": r["instrument_type"],
            "currency": r["currency"], "account": r["account"],
            "value_sek": _r(r["market_value_sek"], 0),
            "weight_of_portfolio_pct": _r(r["market_value_sek"] / total * 100) if total else None,
            "weight_of_invested_pct": _r(r["market_value_sek"] / invested * 100) if invested else None,
            "pnl_sek": _r(r["pnl_sek"], 0), "pnl_pct": r["pnl_pct"],
            "day_change_pct": r["day_change_pct"],
        })

    by_type: dict[str, float] = {}
    for r in rows:
        by_type[r["instrument_type"]] = by_type.get(r["instrument_type"], 0) + r["market_value_sek"]

    today = date.today()
    stale = []
    for r in rows:
        ts = r.get("last_price_updated")
        try:
            age = (today - datetime.fromisoformat(ts[:19]).date()).days
        except Exception:
            age = None
        if age is None or age > STALE_DAYS:
            stale.append({"name": r["name"], "last_price_updated": ts, "age_days": age})

    stock_tickers = sorted({r["yahoo_ticker"] for r in rows
                            if r["yahoo_ticker"] and r["instrument_type"] == "STOCK"})
    with ThreadPoolExecutor(max_workers=8) as ex:
        earn = dict(ex.map(_next_earnings, stock_tickers))
    upcoming = sorted(
        ({"ticker": t, **e} for t, e in earn.items()
         if e.get("days_until") is not None and e["days_until"] <= earnings_within_days),
        key=lambda e: e["days_until"])

    perf = {}
    for p in ("1d", "1w", "1m", "ytd"):
        d = pf.performance(p)
        perf[p] = {
            "per_account": [{k: a[k] for k in ("account", "change", "change_pct")}
                            for a in d["per_account"] if a["change"]],
            "insights_total_sek": _r((d["insights"] or {}).get("total_outcome_sek")),
            "best": (d["insights"] or {}).get("best") if p == "1w" else None,
            "worst": (d["insights"] or {}).get("worst") if p == "1w" else None,
        }

    top = [h["weight_of_invested_pct"] for h in holdings]
    return {
        "as_of": datetime.now().isoformat(timespec="minutes"),
        "totals_sek": {"portfolio": _r(total, 0), "invested": _r(invested, 0), "cash": _r(cash, 0),
                       "cash_pct": _r(cash / total * 100) if total else None,
                       "cost_basis": pos["totals_sek"]["cost_basis"],
                       "unrealized_pnl": pos["totals_sek"]["pnl"],
                       "unrealized_pnl_pct": _r(pos["totals_sek"]["pnl"] / pos["totals_sek"]["cost_basis"] * 100)
                       if pos["totals_sek"]["cost_basis"] else None},
        "accounts": [{k: a[k] for k in ("account", "type", "total_value", "cash")}
                     for a in summ["accounts"] if a["total_value"]],
        "performance": perf,
        "concentration": {
            "top1_pct_of_invested": _r(top[0]) if top else None,
            "top3_pct_of_invested": _r(sum(top[:3])) if top else None,
            "by_instrument_type_pct": {k: _r(v / invested * 100) for k, v in
                                       sorted(by_type.items(), key=lambda kv: -kv[1])} if invested else {},
            "by_currency_pct": {k: v["pct"] for k, v in pos["exposure_by_currency_sek"].items()},
        },
        "holdings": holdings,
        "flags": {
            f"day_move_over_{BIG_DAY_MOVE_PCT:g}pct": [h for h in holdings
                                                      if abs(h["day_change_pct"] or 0) >= BIG_DAY_MOVE_PCT],
            f"unrealized_loss_beyond_{DEEP_LOSS_PCT:g}pct": [h for h in holdings
                                                            if (h["pnl_pct"] or 0) <= DEEP_LOSS_PCT],
            f"stale_price_over_{STALE_DAYS}d": stale,
        },
        "earnings": {
            "within_days": earnings_within_days,
            "upcoming": upcoming,
            "checked": stock_tickers,
            "lookup_failed": [t for t, e in earn.items() if "error" in e],
            "not_applicable": [h["name"] for h in holdings if h["type"] != "STOCK"],
            "unmapped_stocks": [h["name"] for h in holdings if h["type"] == "STOCK" and not h["ticker"]],
        },
        "news_targets": {
            "stock_tickers": stock_tickers,
            "other_mapped": sorted({h["ticker"] for h in holdings if h["ticker"] and h["type"] != "STOCK"}),
        },
    }
