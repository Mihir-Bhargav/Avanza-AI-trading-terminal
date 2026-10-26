"""SEC 13F fund moves: parsing, units, aggregation, amendments, quarter diff,
ticker mapping, splits, loader caching and the endpoint.
Fakes only -- the conftest network guard fails any real request."""
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terminal import funds13f as F

FIX = Path(__file__).parent / "fixtures"
SUB = (FIX / "sec_13f_submission.txt").read_text()
UA = "Test UA test@example.com"
TODAY = date(2026, 9, 24)


def make_sub(period_mdy: str, rows: list[tuple], *, form="13F-HR", amendment_type=None, table=True) -> str:
    """A minimal complete submission. rows: (cusip, name, cls, value, shares[, putCall])."""
    amend = ("<isAmendment>true</isAmendment><amendmentNo>1</amendmentNo>"
             f"<amendmentInfo><amendmentType>{amendment_type}</amendmentType></amendmentInfo>") if amendment_type else ""
    primary = (f'<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><headerData>'
               f"<submissionType>{form}</submissionType></headerData><formData><coverPage>"
               f"<reportCalendarOrQuarter>{period_mdy}</reportCalendarOrQuarter>{amend}"
               f"<filingManager><name>FAKE FUND LP</name></filingManager></coverPage></formData></edgarSubmission>")
    docs = f"<DOCUMENT>\n<TYPE>{form}\n<TEXT>\n<XML>\n{primary}\n</XML>\n</TEXT>\n</DOCUMENT>\n"
    if table:
        its = "".join(
            f"<infoTable><nameOfIssuer>{r[1]}</nameOfIssuer><titleOfClass>{r[2]}</titleOfClass>"
            f"<cusip>{r[0]}</cusip><value>{r[3]}</value><shrsOrPrnAmt><sshPrnamt>{r[4]}</sshPrnamt>"
            f"<sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>"
            + (f"<putCall>{r[5]}</putCall>" if len(r) > 5 else "") + "</infoTable>" for r in rows)
        docs += ("<DOCUMENT>\n<TYPE>INFORMATION TABLE\n<TEXT>\n<XML>\n<informationTable xmlns="
                 f'"http://www.sec.gov/edgar/document/thirteenf/informationtable">{its}</informationTable>\n'
                 "</XML>\n</TEXT>\n</DOCUMENT>\n")
    return f"<SEC-DOCUMENT>\n{docs}</SEC-DOCUMENT>\n"


def holdings(*rows):
    """rows: (cusip, value, shares[, put_call])."""
    return F.aggregate([{"cusip": r[0], "name": f"CO {r[0]}", "cls": "COM", "value": r[1], "shares": r[2],
                         "sh_type": "SH", "put_call": r[3] if len(r) > 3 else None} for r in rows])


# ----------------------------------------------------------------- parsing
def test_split_and_parse_fixture():
    primary, table = F.split_submission(SUB)
    meta = F.parse_primary(primary)
    assert meta["period"] == "2026-06-30" and meta["is_amendment"] is False
    assert meta["amendment_type"] is None and meta["table_value_total"] == 1515000000
    rows = F.parse_info_table(table)
    assert len(rows) == 5
    assert rows[0] == {"cusip": "900000101", "name": "EXAMPLE ROBOTICS INC", "cls": "COM",
                       "value": 600000000.0, "shares": 3000000.0, "sh_type": "SH", "put_call": None}
    assert rows[3]["put_call"] == "CALL" and rows[4]["sh_type"] == "PRN"


def test_value_units_dollars_vs_thousands():
    assert F.value_multiplier("2026-08-14") == 1
    assert F.value_multiplier("2023-01-03") == 1
    assert F.value_multiplier("2022-11-14") == 1000          # $ thousands before the rule change
    _, table = F.split_submission(SUB)
    old = F.parse_info_table(table, multiplier=F.value_multiplier("2022-11-14"))
    assert old[0]["value"] == 600000000.0 * 1000
    parsed = F.parse_filing(SUB, "acc-1", "13F-HR", "2022-11-14")
    assert parsed["value_multiplier"] == 1000


