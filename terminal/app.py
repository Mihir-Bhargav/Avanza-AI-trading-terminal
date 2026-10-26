"""
Trading terminal — FastAPI backend.

Phase 0+1 of docs/TERMINAL_PLAN.md: watchlist ranking + charts with levels
drawn, every panel carrying its own data freshness.

Run:
    python3.13 -m terminal.app
    open http://127.0.0.1:8777

Reuses rather than reimplements:
    screeners/levels.py        CPR, pivots, prior day/week, ATR, MACD
    screeners/watchlist_core   RSI, BB width, catalyst tagging
    watchlists/*.txt           the universes
"""

from __future__ import annotations

import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asyncio
import json
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# `python -m terminal.app` runs this file as __main__. Modules that later do
# `from terminal.app import AVANZA_AUTH` (terminal/ai.py) would otherwise import
# a SECOND copy of this module -- with a second AvanzaAuth and a second login.
# Alias it so there is exactly one module, one session.
if __name__ == "__main__":
    sys.modules.setdefault("terminal.app", sys.modules[__name__])


def _load_env() -> None:
    """Read .env into the environment before anything reads os.getenv().

    This existed as a documented instruction and NOT as code, which made the
    instruction wrong: AvanzaAuth reads os.getenv, nothing populated it, and
    credentials written to .env would have silently done nothing. Hand-rolled
    rather than depending on python-dotenv, so the terminal keeps working if
    that package is not installed.

    Existing environment variables always win, so a shell export can override
    the file, and nothing here is ever logged or echoed.
    """
    f = ROOT / ".env"
    if not f.exists():
        return
    import os
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if v and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k, v)


_load_env()

from screeners.levels import compute_levels, macd_state          # noqa: E402
from screeners.watchlist_core import _rsi                        # noqa: E402
from terminal import indicators as IND                           # noqa: E402
from terminal import ai as AI                                    # noqa: E402
from terminal import news as NEWS                                # noqa: E402
from terminal import strategies as STRAT                         # noqa: E402
from terminal.alerts import AlertEngine, LevelWatch, push        # noqa: E402
from terminal.feeds.avanza import AvanzaFeed                     # noqa: E402
from terminal.feeds.base import Bars, is_market_open             # noqa: E402
from terminal.feeds.stream import STREAM                         # noqa: E402
from terminal.feeds import spot as SPOT                          # noqa: E402
from terminal.feeds.yf import YFinanceFeed                       # noqa: E402

app = FastAPI(title="Terminal")
FEED = YFinanceFeed()

# One auth object shared by the feed and the API. Login is LAZY -- it happens on
# the first Avanza request, not at import, so the terminal starts instantly and
# still works when credentials are absent or Avanza is down.
from terminal.feeds.avanza import AvanzaAuth                      # noqa: E402
AVANZA_AUTH = AvanzaAuth()
AVANZA = AvanzaFeed(auth=AVANZA_AUTH)

# Quotes route through Avanza wherever it is genuinely real-time and fall back
# to yfinance otherwise. Added after yfinance stalled mid-session on 2026-08-06
# and served five-hour-old Swedish prices while Stockholm was open. FEED keeps
# the same interface, so every caller is unchanged.
from terminal.feeds.router import QuoteRouter                     # noqa: E402
_YF = FEED
FEED = QuoteRouter(_YF, AVANZA)
ALERTS = AlertEngine()

# Redesigned front end (web/, Next.js dev server on :3000). Nothing wider:
# the backend holds a broker session and must not be callable from any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# v2 API for the redesign (docs/API.md). Bound to the SAME feed/auth objects,
# so the portfolio shares this process's one Avanza session.
from terminal import api_v2 as API_V2                              # noqa: E402
API_V2.bind(feed=FEED, yf=_YF, avanza=AVANZA, auth=AVANZA_AUTH)
app.include_router(API_V2.router)
from terminal import markets as MARKETS; app.include_router(MARKETS.router)  # noqa: E402,E702  /api/markets/sectors
from terminal import insiders as INSIDERS; app.include_router(INSIDERS.router)  # noqa: E402,E702  SEC Form 4 poller (lifespan)
from terminal import funds13f as FUNDS13F; app.include_router(FUNDS13F.router)  # noqa: E402,E702  SEC 13F loader (lifespan), served by /api/disclosures?type=funds
STATIC = Path(__file__).parent / "static"
WATCHLIST_DIR = ROOT / "watchlists"


