"""
Premarket Levels Engine — CPR, Pivots, Prior-Period Levels, Expected Range
===========================================================================

Deterministic price levels computed from the prior session. No modelling, no
fitting, no backtest needed to trust them: given yesterday's high/low/close,
every number here is arithmetic that thousands of other traders are computing
the same way. That shared-reference property is most of why they work.

CENTRAL PIVOT RANGE (CPR)
    Pivot (P) = (H + L + C) / 3
    BC        = (H + L) / 2
    TC        = 2P - BC
    (TC and BC invert depending on where C sits; we always return TC as the
    upper of the two and BC as the lower.)

    The WIDTH is the actual signal, not the levels:
        narrow CPR  -> market is coiled, expect a TRENDING day
        wide CPR    -> expect a RANGE-BOUND / rotational day
    Width is scored as a percentile against the name's own recent history,
    because "narrow" only means anything relative to that instrument.

    The two-day relationship adds directional context:
        Higher Value  - today's CPR entirely above yesterday's  -> bullish
        Lower Value   - entirely below                          -> bearish
        Overlapping   - partial overlap                         -> sideways
        Outside Value - today's CPR engulfs yesterday's         -> indecision

EXPECTED RANGE
    ATR(14) is the honest expected daily range. If an ATM straddle is
    available (US names via yfinance), the options-implied move is also
    reported -- when implied is well below ATR, the market is underpricing
    movement relative to what the instrument actually does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Levels:
    ticker: str = ""
    # CPR
    pivot: float = np.nan
    tc: float = np.nan
    bc: float = np.nan
    cpr_width_pct: float = np.nan      # (TC-BC)/P as a percentage
    cpr_width_pctile: float = np.nan   # 0-1 vs own history; LOW = coiled
    cpr_verdict: str = ""              # "narrow (trend day)" / "wide (range day)"
    cpr_relationship: str = ""         # Higher/Lower/Overlapping/Outside Value
    # Classic pivots
    r1: float = np.nan
    r2: float = np.nan
    r3: float = np.nan
    s1: float = np.nan
    s2: float = np.nan
    s3: float = np.nan
    # Prior period
    pdh: float = np.nan                # prior day high
    pdl: float = np.nan
    pdc: float = np.nan
    pwh: float = np.nan                # prior week high
    pwl: float = np.nan
    # Expected range
    atr14: float = np.nan
    atr_pct: float = np.nan            # ATR as % of price
    implied_move_pct: float = np.nan   # from ATM straddle, if available
    # Context
    price: float = np.nan
    nearest_level: str = ""
    dist_to_nearest_pct: float = np.nan
    # Provenance: WHICH session these levels were derived from. CPR for day N+1
    # comes from day N's H/L/C, so if source_date is stale the levels describe a
    # session that has already traded and are useless for the next one.
    source_date: object = None
    stale_days: int = 0
    is_stale: bool = False      # older than the last completed weekday
    is_partial: bool = False    # bar dated today: still forming, H/L/C provisional


def _true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)


def _cpr(high: float, low: float, close: float) -> tuple[float, float, float]:
    """Return (pivot, tc, bc) with tc always the upper bound."""
    p = (high + low + close) / 3
    bc = (high + low) / 2
    tc = 2 * p - bc
    return p, max(tc, bc), min(tc, bc)


def compute_levels(df: pd.DataFrame, ticker: str = "",
                   hist_window: int = 120) -> Levels | None:
    """Levels for the CURRENT session from the PRIOR session's bar.

    `df` is daily OHLC, oldest first. The last row is treated as the most
    recent completed session, so this is a pre-market tool: run it before the
    open and it describes the day ahead.
    """
    if df is None or len(df) < 25:
        return None

    # Drop unsettled bars. yfinance returns TODAY's row for NSE names with a
    # volume figure but NaN OHLC while the session is still in progress or not
    # yet settled. Taking .iloc[-1] off that row silently makes every level NaN
    # — confirmed on RELIANCE.NS, 2026-08-03. Always compute from the last
    # bar that actually has prices.
    df = df.dropna(subset=["High", "Low", "Close"])
    if len(df) < 25:
        return None

    lv = Levels(ticker=ticker)

    # Record which session these levels come from, and how stale it is in
    # CALENDAR days. Data vendors lag: NSE bars from yfinance routinely have not
    # settled until the following day, so a run "before tomorrow's open" can
    # silently hand you levels for a session that already traded.
    src = df.index[-1]
    lv.source_date = src.date() if hasattr(src, "date") else src
    try:
        import datetime as _dt
        today = _dt.date.today()
        lv.stale_days = (today - lv.source_date).days
        # Weekday-aware: the newest bar we should have is the most recent
        # weekday BEFORE today. A plain day-count threshold false-negatives on
        # Tuesdays (2-day gap looks small) and false-positives on Mondays
        # (Friday is 3 calendar days back but perfectly fresh).
        prev = today - _dt.timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= _dt.timedelta(days=1)
        lv.is_stale = lv.source_date < prev
        # A bar dated today is still forming -- its H/L/C can change, so CPR
        # built from it is provisional.
        lv.is_partial = lv.source_date >= today
    except Exception:
        lv.stale_days, lv.is_stale, lv.is_partial = 0, False, False

    h, l, c = float(df["High"].iloc[-1]), float(df["Low"].iloc[-1]), float(df["Close"].iloc[-1])
    lv.price = c
    lv.pdh, lv.pdl, lv.pdc = h, l, c

    # --- CPR for the coming session ---
    lv.pivot, lv.tc, lv.bc = _cpr(h, l, c)
    lv.cpr_width_pct = (lv.tc - lv.bc) / lv.pivot * 100 if lv.pivot else np.nan

    # Width percentile against this name's own recent history. "Narrow" is
    # meaningless in absolute terms -- it only exists relative to the
    # instrument's normal.
    widths = []
    for i in range(max(1, len(df) - hist_window), len(df)):
        ph, pl, pc = float(df["High"].iloc[i]), float(df["Low"].iloc[i]), float(df["Close"].iloc[i])
        p_, tc_, bc_ = _cpr(ph, pl, pc)
        if p_:
            widths.append((tc_ - bc_) / p_ * 100)
    if len(widths) >= 20:
        lv.cpr_width_pctile = float(np.mean(np.array(widths) < lv.cpr_width_pct))
        if lv.cpr_width_pctile <= 0.35:
            lv.cpr_verdict = "narrow → trend day"
        elif lv.cpr_width_pctile >= 0.65:
            lv.cpr_verdict = "wide → range day"
        else:
            lv.cpr_verdict = "average"

    # --- Two-day CPR relationship ---
    if len(df) >= 2:
        ph, pl, pc = float(df["High"].iloc[-2]), float(df["Low"].iloc[-2]), float(df["Close"].iloc[-2])
        _, ptc, pbc = _cpr(ph, pl, pc)
        if lv.bc > ptc:
            lv.cpr_relationship = "Higher Value (bullish)"
        elif lv.tc < pbc:
            lv.cpr_relationship = "Lower Value (bearish)"
        elif lv.tc >= ptc and lv.bc <= pbc:
            lv.cpr_relationship = "Outside Value (indecision)"
        else:
            lv.cpr_relationship = "Overlapping (sideways)"

    # --- Classic pivots ---
    rng = h - l
    lv.r1, lv.s1 = 2 * lv.pivot - l, 2 * lv.pivot - h
    lv.r2, lv.s2 = lv.pivot + rng, lv.pivot - rng
    lv.r3, lv.s3 = h + 2 * (lv.pivot - l), l - 2 * (h - lv.pivot)

    # --- Prior week (last 5 completed sessions) ---
    if len(df) >= 5:
        lv.pwh = float(df["High"].iloc[-5:].max())
        lv.pwl = float(df["Low"].iloc[-5:].min())

    # --- Expected range ---
    atr = _true_range(df).ewm(alpha=1 / 14, adjust=False).mean()
    lv.atr14 = float(atr.iloc[-1])
    lv.atr_pct = lv.atr14 / c * 100 if c else np.nan

    # --- Nearest level to current price ---
    candidates = {
        "Pivot": lv.pivot, "TC": lv.tc, "BC": lv.bc,
        "R1": lv.r1, "R2": lv.r2, "S1": lv.s1, "S2": lv.s2,
        "PDH": lv.pdh, "PDL": lv.pdl, "PWH": lv.pwh, "PWL": lv.pwl,
    }
    valid = {k: v for k, v in candidates.items() if v == v and v > 0}
    if valid:
        name = min(valid, key=lambda k: abs(valid[k] - c))
        lv.nearest_level = name
        lv.dist_to_nearest_pct = (c - valid[name]) / c * 100

    return lv


def implied_move_from_straddle(ticker: str, price: float) -> float:
    """ATM straddle price as a % of spot — the options market's expected move.

    Only works where yfinance carries real option chains (US names). Applies
    the same live-quote guards as watchlist_core: Yahoo returns placeholder
    values for contracts with no market, and a straddle built from those is
    fiction. Returns NaN when it cannot be computed honestly.
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        expiries = tk.options
        if not expiries:
            return float("nan")
        chain = tk.option_chain(expiries[0])
        calls, puts = chain.calls, chain.puts
        if calls.empty or puts.empty:
            return float("nan")

        def _atm(df):
            live = df[(df["bid"] > 0) & (df["ask"] > 0)
                      & ((df["strike"] - price).abs() <= price * 0.05)]
            if live.empty:
                return None
            row = live.iloc[(live["strike"] - price).abs().argsort().iloc[0]]
            return float((row["bid"] + row["ask"]) / 2)

        c_mid, p_mid = _atm(calls), _atm(puts)
        if c_mid is None or p_mid is None:
            return float("nan")
        return (c_mid + p_mid) / price * 100
    except Exception:
        return float("nan")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Standard MACD. Returns (macd_line, signal_line, histogram)."""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    line = ema_f - ema_s
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def macd_state(close: pd.Series) -> tuple[str, int]:
    """(verdict, bars_since_cross). Direction of momentum, and how fresh it is.

    A cross 1-3 bars old is information; one 40 bars old is just the trend.
    """
    line, sig, hist = macd(close)
    if len(hist.dropna()) < 2:
        return "n/a", -1
    above = hist.iloc[-1] > 0
    bars = 0
    for i in range(len(hist) - 1, 0, -1):
        if (hist.iloc[i] > 0) != above:
            break
        bars += 1
    verdict = "bullish" if above else "bearish"
    if bars <= 3:
        verdict += f" (fresh cross, {bars}b)"
    return verdict, bars
