# portfolio_mcp — read-only Avanza portfolio for Claude

A thin MCP server over the trading terminal's existing Avanza login
(`terminal/feeds/avanza.py:AvanzaAuth`). It lets Claude Desktop / Claude Code
read your holdings, cash, transactions and performance. It cannot trade.

## Read-only guarantee

- **Allowlist, not omission.** `avanza_readonly.READ_ENDPOINTS` is the complete
  set of requests this server can send: `overview`, `positions`, `transactions`
  (GET) and `insights` (a POST report query that changes nothing). Callers name
  an entry; there is no raw-path parameter. Anything else raises
  `ReadOnlyViolation`, and the table is immutable at runtime.
- **The Qluxzz `avanza` library is not imported.** Its `place_order`, stop-loss
  and transfer methods are therefore not reachable from this package at all.
- **One login path.** Credentials are read once by `AvanzaAuth` from env vars
  (`.env`, gitignored). They are never logged, returned or re-sent.
- **Account numbers never leave the process.** Avanza's account `id` *is* the
  account number, so tools speak in aliases (`ISK`, `AF`, `SPARKONTO`, ...).
  Errors additionally mask any 5+ digit run.

Verified 2026-09-24 against the live account: write names and a
path-traversal attempt are blocked, and a scan of every tool output found zero
account identifiers.

## Tools

| Tool | Returns |
|---|---|
| `get_account_summary()` | Accounts by alias: type, total value, cash, buying power; SEK totals |
| `get_positions(account?)` | Holdings with ISIN, orderbook id, `yahoo_ticker`, qty, avg cost and market value in both instrument currency and SEK, P&L SEK/%, day %, implied FX; cash; SEK exposure by currency |
| `get_transactions(account?, from_date?, to_date?, max_elements=200)` | Trades, deposits, dividends, fees — including commission per trade |
| `get_performance(period, account?)` | `1d 1w 1m 3m ytd 1y 3y all`. Per-account change from the overview; for `1d/1w/ytd/3y` also Avanza's insights (total outcome, dividends, best/worst holdings). Insights has no 1m/3m/1y — the tool says so rather than inventing it. |
| `get_brief_data(earnings_within_days=30)` | Everything the brief quotes, computed in code: totals/cash %, weights, concentration (top-1/top-3/type/currency), 1d/1w/1m/ytd, flags (≥3% day moves, ≤−10% unrealized, stale prices), upcoming earnings for held stocks (public yfinance data — no extra Avanza calls). Used by the `/portfolio-brief` skill. |

Currency: values come back in the instrument's currency **and** SEK. Totals
are summed over SEK amounts only; anything not in SEK is listed separately.
Responses are cached 60 s. An expired session triggers one re-login; a TOTP
code already spent in the current 30 s window (e.g. by the terminal) is
handled by waiting out AvanzaAuth's 60 s TOTP cool-down once, then failing
clearly. A step-1 401/403 (bad credentials or throttling) is never retried:
`AvanzaAuth` blocks all logins for 30 min after one.

## Setup

Needs `uv`. `.env` in the repo root with `AVANZA_USERNAME`, `AVANZA_PASSWORD`,
`AVANZA_TOTP_SECRET` (see `.env.example`). Test it:

```bash
uv --directory /path/to/trading-terminal run --python 3.13 \
  --with "mcp<2" --with pandas --with certifi --with yfinance python -m portfolio_mcp.server
```

`mcp<2` is pinned on purpose: mcp 2.x renamed `FastMCP` and changed its API.

**Claude Desktop:** merge the `mcpServers` block from `claude_mcp_config.json`
into `~/Library/Application Support/Claude/claude_desktop_config.json`, restart.

**Claude Code:** `claude mcp add-json avanza-portfolio '<that server's JSON>'`
per server, or copy the file to the repo root as `.mcp.json`.

## Companion servers (config only)

| Name | Source | Notes |
|---|---|---|
| `avanza-market` | PyPI `avanza-mcp==2.1.0` | Public Avanza market data, no login, no order tools. Does **not** need `--prerelease=allow` at 2.1.0 (verified). |
| `yahoo-finance` | Alex2Yang97/yahoo-finance-mcp, pinned to commit `b9c1765` | Quotes, history, news, statements, options, recommendations. uv fetches Python 3.14 for it automatically. |
| `efn-news` | PyPI `efn-mcp==0.1.0` | Swedish news, market commentary, analyst picks. |

These are third-party code running on your machine. `avanza-mcp` and
`efn-mcp` publish no source link on PyPI, which is why every entry is pinned
to an exact version/commit and none of them is given any environment variables
— they never see your Avanza credentials. Bump pins deliberately, not
automatically.

## Ticker map

`ticker_map.json` maps Avanza orderbook ids to Yahoo tickers. It is
**gitignored** because it lists your actual holdings; copy
`ticker_map.example.json` to start one. Entries are only
added after a same-currency live price match against yfinance (<3%), plus ISIN
where the listing is ambiguous. Funds are unmapped and return `null`. When you
buy something new it shows up with `yahoo_ticker: null` until added the same way.

## Not enabled: HTTP

`PORTFOLIO_MCP_TRANSPORT` other than `stdio` exits on purpose. This serves real
brokerage data; before running it on Railway, add enforced bearer-token auth
(a FastMCP `TokenVerifier`) — then the switch is the transport setting in
`main()`.
