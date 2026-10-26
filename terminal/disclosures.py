"""
Public trade disclosures (`/api/disclosures`) from the Alpha Vantage REST API.

`type=funds` (13F) is NOT served from here any more: since 2026-09-24 it reads
well-known funds' 13F-HR filings straight from SEC EDGAR (terminal/funds13f.py),
so the whole Alpha Vantage budget goes to Congress (and legacy insiders).

Functions and fields verified 2026-09-24 against
https://www.alphavantage.co/documentation/ and the documented demo responses:

  CONGRESS_TRADES        ?symbol=  -> {"symbol", "trades": [{chamber, politician,
                         politician_canonical, party, state, transaction_type
                         (BUY|SELL|OTHER), transaction_date, filed_date,
                         notification_date, amount_min, amount_max, owner_code
                         (SELF|SPOUSE|JOINT|DEPENDENT_CHILD|OTHER), ...}]}
  INSIDER_TRANSACTIONS   ?symbol=&from=YYYY-MM-DD -> {"data": [{transaction_date,
                         ticker, executive, executive_title, security_type,
                         acquisition_or_disposal (A|D), shares, share_price}]}
                         NOTE: no filing date is published -> filed/lag are null.

Throttling/errors come back as HTTP 200 with a single "Information", "Note" or
"Error Message" key. Those are detected, never cached, and the symbol is listed
in `skipped` so the response says it is partial.

Free tier is 25 requests/day, so every good response is cached on disk under
data/cache/alphavantage/ keyed by function + symbol + date, a request makes at
most MAX_LIVE_FETCHES network calls, and a per-day ledger
(_budget_YYYY-MM-DD.json next to the cache) stops live calls at DAILY_LIMIT
across all requests and tabs. The legacy `insiders` type gets at most
FUNCTION_DAILY_CAP of it so Congress, the primary use, keeps the rest (the
Insiders tab itself reads SEC Form 4, terminal/insiders.py). A rate-limit answer from Alpha
Vantage marks the day exhausted, so a throttled key is not hammered.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "alphavantage"
BASE_URL = "https://www.alphavantage.co/query"
MAX_LIVE_FETCHES = 10
DAILY_LIMIT = 25              # Alpha Vantage free tier; ALPHAVANTAGE_DAILY_LIMIT overrides
FUNCTION_DAILY_CAP = {"INSIDER_TRANSACTIONS": 4}
DEFAULT_DAYS = 180            # rows older than this (by filed, else traded) are dropped
MOST_BOUGHT_DAYS = 30
MAX_ROWS_PER_SYMBOL = 200     # funds/insiders can return thousands per symbol

TYPES = {
    "congress": {"function": "CONGRESS_TRADES",
                 "rule": "STOCK Act · filed within 45 days",
                 "source": "Alpha Vantage CONGRESS_TRADES (STOCK Act periodic transaction reports)"},
    "insiders": {"function": "INSIDER_TRANSACTIONS",
                 "rule": "SEC Form 4 · within 2 business days",
                 "source": "Alpha Vantage INSIDER_TRANSACTIONS (SEC Form 4)"},
}


class UpstreamError(RuntimeError):
    pass


# --------------------------------------------------------------------- utils
def _d(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _f(s) -> float | None:
    if s in (None, ""):
        return None
    try:
        return float(str(s).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def lag_days(filed: str | None, traded: str | None) -> int | None:
    a, b = _d(filed), _d(traded)
    return (a - b).days if a and b else None


def _money(x: float | None) -> str:
    if x is None:
        return "?"
    if x >= 1_000_000:
        return f"${x / 1_000_000:.1f}M".replace(".0M", "M")
    if x >= 1_000:
        return f"${round(x / 1_000):,}K"
    return f"${x:,.0f}"


def amount_label(lo: float | None, hi: float | None) -> str | None:
    if lo is None and hi is None:
        return None
    if hi is None or lo == hi:
        return _money(lo)
    return f"{_money(lo)}–{_money(hi)}"


def _side(raw: str | None) -> str | None:
    t = (raw or "").upper()
    if t in ("BUY", "A", "PURCHASE", "INCREASED", "INITIATED") or "PURCHASE" in t:
        return "buy"
    if t in ("SELL", "D", "SALE", "DECREASED", "SOLD OUT") or "SALE" in t:
        return "sell"
    if t == "UNCHANGED":
        return "hold"
    return "other" if t else None


def av_error(payload) -> str | None:
    """Alpha Vantage signals errors and throttling with HTTP 200."""
    if not isinstance(payload, dict):
        return "unexpected response shape"
    for k in ("Error Message", "Information", "Note"):
        if k in payload:
            return f"{k}: {str(payload[k])[:160]}"
    return None


# -------------------------------------------------------------- normalisers
def _row(**kw) -> dict:
    base = {"filed": None, "traded": None, "lag_days": None, "who": None,
            "chamber": None, "party": None, "owner": None, "role": None,
            "symbol": None, "side": None, "amount_min": None, "amount_max": None,
            "amount_label": None, "yours": None}
    base.update(kw)
    base["lag_days"] = lag_days(base["filed"], base["traded"])
    return base


def normalise_congress(payload: dict, symbol: str) -> list[dict]:
    out = []
    for t in payload.get("trades", []) or []:
        lo, hi = _f(t.get("amount_min")), _f(t.get("amount_max"))
        out.append(_row(
            filed=t.get("filed_date") or t.get("notification_date"),
            traded=t.get("transaction_date"),
            who=t.get("politician_canonical") or t.get("politician"),
            chamber=(t.get("chamber") or "").title() or None,
            party=t.get("party"),
            owner=(t.get("owner_code") or "").lower() or None,
            symbol=(t.get("symbol") or symbol).upper(),
            side=_side(t.get("transaction_type")),
            amount_min=lo, amount_max=hi, amount_label=amount_label(lo, hi)))
    return out


def normalise_insiders(payload: dict, symbol: str) -> list[dict]:
    out = []
    for t in payload.get("data", []) or []:
        sh, px = _f(t.get("shares")), _f(t.get("share_price"))
        val = sh * px if sh is not None and px else None
        lbl = amount_label(val, val)
        if sh is not None:
            lbl = f"{sh:,.0f} sh" + (f" · {lbl}" if val is not None else "")
        out.append(_row(
            filed=None,                      # not published by the API
            traded=t.get("transaction_date"),
            who=t.get("executive"), role=t.get("executive_title"),
            security=t.get("security_type"),
            symbol=(t.get("ticker") or symbol).upper(),
            side=_side(t.get("acquisition_or_disposal")),
            amount_min=val, amount_max=val, amount_label=lbl))
    return out


NORMALISE: dict[str, Callable[[dict, str], list[dict]]] = {
    "congress": normalise_congress, "insiders": normalise_insiders}


# ----------------------------------------------------------------- fetching
def http_get(function: str, symbol: str, api_key: str) -> dict:
    params = {"function": function, "symbol": symbol, "apikey": api_key}
    if function == "INSIDER_TRANSACTIONS":
        params["from"] = (date.today() - timedelta(days=DEFAULT_DAYS)).isoformat()
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "terminal"}),
                                    timeout=20) as r:
            return json.load(r)
    except Exception as e:
        # Never include the URL: it carries the API key.
        raise UpstreamError(f"{type(e).__name__}" + (f" HTTP {e.code}" if hasattr(e, "code") else "")) from None


def daily_limit() -> int:
    try:
        return max(0, int(os.getenv("ALPHAVANTAGE_DAILY_LIMIT") or DAILY_LIMIT))
    except ValueError:
        return DAILY_LIMIT


def _is_rate_limit(err: str) -> bool:
    e = err.lower()
    return "rate limit" in e or "requests per day" in e or "per day" in e or "premium" in e


class Budget:
    """Per-day ledger of live Alpha Vantage calls, shared by every request."""

    def __init__(self, cache_dir: Path, limit: int | None = None, today: Callable[[], date] = date.today):
        self.cache_dir, self.today = cache_dir, today
        self.limit = daily_limit() if limit is None else limit

    def _path(self) -> Path:
        return self.cache_dir / f"_budget_{self.today().isoformat()}.json"

    def state(self) -> dict:
        p = self._path()
        try:
            s = json.loads(p.read_text()) if p.exists() else {}
        except ValueError:
            s = {}                           # corrupt ledger: counted from zero, see `note`
            s["note"] = "ledger was unreadable and restarted"
        s.setdefault("used", 0)
        s.setdefault("by_function", {})
        s.setdefault("exhausted", None)
        return s

    def _save(self, s: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(s))
        tmp.replace(self._path())

    def refuse(self, function: str) -> str | None:
        s = self.state()
        if s["exhausted"]:
            return f"Alpha Vantage rate limit hit earlier today ({s['exhausted']}); resets tomorrow"
        if s["used"] >= self.limit:
            return f"daily Alpha Vantage budget used ({s['used']}/{self.limit}); resets tomorrow"
        cap = FUNCTION_DAILY_CAP.get(function)
        if cap is not None and s["by_function"].get(function, 0) >= cap:
            return f"daily share for this tab used ({cap} of {self.limit}); resets tomorrow"
        return None

    def spend(self, function: str) -> None:
        s = self.state()
        s["used"] += 1
        s["by_function"][function] = s["by_function"].get(function, 0) + 1
        self._save(s)

    def mark_exhausted(self, why: str) -> None:
        s = self.state()
        s["exhausted"] = why[:120]
        self._save(s)

    def summary(self) -> dict:
        s = self.state()
        return {"used": s["used"], "limit": self.limit, "date": self.today().isoformat(),
                "by_function": s["by_function"], "exhausted": s["exhausted"]}


class Fetcher:
    """Same-day disk cache in front of Alpha Vantage, with a per-request cap
    and a per-day budget."""

    def __init__(self, api_key: str, cache_dir: Path = CACHE_DIR,
                 getter: Callable[[str, str, str], dict] = http_get,
                 max_live: int = MAX_LIVE_FETCHES, budget: Budget | None = None):
        self.api_key, self.cache_dir, self.getter, self.max_live = api_key, cache_dir, getter, max_live
        self.budget = budget or Budget(cache_dir)
        self.live_calls = 0

    def get(self, function: str, symbol: str) -> tuple[dict | None, str | None]:
        """(payload, None) or (None, reason-skipped)."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", symbol.upper())
        p = self.cache_dir / f"{function}_{safe}_{date.today().isoformat()}.json"
        if p.exists():
            try:
                return json.loads(p.read_text()), None
            except ValueError:
                p.unlink(missing_ok=True)      # corrupt: refetch below
        if self.live_calls >= self.max_live:
            return None, "live-fetch cap reached for this request"
        refused = self.budget.refuse(function)
        if refused:
            return None, refused
        self.live_calls += 1
        self.budget.spend(function)          # before the call: a timeout may still count upstream
        try:
            payload = self.getter(function, symbol, self.api_key)
        except UpstreamError as e:
            return None, f"upstream error: {e}"
        err = av_error(payload)
        if err:
            if _is_rate_limit(err):
                self.budget.mark_exhausted(err)
            return None, err
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(p)
        return payload, None


