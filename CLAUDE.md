# CLAUDE.md

Guidance for Claude Code in this repo. The terminal's AI panel (`terminal/ai.py`)
also runs `claude -p` with this directory as cwd, so these rules govern that
assistant too.

## What this is

A local trading terminal (FastAPI backend + static JS UI) with Avanza
integration, plus a read-only portfolio MCP server and an on-demand portfolio
brief skill. Split out of `Algorithmic_trading_projects` on 2026-09-24 so the
terminal can be redesigned and deployed as its own project. That repo still
holds the strategies, backtests and IBKR execution stack.

## Commands

```bash
python3.13 -m terminal.app              # terminal at http://127.0.0.1:8777 (--port to change)
python3.13 -m terminal.avanza_setup     # TOTP activation helper; --login tests a real login
uv --directory . run --python 3.13 --with "mcp<2" --with pandas --with certifi --with yfinance \
    python -m portfolio_mcp.server      # read-only portfolio MCP (see portfolio_mcp/README.md)
python3.13 -m pytest -q                 # unit tests: fakes only, no network, no Avanza logins
AVANZA_USERNAME= AVANZA_PASSWORD=<your-password> AVANZA_TOTP_SECRET=<your-totp-secret> python3.13 -m terminal.app --port 8791
                                        # run with Avanza disabled (empty env beats .env)
```

Tests cover the v2 API (`terminal/api_v2.py`, contract in `docs/API.md`). For
everything else, verify by running the terminal and using the feature. Never
write a test that logs in to Avanza — logins are throttled (HTTP 401 after
~15 in a day).

Config: `ALPHAVANTAGE_API_KEY` (disclosures, optional). The AI panel's personal
profile is `profile.local.md` (gitignored; template `profile.example.md`).
Local runtime data (trade plans, API caches) lives in gitignored `data/`.

## Hard rules

1. **Never place, modify or cancel an order** — through Avanza, the terminal,
   the MCP servers or anything else — unless the user gives a very explicit,
   unambiguous instruction to do so (he has said he will not). The Avanza API
   here is unofficial and the account is funded. `portfolio_mcp` is read-only by
   an immutable allowlist of four read endpoints; never add a write path to it.
2. **This repo is intended to go public.** Never commit `.env`,
   `alerts_config.json` (push-alert topic + capital), `portfolio_mcp/ticker_map.json`
   (lists real holdings), `profile.local.md` (personal profile), `data/`, or any real amounts, positions, or account numbers —
   including as examples in docs or skills. Before any commit touching Avanza,
   portfolio or alert code, scan the staged diff for `.env` values, account
   identifiers and holdings names, printing counts only, never the values.
3. **Account numbers never leave the process.** Avanza's account `id` is the
   account number; tools expose aliases (ISK, AF, SPARKONTO).
4. **No silent failures.** Several indicator/panel builders catch `Exception`
   and return nothing, which hides breakage as "no data". Don't add more; when
   touching one, surface the error instead.

## Trade discussion rules (AI panel and Claude Code alike)

Any discretionary trade suggestion needs, before entry:
1. a predefined take-profit **and** stop-loss;
2. an explicit gamma/theta/decay warning for leveraged, short-dated or 0DTE
   products — daily-reset certificates (BULL/BEAR X5 etc.) decay on choppy paths
   independent of direction;
3. leverage capped at `100 / (3.5 × ATR%)`;
4. an earnings-date check.
Courtage is charged on both legs; on small positions it can exceed the gain.

## Architecture notes

- `terminal/feeds/avanza.py` — `AvanzaAuth` is the single login path (env vars,
  cookie-jar session, local TOTP). A TOTP code is single-use per 30 s window;
  two logins in one window fail as a replay. Route through `ensure()`.
- `terminal/indicators.py` — TTM Power Range lives here; it produced ~75% of
  realized profit historically, far more than any backtested strategy. Treat it
  as the core feature, not one indicator among many.
- `screeners/` and `terminal/trend_compass.py` were copied from the old repo;
  trend compass is descriptive only (backtested: no forward-return edge).

## Deployment direction

Planned: redesigned UI on Vercel. The backend holds a logged-in Avanza session,
websocket streams and in-memory caches, so it needs a long-running host
(Railway), not serverless functions — cold starts would re-login with fresh
TOTP codes and drop streams. Any hosted backend or MCP HTTP transport must have
enforced authentication before it serves account data.
