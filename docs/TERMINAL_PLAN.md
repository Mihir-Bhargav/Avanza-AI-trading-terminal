# Trading Terminal — Plan

Drafted 2026-08-05. Not started. This is the design, the evidence behind it, and
the build order.

**Goal:** a local, browser-based terminal for live session monitoring — unlimited
panels, indicators and tickers — with an AI layer that can be asked anything
about the data. TradingView's flexibility without its free-tier caps, plus the
parts of a Bloomberg terminal that are actually reachable.

---

## 1. Data layer — measured, not assumed

Everything below was tested on 2026-08-05, not taken from documentation.

| Source | Coverage | Latency | Verdict |
|---|---|---|---|
| **yfinance** | Swedish stocks + OMXS30 | **~1 min** | Best free Swedish feed. Surprising but measured. |
| yfinance | DAX / EuroStoxx / EU equities | ~16 min | Delayed |
| yfinance | Metals/oil futures | ~11 min | Delayed |
| yfinance | daily bars, all markets | — | **Unreliable** — deleted the entire 08-04 session for 78/86 EU names |
| **IBKR TWS** | EU indices + AEB/SMART-routed equities | real-time where entitled | Proven: recovered the bars yfinance deleted |
| IBKR TWS | Stockholm (SFB), Paris (SBF), Xetra, Swiss | blocked | `error 162: No market data permissions` |
| **Avanza unauth** | Swedish stocks, 1-min OHLCV + volume | **15.7 min** | Worse than yfinance. Not a backbone. |
| Avanza **authenticated** | US + most of W. Europe + Nordics | real-time (per their docs) | Possible, but see risk below |
| **Alpaca** | US equities (IEX) | real-time | Free, incl. paper-trading API |
| **Binance** | Crypto | real-time | Free WebSocket, already working in `run_dom.py` |
| **TradingView** | spot/CFD symbols (`XAUUSD`, `GER40`) | real-time | Free, but no API — screen only |

### The Avanza question, settled

Avanza's own support page confirms real-time **stocks** are free and automatic for
Nordics (ex-Norway), USA, Germany, Italy, France, Belgium, Netherlands, Portugal,
Switzerland, Spain and the UK. Non-Nordic **indices are always 15 min delayed,
regardless of add-ons** — unfixable at any price.

Tested endpoints (Qluxzz/avanza library, still current):

    /_api/market-guide/stock/{id}          -> 200 JSON, instrument metadata
    /_api/price-chart/stock/{id}?...       -> 200 JSON, 1-min OHLCV + volume
    /_api/search/filtered-search           -> 500 unauthenticated

Unauthenticated latency measured at **15.7 min**. The real-time entitlement is
tied to the logged-in session.

**Risk if we authenticate:** unofficial API, no streaming endpoint (so live data
means polling in a loop), credentials for a funded account, and the library
authors' own warning that it *"can be taken down or changed without warning."*
Polling dozens of instruments continuously against an undocumented endpoint with
real credentials is exactly the pattern that gets an account restricted.

**Decision: not the backbone.** Optional later as an authenticated *supplement*
for the markets nothing else covers well, polled gently, never for orders.

### Chosen backbone (per market)

| Market | Source | Why |
|---|---|---|
| Sweden | yfinance | 1-min, free, no dependency |
| US | **Alpaca** | free real-time IEX + paper trading, no desktop app to babysit |
| EU indices/equities | IBKR TWS | only reliable source; entitlements permitting |
| Crypto | Binance WS | true real-time, already built |
| Daily bars / levels | IBKR, yfinance fallback | IBKR is authoritative after the 08-04 incident |

---

