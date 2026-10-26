"""
TTM Power Range zone panel -- daily, glanceable, decision-support only.

Ported 2026-09-24 from Algorithmic_trading_projects/screeners/avanza_zone_panel.py
(the CLI printer there is unchanged). The zone math, trend filter and base-rate
check are identical; this module adds a pure row builder, a state classifier
and a sort so the terminal API (`/api/setups`) can serve the same read.

NOT a strategy that fires and auto-trades. Every attempt to mechanise this exact
zone logic into an auto-fire rule failed once honestly backtested (NIFTY daily
zone breakout: Sharpe -0.90; EMA trend on this universe: Sharpe 0.05-0.26). The
thing that made money is a human filtering an always-on read with judgment. A
cross is a prompt to look, not an order.

Zone math (no lookahead):
    r[1..10] = last 10 daily (high-low) ranges, r[1] = yesterday
    zone1 = today_open + sum(r[1..5])  / 10        (outer upper)
    zone2 = today_open + sum(r[1..10]) / 10 / 2    (inner upper)
    zone3 = today_open - sum(r[1..5])  / 10        (outer lower)
    zone4 = today_open - sum(r[1..10]) / 10 / 2    (inner lower)
    trend filter: EMA(21)

Distances, as served (both signed so that POSITIVE = THROUGH the zone):
    dist_z1_atr = (close - zone1) / ATR14     > 0: above zone1
    dist_z3_atr = (zone3 - close) / ATR14     > 0: below zone3
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screeners.levels import _true_range  # noqa: E402

# (symbol, display name, yahoo ticker, Avanza mini-future search term).
# Checked in the old repo to have both real yfinance daily data and live
# tradeable Avanza mini futures: the Swedish five on 2026-09-02, US megacaps on
# 2026-08-31, semis on 2026-09-05. Intel and Atlas Copco were checked and have
# no mini line -- dropped, not an oversight.
UNIVERSE: list[tuple[str, str, str, str]] = [
    ("OMXS30", "OMXS30",             "^OMX",      "MINI OMX"),
    ("VOLV-B", "Volvo B",            "VOLV-B.ST", "MINI VOLVO"),
    ("ERIC-B", "Ericsson B",         "ERIC-B.ST", "MINI ERICSSON"),
    ("HM-B",   "H&M B",              "HM-B.ST",   "MINI HM"),
    ("EVO",    "Evolution",          "EVO.ST",    "MINI EVOLUTION"),
    ("SPX",    "S&P 500",            "^GSPC",     "MINI SP500"),
    ("NDX",    "Nasdaq 100",         "^NDX",      "MINI NASDAQ"),
    ("NVDA",   "NVIDIA",             "NVDA",      "MINI NVIDIA"),
    ("TSLA",   "Tesla",              "TSLA",      "MINI TESLA"),
    ("AAPL",   "Apple",              "AAPL",      "MINI APPLE"),
    ("AMD",    "AMD",                "AMD",       "MINI AMD"),
    ("AVGO",   "Broadcom",           "AVGO",      "MINI AVGO"),
    ("TSM",    "TSMC",               "TSM",       "MINI TSMC"),
    ("MU",     "Micron Technology",  "MU",        "MINI MICRON"),
    ("QCOM",   "Qualcomm",           "QCOM",      "MINI QUALCOMM"),
    ("ASML",   "ASML",               "ASML",      "MINI ASML"),
]

EMA_SPAN = 21
ATR_PERIOD = 14
FORWARD_DAYS = 3        # horizon of the descriptive base-rate check

# State thresholds, in ATRs of signed distance (positive = through the zone).
AT_ATR = 0.10           # |dist| <= 0.10 ATR           -> at_z1 / at_z3
NEAR_ATR = 0.35         # 0.10 < inside-distance <= 0.35 -> near_z1 / near_z3
                        # dist > +0.10 ATR               -> crossed_*

STATES = ("crossed_z1_up", "crossed_z3_down", "at_z1", "at_z3",
          "near_z1", "near_z3", "inside")


def compute_zones(df: pd.DataFrame) -> pd.DataFrame:
    """Zone1-4 computed causally: today's zones use yesterday's ranges only."""
    rng = df["High"] - df["Low"]
    r_5 = rng.shift(1).rolling(5).sum()
    r_10 = rng.shift(1).rolling(10).sum()
    out = pd.DataFrame(index=df.index)
    out["open"] = df["Open"]
    out["zone1"] = df["Open"] + r_5 / 10
    out["zone2"] = df["Open"] + r_10 / 10 / 2
    out["zone3"] = df["Open"] - r_5 / 10
    out["zone4"] = df["Open"] - r_10 / 10 / 2
    out["ema21"] = df["Close"].ewm(span=EMA_SPAN, adjust=False).mean()
    out["atr14"] = _true_range(df).ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    out["close"] = df["Close"]
    out["high"] = df["High"]
    out["low"] = df["Low"]
    return out


def historical_base_rate(z: pd.DataFrame) -> dict:
    """Purely descriptive, NOT a backtested strategy result. Of every day price
    crossed zone1 up with close > EMA21, what fraction closed higher
    FORWARD_DAYS later? Same for zone3 down (win = closed lower)."""
    crossed_up = (z["close"] > z["zone1"]) & (z["close"].shift(1) <= z["zone1"].shift(1)) & (z["close"] > z["ema21"])
    crossed_dn = (z["close"] < z["zone3"]) & (z["close"].shift(1) >= z["zone3"].shift(1)) & (z["close"] < z["ema21"])
    fwd_ret = z["close"].shift(-FORWARD_DAYS) / z["close"] - 1

    up_events = fwd_ret[crossed_up].dropna()
    dn_events = fwd_ret[crossed_dn].dropna()
    return {
        "zone1_up_n": len(up_events),
        "zone1_up_winrate": (up_events > 0).mean() if len(up_events) else float("nan"),
        "zone1_up_avg_fwd_ret": up_events.mean() if len(up_events) else float("nan"),
        "zone3_dn_n": len(dn_events),
        "zone3_dn_winrate": (dn_events < 0).mean() if len(dn_events) else float("nan"),
        "zone3_dn_avg_fwd_ret": dn_events.mean() if len(dn_events) else float("nan"),
    }


def survivable_leverage(atr_pct: float) -> float:
    """House rule: max sensible leverage ~= 100 / (3.5 x ATR%)."""
    return 100.0 / (3.5 * atr_pct) if atr_pct > 0 else float("nan")


def _num(x, nd: int | None = None):
    """float or None -- NaN/inf never reach JSON."""
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd) if nd is not None else x


def classify_state(close: float, zone1: float, zone3: float, atr: float) -> tuple[str, float, float]:
    """(state, dist_z1_atr, dist_z3_atr). Distances are positive when THROUGH."""
    if not atr or atr != atr or atr <= 0:
        raise ValueError("ATR must be positive to classify a zone state")
    d1 = (close - zone1) / atr
    d3 = (zone3 - close) / atr
    if d1 > AT_ATR:
        state = "crossed_z1_up"
    elif d3 > AT_ATR:
        state = "crossed_z3_down"
    elif abs(d1) <= AT_ATR or abs(d3) <= AT_ATR:
        state = "at_z1" if abs(d1) <= abs(d3) else "at_z3"
    elif -d1 <= NEAR_ATR or -d3 <= NEAR_ATR:
        state = "near_z1" if -d1 <= -d3 else "near_z3"
    else:
        state = "inside"
    return state, d1, d3


def is_with_trend(state: str, trend: str) -> bool:
    return ((state in ("crossed_z1_up", "at_z1") and trend == "up")
            or (state in ("crossed_z3_down", "at_z3") and trend == "down"))


def _hist_block(n, wr, avg) -> dict:
    return {"n": int(n), "win_rate": _num(wr, 3), "avg_fwd_ret": _num(avg, 4)}


def build_row(symbol: str, name: str, yahoo: str, avanza_query: str | None,
              df: pd.DataFrame) -> dict:
    """One setups row from daily OHLC whose LAST row is today's (forming) bar.

    Raises ValueError when there is not enough history -- the caller reports
    that per symbol rather than dropping the row silently.
    """
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 30:
        raise ValueError(f"only {len(df)} daily bars; need 30")
    z = compute_zones(df)
    last = z.iloc[-1]
    close, atr = float(last["close"]), float(last["atr14"])
    if any(v != v for v in (last["zone1"], last["zone3"], atr)):
        raise ValueError("zones undefined on the last bar (missing ranges)")
    atr_pct = atr / close * 100
    trend = "up" if close > float(last["ema21"]) else "down"
    state, d1, d3 = classify_state(close, float(last["zone1"]), float(last["zone3"]), atr)
    st = historical_base_rate(z)
    ts = df.index[-1]
    return {
        "symbol": symbol, "yahoo": yahoo, "name": name, "avanza_query": avanza_query,
        "trend": trend,
        "close": _num(close, 4), "open": _num(last["open"], 4),
        "zone1": _num(last["zone1"], 4), "zone2": _num(last["zone2"], 4),
        "zone3": _num(last["zone3"], 4), "zone4": _num(last["zone4"], 4),
        "atr14": _num(atr, 4), "atr_pct": _num(atr_pct, 3),
        "lev_cap": _num(survivable_leverage(atr_pct), 1),
        "state": state,
        "dist_z1_atr": _num(d1, 3), "dist_z3_atr": _num(d3, 3),
        "with_trend": is_with_trend(state, trend),
        "hist": {
            "z1_up": _hist_block(st["zone1_up_n"], st["zone1_up_winrate"], st["zone1_up_avg_fwd_ret"]),
            "z3_dn": _hist_block(st["zone3_dn_n"], st["zone3_dn_winrate"], st["zone3_dn_avg_fwd_ret"]),
        },
        # Date of the bar being classified. Before a market opens this is the
        # PREVIOUS session (e.g. US names during the Stockholm morning).
        "bar_date": ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10],
        "earnings_date": None, "earnings_days": None,
    }


def sort_key(row: dict) -> tuple:
    """Crossed-with-trend first, then the smallest distance to either zone."""
    crossed_wt = row["with_trend"] and row["state"].startswith("crossed")
    d = min(abs(row["dist_z1_atr"] or 0.0) if row["dist_z1_atr"] is not None else math.inf,
            abs(row["dist_z3_atr"] or 0.0) if row["dist_z3_atr"] is not None else math.inf)
    return (0 if crossed_wt else 1, d, row["symbol"])


def sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=sort_key)
