"""Router tests with fakes bound in place of feeds, auth and Portfolio."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from portfolio_mcp.avanza_readonly import AvanzaUnavailable
from terminal import api_v2
from terminal import disclosures as DISC
from terminal.feeds.base import Bars, Quote
from terminal.plans import PlanStore
from terminal.setups import SetupsService


class FakeAuth:
    def __init__(self, configured=True, token=None):
        self.configured, self.token = configured, token

    def ensure(self):
        raise AssertionError("login attempted")

    login = ensure


class FakePortfolio:
    def __init__(self, fail=None):
        self.fail = fail

    def _maybe(self):
        if self.fail:
            raise self.fail

    def account_summary(self):
        self._maybe()
        return {"accounts": [{"account": "ISK", "total_value": 100.0}], "totals_sek": {}}

    def positions(self, account=None):
        self._maybe()
        if account == "NOPE":
            raise ValueError("unknown account 'NOPE'; valid: ['ISK']")
        return {"positions": [{"yahoo_ticker": "AAPL", "instrument_type": "STOCK"}], "cash": []}

    def performance(self, period="1m", account=None):
        self._maybe()
        if period not in ("1d", "1m"):
            raise ValueError("period must be one of [...]")
        return {"period": period, "per_account": []}

    def transactions(self, account=None, from_date=None, to_date=None, max_elements=200):
        self._maybe()
        if from_date:
            datetime.fromisoformat(from_date)
        return {"transactions": [], "count": 0, "max": max_elements}


def _frame(n=260, seed=3, drift=0.0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = close * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame({"Open": o, "High": np.maximum(o, close) * 1.004,
                         "Low": np.minimum(o, close) * 0.996, "Close": close, "Volume": 1.0},
                        index=pd.date_range("2025-09-01", periods=n, freq="B"))


class FakeFeed:
    name = "fake"

    def __init__(self, age_min=0.5, source="fake"):
        self.age, self.source, self.calls = age_min, source, []

    def quote(self, symbol):
        self.calls.append(symbol)
        return Quote(symbol=symbol, price=123.456, change_pct=0.5, source=self.source,
                     ts=datetime.now(timezone.utc) - timedelta(minutes=self.age))

    def bars(self, symbol, interval="1d", lookback="1y", exclude_today=True):
        return Bars(symbol=symbol, df=_frame(), source="fake")


UNIVERSE = [("MU", "Micron", "MU", "MINI MICRON"), ("SPX", "S&P 500", "^GSPC", "MINI SP500")]


@pytest.fixture
def client(tmp_path):
    def build(auth=None, portfolio=None, bars=None):
        feed = FakeFeed()
        auth = auth or FakeAuth(configured=False)
        pf = portfolio or FakePortfolio()
        svc = SetupsService(bars or (lambda y: _frame()),
                            earnings_fn=lambda t: (t, {"date": "2026-09-30", "days_until": 6}),
                            universe=UNIVERSE)
        api_v2.bind(feed=feed, yf=FakeFeed(age_min=0.5, source="yfinance"),
                    avanza=type("AV", (), {"authenticated": False})(), auth=auth,
                    setups=svc, plans=PlanStore(tmp_path / "plans.json"),
                    portfolio_factory=lambda: pf,
                    disclosure_fetcher_factory=lambda k: DISC.Fetcher(
                        k, cache_dir=tmp_path, getter=lambda f, s, key: {"Information": "throttled"}))
        app = FastAPI()
        app.add_middleware(CORSMiddleware,
                           allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
        app.include_router(api_v2.router)
        return TestClient(app)
    return build


# ------------------------------------------------------------- market line
def test_market_line(client):
    r = client().get("/api/market-line")
    assert r.status_code == 200
    d = r.json()
    assert [i["key"] for i in d["items"]] == ["omxs30", "spx", "ndx", "gold", "usdsek"]
    for i in d["items"]:
        assert set(["key", "label", "symbol", "last", "change_pct", "freshness", "age_min"]) <= set(i)
    by = {i["key"]: i for i in d["items"]}
    assert by["spx"]["freshness"] == "live" and by["spx"]["last"] == 123.456
    # no authenticated Avanza -> GC=F futures, never labelled live
    assert by["gold"]["symbol"] == "GC=F" and by["gold"]["freshness"] == "delayed"


# ------------------------------------------------------------------ setups
def test_setups_rows_and_earnings_only_for_stocks(client):
    d = client().get("/api/setups").json()
    rows = {r["symbol"]: r for r in d["rows"]}
    assert set(rows) == {"MU", "SPX"}
    assert rows["MU"]["earnings_days"] == 6 and rows["SPX"]["earnings_days"] is None
    assert d["errors"] == []
    one = client().get("/api/setups?symbol=mu").json()
    assert [r["symbol"] for r in one["rows"]] == ["MU"]


def test_setups_errors_reported_not_dropped(client):
    def bars(y):
        if y == "MU":
            raise RuntimeError("rate limited")
        return _frame()
    d = client(bars=bars).get("/api/setups").json()
    assert [r["symbol"] for r in d["rows"]] == ["SPX"]
    assert d["errors"][0]["symbol"] == "MU" and "rate limited" in d["errors"][0]["error"]
    r = client(bars=lambda y: None).get("/api/setups")
    assert r.status_code == 503 and "error" in r.json()


# --------------------------------------------------------------- portfolio
def test_status_never_logs_in(client):
    c = client(auth=FakeAuth(configured=True, token=None))
    assert c.get("/api/portfolio/status").json() == {
        "configured": True, "authenticated": False,
        "login_blocked_until": None, "last_login_failure": None}
    assert api_v2.D._portfolio is None          # not even constructed


def test_portfolio_unconfigured_is_503(client):
    r = client().get("/api/portfolio/summary")
    assert r.status_code == 503 and "not configured" in r.json()["error"]


def test_portfolio_endpoints(client):
    c = client(auth=FakeAuth(configured=True, token="t"))
    assert c.get("/api/portfolio/summary").json()["accounts"][0]["account"] == "ISK"
    assert c.get("/api/portfolio/positions?account=ISK").status_code == 200
    assert c.get("/api/portfolio/performance?period=1d").json()["period"] == "1d"
    assert c.get("/api/portfolio/transactions?max_elements=5").json()["max"] == 5


def test_portfolio_bad_input_is_400(client):
    c = client(auth=FakeAuth(configured=True, token="t"))
    assert c.get("/api/portfolio/positions?account=NOPE").status_code == 400
    assert c.get("/api/portfolio/performance?period=5y").status_code == 400
    assert c.get("/api/portfolio/transactions?from_date=notadate").status_code == 400


def test_portfolio_upstream_error_is_503_and_redacted(client):
    fail = AvanzaUnavailable("Avanza 'overview' failed for account 1234567 HTTP 500")
    c = client(auth=FakeAuth(configured=True, token="t"), portfolio=FakePortfolio(fail=fail))
    r = c.get("/api/portfolio/summary")
    assert r.status_code == 503
    assert "1234567" not in r.text and "•••••••" in r.json()["error"]
    r = c.get("/api/portfolio/positions")
    assert r.status_code == 503 and "1234567" not in r.text


# ------------------------------------------------------------- disclosures
def test_disclosures_unconfigured(client, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "")
    r = client().get("/api/disclosures?type=congress")
    assert r.status_code == 503
    assert r.json() == {"error": "ALPHAVANTAGE_API_KEY is not set", "configured": False,
                        "type": "congress"}


def test_disclosures_bad_type_and_partial(client, monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "fake-key")
    c = client()
    assert c.get("/api/disclosures?type=bogus").status_code == 400
    d = c.get("/api/disclosures?type=congress").json()
    assert d["configured"] is True and d["partial"] is True and d["rows"] == []
    assert "fake-key" not in str(d)
    assert "not authenticated" in d["holdings_note"]
    # cap: at most 10 live fetches per request, the rest skipped
    assert d["live_fetches"] == 9 and len(d["skipped"]) == 9      # 9 US names in UNIVERSE
    assert d["budget"]["used"] == 9 and d["budget"]["limit"] == DISC.DAILY_LIMIT
    # funds read SEC EDGAR, not Alpha Vantage: no budget spent (SEC_USER_AGENT
    # is blank in tests, so the tab reports itself unconfigured)
    f = c.get("/api/disclosures?type=funds")
    assert f.status_code == 503 and f.json()["configured"] is False and "SEC_USER_AGENT" in f.json()["error"]
    assert c.get("/api/disclosures?type=congress").json()["budget"]["used"] == 18   # 9 + 9, nothing for funds


# --------------------------------------------------------------------- kes
def test_kes_briefing(client):
    d = client().get("/api/kes/briefing").json()
    assert d["mood"] in ("watching", "alert", "cautious", "pleased")
    assert d["text"] and isinstance(d["links"], list) and d["as_of"]


# ------------------------------------------------------------------- plans
def test_plans_flow(client):
    c = client()
    assert c.get("/api/plans").json() == {"plans": [], "streak": 0}
    row = c.get("/api/setups?symbol=MU").json()["rows"][0]
    px, cap = row["close"], row["lev_cap"]
    bad = c.post("/api/plans", json={"symbol": "MU", "side": "long",
                                     "take_profit": px * 1.1, "leverage": 1})
    assert bad.status_code == 400 and "stop_loss is required" in bad.json()["error"]
    wrong_side = c.post("/api/plans", json={"symbol": "MU", "side": "long", "leverage": 1,
                                            "take_profit": px * 0.9, "stop_loss": px * 0.8})
    assert wrong_side.status_code == 400 and "price" in wrong_side.json()["error"]
    too_lev = c.post("/api/plans", json={"symbol": "MU", "side": "long", "leverage": cap + 1,
                                         "take_profit": px * 1.1, "stop_loss": px * 0.9})
    assert too_lev.status_code == 400 and "ATR cap" in too_lev.json()["error"]
    ok = c.post("/api/plans", json={"symbol": "MU", "side": "long", "leverage": 1,
                                    "take_profit": px * 1.1, "stop_loss": px * 0.9, "note": "n"})
    assert ok.status_code == 200
    p = ok.json()
    assert p["lev_cap"] == cap and p["id"] and p["created_at"] and p["streak"] == 1
    got = c.get("/api/plans").json()
    assert got["streak"] == 1 and got["plans"][0]["id"] == p["id"]


def test_real_app_cors_and_routes():
    """The actual terminal.app object: CORS scoped to :3000, v2 routes mounted.
    conftest blanked the Avanza env, so importing it cannot log in."""
    from terminal import app as APP
    assert APP.AVANZA_AUTH.configured is False
    paths = {r.path for r in APP.app.routes}
    for p in ("/api/market-line", "/api/setups", "/api/portfolio/status", "/api/disclosures",
              "/api/kes/briefing", "/api/plans", "/api/ai/ask"):
        assert p in paths
    c = TestClient(APP.app)
    ok = c.options("/api/plans", headers={"Origin": "http://localhost:3000",
                                          "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = c.get("/api/portfolio/status", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
