"""
Daily Watchlist Core -- Shared Asset-Selection Engine
=======================================================

Answers "which of these N names deserve attention TODAY," the way a prop
desk's morning scan works, adapted to free data sources. Used by
run_watchlist_india.py / _us.py / _sweden.py, each supplying a universe
and market-specific context (VIX regime, trading hours).

WHAT INSTITUTIONS ACTUALLY SCREEN FOR (this module implements simplified,
honest versions of each):

1. RELATIVE VOLUME (RVOL) -- the #1 "is this stock in play" filter on every
   prop desk scanner (Trade Ideas, Benzinga Pro). Volume vs its own 20-day
   average; >2x is the traditional "something is happening" threshold.

2. GAP / MOMENTUM -- overnight or recent price displacement. Gaps combined
   with above-average volume in the same direction are a classic signal
   that a name has a live catalyst, not just noise.

3. UNUSUAL OPTIONS ACTIVITY (UOA) proxy -- real UOA needs a paid options-flow
   feed (sweep detection, block trades). We approximate with what's free:
   options volume / open interest ratio, and volume vs the stock's own
   recent average options volume. A ratio >=1.25 with volume >500 is a
   commonly cited simplified UOA screen threshold.

4. VOLATILITY CONTEXT -- IV vs realized vol (a rough IV-rank proxy; true
   IV rank needs a year of daily IV history that isn't freely available).
   Professional premium sellers want IV rank/percentile >50-70 before
   selling; premium BUYERS (this account's stated bias) want the opposite
   -- IV cheap relative to what realized vol/recent range would justify.

5. TECHNICAL SETUP -- RSI(14) extremes (mean reversion), Bollinger Band
   width (compression -> expansion, same logic as Gamma Blast), distance
   from 20/50-day SMA (trend location), proximity to 52-week high/low.

6. NEWS / CATALYST TAGGING -- real headlines (Yahoo Finance news feed) run
   through a simple keyword tagger (earnings, upgrade/downgrade, M&A,
   guidance, regulatory, macro). This is explicitly NOT NLP sentiment --
   it's a transparent keyword heuristic, labeled as such throughout.

7. LIQUIDITY FLOOR -- hard cutoff, not scored: minimum average dollar
   volume so nothing illiquid/impossible-to-fill makes the list.

Composite score = weighted sum of the above, liquidity-gated. Every score
component is printed alongside the ranking so nothing is a black box.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

CATALYST_KEYWORDS = {
    "earnings": ["earnings", "eps", "quarterly results", "q1", "q2", "q3", "q4", "revenue"],
    "upgrade": ["upgrade", "raised target", "buy rating", "outperform", "overweight"],
    "downgrade": ["downgrade", "cut target", "sell rating", "underperform", "underweight"],
    "M&A": ["acquisition", "merger", "acquire", "takeover", "buyout"],
    "guidance": ["guidance", "forecast raised", "forecast cut", "outlook"],
    "regulatory": ["fda", "regulatory", "investigation", "lawsuit", "antitrust", "sec filing"],
    "macro": ["fed", "rate decision", "inflation", "cpi", "jobs report", "rbi", "riksbank", "central bank"],
    "corporate_action": ["buyback", "dividend", "stock split", "spin-off"],
}
POSITIVE_WORDS = ["beat", "surge", "soar", "rally", "jump", "record", "strong", "raise", "upgrade", "outperform"]
NEGATIVE_WORDS = ["miss", "plunge", "slump", "fall", "cut", "downgrade", "weak", "warning", "lawsuit", "investigation"]


@dataclass
class AssetSnapshot:
    ticker: str
    display_name: str = ""
    price: float = np.nan
    rvol: float = np.nan
    gap_pct: float = np.nan
    rsi14: float = np.nan
    rsi14_1w_ago: float = np.nan
    bb_width_pctile: float = np.nan  # 0-1, low = compressed
    dist_from_sma20: float = np.nan
    dist_52w_high: float = np.nan
    dist_52w_low: float = np.nan
    realized_vol_21d: float = np.nan
    iv_atm: float = np.nan  # if options data available
    iv_vs_rv: float = np.nan  # iv / realized_vol, >1 = rich, <1 = cheap
    options_vol_oi_ratio: float = np.nan
    headlines: list = field(default_factory=list)
    catalyst_tags: list = field(default_factory=list)
    news_sentiment: int = 0  # simple keyword count, not NLP
    dollar_volume: float = np.nan
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)


def _rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def _bb_width(prices: pd.Series, period: int = 20, std: float = 2.0) -> pd.Series:
    sma = prices.rolling(period).mean()
    sd = prices.rolling(period).std()
    return (sd * std * 2) / (sma + 1e-10)


def fetch_snapshot(ticker: str, display_name: str = "") -> AssetSnapshot | None:
    """Pull ~1 year of daily history + recent news for one ticker."""
    import yfinance as yf

    snap = AssetSnapshot(ticker=ticker, display_name=display_name or ticker)
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1y")
        if len(hist) < 60:
            return None

        close = hist["Close"]
        vol = hist["Volume"]

        snap.price = float(close.iloc[-1])
        avg_vol20 = vol.rolling(20).mean().iloc[-1]
        snap.rvol = float(vol.iloc[-1] / avg_vol20) if avg_vol20 > 0 else np.nan
        snap.gap_pct = float((hist["Open"].iloc[-1] / close.iloc[-2] - 1) * 100) if len(hist) > 1 else np.nan

        rsi = _rsi(close, 14)
        snap.rsi14 = float(rsi.iloc[-1])
        snap.rsi14_1w_ago = float(rsi.iloc[-6]) if len(rsi) > 6 else np.nan

        bbw = _bb_width(close, 20)
        bbw_valid = bbw.dropna()
        if len(bbw_valid) > 20:
            snap.bb_width_pctile = float((bbw_valid < bbw_valid.iloc[-1]).mean())

        sma20 = close.rolling(20).mean().iloc[-1]
        snap.dist_from_sma20 = float((snap.price / sma20 - 1) * 100) if sma20 > 0 else np.nan

        high52 = close.rolling(252, min_periods=60).max().iloc[-1]
        low52 = close.rolling(252, min_periods=60).min().iloc[-1]
        snap.dist_52w_high = float((snap.price / high52 - 1) * 100) if high52 > 0 else np.nan
        snap.dist_52w_low = float((snap.price / low52 - 1) * 100) if low52 > 0 else np.nan

        daily_ret = close.pct_change().dropna()
        snap.realized_vol_21d = float(daily_ret.tail(21).std() * np.sqrt(252) * 100)

        snap.dollar_volume = float(snap.price * vol.rolling(20).mean().iloc[-1])

        # News (real headlines from Yahoo Finance)
        try:
            news = tk.news or []
            for item in news[:6]:
                content = item.get("content", item)
                title = content.get("title", "")
                if title:
                    snap.headlines.append(title)
        except Exception:
            pass

        snap.catalyst_tags = _tag_catalysts(snap.headlines)
        snap.news_sentiment = _score_sentiment(snap.headlines)

        # Options context, best-effort (only works for exchanges yfinance covers options for)
        # IMPORTANT: yfinance/Yahoo returns impliedVolatility ~= 0.00001 as a
        # PLACEHOLDER when a contract has no live bid/ask -- not a real value.
        # Blindly taking the nearest-strike contract picks up this garbage on
        # thinly-quoted names/expiries (confirmed 2026-07-13 on GS: ATM read
        # 0.0% IV when real GS IV is ~20-30%). Fix: only accept a contract
        # with an actual two-sided market (bid>0 AND ask>0), and sanity-bound
        # the result -- reject anything outside a plausible 3%-300% IV range.
        try:
            expiries = tk.options
            if expiries:
                chain = tk.option_chain(expiries[0])
                calls = chain.calls
                # require an actual two-sided market AND real recent volume --
                # a live quote with zero volume can still be a stale carryover.
                # Also hard-bound moneyness (within 10% of spot) so a sparse
                # live-set can never fall back to a deep ITM/OTM contract,
                # whose back-solved IV isn't representative of ATM vol.
                moneyness_ok = (calls["strike"] - snap.price).abs() <= snap.price * 0.10
                live = calls[(calls["bid"] > 0) & (calls["ask"] > 0)
                            & (calls["volume"].fillna(0) > 0) & moneyness_ok]
                if not live.empty:
                    live = live.assign(dist=(live["strike"] - snap.price).abs()).sort_values("dist")
                    near = live[live["impliedVolatility"].between(0.03, 2.0)].head(3)
                    if not near.empty:
                        snap.iv_atm = float(near["impliedVolatility"].median() * 100)
                        snap.iv_vs_rv = float(snap.iv_atm / snap.realized_vol_21d) if snap.realized_vol_21d > 0 else np.nan
                if not calls.empty:
                    vol_sum = calls["volume"].fillna(0).sum() + chain.puts["volume"].fillna(0).sum()
                    oi_sum = calls["openInterest"].fillna(0).sum() + chain.puts["openInterest"].fillna(0).sum()
                    if oi_sum > 0:
                        snap.options_vol_oi_ratio = float(vol_sum / oi_sum)
        except Exception:
            pass

        return snap
    except Exception:
        return None


def _tag_catalysts(headlines: list[str]) -> list[str]:
    text = " ".join(headlines).lower()
    tags = []
    for tag, keywords in CATALYST_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags


def _score_sentiment(headlines: list[str]) -> int:
    """Simple keyword count, NOT NLP sentiment analysis. Transparently naive."""
    text = " ".join(headlines).lower()
    pos = sum(text.count(w) for w in POSITIVE_WORDS)
    neg = sum(text.count(w) for w in NEGATIVE_WORDS)
    return pos - neg


DEFAULT_WEIGHTS = {
    "rvol": 0.25,           # is this name "in play" today
    "gap": 0.10,             # overnight displacement
    "rsi_extreme": 0.15,     # mean-reversion setup
    "compression": 0.15,     # vol compression -> expansion candidate (long-convexity bias)
    "catalyst": 0.20,        # real news catalyst present
    "options_activity": 0.10,  # UOA proxy
    "cheap_iv": 0.05,        # IV cheap vs realized (favors premium buyers)
}


def compute_score(snap: AssetSnapshot, weights: dict = None) -> AssetSnapshot:
    w = weights or DEFAULT_WEIGHTS
    breakdown = {}

    breakdown["rvol"] = min(snap.rvol / 3.0, 1.0) * w["rvol"] if not np.isnan(snap.rvol) else 0
    breakdown["gap"] = min(abs(snap.gap_pct) / 3.0, 1.0) * w["gap"] if not np.isnan(snap.gap_pct) else 0
    rsi_dist = max(abs(snap.rsi14 - 50) - 15, 0) / 35 if not np.isnan(snap.rsi14) else 0
    breakdown["rsi_extreme"] = min(rsi_dist, 1.0) * w["rsi_extreme"]
    compression_score = (1 - snap.bb_width_pctile) if not np.isnan(snap.bb_width_pctile) else 0
    breakdown["compression"] = compression_score * w["compression"]
    breakdown["catalyst"] = min(len(snap.catalyst_tags) / 2.0, 1.0) * w["catalyst"]
    breakdown["options_activity"] = (min(snap.options_vol_oi_ratio / 1.5, 1.0) * w["options_activity"]
                                     if not np.isnan(snap.options_vol_oi_ratio) else 0)
    breakdown["cheap_iv"] = (max(1 - snap.iv_vs_rv, 0) * w["cheap_iv"]
                             if not np.isnan(snap.iv_vs_rv) else 0)

    snap.score_breakdown = breakdown
    snap.score = sum(breakdown.values())
    return snap


def screen_universe(tickers: dict[str, str], min_dollar_volume: float = 0,
                    weights: dict = None, top_n: int = 15) -> list[AssetSnapshot]:
    """tickers: {yfinance_symbol: display_name}. Returns top_n ranked snapshots."""
    results = []
    for sym, name in tickers.items():
        snap = fetch_snapshot(sym, name)
        if snap is None:
            continue
        if not np.isnan(snap.dollar_volume) and snap.dollar_volume < min_dollar_volume:
            continue
        compute_score(snap, weights)
        results.append(snap)

    results.sort(key=lambda s: s.score, reverse=True)
    return results[:top_n]


class C:
    GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
    CYAN = "\033[96m"; BOLD = "\033[1m"; END = "\033[0m"; DIM = "\033[2m"


def print_watchlist(results: list[AssetSnapshot], market_name: str, options_note: str = ""):
    now = datetime.now()
    print(f"\n{C.BOLD}{C.CYAN}{'='*115}{C.END}")
    print(f"{C.BOLD}DAILY WATCHLIST — {market_name}{C.END} — {now:%Y-%m-%d %H:%M}")
    print(f"{C.BOLD}{C.CYAN}{'='*115}{C.END}")
    if options_note:
        print(f"{C.DIM}{options_note}{C.END}")
    print()

    if not results:
        print(f"{C.YELLOW}No names passed the liquidity/data filters.{C.END}\n")
        return

    for i, s in enumerate(results, 1):
        rsi_color = C.RED if s.rsi14 > 70 else (C.GREEN if s.rsi14 < 30 else C.END)
        print(f"{C.BOLD}{i}. {s.display_name} ({s.ticker}){C.END}  "
              f"score={C.BOLD}{s.score:.2f}{C.END}  price={s.price:.2f}")
        print(f"   RVOL: {s.rvol:.2f}x  |  Gap: {s.gap_pct:+.2f}%  |  "
              f"RSI14: {rsi_color}{s.rsi14:.0f}{C.END} (1wk ago: {s.rsi14_1w_ago:.0f})  |  "
              f"BB compression pctile: {s.bb_width_pctile:.0%}" if not np.isnan(s.bb_width_pctile) else
              f"   RVOL: {s.rvol:.2f}x  |  Gap: {s.gap_pct:+.2f}%  |  RSI14: {rsi_color}{s.rsi14:.0f}{C.END}")
        print(f"   vs SMA20: {s.dist_from_sma20:+.1f}%  |  vs 52w high: {s.dist_52w_high:+.1f}%  |  "
              f"vs 52w low: {s.dist_52w_low:+.1f}%  |  Realized vol(21d): {s.realized_vol_21d:.1f}%")
        if not np.isnan(s.iv_atm):
            rich_cheap = "RICH" if s.iv_vs_rv > 1.15 else ("CHEAP" if s.iv_vs_rv < 0.85 else "fair")
            print(f"   ATM IV: {s.iv_atm:.1f}%  |  IV/RV: {s.iv_vs_rv:.2f} ({rich_cheap})  |  "
                  f"Options Vol/OI: {s.options_vol_oi_ratio:.2f}" if not np.isnan(s.options_vol_oi_ratio) else
                  f"   ATM IV: {s.iv_atm:.1f}%  |  IV/RV: {s.iv_vs_rv:.2f} ({rich_cheap})")
        if s.catalyst_tags:
            sent = "+" if s.news_sentiment > 0 else ("-" if s.news_sentiment < 0 else "~")
            print(f"   {C.YELLOW}Catalysts: {', '.join(s.catalyst_tags)} (headline tone: {sent}){C.END}")
        if s.headlines:
            print(f"   {C.DIM}News: {s.headlines[0][:90]}{C.END}")
        print()

    print(f"{C.BOLD}{C.CYAN}{'='*115}{C.END}\n")
