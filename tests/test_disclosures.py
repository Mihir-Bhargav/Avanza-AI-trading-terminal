import json
from datetime import date
from pathlib import Path

import pytest

from terminal import disclosures as DISC

FIXTURES = Path(__file__).parent / "fixtures"

TODAY = date(2026, 9, 24)


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_lag_days():
    assert DISC.lag_days("2026-09-17", "2026-08-20") == 28
    assert DISC.lag_days(None, "2026-08-20") is None
    assert DISC.lag_days("bad", "2026-08-20") is None


def test_normalise_congress():
    rows = DISC.normalise_congress(load("av_congress_aapl.json"), "AAPL")
    r = rows[0]
    assert r["filed"] == "2026-09-17" and r["traded"] == "2026-08-20"
    assert r["lag_days"] == 28
    assert r["who"] == "Rep A" and r["chamber"] == "House" and r["party"] == "D"
    assert r["owner"] == "spouse" and r["side"] == "buy" and r["symbol"] == "AAPL"
    assert r["amount_min"] == 1001.0 and r["amount_max"] == 15000.0
    assert r["amount_label"] == "$1K–$15K"
    assert rows[1]["side"] == "sell" and rows[1]["amount_label"] == "$100K–$250K"
    assert rows[2]["side"] == "other"
    keys = {"filed", "traded", "lag_days", "who", "chamber", "party", "owner", "role",
            "symbol", "side", "amount_min", "amount_max", "amount_label", "yours"}
    assert keys <= set(r)


def test_normalise_insiders_has_no_filed_date():
    rows = DISC.normalise_insiders(load("av_insiders_nvda.json"), "NVDA")
    assert rows[0]["filed"] is None and rows[0]["lag_days"] is None
    assert rows[0]["side"] == "sell" and rows[0]["role"] == "Director"
    assert rows[0]["amount_min"] == pytest.approx(25000 * 180.5)
    assert rows[1]["side"] == "buy" and rows[1]["amount_min"] is None


def test_av_error_detection():
    assert DISC.av_error({"Information": "rate limit"}).startswith("Information")
    assert DISC.av_error({"Note": "x"})
    assert DISC.av_error({"Error Message": "bad"})
    assert DISC.av_error({"trades": []}) is None
    assert DISC.av_error([]) == "unexpected response shape"


class FakeGetter:
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []

    def __call__(self, function, symbol, key):
        self.calls.append((function, symbol))
        return self.payloads.get(symbol, {"Information": "throttled"})


def test_fetcher_caches_and_caps(tmp_path):
    g = FakeGetter({"AAPL": load("av_congress_aapl.json")})
    f = DISC.Fetcher("k", cache_dir=tmp_path, getter=g, max_live=2)
    p, why = f.get("CONGRESS_TRADES", "AAPL")
    assert p and why is None and len(list(tmp_path.glob("CONGRESS_*"))) == 1
    # throttled response: not cached, reported
    p, why = f.get("CONGRESS_TRADES", "MSFT")
    assert p is None and why.startswith("Information")
    assert len(list(tmp_path.glob("CONGRESS_*"))) == 1
    # cap reached, but cached AAPL still served without a live call
    p, why = f.get("CONGRESS_TRADES", "NVDA")
    assert p is None and "cap" in why
    f2 = DISC.Fetcher("k", cache_dir=tmp_path, getter=g, max_live=0)
    p, why = f2.get("CONGRESS_TRADES", "AAPL")
    assert p is not None and f2.live_calls == 0
    assert len(g.calls) == 2


