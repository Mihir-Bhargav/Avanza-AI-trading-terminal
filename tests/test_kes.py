import re

from terminal.kes import compose_briefing


def row(sym, state, trend, wt, d1=-1.0, d3=-1.0, earn=None, n=76, wr=0.55, avg=0.016, lev=5.6):
    return {"symbol": sym, "state": state, "trend": trend, "with_trend": wt,
            "dist_z1_atr": d1, "dist_z3_atr": d3, "earnings_days": earn,
            "lev_cap": lev,
            "hist": {"z1_up": {"n": n, "win_rate": wr, "avg_fwd_ret": avg},
                     "z3_dn": {"n": n, "win_rate": wr, "avg_fwd_ret": -avg}}}


NO_ORDERS = re.compile(r"\b(buy|sell|go long|go short)\b", re.I)


def test_two_crosses_with_earnings_is_cautious():
    rows = [row("MU", "crossed_z1_up", "up", True, d1=0.28, earn=6),
            row("NVDA", "crossed_z1_up", "up", True, d1=0.5),
            row("AAPL", "inside", "up", False)]
    b = compose_briefing(rows)
    assert b["mood"] == "cautious"
    assert b["text"].startswith("Two setups crossed with the trend.")
    assert "MU is the interesting one, 0.28 ATR through zone 1" in b["text"]
    assert "n=76, 55% closed higher three days later, average move +1.6%" in b["text"]
    assert "Earnings land in 6 days" in b["text"]
    assert b["links"][0] == {"label": "Show MU", "href": "/terminal/chart/MU"}
    assert "as of the" not in b["text"]            # no bar_date -> no staleness note
    assert not NO_ORDERS.search(b["text"])


def test_previous_session_bar_is_named():
    r = row("MU", "crossed_z1_up", "up", True, d1=0.28)
    r["bar_date"] = "2026-09-23"
    b = compose_briefing([r], today="2026-09-24")
    assert "0.28 ATR through zone 1 as of the 2026-09-23 close" in b["text"]
    assert not NO_ORDERS.search(b["text"])


def test_cross_without_earnings_is_alert():
    b = compose_briefing([row("SPX", "crossed_z3_down", "down", True, d3=0.4, n=5)])
    assert b["mood"] == "alert"
    assert "One setup crossed" in b["text"] and "zone 3" in b["text"]
    assert "History is thin: n=5." in b["text"]


def test_quiet_day_watching_and_pleased():
    rows = [row("VOLV-B", "near_z1", "up", False, d1=-0.2)]
    b = compose_briefing(rows)
    assert b["mood"] == "watching"
    assert "Nothing crossed with the trend." in b["text"]
    assert "Closest is VOLV-B, 0.20 ATR from zone 1" in b["text"]
    assert compose_briefing(rows, plan_today=True)["mood"] == "pleased"


def test_no_data_says_i_dont_know():
    b = compose_briefing([], errors=[{"symbol": "MU", "error": "x"}])
    assert b["mood"] == "alert" and "I don't know" in b["text"]


def test_errors_are_mentioned():
    b = compose_briefing([row("A", "inside", "up", False)],
                         errors=[{"symbol": "MU", "error": "x"}])
    assert b["mood"] == "alert" and "No data for MU" in b["text"]
