"""
Read-only Avanza portfolio MCP server.

Run (stdio, from the repo root):
    uv run --python 3.13 --with "mcp<2" --with pandas --with certifi --with yfinance \
        python -m portfolio_mcp.server

Exposes exactly five tools. None of them can place, change or cancel an order,
set a stop-loss, or move money -- see avanza_readonly.READ_ENDPOINTS for the
complete list of requests this server can send.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    """Same semantics as terminal/app.py: .env fills gaps, real env vars win.
    Nothing is printed -- stdout is the MCP protocol channel under stdio."""
    f = ROOT / ".env"
    if not f.exists():
        return
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

from mcp.server.fastmcp import FastMCP                                   # noqa: E402

from portfolio_mcp.avanza_readonly import AvanzaUnavailable, redact     # noqa: E402
from portfolio_mcp.portfolio import Portfolio                            # noqa: E402

_pf: Portfolio | None = None


def _portfolio() -> Portfolio:
    global _pf
    if _pf is None:
        _pf = Portfolio()
    return _pf


def _safe(fn):
    """Every error leaves as a short, redacted message -- never a traceback that
    could carry a URL, account number or response body."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except (AvanzaUnavailable, ValueError) as e:
            raise RuntimeError(redact(str(e))) from None
        except Exception as e:
            raise RuntimeError(redact(f"{fn.__name__} failed: {type(e).__name__}")) from None
    return wrapper


def build_server() -> FastMCP:
    mcp = FastMCP("avanza-portfolio")

    @mcp.tool()
    @_safe
    def get_account_summary() -> dict:
        """All Avanza accounts by alias (ISK, AF, SPARKONTO, ...): type, total
        value, cash and buying power, plus SEK totals. Account numbers are never
        returned. Read-only."""
        return _portfolio().account_summary()

    @mcp.tool()
    @_safe
    def get_positions(account: str | None = None) -> dict:
        """Holdings: account alias, name, ISIN, orderbook id, yahoo_ticker (null if
        unmapped), quantity, average cost (instrument currency and SEK), market
        value (instrument currency and SEK), P&L in SEK and %, day change %.
        Also cash per account, SEK totals, and SEK exposure by currency.
        Optional account alias (e.g. "ISK") filters to one account. Read-only."""
        return _portfolio().positions(account)

    @mcp.tool()
    @_safe
    def get_transactions(account: str | None = None, from_date: str | None = None,
                         to_date: str | None = None, max_elements: int = 200) -> dict:
        """Trades, deposits, withdrawals, dividends and fees, newest first. Dates
        are ISO (YYYY-MM-DD). Includes commission per trade. Optional account
        alias. max_elements capped at 1000. Read-only."""
        return _portfolio().transactions(account, from_date, to_date, max_elements)

    @mcp.tool()
    @_safe
    def get_performance(period: str = "1m", account: str | None = None) -> dict:
        """Performance for one period: 1d, 1w, 1m, 3m, ytd, 1y, 3y, all. Per-account change
        (SEK and %) from the account overview; for 1d/1w/ytd/3y also Avanza's
        insights report with total outcome, dividends, and best/worst holdings.
        Optional account alias. Read-only."""
        return _portfolio().performance(period, account)

    @mcp.tool()
    @_safe
    def get_brief_data(earnings_within_days: int = 30) -> dict:
        """Everything a portfolio brief needs, computed in code so the numbers are
        exact: totals and cash %, per-holding weight and P&L, concentration (top-1,
        top-3, by type, by currency), 1d/1w/1m/ytd performance with 1w best/worst,
        flags (big day moves, deep unrealized losses, stale prices), upcoming
        earnings for held stocks, and the tickers to fetch news for. Read-only."""
        from portfolio_mcp.brief import brief_data
        return brief_data(_portfolio(), earnings_within_days)

    return mcp


def main() -> None:
    transport = os.getenv("PORTFOLIO_MCP_TRANSPORT", "stdio")
    if transport != "stdio":
        # Deliberately not wired: this serves real brokerage data, and HTTP
        # without enforced bearer-token auth would expose it to anyone who can
        # reach the port. Add a TokenVerifier before enabling this branch.
        sys.exit(f"transport '{transport}' is not enabled yet -- stdio only until "
                 "bearer-token auth is implemented (see portfolio_mcp/README.md)")
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
