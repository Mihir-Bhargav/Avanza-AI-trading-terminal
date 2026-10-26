"""
Live insider trades (`/api/insiders`) from SEC EDGAR Form 4 filings.

Market-wide, not limited to the watchlist: every CEO, CFO, director and 10%
owner who files a Form 4 shows up here within minutes of the SEC accepting it.

Source details, verified 2026-09-24 against live EDGAR responses:

  Feed   https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4
         &owner=only&count=100&start=N&output=atom
         `type` is a PREFIX match: with owner=include, type=4 also returns
         424B2, 485BPOS, ... (about 10% of a page was Form 4). owner=only
         restricts the feed to ownership filings, so every entry is a Form 4.
         Each filing appears twice (one "(Reporting)" and one "(Issuer)"
         entry) with the same accession; <updated> is the acceptance time
         with a UTC offset; `start=` pages back (100 entries per page).
  Filing https://www.sec.gov/Archives/edgar/data/{cik}/{acc-no-dashes}/{acc}.txt
         The complete submission. It embeds the Form 4 XML
         (<ownershipDocument>) in one request, instead of index + XML (two).

SEC fair-access rules (https://www.sec.gov/os/accessing-edgar-data): a
User-Agent naming the requester with a contact, and at most 10 requests/s.
The User-Agent comes from env SEC_USER_AGENT and is never hardcoded; without
it the endpoint answers 503 and the poller does not start. Requests are spaced
to <= 4/s; HTTP 429/403 backs the whole poller off exponentially.

Only open-market purchases (code P) and sales (code S) from the
non-derivative table are kept: grants, option exercises, tax withholding and
gifts are not "an insider decided to buy or sell". Amendments (4/A) are
skipped so a restated trade is not counted twice.

Runtime data lives in gitignored data/insiders/: trades.jsonl (one parsed
trade per line, deduped by accession + line, pruned to RETENTION_DAYS) and
seen.json (every accession already processed, including ones with no P/S
trades, so a restart does not refetch them).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "insiders"

FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4"
            "&owner=only&count=100&start={start}&output=atom")
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}.txt"
FEED_PAGE_SIZE = 100

POLL_SECONDS = 120
BACKFILL_FILINGS = 400          # unique filings processed on startup
BACKFILL_MAX_PAGES = 10         # ~47 unique filings per 100-entry page
POLL_MAX_PAGES = 4
MAX_REQUESTS_PER_SECOND = 4.0   # SEC limit is 10/s
BACKOFF_START_S = 60
BACKOFF_MAX_S = 900
RETENTION_DAYS = 30
HELD_CACHE_S = 300

# "Notable" rules. Buys are rarer and more informative than sells (insiders
# sell for taxes, diversification, houses); a sale has to be large to matter.
NOTABLE_BUY_USD = 250_000
# A CEO/CFO/Chair buy is a stronger signal than anyone else's, but a token
# $2k purchase is noise; executives still need a meaningful amount.
NOTABLE_EXEC_BUY_USD = 50_000
NOTABLE_SELL_USD = 5_000_000

NOT_CONFIGURED_ERROR = ("Set SEC_USER_AGENT in .env, e.g. 'Range Terminal you@example.com' "
                        "(required by the SEC)")

ET_TZ = ZoneInfo("America/New_York")
ATOM = "{http://www.w3.org/2005/Atom}"


class SecError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def user_agent() -> str | None:
    ua = (os.getenv("SEC_USER_AGENT") or "").strip()
    return ua or None


# ------------------------------------------------------------ rate limiting
class RateLimiter:
    """Spaces calls at least 1/rate seconds apart (thread-safe).

    `sleep` is injectable: tests pass a fake, the poller passes its stop
    event's wait so shutdown is never stuck behind the limiter."""

    def __init__(self, rate: float = MAX_REQUESTS_PER_SECOND,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], object] = time.sleep):
        self.interval = 1.0 / rate
        self.clock, self.sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            delay = self._next - now
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
            self._next = max(now, self._next) + self.interval


# One limiter for every SEC client in the process (this Form 4 poller and the
# 13F loader in terminal/funds13f.py), so together they stay <= 4 requests/s.
SEC_LIMITER = RateLimiter()


