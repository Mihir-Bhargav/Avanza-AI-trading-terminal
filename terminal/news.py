"""
News scanner.

THE TRADE THIS EXISTS TO CATCH
------------------------------
On 2026-08-05 Google's AI leadership changed -- Jeff Dean out, Hassabis moving
off DeepMind -- and GOOGL, a name that had been going nowhere, fell ~4%. The
story was on the wire at 16:03 GMT. The terminal showed the price move and had
nothing to say about why, so it read as noise.

The bot exists to close that gap: it pairs an unusual PRICE move with the
HEADLINES that landed next to it, so a 4% drop arrives with its reason attached.

ON X / TWITTER -- READ THIS BEFORE ASKING WHY IT IS MISSING
-----------------------------------------------------------
X has no usable free tier. Search was removed from the free API entirely, and
the cheapest plan that can search is ~$200/month. Nitter mirrors are dead. So
there is no honest way to stream X here without paying, and pretending
otherwise by scraping would break the moment it mattered.

What actually replaces it: Google News indexes the reporting that follows a
tweet within minutes, and its `when:1h` filter is genuinely fast -- it carried
the Google AI story the same afternoon, from four outlets. That is the same
information one hop later, and it is free and stable. If X access is ever worth
$200/month, this module has one clean seam (`SOURCES`) to add it to.

Every source below was verified reachable on 2026-08-05.
"""

from __future__ import annotations

import html
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# Google News is the backbone here, not one feed among several. It aggregates
# every outlet, its `when:` filter is the fastest free recency control
# available, and -- the reason it matters for THIS trader -- it is regional.
# The other five feeds are all US desks, which is useless when the position is
# on OMXS30 or the DAX.
GOOGLE = "https://news.google.com/rss/search?q={q}&{region}"

# Verified live 2026-08-05, one region at a time. Swedish comes back in Swedish
# (Placera, Affarsvarlden) which is correct -- those desks break Stockholm news
# first, and an English-only query would miss them.
REGIONS = {
    "us": "hl=en-US&gl=US&ceid=US:en",
    "sweden": "hl=sv&gl=SE&ceid=SE:sv",
    "eu": "hl=en-GB&gl=GB&ceid=GB:en",
    "india": "hl=en-IN&gl=IN&ceid=IN:en",
    "commodities": "hl=en-US&gl=US&ceid=US:en",
}

# What "the market" means depends on which tab is open.
#
# MULTI-WORD TERMS IN AN `OR` CHAIN MUST BE QUOTED. This is not style: an
# unquoted phrase silently zeroes the WHOLE query rather than just its own term.
# Measured 2026-08-05 --
#     Stockholmsbörsen when:2d                             -> 63 items
#     Stockholmsbörsen OR OMXS30 when:2d                   -> 37 items
#     ... OR Stockholm stock exchange when:2d              ->  0 items
# Google returns a valid, empty RSS document, so the failure looks exactly like
# "no news today". Quoting that one phrase brought it back to 38.
MARKET_QUERIES = {
    "us": '"stock market" OR "wall street" OR "S&P 500" when:1d',
    "sweden": "Stockholmsbörsen OR OMXS30 OR börsen when:2d",
    "eu": 'DAX OR "CAC 40" OR "European stocks" OR STOXX when:1d',
    # "Nifty 50", not bare "Nifty" -- unquoted it is an ordinary English
    # adjective and the feed returned tennis coverage from Montreal.
    "india": '"Nifty 50" OR Sensex OR "Indian stock market" when:1d',
    "commodities": '"gold price" OR "oil price" OR commodities when:1d',
}

_UNQUOTED_PHRASE = re.compile(r"(?:^|\bOR\s+)(?!\")([A-Za-zÀ-ÿ&][\w&.-]*(?:\s+(?!OR\b|when:)[\w&.-]+)+)")


def check_query(query: str) -> list[str]:
    """Return unquoted multi-word terms in an OR chain — the failure above.

    Called by the tests rather than at runtime, so a bad query is caught when
    it is written instead of showing up months later as a quiet empty feed.
    """
    if " OR " not in query:
        return []
    return [m.group(1).strip() for m in _UNQUOTED_PHRASE.finditer(query)
            if not m.group(1).strip().startswith("when:")]


