"""SEC Form 4 insider feed: parsing, rules, store, poller and endpoint.
Fakes only -- the conftest network guard fails any real request."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terminal import insiders as I

FIX = Path(__file__).parent / "fixtures"


class _FrozenDT(datetime):
    """The fixture filings are dated 2026-09-24. Freeze the module clock two days
    later so the 30-day retention and the endpoint window don't depend on today's date."""
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 26, 12, 0, tzinfo=tz or timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(I, "datetime", _FrozenDT)
FEED = (FIX / "sec_form4_feed.atom").read_text(encoding="latin-1")
SUB = (FIX / "sec_form4_submission.txt").read_text()
ACC = "0009000002-26-000123"
URL = "https://www.sec.gov/Archives/edgar/data/9000002/000900000226000123/0009000002-26-000123-index.htm"


# ----------------------------------------------------------------- parsing
def test_parse_atom_dedupes_filings_and_keeps_form_type():
    entries = I.parse_atom(FEED)
    assert [e.accession for e in entries] == [ACC, "0009000003-26-000045", "0009000004-26-000001"]
    e = entries[0]
    assert e.cik == "9000002"                       # the (Issuer) entry wins
    assert e.filed_at == "2026-09-24T10:57:28-04:00" and e.form == "4"
    assert e.index_url == URL
    assert entries[1].form == "4/A" and entries[2].form == "424B2"
    assert I.feed_updated(FEED) == "2026-09-24T11:23:04-04:00"


def test_parse_form4_keeps_only_open_market_p_and_s():
    rows = I.parse_form4(SUB, ACC, None, URL)
    # F (tax withholding) and the derivative-table row are dropped
    assert [(r["side"], r["shares"]) for r in rows] == [("BUY", 10000.0), ("SELL", 500000.0), ("SELL", 100.0)]
    buy = rows[0]
    assert buy["id"] == f"{ACC}:0" and buy["accession"] == ACC
    assert buy["ticker"] == "EXRO" and buy["issuer"] == "Example Robotics Inc"
    assert buy["who"] == "Doe Jane Q"
    assert buy["role"] == "Chief Executive Officer · Director" and buy["is_ceo_like"] is True
    assert buy["price"] == 12.5 and buy["value"] == pytest.approx(125_000)
    assert buy["plan_10b5_1"] is True and buy["trade_date"] == "2026-09-22"
    # filed_at falls back to ACCEPTANCE-DATETIME (US Eastern)
    assert buy["filed_at"] == "2026-09-24T10:57:28-04:00"
    assert rows[1]["trade_date"] == "2026-09-23"   # time part trimmed
    assert rows[2]["price"] is None and rows[2]["value"] is None


def test_notable_rules():
    rows = I.parse_form4(SUB, ACC, "2026-09-24T10:57:28-04:00", URL)
    assert rows[0]["notable"] is True                # CEO purchase, any size
    assert rows[1]["notable"] is True                # $6M sale >= NOTABLE_SELL_USD
    assert rows[2]["notable"] is False
    base = {"side": "BUY", "is_ceo_like": False}
    assert I.is_notable({**base, "value": I.NOTABLE_BUY_USD}) is True
    assert I.is_notable({**base, "value": I.NOTABLE_BUY_USD - 1}) is False
    assert I.is_notable({"side": "SELL", "is_ceo_like": True, "value": I.NOTABLE_SELL_USD - 1}) is False


def test_amendment_is_skipped_and_garbage_raises():
    assert I.parse_form4(SUB.replace("<documentType>4<", "<documentType>4/A<"), ACC, None, URL) == []
    with pytest.raises(ValueError):
        I.parse_form4("<SEC-DOCUMENT>no xml here", ACC, None, URL)


def test_ceo_like_and_names():
    for t in ("CEO", "Chief Financial Officer", "President and COO", "Executive Chairman", "Chair"):
        assert I.is_ceo_like(t), t
    for t in ("Vice President, Sales", "EVP & General Counsel", "Director", None):
        assert not I.is_ceo_like(t), t
    assert I.pretty_name("SMITH JOHN III") == "Smith John III"
    assert I.pretty_name("Saba Capital Management, L.P.") == "Saba Capital Management, L.P."
    assert I.pretty_issuer("GENERAL AMERICAN INVESTORS CO INC") == "General American Investors Co Inc"


# ------------------------------------------------------------ rate limiter
def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept = []

    def sleep(d):
        slept.append(round(d, 6))
        t[0] += d

    rl = I.RateLimiter(rate=4, clock=lambda: t[0], sleep=sleep)
    for _ in range(3):
        rl.wait()
    assert slept == [0.25, 0.25]
    t[0] += 10                     # idle: no sleep after a long gap
    rl.wait()
    assert slept == [0.25, 0.25]


# ------------------------------------------------------------ store/poller
class FakeSec:
    def __init__(self, fail_with=None):
        self.calls, self.fail_with = [], fail_with

    def __call__(self, url, ua):
        self.calls.append(url)
        assert ua == "Test UA test@example.com"
        if self.fail_with:
            raise self.fail_with
        if "browse-edgar" in url:
            return FEED if "start=0" in url else FEED.split("<entry>")[0] + "</feed>"
        return SUB


def _poller(tmp_path, getter):
    store = I.Store(tmp_path)
    store.load()
    lim = I.RateLimiter(rate=1000, sleep=lambda d: None)
    return I.Poller("Test UA test@example.com", store, getter=getter, limiter=lim), store


def test_poller_sync_parses_dedupes_and_persists(tmp_path, monkeypatch):
    g = FakeSec()
    p, store = _poller(tmp_path, g)
    p.sync(max_filings=50, max_pages=3)
    assert p.poll_error is None and p.last_poll
    # only the Form 4 is fetched (4/A amendments and other forms are not)
    filing_calls = [u for u in g.calls if u.endswith(".txt")]
    assert len(filing_calls) == 1 and filing_calls[0].endswith("/9000002/000900000226000123/0009000002-26-000123.txt")
    assert store.seen_count() == 1
    # rows dated 2026-09-24 get pruned only after 30 days; with the fixture date they are recent enough
    n = len(store.snapshot())
    assert n == 3
    # second sync: everything seen -> no filing refetch, no duplicates
    g.calls.clear()
    p.sync(max_filings=50, max_pages=3)
    assert [u for u in g.calls if u.endswith(".txt")] == [] and len(store.snapshot()) == 3
    # persisted: a new Store reads the same trades back
    s2 = I.Store(tmp_path)
    s2.load()
    assert len(s2.snapshot()) == 3 and s2.seen_count() == 1


def test_poller_backs_off_on_429(tmp_path):
    p, _ = _poller(tmp_path, FakeSec(fail_with=I.SecError("SEC HTTP 429", 429)))
    p.sync(10, 1)
    assert p.backoff == I.BACKOFF_START_S and "429" in p.poll_error and "backing off" in p.poll_error
    p.sync(10, 1)
    assert p.backoff == I.BACKOFF_START_S * 2


def test_parse_failure_is_counted_not_hidden(tmp_path):
    def g(url, ua):
        return FEED if "browse-edgar" in url else "<SEC-DOCUMENT>broken"
    p, store = _poller(tmp_path, g)
    p.sync(10, 1)
    assert p.parse_failures == 1 and "no <ownershipDocument>" in p.last_parse_failure
    assert store.seen_count() == 1 and store.snapshot() == []


def test_store_prunes_old_trades(tmp_path):
    s = I.Store(tmp_path, retention_days=30)
    s.load()
    old = {"id": "a:0", "filed_at": "2020-01-01T10:00:00-05:00"}
    new = {"id": "b:0", "filed_at": datetime.now(timezone.utc).isoformat()}
    s.add("a", old["filed_at"], [old])
    s.add("b", new["filed_at"], [new])
    s.add("b", new["filed_at"], [new])            # duplicate line ignored
    s.prune()
    assert [r["id"] for r in s.snapshot()] == ["b:0"] and s.seen_count() == 1


# ------------------------------------------------------------------- build
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _rows():
    return I.parse_form4(SUB, ACC, "2026-09-24T10:57:28-04:00", URL)


def test_build_filters_and_top_buys():
    rows = _rows()
    out = I.build(rows, now=NOW, held={"EXRO"})
    assert len(out["rows"]) == 3 and all(r["yours"] == "HELD" for r in out["rows"])
    assert out["rows"][0]["lag_days"] in (1, 2)
    assert out["top_buys"] == [{"ticker": "EXRO", "issuer": "Example Robotics Inc",
                                "value": pytest.approx(125_000), "buyers": 1}]
    assert [r["side"] for r in I.build(rows, side="buy", now=NOW)["rows"]] == ["BUY"]
    assert len(I.build(rows, side="sell", now=NOW)["rows"]) == 2
    assert len(I.build(rows, min_value=1_000_000, now=NOW)["rows"]) == 1
    assert len(I.build(rows, notable_only=True, now=NOW)["rows"]) == 2
    assert I.build(rows, symbols={"AAPL"}, now=NOW)["rows"] == []
    assert I.build(rows, mine_only=True, now=NOW)["rows"] == []
    assert len(I.build(rows, mine_only=True, watch={"EXRO"}, now=NOW)["rows"]) == 3
    assert I.build(rows, days=1, now=datetime(2026, 9, 30, tzinfo=timezone.utc))["rows"] == []
    lim = I.build(rows, limit=1, now=NOW)
    assert len(lim["rows"]) == 1 and lim["truncated"] and lim["total_matching"] == 3


# ---------------------------------------------------------------- endpoint
def _client():
    app = FastAPI()
    app.include_router(I.router)
    return TestClient(app)        # no `with`: the lifespan (poller) does not start


def test_endpoint_not_configured(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    r = _client().get("/api/insiders")
    assert r.status_code == 503
    assert r.json() == {"configured": False, "error": I.NOT_CONFIGURED_ERROR}
    I.start_poller()                              # no UA -> no thread
    assert I.S.poller is None


def test_endpoint_serves_store(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_USER_AGENT", "Test UA test@example.com")
    p, store = _poller(tmp_path, FakeSec())
    p.sync(10, 1)
    monkeypatch.setattr(I.S, "poller", p)
    monkeypatch.setattr(I.S, "store", store)
    monkeypatch.setattr(I, "_held_and_watch", lambda: (set(), {"EXRO"}, "portfolio session not authenticated"))
    c = _client()
    assert c.get("/api/insiders?side=bogus").status_code == 400
    d = c.get("/api/insiders?days=30&side=buy").json()
    assert d["configured"] is True and d["filings_seen"] == 1 and d["backfilling"] is False
    assert d["poll_error"] is None and d["last_poll"]
    assert [r["side"] for r in d["rows"]] == ["BUY"] and d["rows"][0]["yours"] == "WATCH"
    assert d["top_buys"][0]["ticker"] == "EXRO" and d["holdings_note"]


def test_timeout_is_retried_once_but_429_is_not(tmp_path):
    calls = []

    def flaky(url, ua):
        calls.append(url)
        if len(calls) == 1:
            raise I.SecError("SEC request failed: TimeoutError")
        return FakeSec()(url, ua)
    p, store = _poller(tmp_path, flaky)
    assert p.sync(10, 1) is True and len(store.snapshot()) == 3
    g = FakeSec(fail_with=I.SecError("SEC HTTP 429", 429))
    p2, _ = _poller(tmp_path / "b", g)
    assert p2.sync(10, 1) is False and len(g.calls) == 1