# ------------------------------------------------------------------- build
def is_us_ticker(t: str | None) -> bool:
    return bool(t) and "." not in t and not t.startswith("^") and "=" not in t


def build(kind: str, held: list[str], watch: list[str], fetcher: Fetcher,
          days: int = DEFAULT_DAYS, holdings_note: str | None = None,
          today: date | None = None) -> dict:
    if kind not in TYPES:
        raise ValueError(f"type must be one of {sorted(TYPES)}")
    cfg = TYPES[kind]
    held_set = {t.upper() for t in held if is_us_ticker(t)}
    watch_set = {t.upper() for t in watch if is_us_ticker(t)}
    symbols = sorted(held_set) + sorted(watch_set - held_set)   # holdings first

    rows, skipped, reasons = [], [], {}
    for sym in symbols:
        payload, why = fetcher.get(cfg["function"], sym)
        if payload is None:
            skipped.append(sym)
            reasons[sym] = why
            continue
        rows.extend(NORMALISE[kind](payload, sym)[:MAX_ROWS_PER_SYMBOL])

    today = today or date.today()
    cutoff = today - timedelta(days=days)
    for r in rows:
        r["yours"] = "HELD" if r["symbol"] in held_set else ("WATCH" if r["symbol"] in watch_set else None)
    rows = [r for r in rows if (_d(r["filed"]) or _d(r["traded"]) or date.min) >= cutoff]
    rows.sort(key=lambda r: (r["filed"] or "", r["traded"] or ""), reverse=True)

    recent = today - timedelta(days=MOST_BOUGHT_DAYS)
    counts = Counter(r["symbol"] for r in rows
                     if r["side"] == "buy" and (_d(r["filed"]) or _d(r["traded"]) or date.min) >= recent)
    out = {
        "type": kind, "configured": True, "rule": cfg["rule"],
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": cfg["source"],
        "partial": bool(skipped), "skipped": skipped, "skipped_reasons": reasons,
        "symbols": symbols, "window_days": days,
        "rows": rows,
        "most_bought": [{"symbol": s, "count": n} for s, n in counts.most_common(10)],
        "live_fetches": fetcher.live_calls,
        "budget": fetcher.budget.summary(),
    }
    if holdings_note:
        out["holdings_note"] = holdings_note
    return out


def api_key() -> str | None:
    return os.getenv("ALPHAVANTAGE_API_KEY") or None
