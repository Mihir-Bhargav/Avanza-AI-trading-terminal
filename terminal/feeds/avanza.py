"""
Avanza feed — unauthenticated public endpoints.

WHAT THIS IS FOR. Not a price backbone: measured latency is 15.7 min on
2026-08-05, worse than yfinance's ~1 min on Swedish names. Its value is the two
things nothing else gives:

  1. SPREAD, per instrument. This is the entire cost of trading on Avanza,
     since Avanza Markets certificates and minis are commission-free above
     1,000 SEK. And it varies enormously between instruments on the SAME
     underlying -- measured live:

         MINI L SP500 5 SG    277,43   spread 0,01   ->     0.004%
         BULL GULD X20 AVA 4   10,23   spread 0,10   ->     0.98%
         BULL GULD X20 SG18    0,507   spread 0,20   ->    39%
         BULL GULD X18 VT14     0,06   spread 3,45   -> 5,750%

     Choosing badly costs more than any edge could earn. `find_instruments()`
     ranks by spread percentage so the cheapest tradeable line is obvious.

  2. CERTIFICATES, WARRANTS AND MINI FUTURES -- the instruments actually
     traded here, which yfinance does not carry at all.

Endpoints (verified working 2026-08-05):
    POST /_api/search/filtered-search      {query, pageSize} -> hits w/ orderBookId, price, spread
    GET  /_api/market-guide/{type}/{id}    instrument metadata
    GET  /_api/price-chart/stock/{id}      1-min OHLCV + volume

Unofficial. These can change without notice -- an older library's endpoints were
already dead when tested. Every call is defensive and returns None on failure.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from .base import Bars, Quote

BASE = "https://www.avanza.se"
_HDRS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
         "Content-Type": "application/json"}


def _ctx():
    # Pin certifi: the system store fails behind proxies that inject a root,
    # which is common on university and corporate networks.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _num(v) -> float:
    """Swedish formatting: comma decimal, thin-space thousands, and a real
    Unicode minus sign (U+2212) rather than a hyphen."""
    if v is None:
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = (str(v).replace("−", "-").replace(" ", "").replace(" ", "")
         .replace(".", "").replace(",", "."))
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _jsonable(d: dict) -> dict:
    """NaN -> None, because NaN is not valid JSON.

    _num() returns NaN for every absent field, and absent fields are normal
    here: a plain stock has no keyIndicators, and outside market hours Avanza
    returns no spread at all. Serialising those raised
    "Out of range float values are not JSON compliant" and 500'd the whole
    response. None is both valid and honest -- the field is missing, not zero.
    """
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in d.items()}


class AvanzaFeed:
    """Public endpoints, upgraded to authenticated ones when a session exists.

    Attaching an AvanzaAuth is what makes quotes real-time. Without it every
    endpoint still works -- that is deliberate, the terminal must not depend on
    credentials -- but Avanza returns isRealTime=False and a delayed price.
    Measured on ERIC B: 969.0 with isRealTime=True authenticated, against a
    15.7-minute-stale quote without.
    """

    name = "avanza"

    def __init__(self, auth=None):
        self.auth = auth

    def _get(self, path: str):
        # Prefer the authenticated session when one is live. It is the same URL;
        # Avanza decides what to return based on who is asking.
        if self.auth is not None:
            try:
                if self.auth.token or self.auth.configured:
                    ok, _ = self.auth.ensure()
                    if ok:
                        d = self.auth.get(path)
                        if d is not None:
                            return d
            except Exception:
                pass          # fall through to the public path
        try:
            req = urllib.request.Request(BASE + path, headers=_HDRS)
            with urllib.request.urlopen(req, timeout=12, context=_ctx()) as r:
                return json.load(r)
        except Exception:
            return None

    @property
    def authenticated(self) -> bool:
        return bool(self.auth is not None and self.auth.token)

    def _post(self, path: str, body: dict):
        try:
            req = urllib.request.Request(BASE + path, headers=_HDRS,
                                         data=json.dumps(body).encode(), method="POST")
            with urllib.request.urlopen(req, timeout=12, context=_ctx()) as r:
                return json.load(r)
        except Exception:
            return None

    # ---------------------------------------------------------------- search
    def search(self, query: str, limit: int = 20) -> list[dict]:
        d = self._post("/_api/search/filtered-search",
                       {"query": query, "pageSize": limit})
        if not d or "hits" not in d:
            return []
        out = []
        for h in d["hits"][:limit]:
            px = h.get("price") or {}
            last, spread = _num(px.get("last")), _num(px.get("spread"))
            out.append({
                "name": h.get("title", ""),
                "type": h.get("type", ""),
                "orderbook_id": str(h.get("orderBookId", "")),
                "market": h.get("marketPlaceName", ""),
                "currency": px.get("currency", ""),
                "last": last,
                "change_pct": _num(px.get("todayChangePercent")),
                "spread": spread,
                # The number that decides whether an instrument is tradeable.
                "spread_pct": (spread / last * 100) if (last == last and last > 0
                                                        and spread == spread) else float("nan"),
                "tradeable": bool(h.get("tradeable")),
            })
        return [_jsonable(o) for o in out]

    def find_instruments(self, query: str, limit: int = 60,
                         max_spread_pct: float | None = None) -> list[dict]:
        """Search, then rank by spread — cheapest genuinely tradeable first.

        No spread cap by default. An earlier version hid everything above 2%,
        which quietly deleted rows rather than ranking them; the sort already
        puts the tradeable ones on top, and seeing that the same underlying also
        quotes 39% wide is information, not noise. Pass max_spread_pct to filter.
        """
        hits = [h for h in self.search(query, limit=limit) if h["tradeable"]]
        for h in hits:
            sp = h.get("spread_pct")
            h["spread_known"] = sp is not None and sp == sp and sp > 0

        # Outside Swedish market hours Avanza returns spread: null on every
        # line. Filtering on spread therefore emptied the panel completely each
        # evening -- which is when you would actually be planning tomorrow. So
        # unpriced rows are kept and sorted last, flagged rather than dropped:
        # you can still find the instrument, you just cannot rank it on cost
        # until the market opens.
        if max_spread_pct is not None:
            hits = [h for h in hits
                    if not h["spread_known"] or h["spread_pct"] <= max_spread_pct]
        hits.sort(key=lambda h: (not h["spread_known"],
                                 h["spread_pct"] if h["spread_known"] else 0))
        return hits

    # ------------------------------------------------------------ instrument
    def instrument(self, orderbook_id: str) -> dict | None:
        """Full detail for one certificate/mini/warrant.

        The market-guide path is typed and the type is not known in advance, so
        this tries each. `keyIndicators` is why this endpoint matters: it carries
        the KNOCKOUT BARRIER and financing level, which decide whether a mini
        future dies, and which appear nowhere in the search results.
        """
        d = None
        for t in ("warrant", "certificate", "stock", "index", "fund", "etf"):
            d = self._get(f"/_api/market-guide/{t}/{orderbook_id}")
            if d and d.get("keyIndicators"):
                break
            if d and t == "stock":
                break
        if not d:
            return None
        k = d.get("keyIndicators") or {}
        q = d.get("quote") or {}
        last, spread = _num(q.get("last")), _num(q.get("spread"))
        sub = d.get("subCategory") or ""
        out = {
            "orderbook_id": str(orderbook_id),
            "name": d.get("name", ""),
            "type": d.get("type", ""),
            "sub_type": k.get("subType", ""),
            "direction": k.get("direction", ""),
            "leverage": _num(k.get("leverage")),
            "barrier": _num(k.get("barrierLevel")),
            "financing": _num(k.get("financingLevel")),
            "parity": _num(k.get("parity")),
            "currency": (d.get("listing") or {}).get("currency", ""),
            "last": last,
            "bid": _num(q.get("buy")),
            "ask": _num(q.get("sell")),
            "spread": spread,
            "spread_pct": (spread / last * 100) if (last == last and last > 0
                                                    and spread == spread) else float("nan"),
            "change_pct": _num(q.get("changePercent")),
            # Avanza states this itself; do not present a stale cert as live.
            "is_realtime": bool(q.get("isRealTime")),
            # Avanza's own clocks, in epoch ms. Needed because stamping a quote
            # with now() makes it permanently un-ageable -- see router.py.
            "updated_ms": q.get("updated"),
            "last_trade_ms": q.get("timeOfLast"),
            "tradeable": d.get("tradable") == "BUYABLE_AND_SELLABLE",
            "category": d.get("category", ""),
            "sub_category": sub,
            "underlying": underlying_symbol(sub, d.get("name", "")),
            "history": d.get("historicalClosingPrices") or {},
        }
        return _jsonable(out)

    # ----------------------------------------------------------------- quote
    def quote(self, symbol: str) -> Quote | None:
        """`symbol` is an Avanza orderbook id (numeric string)."""
        d = self._get(f"/_api/market-guide/stock/{symbol}")
        if not d:
            return None
        q = d.get("quote") or {}
        last = _num(q.get("last"))
        if last != last:
            return None
        ts = q.get("updated") or q.get("timestamp")
        when = datetime.now(timezone.utc)
        if isinstance(ts, str):
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        return Quote(symbol=symbol, price=last, ts=when,
                     change_pct=_num(q.get("changePercent")),
                     volume=_num(q.get("totalVolumeTraded")), source=self.name)

    # ------------------------------------------------------------------ bars
    def bars(self, symbol: str, interval: str = "1d",
             lookback: str = "today", **_) -> Bars | None:
        period = {"today": "today", "1d": "today", "1w": "one_week",
                  "1mo": "one_month", "3mo": "three_months",
                  "1y": "one_year"}.get(lookback, "today")
        d = self._get(f"/_api/price-chart/stock/{symbol}?timePeriod={period}")
        if not d or "ohlc" not in d or not d["ohlc"]:
            return None
        rows = []
        for b in d["ohlc"]:
            rows.append({
                "Date": datetime.fromtimestamp(b["timestamp"] / 1000, tz=timezone.utc),
                "Open": b.get("open"), "High": b.get("high"),
                "Low": b.get("low"), "Close": b.get("close"),
                "Volume": b.get("totalVolumeTraded", 0),
            })
        df = pd.DataFrame(rows).set_index("Date").dropna(subset=["Close"])
        return Bars(symbol=symbol, df=df, source=self.name, interval=interval) if len(df) else None


# --------------------------------------------------------------------------
# Underlying resolution.
#
# A mini future's own price chart is NOT usable: Avanza only records a bar when
# a retail trade prints, so a liquid S&P mini showed 16 bars in a month and 7 of
# them had a close outside their own high/low. Measured 2026-08-05.
#
# The instrument is a linear function of its underlying, so the underlying is
# what you actually chart -- with the knockout barrier drawn on it.
# --------------------------------------------------------------------------

_UNDERLYING = {
    "s&p 500": "^GSPC", "nasdaq": "^NDX", "nasdaq 100": "^NDX",
    "omx stockholm 30 index": "^OMX", "omxs30": "^OMX",
    "dax": "^GDAXI", "dow jones": "^DJI", "nikkei": "^N225",
    "euro stoxx 50": "^STOXX50E", "ftse 100": "^FTSE",
    "ice brent crude oil futures": "BZ=F", "brent": "BZ=F", "wti": "CL=F",
    "guld": "GC=F", "gold": "GC=F", "silver": "SI=F", "silver ": "SI=F",
    "koppar": "HG=F", "copper": "HG=F", "naturgas": "NG=F",
    "tesla": "TSLA", "apple": "AAPL", "amazon": "AMZN", "nvidia": "NVDA",
    "meta": "META", "microsoft": "MSFT", "alphabet": "GOOGL", "netflix": "NFLX",
    "bitcoin": "BTC-USD", "ethereum": "ETH-USD",
    # Stockholm large caps. Yahoo's name search does not find Swedish share
    # classes ("Volvo B"), so these are explicit.
    "volvo car": "VOLCAR-B.ST", "volvo b": "VOLV-B.ST", "volvo a": "VOLV-A.ST",
    "ericsson b": "ERIC-B.ST", "h&m b": "HM-B.ST", "hennes & mauritz b": "HM-B.ST",
    "evolution": "EVO.ST", "investor b": "INVE-B.ST", "atlas copco a": "ATCO-A.ST",
    "atlas copco b": "ATCO-B.ST", "sandvik": "SAND.ST", "seb a": "SEB-A.ST",
    "swedbank a": "SWED-A.ST", "handelsbanken a": "SHB-A.ST", "saab b": "SAAB-B.ST",
    "hexagon b": "HEXA-B.ST", "essity b": "ESSITY-B.ST", "skf b": "SKF-B.ST",
    "nordea": "NDA-SE.ST", "boliden": "BOL.ST", "alfa laval": "ALFA.ST",
    "assa abloy b": "ASSA-B.ST", "astrazeneca": "AZN.ST", "electrolux b": "ELUX-B.ST",
    "telia": "TELIA.ST", "abb ltd": "ABB.ST", "sinch": "SINCH.ST",
}

# Fallback keyed off the instrument NAME, since certificates (BULL/BEAR) often
# carry no subCategory at all -- BULL GULD and BULL TESLA both returned nothing.
_NAME_HINTS = [
    ("SP500", "^GSPC"), ("S&P", "^GSPC"), ("NASDAQ", "^NDX"), ("OMX", "^OMX"),
    ("DAX", "^GDAXI"), ("GULD", "GC=F"), ("SILVER", "SI=F"), ("OLJA", "BZ=F"),
    ("BRENT", "BZ=F"), ("KOPPAR", "HG=F"), ("NATURGAS", "NG=F"),
    ("TESLA", "TSLA"), ("APPLE", "AAPL"), ("NVIDIA", "NVDA"), ("AMAZON", "AMZN"),
    ("BITCOIN", "BTC-USD"), ("ETHEREUM", "ETH-USD"), ("META", "META"),
    ("MICROSOFT", "MSFT"), ("GOOGLE", "GOOGL"),
    ("VOLVO", "VOLV-B.ST"), ("ERICSSON", "ERIC-B.ST"), ("EVOLUTION", "EVO.ST"),
    ("INVESTOR", "INVE-B.ST"), ("SANDVIK", "SAND.ST"), ("SAAB", "SAAB-B.ST"),
]


def underlying_symbol(sub_category: str, name: str = "") -> str | None:
    """Map an Avanza instrument to a yfinance symbol for charting."""
    s = (sub_category or "").strip().lower()
    if s in _UNDERLYING:
        return _UNDERLYING[s]
    for k, v in _UNDERLYING.items():
        if k and k in s:
            return v
    up = (name or "").upper()
    for k, v in _NAME_HINTS:
        if k in up:
            return v
    return _search_underlying(sub_category)


_SEARCH_CACHE: dict[str, str | None] = {}


def _search_underlying(company: str) -> str | None:
    """Fallback when the table has no entry: ask Yahoo's search for the
    underlying's company name ("Advanced Micro Devices" -> AMD). Only a
    stock/ETF/index hit counts; anything else stays unresolved rather than
    guessed. Cached per name, including misses, so it costs one lookup."""
    key = (company or "").strip().lower()
    if len(key) < 3:
        return None
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    try:
        import yfinance as yf
        quotes = yf.Search(company, max_results=8).quotes or []
    except Exception:
        return None             # network failure: don't cache, try again next time
    # Real listings only: US (no suffix), Stockholm first, then major Europe.
    # A hit like "SSVOLVB.FGI" (a fund index) must not pass for Volvo B.
    ok_suffix = ("", ".ST", ".HE", ".CO", ".OL", ".DE", ".PA", ".AS", ".L", ".SW", ".MI")
    cands = []
    for q in quotes:
        sym = q.get("symbol") or ""
        if q.get("quoteType") not in ("EQUITY", "ETF", "INDEX") or not sym:
            continue
        suffix = sym[sym.rfind("."):] if "." in sym else ""
        if sym.startswith("^") or suffix in ok_suffix:
            cands.append(sym)
    found = next((c for c in cands if c.endswith(".ST")), cands[0] if cands else None)
    _SEARCH_CACHE[key] = found
    return found


# --------------------------------------------------------------------------
# Authenticated session (optional).
#
# Unlocks: real-time quotes (Avanza serves free real-time stocks for the
# Nordics, US and most of western Europe), order book depth, and positions.
#
# CREDENTIALS COME FROM THE ENVIRONMENT ONLY. Never hardcode them, never log
# them, never paste them into a chat. Put them in a local .env that is already
# gitignored:
#
#     AVANZA_USERNAME=...
#     AVANZA_PASSWORD=...
#     AVANZA_TOTP_SECRET=...        # the BankID/TOTP base32 secret
#
# This is an UNOFFICIAL API against a funded brokerage account. Poll gently,
# never place orders through it, and expect it to break without warning.
# --------------------------------------------------------------------------

def _totp(secret: str) -> str:
    """RFC 6238 TOTP from a base32 secret — no third-party dependency.

    Verified against the RFC 6238 test vectors (T=59 -> 287082,
    T=1111111109 -> 081804).

    The secret is cleaned BEFORE the padding is computed. That ordering is the
    whole bug this docstring exists for: Avanza shows the secret in
    space-separated groups, and padding on the raw length threw
    "Incorrect padding" on exactly the string a user would paste.
    """
    import base64, hmac, hashlib, struct, time
    clean = secret.upper().replace(" ", "").replace("-", "").replace("=", "")
    key = base64.b32decode(clean + "=" * (-len(clean) % 8))
    counter = struct.pack(">Q", int(time.time()) // 30)
    h = hmac.new(key, counter, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


# Seconds to refuse further login attempts after a failure, by failure kind.
LOGIN_COOLDOWN_S = {"auth": 30 * 60, "totp": 60, "other": 5 * 60}
# Any failure after the first consecutive one waits this long. Each TOTP-stage
# failure has already passed step 1 (the password), which is what Avanza counts
# toward its daily throttle; a persistent TOTP problem (wrong secret, clock skew)
# with a flat 60 s cool-down would spend ~15 logins in ~15 minutes of polling.
LOGIN_COOLDOWN_REPEAT_S = 30 * 60

_LONG_DIGITS = re.compile(r"\d{5,}")


def _redact(text: str) -> str:
    """Mask 5+ digit runs (account/customer numbers) in anything shown."""
    return _LONG_DIGITS.sub(lambda m: "•" * len(m.group()), str(text))


class AvanzaAuth:
    """Holds an authenticated session. Import lazily; absent creds = disabled."""

    def __init__(self):
        import os
        self.user = os.getenv("AVANZA_USERNAME")
        self.pw = os.getenv("AVANZA_PASSWORD")
        self.secret = os.getenv("AVANZA_TOTP_SECRET")
        self.token = None
        self.customer_id = None
        # Set when Avanza reports 2FA is not yet activated; carries the URL it
        # handed back. Held in memory only, never logged -- it embeds a ticket.
        self.activation_url = None
        self.security_token = None
        self.cookies = None
        self.opener = None
        self._last_attempt = 0.0
        # Failure memory. Avanza throttles logins (HTTP 401 after ~15 in a day),
        # and before this existed a failed login was retried on EVERY quote,
        # portfolio call and panel refresh -- the fastest way to turn one bad
        # login into a lockout. Every caller goes through login(), so this is
        # the single place that can stop it.
        self.blocked_until = 0.0          # epoch seconds; 0 = not blocked
        self.last_failure: str | None = None
        self.last_failure_kind: str | None = None
        self._fail_kind = "other"
        self._consecutive_failures = 0
        self._login_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """Username and password are enough to ATTEMPT a login.

        The TOTP secret is deliberately not required here. Avanza is expected to
        demand a second factor, but that is Avanza's answer to give, not a
        precondition invented on this side -- refusing to try would report
        "not configured" when the real answer is "your account requires 2FA",
        and those need different fixes.
        """
        return bool(self.user and self.pw)

    @property
    def has_totp(self) -> bool:
        return bool(self.secret)

    def login_block(self) -> dict:
        """Cool-down state, safe to show: ISO time or None, redacted reason."""
        active = self.blocked_until > time.time()
        return {"login_blocked_until": (datetime.fromtimestamp(self.blocked_until, timezone.utc)
                                        .isoformat(timespec="seconds") if active else None),
                "last_login_failure": _redact(self.last_failure) if self.last_failure else None}

    def status(self) -> dict:
        return {"configured": self.configured, "has_totp": self.has_totp,
                "authenticated": bool(self.token), **self.login_block(),
                "unlocks": ["real-time quotes", "order book depth", "positions"],
                "note": "unofficial API — poll gently, never place orders through it"}

    def login(self) -> tuple[bool, str]:
        """Rate-guarded login. Returns (ok, reason) without touching the network
        while a cool-down from the previous failure is active.

        Cool-downs (LOGIN_COOLDOWN_S): 30 min after a step-1 HTTP 401/403 --
        credentials rejected OR Avanza throttling, the lockout risk; 60 s after a
        TOTP replay/rejection; 5 min for anything else; 30 min for any failure after
        the first consecutive one. The first attempt of a
        session is never blocked. Serialised by a lock so concurrent callers
        (eight quote threads at startup) produce one login, not eight.
        """
        if not self.configured:
            return False, "AVANZA_USERNAME and AVANZA_PASSWORD are not set"
        with self._login_lock:
            if self.token:
                return True, "existing session"
            now = time.time()
            if now < self.blocked_until:
                mins = max(1, round((self.blocked_until - now) / 60))
                return False, (f"{self.last_failure}; next attempt allowed in {mins} min")
            self._fail_kind = "other"
            ok, why = self._attempt_login()
            if ok:
                self.blocked_until, self.last_failure, self.last_failure_kind = 0.0, None, None
                self._consecutive_failures = 0
            else:
                self.last_failure, self.last_failure_kind = why, self._fail_kind
                self._consecutive_failures += 1
                cool = LOGIN_COOLDOWN_S[self._fail_kind]
                if self._consecutive_failures > 1:
                    cool = max(cool, LOGIN_COOLDOWN_REPEAT_S)
                self.blocked_until = time.time() + cool
            return ok, why

    def _attempt_login(self) -> tuple[bool, str]:
        """One real login. Returns (ok, reason). Reason is safe to display -- it never contains
        a credential, only which stage failed and what that stage means.

        Step 1 posts username and password. Avanza replies with a
        transactionId, which is NOT a session: it is a ticket saying "now prove
        the second factor". Step 2 spends that ticket with a TOTP code.

        If Avanza ever returns a session straight from step 1, that is honoured
        and the login succeeds without TOTP. That branch is not expected to fire
        -- Swedish brokers are under PSD2 strong-customer-authentication rules --
        but it costs nothing and means the code reports what Avanza actually
        does rather than what it was assumed to do.
        """
        if not self.configured:
            return False, "AVANZA_USERNAME and AVANZA_PASSWORD are not set"

        # THE TWO STEPS SHARE A COOKIE, AND THAT IS THE WHOLE TRICK.
        #
        # Step 1 sets a session cookie identifying the pending 2FA transaction.
        # Step 2 is only meaningful inside that session. Bare urlopen keeps no
        # cookies, so an earlier version passed the transactionId as an
        # Authorization header instead -- and Avanza answered 401, which
        # presented as "the TOTP code was rejected". The code was correct; the
        # transaction simply was not attached to the request. Wrong diagnosis,
        # sent by a wrong assumption, and it cost real debugging time on the
        # clock and the secret.
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            urllib.request.HTTPSHandler(context=_ctx()))

        try:
            body = json.dumps({"maxInactiveMinutes": 240,
                               "password": self.pw, "username": self.user}).encode()
            req = urllib.request.Request(BASE + "/_api/authentication/sessions/usercredentials",
                                         headers=_HDRS, data=body, method="POST")
            with opener.open(req, timeout=15) as r:
                d = json.load(r)
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (401, 403):
                self._fail_kind = "auth"
                return False, ("Avanza rejected the login at step 1 (HTTP %s): wrong "
                               "username/password, or logins are being throttled" % code)
            return False, f"step 1 failed: {type(e).__name__}"

        # Some accounts may be handed a session directly.
        direct = d.get("authenticationSession")
        if direct:
            self.token = direct
            self.customer_id = d.get("customerId")
            return True, "authenticated with username and password (no 2FA required)"

        # Avanza answers step 1 with one of two objects, and they mean OPPOSITE
        # things. Reading only a top-level transactionId conflated them into
        # "neither a session nor a ticket", which is true but useless:
        #
        #   twoFactorLogin      -> 2FA IS set up. Prove it. This is the good path.
        #   twoFactorActivation -> 2FA is NOT set up. Avanza is handing back
        #                          activation URLs, not a login challenge. No
        #                          TOTP code can satisfy this, however correct
        #                          the secret is -- the account must be
        #                          activated first, in a browser.
        act = d.get("twoFactorActivation")
        if act:
            self.activation_url = act.get("activateUrl") or act.get("webViewActivateUrl")
            return False, ("two-factor login is NOT activated on this Avanza account. "
                           "Avanza returned an ACTIVATION ticket, not a login "
                           "challenge, so no TOTP code can satisfy it yet. Activate "
                           "it in a browser first — run this script with --activate "
                           "to print the exact URL Avanza just handed back.")

        two = d.get("twoFactorLogin") or {}
        tx = two.get("transactionId") or d.get("transactionId")
        if not tx:
            return False, (f"unrecognised response from Avanza (keys: "
                           f"{sorted(d.keys())}) — the API shape may have changed")

        if not self.has_totp:
            return False, ("Avanza accepted the password and is asking for a second "
                           "factor. Username and password alone are not enough — "
                           "set AVANZA_TOTP_SECRET.")

        method = (two.get("method") or "TOTP").upper()
        if method not in ("TOTP", "SMS"):
            return False, f"Avanza wants a second factor this code cannot supply: {method}"
        # Deliberately generated as late as possible: a code minted before a
        # slow step 1 can expire inside its own 30-second window.
        try:
            body2 = json.dumps({"method": "TOTP",
                                "totpCode": _totp(self.secret)}).encode()
            req2 = urllib.request.Request(BASE + "/_api/authentication/sessions/totp",
                                          headers=_HDRS, data=body2, method="POST")
            with opener.open(req2, timeout=15) as r:   # same opener == same cookies
                d2 = json.load(r)
                # Every later authenticated call is signed with this, not with
                # the credentials, which never travel again.
                self.security_token = r.headers.get("X-SecurityToken")
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (401, 403):
                self._fail_kind = "totp"
                # A TOTP code is single-use. Logging in twice inside the same
                # 30-second window sends the SAME code twice and Avanza rejects
                # the replay -- which is correct of it, and looks identical to a
                # wrong secret. Measured: a login that succeeded, repeated
                # immediately, failed; the same credentials succeeded again in
                # the next window. So say both, cheapest check first.
                if time.time() - self._last_attempt < 30:
                    return False, ("TOTP code replayed — a code is single-use and "
                                   "this login was inside the same 30s window as "
                                   "the last one. Wait for the next window.")
                return False, ("Avanza rejected the TOTP code. If the clock is "
                               "correct, the secret in .env is probably from an "
                               "earlier activation — re-activating issues a NEW "
                               "secret and invalidates the old one.")
            return False, f"step 2 failed: {type(e).__name__}"
        finally:
            self._last_attempt = time.time()

        self.token = d2.get("authenticationSession")
        self.customer_id = d2.get("customerId")
        self.cookies = jar
        self.opener = opener
        return (True, "authenticated") if self.token else (False, "no session returned")

    # --------------------------------------------------------- authenticated
    def ensure(self) -> tuple[bool, str]:
        """Log in only if there is no live session.

        Re-logging in gratuitously is not free: it burns a single-use TOTP code
        and, inside the same 30s window, fails outright. Callers should route
        through here rather than calling login() directly.
        """
        if self.token:
            return True, "existing session"
        return self.login()

    def get(self, path: str):
        """Authenticated GET. Returns parsed JSON, or None.

        Uses the login opener so the session cookies travel, and signs with
        X-SecurityToken. The SSL context must be pinned here too -- an opener
        built without it fails on any machine whose trust store lacks the root,
        which is exactly how this first failed with a bare URLError.
        """
        if not self.token or not self.opener:
            return None
        h = dict(_HDRS)
        if self.security_token:
            h["X-SecurityToken"] = self.security_token
        try:
            with self.opener.open(urllib.request.Request(BASE + path, headers=h),
                                  timeout=12) as r:
                return json.load(r)
        except Exception:
            return None