def test_units_heuristic_scales_thousands_filed_after_2023():
    thousands = make_sub("06-30-2026", [("900000101", "A", "COM", 2000, 10000),       # $0.20/share
                                        ("900000202", "B", "COM", 5000, 50000),
                                        ("900000303", "C", "COM", 900, 30000)])
    p = F.check_units(F.parse_filing(thousands, "acc-t", "13F-HR", "2026-08-14"))
    assert p["holdings"]["900000101||SH"]["value"] == 2_000_000
    assert "scaled x1000" in p["unit_note"]
    fine = F.check_units(F.parse_filing(SUB, "acc-1", "13F-HR", "2026-08-14"))
    assert "unit_note" not in fine and fine["holdings"]["900000101||SH"]["value"] == 1e9


def test_aggregate_by_cusip_keeps_options_and_principal_apart():
    parsed = F.parse_filing(SUB, "acc-1", "13F-HR", "2026-08-14")
    h = parsed["holdings"]
    robo = h["900000101||SH"]
    assert robo["value"] == 1_000_000_000 and robo["shares"] == 5_000_000 and robo["rows"] == 2
    assert h["900000101|CALL|SH"]["value"] == 10_000_000
    assert "900000AB1||PRN" in h
    assert set(F._equity(h)) == {"900000101||SH", "900000202||SH"}


def test_original_without_table_is_an_error_but_amendment_is_not():
    no_table = make_sub("06-30-2026", [], table=False)
    with pytest.raises(ValueError):
        F.parse_filing(no_table, "acc-x", "13F-HR", "2026-08-14")
    cover = make_sub("06-30-2026", [], form="13F-HR/A", amendment_type="RESTATEMENT", table=False)
    p = F.parse_filing(cover, "acc-y", "13F-HR/A", "2026-09-01")
    assert p["has_table"] is False and p["is_amendment"] is True


# -------------------------------------------------------------- amendments
def _parsed(acc, form, filed, h, amendment_type=None, has_table=True):
    return {"accession": acc, "form": form, "filed": filed, "is_amendment": form.endswith("/A"),
            "amendment_type": amendment_type, "has_table": has_table, "holdings": h if has_table else None}


def test_resolve_period_amendments():
    orig = _parsed("a1", "13F-HR", "2026-08-14", holdings(("X", 100.0, 10.0), ("Y", 50.0, 5.0)))
    restated = _parsed("a2", "13F-HR/A", "2026-09-02", holdings(("X", 120.0, 12.0)), "RESTATEMENT")
    added = _parsed("a3", "13F-HR/A", "2026-09-10", holdings(("Z", 70.0, 7.0), ("X", 10.0, 1.0)), "NEW HOLDINGS")
    cover = _parsed("a4", "13F-HR/A", "2026-09-11", None, "RESTATEMENT", has_table=False)
    r = F.resolve_period([orig, restated])
    assert set(r["holdings"]) == {"X||SH"} and r["holdings"]["X||SH"]["shares"] == 12.0
    assert r["filed"] == "2026-08-14" and r["amended"] == "2026-09-02"
    r = F.resolve_period([orig, added])
    assert set(r["holdings"]) == {"X||SH", "Y||SH", "Z||SH"} and r["holdings"]["X||SH"]["shares"] == 11.0
    assert orig["holdings"]["X||SH"]["shares"] == 10.0          # inputs not mutated
    r = F.resolve_period([orig, cover])
    assert r["holdings"]["X||SH"]["shares"] == 10.0 and r["amended"] is None and "cover page" in r["notes"][0]
    with pytest.raises(ValueError):
        F.resolve_period([restated])


