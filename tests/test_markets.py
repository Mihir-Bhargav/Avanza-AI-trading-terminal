"""Markets sector overview: fakes only (no yfinance, no news, no network)."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terminal import markets as M

NOW = datetime(2026, 9, 24, 15, 20, tzinfo=timezone.utc)   # 11:20 New York

CFG = {
    "as_of": "2026-09-24",
    "sector_etfs": {"Technology": "XLK", "Energy": "XLE"},
    "indexes": {
        "sp500": {"label": "S&P 500", "market": "us", "sector_change": "etf",
                  "sectors": {"Technology": [["AAA", "Alpha"], ["BBB", "Beta"]],
                              "Energy": [["CCC", "Gamma"]]}},
        "omx": {"label": "OMX", "market": "sweden", "sector_change": "members_avg",
                "sectors": {"Industrials": [["X.ST", "Ex"], ["Y.ST", "Why"]]}},
    },
}


def _intraday(prices: dict[str, tuple[float, float, int]], end=NOW) -> pd.DataFrame:
    """sym -> (yesterday_last, today_last, n_today_bars); linear path today."""
    y_idx = pd.date_range("2026-09-23 13:30", periods=78, freq="5min", tz="UTC")
    t_idx = pd.date_range(end=end, periods=max(n for *_, n in prices.values()), freq="5min", tz="UTC")
    idx = y_idx.append(t_idx)
    cols = {}
    for sym, (yl, tl, n) in prices.items():
        y = np.full(len(y_idx), yl)
        t = np.full(len(t_idx), np.nan)
        t[-n:] = np.linspace(yl, tl, n)
        cols[sym] = np.concatenate([y, t])
    return pd.DataFrame(cols, index=idx)


def _daily(closes: dict[str, float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2026-09-22", "2026-09-23", "2026-09-24"])  # tz-naive, like yfinance
    return pd.DataFrame({s: [c * 0.99, c, np.nan] for s, c in closes.items()}, index=idx)


def _fake_download(intraday: pd.DataFrame, daily: pd.DataFrame | Exception, calls: list):
    def dl(symbols, period, interval):
        calls.append((tuple(symbols), interval))
        if interval == "1d":
            if isinstance(daily, Exception):
                raise daily
            return daily
        return intraday
    return dl


def _headlines(calls: list):
    def h(sym, name, market):
        calls.append((sym, market))
        return {"title": f"{name} moves", "source": "Wire", "age_min": 12, "url": "https://x", "symbol": sym}
    return h


# ------------------------------------------------------------ downsampling
def test_downsample_keeps_ends_and_caps_length():
    vals = list(range(100))
    out = M.downsample(vals, 40)
    assert len(out) == 40 and out[0] == 0 and out[-1] == 99
    assert out == sorted(out)


def test_downsample_short_series_untouched_and_drops_nan():
    assert M.downsample([1.0, float("nan"), 3.0], 40) == [1.0, 3.0]
    assert M.downsample([], 40) == []


# ------------------------------------------------------------ one quote
def test_quote_uses_daily_prev_close_and_today_session_only():
    intr = _intraday({"AAA": (100.0, 102.0, 60)})
    q = M.quote_from_bars("AAA", intr["AAA"], _daily({"AAA": 100.0})["AAA"], "America/New_York", NOW)
    assert q["last"] == 102.0
    assert q["change_pct"] == pytest.approx(2.0)
    assert q["prev_close_source"] == "daily"
    assert len(q["spark"]) == 40 and q["spark"][0] == 100.0 and q["spark"][-1] == 102.0
    assert q["age_min"] == 0.0 and q["freshness"] == "live"


def test_quote_falls_back_to_intraday_prev_close():
    intr = _intraday({"AAA": (50.0, 45.0, 10)})
    q = M.quote_from_bars("AAA", intr["AAA"], None, "America/New_York", NOW)
    assert q["change_pct"] == pytest.approx(-10.0)
    assert q["prev_close_source"] == "intraday"
    assert len(q["spark"]) == 10


def test_quote_age_is_honest_when_bars_stop():
    intr = _intraday({"AAA": (100.0, 101.0, 5)}, end=datetime(2026, 9, 24, 14, 50, tzinfo=timezone.utc))
    q = M.quote_from_bars("AAA", intr["AAA"], None, "America/New_York", NOW)
    assert q["age_min"] == 30.0
    assert q["freshness"] in ("stale", "closed")     # never "live"


def test_quote_without_bars_is_explicit():
    q = M.quote_from_bars("ZZZ", pd.Series(dtype=float), None, "America/New_York", NOW)
    assert q["last"] is None and q["error"] and q["freshness"] == "unknown"


# ------------------------------------------------------------ aggregation
def test_build_aggregates_sectors_with_etf_change_and_one_headline_per_sector():
    prices = {"AAA": (100.0, 101.0, 20), "BBB": (10.0, 9.0, 20), "CCC": (50.0, 51.0, 20),
              "XLK": (200.0, 199.0, 20), "XLE": (80.0, 82.0, 20)}
    dl_calls, h_calls = [], []
    out = M.build("sp500", cfg=CFG, download=_fake_download(
        _intraday(prices), _daily({s: p[0] for s, p in prices.items()}), dl_calls),
        headline=_headlines(h_calls), now=NOW)

    # exactly one batched call per interval, containing every member and ETF
    assert sorted(i for _, i in dl_calls) == ["1d", "5m"]
    assert set(dl_calls[0][0]) == {"AAA", "BBB", "CCC", "XLK", "XLE"}

    by = {s["sector"]: s for s in out["sectors"]}
    tech = by["Technology"]
    assert tech["etf"] == "XLK" and tech["change_basis"] == "etf"
    assert tech["change_pct"] == pytest.approx(-0.5)
    assert tech["members_avg_pct"] == pytest.approx((1.0 - 10.0) / 2)
    assert tech["top_mover"] == "BBB"                      # |−10%| beats |+1%|
    assert tech["headline"]["title"] == "Beta moves"
    assert [m["symbol"] for m in tech["members"]] == ["AAA", "BBB"]
    assert tech["members"][1]["name"] == "Beta"
    # sectors sorted by change, best first
    assert [s["sector"] for s in out["sectors"]] == ["Energy", "Technology"]
    # headlines fetched for sectors only, not every stock
    assert sorted(h_calls) == [("BBB", "us"), ("CCC", "us")]
    assert out["errors"] == [] and out["membership_as_of"] == "2026-09-24"


def test_build_members_avg_for_index_without_sector_etfs():
    prices = {"X.ST": (100.0, 104.0, 10), "Y.ST": (100.0, 98.0, 10)}
    out = M.build("omx", cfg=CFG, download=_fake_download(_intraday(prices), _daily({s: p[0] for s, p in prices.items()}), []),
                  headline=_headlines([]), now=NOW)
    sec = out["sectors"][0]
    assert sec["etf"] is None and sec["change_basis"] == "members_avg"
    assert sec["change_pct"] == pytest.approx(1.0)
    assert out["market"] == "sweden"


# ------------------------------------------------------------ error paths
def test_build_intraday_batch_failure_raises_not_empty():
    def dl(symbols, period, interval):
        raise RuntimeError("rate limited")
    with pytest.raises(M.MarketsError, match="intraday batch failed"):
        M.build("sp500", cfg=CFG, download=dl, headline=_headlines([]), now=NOW)


def test_build_all_symbols_empty_raises():
    empty = pd.DataFrame({"AAA": [np.nan]}, index=pd.DatetimeIndex([NOW]))
    with pytest.raises(M.MarketsError, match="no usable prices"):
        M.build("sp500", cfg=CFG, download=_fake_download(empty, empty, []), headline=_headlines([]), now=NOW)


def test_build_partial_failures_are_listed_and_daily_failure_falls_back():
    prices = {"AAA": (100.0, 101.0, 20), "CCC": (50.0, 51.0, 20), "XLK": (200.0, 199.0, 20)}
    out = M.build("sp500", cfg=CFG, download=_fake_download(_intraday(prices), RuntimeError("boom"), []),
                  headline=_headlines([]), now=NOW)
    assert out["errors"][0].startswith("daily batch failed")
    assert any(e.startswith("BBB:") for e in out["errors"])
    assert any(e.startswith("XLE:") for e in out["errors"])
    by = {s["sector"]: s for s in out["sectors"]}
    assert by["Energy"]["change_pct"] is None              # ETF missing -> no number, not 0
    bbb = next(m for m in by["Technology"]["members"] if m["symbol"] == "BBB")
    assert bbb["last"] is None and bbb["error"]
    aaa = next(m for m in by["Technology"]["members"] if m["symbol"] == "AAA")
    assert aaa["prev_close_source"] == "intraday"


def test_headline_failure_is_surfaced_per_sector():
    prices = {"AAA": (100.0, 101.0, 20), "BBB": (10.0, 9.0, 20), "CCC": (50.0, 51.0, 20),
              "XLK": (200.0, 199.0, 20), "XLE": (80.0, 82.0, 20)}

    def bad(sym, name, market):
        raise TimeoutError("news down")
    out = M.build("sp500", cfg=CFG, download=_fake_download(_intraday(prices), _daily({s: p[0] for s, p in prices.items()}), []),
                  headline=bad, now=NOW)
    assert all(s["headline"] is None and "news down" in s["headline_error"] for s in out["sectors"])


def test_unknown_index_raises_value_error():
    with pytest.raises(ValueError):
        M.build("nope", cfg=CFG, download=_fake_download(None, None, []), headline=_headlines([]))


# ------------------------------------------------------------ router + cache
@pytest.fixture
def client(monkeypatch):
    prices = {"AAA": (100.0, 101.0, 20), "BBB": (10.0, 9.0, 20), "CCC": (50.0, 51.0, 20),
              "XLK": (200.0, 199.0, 20), "XLE": (80.0, 82.0, 20)}
    state = {"fail": False, "calls": []}

    def dl(symbols, period, interval):
        state["calls"].append(interval)
        if state["fail"]:
            raise M.MarketsError("yfinance returned no 5m data for 5 symbols")
        return _daily({s: p[0] for s, p in prices.items()}) if interval == "1d" else _intraday(prices)

    svc = M.SectorService(download=dl, headline=_headlines([]), cfg_loader=lambda: CFG)
    monkeypatch.setattr(M, "SERVICE", svc)
    app = FastAPI()
    app.include_router(M.router)
    return TestClient(app), state


def test_endpoint_caches_and_validates(client):
    c, state = client
    r = c.get("/api/markets/sectors?index=sp500")
    assert r.status_code == 200
    body = r.json()
    assert body["index"] == "sp500" and body["as_of"] and len(body["sectors"]) == 2
    c.get("/api/markets/sectors?index=sp500")
    assert state["calls"].count("5m") == 1                 # second hit served from cache

    r = c.get("/api/markets/sectors?index=russell")
    assert r.status_code == 400 and "valid" in r.json()["error"]


def test_endpoint_error_is_503_and_not_cached(client):
    c, state = client
    state["fail"] = True
    r = c.get("/api/markets/sectors?index=sp500")
    assert r.status_code == 503 and "no 5m data" in r.json()["error"]
    state["fail"] = False
    r = c.get("/api/markets/sectors?index=sp500")
    assert r.status_code == 200


def test_shipped_leaders_file_is_consistent():
    cfg = M.load_leaders()
    assert cfg["as_of"] and set(cfg["indexes"]) >= {"sp500", "nasdaq100", "dow30"}
    assert sum(len(m) for m in cfg["indexes"]["dow30"]["sectors"].values()) == 30
    for key, spec in cfg["indexes"].items():
        for sector, members in spec["sectors"].items():
            if spec["sector_change"] == "etf":
                assert sector in cfg["sector_etfs"], (key, sector)
            assert 1 <= len(members) <= 13
            assert all(len(m) == 2 and m[0] and m[1] for m in members)


def test_headline_must_name_the_company():
    assert not M.names_company("LIVESTREAMING: BoG holds 132nd MPC press briefing", "MPC", "Marathon Petroleum")
    assert M.names_company("Marathon Petroleum beats on refining margins", "MPC", "Marathon Petroleum")
    assert M.names_company("Refiners rally; MPC shares up 3%", "MPC", "Marathon Petroleum")
    assert M.names_company("Why Berkshire (BRK.B) is lagging", "BRK-B", "Berkshire Hathaway")
    assert M.names_company("3M raises guidance", "MMM", "3M")
    assert M.names_company("Ericsson vinner order", "ERIC-B.ST", "Ericsson B")
    assert not M.names_company("CBRE Expands Industrious' Footprint", "CCI", "Crown Castle")