def http_get(url: str, ua: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            # The Atom feed declares ISO-8859-1; filings are ASCII/UTF-8.
            return raw.decode("latin-1" if b"ISO-8859-1" in raw[:100] else "utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise SecError(f"SEC HTTP {e.code}", e.code) from None
    except Exception as e:
        raise SecError(f"SEC request failed: {type(e).__name__}: {e}"[:200]) from None


# ------------------------------------------------------------------ parsing
@dataclass
class FeedEntry:
    accession: str
    cik: str
    filed_at: str | None        # ISO with offset
    form: str
    index_url: str


_ACC_RE = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
_CIK_RE = re.compile(r"/edgar/data/(\d+)/")


def parse_atom(xml_text: str) -> list[FeedEntry]:
    """Unique filings in feed order (newest first). Prefers the issuer entry's
    link (the index page is the same either way)."""
    root = ET.fromstring(xml_text)
    out: dict[str, FeedEntry] = {}
    for e in root.findall(f"{ATOM}entry"):
        ident = (e.findtext(f"{ATOM}id") or "")
        m = _ACC_RE.search(ident)
        link = e.find(f"{ATOM}link")
        href = link.get("href") if link is not None else ""
        cm = _CIK_RE.search(href or "")
        if not m or not cm:
            continue
        cat = e.find(f"{ATOM}category")
        form = cat.get("term") if cat is not None else ""
        acc = m.group(1)
        title = e.findtext(f"{ATOM}title") or ""
        entry = FeedEntry(acc, cm.group(1), e.findtext(f"{ATOM}updated"), form, href)
        if acc not in out or "(Issuer)" in title:
            out[acc] = entry
    return list(out.values())


def feed_updated(xml_text: str) -> str | None:
    """The feed's own generation time. EDGAR serves this feed from several
    backends; on 2026-09-24 one answered ~35 min stale, so it is surfaced."""
    m = re.search(r"<updated>([^<]+)</updated>", xml_text)
    return m.group(1) if m else None


def _txt(el: ET.Element | None, path: str) -> str | None:
    """Text of `path/value` (the Form 4 idiom), else of `path` itself."""
    if el is None:
        return None
    node = el.find(f"{path}/value")
    if node is None:
        node = el.find(path)
    if node is None or node.text is None:
        return None
    t = node.text.strip()
    return t or None


def _flag(el: ET.Element | None, path: str) -> bool:
    return (_txt(el, path) or "").lower() in ("1", "true", "y", "yes")


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


_KEEP_UPPER = {"II", "III", "IV", "LLC", "LP", "L.P.", "LLP", "INC", "INC.", "CO", "CO.", "N.V.",
               "PLC", "SA", "AG", "USA", "US", "LTD", "LTD.", "FBO", "UTA", "JR", "SR"}


_KEEP_UPPER_ISSUER = {"II", "III", "IV", "LLC", "LP", "L.P.", "LLP", "N.V.", "PLC", "SA", "AG", "USA", "US",
                      "ETF", "REIT", "BDC", "AI"}


def pretty_issuer(name: str | None) -> str | None:
    return pretty_name(name, _KEEP_UPPER_ISSUER)


def pretty_name(name: str | None, keep: set[str] = _KEEP_UPPER) -> str | None:
    """EDGAR files most people in ALL CAPS as 'LAST FIRST M'. Title-case it
    (keeping suffixes and legal-entity tokens) but do not reorder, which would
    guess wrong on compound surnames."""
    if not name:
        return name
    if name != name.upper():
        return name
    return " ".join(w if w.upper().strip(",") in keep else w.capitalize()
                    for w in name.split())


_CEO_RE = re.compile(r"\b(ceo|cfo|chief executive|chief financial|chair(man|woman|person)?|"
                     r"(?<!vice )(?<!vice-)president|founder)\b", re.I)


def is_ceo_like(title: str | None) -> bool:
    return bool(title and _CEO_RE.search(title))


def _role(rel: ET.Element | None) -> tuple[list[str], bool]:
    if rel is None:
        return [], False
    parts, titles = [], []
    title = _txt(rel, "officerTitle")
    other = _txt(rel, "otherText")
    if _flag(rel, "isOfficer") and title:
        parts.append(title)
        titles.append(title)
    elif _flag(rel, "isOfficer"):
        parts.append("Officer")
    if _flag(rel, "isDirector"):
        parts.append("Director")
    if _flag(rel, "isTenPercentOwner"):
        parts.append("10% owner")
    if _flag(rel, "isOther") and other:
        parts.append(other)
        titles.append(other)
    return parts, any(is_ceo_like(t) for t in titles)


def extract_ownership_xml(submission: str) -> str | None:
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", submission, re.S)
    return m.group(0) if m else None


def acceptance_time(submission: str) -> str | None:
    """<ACCEPTANCE-DATETIME>YYYYMMDDHHMMSS (US Eastern) -> ISO with offset."""
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", submission)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=ET_TZ)
    return dt.isoformat()


def parse_form4(submission: str, accession: str, filed_at: str | None, sec_url: str) -> list[dict]:
    """All open-market P/S trades in one filing. Raises ValueError when the
    filing carries no parseable Form 4 XML (reported, never swallowed)."""
    xml = extract_ownership_xml(submission)
    if xml is None:
        raise ValueError("no <ownershipDocument> in submission")
    doc = ET.fromstring(xml)
    doc_type = _txt(doc, "documentType") or ""
    if doc_type != "4":
        return []                                        # 4/A etc. -- see module doc
    filed_at = filed_at or acceptance_time(submission)
    issuer = doc.find("issuer")
    ticker = (_txt(issuer, "issuerTradingSymbol") or "").upper().strip()
    if ticker in ("", "NONE", "N/A", "NA", "-"):
        ticker = None
    issuer_name = pretty_issuer(_txt(issuer, "issuerName"))

    owners = doc.findall("reportingOwner")
    names, roles, ceo = [], [], False
    for o in owners:                             # joint filings: several owners
        n = pretty_name(_txt(o, "reportingOwnerId/rptOwnerName"))
        parts, c = _role(o.find("reportingOwnerRelationship"))
        if n:
            names.append(n)
        roles.extend(p for p in parts if p not in roles)
        ceo = ceo or c
    who = names[0] if names else None
    if len(names) > 1:
        who = f"{who} +{len(names) - 1}"
    plan_doc = _flag(doc, "aff10b5One")

    rows = []
    for line, t in enumerate(doc.findall("nonDerivativeTable/nonDerivativeTransaction")):
        code = (_txt(t, "transactionCoding/transactionCode") or "").upper()
        if code not in ("P", "S"):
            continue
        shares = _num(_txt(t, "transactionAmounts/transactionShares"))
        price = _num(_txt(t, "transactionAmounts/transactionPricePerShare"))
        value = shares * price if shares is not None and price else None
        side = "BUY" if code == "P" else "SELL"
        trade_date = (_txt(t, "transactionDate") or "")[:10] or None
        rows.append({
            "id": f"{accession}:{line}",
            "accession": accession,
            "filed_at": filed_at,
            "trade_date": trade_date,
            "ticker": ticker,
            "issuer": issuer_name,
            "who": who,
            "role": " · ".join(roles) or None,
            "is_ceo_like": ceo,
            "side": side,
            "shares": shares,
            "price": price,
            "value": value,
            "security": _txt(t, "securityTitle"),
            "plan_10b5_1": plan_doc,
            "sec_url": sec_url,
        })
        rows[-1]["notable"] = is_notable(rows[-1])
    return rows


def is_notable(r: dict) -> bool:
    v = r.get("value") or 0
    if r["side"] == "BUY":
        return v >= NOTABLE_BUY_USD or (bool(r.get("is_ceo_like")) and v >= NOTABLE_EXEC_BUY_USD)
    return v >= NOTABLE_SELL_USD


# -------------------------------------------------------------------- store
def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Store:
    """Parsed trades + processed accessions, on disk and in memory."""

    def __init__(self, data_dir: Path = DATA_DIR, retention_days: int = RETENTION_DAYS):
        self.dir = data_dir
        self.trades_path = data_dir / "trades.jsonl"
        self.seen_path = data_dir / "seen.json"
        self.retention = timedelta(days=retention_days)
        self.lock = threading.Lock()
        self.trades: dict[str, dict] = {}
        self.seen: dict[str, str] = {}          # accession -> filed_at (or "")
        self.load_error: str | None = None

    def load(self) -> None:
        with self.lock:
            try:
                if self.trades_path.exists():
                    for ln in self.trades_path.read_text().splitlines():
                        if ln.strip():
                            r = json.loads(ln)
                            self.trades[r["id"]] = r
                if self.seen_path.exists():
                    self.seen = json.loads(self.seen_path.read_text())
            except (ValueError, KeyError, OSError) as e:
                self.load_error = f"insider store unreadable, starting empty: {type(e).__name__}: {e}"[:200]
                self.trades, self.seen = {}, {}
            self._prune_locked()
            self._rewrite_locked()

    def _prune_locked(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.retention
        self.trades = {k: r for k, r in self.trades.items()
                       if (_parse_ts(r.get("filed_at")) or cutoff) >= cutoff}
        self.seen = {k: v for k, v in self.seen.items()
                     if not v or (_parse_ts(v) or cutoff) >= cutoff}

    def _rewrite_locked(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.trades_path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in self.trades.values()))
        tmp.replace(self.trades_path)
        self._write_seen_locked()

    def _write_seen_locked(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.seen_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.seen))
        tmp.replace(self.seen_path)

    def is_seen(self, acc: str) -> bool:
        with self.lock:
            return acc in self.seen

    def add(self, accession: str, filed_at: str | None, rows: list[dict]) -> int:
        """Record a processed filing. Returns the number of NEW trades."""
        with self.lock:
            new = [r for r in rows if r["id"] not in self.trades]
            for r in new:
                self.trades[r["id"]] = r
            if new:
                self.dir.mkdir(parents=True, exist_ok=True)
                with self.trades_path.open("a") as f:
                    for r in new:
                        f.write(json.dumps(r) + "\n")
            self.seen[accession] = filed_at or ""
            self._write_seen_locked()
            return len(new)

    def prune(self) -> None:
        with self.lock:
            self._prune_locked()
            self._rewrite_locked()

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.trades.values())

    def seen_count(self) -> int:
        with self.lock:
            return len(self.seen)


