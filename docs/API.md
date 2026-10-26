# Terminal API v2 (for the `web/` front end)

Base URL: `http://127.0.0.1:8777` (run `python3.13 -m terminal.app`).
CORS allows `http://localhost:3000` and `http://127.0.0.1:3000`, GET and POST only.
Implementation: `terminal/api_v2.py`. Existing endpoints (`/api/watchlist/...`,
`/api/chart/...`, `/api/ai/...`, `/ws`, ...) are unchanged.

**Read-only.** No endpoint places, modifies or cancels an order. The only write
is `POST /api/plans`, a local record of intent.

**Errors** are always JSON `{"error": "..."}` (sometimes with extra keys):
`400` bad input, `503` upstream unavailable or not configured, `500` local
storage problem. Nothing is turned into empty data silently: partial failures
are listed inside `200` responses (`errors`, `skipped`, `earnings_error`,
`holdings_note`, `plans_error`).

**Freshness.** Values are `"live" | "delayed" | "closed" | "stale" | "unknown"`.
`closed` = market shut, old price is correct. `stale` = market open but the
data is old: do not trust it. `age_min` is minutes since the data's own
timestamp. `as_of` is when the server built the response (ISO 8601, UTC).

---

## GET /api/market-line

Ticker strip. Cached 15 s.

```json
{
  "as_of": "2026-09-24T11:12:20+00:00",
  "items": [
    {"key": "omxs30", "label": "OMXS30", "symbol": "^OMX", "last": 3288.92,
     "change_pct": -0.844, "freshness": "live", "age_min": 0.3, "source": "yfinance"},
    {"key": "gold", "label": "Gold", "symbol": "GC=F", "last": 4293.0,
     "change_pct": -0.588, "freshness": "delayed", "age_min": 11.3, "source": "yfinance-futures"}
  ]
}
```

Keys, in order: `omxs30` (^OMX), `spx` (^GSPC), `ndx` (^NDX), `gold`, `usdsek` (USDSEK=X).
`change_pct` is in percent (`-0.844` = −0.844%). Gold is real-time spot
(`symbol: "XAUUSD"`, `source: "avanza-spot"`) only when an Avanza session is
already authenticated; otherwise GC=F futures, never reported as `live`.
A failed item has `last: null`, `freshness: "unknown"` and an `error` string.

## GET /api/setups?symbol=

TTM Power Range zone panel (`screeners/zone_panel.py`). Cached 5 min.
`symbol` is optional; matches `symbol` or `yahoo` case-insensitively. A symbol
outside the universe is computed ad hoc (`avanza_query: null`).

```json
{
  "as_of": "2026-09-24T11:12:21+00:00",
  "rows": [{
    "symbol": "MU", "yahoo": "MU", "name": "Micron Technology", "avanza_query": "MINI MICRON",
    "trend": "up", "close": 1071.88, "open": 1100.07,
    "zone1": 1119.66, "zone2": 1117.70, "zone3": 1080.48, "zone4": 1082.44,
    "atr14": 49.84, "atr_pct": 4.65, "lev_cap": 6.1,
    "state": "crossed_z3_down", "dist_z1_atr": -0.959, "dist_z3_atr": 0.173,
    "with_trend": false,
    "hist": {"z1_up": {"n": 76, "win_rate": 0.553, "avg_fwd_ret": 0.0162},
             "z3_dn": {"n": 40, "win_rate": 0.5, "avg_fwd_ret": -0.002}},
    "earnings_date": "2026-09-30", "earnings_days": 6,
    "bar_date": "2026-09-23"
  }],
  "errors": [{"symbol": "EVO", "error": "RuntimeError: ..."}]
}
```

- Universe (16): OMXS30, VOLV-B, ERIC-B, HM-B, EVO, SPX, NDX, NVDA, TSLA, AAPL,
  AMD, AVGO, TSM, MU, QCOM, ASML. Chart links use `symbol`; data uses `yahoo`.
