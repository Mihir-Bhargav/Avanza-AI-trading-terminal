"""
Indicator library for the terminal.

No cap on how many run at once — that limit is TradingView's business model,
not a technical constraint. Everything is computed server-side in pandas from
the same bars the chart draws, so an indicator can never disagree with the
candles it sits on.

Two kinds:
    OVERLAY   drawn on the price chart (EMAs, Bollinger, VWAP, CPR)
    PANE      drawn in its own sub-chart below (RSI, MACD, ATR, volume)

Reuses the logic already validated in this repo rather than rewriting it:
    screeners/levels.py            CPR, pivots, MACD, ATR
    terminal/trend_compass.py            composite state score
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ts(idx) -> list[int]:
    out = []
    for t in idx:
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        if t.tzinfo is None:
            from datetime import timezone
            t = t.replace(tzinfo=timezone.utc)
        out.append(int(t.timestamp()))
    return out


def _line(idx, series, color, title, pane="overlay", width=1):
    """Drop NaNs — Lightweight Charts wants gaps absent, not null."""
    ts = _ts(idx)
    data = [{"time": t, "value": round(float(v), 4)}
            for t, v in zip(ts, series) if v == v]
    return {"kind": "line", "pane": pane, "color": color,
            "title": title, "lineWidth": width, "data": data}


def _hist(idx, series, title, pane, pos="#26a69a", neg="#ef5350"):
    ts = _ts(idx)
    data = [{"time": t, "value": round(float(v), 4),
             "color": pos if v >= 0 else neg}
            for t, v in zip(ts, series) if v == v]
    return {"kind": "histogram", "pane": pane, "title": title, "data": data}


# --------------------------------------------------------------------------
# Each builder takes the OHLCV frame and returns a list of series dicts.
# --------------------------------------------------------------------------

def ema_ribbon(df):
    c = df["Close"]
    return [
        _line(df.index, c.ewm(span=8, adjust=False).mean(), "#f0a020", "EMA8", width=2),
        _line(df.index, c.ewm(span=20, adjust=False).mean(), "#4fd6c0", "EMA20"),
        _line(df.index, c.ewm(span=50, adjust=False).mean(), "#7b8794", "EMA50"),
    ]


def sma200(df):
    return [_line(df.index, df["Close"].rolling(200).mean(), "#c792ea", "SMA200", width=2)]


def bollinger(df, n=20, k=2.0):
    c = df["Close"]; m = c.rolling(n).mean(); s = c.rolling(n).std()
    return [_line(df.index, m + k * s, "#5c6b7a", "BB upper"),
            _line(df.index, m, "#3d4854", "BB mid"),
            _line(df.index, m - k * s, "#5c6b7a", "BB lower")]


def vwap_session(df):
    """Session-anchored VWAP. Needs real volume — spot indices report none."""
    if "Volume" not in df or float(df["Volume"].sum()) == 0:
        return []
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    day = pd.Series([t.date() for t in df.index], index=df.index)
    pv = (tp * df["Volume"]).groupby(day).cumsum()
    vv = df["Volume"].groupby(day).cumsum()
    return [_line(df.index, pv / vv.replace(0, np.nan), "#ffd166", "VWAP", width=2)]


def rsi(df, n=14):
    d = df["Close"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / (dn + 1e-10))
    return [_line(df.index, r, "#f0a020", "RSI14", pane="rsi", width=2),
            _line(df.index, pd.Series(70, index=df.index), "#ef535055", "70", pane="rsi"),
            _line(df.index, pd.Series(30, index=df.index), "#26a69a55", "30", pane="rsi")]


def macd(df, f=12, s=9, sl=26):
    c = df["Close"]
    line = c.ewm(span=f, adjust=False).mean() - c.ewm(span=sl, adjust=False).mean()
    sig = line.ewm(span=s, adjust=False).mean()
    return [_hist(df.index, line - sig, "MACD hist", "macd"),
            _line(df.index, line, "#4fd6c0", "MACD", pane="macd", width=2),
            _line(df.index, sig, "#f0a020", "signal", pane="macd")]


def atr_pct(df, n=14):
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / n, adjust=False).mean() / df["Close"] * 100
    return [_line(df.index, a, "#c792ea", "ATR%", pane="atr", width=2)]


def volume(df):
    if "Volume" not in df or float(df["Volume"].sum()) == 0:
        return []
    up = df["Close"] >= df["Open"]
    ts = _ts(df.index)
    data = [{"time": t, "value": float(v), "color": "#26a69a88" if u else "#ef535088"}
            for t, v, u in zip(ts, df["Volume"], up) if v == v]
    return [{"kind": "histogram", "pane": "vol", "title": "Volume", "data": data}]


def cpr_bands(df):
    """CPR from the prior bar, plotted forward — same maths as levels.py."""
    p = (df["High"].shift() + df["Low"].shift() + df["Close"].shift()) / 3
    bc = (df["High"].shift() + df["Low"].shift()) / 2
    tc = 2 * p - bc
    hi, lo = np.maximum(tc, bc), np.minimum(tc, bc)
    return [_line(df.index, p, "#ffffff", "Pivot"),
            _line(df.index, pd.Series(hi, index=df.index), "#ff9800", "TC"),
            _line(df.index, pd.Series(lo, index=df.index), "#ff9800", "BC")]


def trend_compass(df):
    """Composite -1..+1 state score. NOTE: backtested and found to have NO
    forward-return edge (see trend_compass_backtest.py) — it describes the
    market, it does not predict it."""
    try:
        from terminal.trend_compass import compute_scores
        res = compute_scores(df)
        return [_line(df.index, res["score"], "#4fd6c0", "Compass", pane="compass", width=2),
                _line(df.index, pd.Series(0, index=df.index), "#5c6b7a55", "0", pane="compass")]
    except Exception:
        return []


REGISTRY = {
    "ema":      ("EMA 8/20/50",      "overlay", ema_ribbon),
    "sma200":   ("SMA 200",          "overlay", sma200),
    "bb":       ("Bollinger 20,2",   "overlay", bollinger),
    "vwap":     ("VWAP (session)",   "overlay", vwap_session),
    "cpr":      ("CPR bands",        "overlay", cpr_bands),
    "rsi":      ("RSI 14",           "rsi",     rsi),
    "macd":     ("MACD",             "macd",    macd),
    "atr":      ("ATR %",            "atr",     atr_pct),
    "vol":      ("Volume",           "vol",     volume),
    "compass":  ("Trend Compass",    "compass", trend_compass),
}


def build(df: pd.DataFrame, names: list[str]) -> list[dict]:
    """Compute any number of indicators. There is deliberately no limit."""
    out = []
    for n in names:
        entry = REGISTRY.get(n)
        if not entry:
            continue
        try:
            out += entry[2](df)
        except Exception:
            continue          # one bad indicator must not break the chart
    return out


def catalog() -> list[dict]:
    return [{"id": k, "label": v[0], "pane": v[1]} for k, v in REGISTRY.items()]


# --------------------------------------------------------------------------
# TTM Power Range — the highest-earning tool in this project.
#
# ~75% of all realised P&L came from this (+2,300 and +1,713, both largest
# wins). It sat archived for "low Sharpe 0.80" until the 2026-08-04 audit.
#
# Formula lifted verbatim from production_system/live/ttm_power_range_trader.py,
# which itself matches the original Pine:
#     r[0] = yesterday's range ... r[9] = ten days ago
#     zone1 = open + sum(r[0:5])/10        zone3 = open - sum(r[0:5])/10
#     zone2 = open + sum(r[0:10])/10/2     zone4 = open - sum(r[0:10])/10/2
#     BUY  : close crosses OVER zone2 while above EMA8
#     SELL : close crosses UNDER zone4 while below EMA8
# --------------------------------------------------------------------------

def ttm_power_range(df):
    if len(df) < 12:
        return []
    rng = (df["High"] - df["Low"])
    op = df["Open"]
    z1 = pd.Series(np.nan, index=df.index); z2 = z1.copy()
    z3 = z1.copy(); z4 = z1.copy()
    for i in range(10, len(df)):
        r = rng.iloc[i - 10:i][::-1].values          # [0] = most recent prior bar
        o = float(op.iloc[i])
        r5, r10 = float(r[:5].sum()), float(r[:10].sum())
        z1.iloc[i] = o + r5 / 10
        z2.iloc[i] = o + r10 / 10 / 2
        z3.iloc[i] = o - r5 / 10
        z4.iloc[i] = o - r10 / 10 / 2
    ema8 = df["Close"].ewm(span=8, adjust=False).mean()
    return [
        _line(df.index, z1, "#ef5350", "TTM z1", width=1),
        _line(df.index, z2, "#ff9800", "TTM z2", width=2),
        _line(df.index, z4, "#ff9800", "TTM z4", width=2),
        _line(df.index, z3, "#26a69a", "TTM z3", width=1),
        _line(df.index, ema8, "#f0a020", "EMA8 (TTM)", width=2),
    ]


def ttm_signals(df):
    """BUY/SELL markers on the exact crossover rule the trader uses."""
    if len(df) < 12:
        return []
    rng = (df["High"] - df["Low"]); op = df["Open"]; c = df["Close"]
    ema8 = c.ewm(span=8, adjust=False).mean()
    marks = []
    for i in range(11, len(df)):
        r = rng.iloc[i - 10:i][::-1].values
        o = float(op.iloc[i])
        z2 = o + float(r[:10].sum()) / 10 / 2
        z4 = o - float(r[:10].sum()) / 10 / 2
        prev, curr, e = float(c.iloc[i - 1]), float(c.iloc[i]), float(ema8.iloc[i])
        t = df.index[i]
        t = t.to_pydatetime() if hasattr(t, "to_pydatetime") else t
        if t.tzinfo is None:
            from datetime import timezone
            t = t.replace(tzinfo=timezone.utc)
        if prev <= z2 < curr and curr > e:
            marks.append({"time": int(t.timestamp()), "position": "belowBar",
                          "color": "#26a69a", "shape": "arrowUp", "text": "TTM"})
        elif prev >= z4 > curr and curr < e:
            marks.append({"time": int(t.timestamp()), "position": "aboveBar",
                          "color": "#ef5350", "shape": "arrowDown", "text": "TTM"})
    return [{"kind": "markers", "pane": "overlay", "title": "TTM signals", "data": marks}]


# --- Python equivalents of the Pine guide indicators (signals/indicators/) ---

def vol_regime(df):
    """COMPRESSED / EXPANDED. ATR5/ATR20 < 0.85 is the threshold validated in
    the Gamma_Blast backtest (real PF 3.6), combined with BB-width percentile
    so a single noisy measure cannot flip the regime."""
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - df["Close"].shift()).abs(),
                    (df["Low"] - df["Close"].shift()).abs()], axis=1).max(axis=1)
    ratio = tr.rolling(5).mean() / tr.rolling(20).mean()
    c = df["Close"]; bw = (c.rolling(20).std() * 4) / c.rolling(20).mean()
    pct = bw.rolling(100).rank(pct=True) * 100
    state = pd.Series(0.0, index=df.index)
    state[(ratio < 0.85) & (pct < 25)] = -1.0        # compressed / coiled
    state[(ratio > 1.25) & (pct > 75)] = 1.0         # expanded
    return [_line(df.index, ratio, "#4fd6c0", "ATR5/20", pane="regime", width=2),
            _line(df.index, pd.Series(0.85, index=df.index), "#26a69a55", "0.85", pane="regime"),
            _line(df.index, pd.Series(1.25, index=df.index), "#ef535055", "1.25", pane="regime"),
            _hist(df.index, state, "regime", "regime", pos="#ef535066", neg="#4fd6c066")]


def trend_ribbon(df):
    """EMA 8/20/50 stack, coloured only when RSI agrees with the stack."""
    c = df["Close"]
    e8 = c.ewm(span=8, adjust=False).mean()
    e20 = c.ewm(span=20, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    r = 100 - 100 / (1 + up / (dn + 1e-10))
    bull = (e8 > e20) & (e20 > e50) & (r > 50) & (r < 70)
    bear = (e8 < e20) & (e20 < e50) & (r < 50) & (r > 30)
    st = pd.Series(0.0, index=df.index); st[bull] = 1.0; st[bear] = -1.0
    return [_line(df.index, e8, "#26a69a", "R-EMA8", width=2),
            _line(df.index, e20, "#4fd6c0", "R-EMA20"),
            _line(df.index, e50, "#7b8794", "R-EMA50"),
            _hist(df.index, st, "confirmed trend", "ribbon")]


REGISTRY.update({
    "ttm":      ("TTM Power Range ★", "overlay", ttm_power_range),
    "ttmsig":   ("TTM signals ★",     "overlay", ttm_signals),
    "regime":   ("Volatility Regime", "regime",  vol_regime),
    "ribbon":   ("Trend Ribbon",      "ribbon",  trend_ribbon),
})
