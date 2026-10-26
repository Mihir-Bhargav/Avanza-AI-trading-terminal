from datetime import datetime, timedelta, timezone

import pytest

from terminal import plans as P

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
GOOD = {"symbol": "mu", "side": "long", "take_profit": 110, "stop_loss": 95, "leverage": 3}


def test_valid_long_with_price_and_cap():
    c = P.validate(GOOD, price=100, lev_cap=5.6)
    assert c["symbol"] == "MU" and c["lev_cap"] == 5.6 and c["price_at_plan"] == 100


@pytest.mark.parametrize("patch,msg", [
    ({"take_profit": None}, "take_profit is required"),
    ({"stop_loss": ""}, "stop_loss is required"),
    ({"leverage": "x"}, "leverage must be a number"),
    ({"leverage": -1}, "positive"),
    ({"side": "up"}, "side must be"),
    ({"symbol": ""}, "symbol is required"),
    ({"take_profit": 90, "stop_loss": 95}, "stop_loss must be below take_profit"),
])
def test_invalid(patch, msg):
    with pytest.raises(P.PlanError, match=msg):
        P.validate({**GOOD, **patch}, price=None, lev_cap=None)


def test_price_sides():
    with pytest.raises(P.PlanError, match="price is 111"):
        P.validate(GOOD, price=111, lev_cap=None)          # already past TP
    short = {**GOOD, "side": "short", "take_profit": 90, "stop_loss": 105}
    assert P.validate(short, price=100, lev_cap=None)["side"] == "short"
    with pytest.raises(P.PlanError, match="short plan"):
        P.validate({**short, "take_profit": 106, "stop_loss": 105}, price=None, lev_cap=None)
    with pytest.raises(P.PlanError, match="take_profit < price < stop_loss"):
        P.validate(short, price=106, lev_cap=None)


def test_leverage_cap():
    with pytest.raises(P.PlanError, match="exceeds the ATR cap of 2.5x"):
        P.validate(GOOD, price=100, lev_cap=2.5)


def _p(days_ago):
    return {"created_at": (NOW - timedelta(days=days_ago)).isoformat()}


def test_streak():
    assert P.streak([], now=NOW) == 0
    assert P.streak([_p(1), _p(5), _p(15), _p(40)], now=NOW) == 3   # 15->40 is a 25d gap
    assert P.streak([_p(20)], now=NOW) == 0                        # newest too old
    assert P.streak([_p(0), _p(14), _p(28)], now=NOW) == 3         # 14 days is not > 14


def test_store_roundtrip(tmp_path):
    s = P.PlanStore(tmp_path / "sub" / "plans.json")
    assert s.all() == []
    a = s.add(P.validate(GOOD, 100, 5.6), now=NOW - timedelta(days=1))
    b = s.add(P.validate(GOOD, 100, 5.6), now=NOW)
    assert [p["id"] for p in s.all()] == [b["id"], a["id"]]
    assert {"id", "created_at", "lev_cap"} <= set(b)
    assert s.logged_today(now=NOW)


def test_store_corrupt_file_raises(tmp_path):
    f = tmp_path / "plans.json"
    f.write_text("{not json")
    with pytest.raises(ValueError):
        P.PlanStore(f).all()
