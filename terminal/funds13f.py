"""
What well-known funds bought and sold last quarter, from their SEC 13F-HR
filings (served as `GET /api/disclosures?type=funds`, see terminal/api_v2.py).

A 13F-HR lists a manager's long US-listed equity positions (plus listed
options and some convertibles) at quarter end. It is filed up to 45 days
after the quarter and says nothing about shorts, cash, non-US holdings or
anything traded within the quarter. Diffing two consecutive 13Fs gives
NEW / ADD / TRIM / EXIT per position -- the only "trade" a 13F can show.

Source details, verified 2026-09-24 against live EDGAR responses:

  Filing list  https://data.sec.gov/submissions/CIK##########.json
               filings.recent.{form, filingDate, reportDate, accessionNumber};
               forms 13F-HR and 13F-HR/A (13F-NT = holdings reported by
               another manager, ignored).
  Filing       https://www.sec.gov/Archives/edgar/data/{cik}/{acc-no-dashes}/{acc}.txt
               The complete submission: primary_doc.xml (<edgarSubmission>:
               period, amendmentType, tableValueTotal) and the information
               table (<informationTable>) in one request.
  Tickers      https://www.sec.gov/files/company_tickers.json (CIK, ticker,
               title). There is no free CUSIP->ticker map, so tickers come
               from matching the 13F issuer name against the SEC title; see
               TickerMap. No confident match -> ticker null, never a guess.

Units: `value` is in whole dollars for filings made on/after 2023-01-03 and
in thousands of dollars before that (SEC 13F FAQ); `value_multiplier`.

Amendments: per report period, the original 13F-HR is the base. A 13F-HR/A
with amendmentType RESTATEMENT replaces the holdings; NEW HOLDINGS adds
positions (typically ones held back under confidential treatment); an
amendment with no information table (cover-page fixes) changes nothing.

SEC fair access: the User-Agent comes from env SEC_USER_AGENT (see
terminal/insiders.py) and every request goes through the process-wide
insiders.SEC_LIMITER. Parsed filings are cached forever under
data/cache/sec13f/ keyed by accession (a filing never changes); filing lists
are refreshed at most every 12 h; the ticker list weekly. The loader runs in a
background thread started by the app's lifespan; the endpoint only reads
its in-memory results, so a request never waits on the SEC.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter

from terminal import insiders as SEC

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "sec13f"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_URL = SEC.FILING_URL
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

LIST_REFRESH_S = 12 * 3600          # filing lists: at most every 12 h
TICKERS_REFRESH_S = 7 * 24 * 3600
RETRY_FAILED_S = 15 * 60            # a fund that failed is retried sooner
FILING_TIMEOUT_S = 90               # Citadel's full submission is ~8 MB
MIN_CHANGE_PCT = 1.0                # |share change| below this = unchanged
MAX_MOVES_PER_FUND = 40             # biggest moves by dollar size
DOLLAR_UNIT_FROM = date(2023, 1, 3)

RULE = "13F · quarterly, filed up to 45 days after quarter end"
SOURCE = "SEC EDGAR 13F-HR information tables (curated fund list)"
NOT_CONFIGURED_ERROR = SEC.NOT_CONFIGURED_ERROR


@dataclass(frozen=True)
class Fund:
    key: str
    name: str        # what the UI shows
    manager: str     # the public face of the fund
    cik: int         # the entity filing the latest 13F-HR
    # Other entities whose 13F-HRs belong to the same fund. Per report period
    # every CIK's (amended) holdings are summed: each manager reports only
    # the positions it has discretion over, so they do not overlap.
    also: tuple[int, ...] = ()

    @property
    def ciks(self) -> tuple[int, ...]:
        return (self.cik, *self.also)


# Every CIK verified 2026-09-24 against data.sec.gov/submissions: the entity
# name matches and it filed a 13F-HR for a 2026 period (except Scion, below).
FUNDS: tuple[Fund, ...] = (
    Fund("berkshire", "Berkshire Hathaway", "Warren Buffett", 1067983),
    # Pershing Square Inc. (2026053) reports the holdings from Q2 2026 (the LP
    # filed a 13F-NT); for Q1 2026 the LP (1336528) filed them and the Inc
    # only its own Howard Hughes stake, so both CIKs are read and summed.
    Fund("pershing", "Pershing Square", "Bill Ackman", 2026053, also=(1336528,)),
    Fund("bridgewater", "Bridgewater Associates", "Ray Dalio (founder)", 1350694),
    Fund("renaissance", "Renaissance Technologies", "Jim Simons (founder)", 1037389),
    Fund("citadel", "Citadel Advisors", "Ken Griffin", 1423053),
    Fund("tiger", "Tiger Global", "Chase Coleman", 1167483),
    Fund("coatue", "Coatue Management", "Philippe Laffont", 1135730),
    Fund("appaloosa", "Appaloosa", "David Tepper", 1656456),
    Fund("thirdpoint", "Third Point", "Dan Loeb", 1040273),
    Fund("baupost", "Baupost Group", "Seth Klarman", 1061768),
    Fund("duquesne", "Duquesne Family Office", "Stanley Druckenmiller", 1536411),
    Fund("soros", "Soros Fund Management", "George Soros", 1029160),
    Fund("icahn", "Icahn Enterprises (Carl Icahn)", "Carl Icahn", 921669),
    # Greenlight's 13F is filed by DME Capital Management LP; the old
    # Greenlight Capital Inc CIK (1079114) has filed nothing since 2024.
    Fund("greenlight", "Greenlight Capital", "David Einhorn", 1489933),
    Fund("viking", "Viking Global", "Andreas Halvorsen", 1103804),
    Fund("lonepine", "Lone Pine Capital", "Stephen Mandel (founder)", 1061165),
    Fund("himalaya", "Himalaya Capital", "Li Lu", 1709323),
    Fund("ark", "ARK Investment Management", "Cathie Wood", 1697748),
    # Deregistered in late 2025: the last 13F is for 2025-09-30, so it falls
    # outside the default 180-day window. Kept so the page says so.
    Fund("scion", "Scion Asset Management", "Michael Burry", 1649339),
)


def user_agent() -> str | None:
    return SEC.user_agent()


# ------------------------------------------------------------------ parsing
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _find(el: ET.Element | None, *path: str) -> ET.Element | None:
    for p in path:
        el = _child(el, p)
    return el


def _text(el: ET.Element | None, *path: str) -> str | None:
    n = _find(el, *path)
    if n is None or n.text is None:
        return None
    return n.text.strip() or None


def _iter_local(el: ET.Element, name: str):
    for n in el.iter():
        if _local(n.tag) == name:
            yield n


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


_DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
_TYPE_RE = re.compile(r"<TYPE>([^\n<]+)")
_XML_RE = re.compile(r"<XML>\s*(.*?)\s*</XML>", re.S)


def split_submission(txt: str) -> tuple[str | None, str | None]:
    """(primary_doc xml, information table xml) from a complete .txt submission."""
    primary = table = None
    for doc in _DOC_RE.findall(txt):
        m = _XML_RE.search(doc)
        if not m:
            continue
        xml = m.group(1)
        typ = (_TYPE_RE.search(doc).group(1).strip().upper() if _TYPE_RE.search(doc) else "")
        if "informationTable" in xml[:2000] or typ == "INFORMATION TABLE":
            table = xml
        elif "edgarSubmission" in xml[:2000] or typ.startswith("13F-HR"):
            primary = xml
    return primary, table


def _mdy(s: str | None) -> str | None:
    """'06-30-2026' -> '2026-06-30'."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m-%d-%Y").date().isoformat()
    except ValueError:
        return None