def load_watchlist(market: str) -> list[str]:
    p = WATCHLIST_DIR / f"{market}.txt"
    if not p.exists():
        return []
    return [l.split("#")[0].strip() for l in p.read_text().splitlines()
            if l.split("#")[0].strip()]


def analyse(symbol: str) -> dict | None:
    """One row of the watchlist: quote + levels + a movement score."""
    try:
        q = FEED.quote(symbol)
        b = FEED.bars(symbol, "1d", "1y")          # excludes today's forming bar
        if q is None or b is None or len(b.df) < 30:
            return None
        lv = compute_levels(b.df, symbol)
        if lv is None:
            return None
        close = b.df["Close"]
        rsi = float(_rsi(close, 14).iloc[-1])
        macd = macd_state(close)[0]

        # Distance to the levels that actually matter for a trigger.
        to_pdh = (lv.pdh / q.price - 1) * 100
        to_pdl = (lv.pdl / q.price - 1) * 100

        # Movement score: coiled CPR + near a decision level + real range.
        coil = (1 - lv.cpr_width_pctile) if lv.cpr_width_pctile == lv.cpr_width_pctile else 0.0
        prox = max(0.0, 1 - min(abs(to_pdh), abs(to_pdl)) / 2.0)
        score = 0.55 * coil + 0.45 * prox

        return {
            **q.to_dict(),
            "market_open": is_market_open(symbol),
            "score": round(score, 3),
            "rsi": round(rsi, 0),
            "macd": macd,
            "atr_pct": None if lv.atr_pct != lv.atr_pct else round(lv.atr_pct, 2),
            "max_lev": (None if not lv.atr_pct or lv.atr_pct != lv.atr_pct
                        else round(100 / (3.5 * lv.atr_pct))),
            "cpr_pctile": (None if lv.cpr_width_pctile != lv.cpr_width_pctile
                           else round(lv.cpr_width_pctile * 100)),
            "cpr_verdict": lv.cpr_verdict,
            "cpr_rel": lv.cpr_relationship,
            "to_pdh": round(to_pdh, 2),
            "to_pdl": round(to_pdl, 2),
            # Absolute levels alongside the percentages. The assistant was
            # back-deriving these from the % distances and said so; a level you
            # place a stop at should be given, not reconstructed.
            "pdh": round(float(lv.pdh), 2), "pdl": round(float(lv.pdl), 2),
            "pivot": round(float(lv.pivot), 2),
            "tc": round(float(lv.tc), 2), "bc": round(float(lv.bc), 2),
            "r1": round(float(lv.r1), 2), "s1": round(float(lv.s1), 2),
            "levels_from": str(lv.source_date),
            "levels_stale": bool(lv.is_stale),
        }
    except Exception:
        return None


@app.get("/api/markets")
def markets():
    names = sorted(p.stem for p in WATCHLIST_DIR.glob("*.txt")
                   if not p.stem.endswith("_extended"))
    return {"markets": names}


@app.get("/api/watchlist/{market}")
def watchlist(market: str, limit: int = 40):
    syms = load_watchlist(market)[:limit]
    if not syms:
        return JSONResponse({"error": f"no watchlist '{market}'"}, status_code=404)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(analyse, syms) if r]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"market": market, "count": len(rows), "rows": rows}


@app.get("/api/strategies/{symbol:path}")
def strategies(symbol: str, interval: str = "1d"):
    """Every strategy in the repo, run on one symbol. Reports the ones that do
    NOT fire too -- that was the honest answer on most days, and hiding it is
    how twelve unused strategies accumulated."""
    lb = {"1d": "1y", "1h": "3mo", "15m": "1mo", "5m": "1mo", "1m": "5d"}.get(interval, "1y")
    b = FEED.bars(symbol, interval, lb, exclude_today=(interval == "1d"))
    if b is None or len(b.df) < 25:
        return JSONResponse({"error": f"insufficient data for {symbol}"}, status_code=404)
    r = STRAT.run_all(b.df)
    r["symbol"] = symbol
    r["interval"] = interval
    return r


