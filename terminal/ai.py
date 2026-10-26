"""
Phase 3 — AI layer, powered by `claude -p`.

Runs Claude Code headless via the local CLI, so it uses the existing Pro
subscription rather than an API key. Verified working: `claude -p` returns
cleanly with rc=0.

HOW THIS AVOIDS HALLUCINATING PRICES
------------------------------------
The model is never asked to recall or invent market data. Every question is
answered against a CONTEXT PACK assembled here in Python from the same
functions the panels use — levels.py, strategies.py, the feeds. If a number is
not in the pack, the correct answer is "I don't have that", and the prompt says
so explicitly.

Freshness travels with every quote in the pack. A 16-minute-old price is
labelled 16 minutes old, because the whole reason this terminal exists is that
a delayed DAX looked identical to a live one on 2026-08-05 and cost a trade.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SYSTEM = """You are Kes, the kestrel agent embedded in this trading terminal.

A kestrel hovers perfectly still, watching, before it commits. That is how you
work. You watch the ranges, explain what is moving, and check a plan before the
user enters. You celebrate discipline, not profit. You never place an order and
you never tell the user to buy or sell.

HOW YOU TALK
- Short sentences. Dry, never hype. Lead with the answer, then the evidence.
  No preamble, no disclaimers, no "as an AI" hedging.
- Every number carries its age and source: "982.00, one minute old, avanza-rt."
- When data is stale or missing, say "I don't know" and why -- "Nasdaq data is
  15 minutes old. I will not guess where it is now."
- You explain and you check. You do not instruct. Describe the level, the
  condition and the invalidation; never "buy now", "sell", "go long", "enter".

HOUSE RULES YOU CHECK (for any trade idea the user raises)
- Leverage cap = 100 / (3.5 x ATR%), which keeps a knockout barrier about 3.5
  ATRs away. Inside that, ordinary noise can kill the position before the
  thesis resolves. Use it whenever leverage comes up.
- A plan needs a predefined take-profit AND stop-loss before entry. If the user
  asks about entering something, the exit is part of a complete answer.
- Flag gamma/theta/decay for leveraged, short-dated or daily-reset products.
- Check earnings dates. ATR is backward-looking and understates a binary print.
- TTM Power Range, an always-on indicator, produced most historical realised
  profit; the backtested strategies have not been traded. Weight that.

RULES, in order of importance:
1. Answer ONLY from the CONTEXT below. It holds what the terminal shows: the
   market line, the TTM Power Range setups for the whole universe, the user's
   portfolio (holdings, P&L, concentration, earnings ahead) when connected,
   trade plans, the ranked watchlist, market news, and full detail for every
   symbol the user named. Use all of it. If a number is genuinely not there,
   say "not in the data I have" and, if useful, which page shows it (Chart,
   Portfolio, Disclosures) — never estimate, recall or invent a price or level.
   This matters more than sounding helpful. A confident invented level is the
   single worst thing you can produce here.
2. Always respect freshness. A quote labelled delayed or stale must be
   described that way; never present stale data as current.
3. Be concise and concrete. Cite the actual numbers you used, with their age.
4. You are not a signal generator and you never give orders. Describe what the
   data shows. "Nothing qualifies today" is a valid and often correct answer.
5. News is supplied where available. Use it only to EXPLAIN, never to predict.
   Check the age before attributing a move to a headline: a story older than
   the move did not cause it, and "the move is unexplained by the news I have"
   is a better answer than the nearest plausible narrative. If no headlines
   were found, say the move is unexplained rather than inventing a reason.
6. You see exactly what is on the user's screen — the same watchlist rows,
   levels, strategies, freshness and Avanza instruments the panels render. Talk
   about them as shared context ("SWED-A is 0.3% under its pivot"), not as a
   data dump.
7. SOURCE AND FRESHNESS ARE PART OF THE ANSWER. Every quote carries where it
   came from. avanza-rt and avanza-spot are real-time; yfinance intraday has
   stalled mid-session before, serving five-hour-old prices while the market was
   open. If a number you are leaning on is stale, say so before using it.
8. Be clear, not vague: give the level, the condition and the invalidation --
   as facts to check, never as an instruction to act.
"""

# Personal profile (who the user is, account size, habits) lives in a
# gitignored file so this repo can be public. profile.example.md is the template.
PROFILE_FILE = ROOT / "profile.local.md"


def load_profile() -> str:
    """The user's profile section, or an explicit note that none is loaded."""
    try:
        text = PROFILE_FILE.read_text().strip()
    except FileNotFoundError:
        return ("USER PROFILE: none loaded (profile.local.md is absent). Do not "
                "assume anything about the user's account size or holdings.")
    return "USER PROFILE (local, private):\n" + text