def parse_primary(xml: str) -> dict:
    root = ET.fromstring(xml)
    cover = _find(root, "formData", "coverPage")
    summary = _find(root, "formData", "summaryPage")
    is_amend = (_text(cover, "isAmendment") or "").lower() == "true"
    return {
        "submission_type": _text(root, "headerData", "submissionType"),
        "period": _mdy(_text(cover, "reportCalendarOrQuarter"))
                  or _mdy(_text(root, "headerData", "filerInfo", "periodOfReport")),
        "is_amendment": is_amend,
        "amendment_type": (_text(cover, "amendmentInfo", "amendmentType") or "").upper() or None,
        "report_type": _text(cover, "reportType"),
        "manager_name": _text(cover, "filingManager", "name"),
        "table_entry_total": _num(_text(summary, "tableEntryTotal")),
        "table_value_total": _num(_text(summary, "tableValueTotal")),
    }


def value_multiplier(filed: str) -> int:
    """13F `value` was in $ thousands until the 2023-01-03 rule change."""
    return 1000 if date.fromisoformat(filed[:10]) < DOLLAR_UNIT_FROM else 1


def parse_info_table(xml: str, multiplier: int = 1) -> list[dict]:
    """One dict per <infoTable> row, value in dollars."""
    root = ET.fromstring(xml)
    rows = []
    for it in _iter_local(root, "infoTable"):
        cusip = (_text(it, "cusip") or "").upper()
        if not cusip:
            raise ValueError("infoTable row without a CUSIP")
        value = _num(_text(it, "value"))
        rows.append({
            "cusip": cusip,
            "name": _text(it, "nameOfIssuer"),
            "cls": _text(it, "titleOfClass"),
            "value": None if value is None else value * multiplier,
            "shares": _num(_text(it, "shrsOrPrnAmt", "sshPrnamt")),
            "sh_type": (_text(it, "shrsOrPrnAmt", "sshPrnamtType") or "SH").upper(),
            "put_call": (_text(it, "putCall") or "").upper() or None,
        })
    return rows