@app.get("/api/ai/status")
def ai_status():
    return {"claude_cli": AI.available(), "avanza": AVANZA_AUTH.status()}


@app.post("/api/ai/ask")
async def ai_ask(payload: dict):
    q = (payload.get("question") or "").strip()
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)
    syms = payload.get("symbols") or []
    if not syms:
        syms = load_watchlist(payload.get("market", "us"))[:5]
    loop = asyncio.get_running_loop()
    history = payload.get("history") if isinstance(payload.get("history"), list) else None
    return await loop.run_in_executor(
        None, lambda: AI.ask(q, syms, payload.get("market", "us"), history=history))


@app.get("/api/indicators")
def indicator_catalog():
    """Everything available. No cap on how many can be enabled at once."""
    return {"indicators": IND.catalog()}


# Avanza instruments (certificates, minis) chart as "AV:<orderbook id>". Avanza's
# resolution depends on the period asked for, so each timeframe maps to the
# shortest period that covers it and is resampled to exactly that interval.
_AV_PERIOD = {"1m": ("1d", None), "5m": ("1w", "5min"), "15m": ("1w", "15min"),
              "1h": ("1mo", "1h"), "1d": ("1y", "1D")}


def _avanza_bars(oid: str, interval: str) -> Bars | None:
    lookback, rule = _AV_PERIOD.get(interval, ("1y", "1D"))
    b = AVANZA.bars(oid, interval, lookback)
    if b is None or rule is None:
        return b
    df = (b.df.resample(rule)
          .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
          .dropna(subset=["Close"]))
    return Bars(symbol=oid, df=df, source=b.source, interval=interval) if len(df) else None


@app.get("/api/chart/{symbol:path}")
def chart(symbol: str, interval: str = "1d", lookback: str = "6mo", ind: str = ""):
    intraday = interval != "1d"
    av = symbol.upper().startswith("AV:")
    oid = symbol.split(":", 1)[1] if av else ""
    if av and not oid.isdigit():
        return JSONResponse({"error": "Avanza instruments chart as AV:<orderbook id>"}, status_code=400)
    b = _avanza_bars(oid, interval) if av else FEED.bars(symbol, interval, lookback, exclude_today=not intraday)
    if b is None:
        return JSONResponse({"error": f"no data for {symbol}"}, status_code=404)
    q = AVANZA.quote(oid) if av else FEED.quote(symbol)
    daily = _avanza_bars(oid, "1d") if av else FEED.bars(symbol, "1d", "1y")
    lv = compute_levels(daily.df, symbol) if daily is not None else None

    levels = []
    if lv is not None:
        for label, val, color in [
            ("PDH", lv.pdh, "#ef5350"), ("PDL", lv.pdl, "#26a69a"),
            ("Pivot", lv.pivot, "#ffffff"), ("TC", lv.tc, "#ff9800"),
            ("BC", lv.bc, "#ff9800"), ("R1", lv.r1, "#ef5350"),
            ("S1", lv.s1, "#26a69a"),
        ]:
            if val == val:
                levels.append({"label": label, "price": round(float(val), 2), "color": color})

    names = [x for x in ind.split(",") if x]
    series = []
    if names:
        # Indicators need warmup the display window may not contain: SMA200 on
        # a 6-month chart has zero valid points. Compute on a longer frame,
        # then trim to what is actually shown.
        warm = {"1d": "3y", "1h": "6mo", "15m": "1mo", "5m": "1mo", "1m": "5d"}.get(interval, lookback)
        # Avanza serves one fixed window per period, so an instrument has no wider frame.
        wide = b if av else (FEED.bars(symbol, interval, warm, exclude_today=not intraday) or b)
        series = IND.build(wide.df, names)
        first = b.to_candles()[0]["time"] if b.to_candles() else 0
        for sr in series:
            sr["data"] = [pt for pt in sr["data"] if pt["time"] >= first]

    return {
        "symbol": symbol, "interval": interval,
        "candles": b.to_candles(),
        "series": series,
        "levels": levels,
        "quote": q.to_dict() if q else None,
        "levels_from": str(lv.source_date) if lv else None,
        "levels_stale": bool(lv.is_stale) if lv else False,
        "cpr_verdict": lv.cpr_verdict if lv else "",
        # Avanza certificates and minis trade on Stockholm hours.
        "market_open": is_market_open("^OMX" if av else symbol),
    }


