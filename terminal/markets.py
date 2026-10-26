"""
Markets page sector overview (`GET /api/markets/sectors?index=`).

The heatmap itself is TradingView's embedded widget (web/, MarketHeatmap). This
module supplies the part under it that TradingView does not: per sector, the
day's move, the one headline most likely to explain it, and each leader's
intraday sparkline, last price and % change.

HOW IT IS BUILT
  - Membership is a curated SNAPSHOT (watchlists/sector_leaders.json, dated), the
    ~10 largest names per GICS sector, not a live index feed.
  - Prices come from TWO batched yfinance.download calls for the whole index
    (5-minute bars for sparklines/last, daily bars for the previous close),
    never one request per ticker.
  - Sector % change: the SPDR sector ETF (XLK, XLF, ...) for US indexes, which is
    the sector's market-wide move. OMXS30 has no sector ETFs, so there it is the
    equal-weighted average of the listed members, and the response says so
    (`change_basis`).
  - Headline: only for each sector's biggest |mover| (one news lookup per
    sector, run concurrently), via terminal/news.py ticker_news.

HONESTY
  - Every quote carries its own freshness/age from the timestamp of its last
    5-minute bar (the bar's START, so the age is never understated).
  - A failed batch is an error (MarketsError -> HTTP 503), never an empty list
    that reads as "quiet day". Individual symbols Yahoo returned nothing for are
    listed per member (`error`) and in the top-level `errors`.
  - Change vs previous close uses the daily bar, falling back to the prior
    session's last 5-minute close only when the daily batch lacks the symbol;
    `prev_close_source` says which was used.
"""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from terminal.feeds.base import REALTIME_CUTOFF_MIN, STALE_CUTOFF_MIN, is_market_open

ROOT = Path(__file__).resolve().parent.parent
LEADERS_FILE = ROOT / "watchlists" / "sector_leaders.json"

CACHE_TTL_S = 60
HEADLINE_TTL_S = 300          # news lookups are the slow part; reuse for 5 min
SPARK_POINTS = 40
BAR_MIN = 5

_TZ = {"us": "America/New_York", "sweden": "Europe/Stockholm"}

# yfinance keeps module-level state inside download(); two concurrent calls can
# mix each other's results. Serialise them.
_DL_LOCK = threading.Lock()


class MarketsError(Exception):
    """The data needed for the page could not be fetched at all."""


# ------------------------------------------------------------------ config
def load_leaders(path: Path = LEADERS_FILE) -> dict:
    return json.loads(path.read_text())


def index_names(cfg: dict) -> list[str]:
    return list(cfg["indexes"].keys())


# ------------------------------------------------------------------ fetch
def yf_download(symbols: list[str], period: str, interval: str) -> pd.DataFrame:
    """ONE batched request for every symbol. Returns the Close columns only."""
    import yfinance as yf
    with _DL_LOCK:
        df = yf.download(symbols, period=period, interval=interval,
                         group_by="column", auto_adjust=False, prepost=False,
                         threads=True, progress=False, multi_level_index=True)
    if df is None or df.empty:
        raise MarketsError(f"yfinance returned no {interval} data for {len(symbols)} symbols")
    close = df["Close"] if "Close" in df.columns.get_level_values(0) else None
    if close is None:
        raise MarketsError(f"yfinance {interval} response had no Close column")
    if isinstance(close, pd.Series):          # single symbol
        close = close.to_frame(symbols[0])
    return close


_GENERIC = {"inc", "corp", "co", "company", "group", "holdings", "the", "and", "bank",
            "energy", "financial", "technologies", "international", "industries"}


def names_company(title: str, symbol: str, name: str) -> bool:
    """Does a headline actually name this company?

    ticker_news queries `"Name" OR TICKER`, and short tickers collide: on
    2026-09-24 MPC (Marathon Petroleum) returned a Bank of Ghana "MPC press
    briefing". So a headline counts only if it carries a distinctive word of
    the company name, or the ticker in a market context ("(MPC)", "NYSE:MPC",
    "MPC stock"/"MPC shares").
    """
    import re
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", name)
    min_len = 2 if len(tokens) == 1 else 3          # "3M" alone is distinctive
    words = [w for w in tokens if len(w) >= min_len and re.search("[A-Za-z]", w)
             and w.lower().strip(".") not in _GENERIC]
    for w in words:
        if re.search(rf"\b{re.escape(w)}", title, re.IGNORECASE):
            return True
    bare = re.escape(symbol.split(".")[0].replace("-", "."))
    return bool(re.search(rf"\({bare}\)|:\s?{bare}\b|\b{bare}\s+(stock|shares)\b", title))


def _news_headline(symbol: str, name: str, market: str) -> dict | None:
    from terminal import news as NEWS
    items = NEWS.ticker_news(symbol, name=name, limit=8, rank="explain", market=market)
    items = [i for i in items if names_company(i.get("title", ""), symbol, name)]
    if not items:
        return None
    it = items[0]
    url = it.get("url") or ""
    return {"title": it["title"], "source": it.get("source") or "",
            "age_min": it.get("age_min"), "url": url if url.startswith("http") else None,
            "symbol": symbol}