def check_units(parsed: dict) -> dict:
    """Some filers still report `value` in $ thousands after the 2023 switch
    to dollars (Baupost and Duquesne did in 2026). A share price is never a
    fraction of a dollar across a whole portfolio, so when the median implied
    price (value / shares) is below $0.50 the values are scaled x1000 and the
    fund's notes say so. Returns a copy; the cached parse stays as filed."""
    h = parsed.get("holdings")
    if not h or parsed.get("value_multiplier") != 1:
        return parsed
    px = sorted(v["value"] / v["shares"] for v in h.values()
                if v["sh_type"] == "SH" and not v["put_call"] and v["shares"] and v["value"])
    if len(px) < 3 or px[len(px) // 2] >= 0.5:
        return parsed
    out = dict(parsed)
    out["holdings"] = {k: {**v, "value": v["value"] * 1000} for k, v in h.items()}
    out["unit_note"] = (f"{parsed['accession']}: values filed in $ thousands (median implied price "
                        f"${px[len(px) // 2]:.2f}), scaled x1000")
    return out


def position_key(r: dict) -> str:
    return f"{r['cusip']}|{r.get('put_call') or ''}|{r.get('sh_type') or 'SH'}"


def aggregate(rows: list[dict]) -> dict[str, dict]:
    """Sum rows that describe the same position (13Fs repeat a CUSIP once per
    sub-manager / investment-discretion combination)."""
    out: dict[str, dict] = {}
    for r in rows:
        k = position_key(r)
        a = out.get(k)
        if a is None:
            out[k] = {"cusip": r["cusip"], "name": r["name"], "cls": r["cls"], "put_call": r["put_call"],
                      "sh_type": r["sh_type"], "value": r["value"] or 0.0, "shares": r["shares"] or 0.0,
                      "rows": 1}
        else:
            a["value"] += r["value"] or 0.0
            a["shares"] += r["shares"] or 0.0
            a["rows"] += 1
    return out


def parse_filing(txt: str, accession: str, form: str, filed: str) -> dict:
    """Everything kept from one submission. Raises ValueError when an original
    13F-HR carries no information table (reported, never swallowed)."""
    primary_xml, table_xml = split_submission(txt)
    if primary_xml is None:
        raise ValueError("no primary_doc (<edgarSubmission>) in submission")
    meta = parse_primary(primary_xml)
    mult = value_multiplier(filed)
    holdings = aggregate(parse_info_table(table_xml, mult)) if table_xml else None
    if holdings is None and not meta["is_amendment"]:
        raise ValueError("13F-HR without an information table")
    return {"accession": accession, "form": form, "filed": filed, **meta,
            "value_multiplier": mult, "has_table": holdings is not None, "holdings": holdings}


# ----------------------------------------------------------- filing selection
def thirteenf_filings(submissions: dict) -> list[dict]:
    """13F-HR and 13F-HR/A entries from a submissions JSON, newest first."""
    r = submissions.get("filings", {}).get("recent", {})
    out = []
    for i, form in enumerate(r.get("form", [])):
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        out.append({"form": form, "filed": r["filingDate"][i], "period": r["reportDate"][i] or None,
                    "accession": r["accessionNumber"][i]})
    out.sort(key=lambda f: (f["filed"], f["accession"]), reverse=True)
    return out


def latest_periods(filings: list[dict], n: int = 2) -> list[tuple[str, list[dict]]]:
    """The newest `n` report periods that have an original 13F-HR, each with its
    filings oldest first (original, then amendments)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for f in filings:
        if f["period"]:
            by[f["period"]].append(f)
    periods = sorted((p for p, fs in by.items() if any(f["form"] == "13F-HR" for f in fs)), reverse=True)
    return [(p, sorted(by[p], key=lambda f: (f["filed"], f["accession"]))) for p in periods[:n]]


def resolve_period(parsed: list[dict]) -> dict:
    """Apply amendments (oldest first) to the original filing's holdings."""
    holdings: dict[str, dict] | None = None
    filed = amended = None
    notes = []
    for f in parsed:
        if not f["is_amendment"] and f["form"] == "13F-HR":
            holdings = {k: dict(v) for k, v in f["holdings"].items()}
            filed = f["filed"]
            continue
        if holdings is None:
            continue                                    # amendment before any original: ignored
        if not f["has_table"]:
            notes.append(f"{f['accession']}: amendment without holdings (cover page only)")
            continue
        if f["amendment_type"] == "NEW HOLDINGS":
            for k, v in f["holdings"].items():
                a = holdings.get(k)
                if a is None:
                    holdings[k] = dict(v)
                else:
                    a["value"] += v["value"]
                    a["shares"] += v["shares"]
        else:                                           # RESTATEMENT (or unlabelled): replaces
            holdings = {k: dict(v) for k, v in f["holdings"].items()}
        amended = f["filed"]
    if holdings is None:
        raise ValueError("no original 13F-HR among the filings for this period")
    return {"holdings": holdings, "filed": filed, "amended": amended, "notes": notes}


def merge_parts(parts: list[dict]) -> dict:
    """Sum one period's resolved holdings across a fund's filing entities."""
    if len(parts) == 1:
        return parts[0]
    holdings: dict[str, dict] = {}
    for p in parts:
        for k, v in p["holdings"].items():
            a = holdings.get(k)
            if a is None:
                holdings[k] = dict(v)
            else:
                a["value"] += v["value"]
                a["shares"] += v["shares"]
    amended = [p["amended"] for p in parts if p["amended"]]
    return {"holdings": holdings, "filed": max(p["filed"] for p in parts),
            "amended": max(amended) if amended else None, "notes": [n for p in parts for n in p["notes"]]}


# --------------------------------------------------------------------- diff
def _equity(h: dict[str, dict]) -> dict[str, dict]:
    """Common/ADR share positions only: listed options (putCall) and principal
    amounts (PRN, convertibles) are not share positions to diff."""
    return {k: v for k, v in h.items() if not v["put_call"] and v["sh_type"] == "SH"}


def _move(n: dict | None, o: dict | None, total: float, prev_total: float, split: float | None = None) -> dict | None:
    """One position's quarter-over-quarter change, or None when unchanged
    (|share change| < MIN_CHANGE_PCT). `split` = k for a k-for-1 split
    between the quarters (13F share counts are not split-adjusted)."""
    if n and not o:
        side, moved, change = "NEW", n["value"], None
    elif o and not n:
        side, moved, change = "EXIT", o["value"], -100.0
    else:
        base = o["shares"] * (split or 1)
        if not base:
            return None
        change = (n["shares"] / base - 1) * 100
        if abs(change) < MIN_CHANGE_PCT:
            return None
        side = "ADD" if change > 0 else "TRIM"
        px = n["value"] / n["shares"] if n["shares"] else 0.0
        moved = abs(n["shares"] - base) * px
    ref = n or o
    return {
        "cusip": ref["cusip"], "issuer": ref["name"], "cls": ref["cls"], "side": side,
        "value": n["value"] if n else 0.0,
        "prev_value": o["value"] if o else 0.0,
        "shares": n["shares"] if n else 0.0,
        "prev_shares": o["shares"] if o else 0.0,
        "change_pct": change,
        "split_adjusted": split,
        "pct_portfolio": (n["value"] / total * 100) if n and total else None,
        "prev_pct_portfolio": (o["value"] / prev_total * 100) if o and prev_total else None,
        "moved_value": moved,
    }


def diff(latest: dict[str, dict], previous: dict[str, dict]) -> dict:
    """NEW/ADD/TRIM/EXIT moves, biggest dollar size first. Also returns
    `ratios`: (share ratio, implied price ratio) for positions held in both
    quarters whose price moved 1.6x or more -- the evidence detect_splits()
    pools across funds."""
    cur, prev = _equity(latest), _equity(previous)
    total = sum(v["value"] for v in cur.values()) or 0.0
    prev_total = sum(v["value"] for v in prev.values()) or 0.0
    moves, ratios = [], {}
    for k in cur.keys() | prev.keys():
        n, o = cur.get(k), prev.get(k)
        if n and o and n["shares"] and o["shares"] and n["value"] and o["value"]:
            q = (n["value"] / n["shares"]) / (o["value"] / o["shares"])
            if abs(math.log(q)) >= math.log(1.6):
                ratios[n["cusip"]] = (n["shares"] / o["shares"], q)
        m = _move(n, o, total, prev_total)
        if m:
            moves.append(m)
    moves.sort(key=lambda m: -m["moved_value"])
    return {"moves": moves, "ratios": ratios, "total_value": total, "prev_total_value": prev_total,
            "positions": len(cur), "prev_positions": len(prev),
            "non_equity_rows": len(latest) - len(cur)}


_SPLIT_RATIOS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50)