- `trend`: `up` if close > EMA21.
- `dist_z1_atr = (close − zone1) / ATR14`, `dist_z3_atr = (zone3 − close) / ATR14`.
  **Positive means through the zone**; negative = still inside, by that many ATRs.
- `state` (checked in this order): `crossed_z1_up` if dist_z1 > 0.10;
  `crossed_z3_down` if dist_z3 > 0.10; `at_z1`/`at_z3` if |dist| ≤ 0.10;
  `near_z1`/`near_z3` if within 0.35 ATR short of the zone; else `inside`.
- `with_trend`: (crossed/at z1 and trend up) or (crossed/at z3 and trend down).
- Sort: crossed-with-trend first, then smallest |distance| to either zone.
- `hist`: purely descriptive, last 2 years. `win_rate` is 0..1; `avg_fwd_ret`
  is a fraction (0.016 = 1.6%) of the raw 3-day forward return. For `z3_dn`,
  a "win" is a lower close. `win_rate`/`avg_fwd_ret` are `null` when `n` is 0.
- `lev_cap` = 100 / (3.5 × ATR%).
- `earnings_*` only for single stocks (null for indices). A failed lookup adds
  `earnings_error`.
- `bar_date`: date of the bar classified. Before a market opens this is the
  **previous session** (e.g. US names during the Stockholm morning).
- `errors`: symbols that could not be built. All failed → `503`.

## Portfolio (read-only, Avanza)

All share the terminal's one Avanza session via `ReadOnlyAvanza(auth=AVANZA_AUTH)`.
Accounts are aliases (`ISK`, `AF`, ...); account numbers never appear. Upstream
responses cached 60 s. Shapes are exactly `portfolio_mcp/portfolio.py` /
`brief.py` output (see `portfolio_mcp/README.md`).

| Endpoint | Returns |
|---|---|
| `GET /api/portfolio/status` | `{"configured": bool, "authenticated": bool, "login_blocked_until": iso\|null, "last_login_failure": str\|null}` — never triggers a login |
| `GET /api/portfolio/summary` | `Portfolio.account_summary()` |
| `GET /api/portfolio/positions?account=` | `Portfolio.positions(account)` |
| `GET /api/portfolio/performance?period=1d\|1w\|1m\|3m\|ytd\|1y\|3y\|all&account=` | `Portfolio.performance(...)` (default `1m`) |
| `GET /api/portfolio/transactions?account=&from_date=YYYY-MM-DD&to_date=&max_elements=200` | `Portfolio.transactions(...)` |
| `GET /api/portfolio/brief?earnings_within_days=30` | `brief_data(...)` |

Errors: not configured → `503`; Avanza login/fetch failure → `503` (message
redacted: 5+ digit runs masked); unknown account, bad period or bad date → `400`.
Note: every endpoint except `status` logs in lazily if no session exists.

**Login cool-down.** After a failed Avanza login, `AvanzaAuth` refuses further
attempts without touching the network: 30 min after a step-1 HTTP 401/403
(bad credentials or Avanza throttling), 60 s after a TOTP replay/rejection,
5 min otherwise; any failure after the first consecutive one waits 30 min.
A data request answered 401/403 forces at most one fresh re-login per 15 min.
While blocked, portfolio endpoints return 503 with
`"...; next attempt allowed in N min"`. `login_blocked_until` and the redacted
`last_login_failure` are on `/api/portfolio/status` and `/api/avanza/status`,
so the UI can say "Avanza paused after a failed login, retrying at 10:42".

## GET /api/disclosures?type=congress|insiders|funds&days=180