# ------------------------------------------------------------------ maths
def downsample(values: list[float], n: int = SPARK_POINTS) -> list[float]:
    """Evenly spaced picks that always keep the first and last point."""
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(vals) <= n:
        return vals
    if n <= 1:
        return vals[-1:]
    step = (len(vals) - 1) / (n - 1)
    return [vals[round(i * step)] for i in range(n)]


def _r(x: float | None, nd: int = 4) -> float | None:
    if x is None or x != x:
        return None
    return round(float(x), nd)


def _local_dates(idx: pd.DatetimeIndex, tz: str, naive_is_local: bool = False) -> list:
    """Exchange-local calendar dates. Intraday bars are tz-aware (UTC); daily
    bars can come back tz-naive, already meaning the exchange date."""
    if idx.tz is None:
        if naive_is_local:
            return [d.date() for d in idx]
        idx = idx.tz_localize("UTC")
    return [d.date() for d in idx.tz_convert(tz)]


def freshness(symbol: str, age_min: float | None) -> str:
    """Same rules as terminal/feeds/base.Quote.freshness, with an injectable age."""
    if age_min is None or age_min != age_min:
        return "unknown"
    if age_min < REALTIME_CUTOFF_MIN:
        return "live"
    if age_min < STALE_CUTOFF_MIN:
        return "delayed"
    return "stale" if is_market_open(symbol) else "closed"


def quote_from_bars(symbol: str, intraday: pd.Series | None, daily: pd.Series | None,
                    tz: str, now: datetime | None = None) -> dict:
    """last, change vs previous close, sparkline and freshness for one symbol."""
    s = intraday.dropna() if intraday is not None else pd.Series(dtype=float)
    if s.empty:
        return {"symbol": symbol, "last": None, "change_pct": None, "spark": [],
                "freshness": "unknown", "age_min": None, "ts": None,
                "prev_close_source": None, "error": "no intraday bars returned"}

    dates = _local_dates(s.index, tz)
    session = dates[-1]
    today_mask = [d == session for d in dates]
    sess = s[today_mask]
    last = float(sess.iloc[-1])

    prev, prev_src = None, None
    if daily is not None:
        d = daily.dropna()
        if not d.empty:
            dd = _local_dates(d.index, tz, naive_is_local=True) \
                if isinstance(d.index, pd.DatetimeIndex) else []
            before = [v for v, day in zip(d.values, dd) if day < session]
            if before:
                prev, prev_src = float(before[-1]), "daily"
    if prev is None:
        before = s[[d < session for d in dates]]
        if not before.empty:
            prev, prev_src = float(before.iloc[-1]), "intraday"

    ts = s.index[-1].to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 60.0
    fresh = freshness(symbol, age)

    return {"symbol": symbol, "last": _r(last),
            "change_pct": _r((last / prev - 1) * 100, 3) if prev else None,
            "spark": [_r(v) for v in downsample(list(sess.values))],
            "freshness": fresh, "age_min": _r(age, 1),
            "ts": ts.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "prev_close_source": prev_src,
            **({"error": "no previous close"} if prev is None else {})}


# ------------------------------------------------------------------ build
Downloader = Callable[[list[str], str, str], pd.DataFrame]
Headliner = Callable[[str, str, str], "dict | None"]