def _near(a: float, b: float, tol: float) -> bool:
    return abs(math.log(a / b)) < math.log(1 + tol)


def detect_splits(ratio_sets: list[dict[str, tuple[float, float]]]) -> dict[str, float]:
    """CUSIP -> k for a k-for-1 split (k < 1: reverse split) between the two
    quarters, from every fund's (share ratio, implied price ratio) for the
    positions it held in both. A split moves the price by ~1/k and every
    holder's share count by k (exactly k for holders that did not trade); a
    trade moves one fund's count. Accepted only when the median price ratio
    is within 10% of 1/k and either
      - at least 2 holders (and a third of them) sit within 2% of k, or
      - at least 3 holders, their median share ratio within 25% of k, and
        no holder with a share count within 5% of unchanged (a holder that
        did not trade through a real split would sit at k, not at 1).
    Anything less stays unadjusted (a raw +100%/-50% is visible; a wrong
    adjustment would not be)."""
    obs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for rs in ratio_sets:
        for cusip, rq in rs.items():
            obs[cusip].append(tuple(rq))
    out = {}
    for cusip, xs in obs.items():
        if len(xs) < 2:
            continue
        rs = sorted(r for r, _ in xs)
        r_med = rs[len(rs) // 2] if len(rs) % 2 else math.sqrt(rs[len(rs) // 2 - 1] * rs[len(rs) // 2])
        q_med = sorted(q for _, q in xs)[len(xs) // 2]
        unchanged = sum(1 for r in rs if _near(r, 1.0, 0.05))
        for k in _SPLIT_RATIOS:
            for f in (k, 1 / k):
                if not _near(q_med * f, 1.0, 0.10):
                    continue
                exact = sum(1 for r in rs if _near(r, f, 0.02))
                if (exact >= 2 and exact * 3 >= len(rs)) or (
                        len(rs) >= 3 and _near(r_med, f, 0.25) and unchanged == 0):
                    out[cusip] = f
    return out


def apply_splits(moves: list[dict], splits: dict[str, float], total: float, prev_total: float) -> list[dict]:
    """Recompute ADD/TRIM moves on split CUSIPs with split-adjusted share
    counts (dropping ones that turn out unchanged), re-sorted by size."""
    if not splits:
        return moves
    out = []
    for m in moves:
        k = splits.get(m["cusip"])
        if k is None or m["side"] not in ("ADD", "TRIM"):
            out.append(m)
            continue
        n = {"cusip": m["cusip"], "name": m["issuer"], "cls": m["cls"], "value": m["value"], "shares": m["shares"]}
        o = {"cusip": m["cusip"], "name": m["issuer"], "cls": m["cls"], "value": m["prev_value"],
             "shares": m["prev_shares"]}
        adj = _move(n, o, total, prev_total, split=k)
        if adj:
            out.append(adj)
    out.sort(key=lambda m: -m["moved_value"])
    return out


# ------------------------------------------------------------ ticker mapping
_DROP = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "NV", "SA",
         "AG", "SE", "LLC", "LP", "L", "P", "THE", "OF", "AND", "DEL", "NEW", "COM", "HLDG", "HLDGS", "HLDNGS",
         "HOLDING", "HOLDINGS", "GROUP", "GRP", "SPONSORED", "ADR", "ADS", "N", "V", "S", "A", "DE", "MD",
         "TR", "TRUST", "CL", "CLASS", "LTEE", "CV", "AB", "ASA", "SPA", "BHD", "PUBLIC"}
_ABBR = {"INTL": "INTERNATIONAL", "COS": "COMPANIES", "MFG": "MANUFACTURING", "SVCS": "SERVICES",
         "TECHNOLOGIES": "TECHNOLOGY", "TECH": "TECHNOLOGY", "TECHN": "TECHNOLOGY", "SYS": "SYSTEMS",
         "PHARMACEUTICALS": "PHARMA", "PHARMACEUTICAL": "PHARMA", "BANCORPORATION": "BANCORP",
         "FINL": "FINANCIAL", "MGMT": "MANAGEMENT", "COMMUNICATIONS": "COMMUNICATION", "COMM": "COMMUNICATION",
         "LABS": "LABORATORIES", "ENTMT": "ENTERTAINMENT", "SOLUTIONS": "SOLUTION", "RES": "RESOURCES",
         "AMER": "AMERICA", "AMERN": "AMERICAN", "PPTYS": "PROPERTIES", "INVT": "INVESTMENT", "CAP": "CAPITAL",
         "MATLS": "MATERIALS", "PETE": "PETROLEUM", "PWR": "POWER", "ELEC": "ELECTRIC", "MTRS": "MOTORS",
         "INSTRS": "INSTRUMENTS", "SOUTHN": "SOUTHERN", "RLTY": "REALTY", "CMNTYS": "COMMUNITIES",
         "INDS": "INDUSTRIES", "AIRLS": "AIRLINES", "MKTS": "MARKETS", "RUBR": "RUBBER", "STR": "STREET",
         "BK": "BANK", "PAC": "PACIFIC", "FGHT": "FREIGHT", "NATL": "NATIONAL", "GEN": "GENERAL",
         "ENTERPRISES": "ENTERPRISE", "SVC": "SERVICE", "CHEM": "CHEMICAL", "CHEMICALS": "CHEMICAL",
         "BANCSHARES": "BANCSHARES", "HEALTHCARE": "HEALTH CARE", "THERAPEUTIC": "THERAPEUTICS",
         "BIOPHARMACEUTICALS": "BIOPHARMA", "SEMICONDUCTORS": "SEMICONDUCTOR", "GLOBL": "GLOBAL"}


def norm_name(name: str | None) -> str:
    """'BANK AMERICA CORP /DE/' and 'Bank of America Corp' -> 'BANK AMERICA'."""
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"/[A-Z]{2,3}/?", " ", s)             # /DE/, /MD, state suffixes
    s = re.sub(r"[^A-Z0-9 ]", " ", s.replace(".COM", " COM").replace("'", ""))
    words = " ".join(_ABBR.get(w, w) for w in s.split()).split()
    return " ".join(w for w in words if w not in _DROP)