def system_prompt() -> str:
    return f"{SYSTEM}\n{load_profile()}\n"


def available() -> bool:
    return shutil.which("claude") is not None


def build_context(symbols: list[str], market: str = "us",
                  with_news: bool = True) -> dict:
    """Assemble the facts. Everything here is computed, never remembered.

    News is part of the context because price without it is unreadable: GOOGL
    fell 4% on 2026-08-05 and the terminal could describe the move precisely
    while having nothing to say about why. Headlines carry their age for the
    same reason quotes do -- a four-hour-old story is not an explanation for a
    move that happened twenty minutes ago, and the model is told to treat it
    that way rather than reaching for the nearest plausible narrative.
    """
    from concurrent.futures import ThreadPoolExecutor

    from screeners.levels import compute_levels, macd_state
    from terminal import news as NEWS
    from terminal import strategies as STRAT
    from terminal.feeds.yf import YFinanceFeed

    feed = YFinanceFeed()
    out = {"market": market, "symbols": {}}

    # Everything below mirrors what the panels render, so the assistant reasons
    # over the same picture rather than a reduced copy of it. Each block is
    # wrapped: one failing source degrades that block, never the whole answer.
    try:
        from terminal.app import AVANZA, AVANZA_AUTH, FEED as ROUTED, STREAM
        out["session"] = {
            "avanza_authenticated": AVANZA.authenticated,
            "quote_routing": ROUTED.stats() if hasattr(ROUTED, "stats") else {},
            "stream": STREAM.status(),
            "note": ("avanza-rt and avanza-spot are real-time; yfinance intraday "
                     "has stalled mid-session before"),
        }
        feed = ROUTED          # same feed the screen uses
    except Exception:
        pass

    try:
        from terminal.feeds import spot as SPOT
        from terminal.app import AVANZA as _AV
        g = SPOT.annotate("GC=F", _AV, YFinanceFeed())
        if g:
            out["gold_spot"] = {k: g[k] for k in
                                ("price", "futures", "basis", "basis_pct", "note")
                                if k in g}
    except Exception:
        pass

    # Fetched in parallel up front: one round trip per symbol regardless of how
    # long the rest of the context takes to compute.
    news_by_sym: dict[str, list] = {}
    if with_news:
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for s, n in zip(symbols[:8], pool.map(
                        lambda x: NEWS.ticker_news(x, limit=4, rank="explain",
                                                   market=market), symbols[:8])):
                    news_by_sym[s] = n
            out["market_news"] = [
                {"title": i["title"], "source": i["source"], "age_min": i["age_min"]}
                for i in NEWS.market_news(limit=8, market=market)]
        except Exception:
            out["news_error"] = "news fetch failed — treat as no news available"

    # Built in parallel. Sequentially this was the whole latency: eight symbols
    # each fetching a quote plus a year of daily bars took ~80s wall-clock, and
    # a minute of a motionless panel reads as broken even though nothing failed.
    def _one(s: str) -> tuple[str, dict | None]:
        try:
            q = feed.quote(s)
            b = feed.bars(s, "1d", "1y")
            if b is None:
                return s, None
            lv = compute_levels(b.df, s)
            sig = STRAT.run_all(b.df)
            return s, {
                "quote": q.to_dict() if q else None,
                "levels": None if lv is None else {
                    "from_session": str(lv.source_date), "stale": bool(lv.is_stale),
                    "pivot": round(lv.pivot, 2), "tc": round(lv.tc, 2), "bc": round(lv.bc, 2),
                    "pdh": round(lv.pdh, 2), "pdl": round(lv.pdl, 2),
                    "r1": round(lv.r1, 2), "s1": round(lv.s1, 2),
                    "atr_pct": None if lv.atr_pct != lv.atr_pct else round(lv.atr_pct, 2),
                    "cpr_width_pctile": (None if lv.cpr_width_pctile != lv.cpr_width_pctile
                                         else round(lv.cpr_width_pctile * 100)),
                    "cpr_verdict": lv.cpr_verdict,
                    "cpr_vs_prior_day": lv.cpr_relationship,
                    "max_leverage_by_atr": (None if not lv.atr_pct or lv.atr_pct != lv.atr_pct
                                            else round(100 / (3.5 * lv.atr_pct))),
                },
                "macd": macd_state(b.df["Close"])[0],
                "strategies": {"fired": sig["fired"], "of": sig["total"],
                               "signals": [x for x in sig["signals"] if x["fired"]] or "none firing"},
                "news": [{"title": n["title"], "source": n["source"],
                          "age_min": n["age_min"]}
                         for n in news_by_sym.get(s, [])] or "no recent headlines found",
            }
        except Exception as e:
            return s, {"error": f"{type(e).__name__}"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for sym, data in pool.map(_one, symbols[:8]):
            if data is not None:
                out["symbols"][sym] = data

    # The full ranked watchlist he is looking at, not just the charted symbols.
    # Trimmed to the columns the table shows, because the whole point is that we
    # are discussing the same screen.
    try:
        from terminal.app import analyse, load_watchlist
        syms = load_watchlist(market)[:25]
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = [r for r in pool.map(analyse, syms) if r]
        rows.sort(key=lambda r: r["score"], reverse=True)
        out["watchlist"] = [{
            "symbol": r["symbol"], "price": r["price"], "chg_pct": r["change_pct"],
            "score": r["score"], "cpr_pctile": r["cpr_pctile"],
            "to_pdh": r["to_pdh"], "to_pdl": r["to_pdl"], "atr_pct": r["atr_pct"],
            "pdh": r.get("pdh"), "pdl": r.get("pdl"), "pivot": r.get("pivot"),
            "tc": r.get("tc"), "bc": r.get("bc"), "r1": r.get("r1"), "s1": r.get("s1"),
            "max_lev": r["max_lev"], "freshness": r["freshness"],
            "source": r.get("source"), "levels_stale": r["levels_stale"],
        } for r in rows[:20]]
    except Exception:
        out["watchlist_error"] = "watchlist unavailable"
    return out


# Words that look like tickers in a question but aren't.
_NOT_TICKERS = {"I", "A", "AN", "THE", "AND", "OR", "IS", "IT", "TP", "SL", "ATR", "CPR", "RSI",
                "EMA", "SMA", "MACD", "VWAP", "US", "EU", "SE", "ETF", "AI", "OK", "PNL", "YTD",
                "TTM", "ISK", "AF", "SEK", "USD", "EUR", "CEO", "IPO", "FX", "NAV", "GDP", "CPI",
                "FED", "ECB", "Q1", "Q2", "Q3", "Q4", "UP", "DOWN", "BUY", "SELL", "WHY", "WHAT"}
_TICKER_RE = re.compile(r"(?<![\w^.])([A-Z]{1,5}(?:[.-][A-Z]{1,3})?)(?![\w])")


def _mentioned_symbols(question: str, known: dict[str, str]) -> list[str]:
    """Tickers and company names the user typed, mapped to fetchable symbols.

    `known` maps lowercase names/symbols (from the setups universe and holdings)
    to a Yahoo ticker, so "what about Volvo?" resolves without the user typing
    VOLV-B.ST. Unknown ALL-CAPS tokens are passed through as tickers.
    """
    found: list[str] = []
    low = question.lower()
    for name, sym in known.items():
        if len(name) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low):
            found.append(sym)
    for tok in _TICKER_RE.findall(question):
        if tok in _NOT_TICKERS:
            continue
        if tok.lower() in known:
            found.append(known[tok.lower()])
        elif len(tok) >= 2:        # a stray "B" (as in "Volvo B") is not a ticker
            found.append(tok)
    return list(dict.fromkeys(found))