def build(index: str, *, cfg: dict | None = None, download: Downloader = yf_download,
          headline: Headliner = _news_headline, now: datetime | None = None) -> dict:
    cfg = cfg or load_leaders()
    spec = cfg["indexes"].get(index)
    if spec is None:
        raise ValueError(f"unknown index {index!r}; valid: {index_names(cfg)}")
    market = spec.get("market", "us")
    tz = _TZ.get(market, "America/New_York")
    use_etf = spec.get("sector_change") == "etf"
    etfs: dict[str, str] = cfg.get("sector_etfs", {}) if use_etf else {}

    names = {sym: nm for members in spec["sectors"].values() for sym, nm in members}
    symbols = list(dict.fromkeys(list(names) + [etfs[s] for s in spec["sectors"] if s in etfs]))

    # The two batches run concurrently; each is one request for all symbols.
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f5 = pool.submit(download, symbols, "5d", f"{BAR_MIN}m")
            fd = pool.submit(download, symbols, "10d", "1d")
            intraday = f5.result()
            try:
                daily = fd.result()
                daily_err = None
            except Exception as e:           # prices still usable via intraday fallback
                daily, daily_err = None, f"daily batch failed: {type(e).__name__}: {e}"[:200]
    except MarketsError:
        raise
    except Exception as e:
        raise MarketsError(f"intraday batch failed: {type(e).__name__}: {e}"[:300]) from e

    def col(frame: pd.DataFrame | None, sym: str) -> pd.Series | None:
        if frame is None or sym not in frame.columns:
            return None
        return frame[sym]

    quotes = {sym: quote_from_bars(sym, col(intraday, sym), col(daily, sym), tz, now)
              for sym in symbols}
    priced = [q for q in quotes.values() if q["last"] is not None]
    if not priced:
        raise MarketsError(f"yfinance returned no usable prices for any of {len(symbols)} symbols")

    sectors = []
    for sector, members in spec["sectors"].items():
        rows = []
        for sym, nm in members:
            q = dict(quotes[sym])
            q["name"] = nm
            rows.append(q)
        moves = [m["change_pct"] for m in rows if m["change_pct"] is not None]
        avg = _r(sum(moves) / len(moves), 3) if moves else None
        etf = etfs.get(sector)
        eq = quotes.get(etf) if etf else None
        if etf:
            change, basis = (eq["change_pct"] if eq else None), "etf"
        else:
            change, basis = avg, "members_avg"
        movers = [m for m in rows if m["change_pct"] is not None]
        top = max(movers, key=lambda m: abs(m["change_pct"])) if movers else None
        sectors.append({
            "sector": sector, "etf": etf, "change_pct": change, "change_basis": basis,
            "members_avg_pct": avg,
            "etf_quote": ({k: eq[k] for k in ("last", "change_pct", "freshness", "age_min")}
                          if eq else None),
            "top_mover": top["symbol"] if top else None,
            "headline": None, "headline_error": None,
            "members": rows,
        })

    # Headlines: one lookup per sector (its biggest mover), concurrently.
    def fetch(sec: dict):
        top = sec["top_mover"]
        if not top:
            return
        try:
            sec["headline"] = headline(top, next(m["name"] for m in sec["members"]
                                                 if m["symbol"] == top), market)
        except Exception as e:
            sec["headline_error"] = f"{type(e).__name__}: {e}"[:160]

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(sectors)))) as pool:
        list(pool.map(fetch, sectors))

    sectors.sort(key=lambda s: -(s["change_pct"] if s["change_pct"] is not None else -1e9))

    errors = [f"{sym}: {q['error']}" for sym, q in quotes.items() if q.get("error")]
    if daily_err:
        errors.insert(0, daily_err)
    return {
        "as_of": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds"),
        "index": index, "label": spec.get("label", index), "market": market,
        "membership_as_of": cfg.get("as_of"),
        "sources": {"prices": f"yfinance {BAR_MIN}m + 1d (batched)",
                    "headlines": "terminal/news.py ticker_news (Google News + Yahoo)"},
        "errors": errors,
        "sectors": sectors,
    }


# ------------------------------------------------------------------ service
class _TTLCache:
    def __init__(self, ttl: float):
        self.ttl, self._d, self._lock = ttl, {}, threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        return None

    def put(self, key, val):
        with self._lock:
            self._d[key] = (time.time(), val)


class SectorService:
    """Caches whole responses (60 s) and headlines per symbol (5 min).

    Failures are never cached: the next request retries."""

    def __init__(self, download: Downloader = yf_download, headline: Headliner = _news_headline,
                 ttl: float = CACHE_TTL_S, headline_ttl: float = HEADLINE_TTL_S,
                 cfg_loader: Callable[[], dict] = load_leaders):
        self.download, self._headline = download, headline
        self.cache, self.news_cache = _TTLCache(ttl), _TTLCache(headline_ttl)
        self.cfg_loader = cfg_loader
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _cached_headline(self, symbol: str, name: str, market: str):
        hit = self.news_cache.get(symbol)
        if hit is not None:
            return hit[0]
        h = self._headline(symbol, name, market)
        self.news_cache.put(symbol, (h,))
        return h

    def get(self, index: str) -> dict:
        hit = self.cache.get(index)
        if hit is not None:
            return hit
        with self._locks_guard:
            lock = self._locks.setdefault(index, threading.Lock())
        with lock:                      # one build per index at a time, no stampede
            hit = self.cache.get(index)
            if hit is not None:
                return hit
            data = build(index, cfg=self.cfg_loader(), download=self.download,
                         headline=self._cached_headline)
            self.cache.put(index, data)
            return data


SERVICE = SectorService()
router = APIRouter()


@router.get("/api/markets/sectors")
def sectors(index: str = Query("sp500")):
    try:
        cfg = SERVICE.cfg_loader()
    except Exception as e:
        return JSONResponse({"error": f"sector membership file unreadable: {type(e).__name__}: {e}"[:300]},
                            status_code=503)
    if index not in cfg.get("indexes", {}):
        return JSONResponse({"error": f"unknown index {index!r}; valid: {index_names(cfg)}"},
                            status_code=400)
    try:
        return SERVICE.get(index)
    except MarketsError as e:
        return JSONResponse({"error": str(e), "index": index}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": f"sector overview failed: {type(e).__name__}: {e}"[:300],
                             "index": index}, status_code=503)