def test_build_partial_yours_sort_most_bought(tmp_path):
    g = FakeGetter({"AAPL": load("av_congress_aapl.json")})
    f = DISC.Fetcher("k", cache_dir=tmp_path, getter=g)
    out = DISC.build("congress", held=["AAPL", "VOLV-B.ST"], watch=["NVDA", "^GSPC", "AAPL"],
                     fetcher=f, today=TODAY)
    assert out["symbols"] == ["AAPL", "NVDA"]             # non-US filtered, holdings first
    assert out["partial"] is True and out["skipped"] == ["NVDA"]
    assert out["rule"] == "STOCK Act · filed within 45 days"
    assert out["configured"] is True and out["type"] == "congress"
    # 2020 row is outside the 180-day window
    assert [r["filed"] for r in out["rows"]] == ["2026-09-17", "2026-09-10"]
    assert all(r["yours"] == "HELD" for r in out["rows"])
    assert out["most_bought"] == [{"symbol": "AAPL", "count": 1}]


def test_build_watch_tag_and_bad_type(tmp_path):
    g = FakeGetter({"AAPL": load("av_congress_aapl.json")})
    out = DISC.build("congress", held=[], watch=["AAPL"],
                     fetcher=DISC.Fetcher("k", cache_dir=tmp_path, getter=g), today=TODAY)
    assert {r["yours"] for r in out["rows"]} == {"WATCH"}
    assert out["partial"] is False
    with pytest.raises(ValueError):
        DISC.build("nope", [], [], DISC.Fetcher("k", cache_dir=tmp_path, getter=g))


def test_daily_budget_stops_live_calls_across_requests(tmp_path):
    g = FakeGetter({s: load("av_congress_aapl.json") for s in ("A", "B", "C", "D")})
    budget = DISC.Budget(tmp_path, limit=3, today=lambda: TODAY)
    f1 = DISC.Fetcher("k", cache_dir=tmp_path, getter=g, budget=budget)
    assert f1.get("CONGRESS_TRADES", "A")[0] and f1.get("CONGRESS_TRADES", "B")[0]
    # a second request (new Fetcher, same ledger) only has one call left
    f2 = DISC.Fetcher("k", cache_dir=tmp_path, getter=g,
                      budget=DISC.Budget(tmp_path, limit=3, today=lambda: TODAY))
    assert f2.get("CONGRESS_TRADES", "C")[0]
    p, why = f2.get("CONGRESS_TRADES", "D")
    assert p is None and "budget used (3/3)" in why
    assert len(g.calls) == 3
    # cached symbols are still served once the budget is gone
    assert f2.get("CONGRESS_TRADES", "A")[0]
    assert budget.summary()["used"] == 3


def test_rate_limit_answer_exhausts_the_day(tmp_path):
    g = FakeGetter({})
    g.payloads = {}
    def getter(function, symbol, key):
        g.calls.append(symbol)
        return {"Information": "We have detected your API key and our standard API rate limit is 25 requests per day."}
    f = DISC.Fetcher("k", cache_dir=tmp_path, getter=getter,
                     budget=DISC.Budget(tmp_path, limit=25, today=lambda: TODAY))
    p, why = f.get("CONGRESS_TRADES", "A")
    assert p is None and why.startswith("Information")
    p, why = f.get("CONGRESS_TRADES", "B")
    assert p is None and "rate limit hit earlier today" in why
    assert g.calls == ["A"]


def test_function_share_caps_legacy_insiders(tmp_path):
    g = FakeGetter({s: {"data": []} for s in "ABCDEFGHIJ"})
    f = DISC.Fetcher("k", cache_dir=tmp_path, getter=g, max_live=10,
                     budget=DISC.Budget(tmp_path, limit=25, today=lambda: TODAY))
    got = [f.get("INSIDER_TRANSACTIONS", s) for s in "ABCDEFGHIJ"]
    cap = DISC.FUNCTION_DAILY_CAP["INSIDER_TRANSACTIONS"]
    assert sum(1 for p, _ in got if p is not None) == cap
    assert "daily share" in got[-1][1]


def test_funds_no_longer_use_alpha_vantage():
    # 13F comes from SEC EDGAR (terminal/funds13f.py): Congress keeps the budget
    assert "funds" not in DISC.TYPES and "INSTITUTIONAL_HOLDINGS" not in DISC.FUNCTION_DAILY_CAP