@app.get("/api/avanza/find")
def avanza_find(q: str, max_spread: float | None = None, limit: int = 60):
    """Every tradeable certificate/mini for an underlying, ranked by spread.

    Spread is the entire cost on Avanza Markets (commission-free >=1,000 SEK),
    and it ranges from 0.004% to millions of percent on the SAME underlying --
    BULL GULD X20 VT12 quotes 10,000,000% wide, measured 2026-08-05. No cap:
    the sort puts the cheapest first, and a dead line is worth seeing rather
    than silently dropping.
    """
    rows = AVANZA.find_instruments(q, limit=limit, max_spread_pct=max_spread)
    return {"query": q, "count": len(rows), "rows": rows}


@app.get("/api/feed/stats")
def feed_stats():
    """Which source is actually serving quotes, and is the stream alive."""
    return {"router": FEED.stats() if hasattr(FEED, "stats") else {},
            "stream": STREAM.status(),
            "avanza_authenticated": AVANZA.authenticated}


@app.get("/api/spot/{metal}")
def spot_price(metal: str):
    """Real-time SPOT, derived from a physically-backed Avanza ETC.

    Exists because GC=F is FUTURES and 11 minutes delayed, Yahoo's live socket
    carries no futures at all, and futures sit ~1.4% above spot on carry. That
    gap is contango, not lag, so the fix is a different instrument rather than a
    faster feed.
    """
    # _YF, not FEED. FEED is the router, and its _spot_quote intercepts GC=F and
    # returns Avanza spot -- so annotate()'s "futures" leg was handed the spot
    # price and the basis collapsed to exactly 0.00, which is impossible in
    # contango. The microsecond-old futures_age_min was the tell.
    d = SPOT.annotate(metal, AVANZA, _YF) or SPOT.spot(metal, AVANZA, _YF)
    if not d:
        return JSONResponse(
            {"error": f"no real-time spot for {metal}",
             "reason": "needs an authenticated Avanza session and a mapped ETC"},
            status_code=404)
    return d


@app.get("/api/avanza/chart/{oid}")
def avanza_chart(oid: str, period: str = "one_year"):
    """The instrument's OWN price history.

    Unauthenticated this was not worth drawing -- Avanza recorded a bar only
    when a retail trade printed, so a liquid mini showed 16 bars in a month and
    7 of them closed outside their own high/low. With a session it is a proper
    series: BULL GULD X3 returns 240 bars over a year with zero invalid OHLC.

    The bars are daily CLOSES though (open=high=low=close), so this reports
    `is_line` and the front end draws a line. Rendering flat candles would imply
    an intraday range that was never recorded.
    """
    d = AVANZA._get(f"/_api/price-chart/stock/{oid}?timePeriod={period}")
    if not d or not d.get("ohlc"):
        return JSONResponse({"error": f"no price history for {oid}"}, status_code=404)

    rows, flat = [], True
    for b in d["ohlc"]:
        c = b.get("close")
        if c is None:
            continue
        o = b.get("open", c); hi = b.get("high", c); lo = b.get("low", c)
        if not (o == hi == lo == c):
            flat = False
        rows.append({"time": int(b["timestamp"] / 1000), "open": o,
                     "high": hi, "low": lo, "close": c})
    if not rows:
        return JSONResponse({"error": f"no usable bars for {oid}"}, status_code=404)
    rows.sort(key=lambda r: r["time"])

    meta = AVANZA.instrument(oid) or {}
    return {
        "orderbook_id": oid, "name": meta.get("name", oid),
        "candles": rows,
        "line": [{"time": r["time"], "value": r["close"]} for r in rows],
        "is_line": flat,
        "currency": meta.get("currency", ""),
        "leverage": meta.get("leverage"), "barrier": meta.get("barrier"),
        "underlying": meta.get("underlying"),
        "is_realtime": meta.get("is_realtime"),
        "authenticated": AVANZA.authenticated,
        "prev_close": d.get("previousClosingPrice"),
    }