def _keys(n: str) -> tuple[str, str]:
    """Word order and spacing differ between sources ('DISNEY WALT' vs 'Walt
    Disney', 'EXXON MOBIL' vs 'ExxonMobil'): a sorted-words key and a
    no-spaces key."""
    return " ".join(sorted(n.split())), n.replace(" ", "")


_CLASS_RE = re.compile(r"\bCL(?:ASS)?\s*([A-C])\b")
_BAD_CLASS = ("PFD", "PREF", "WARRANT", "WTS", "NOTE", "RIGHT", "DEP SHS RP", "DEBT", "BOND")
TRUNCATED_LEN = 24                                   # 13F issuer names are often cut at 25-28 chars

# Share classes and ETFs that one issuer name cannot tell apart. Every CUSIP
# checked against the 13F rows cached from these funds' own filings.
CUSIP_OVERRIDES = {
    "02079K305": "GOOGL", "02079K107": "GOOG",       # Alphabet Class A / Class C
    "084670702": "BRK-B", "084670108": "BRK-A",      # Berkshire Class B / Class A
    "78462F103": "SPY", "46090E103": "QQQ", "464287200": "IVV", "922908363": "VOO",
    "78467X109": "DIA", "464287655": "IWM",
}


class TickerMap:
    """Issuer name (+ share class) -> ticker via SEC company_tickers.json.

    Only confident matches: the normalised 13F name must match exactly one
    SEC company (by sorted words or with spaces removed; truncated 13F names
    by unique prefix), and the ticker must be unambiguous: the company's
    primary (first-listed) ticker for common stock, or for a lettered class
    the single equity-like ticker ending in that letter. Anything else is
    null -- a missing ticker is better than a wrong one."""

    def __init__(self, company_tickers: dict | None):
        self.index: dict[str, dict[int, list[str]]] = defaultdict(dict)
        self.titles: list[tuple[str, int]] = []
        seen: set[int] = set()
        for v in (company_tickers or {}).values():
            t, cik = str(v.get("ticker") or "").upper(), int(v.get("cik_str") or 0)
            if not t or not cik:
                continue
            n = norm_name(v.get("title"))
            if not n:
                continue
            for k in _keys(n):
                self.index[k].setdefault(cik, [])
                if t not in self.index[k][cik]:
                    self.index[k][cik].append(t)
            if cik not in seen:
                seen.add(cik)
                self.titles.append((n, cik))
        self.by_cik = {cik: tickers for d in self.index.values() for cik, tickers in d.items()}
        self.loaded = bool(company_tickers)
        self._memo: dict[tuple, str | None] = {}

    def _company(self, name: str | None) -> list[str] | None:
        n = norm_name(name)
        if not n:
            return None
        ciks: set[int] = set()
        for k in _keys(n):
            ciks |= set(self.index.get(k, {}))
        if not ciks and len(name or "") >= TRUNCATED_LEN:
            words = n.split()
            for prefix in (n, " ".join(words[:-1]) if len(words) > 2 else None):
                if prefix:
                    ciks = {cik for t, cik in self.titles if t.startswith(prefix)}
                    if ciks:
                        break
        if len(ciks) != 1:
            return None                                  # unknown or ambiguous company
        return self.by_cik.get(next(iter(ciks)))

    def lookup(self, cusip: str, name: str | None, cls: str | None) -> str | None:
        if cusip in CUSIP_OVERRIDES:
            return CUSIP_OVERRIDES[cusip]
        key = (name, cls)
        if key not in self._memo:
            self._memo[key] = self._lookup(name, cls)
        return self._memo[key]

    def _lookup(self, name: str | None, cls: str | None) -> str | None:
        tickers = self._company(name)
        if not tickers:
            return None
        cls_u = (cls or "").upper()
        if any(w in cls_u for w in _BAD_CLASS):
            return None
        # equity-like: no -P/.A suffixes; 5-letter extras are usually OTC
        # foreign lines (BABAF) or notes (TMUSZ), except the primary listing.
        equity = [t for i, t in enumerate(tickers)
                  if "-" not in t and "." not in t and (i == 0 or len(t) <= 4)]
        m = _CLASS_RE.search(cls_u)
        if m:
            letter = m.group(1)
            dashed = [t for t in tickers if re.fullmatch(rf"[A-Z]+[-.]{letter}", t)]
            if len(dashed) == 1:
                return dashed[0]
            if len(equity) == 1:
                return equity[0]
            ending = [t for t in equity if t.endswith(letter)]
            return ending[0] if len(ending) == 1 else None
        first = tickers[0]
        return first if first in equity else None