def terminal_blocks(question: str, recent: str = "") -> tuple[dict, list[str]]:
    """What the terminal's own pages show, so Kes sees the same screen.

    Reuses the shared v2 services and their caches. The portfolio is included
    only when an Avanza session already exists: asking Kes never triggers a
    login. Returns (blocks, symbols mentioned in the question).
    """
    out: dict = {}
    known: dict[str, str] = {}
    try:
        from terminal import api_v2 as V2
        D = V2.D
    except Exception as e:
        return {"terminal_error": f"terminal services unavailable: {type(e).__name__}"}, []

    try:
        ml = D.market_line.get(D.feed, D.yf, D.avanza)
        out["market_line"] = [{k: i.get(k) for k in ("label", "last", "change_pct", "freshness",
                                                      "age_min", "source")} for i in ml["items"]]
    except Exception as e:
        out["market_line_error"] = type(e).__name__

    try:
        s = D.setups.get(None)
        out["ttm_setups"] = {
            "note": ("TTM Power Range zones, the terminal's core. state=crossed/at/near a zone; "
                     "dist_*_atr signed, positive = through the zone; hist = how past crosses "
                     "did 3 days later (win_rate and avg_fwd_ret are fractions)."),
            "as_of": s.get("as_of"),
            "rows": [{k: r.get(k) for k in ("symbol", "name", "yahoo", "trend", "state", "with_trend",
                                            "close", "zone1", "zone2", "zone3", "zone4",
                                            "dist_z1_atr", "dist_z3_atr", "atr_pct", "lev_cap",
                                            "hist", "earnings_days", "bar_date")}
                     for r in s.get("rows", [])],
            "errors": s.get("errors") or None,
        }
        for r in s.get("rows", []):
            for key in (r.get("symbol"), r.get("name"), r.get("yahoo")):
                if key:
                    known[str(key).lower()] = r["yahoo"]
    except Exception as e:
        out["ttm_setups_error"] = type(e).__name__

    if getattr(D.auth, "token", None):
        try:
            from portfolio_mcp.brief import brief_data
            b = brief_data(V2._pf(), earnings_within_days=30)
            out["portfolio"] = {
                "note": "The user's own read-only Avanza portfolio. SEK. Accounts are aliases.",
                "as_of": b.get("as_of"), "totals_sek": b.get("totals_sek"),
                "performance": b.get("performance"), "concentration": b.get("concentration"),
                "holdings": b.get("holdings"), "flags": b.get("flags"),
                "earnings_ahead": (b.get("earnings") or {}).get("upcoming"),
            }
            for h in b.get("holdings", []):
                if h.get("ticker"):
                    known[str(h["name"]).lower()] = h["ticker"]
                    known[str(h["ticker"]).lower()] = h["ticker"]
        except Exception as e:
            out["portfolio_error"] = f"portfolio unavailable: {type(e).__name__}"
    else:
        out["portfolio"] = "not connected (no Avanza session); portfolio questions cannot be answered"

    try:
        plans = D.plans.all()
        from terminal import plans as PLANS
        out["trade_plans"] = {"streak": PLANS.streak(plans), "recent": plans[:5]}
    except Exception as e:
        out["trade_plans_error"] = type(e).__name__

    now = _mentioned_symbols(question, known)
    return out, list(dict.fromkeys(now + _mentioned_symbols(recent, known)))