`congress` and `insiders`: public filings via Alpha Vantage (below).
`funds`: 13F-HR filings of well-known funds read from SEC EDGAR — see
[type=funds](#get-apidisclosurestypefunds) after this section; it needs no
Alpha Vantage key and spends none of its budget.

Needs `ALPHAVANTAGE_API_KEY`; without it:
`503 {"error": "ALPHAVANTAGE_API_KEY is not set", "configured": false, "type": "..."}`.

```json
{
  "type": "congress", "configured": true,
  "rule": "STOCK Act · filed within 45 days",
  "as_of": "...", "source": "Alpha Vantage CONGRESS_TRADES (...)",
  "partial": true, "skipped": ["TSLA"], "skipped_reasons": {"TSLA": "live-fetch cap reached for this request"},
  "symbols": ["AAPL", "NVDA"], "window_days": 180, "live_fetches": 2,
  "holdings_note": "portfolio session not authenticated; HELD is not marked",
  "rows": [{
    "filed": "2026-09-17", "traded": "2026-08-20", "lag_days": 28,
    "who": "Rep A", "chamber": "House", "party": "D", "owner": "spouse", "role": null,
    "symbol": "AAPL", "side": "buy", "amount_min": 1001.0, "amount_max": 15000.0,
    "amount_label": "$1K–$15K", "yours": "HELD"
  }],
  "most_bought": [{"symbol": "AAPL", "count": 1}]
}
```

- Symbols: held US stock tickers (only if a portfolio session is **already**
  authenticated — never forces a login) ∪ US tickers in the setups universe.
  Non-US tickers (`.ST`, indices) are skipped because the source is US-only.
- `side`: `buy | sell | hold | other`. `yours`: `HELD`, `WATCH` or `null`.
- `lag_days = filed − traded`. Rows sorted by `filed` desc (then `traded`),
  limited to the last `days` days.
- `most_bought`: buys per symbol in the last 30 days.
- Per type:
  - `congress`: all fields populated; `owner` ∈ self/spouse/joint/dependent_child/other.
  - `insiders` (Form 4): **the API publishes no filing date**, so `filed` and
    `lag_days` are null; `role` = executive title; `amount_*` = shares × price
    (USD; null when price is 0, e.g. RSU grants); extra `security` field.
- Free tier = 25 requests/day. Responses are cached on disk per
  function+symbol+day (`data/cache/alphavantage/`, gitignored); at most 10 live
  calls per request, and a per-day ledger (`_budget_YYYY-MM-DD.json` in the same
  folder) stops live calls at 25 across all requests (`ALPHAVANTAGE_DAILY_LIMIT`
  overrides, e.g. for a paid key). The legacy `insiders` type may use at most
  4 of them; `congress` gets the rest (funds no longer use Alpha Vantage). A
  rate-limit answer marks the day exhausted. Symbols
  not fetched appear in `skipped` with the reason and `partial: true`.
- `budget`: `{"used": 9, "limit": 25, "date": "2026-09-24",
  "by_function": {"CONGRESS_TRADES": 9}, "exhausted": null}`.
- The web UI's Insiders tab uses `/api/insiders` (SEC, below), not
  `type=insiders`, which is kept for compatibility.

## GET /api/disclosures?type=funds

What ~19 well-known funds (Berkshire, Pershing Square, Bridgewater,
Renaissance, Citadel, Tiger, Coatue, Appaloosa, Third Point, Baupost,
Duquesne, Soros, Icahn, Greenlight, Viking, Lone Pine, Himalaya, ARK, Scion)
opened, added to, trimmed and closed last quarter: their two latest 13F-HR
filings, diffed. Read directly from SEC EDGAR (`terminal/funds13f.py`; the
curated list with verified CIKs is `FUNDS` there). Needs `SEC_USER_AGENT`
(same as `/api/insiders`); without it:
`503 {"error": "Set SEC_USER_AGENT in .env, ...", "configured": false, "type": "funds"}`.
If the background loader is not running: `503 {"configured": true, "error": "SEC 13F loader is not running (restart the backend)"}`.

```json
{
  "type": "funds", "configured": true,
  "rule": "13F · quarterly, filed up to 45 days after quarter end",
  "as_of": "...", "source": "SEC EDGAR 13F-HR information tables (curated fund list)",
  "partial": false, "skipped": [], "skipped_reasons": {},
  "loading": false, "progress": {"done": 19, "total": 19},
  "window_days": 180, "max_moves_per_fund": 40,
  "holdings_note": "portfolio session not authenticated; HELD is not marked",
  "tickers": {"mapped": 538, "total": 568, "error": null},
  "rows": [{
    "filed": "2026-08-14", "traded": "2026-06-30", "lag_days": 45,
    "who": "Example Capital", "fund_key": "example", "manager": "Jane Doe", "role": "Fund",
    "chamber": null, "party": null, "owner": null,
    "symbol": "EXRB", "issuer": "Example Robotics Inc", "cusip": "900000101", "security": "COM",
    "side": "ADD", "amount_min": 1.2e9, "amount_max": 1.2e9,
    "amount_label": "+25% shares · $1.2B · 6.9% of portfolio",
    "value": 1.2e9, "prev_value": 8.0e8, "shares": 5000000, "prev_shares": 4000000,
    "change_pct": 25.0, "split_adjusted": null, "pct_portfolio": 6.9, "prev_pct_portfolio": 4.1,
    "prev_period": "2026-03-31", "amended": null, "yours": "WATCH"
  }],
  "most_bought": [{"symbol": "EXRB", "count": 3, "value": 2.1e9, "funds": ["Example Capital", "..."]}],
  "funds": [{
    "key": "example", "name": "Example Capital", "manager": "Jane Doe", "cik": 9000010, "ciks": [9000010],
    "status": "ok", "error": null, "period": "2026-06-30", "filed": "2026-08-14", "amended": null,
    "prev_period": "2026-03-31", "positions": 46, "total_value": 2.4e10, "moves": 52,
    "in_window": true, "notes": [], "sec_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=9000010&type=13F-HR"
  }]
}
```

- One row per position that changed between the fund's latest 13F and the
  one before: `side` = `NEW` (opened), `ADD`, `TRIM` (share count ±1% or
  more; `change_pct` = share change), `EXIT` (closed). `traded` = the report
  period (quarter end); `filed` = the original filing date; `lag_days = filed − traded`.
- Values in USD. `amount_min = amount_max` = position value at quarter end
  (for `EXIT`: the value at the previous quarter end). `pct_portfolio` =
  share of the fund's reported long-equity value. Only share positions are
  diffed: listed options (`putCall`) and principal amounts (convertibles) are
  left out. Per fund at most the 40 biggest moves by dollar size.
- Sorted by `filed` desc, then value. `days` limits by filing date: a fund
  whose latest 13F is older (e.g. Scion, which stopped filing in 2025) is
  listed in `funds` with `in_window: false` and contributes no rows.
- `symbol`: CUSIP → ticker has no free official map, so the 13F issuer name
  is matched to SEC `company_tickers.json` (normalised; truncated names by
  unique prefix) plus a few verified CUSIP overrides (Alphabet and Berkshire
  share classes, big ETFs). No confident match → `null`, never a guess.
  `tickers` reports the coverage.
- `most_bought`: tickers opened or added to, by number of funds, then dollars added.
- `yours`: HELD / WATCH / null, same rule as the other types (never logs in).
- Amendments: per period the original 13F-HR is the base; a 13F-HR/A
  RESTATEMENT replaces it, NEW HOLDINGS adds to it (`amended` = its date).
  `value` units: whole dollars from 2023-01-03, $ thousands before; a filing
  whose implied share prices are all cents is treated as thousands and says
  so in the fund's `notes`. Stock splits between quarters are adjusted only
  when the evidence across funds agrees (`split_adjusted` = k).
- Loading: a background thread started with the app fetches each fund's
  filing list and the two latest filings (≤ 4 req/s, shared with the Form 4
  poller). While it runs, `loading: true`, `partial: true` and rows appear
  fund by fund; a fund that failed is in `skipped` with the reason and is
  retried after 15 min. Cache: `data/cache/sec13f/` (gitignored) — parsed
  filings by accession forever, filing lists refreshed every 12 h, the ticker
  list weekly. The endpoint never waits on the SEC.

## GET /api/insiders

Live, market-wide SEC Form 4 insider trades (CEOs, CFOs, directors, 10%
owners), read directly from EDGAR. Needs `SEC_USER_AGENT` (the SEC's
fair-access rules require a contact in the User-Agent); without it:
`503 {"configured": false, "error": "Set SEC_USER_AGENT in .env, e.g. 'Range Terminal you@example.com' (required by the SEC)"}`.

Query: `days` (1–30, default 7, by filing time) · `side=buy|sell|all` ·
`min_value` (USD) · `notable_only` · `ceo_only` · `mine` (HELD or WATCH only) ·
`symbols=NVDA,UBER` · `limit` (default 300, max 2000). Bad `side`: 400.

```json
{
  "configured": true, "as_of": "...", "source": "SEC EDGAR Form 4 (current filings feed)",
  "last_poll": "2026-09-24T15:33:40+00:00", "feed_updated": "2026-09-24T11:28:19-04:00",
  "poll_error": null, "backfilling": false, "filings_seen": 472,
  "parsed_this_session": 72, "parse_failures": 0, "last_parse_failure": null,
  "store_error": null, "poll_seconds": 120, "window_days": 7,
  "thresholds": {"notable_buy_usd": 250000, "notable_sell_usd": 5000000},
  "holdings_note": "portfolio session not authenticated; HELD is not marked",
  "total_matching": 212, "truncated": false,
  "rows": [{
    "id": "0009000002-26-000123:0", "filed_at": "2026-09-24T10:57:28-04:00",
    "trade_date": "2026-09-22", "lag_days": 2, "ticker": "EXRO",
    "issuer": "Example Robotics Inc", "who": "Doe Jane Q",
    "role": "Chief Executive Officer · Director", "is_ceo_like": true,
    "side": "BUY", "shares": 10000.0, "price": 12.5, "value": 125000.0,
    "security": "Common Stock", "plan_10b5_1": false, "notable": true,
    "yours": "WATCH", "sec_url": "https://www.sec.gov/Archives/edgar/data/.../...-index.htm"
  }],
  "top_buys": [{"ticker": "EXRO", "issuer": "Example Robotics Inc", "value": 125000.0, "buyers": 1}]
}
```

- Rows newest filing first. Only open-market **P** (BUY) and **S** (SELL)
  from the non-derivative table; grants, exercises, tax withholding, gifts and
  4/A amendments are excluded. `value = shares × price` (null when the filing
  gives no price). `who` is as filed (title-cased), `+N` for joint filers.
- `notable`: a buy ≥ $250K, any buy by a CEO/CFO/President/Chair
  (`is_ceo_like`, from officer title / other text), or a sale ≥ $5M.
- `plan_10b5_1`: the filing's Rule 10b5-1 checkbox (pre-arranged plan).
- `yours`: HELD (only if an Avanza session is already authenticated; never
  logs in) / WATCH (setups universe) / null — same rule as `/api/disclosures`.
- `top_buys`: last 7 days of BUY value per ticker, ignoring the filters.
- Poller: a background thread started by the app's lifespan. Startup
  backfills the latest 400 filings (processed page by page, newest first,
  `backfilling: true` until done), then polls every 2 minutes. Feed:
  `browse-edgar?action=getcurrent&type=4&owner=only&count=100&start=N&output=atom`
  (`type` is a prefix match; `owner=only` keeps it to ownership filings).
  One request per filing (the complete submission `.txt`, which embeds the
  Form 4 XML). ≤ 4 requests/s; HTTP 403/429 backs off 60 s doubling to 15 min.
  Requests never wait on the network: the endpoint reads the local store.
- Store: `data/insiders/trades.jsonl` + `seen.json` (gitignored), deduped by
  accession + line, pruned to 30 days.

## GET /api/kes/briefing

Deterministic cockpit line from the setups rows (no LLM).

```json
{"mood": "alert",
 "text": "Two setups crossed with the trend. AVGO is the interesting one, 0.24 ATR through zone 3 as of the 2026-09-23 close, trend down. History: n=46, 46% closed lower three days later, average move +0.9%. Leverage cap there is 8.7x.",
 "links": [{"label": "Show AVGO", "href": "/terminal/chart/AVGO"}],
 "as_of": "2026-09-24T11:13:03+00:00"}
```

Mood: `cautious` (a with-trend setup has earnings ≤ 7 days) > `alert` (a
with-trend cross, or setup data failed) > `pleased` (a plan was logged today)
> `watching`. Never contains buy/sell instructions. Optional `plans_error`.

## Trade plans

Local, gitignored `data/plans.json`. Records intent only; never places anything.

### GET /api/plans
`{"plans": [ ...newest first ], "streak": 3}`

### POST /api/plans
Body: `{"symbol": "MU", "side": "long"|"short", "take_profit": 1200, "stop_loss": 1000, "leverage": 3, "note": "optional"}`

Validation (400 with a readable `error` on failure):
- `take_profit` and `stop_loss` both required, positive numbers.
- long: `stop_loss < take_profit`; short: `take_profit < stop_loss`.
- If a current price is known (setups `close` for that symbol):
  long needs `stop_loss < price < take_profit`, short `take_profit < price < stop_loss`.
- If `lev_cap` is known: `leverage ≤ lev_cap`.

Response 200: the stored plan plus the new streak:
```json
{"id": "188fd66dc0f6", "created_at": "2026-09-24T11:13:03+00:00", "symbol": "MU",
 "side": "long", "take_profit": 1200.0, "stop_loss": 1000.0, "leverage": 3.0,
 "note": "…", "price_at_plan": 1071.88, "lev_cap": 6.1,
 "checked_against": "price 1071.88 from the 2026-09-23 daily bar; lev_cap from ATR14",
 "streak": 1}
```

**Streak**: walk plans newest → oldest, counting while the gap between
consecutive plans is ≤ 14 days; 0 if the newest plan is older than 14 days.

## POST /api/ai/ask (unchanged contract)

Body `{"question": str, "symbols"?: [str], "market"?: "us"}` →
`{"answer": str, "symbols": [...]}` or `{"error": ...}`. The persona is now Kes;
the personal profile is read from gitignored `profile.local.md`
(template: `profile.example.md`).

## GET /api/markets/sectors?index=sp500|nasdaq100|dow30|omxs30

Sector overview under the Markets page heatmap (`terminal/markets.py`, own router).
Membership is a dated curated snapshot (`watchlists/sector_leaders.json`). Prices:
two batched `yfinance.download` calls per index (5m bars + 1d for previous close).
Sector move = SPDR sector ETF for US indexes (`change_basis: "etf"`), equal-weighted
members for OMXS30 (`"members_avg"`). Headline = the biggest |mover|'s top
`ticker_news` item that actually names the company (or `null`). Cached 60 s
(headlines 5 min); failures are not cached.

```json
{"as_of": "…", "index": "sp500", "label": "S&P 500", "market": "us",
 "membership_as_of": "2026-09-24", "sources": {...}, "errors": ["BBB: no intraday bars returned"],
 "sectors": [{"sector": "Energy", "etf": "XLE", "change_pct": 1.52, "change_basis": "etf",
   "members_avg_pct": 1.27, "etf_quote": {...}, "top_mover": "MPC",
   "headline": {"title": "…", "source": "…", "age_min": 72, "url": "https://…", "symbol": "MPC"} | null,
   "headline_error": null,
   "members": [{"symbol": "XOM", "name": "Exxon Mobil", "last": 164.2, "change_pct": 1.84,
     "spark": [≤40 closes], "freshness": "live|delayed|closed|stale|unknown", "age_min": 5.0,
     "ts": "…", "prev_close_source": "daily|intraday|null", "error"?: "…"}]}]}
```
Errors: 400 unknown index; 503 `{"error"}` when the intraday batch fails or no symbol priced.
