"""
Trend Compass — a daily market-state readout
=============================================

Unlike every strategy in this repo, this NEVER sits idle. It emits a state
every single bar, because the question it answers is "what kind of market am I
in right now" — and that always has an answer. There is no such thing as a day
with no trend state; there are only days with a weak one.

That makes it an indicator, not a signal generator. It does not tell you to
buy. It tells you which way the weight of evidence is leaning and how strongly,
so you know whether to be looking for longs, looking for shorts, or standing
aside — before you go hunting for an entry.

===========================================================================
BACKTEST RESULT — READ THIS BEFORE TRADING OFF IT
===========================================================================
This was validated in backtests/trend_compass_backtest.py over 10 years of
daily bars across 10 tickers (SPY, QQQ, NIFTY, BankNifty, AAPL, MSFT, NVDA,
RELIANCE, HDFCBANK, INFY). The test asked whether the five states are followed
by forward returns in the RIGHT ORDER.

    They are not. The ordering is INVERTED at every horizon tested.

    Horizon    Strong Down    Strong Up    rank corr
      1d          +0.22%        +0.09%       -0.10
      3d          +0.45%        +0.23%       -1.00
      5d          +0.60%        +0.38%       -0.70
     20d          +1.98%        +1.70%       -0.90
     60d          +7.04%        +5.05%       -1.00

Only 1 of 10 tickers showed correct ordering at the 5-day horizon.

WHAT THIS MEANS: the Compass describes trend state accurately, but trend state
does NOT predict forward returns in the direction a trend-follower would
assume. Buying strength underperformed buying weakness across this sample —
consistent with the documented short-term reversal effect in liquid equities.

SO USE IT AS: a DESCRIPTION of where the market is, useful for regime
awareness and for deciding which of your strategies suits today's conditions.

DO NOT USE IT AS: a directional entry signal. It has no demonstrated edge in
that role, and this file will keep saying so until a test shows otherwise.

The inversion is consistent enough to be interesting, but do NOT flip it into
a contrarian signal on this evidence: the sample is one broadly bullish decade,
windows overlap heavily, and the ticker set is small. That would be fitting the
sample, which is the exact failure mode this repo has already been burned by.
===========================================================================

SEVEN COMPONENTS, each scored -1 (bearish) to +1 (bullish):

    1. CPR zone       price above TC / inside / below BC
    2. EMA stack      8 > 20 > 50 and price above the stack, or the inverse
    3. Long regime    price vs SMA200, the single most-watched line there is
    4. MACD           histogram sign, scaled by whether it is expanding
    5. RSI regime     RSI as a bias reading (>55 / <45), NOT as an extreme
    6. Structure      higher-highs-and-higher-lows over a 20-bar window
    7. Location       where price sits inside its own 20-day range

Composite = weighted mean of the seven. ADX then gates CONFIDENCE, never
direction: a +0.6 score in a 12-ADX chop is the same lean as in a 35-ADX trend,
but you should size it very differently, and the confidence figure says so.

Everything is computed from the bar's own close and earlier data only. No
lookahead: state at bar t uses data through t, which is what makes the
backtest in backtests/trend_compass_backtest.py honest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# Component weights. Kept flat-ish deliberately: this is a consensus reading,
# and heavily tuned weights on seven correlated trend measures is exactly how
# you overfit a number that looks smart and predicts nothing.
WEIGHTS = {
    "cpr_zone": 0.15,
    "ema_stack": 0.20,
    "long_regime": 0.15,
    "macd": 0.15,
    "rsi_regime": 0.10,
    "structure": 0.15,
    "location": 0.10,
}

STATES = ["Strong Down", "Down", "Neutral", "Up", "Strong Up"]


@dataclass
class CompassReading:
    date: pd.Timestamp
    ticker: str
    close: float
    score: float             # -1 .. +1
    state: str
    confidence: float        # 0 .. 1, driven by ADX and component agreement
    adx: float
    agreement: float         # fraction of components agreeing with the sign
    components: dict


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-10))


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df["High"].diff(), -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / (atr + 1e-10)
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / (atr + 1e-10)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def compute_components(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorised: one row per bar, one column per component, each in -1..+1."""
    close, high, low = df["Close"], df["High"], df["Low"]
    out = pd.DataFrame(index=df.index)

    # 1. CPR zone — built from the PRIOR bar, which is how CPR is defined.
    pivot = (high.shift() + low.shift() + close.shift()) / 3
    bc_raw = (high.shift() + low.shift()) / 2
    tc_raw = 2 * pivot - bc_raw
    tc, bc = np.maximum(tc_raw, bc_raw), np.minimum(tc_raw, bc_raw)
    out["cpr_zone"] = np.where(close > tc, 1.0, np.where(close < bc, -1.0, 0.0))

    # 2. EMA stack
    e8, e20, e50 = _ema(close, 8), _ema(close, 20), _ema(close, 50)
    bull = (e8 > e20) & (e20 > e50) & (close > e8)
    bear = (e8 < e20) & (e20 < e50) & (close < e8)
    partial_bull = (e8 > e20) & ~bull
    partial_bear = (e8 < e20) & ~bear
    out["ema_stack"] = np.select([bull, bear, partial_bull, partial_bear],
                                 [1.0, -1.0, 0.4, -0.4], default=0.0)

    # 3. Long-term regime — distance from SMA200, saturating at +/-10%.
    sma200 = close.rolling(200, min_periods=50).mean()
    out["long_regime"] = ((close / sma200 - 1) / 0.10).clip(-1, 1)

    # 4. MACD — sign of the histogram, amplified when it is expanding.
    line = _ema(close, 12) - _ema(close, 26)
    sig = line.ewm(span=9, adjust=False).mean()
    hist = line - sig
    expanding = hist.abs() > hist.abs().shift()
    out["macd"] = np.sign(hist) * np.where(expanding, 1.0, 0.5)

    # 5. RSI as a REGIME reading, not an extreme one. 50 is the pivot; this
    #    deliberately does not fade high RSI, because in a real trend high RSI
    #    is confirmation, not a reversal signal.
    rsi = _rsi(close, 14)
    out["rsi_regime"] = ((rsi - 50) / 20).clip(-1, 1)

    # 6. Structure — higher highs and higher lows over 20 bars.
    hh = high.rolling(20).max()
    ll = low.rolling(20).min()
    out["structure"] = np.select(
        [(hh > hh.shift(10)) & (ll > ll.shift(10)),
         (hh < hh.shift(10)) & (ll < ll.shift(10))],
        [1.0, -1.0], default=0.0)

    # 7. Location inside the 20-day range: 1 at the highs, -1 at the lows.
    rng = hh - ll
    out["location"] = np.where(rng > 0, ((close - ll) / rng * 2 - 1), 0.0)

    return out.fillna(0.0)


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add score / state / confidence columns to a component frame."""
    comp = compute_components(df)
    score = sum(comp[k] * w for k, w in WEIGHTS.items()) / sum(WEIGHTS.values())

    res = comp.copy()
    res["score"] = score.clip(-1, 1)
    res["adx"] = _adx(df)

    # Agreement: how many components share the composite's sign. Seven
    # measures all pointing one way is a different thing from four-versus-three
    # netting out to the same number.
    signs = np.sign(comp[list(WEIGHTS)])
    res["agreement"] = signs.eq(np.sign(score), axis=0).sum(axis=1) / len(WEIGHTS)

    # ADX gates confidence only. A strong lean in a chop is still a lean, but
    # it deserves smaller size, and this is where that gets said.
    adx_factor = (res["adx"] / 30).clip(0, 1)
    res["confidence"] = (res["score"].abs() * 0.4
                         + res["agreement"] * 0.3
                         + adx_factor * 0.3).clip(0, 1)

    res["state"] = pd.cut(res["score"],
                          bins=[-1.01, -0.5, -0.15, 0.15, 0.5, 1.01],
                          labels=STATES).astype(str)
    return res


def latest_reading(df: pd.DataFrame, ticker: str = "") -> CompassReading | None:
    if df is None or len(df) < 60:
        return None
    # Drop unsettled bars (NaN OHLC on an in-progress session).
    df = df.dropna(subset=["High", "Low", "Close"])
    if len(df) < 60:
        return None
    res = compute_scores(df)
    r = res.iloc[-1]
    return CompassReading(
        date=res.index[-1], ticker=ticker, close=float(df["Close"].iloc[-1]),
        score=float(r["score"]), state=str(r["state"]),
        confidence=float(r["confidence"]), adx=float(r["adx"]),
        agreement=float(r["agreement"]),
        components={k: float(r[k]) for k in WEIGHTS},
    )


def format_reading(r: CompassReading) -> str:
    bar_slots = 21
    pos = int(round((r.score + 1) / 2 * (bar_slots - 1)))
    bar = "".join("▓" if i == pos else "·" for i in range(bar_slots))

    lines = [
        f"  {r.ticker}  @ {r.close:,.2f}   ({r.date:%Y-%m-%d})",
        f"  BEAR {bar} BULL",
        f"  STATE: {r.state:<12s} score {r.score:+.3f}   "
        f"confidence {r.confidence:.0%}   ADX {r.adx:.0f}   "
        f"agreement {r.agreement:.0%}",
        "  " + "-" * 66,
    ]
    for k in WEIGHTS:
        v = r.components[k]
        mark = "+" if v > 0.05 else ("-" if v < -0.05 else "·")
        lines.append(f"    {k:<14s} {mark} {v:+.2f}   (weight {WEIGHTS[k]:.2f})")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import warnings

    warnings.filterwarnings("ignore")
    import yfinance as yf

    ap = argparse.ArgumentParser(description="Daily trend state readout")
    ap.add_argument("--tickers", default="SPY,QQQ,^NSEI,^NSEBANK")
    args = ap.parse_args()

    print("\n" + "=" * 70)
    print("  TREND COMPASS — daily market state")
    print("=" * 70)
    for t in [x.strip() for x in args.tickers.split(",") if x.strip()]:
        df = yf.Ticker(t).history(period="2y")
        r = latest_reading(df, t)
        print()
        print(format_reading(r) if r else f"  {t}: insufficient data")
    print()