@app.get("/api/avanza/status")
def avanza_status():  # noqa: D401
    """Which of the three credentials are present, and is a session live.

    Reports presence only -- never a value, never a prefix. The point is to make
    a typo diagnosable without the response itself becoming a place a credential
    can leak into a log or a screenshot.
    """
    import os

    a = AVANZA_AUTH
    return {
        **a.status(),
        "feed_authenticated": AVANZA.authenticated,
        "env_seen": {k: bool(os.getenv(k)) for k in
                     ("AVANZA_USERNAME", "AVANZA_PASSWORD", "AVANZA_TOTP_SECRET")},
        "env_file": (ROOT / ".env").exists(),
    }


@app.post("/api/avanza/login")
async def avanza_login():
    """Authenticate and report the outcome, without echoing any credential."""
    a = AVANZA_AUTH
    if not a.configured:
        return JSONResponse(
            {"ok": False, "error": "AVANZA_USERNAME and AVANZA_PASSWORD are not set",
             "hint": "put them in .env (gitignored), then restart the terminal"},
            status_code=400)
    loop = asyncio.get_running_loop()
    ok, reason = await loop.run_in_executor(None, a.ensure)
    if not ok:
        return JSONResponse({"ok": False, "error": reason, "has_totp": a.has_totp},
                            status_code=401)
    AVANZA_SESSION["auth"] = a
    return {"ok": True, "authenticated": True, "detail": reason,
            "unlocks": ["real-time quotes", "order book depth", "positions"]}


# Holds the live session. Module-level and deliberately not persisted anywhere:
# the token dies with the process rather than landing on disk.
AVANZA_SESSION: dict = {}


@app.get("/api/avanza/instrument/{oid}")
def avanza_instrument(oid: str):
    """One instrument in full, plus the underlying it should be charted against.

    A mini future's OWN chart is not usable -- Avanza records a bar only when a
    retail trade prints, so a liquid S&P mini showed 16 bars in a month and 7 of
    them closed outside their own high/low. The instrument is linear in its
    underlying, so the underlying is charted and the KNOCKOUT BARRIER is drawn
    on it. Distance to that barrier is the number that decides the position.
    """
    d = AVANZA.instrument(oid)
    if not d:
        return JSONResponse({"error": f"no instrument {oid}"}, status_code=404)

    d["session_authenticated"] = AVANZA.authenticated
    d["underlying_price"] = None
    d["barrier_distance_pct"] = None
    d["atrs_to_barrier"] = None
    u = d.get("underlying")
    if u:
        q = FEED.quote(u)
        if q:
            d["underlying_price"] = q.price
            d["underlying_freshness"] = q.freshness
            d["underlying_age_min"] = q.age_min
            # `is not None`, NOT `x == x`. The self-comparison is a NaN idiom,
            # and instrument() now returns None for absent fields -- None == None
            # is True, so this branch ran on a certificate with no barrier and
            # died on `price - None`. Certificates legitimately have no knockout.
            if d["barrier"] is not None and q.price:
                # Signed so the sign always means the same thing: how far the
                # underlying must travel AGAINST the position before knockout.
                d["barrier_distance_pct"] = round(abs(q.price - d["barrier"]) / q.price * 100, 2)
                b = FEED.bars(u, "1d", "6mo")
                if b is not None and len(b.df) > 15:
                    lv = compute_levels(b.df, u)
                    if lv and lv.atr_pct == lv.atr_pct and lv.atr_pct > 0:
                        d["atrs_to_barrier"] = round(d["barrier_distance_pct"] / lv.atr_pct, 1)
    return d


@app.get("/api/avanza/search")
def avanza_search(q: str, limit: int = 20):
    return {"query": q, "rows": AVANZA.search(q, limit=limit)}


@app.get("/api/alerts")
def get_alerts():
    return {"watches": [w.__dict__ for w in ALERTS.watches],
            "ntfy": bool(__import__("terminal.alerts", fromlist=["ntfy_topic"]).ntfy_topic())}


@app.post("/api/alerts")
async def set_alerts(payload: dict):
    ALERTS.set_watches([LevelWatch(**w) for w in payload.get("watches", [])])
    return {"ok": True, "count": len(ALERTS.watches)}


