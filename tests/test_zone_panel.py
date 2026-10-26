import numpy as np
import pandas as pd
import pytest

from screeners import zone_panel as ZP


@pytest.mark.parametrize("close,expected", [
    (112.0, "crossed_z1_up"),    # d1 = +0.2 ATR
    (110.05, "at_z1"),           # d1 = +0.005
    (109.95, "at_z1"),           # d1 = -0.005
    (108.0, "near_z1"),          # d1 = -0.2
    (100.0, "inside"),
    (92.0, "near_z3"),           # d3 = -0.2
    (90.0, "at_z3"),
    (88.0, "crossed_z3_down"),   # d3 = +0.2
])
def test_classify_state_thresholds(close, expected):
    state, d1, d3 = ZP.classify_state(close, zone1=110.0, zone3=90.0, atr=10.0)
    assert state == expected
    assert d1 == pytest.approx((close - 110.0) / 10)
    assert d3 == pytest.approx((90.0 - close) / 10)


def test_classify_boundaries():
    # exactly 0.10 through is still "at"; exactly 0.35 short is still "near"
    assert ZP.classify_state(111.0, 110.0, 90.0, 10.0)[0] == "at_z1"
    assert ZP.classify_state(106.5, 110.0, 90.0, 10.0)[0] == "near_z1"
    assert ZP.classify_state(106.4, 110.0, 90.0, 10.0)[0] == "inside"


def test_classify_rejects_bad_atr():
    with pytest.raises(ValueError):
        ZP.classify_state(100, 110, 90, 0)


def test_with_trend():
    assert ZP.is_with_trend("crossed_z1_up", "up")
    assert ZP.is_with_trend("at_z3", "down")
    assert not ZP.is_with_trend("crossed_z1_up", "down")
    assert not ZP.is_with_trend("near_z1", "up")
    assert not ZP.is_with_trend("inside", "up")


def _row(sym, state, wt, d1, d3):
    return {"symbol": sym, "state": state, "with_trend": wt,
            "dist_z1_atr": d1, "dist_z3_atr": d3}


def test_sort_crossed_with_trend_first_then_distance():
    rows = [
        _row("FAR", "inside", False, -1.0, -1.2),
        _row("AGAINST", "crossed_z1_up", False, 0.05, -2.0),   # crossed but not with trend
        _row("X2", "crossed_z1_up", True, 0.8, -3.0),
        _row("NEAR", "near_z3", False, -2.0, -0.2),
        _row("X1", "crossed_z3_down", True, -3.0, 0.3),
    ]
    order = [r["symbol"] for r in ZP.sort_rows(rows)]
    assert order == ["X1", "X2", "AGAINST", "NEAR", "FAR"]


def _frame(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - abs(rng.normal(0, 0.005, n)))
    idx = pd.date_range("2025-06-01", periods=n, freq="B")
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                         "Volume": 1.0}, index=idx)


def test_build_row_shape_and_values():
    df = _frame()
    r = ZP.build_row("TEST", "Test Co", "TEST", "MINI TEST", df)
    for k in ("symbol", "yahoo", "name", "avanza_query", "trend", "close", "open",
              "zone1", "zone2", "zone3", "zone4", "atr14", "atr_pct", "lev_cap",
              "state", "dist_z1_atr", "dist_z3_atr", "with_trend", "hist",
              "earnings_date", "earnings_days"):
        assert k in r
    assert r["state"] in ZP.STATES
    assert r["trend"] in ("up", "down")
    assert r["zone3"] < r["open"] < r["zone1"]
    assert r["zone4"] < r["open"] < r["zone2"]
    assert r["lev_cap"] == pytest.approx(100 / (3.5 * r["atr_pct"]), rel=0.02)
    for k in ("z1_up", "z3_dn"):
        h = r["hist"][k]
        assert set(h) == {"n", "win_rate", "avg_fwd_ret"}
        if h["n"]:
            assert 0 <= h["win_rate"] <= 1
            assert abs(h["avg_fwd_ret"]) < 0.5         # a fraction, not a percent


def test_zones_are_causal():
    df = _frame()
    z1 = ZP.compute_zones(df)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("High")] *= 1.5      # change TODAY's range
    z2 = ZP.compute_zones(df2)
    assert z1["zone1"].iloc[-1] == pytest.approx(z2["zone1"].iloc[-1])


def test_build_row_short_history_raises():
    with pytest.raises(ValueError):
        ZP.build_row("T", "T", "T", None, _frame(n=20))


def test_universe_shape():
    assert len(ZP.UNIVERSE) == 16
    assert all(len(u) == 4 for u in ZP.UNIVERSE)
    assert len({u[0] for u in ZP.UNIVERSE}) == 16