# ------------------------------------------------------------------ loader
@dataclass
class FundState:
    fund: Fund
    status: str = "pending"            # pending | ok | error
    error: str | None = None
    checked_at: float | None = None    # monotonic, last attempt
    result: dict | None = None
    requests: int = 0


class Loader:
    """Fetches, parses and caches each fund's latest two quarters."""

    def __init__(self, ua: str, cache_dir: Path = CACHE_DIR, funds: tuple[Fund, ...] = FUNDS,
                 getter: Callable[[str, str], str] | None = None, limiter: SEC.RateLimiter | None = None,
                 wall: Callable[[], float] = time.time):
        self.ua, self.cache_dir, self.funds = ua, cache_dir, funds
        self.getter = getter or (lambda url, ua: SEC.http_get(url, ua, timeout=FILING_TIMEOUT_S))
        self.limiter = limiter or SEC.SEC_LIMITER
        self.wall = wall
        self.lock = threading.Lock()
        self.states = {f.key: FundState(f) for f in funds}
        self.tickers = TickerMap(None)
        self.tickers_error: str | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.running = False
        self.last_cycle: str | None = None
        self.requests = 0

    # -- network
    def _get(self, url: str) -> str:
        if self.stop_event.is_set():
            raise SEC.SecError("stopping")
        self.limiter.wait()
        self.requests += 1
        return self.getter(url, self.ua)

    def _read_json(self, p: Path) -> dict | None:
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (ValueError, OSError):
            p.unlink(missing_ok=True)                   # corrupt cache: refetched
            return None

    def _write_json(self, p: Path, obj) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj))
        tmp.replace(p)

    def _cached_fetch(self, name: str, url: str, max_age_s: float) -> tuple[dict, str | None]:
        """JSON document cached on disk with its fetch time -> (doc, note).
        When a refresh fails but an older copy exists, the older copy is used
        and `note` says so (surfaced in the response, not hidden)."""
        p = self.cache_dir / name
        c = self._read_json(p)
        if c and self.wall() - c.get("fetched_at", 0) < max_age_s:
            return c["doc"], None
        try:
            doc = json.loads(self._get(url))
        except (SEC.SecError, ValueError) as e:
            if c:
                age_h = (self.wall() - c.get("fetched_at", 0)) / 3600
                return c["doc"], f"refresh failed ({e}); using the copy from {age_h:.0f} h ago"[:200]
            raise
        self._write_json(p, {"fetched_at": self.wall(), "doc": doc})
        return doc, None

    def load_tickers(self) -> None:
        try:
            doc, note = self._cached_fetch("company_tickers.json", TICKERS_URL, TICKERS_REFRESH_S)
            self.tickers, self.tickers_error = TickerMap(doc), (f"ticker list {note}" if note else None)
        except (SEC.SecError, ValueError) as e:
            self.tickers_error = f"ticker list unavailable, tickers not mapped: {e}"[:200]

    def filing(self, cik: int, f: dict) -> dict:
        p = self.cache_dir / "filings" / f"{f['accession']}.json"
        c = self._read_json(p)
        if c is not None:
            return check_units(c)
        acc = f["accession"]
        txt = self._get(FILING_URL.format(cik=cik, acc_nodash=acc.replace("-", ""), acc=acc))
        parsed = parse_filing(txt, acc, f["form"], f["filed"])
        self._write_json(p, parsed)
        return check_units(parsed)

    def load_fund(self, fund: Fund) -> dict:
        filings, notes = [], []
        for cik in fund.ciks:
            subs, list_note = self._cached_fetch(f"submissions_{cik}.json",
                                                 SUBMISSIONS_URL.format(cik=cik), LIST_REFRESH_S)
            filings += [{**f, "cik": cik} for f in thirteenf_filings(subs)]
            if list_note:
                notes.append(f"CIK {cik} filing list {list_note}")
        periods = latest_periods(filings)
        if not periods:
            raise ValueError("no 13F-HR on file")
        resolved = []
        for period, fs in periods:
            parts = []
            for cik in fund.ciks:
                mine = [f for f in fs if f["cik"] == cik]
                if not any(f["form"] == "13F-HR" for f in mine):
                    continue
                parsed = [self.filing(cik, f) for f in mine]
                notes += [x["unit_note"] for x in parsed if x.get("unit_note")]
                parts.append(resolve_period(parsed))
            r = merge_parts(parts)
            r["period"] = period
            resolved.append(r)
        latest = resolved[0]
        out = {"period": latest["period"], "filed": latest["filed"], "amended": latest["amended"],
               "notes": latest["notes"] + notes, "prev_period": None, "prev_filed": None}
        if len(resolved) < 2:
            eq = _equity(latest["holdings"])
            out.update(moves=[], ratios={}, total_value=sum(v["value"] for v in eq.values()),
                       positions=len(eq), prev_total_value=None, prev_positions=None, non_equity_rows=0,
                       notes=out["notes"] + ["only one 13F on file: no quarter-over-quarter change"])
            return out
        prev = resolved[1]
        out.update(prev_period=prev["period"], prev_filed=prev["filed"])
        out.update(diff(latest["holdings"], prev["holdings"]))
        return out

    def load_one(self, st: FundState) -> None:
        with self.lock:
            st.checked_at = time.monotonic()
        try:
            res = self.load_fund(st.fund)
        except SEC.SecError as e:
            err = str(e)
        except (ValueError, ET.ParseError, KeyError) as e:
            err = f"unparseable 13F data: {type(e).__name__}: {e}"[:200]
        except Exception as e:                           # reported, never hidden
            err = f"13F load failed: {type(e).__name__}: {e}"[:200]
        else:
            with self.lock:
                st.status, st.error, st.result = "ok", None, res
            return
        with self.lock:
            st.error = err
            if st.result is None:                        # keep an older good result
                st.status = "error"

    def cycle(self) -> None:
        self.load_tickers()
        for st in self.states.values():
            if self.stop_event.is_set():
                return
            self.load_one(st)
        self.last_cycle = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def run(self) -> None:
        self.running = True
        try:
            while not self.stop_event.is_set():
                self.cycle()
                wait = RETRY_FAILED_S if any(s.status == "error" for s in self.states.values()) else LIST_REFRESH_S
                if self.stop_event.wait(wait):
                    return
        finally:
            self.running = False

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="sec-13f-loader", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def snapshot(self) -> list[FundState]:
        with self.lock:
            return [FundState(s.fund, s.status, s.error, s.checked_at, s.result) for s in self.states.values()]


