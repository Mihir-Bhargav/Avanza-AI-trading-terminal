"""
Setups service behind `/api/setups` and the Kes briefing.

Wraps screeners/zone_panel.py with data fetching, earnings lookup, concurrency
and a 5-minute cache. Bars come from whatever `bars_fn` the app binds (the
routed feed in production, a fake in tests), so this module never opens a
network connection on its own.

Failures are reported, never swallowed: a symbol whose data could not be built
appears in `errors` with the reason, and an earnings lookup that failed carries
`earnings_error` on its row.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from screeners import zone_panel as ZP

CACHE_TTL_S = 300

BarsFn = Callable[[str], "object"]            # yahoo ticker -> DataFrame | None
EarningsFn = Callable[[str], tuple]           # yahoo ticker -> (ticker, {date, days_until} | {error})


def is_stock(yahoo: str) -> bool:
    """Earnings apply to single stocks, not indices/FX/futures."""
    return not (yahoo.startswith("^") or "=" in yahoo)


def _default_earnings(ticker: str):
    from portfolio_mcp.brief import _next_earnings
    return _next_earnings(ticker)


class SetupsService:
    def __init__(self, bars_fn: BarsFn, earnings_fn: EarningsFn | None = None,
                 universe: list[tuple[str, str, str, str]] | None = None,
                 ttl: float = CACHE_TTL_S):
        self.bars_fn = bars_fn
        self.earnings_fn = earnings_fn or _default_earnings
        self.universe = universe if universe is not None else ZP.UNIVERSE
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ build
    def _one(self, spec: tuple[str, str, str, str | None]) -> tuple[dict | None, dict | None]:
        symbol, name, yahoo, query = spec
        try:
            df = self.bars_fn(yahoo)
            if df is None:
                return None, {"symbol": symbol, "error": "no daily bars returned"}
            row = ZP.build_row(symbol, name, yahoo, query, df)
        except Exception as e:  # reported per symbol, not dropped
            return None, {"symbol": symbol, "error": f"{type(e).__name__}: {e}"[:200]}
        if is_stock(yahoo):
            try:
                _, e = self.earnings_fn(yahoo)
                row["earnings_date"] = e.get("date")
                row["earnings_days"] = e.get("days_until")
                if "error" in e:
                    row["earnings_error"] = e["error"]
            except Exception as ex:
                row["earnings_error"] = type(ex).__name__
        return row, None

    def _compute(self, specs: list[tuple]) -> dict:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self._one, specs))
        rows = [r for r, _ in results if r]
        errors = [e for _, e in results if e]
        return {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rows": ZP.sort_rows(rows), "errors": errors}

    def _cached(self, key: str, specs: list[tuple]) -> dict:
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        data = self._compute(specs)
        # A total failure is not cached: the next request should retry rather
        # than serve an empty panel for five minutes.
        if data["rows"]:
            with self._lock:
                self._cache[key] = (time.time(), data)
        return data

    # ----------------------------------------------------------------- public
    def find_spec(self, symbol: str) -> tuple | None:
        s = symbol.strip().upper()
        for spec in self.universe:
            if s in (spec[0].upper(), spec[2].upper()):
                return spec
        return None

    def get(self, symbol: str | None = None) -> dict:
        if not symbol:
            return self._cached("*", list(self.universe))
        spec = self.find_spec(symbol)
        if spec is not None:
            full = self._cached("*", list(self.universe))
            rows = [r for r in full["rows"] if r["symbol"] == spec[0]]
            errs = [e for e in full["errors"] if e["symbol"] == spec[0]]
            return {"as_of": full["as_of"], "rows": rows, "errors": errs}
        # Not in the universe: compute an ad-hoc row (chart page on any symbol).
        s = symbol.strip()
        return self._cached(f"adhoc:{s.upper()}", [(s.upper(), s, s, None)])

    def row_for(self, symbol: str) -> dict | None:
        """One row for plan validation. Uses the cached universe when present,
        otherwise computes just this symbol -- never a 16-symbol fetch."""
        spec = self.find_spec(symbol)
        with self._lock:
            hit = self._cache.get("*")
        if hit and spec is not None and time.time() - hit[0] < self.ttl:
            row = next((r for r in hit[1]["rows"] if r["symbol"] == spec[0]), None)
            if row:
                return row
        if spec is None:
            s = symbol.strip().upper()
            spec = (s, s, s, None)
        data = self._cached(f"one:{spec[0]}", [spec])
        return data["rows"][0] if data["rows"] else None