def ask(question: str, symbols: list[str], market: str = "us",
        timeout: int = 180, history: list[dict] | None = None) -> dict:
    if not available():
        return {"error": "claude CLI not found on PATH"}
    # Follow-ups ("what about that one?") name nothing, so the last two turns
    # are scanned too; the current question still gets priority.
    recent = " ".join(str(t.get("text", ""))[:600] for t in (history or [])[-2:]
                       if isinstance(t, dict))
    blocks, mentioned = terminal_blocks(question, recent)
    # Tickers named in the question come first: they are what was asked about.
    syms = list(dict.fromkeys(mentioned + list(symbols)))[:8]
    ctx = build_context(syms, market)
    ctx["terminal"] = blocks
    convo = ""
    if history:
        turns = [f"{'USER' if t.get('role') == 'user' else 'KES'}: {str(t.get('text', ''))[:600]}"
                 for t in history[-6:] if isinstance(t, dict)]
        if turns:
            convo = "CONVERSATION SO FAR (oldest first):\n" + "\n".join(turns) + "\n\n"
    # Compact JSON: the context is large and every token costs answer time.
    prompt = (f"{system_prompt()}\nCONTEXT (JSON, computed just now):\n"
              f"{json.dumps(ctx, separators=(',', ':'), default=str)}\n\n"
              f"{convo}QUESTION: {question}\n")
    try:
        # cwd IS the project root, always. `claude -p` picks up CLAUDE.md,
        # settings and project context from wherever it is invoked, so a session
        # launched from another directory answers with that project's context
        # bleeding in. The terminal can be started from anywhere; the subprocess
        # must not inherit that.
        # No tools, no MCP servers: the prompt carries third-party headlines,
        # and this project registers portfolio MCP servers. Kes only needs the
        # context already in the prompt, so a crafted headline gets nothing to
        # act with. Prompt goes via stdin because --tools takes a list and
        # would otherwise swallow it.
        # Kes explains numbers that are already computed; a fast model is enough
        # and cuts answer time sharply. Override with KES_MODEL (e.g. "sonnet").
        model = os.environ.get("KES_MODEL", "haiku")
        r = subprocess.run(["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config"],
                           input=prompt, capture_output=True,
                           text=True, timeout=timeout, cwd=str(ROOT))
        if r.returncode != 0:
            return {"error": f"claude exited {r.returncode}",
                    "detail": (r.stderr or "")[:300]}
        return {"answer": r.stdout.strip(), "symbols": list(ctx["symbols"])}
    except subprocess.TimeoutExpired:
        return {"error": f"claude -p timed out after {timeout}s"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