## 2. Architecture

    ┌─────────────────────────────────────────────────────┐
    │  BROWSER (localhost:8000)                           │
    │  Lightweight Charts (TradingView OSS, MIT)          │
    │  panels: chart grid · watchlist · levels · DOM ·    │
    │          news · AI chat · positions                 │
    └───────────────▲─────────────────────────────────────┘
                    │ WebSocket (live push) + REST (history)
    ┌───────────────┴─────────────────────────────────────┐
    │  FastAPI backend                                     │
    │  ├── feeds/      alpaca · ibkr · yfinance · binance  │
    │  │               one Feed interface, hot-swappable   │
    │  ├── indicators/ REUSES screeners/levels.py,         │
    │  │               signals/indicators/*                │
    │  ├── store/      SQLite (bars, trades) + Parquet     │
    │  ├── alerts/     level triggers -> ntfy push         │
    │  └── ai/         LLM + tools over the local data     │
    └──────────────────────────────────────────────────────┘

**Why this stack:** Lightweight Charts is TradingView's own charting library,
open-source and MIT — the same rendering, no indicator or ticker caps. FastAPI
keeps everything in Python so `screeners/levels.py`, `signals/indicators/` and
the watchlists are reused rather than rewritten.

**Feed interface** — one abstraction so sources are swappable without touching
the UI:

    class Feed(Protocol):
        def history(symbol, timeframe, lookback) -> DataFrame
        async def subscribe(symbols, on_bar) -> None
        def status(symbol) -> FeedStatus   # realtime | delayed(min) | stale

`status()` is not optional. Every panel displays its own latency. The DAX loss on
2026-08-05 happened because a 16-min-delayed index looked identical to live data.
**No number renders without its freshness attached.**

---

## 3. Build order

**Phase 0 — skeleton (½ day).** FastAPI + one chart + one hardcoded symbol from
yfinance. Proves the pipe end to end.

**Phase 1 — the prep view (2 days).** Watchlist table with live `run_session_picks`
scoring; click a row to load the chart with CPR/pivot/PDH/PDL lines drawn. This
alone replaces the terminal output you use every morning.

**Phase 2 — live layer (3 days).** WebSocket push, per-panel latency badges,
multi-panel grid, level-cross alerts to ntfy. **This is the actual goal** — you
currently watch Avanza and TradingView side by side with no level overlay.

**Phase 3 — AI layer (3 days).** See below.

**Phase 4 — depth & extras.** DOM panel (port `run_dom.py`), positions, trade log
integration, EOD review.

Phases 1 and 2 are independently useful. Nothing later is required for the thing
to earn its place.

---

## 4. AI layer

All four requested, built in this order — cheapest and safest first.

1. **Explain what's moving** — news pulled for whatever is statistically unusual,
   summarised, with conflicting narratives flagged. This is what caught that gold
   was rallying on Fed real-yields while the tape read "Iran de-escalation."
2. **Morning brief + EOD review** — auto-generate the pre-session brief; at the
   close, compare what happened against what was predicted, **including where the
   brief was wrong**. The 08-05 DAX call is exactly the kind of thing that must
   be recorded rather than quietly forgotten.
3. **Natural-language query over your own data** — the AI gets *tools*, not a
   prompt full of numbers: `get_levels`, `scan_watchlist`, `query_trades`,
   `get_bars`. Ask "which watchlist names have narrow CPR and rising RVOL" or
   "every time NEM gapped >2%, what happened next" and it computes the answer.
   This is the one that makes the repo's history interrogable.
4. **Signal generation** — requested, and it will be built. Stated concern, once:
   twelve backtested strategies exist and none are traded, and the audit showed
   the constraint is execution discipline, not signal supply. Mitigation: every
   AI signal must cite the levels and data it used, and is logged and scored
   against outcomes like any other strategy. If it doesn't beat TTM Power Range
   it gets archived — same rule as everything else.

**Hard rule:** the AI reads the same data the panels show, including staleness.
It must never present a number without its freshness, and must say "I don't know"
rather than infer a price it cannot see.

---

## 5. Open questions

- Auth for Avanza: worth the risk for real-time US + EU stocks, or leave it?
- Alpaca account needed for the US feed — free, but it's another signup.
- Multi-monitor: one browser window with a grid, or several windows?
- Does the terminal ever place orders, or stay read-only? (Read-only is the
  safer default and matches the manual-trading phase.)
- Where does it run — laptop only, or a small always-on box so alerts fire when
  the laptop is shut?

---

## 6. What this replaces

`dashboard/` (~2,200 lines) predates the session picker, the levels engine and
the DOM viewer. Starting fresh, but worth reading first for anything reusable
before it is retired.

---

## Build log

**2026-08-05 — Phase 0 + 1 complete.** `terminal/` — FastAPI + vendored
Lightweight Charts. Watchlist ranking, click-to-chart with CPR/pivot/PDH/PDL
drawn as price lines, freshness badge on every row and every chart.

    python3.13 -m terminal.app          # http://127.0.0.1:8777

Port 8777 because 8000 is occupied by another local process.

Added during the build, not in the original design: `Freshness.CLOSED`. The
first test showed OMXS30 and Ericsson flagged STALE at 66 minutes old — but
European markets had simply shut. Old data with the market closed is correct,
not broken. Without the distinction the terminal would cry wolf every evening
and the warning would stop meaning anything. `terminal/feeds/base.py` now
carries a per-market session map and `is_market_open()`.

Next: Phase 2 — WebSocket push, multi-panel grid, level-cross alerts to ntfy.

**2026-08-05 — Phase 2 complete.** WebSocket push (5s), level-cross alerts to
ntfy, and the Avanza certificate screener.

Verified live: alert armed on SPY fired once and pushed to ntfy, then returned
0 on the next tick — dedupe works. Quotes stream with freshness per symbol
(SPY realtime 0.2m, OMXS30 closed 141m).

**The unplanned find: the Avanza spread screener.** Search needed POST, not GET
(`/_api/search/filtered-search`), and it returns `orderBookId`, live price AND
**spread** for certificates, warrants and minis — instruments yfinance does not
carry at all. Measured on the same underlying:

    MINI L SP500 5 SG    277,43   spread 0,01  ->     0.004%
    BULL GULD X20 AVA 4   10,23   spread 0,10  ->     0.98%
    BULL GULD X20 SG18    0,507   spread 0,20  ->    39%
    BULL GULD X18 VT14     0,06   spread 3,45  -> 5,750%

Spread is the entire cost on Avanza Markets (commission-free >=1,000 SEK), so
picking the wrong line costs more than any edge could earn. `find_instruments()`
ranks by spread % and drops anything above 2%.

Next: Phase 3 — AI layer with tools over local data.

**2026-08-05 — indicators, uncapped.** `terminal/indicators.py`, 10 to start,
21 series when all are on: EMA 8/20/50, SMA200, Bollinger, session VWAP, CPR
bands (overlay) + RSI, MACD, ATR%, Volume, Trend Compass (own synced panes).

No limit on how many run at once — that cap is TradingView's business model,
not a technical constraint. Adding one is a function plus a REGISTRY entry.

Two things fixed while testing:
  - SMA200 returned 0 points on a 6-month chart. Indicators now compute on a
    longer warmup frame (3y for daily) and are trimmed to the display window.
  - Volume-dependent indicators drop out silently when volume is genuinely
    absent, rather than drawing a flat zero line. Verified both ways: ERIC-B.ST
    and ^OMX carry real volume so VWAP renders; spot indices without it do not.

**2026-08-05 — strategies, TTM, drawing, 1m.**

- `terminal/strategies.py` — all 9 runnable strategies on one panel, reporting
  the ones that DON'T fire too. That was the honest answer most days, and
  hiding it is how twelve unused strategies accumulated.
- **TTM Power Range** as indicator + signal markers, formula lifted verbatim
  from `production_system/live/ttm_power_range_trader.py`. 33 signals over 6
  months of SPY. This is the tool that produced ~75% of realised P&L.
- Volatility Regime and Trend Ribbon ported from the Pine guides.
- 1-minute candles.
- Drawing tools: trendline, horizontal line, highlighter box. Stored in
  price/time space, not pixels, so they stay pinned through pan and zoom.

**Avanza status.** Unauthenticated works for instrument metadata, 1-min OHLCV
with volume, and the spread screener. Order book and positions need auth.
Latency measured again at 160 min after the Swedish close — the public feed
carries the last settled bar, not live. Authenticating would unlock real-time
(their support page confirms free real-time stocks for Nordics/US/most of W.
Europe) plus order book and holdings.