def test_latest_periods_need_an_original():
    subs = {"filings": {"recent": {
        "form": ["13F-HR/A", "13F-HR", "13F-NT", "13F-HR", "13F-HR/A", "13F-HR", "4"],
        "filingDate": ["2026-09-02", "2026-08-14", "2026-08-14", "2026-05-15", "2026-02-20", "2025-11-14", "2026-01-01"],
        "reportDate": ["2026-06-30", "2026-06-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", ""],
        "accessionNumber": ["a5", "a4", "nt", "a3", "a2", "a1", "f4"]}}}
    fs = F.thirteenf_filings(subs)
    assert [f["accession"] for f in fs] == ["a5", "a4", "a3", "a2", "a1"]
    periods = F.latest_periods(fs)
    assert [p for p, _ in periods] == ["2026-06-30", "2026-03-31"]      # 2025-12-31 has no original
    assert [f["accession"] for f in periods[0][1]] == ["a4", "a5"]      # original first


# -------------------------------------------------------------------- diff
def test_diff_new_add_trim_exit():
    prev = holdings(("KEEP", 100.0, 10.0), ("ADD", 100.0, 10.0), ("TRIM", 100.0, 10.0), ("GONE", 200.0, 20.0),
                    ("TINY", 100.0, 1000.0))
    cur = holdings(("KEEP", 110.0, 10.0), ("ADD", 190.0, 15.0), ("TRIM", 40.0, 4.0), ("NEW", 300.0, 3.0),
                   ("TINY", 100.0, 1005.0), ("OPT", 999.0, 1.0, "PUT"))
    d = F.diff(cur, prev)
    by = {m["cusip"]: m for m in d["moves"]}
    assert set(by) == {"ADD", "TRIM", "NEW", "GONE"}                    # KEEP and +0.5% TINY unchanged; PUT ignored
    assert by["NEW"]["side"] == "NEW" and by["NEW"]["change_pct"] is None
    assert by["ADD"]["side"] == "ADD" and by["ADD"]["change_pct"] == pytest.approx(50.0)
    assert by["TRIM"]["side"] == "TRIM" and by["TRIM"]["change_pct"] == pytest.approx(-60.0)
    assert by["GONE"]["side"] == "EXIT" and by["GONE"]["prev_value"] == 200.0 and by["GONE"]["value"] == 0.0
    total = 110 + 190 + 40 + 300 + 100
    assert d["total_value"] == total and d["non_equity_rows"] == 1
    assert by["NEW"]["pct_portfolio"] == pytest.approx(300 / total * 100)
    assert by["GONE"]["prev_pct_portfolio"] == pytest.approx(200 / 600 * 100)
    assert [m["cusip"] for m in d["moves"]] == ["NEW", "GONE", "ADD", "TRIM"]   # by dollar size moved
    assert F.move_label(by["NEW"]).startswith("new · $300 · ")
    assert F.move_label(by["ADD"]).startswith("+50% shares · $190 · ")
    assert F.move_label(by["GONE"]).startswith("sold out · was $200")


def test_split_detection_needs_evidence_across_funds():
    # 5:1 split: price ~1/5, holders that did not trade sit exactly at 5x
    split = [{"S": (5.0, 0.21)}, {"S": (5.0, 0.21)}, {"S": (7.5, 0.21)}]
    assert F.detect_splits(split) == {"S": 5}
    # price quadrupled, share counts all over the place: not a split
    scattered = [{"M": (0.079, 3.42)}, {"M": (0.098, 3.42)}, {"M": (0.13, 3.42)}, {"M": (0.59, 3.42)},
                 {"M": (7.9, 3.42)}, {"M": (18.9, 3.42)}]
    assert F.detect_splits(scattered) == {}
    # price halved but holders kept (about) the same count: not a split
    assert F.detect_splits([{"H": (0.98, 0.49)}, {"H": (1.0, 0.49)}, {"H": (3.1, 0.49)}, {"H": (35.7, 0.49)}]) == {}
    # one fund alone never proves a split
    assert F.detect_splits([{"S": (5.0, 0.2)}]) == {}
    moves = F.diff(holdings(("S", 120.0, 60.0)), holdings(("S", 100.0, 10.0)))["moves"]
    assert moves[0]["change_pct"] == pytest.approx(500.0)
    adj = F.apply_splits(moves, {"S": 5}, 120.0, 100.0)
    assert adj[0]["change_pct"] == pytest.approx(20.0) and "after 5:1 split" in F.move_label(adj[0])
    assert F.apply_splits(F.diff(holdings(("S", 20.0, 50.0)), holdings(("S", 100.0, 10.0)))["moves"],
                          {"S": 5}, 20.0, 100.0) == []                  # unchanged once adjusted