# ------------------------------------------------------------------- poller
class Poller:
    def __init__(self, ua: str, store: Store, getter: Callable[[str, str], str] = http_get,
                 limiter: RateLimiter | None = None, poll_seconds: float = POLL_SECONDS):
        self.ua, self.store, self.getter = ua, store, getter
        self.stop_event = threading.Event()
        self.limiter = limiter or RateLimiter(sleep=self.stop_event.wait)
        self.poll_seconds = poll_seconds
        self.thread: threading.Thread | None = None
        self.last_poll: str | None = None
        self.poll_error: str | None = None
        self.backfilling = False
        self.backfill_done = False
        self.backoff = 0.0
        self.parse_failures = 0
        self.last_parse_failure: str | None = None
        self.parsed_this_session = 0
        self.feed_updated: str | None = None

    # -- network with fair-access handling
    def _get(self, url: str) -> str:
        self.limiter.wait()
        try:
            text = self.getter(url, self.ua)
        except SecError as e:
            if e.status in (403, 429):
                self.backoff = min(BACKOFF_MAX_S, (self.backoff * 2) or BACKOFF_START_S)
            raise
        self.backoff = 0.0
        return text

    def _get_retry(self, url: str) -> str:
        """One retry for transient failures (EDGAR pages occasionally time
        out); never retries a 403/429 -- that is the back-off's job."""
        try:
            return self._get(url)
        except SecError as e:
            if e.status in (403, 429) or self.stop_event.is_set():
                raise
            return self._get(url)

    def process(self, e: FeedEntry) -> int:
        url = FILING_URL.format(cik=e.cik, acc_nodash=e.accession.replace("-", ""), acc=e.accession)
        text = self._get_retry(url)              # SecError propagates: retried next poll
        try:
            rows = parse_form4(text, e.accession, e.filed_at, e.index_url)
        except (ValueError, ET.ParseError) as err:
            self.parse_failures += 1
            self.last_parse_failure = f"{e.accession}: {type(err).__name__}: {err}"[:200]
            rows = []                            # recorded as seen: refetching won't fix it
        self.parsed_this_session += 1
        return self.store.add(e.accession, e.filed_at, rows)

    def sync(self, max_filings: int, max_pages: int, stop_at_seen: bool = True) -> bool:
        """Walk the feed newest -> oldest, processing each page's unseen Form 4s
        as soon as the page arrives (so rows appear within seconds). Stops at
        the first page whose OLDEST filing is already processed: that is where
        the previous sync left off. (Checking any-seen would stop early, since
        filings accepted mid-sync shift entries from page N onto page N+1.)
        The startup backfill passes stop_at_seen=False and walks every page,
        so a backfill interrupted by an error resumes where it failed.
        Returns True when the walk completed without an error."""
        done = 0
        try:
            for page in range(max_pages):
                text = self._get_retry(FEED_URL.format(start=page * FEED_PAGE_SIZE))
                if page == 0:
                    self.feed_updated = feed_updated(text)
                entries = parse_atom(text)
                if not entries:
                    break
                for e in entries:
                    if self.stop_event.is_set() or done >= max_filings:
                        break
                    if e.form == "4" and not self.store.is_seen(e.accession):   # 4/A: not fetched
                        self.process(e)
                        done += 1
                if ((stop_at_seen and self.store.is_seen(entries[-1].accession)) or done >= max_filings
                        or self.stop_event.is_set()):
                    break
            self.poll_error = None
            return True
        except SecError as err:
            self.poll_error = str(err) + (f"; backing off {int(self.backoff)} s" if self.backoff else "")
        except ET.ParseError as err:
            self.poll_error = f"SEC feed unparseable: {err}"[:200]
        except Exception as err:                 # reported, never hidden
            self.poll_error = f"poll failed: {type(err).__name__}: {err}"[:200]
        finally:
            self.last_poll = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return False

    def run(self) -> None:
        # Backfill until one full walk succeeds; a failed walk keeps what it
        # parsed and resumes 30 s later (seen filings are not refetched).
        self.backfilling = True
        while not self.sync(BACKFILL_FILINGS, BACKFILL_MAX_PAGES, stop_at_seen=False):
            if self.stop_event.wait(30 + self.backoff):
                return
        self.backfilling, self.backfill_done = False, True
        while not self.stop_event.wait(self.poll_seconds + self.backoff):
            self.sync(BACKFILL_FILINGS, POLL_MAX_PAGES)
            self.store.prune()

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="sec-form4-poller", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)