# ----------------------------------------------------------------- response
def _money(x: float | None) -> str:
    if x is None:
        return "?"
    a = abs(x)
    if a >= 999.5e6:
        return f"${x / 1e9:.1f}B"
    if a >= 999.5e3:
        return f"${x / 1e6:.1f}M" if a < 99.95e6 else f"${x / 1e6:.0f}M"
    if a >= 999.5:
        return f"${x / 1e3:.0f}K"
    return f"${x:,.0f}"


def move_label(m: dict) -> str:
    k = m.get("split_adjusted")
    split = "" if not k else (f" (after {k:g}:1 split)" if k >= 1 else f" (after 1:{1 / k:g} reverse split)")
    if m["side"] == "NEW":
        return f"new · {_money(m['value'])} · {m['pct_portfolio']:.1f}% of portfolio"
    if m["side"] == "EXIT":
        was = f" · was {m['prev_pct_portfolio']:.1f}%" if m.get("prev_pct_portfolio") is not None else ""
        return f"sold out · was {_money(m['prev_value'])}{was}"
    pct = m["pct_portfolio"]
    return f"{m['change_pct']:+.0f}% shares{split} · {_money(m['value'])} · {pct:.1f}% of portfolio"


def lag_days(filed: str | None, period: str | None) -> int | None:
    try:
        return (date.fromisoformat(filed) - date.fromisoformat(period)).days if filed and period else None
    except ValueError:
        return None