# ---------------------------------------------------------------- tickers
COMPANY_TICKERS = {
    "0": {"cik_str": 1, "ticker": "EXRB", "title": "Example Robotics, Inc."},
    "1": {"cik_str": 2, "ticker": "SFDA", "title": "Sample Foods Co"},
    "2": {"cik_str": 2, "ticker": "SFD-B", "title": "Sample Foods Co"},
    "4": {"cik_str": 3, "ticker": "WFX", "title": "WELLS FARGOX & CO/MN"},
    "5": {"cik_str": 3, "ticker": "WFX-PL", "title": "WELLS FARGOX & CO/MN"},
    "6": {"cik_str": 4, "ticker": "TWIN", "title": "Twin Corp"},
    "7": {"cik_str": 5, "ticker": "TWIX", "title": "TWIN CORP /DE/"},
    "8": {"cik_str": 6, "ticker": "DWD", "title": "Disney Walter Demo Co"},
    "9": {"cik_str": 7, "ticker": "TSDM", "title": "Taiwan Semiconductor Demo Manufacturing Co Ltd"},
    "10": {"cik_str": 8, "ticker": "BABX", "title": "Alibabax Group Holding Ltd"},
    "11": {"cik_str": 8, "ticker": "BABXF", "title": "Alibabax Group Holding Ltd"},
}


def test_ticker_map_confident_matches_only():
    tm = F.TickerMap(COMPANY_TICKERS)
    assert tm.lookup("900000101", "EXAMPLE ROBOTICS INC", "COM") == "EXRB"
    assert tm.lookup("x", "SAMPLE FOODS CO", "CL B") == "SFD-B"          # class picks the dashed ticker
    assert tm.lookup("x", "WELLS FARGOX & CO", "COM") == "WFX"           # primary ticker, not the preferred
    assert tm.lookup("x", "WELLS FARGOX & CO", "PFD SER L") is None
    assert tm.lookup("x", "TWIN CORP", "COM") is None                    # two companies, same name
    assert tm.lookup("x", "WALTER DEMO DISNEY", "COM") == "DWD"          # word order differs
    assert tm.lookup("x", "TAIWAN SEMICONDUCTOR DEMO MANUF", "SPONSORED ADS") == "TSDM"   # truncated name
    assert tm.lookup("x", "ALIBABAX GROUP HLDG LTD", "SPONSORED ADS") == "BABX"         # OTC line ignored
    assert tm.lookup("x", "UNKNOWN THING INC", "COM") is None
    assert tm.lookup("02079K305", "ALPHABET INC", "CAP STK CL A") == "GOOGL"            # override
    assert F.TickerMap(None).lookup("x", "EXAMPLE ROBOTICS INC", "COM") is None


# ------------------------------------------------------------------ loader
PREV = make_sub("03-31-2026", [("900000101", "EXAMPLE ROBOTICS INC", "COM", 800000000, 4000000),
                               ("900000303", "GONE CORP", "COM", 100000000, 1000000)])
LATEST = make_sub("06-30-2026", [("900000101", "EXAMPLE ROBOTICS INC", "COM", 1200000000, 5000000),
                                 ("900000202", "SAMPLE FOODS CO", "CL A", 500000000, 10000000)])
AMEND = make_sub("06-30-2026", [("900000404", "HIDDEN CO", "COM", 50000000, 100000)],
                 form="13F-HR/A", amendment_type="NEW HOLDINGS")