@app.post("/api/alerts/test")
def test_alert():
    ok = push("Terminal", "Test alert — ntfy is wired up correctly.", tags="white_check_mark")
    return {"sent": ok}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    """Stream quotes for whatever the client is watching, and fire level alerts.

    TWO SPEEDS, deliberately:

      * every ~2s the live socket cache is read and pushed. This costs NOTHING
        -- Yahoo pushes those ticks to us, nothing is requested -- so it can be
        fast without any risk to the feed.
      * every ~90s the REST path fills in whatever the stream does not cover
        (closed markets, unsupported symbols), through the TTL cache.

    Polling harder is what broke this before: 40 symbols on a 5s timer earned a
    wall of YFRateLimitError and blanked every panel. The fix was not a gentler
    poll, it was to stop polling for the symbols that can be streamed.
    """
    await sock.accept()
    symbols: list[str] = []
    rest_at = 0.0
    rest_cache: dict[str, dict] = {}
    try:
        while True:
            try:
                raw = await asyncio.wait_for(sock.receive_text(), timeout=0.05)
                msg = json.loads(raw)
                if "symbols" in msg:
                    new = list(dict.fromkeys(msg["symbols"]))[:60]
                    if new != symbols:
                        symbols = new
                        STREAM.set_symbols(symbols)
                        rest_at = 0.0          # refill immediately for new names
            except asyncio.TimeoutError:
                pass
            except (json.JSONDecodeError, KeyError):
                pass

            if symbols:
                now = time.time()
                if now - rest_at > 90:
                    loop = asyncio.get_running_loop()
                    missing = [s for s in symbols if not STREAM.quote(s)]
                    if missing:
                        filled = await loop.run_in_executor(None, _quote_batch, missing[:40])
                        rest_cache.update({q["symbol"]: q for q in filled})
                    rest_at = now

                quotes, fired = [], []
                for s in symbols:
                    live = STREAM.quote(s)
                    if live:
                        live["market_open"] = is_market_open(s)
                        quotes.append(live)
                    elif s in rest_cache:
                        quotes.append(rest_cache[s])
                for qd in quotes:
                    fired += ALERTS.check(qd["symbol"], qd["price"], qd["freshness"])
                await sock.send_text(json.dumps(
                    {"quotes": quotes, "alerts": fired, "stream": STREAM.status()}))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
    except Exception:
        return


def _quote_batch(symbols: list[str]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        out = []
        for q in pool.map(FEED.quote, symbols):
            if q:
                d = q.to_dict()
                d["market_open"] = is_market_open(q.symbol)
                out.append(d)
        return out


# ----------------------------------------------------------------------- news

@app.get("/api/news/market")
def news_market(limit: int = 30, market: str = "us"):
    """Region-aware wire. Google News carries the regional query; the US desks
    are mixed in only for the US tab, because a CNBC front page next to an
    OMXS30 position is noise dressed as coverage."""
    items = NEWS.market_news(limit=limit, market=market)
    n_feeds = 1 + (len(NEWS.US_DESKS) if market == "us" else 0)
    return {"market": market, "items": items, "feeds": n_feeds,
            "query": NEWS.MARKET_QUERIES.get(market, NEWS.MARKET_QUERIES["us"])}


@app.get("/api/news/ticker/{symbol:path}")
def news_ticker(symbol: str, limit: int = 12, market: str = "us", rank: str = "recent"):
    return {"symbol": symbol,
            "items": NEWS.ticker_news(symbol, limit=limit, market=market, rank=rank)}


@app.get("/api/news/bot")
def news_bot_state():
    return {"status": NEWS.BOT.status(), "hits": NEWS.BOT.hits()}


@app.post("/api/news/bot/scan")
async def news_bot_scan(payload: dict | None = None):
    """Pair unusual movers with the headlines that landed next to them.

    Moves are measured in ATRs, not percent: 4% is enormous for a utility and a
    normal morning for AMD, so a percent threshold fires constantly on the
    volatile names and never on the ones where it would mean something.
    """
    payload = payload or {}
    mkt = payload.get("market", "us")
    syms = load_watchlist(mkt)[:40]
    if not syms:
        return JSONResponse({"error": f"no watchlist '{mkt}'"}, status_code=404)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(analyse, syms) if r]
    hits = await loop.run_in_executor(None, lambda: NEWS.BOT.scan(rows, market=mkt))
    return {"scanned": len(rows), "hits": hits, "status": NEWS.BOT.status()}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"terminal -> http://{a.host}:{a.port}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