def google_news_url(query: str, market: str = "us") -> str:
    return GOOGLE.format(q=urllib.parse.quote(query),
                         region=REGIONS.get(market, REGIONS["us"]))


# Non-Google desks. Kept because they publish their own wire directly and
# sometimes beat the aggregator by a few minutes -- but they are all US, so they
# are only mixed in for the US tab.
US_DESKS = {
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "cnbc_markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "investing": "https://www.investing.com/rss/news.rss",
    "nasdaq": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
}

# Back-compat for anything still importing SOURCES.
SOURCES = {"google": GOOGLE, **US_DESKS}

# Yahoo attaches news to a SYMBOL, so the market wire pulls it from each
# market's bellwethers rather than from a query. No query means no query bugs --
# this is the source that cannot accidentally return tennis coverage.
YF_MARKET_TICKERS = {
    "us": ["^GSPC", "SPY", "NVDA"],
    "sweden": ["ERIC-B.ST", "VOLV-B.ST", "ATCO-A.ST"],
    "eu": ["^GDAXI", "ASML.AS", "SAP.DE"],
    "india": ["RELIANCE.NS", "INFY.NS", "^NSEI"],
    "commodities": ["GC=F", "CL=F", "GLD"],
}

# Words that move a price on their own. Used to rank, never to decide -- the
# score orders the list, it does not claim the story is tradeable.
_HOT = {
    3: ("bankruptcy", "fraud", "halted", "investigation", "recall", "guidance cut",
        "profit warning", "resigns", "resignation", "steps down", "ousted", "fired",
        "probe", "lawsuit", "subpoena", "default", "delisting", "short seller",
        # Leadership churn, added because the case this module was built around
        # was worded "shakes up AI leadership" and "joins wave of exits" -- the
        # obvious words ("resigns", "steps down") appeared in neither headline.
        "shakes up", "shake-up", "shakeup", "reshuffle", "overhaul", "exits",
        "departure", "departs", "leadership change", "replaced", "quits"),
    2: ("beats", "misses", "downgrade", "upgrade", "acquisition", "merger", "takeover",
        "buyout", "layoffs", "guidance", "earnings", "warns", "cuts", "raises",
        "ceo", "cfo", "stake", "activist", "fda", "approval", "rejected", "strike"),
    1: ("outlook", "forecast", "partnership", "launch", "contract", "deal",
        "expands", "reports", "announces", "target"),
}


# Boilerplate that is published on a schedule and carries no information.
# Without this the wire is unusable: Nasdaq alone posted six identical
# "Q2 26 Earnings Conference Call At 5:00 PM ET" lines within one minute, each
# scoring 2 on the word "earnings", and they buried every real story.
_NOISE = (
    re.compile(r"earnings conference call at", re.I),
    re.compile(r"^\s*(notice|correction|update)\s*[:\-]", re.I),
    re.compile(r"(webcast|conference call).{0,30}(scheduled|announce)", re.I),
    re.compile(r"to (host|present at|participate in).{0,40}(conference|call|summit)", re.I),
    re.compile(r"declares? (quarterly )?(cash )?dividend", re.I),
    re.compile(r"^\s*\w+\s+(q[1-4]|fy)\s*\d+\s+earnings\s+(date|call|release)", re.I),
)


def _is_noise(title: str) -> bool:
    return any(p.search(title) for p in _NOISE)


# Headlines that assert a CAUSE for a move. This is a separate axis from _HOT:
# keywords say the topic is weighty, this says the sentence is an explanation.
# Both are needed -- "Why Is Nvidia Stock Up Today? SpaceX Just Went All-In on
# Its Chips" contains no hot keyword at all and was the correct answer, while a
# keyword-heavy think-piece from four hours earlier was not.
_CAUSAL = re.compile(
    r"\b(why (is|are|did|does)|after|amid|following|on news|as \w+ (said|announced))\b"
    r"|\b(drops?|falls?|slides?|sinks?|plunges?|tumbles?|slumps?"
    r"|rises?|jumps?|soars?|surges?|climbs?|rallies|gains?)\b"
    r"|\b(weighs? on|boosts?|lifts?|drags?|sends?)\b", re.I)