SUBMISSIONS = {"filings": {"recent": {
    "form": ["13F-HR/A", "13F-HR", "13F-HR"], "filingDate": ["2026-09-01", "2026-08-14", "2026-05-15"],
    "reportDate": ["2026-06-30", "2026-06-30", "2026-03-31"],
    "accessionNumber": ["0009000010-26-000003", "0009000010-26-000002", "0009000010-26-000001"]}}}
FUND = F.Fund("example", "Example Capital", "Jane Doe", 9000010)
FUND2 = F.Fund("broken", "Broken Fund", "John Doe", 9000011)


class FakeSec:
    def __init__(self):
        self.calls = []

    def __call__(self, url, ua):
        assert ua == UA
        self.calls.append(url)
        if url == F.TICKERS_URL:
            return json.dumps(COMPANY_TICKERS)
        if url.endswith("CIK0009000010.json"):
            return json.dumps(SUBMISSIONS)
        if url.endswith("CIK0009000011.json"):
            raise F.SEC.SecError("SEC HTTP 404", 404)
        return {"0009000010-26-000001": PREV, "0009000010-26-000002": LATEST,
                "0009000010-26-000003": AMEND}[url.rsplit("/", 1)[-1][:-4]]


class NoWait:
    def wait(self):
        pass


def make_loader(tmp_path, getter, funds=(FUND, FUND2), wall=lambda: 1_000_000.0):
    return F.Loader(UA, cache_dir=tmp_path, funds=funds, getter=getter, limiter=NoWait(), wall=wall)


def test_loader_end_to_end_and_cache(tmp_path):
    g = FakeSec()
    ld = make_loader(tmp_path, g)
    ld.cycle()
    by = {s.fund.key: s for s in ld.snapshot()}
    ok, bad = by["example"], by["broken"]
    assert ok.status == "ok" and bad.status == "error" and "404" in bad.error
    r = ok.result
    assert (r["period"], r["filed"], r["amended"], r["prev_period"]) == ("2026-06-30", "2026-08-14", "2026-09-01", "2026-03-31")
    sides = {m["cusip"]: m["side"] for m in r["moves"]}
    assert sides == {"900000101": "ADD", "900000202": "NEW", "900000303": "EXIT", "900000404": "NEW"}
    assert len(g.calls) == 6                         # tickers + 2 filing lists + 3 filings
    assert (tmp_path / "filings" / "0009000010-26-000002.json").exists()

    # a restart within 12 h: everything from disk, no request at all
    g2 = FakeSec()
    ld2 = make_loader(tmp_path, g2, funds=(FUND,))
    ld2.cycle()
    assert g2.calls == [] and ld2.snapshot()[0].result["moves"] == r["moves"]
    # 13 h later: only the filing list is refreshed; filings never refetched
    g3 = FakeSec()
    ld3 = make_loader(tmp_path, g3, funds=(FUND,), wall=lambda: 1_000_000.0 + 13 * 3600)
    ld3.cycle()
    assert g3.calls == [F.SUBMISSIONS_URL.format(cik=9000010)]


def test_loader_stale_list_is_used_and_reported(tmp_path):
    make_loader(tmp_path, FakeSec(), funds=(FUND,)).cycle()

    def failing(url, ua):
        raise F.SEC.SecError("SEC HTTP 503", 503)
    ld = make_loader(tmp_path, failing, funds=(FUND,), wall=lambda: 1_000_000.0 + 13 * 3600)
    ld.cycle()
    st = ld.snapshot()[0]
    assert st.status == "ok"
    assert any("refresh failed (SEC HTTP 503)" in n for n in st.result["notes"])


