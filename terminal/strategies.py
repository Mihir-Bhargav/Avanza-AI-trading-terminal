"""
Strategy signal engine — every strategy in this repo, on one screen.

This is the terminal's actual advantage over TradingView: your strategies are
Python, they live here, and nothing else can run them.

HONEST FRAMING, carried over from the 2026-08-04 audit so it is not quietly
forgotten: twelve strategies exist and **zero** have been traded. ~75% of all
realised profit came from TTM Power Range, an always-on indicator, not from any
rare-firing backtested strategy. So this panel reports state for ALL of them and
says plainly when nothing fires — because "nothing fires" was the honest answer
on most days, and hiding it is how twelve unused strategies accumulated.

Each strategy returns:
    fired    bool
    side     BUY / SELL / NEUTRAL
    reason   why, in one line, including the numbers that decided it
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-10))


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _r(name, fired, side, reason):
    return {"name": name, "fired": bool(fired), "side": side, "reason": reason}


# ---------------------------------------------------------------- strategies

def bb_reversion(df):
    """BB lower cross + RSI<42. Backtested on 5m bars (Sharpe 3.04 GLD /
    2.77 SPY) — on daily bars this is a DIFFERENT strategy, so it is labelled."""
    c = df["Close"]; m = c.rolling(20).mean(); s = c.rolling(20).std()
    lo, hi = m - 2.5 * s, m + 2.5 * s
    pb = float((c.iloc[-1] - lo.iloc[-1]) / (hi.iloc[-1] - lo.iloc[-1] + 1e-10))
    r = float(_rsi(c).iloc[-1])
    f = pb < 0.20 and r < 42
    return _r("BB_Reversion", f, "BUY" if f else "NEUTRAL",
              f"%B={pb:.2f} (<0.20), RSI={r:.0f} (<42)")


def gap_fade(df):
    """Overnight gap >2.5% fades. WR 72.7% — the highest win rate in the repo,
    and it has never been traded. Measured base rate: after a >+3% gap the
    intraday mean is -0.21% and negative 56% of the time."""
    if len(df) < 2:
        return _r("Gap_Fade", False, "NEUTRAL", "insufficient history")
    gap = float(df["Open"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100
    f = abs(gap) > 2.5
    return _r("Gap_Fade", f, ("SELL" if gap > 0 else "BUY") if f else "NEUTRAL",
              f"gap {gap:+.2f}% (needs |gap|>2.5%)")


def orb(df):
    """Opening range breakout — needs intraday bars; reports so on daily."""
    return _r("ORB", False, "NEUTRAL", "needs intraday bars (switch to 5m/15m)")


def gamma_blast(df):
    """NIFTY compression setup: NR7 or ATR5/ATR20<0.85. PF 3.62 backtested."""
    rng = df["High"] - df["Low"]
    nr7 = bool((rng == rng.rolling(7).min()).iloc[-1])
    tr = _atr(df, 1)
    ratio = float((tr.rolling(5).mean() / tr.rolling(20).mean()).iloc[-1])
    f = nr7 or ratio < 0.85
    return _r("Gamma_Blast", f, "STRADDLE" if f else "NEUTRAL",
              f"NR7={nr7}, ATR5/20={ratio:.2f} (<0.85)")


def indian_theta(df):
    r = float(_rsi(df["Close"]).iloc[-1])
    f = r > 70 or r < 30
    return _r("Indian_Theta", f, ("BUY" if r < 30 else "SELL") if f else "NEUTRAL",
              f"RSI={r:.0f} (needs <30 or >70)")


def vrp(df):
    """VIX>20 + RSI<40. VIX is global, so this reports the RSI leg only."""
    r = float(_rsi(df["Close"]).iloc[-1])
    return _r("VRP", False, "NEUTRAL", f"RSI={r:.0f} (<40); VIX leg needs ^VIX>20")


def structural_levels(df):
    if "Volume" not in df or float(df["Volume"].sum()) == 0:
        return _r("Structural_Levels", False, "NEUTRAL", "no volume — needs futures/stocks")
    px, vol = df["Close"].tail(120), df["Volume"].tail(120)
    bins = pd.cut(px, 20)
    hvn = vol.groupby(bins, observed=True).sum().idxmax()
    mid = float((hvn.left + hvn.right) / 2)
    last = float(df["Close"].iloc[-1])
    dist = (last / mid - 1) * 100
    f = abs(dist) < 0.5
    return _r("Structural_Levels", f, "WATCH" if f else "NEUTRAL",
              f"HVN {mid:,.2f}, price {dist:+.2f}% away (<0.5% = at node)")


def ttm_power_range(df):
    """The one that has actually made money. ~75% of realised P&L."""
    if len(df) < 12:
        return _r("TTM_Power_Range ★", False, "NEUTRAL", "insufficient history")
    rng = (df["High"] - df["Low"]).iloc[-11:-1][::-1].values
    o = float(df["Open"].iloc[-1])
    r10 = float(rng[:10].sum())
    z2, z4 = o + r10 / 10 / 2, o - r10 / 10 / 2
    prev, curr = float(df["Close"].iloc[-2]), float(df["Close"].iloc[-1])
    e = float(df["Close"].ewm(span=8, adjust=False).mean().iloc[-1])
    if prev <= z2 < curr and curr > e:
        return _r("TTM_Power_Range ★", True, "BUY", f"crossed z2 {z2:,.2f}, above EMA8 {e:,.2f}")
    if prev >= z4 > curr and curr < e:
        return _r("TTM_Power_Range ★", True, "SELL", f"crossed z4 {z4:,.2f}, below EMA8 {e:,.2f}")
    return _r("TTM_Power_Range ★", False, "NEUTRAL",
              f"price {curr:,.2f} between z4 {z4:,.2f} and z2 {z2:,.2f}")


def bigmove_ml(df):
    """Volatility clustering → big move likely. AUC 0.74-0.89. Direction is NOT
    predictable, only magnitude — hence STRADDLE, which needs options."""
    ret = df["Close"].pct_change()
    rv = ret.rolling(5).std() / ret.rolling(20).std()
    v = float(rv.iloc[-1])
    f = v > 1.3
    return _r("BigMove_ML", f, "STRADDLE" if f else "NEUTRAL",
              f"vol ratio 5/20 = {v:.2f} (>1.3). Needs options — a linear cert cannot express it.")


REGISTRY = [bb_reversion, gap_fade, orb, gamma_blast, indian_theta,
            vrp, structural_levels, ttm_power_range, bigmove_ml]


def run_all(df: pd.DataFrame) -> dict:
    out = []
    for fn in REGISTRY:
        try:
            out.append(fn(df))
        except Exception as e:
            out.append(_r(fn.__name__, False, "ERROR", f"{type(e).__name__}: {e}"))
    fired = [s for s in out if s["fired"]]
    out.sort(key=lambda s: (not s["fired"], s["name"]))
    return {"signals": out, "fired": len(fired), "total": len(out)}