def _explains(item: dict) -> bool:
    """Does this headline plausibly say WHY, and recently enough to be the why?"""
    return (bool(_CAUSAL.search(item["title"]) or item["score"] >= 2)
            and item["age_min"] is not None and item["age_min"] <= 720)


def _score(title: str) -> int:
    """Highest weight any keyword in the headline carries. Orders the list;
    it does not claim the story is tradeable."""
    t = title.lower()
    return max([w for w, words in _HOT.items() if any(k in t for k in words)] or [0])


def _get(url: str, timeout: int = 10) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return r.read().decode("utf8", "ignore")
    except Exception:
        return None


def _clean(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _parse_date(s: str) -> datetime | None:
    s = s.strip()
    for f in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
              "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(s, f)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_feed(xml: str, source: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>|<entry>(.*?)</entry>", xml, re.S):
        it = block[0] or block[1]
        tm = re.search(r"<title[^>]*>(.*?)</title>", it, re.S)
        if not tm:
            continue
        title = _clean(tm.group(1))
        if not title or _is_noise(title):
            continue
        dm = re.search(r"<(?:pubDate|published|updated)>(.*?)</(?:pubDate|published|updated)>", it, re.S)
        when = _parse_date(_clean(dm.group(1))) if dm else None
        lm = re.search(r"<link[^>]*>(.*?)</link>", it, re.S) or re.search(r'<link[^>]*href="(.*?)"', it, re.S)
        # Google News appends " - Outlet" to every headline; pull it out so the
        # source is a field rather than noise inside the title.
        outlet = source
        if source.startswith("google") or " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1]) < 40:
                title, outlet = parts[0], parts[1]
        out.append({
            "title": title,
            "url": _clean(lm.group(1)) if lm else "",
            "source": outlet,
            "feed": source,
            "ts": when.isoformat() if when else None,
            "age_min": (None if not when
                        else round((datetime.now(timezone.utc) - when).total_seconds() / 60)),
            "score": _score(title),
        })
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    """Same story from six outlets is one story. Key on the first six
    meaningful words -- headlines get reworded, ledes rarely reorder."""
    seen, out = set(), []
    for it in items:
        words = re.sub(r"[^a-z0-9 ]", "", it["title"].lower()).split()
        key = " ".join([w for w in words if len(w) > 3][:6])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def market_news(limit: int = 40, max_age_min: int = 1440,
                market: str = "us") -> list[dict]:
    """Broad market wire for ONE market, newest and hottest first.

    Google News carries the regional query; the US desks are mixed in only for
    the US tab, because a CNBC front page next to an OMXS30 position is noise
    dressed as coverage.
    """
    from concurrent.futures import ThreadPoolExecutor

    feeds = {"google": google_news_url(
        MARKET_QUERIES.get(market, MARKET_QUERIES["us"]), market)}
    if market == "us":
        feeds.update(US_DESKS)

    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        rss = pool.map(_get, feeds.values())
        yf_f = pool.submit(
            lambda: [n for t in YF_MARKET_TICKERS.get(market, [])
                     for n in yf_news(t, limit=6)])
        for src, xml in zip(feeds, rss):
            if xml:
                items += parse_feed(xml, src)
        try:
            items += yf_f.result(timeout=20)
        except Exception:
            pass
    items = [i for i in items if i["age_min"] is None or i["age_min"] <= max_age_min]
    items = _dedupe(items)
    items.sort(key=lambda i: i["age_min"] if i["age_min"] is not None else 9999)

    # Cap any single feed's share. Nasdaq's bulk poster can emit a dozen items
    # in the same minute and, sorted purely by recency, would own the screen.
    # Skipped when only one feed is in play -- outside the US tab Google News IS
    # the wire, and capping it to a quarter would gut the list to nothing.
    if len(feeds) > 1:
        per, capped = {}, []
        for i in items:
            f = i["feed"]
            per[f] = per.get(f, 0) + 1
            if per[f] <= max(3, limit // 4):
                capped.append(i)
    else:
        capped = items
    # Recency leads; a genuinely hot headline is pulled up within the same hour.
    capped.sort(key=lambda i: ((i["age_min"] or 9999) // 60, -i["score"],
                               i["age_min"] if i["age_min"] is not None else 9999))
    return capped[:limit]


def yf_news(symbol: str, limit: int = 15) -> list[dict]:
    """Yahoo Finance news for one ticker, via yfinance.

    Worth having alongside Google News rather than instead of it. Yahoo's items
    are attached to the SYMBOL by Yahoo itself, so there is no query to get
    wrong -- no "Nifty" matching tennis coverage, no exchange-suffix problem.
    The cost is coverage: Yahoo carries little for Nordic and Indian tickers,
    where Google's regional feeds are the only real source. Using both, deduped,
    is strictly better than either.

    DATE HANDLING, which is not cosmetic here. Yahoo returns two timestamps and
    they genuinely differ -- observed pubDate 2026-08-03 against displayTime
    2026-08-05 on the same story, two days apart. pubDate is when the story was
    published, and that is the one that decides whether it can explain a move,
    so it wins. displayTime is only a fallback.
    """
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []

    out = []
    for it in raw[:limit]:
        c = it.get("content") or it
        title = (c.get("title") or "").strip()
        if not title or _is_noise(title):
            continue
        when = _parse_date(c.get("pubDate") or "") or _parse_date(c.get("displayTime") or "")
        url = ((c.get("clickThroughUrl") or {}) or {}).get("url") \
            or ((c.get("canonicalUrl") or {}) or {}).get("url") or ""
        out.append({
            "title": title,
            "url": url,
            "source": ((c.get("provider") or {}) or {}).get("displayName", "Yahoo Finance"),
            "feed": "yfinance",
            "ts": when.isoformat() if when else None,
            "age_min": (None if not when
                        else round((datetime.now(timezone.utc) - when).total_seconds() / 60)),
            "score": _score(title),
        })
    return out


def ticker_news(symbol: str, name: str = "", limit: int = 15,
                fresh_hours: int = 48, rank: str = "recent",
                market: str = "us") -> list[dict]:
    """News for one ticker, via a targeted Google News query.

    `rank` decides what "top" means, and the two questions genuinely differ:

      "recent"  -- what is the latest on this name? Newest first.
      "explain" -- WHY did it just move? Weight the headline that names a cause
                   over the newest one.

    That distinction is not cosmetic. On the GOOGL drop this module was built
    around, recency put "Ties Search, Cloud, and AI Into One Story" (28m, an
    opinion piece) above "Alphabet stock drops after the Google parent
    reshuffles top AI leadership" (67m) -- the newest headline and the
    explanatory one were different headlines, and only the second was the answer.
    """
    # Strip the exchange suffix: Google News knows "ERIC-B", not "ERIC-B.ST",
    # and a query carrying the suffix returns nothing at all.
    bare = symbol.split(".")[0].lstrip("^")
    q = f'"{name}" OR {bare}' if name else bare
    q = f"{q} stock when:2d"

    # Both sources, concurrently -- one slow feed must not double the latency.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        fg = pool.submit(_get, google_news_url(q, market))
        fy = pool.submit(yf_news, symbol, limit * 2)
        xml, yitems = fg.result(), fy.result()

    items = (parse_feed(xml, "google") if xml else []) + (yitems or [])
    items = [i for i in items
             if i["age_min"] is None or i["age_min"] <= fresh_hours * 60]
    items = _dedupe(items)
    if rank == "explain":
        # Two-hour recency buckets first, then explanatory power, then age. The
        # buckets matter: ranking by score alone floated a 138-minute think-piece
        # above the 43-minute partnership story that actually moved NVDA, while
        # ranking by age alone floated a 28-minute opinion piece above the
        # leadership shakeup that actually moved GOOGL. Bucketing gets both right.
        items.sort(key=lambda i: ((i["age_min"] or 9999) // 120,
                                  -(2 if _explains(i) else 0) - i["score"],
                                  i["age_min"] if i["age_min"] is not None else 9999))
    else:
        items.sort(key=lambda i: i["age_min"] if i["age_min"] is not None else 9999)
    return items[:limit]


# --------------------------------------------------------------------------
# The bot.
#
# A price move alone is noise and a headline alone is chatter. The pairing is
# the signal, and it is the thing that was missing when GOOGL fell 4%.
# --------------------------------------------------------------------------

class NewsBot:
    """Watches for unusual moves and attaches the headlines that explain them."""

    def __init__(self, move_atr: float = 1.0):
        # In ATRs, not percent: 4% is enormous for a utility and a normal
        # morning for AMD. Percent thresholds fire constantly on the volatile
        # names and never on the ones where a move actually means something.
        self.move_atr = move_atr
        self._lock = threading.Lock()
        self._hits: dict[str, dict] = {}
        self._pushed: set[str] = set()
        self._scanned_at: float | None = None
        self._scanning = False

    def status(self) -> dict:
        with self._lock:
            return {"watching": len(self._hits), "move_atr": self.move_atr,
                    "last_scan_min": (None if not self._scanned_at
                                      else round((time.time() - self._scanned_at) / 60, 1)),
                    "scanning": self._scanning}

    def hits(self) -> list[dict]:
        with self._lock:
            v = list(self._hits.values())
        v.sort(key=lambda h: -abs(h.get("move_atr") or 0))
        return v

    def scan(self, rows: list[dict], push_alerts: bool = True,
             market: str = "us") -> list[dict]:
        """`rows` are watchlist rows: symbol, change_pct, atr_pct.

        Only unusual movers get a news lookup -- one request per genuine mover
        rather than one per name, which is what keeps this off the rate limiter.
        """
        from concurrent.futures import ThreadPoolExecutor

        self._scanning = True
        try:
            movers = []
            for r in rows:
                chg, atr = r.get("change_pct"), r.get("atr_pct")
                if chg is None or not atr or atr != atr or atr <= 0:
                    continue
                n = chg / atr
                if abs(n) >= self.move_atr:
                    movers.append((r["symbol"], chg, round(n, 2)))
            movers.sort(key=lambda m: -abs(m[2]))
            movers = movers[:12]

            out = []
            if movers:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    newses = list(pool.map(
                        lambda m: ticker_news(m[0], limit=5, rank="explain",
                                              market=market), movers))
                for (sym, chg, n), news in zip(movers, newses):
                    # "Explained" requires a headline that names a cause within
                    # 12h. A recent opinion piece is not an explanation, and
                    # calling it one would be the same failure as the fabricated
                    # Heston BUY: a confident label over nothing.
                    out.append({"symbol": sym, "change_pct": round(chg, 2),
                                "move_atr": n, "news": news,
                                "explained": bool(news and _explains(news[0]))})
            with self._lock:
                self._hits = {h["symbol"]: h for h in out}
                self._scanned_at = time.time()

            if push_alerts:
                self._push(out)
            return out
        finally:
            self._scanning = False

    def _push(self, hits: list[dict]) -> None:
        from terminal.alerts import push

        today = datetime.now(timezone.utc).date().isoformat()
        for h in hits:
            if not h["explained"] or abs(h["move_atr"]) < 1.5:
                continue
            top = h["news"][0]
            # Dedupe on the story, not the symbol: a name can move twice in a
            # day for two different reasons and both are worth knowing.
            key = f"{h['symbol']}|{top['title'][:60]}|{today}"
            with self._lock:
                if key in self._pushed:
                    continue
                self._pushed.add(key)
            push(f"{h['symbol']} {h['change_pct']:+.2f}% ({h['move_atr']:+.1f} ATR)",
                 f"{top['title']}\n— {top['source']}, {top['age_min']}m ago",
                 tags="newspaper", url=top.get("url") or None)


BOT = NewsBot()