def build(states: list[FundState], tickers: TickerMap, *, held: set[str], watch: set[str],
          days: int, today: date | None = None, running: bool = True, tickers_error: str | None = None,
          holdings_note: str | None = None, max_moves: int = MAX_MOVES_PER_FUND) -> dict:
    today = today or date.today()
    cutoff = today - timedelta(days=days)
    # splits are judged per report period, pooling every fund's evidence
    by_period: dict[str, list] = defaultdict(list)
    for st in states:
        if st.result and st.result.get("ratios"):
            by_period[st.result["period"]].append(st.result["ratios"])
    splits = {p: detect_splits(rs) for p, rs in by_period.items()}
    rows, funds, skipped, reasons = [], [], [], {}
    mapped = total_moves = 0
    buyers: dict[str, dict] = {}
    for st in states:
        f, res = st.fund, st.result
        info = {"key": f.key, "name": f.name, "manager": f.manager, "cik": f.cik, "ciks": list(f.ciks),
                "status": st.status,
                "error": st.error, "period": None, "filed": None, "amended": None, "prev_period": None,
                "positions": None, "total_value": None, "moves": 0, "in_window": None, "notes": [],
                "sec_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={f.cik}&type=13F-HR"}
        if st.status == "error" or (st.status == "pending" and not running):
            skipped.append(f.name)
            reasons[f.name] = st.error or "not loaded"
        if res:
            in_window = (date.fromisoformat(res["filed"]) >= cutoff)
            info.update(period=res["period"], filed=res["filed"], amended=res["amended"],
                        prev_period=res["prev_period"], positions=res["positions"],
                        total_value=res["total_value"], moves=len(res["moves"]), in_window=in_window,
                        notes=res["notes"])
            if in_window:
                moves = apply_splits(res["moves"], splits.get(res["period"], {}),
                                     res["total_value"], res.get("prev_total_value") or 0.0)
                info["moves"] = len(moves)
                for m in moves[:max_moves]:
                    sym = tickers.lookup(m["cusip"], m["issuer"], m["cls"])
                    total_moves += 1
                    mapped += sym is not None
                    s = (sym or "").upper()
                    yours = "HELD" if s and s in held else ("WATCH" if s and s in watch else None)
                    value = m["value"] if m["side"] != "EXIT" else m["prev_value"]
                    rows.append({
                        "filed": res["filed"], "traded": res["period"],
                        "lag_days": lag_days(res["filed"], res["period"]),
                        "who": f.name, "fund_key": f.key, "manager": f.manager,
                        "chamber": None, "party": None, "owner": None, "role": "Fund",
                        "symbol": sym, "issuer": SEC.pretty_issuer(m["issuer"]), "cusip": m["cusip"],
                        "security": m["cls"], "side": m["side"],
                        "amount_min": value, "amount_max": value, "amount_label": move_label(m),
                        "value": m["value"], "prev_value": m["prev_value"],
                        "shares": m["shares"], "prev_shares": m["prev_shares"],
                        "change_pct": m["change_pct"], "split_adjusted": m["split_adjusted"],
                        "pct_portfolio": m["pct_portfolio"], "prev_pct_portfolio": m["prev_pct_portfolio"],
                        "prev_period": res["prev_period"], "amended": res["amended"],
                        "yours": yours,
                    })
                    if sym and m["side"] in ("NEW", "ADD"):
                        b = buyers.setdefault(sym, {"symbol": sym, "count": 0, "value": 0.0, "funds": []})
                        b["count"] += 1
                        b["value"] += m["moved_value"]
                        b["funds"].append(f.name)
        funds.append(info)
    rows.sort(key=lambda r: (r["filed"], r["amount_min"] or 0), reverse=True)
    top = sorted(buyers.values(), key=lambda b: (-b["count"], -b["value"]))[:10]
    done = sum(1 for s in states if s.status != "pending")
    loading = running and done < len(states)
    out = {
        "type": "funds", "configured": True, "rule": RULE,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": SOURCE,
        "partial": bool(skipped) or loading, "skipped": skipped, "skipped_reasons": reasons,
        "window_days": days, "rows": rows, "most_bought": top,
        "loading": loading, "progress": {"done": done, "total": len(states)},
        "funds": funds,
        "tickers": {"mapped": mapped, "total": total_moves, "error": tickers_error},
        "max_moves_per_fund": max_moves,
    }
    if holdings_note:
        out["holdings_note"] = holdings_note
    return out


# ------------------------------------------------------------------ router
class _State:
    loader: Loader | None = None


S = _State()


def start_loader() -> None:
    ua = user_agent()
    if not ua or S.loader is not None:
        return
    S.loader = Loader(ua)
    S.loader.start()


def stop_loader() -> None:
    if S.loader is not None:
        S.loader.stop()
    S.loader = None


def response(held: set[str], watch: set[str], days: int, holdings_note: str | None = None) -> dict | None:
    """The /api/disclosures?type=funds body, or None when the loader is not running."""
    ld = S.loader
    if ld is None:
        return None
    return build(ld.snapshot(), ld.tickers, held=held, watch=watch, days=days,
                 running=ld.thread is not None and ld.thread.is_alive(),
                 tickers_error=ld.tickers_error, holdings_note=holdings_note)


@asynccontextmanager
async def _lifespan(_app):
    start_loader()
    try:
        yield
    finally:
        stop_loader()


# No routes of its own: the data is served by /api/disclosures?type=funds.
# The router exists so the app's lifespan starts and stops the loader.
router = APIRouter(lifespan=_lifespan)