# ---------------------------------------------------------------- building
def _held_and_watch() -> tuple[set[str], set[str], str | None]:
    """Same rule as /api/disclosures: HELD only when an Avanza session ALREADY
    exists (never triggers a login), WATCH = the setups universe."""
    from screeners import zone_panel as ZP
    from terminal import api_v2
    from terminal.disclosures import is_us_ticker
    now = time.monotonic()
    if _HELD["at"] is None or now - _HELD["at"] > HELD_CACHE_S:
        held, note = api_v2._held_tickers()
        _HELD.update(at=now, held=held, note=note)
    held = {t.upper() for t in _HELD["held"] if is_us_ticker(t)}
    watch = {spec[2].upper() for spec in ZP.UNIVERSE if is_us_ticker(spec[2])}
    return held, watch, _HELD["note"]


_HELD: dict = {"at": None, "held": [], "note": None}


def lag_days(filed_at: str | None, trade_date: str | None) -> int | None:
    f = _parse_ts(filed_at)
    try:
        t = date.fromisoformat(trade_date) if trade_date else None
    except ValueError:
        t = None
    return (f.astimezone(ET_TZ).date() - t).days if f and t else None


def build(trades: list[dict], *, days: int = 7, side: str = "all", min_value: float | None = None,
          notable_only: bool = False, ceo_only: bool = False, symbols: set[str] | None = None,
          mine_only: bool = False, held: set[str] = frozenset(), watch: set[str] = frozenset(),
          limit: int = 300, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    week = now - timedelta(days=7)
    rows, buys = [], {}
    for r in trades:
        ts = _parse_ts(r.get("filed_at"))
        if ts is None or ts < cutoff:
            continue
        # Recomputed on read so stored trades follow the current thresholds.
        r["notable"] = is_notable(r)
        t = (r.get("ticker") or "").upper()
        yours = "HELD" if t in held else ("WATCH" if t in watch else None)
        if r["side"] == "BUY" and ts >= week and t and r.get("value"):
            b = buys.setdefault(t, {"ticker": t, "issuer": pretty_issuer(r.get("issuer")), "value": 0.0, "who": set()})
            b["value"] += r["value"]
            b["who"].add(r.get("who"))
        if side == "buy" and r["side"] != "BUY" or side == "sell" and r["side"] != "SELL":
            continue
        if min_value is not None and (r.get("value") or 0) < min_value:
            continue
        if notable_only and not r.get("notable"):
            continue
        if ceo_only and not r.get("is_ceo_like"):
            continue
        if symbols and t not in symbols:
            continue
        if mine_only and yours is None:
            continue
        out = {k: r.get(k) for k in ("id", "filed_at", "trade_date", "ticker", "issuer", "who", "role",
                                     "is_ceo_like", "side", "shares", "price", "value", "security",
                                     "plan_10b5_1", "notable", "sec_url")}
        out["issuer"] = pretty_issuer(out["issuer"])   # rows stored before this rule existed
        out["lag_days"] = lag_days(r.get("filed_at"), r.get("trade_date"))
        out["yours"] = yours
        rows.append((ts, out))
    rows.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
    top = sorted(buys.values(), key=lambda b: -b["value"])[:8]
    return {
        "rows": [r for _, r in rows[:limit]],
        "total_matching": len(rows),
        "truncated": len(rows) > limit,
        "top_buys": [{"ticker": b["ticker"], "issuer": b["issuer"], "value": b["value"],
                      "buyers": len(b["who"])} for b in top],
    }


# ------------------------------------------------------------------ router
class _State:
    poller: Poller | None = None
    store: Store | None = None


S = _State()


def start_poller() -> None:
    ua = user_agent()
    if not ua or S.poller is not None:
        return
    S.store = Store()
    S.store.load()
    S.poller = Poller(ua, S.store, limiter=SEC_LIMITER)
    S.poller.start()


def stop_poller() -> None:
    if S.poller is not None:
        S.poller.stop()
    S.poller = None


@asynccontextmanager
async def _lifespan(_app):
    start_poller()
    try:
        yield
    finally:
        stop_poller()


router = APIRouter(lifespan=_lifespan)


@router.get("/api/insiders")
def insiders(days: int = Query(7, ge=1, le=RETENTION_DAYS),
             side: str = "all",
             min_value: float | None = Query(None, ge=0),
             notable_only: bool = False,
             ceo_only: bool = False,
             mine: bool = False,
             symbols: str | None = None,
             limit: int = Query(300, ge=1, le=2000)):
    if not user_agent():
        return JSONResponse({"configured": False, "error": NOT_CONFIGURED_ERROR}, status_code=503)
    if side not in ("buy", "sell", "all"):
        return JSONResponse({"error": "side must be buy, sell or all"}, status_code=400)
    p, store = S.poller, S.store
    if p is None or store is None:
        return JSONResponse({"configured": True, "error": "SEC poller is not running (restart the backend)"},
                            status_code=503)
    held, watch, note = _held_and_watch()
    syms = {s.strip().upper() for s in symbols.split(",") if s.strip()} if symbols else None
    body = build(store.snapshot(), days=days, side=side, min_value=min_value,
                 notable_only=notable_only, ceo_only=ceo_only, symbols=syms, mine_only=mine,
                 held=held, watch=watch, limit=limit)
    return {
        "configured": True,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SEC EDGAR Form 4 (current filings feed)",
        "last_poll": p.last_poll,
        "feed_updated": p.feed_updated,
        "poll_error": p.poll_error,
        "backfilling": p.backfilling,
        "filings_seen": store.seen_count(),
        "parsed_this_session": p.parsed_this_session,
        "parse_failures": p.parse_failures,
        "last_parse_failure": p.last_parse_failure,
        "store_error": store.load_error,
        "poll_seconds": p.poll_seconds,
        "window_days": days,
        "thresholds": {"notable_buy_usd": NOTABLE_BUY_USD, "notable_exec_buy_usd": NOTABLE_EXEC_BUY_USD, "notable_sell_usd": NOTABLE_SELL_USD},
        "holdings_note": note,
        **body,
    }