def test_build_rows_sort_yours_and_most_bought(tmp_path):
    ld = make_loader(tmp_path, FakeSec())
    ld.cycle()
    out = F.build(ld.snapshot(), ld.tickers, held={"EXRB"}, watch={"SFDA"}, days=180, today=TODAY,
                  running=False, holdings_note="portfolio session not authenticated; HELD is not marked")
    assert out["type"] == "funds" and out["configured"] is True
    assert out["rule"] == "13F · quarterly, filed up to 45 days after quarter end"
    assert out["partial"] is True and out["skipped"] == ["Broken Fund"] and "404" in out["skipped_reasons"]["Broken Fund"]
    assert out["loading"] is False and out["progress"] == {"done": 2, "total": 2}
    rows = out["rows"]
    assert [r["side"] for r in rows] == ["ADD", "NEW", "EXIT", "NEW"]     # same filing: by value
    add = rows[0]
    assert add["symbol"] == "EXRB" and add["yours"] == "HELD" and add["who"] == "Example Capital"
    assert add["role"] == "Fund" and add["filed"] == "2026-08-14" and add["traded"] == "2026-06-30"
    assert add["lag_days"] == 45 and add["amended"] == "2026-09-01"
    assert add["change_pct"] == pytest.approx(25.0) and add["amount_min"] == add["amount_max"] == 1.2e9
    assert add["amount_label"].startswith("+25% shares · $1.2B · ")
    assert rows[1]["symbol"] == "SFDA" and rows[1]["yours"] == "WATCH"
    assert rows[2]["symbol"] is None and rows[2]["amount_min"] == 100000000     # EXIT: previous value
    assert [(m["symbol"], m["count"]) for m in out["most_bought"]] == [("SFDA", 1), ("EXRB", 1)]   # ties: by $ added
    assert out["tickers"] == {"mapped": 2, "total": 4, "error": None}
    assert out["holdings_note"].startswith("portfolio session")
    fund = out["funds"][0]
    assert fund["period"] == "2026-06-30" and fund["in_window"] is True and fund["moves"] == 4
    # outside the window: the fund is listed, its rows are not
    later = F.build(ld.snapshot(), ld.tickers, held=set(), watch=set(), days=30, today=TODAY, running=False)
    assert later["rows"] == [] and later["funds"][0]["in_window"] is False


def test_build_while_loading():
    states = [F.FundState(FUND), F.FundState(FUND2)]
    out = F.build(states, F.TickerMap(None), held=set(), watch=set(), days=180, today=TODAY, running=True)
    assert out["loading"] is True and out["partial"] is True and out["skipped"] == []
    assert out["progress"] == {"done": 0, "total": 2} and out["rows"] == []


def test_curated_list_is_sane():
    keys = [f.key for f in F.FUNDS]
    ciks = [c for f in F.FUNDS for c in f.ciks]
    assert len(keys) == len(set(keys)) and len(ciks) == len(set(ciks)) and 15 <= len(F.FUNDS) <= 25


# -------------------------------------------------------------- endpoint
@pytest.fixture
def api(monkeypatch, tmp_path):
    from terminal import api_v2
    api_v2.bind(feed=None, yf=None, avanza=None, auth=type("A", (), {"configured": False, "token": None})())
    app = FastAPI()
    app.include_router(api_v2.router)
    yield TestClient(app)
    F.S.loader = None


def test_endpoint_not_configured(api, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "")
    r = api.get("/api/disclosures?type=funds")
    assert r.status_code == 503
    assert r.json() == {"error": F.NOT_CONFIGURED_ERROR, "configured": False, "type": "funds"}


def test_endpoint_loader_not_running(api, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    F.S.loader = None
    r = api.get("/api/disclosures?type=funds")
    assert r.status_code == 503 and r.json()["configured"] is True


def test_endpoint_serves_loaded_funds_without_alpha_vantage(api, monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "")                     # not needed for funds
    ld = make_loader(tmp_path, FakeSec(), funds=(FUND,))
    ld.cycle()
    F.S.loader = ld
    d = api.get("/api/disclosures?type=funds&days=3650").json()
    assert d["type"] == "funds" and d["loading"] is False and len(d["rows"]) == 4
    assert d["holdings_note"] == "portfolio session not authenticated; HELD is not marked"
    for k in ("rule", "as_of", "source", "partial", "skipped", "skipped_reasons", "rows", "most_bought"):
        assert k in d
