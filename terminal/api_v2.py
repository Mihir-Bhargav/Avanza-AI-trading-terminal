"""
API for the redesigned front end (`web/`). Contract: docs/API.md.

Everything here is READ-ONLY with respect to the broker. The only write in this
router is POST /api/plans, which appends a local JSON record of intent. Portfolio
data goes exclusively through portfolio_mcp's ReadOnlyAvanza allowlist, sharing
the terminal's ONE AvanzaAuth session (never a second login path).

Dependencies are bound by terminal/app.py via `bind(...)` rather than imported,
which avoids an import cycle and lets tests bind fakes (no network, no logins).

Errors are JSON {"error": "..."}: 503 upstream/unconfigured, 400 bad input.
Anything that could echo an Avanza detail passes through `redact`.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from portfolio_mcp.avanza_readonly import AvanzaUnavailable, redact
from screeners import zone_panel as ZP
from terminal import disclosures as DISC
from terminal import funds13f as F13
from terminal import kes as KES
from terminal import plans as PLANS
from terminal.market_line import MarketLine
from terminal.setups import SetupsService

router = APIRouter()


class _Deps:
    feed: Any = None            # routed QuoteRouter
    yf: Any = None              # plain yfinance feed
    avanza: Any = None          # AvanzaFeed
    auth: Any = None            # the single AvanzaAuth
    setups: SetupsService | None = None
    plans: PLANS.PlanStore | None = None
    market_line: MarketLine | None = None
    portfolio_factory: Callable[[], Any] | None = None
    disclosure_fetcher_factory: Callable[[str], DISC.Fetcher] | None = None
    _portfolio: Any = None
    _pf_lock = threading.Lock()


D = _Deps()


def bind(*, feed, yf, avanza, auth, setups: SetupsService | None = None,
         plans: PLANS.PlanStore | None = None, portfolio_factory=None,
         disclosure_fetcher_factory=None) -> None:
    D.feed, D.yf, D.avanza, D.auth = feed, yf, avanza, auth
    D.setups = setups or SetupsService(_daily_bars)
    D.plans = plans or PLANS.PlanStore()
    D.market_line = MarketLine()
    D.portfolio_factory = portfolio_factory or _default_portfolio
    D.disclosure_fetcher_factory = disclosure_fetcher_factory or (lambda key: DISC.Fetcher(key))
    D._portfolio = None


def _daily_bars(yahoo: str):
    # exclude_today=False: the zones are built around TODAY's open, and the
    # latest close is the price being classified.
    b = D.feed.bars(yahoo, "1d", "2y", exclude_today=False)
    return None if b is None else b.df


def _default_portfolio():
    from portfolio_mcp.avanza_readonly import ReadOnlyAvanza
    from portfolio_mcp.portfolio import Portfolio
    return Portfolio(ReadOnlyAvanza(auth=D.auth))


def _err(msg: str, status: int, **extra) -> JSONResponse:
    return JSONResponse({"error": msg, **extra}, status_code=status)


# ------------------------------------------------------------- market line
@router.get("/api/market-line")
def market_line():
    return D.market_line.get(D.feed, D.yf, D.avanza)


# ------------------------------------------------------------------ setups
@router.get("/api/setups")
def setups(symbol: str | None = None):
    if symbol:
        try:                        # bounds the ad-hoc fetch + its cache key
            PLANS.check_symbol(symbol)
        except PLANS.PlanError as e:
            return _err(str(e), 400)
    data = D.setups.get(symbol)
    if not data["rows"] and data["errors"]:
        return _err("no setup data could be computed", 503, errors=data["errors"],
                    as_of=data["as_of"])
    return data


# --------------------------------------------------------------- portfolio
def _pf():
    with D._pf_lock:
        if D._portfolio is None:
            D._portfolio = D.portfolio_factory()
        return D._portfolio


def _pf_call(fn: Callable[[Any], Any]):
    if not getattr(D.auth, "configured", False):
        return _err("Avanza is not configured (AVANZA_USERNAME / AVANZA_PASSWORD unset)", 503)
    try:
        return fn(_pf())
    except AvanzaUnavailable as e:
        return _err(redact(str(e)), 503)
    except ValueError as e:
        return _err(redact(str(e)), 400)
    except Exception as e:
        return _err(redact(f"portfolio request failed: {type(e).__name__}: {e}")[:300], 503)


@router.get("/api/portfolio/status")
def portfolio_status():
    # Reads flags only. Must never trigger a login.
    block = D.auth.login_block() if hasattr(D.auth, "login_block") else {
        "login_blocked_until": None, "last_login_failure": None}
    return {"configured": bool(getattr(D.auth, "configured", False)),
            "authenticated": bool(getattr(D.auth, "token", None)),
            "login_blocked_until": block["login_blocked_until"],
            "last_login_failure": block["last_login_failure"]}


@router.get("/api/portfolio/summary")
def portfolio_summary():
    return _pf_call(lambda pf: pf.account_summary())


@router.get("/api/portfolio/positions")
def portfolio_positions(account: str | None = None):
    return _pf_call(lambda pf: pf.positions(account or None))


@router.get("/api/portfolio/performance")
def portfolio_performance(period: str = "1m", account: str | None = None):
    return _pf_call(lambda pf: pf.performance(period, account or None))


@router.get("/api/portfolio/transactions")
def portfolio_transactions(account: str | None = None, from_date: str | None = None,
                           to_date: str | None = None, max_elements: int = 200):
    return _pf_call(lambda pf: pf.transactions(account or None, from_date or None,
                                               to_date or None, max_elements))


@router.get("/api/portfolio/brief")
def portfolio_brief(earnings_within_days: int = 30):
    from portfolio_mcp.brief import brief_data
    return _pf_call(lambda pf: brief_data(pf, earnings_within_days=earnings_within_days))


# ------------------------------------------------------------- disclosures
def _held_tickers() -> tuple[list[str], str | None]:
    """Held stock tickers -- only if a session ALREADY exists. Never logs in."""
    if not getattr(D.auth, "token", None):
        return [], "portfolio session not authenticated; HELD is not marked"
    try:
        pos = _pf().positions()
    except Exception as e:
        return [], redact(f"holdings unavailable: {type(e).__name__}: {e}")[:200]
    return sorted({p["yahoo_ticker"] for p in pos.get("positions", [])
                   if p.get("yahoo_ticker") and p.get("instrument_type") == "STOCK"}), None


DISCLOSURE_TYPES = sorted({*DISC.TYPES, "funds"})


def _funds(days: int):
    """13F moves of well-known funds, read from SEC EDGAR (terminal/funds13f.py).
    No Alpha Vantage key or budget involved."""
    if not F13.user_agent():
        return _err(F13.NOT_CONFIGURED_ERROR, 503, configured=False, type="funds")
    held, note = _held_tickers()
    watch = {spec[2].upper() for spec in ZP.UNIVERSE if DISC.is_us_ticker(spec[2])}
    held_set = {t.upper() for t in held if DISC.is_us_ticker(t)}
    body = F13.response(held_set, watch, days, holdings_note=note)
    if body is None:
        return _err("SEC 13F loader is not running (restart the backend)", 503, configured=True, type="funds")
    return body


@router.get("/api/disclosures")
def disclosures(type: str = "congress", days: int = Query(DISC.DEFAULT_DAYS, ge=1, le=3650)):
    if type not in DISCLOSURE_TYPES:
        return _err(f"type must be one of {DISCLOSURE_TYPES}", 400)
    if type == "funds":
        return _funds(days)
    key = DISC.api_key()
    if not key:
        return _err("ALPHAVANTAGE_API_KEY is not set", 503, configured=False, type=type)
    held, note = _held_tickers()
    watch = [spec[2] for spec in ZP.UNIVERSE]
    return DISC.build(type, held, watch, D.disclosure_fetcher_factory(key),
                      days=days, holdings_note=note)


# --------------------------------------------------------------------- kes
@router.get("/api/kes/briefing")
def kes_briefing():
    data = D.setups.get(None)
    plans_error = None
    try:
        plan_today = D.plans.logged_today()
    except Exception as e:          # must not blank the briefing -- but is reported
        plan_today, plans_error = False, f"plans store unreadable: {type(e).__name__}"
    out = KES.compose_briefing(data["rows"], data["errors"], plan_today=plan_today)
    if plans_error:
        out["plans_error"] = plans_error
    return out


# ------------------------------------------------------------------- plans
@router.get("/api/plans")
def get_plans():
    try:
        plans = D.plans.all()
    except Exception as e:
        return _err(f"plans store unreadable: {type(e).__name__}: {e}"[:300], 500)
    return {"plans": plans, "streak": PLANS.streak(plans)}


@router.post("/api/plans")
def post_plan(payload: dict = Body(...)):
    symbol = str((payload or {}).get("symbol") or "").strip()
    if symbol:
        try:                        # before any market-data lookup on it
            PLANS.check_symbol(symbol)
        except PLANS.PlanError as e:
            return _err(str(e), 400)
    price = lev_cap = None
    checked = "no price available; only take_profit/stop_loss ordering was checked"
    if symbol:
        try:
            row = D.setups.row_for(symbol)
        except Exception as e:
            row = None
            checked = (f"setups lookup failed ({type(e).__name__}); "
                       "only take_profit/stop_loss ordering was checked")
        if row:
            price, lev_cap = row.get("close"), row.get("lev_cap")
            checked = f"price {price:g} from the {row.get('bar_date')} daily bar; lev_cap from ATR14"
    try:
        clean = PLANS.validate(payload, price, lev_cap)
    except PLANS.PlanError as e:
        return _err(str(e), 400)
    clean["checked_against"] = checked
    try:
        plan = D.plans.add(clean)
        n = PLANS.streak(D.plans.all())
    except Exception as e:
        return _err(f"could not store plan: {type(e).__name__}: {e}"[:300], 500)
    return {**plan, "streak": n}
