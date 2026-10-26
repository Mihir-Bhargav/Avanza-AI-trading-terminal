"""
Live streaming quotes over Yahoo's push socket.

WHY THIS EXISTS
---------------
The terminal used to poll. Forty symbols on a timer, plus watchlist rescans,
plus a refetch on every chart load, and on 2026-08-05 it rate-limited ITSELF
into a wall of YFRateLimitError -- every panel silently blank. Polling harder to
get "real time" makes that strictly worse: the tighter the loop, the sooner the
feed cuts you off.

This inverts it. Yahoo pushes ticks over a websocket; nothing is requested at
all. Measured on 2026-08-05: 8 symbols live in under 4 seconds, and the socket
carries the whole watchlist for the same zero requests as one symbol.

WHAT IT IS NOT
--------------
Not a replacement for the REST feed. The socket only ticks for markets that are
OPEN, so an evening in Stockholm looking at DAX legitimately produces nothing.
`quote()` therefore returns None rather than a guess, and the caller falls back
to the cached REST path -- which is correct, because a closed market's last
close IS the right number to show. The freshness taxonomy already separates
CLOSED from STALE, and that distinction is the whole reason this terminal exists.

The cardinal rule holds: a streamed price carries its own arrival time, so a
tick that stopped arriving ages visibly instead of pretending to be live.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

# yfinance's socket calls websockets' sync_connect with no SSL context, which
# fails on any machine whose system trust store lacks the root -- the same
# failure the Avanza feed hit behind a university proxy. Pinning certifi via the
# env var fixes it for every library in the process, since Python's ssl module
# reads SSL_CERT_FILE when building its default context.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass


class LiveStream:
    """Background websocket holding the newest tick per symbol.

    Thread-safe. Reconnects on its own. Never raises into the caller: a dead
    socket degrades to "no live quote", which the REST path then covers.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ticks: dict[str, dict] = {}
        self._subs: set[str] = set()
        self._ws = None
        self._thread: threading.Thread | None = None
        self._stop = False
        self._connected = False
        self._last_error: str | None = None
        self._reconnects = 0

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="livestream")
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._close()

    def _close(self) -> None:
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        self._connected = False

    def _run(self) -> None:
        while not self._stop:
            try:
                import yfinance as yf

                self._ws = yf.WebSocket(verbose=False)
                with self._lock:
                    want = sorted(self._subs)
                if want:
                    self._ws.subscribe(want)
                self._connected = True
                self._last_error = None
                self._ws.listen(self._on_message)     # blocks until the socket dies
            except Exception as e:
                self._last_error = f"{type(e).__name__}: {e}"[:200]
            self._connected = False
            if self._stop:
                break
            # Backing off matters: a reconnect storm against a feed that just
            # dropped you is how the rate-limit outage started in the first place.
            self._reconnects += 1
            time.sleep(min(30, 2 ** min(self._reconnects, 4)))

    # ---------------------------------------------------------------- ingest
    def _on_message(self, msg: dict) -> None:
        sym = msg.get("id")
        if not sym:
            return
        price = msg.get("price")
        if price is None:
            return
        with self._lock:
            self._ticks[sym] = {
                "price": float(price),
                "change_pct": (None if msg.get("change_percent") is None
                               else float(msg["change_percent"])),
                "volume": msg.get("day_volume"),
                # Arrival time, not the exchange stamp: this is what makes a
                # stalled stream visibly age instead of looking live forever.
                "at": time.time(),
            }

    # ------------------------------------------------------------ subscribe
    # One socket serves every browser tab, so the subscription set is the UNION
    # of what the clients want, not the last message received. Replacing it
    # would make two open tabs silently unsubscribe each other -- the second tab
    # would look live while the first went quiet for no visible reason.
    MAX_SUBS = 300

    def set_symbols(self, symbols: list[str]) -> None:
        """Add to the subscription set. Cheap to call on every client message."""
        want = {s for s in symbols if s}
        with self._lock:
            new = want - self._subs
            self._subs |= want
            # Bounded so a long session drifting across watchlists cannot grow
            # the socket without limit. Drops the coldest ticks first.
            if len(self._subs) > self.MAX_SUBS:
                cold = sorted(self._subs - want,
                              key=lambda s: self._ticks.get(s, {}).get("at", 0))
                for s in cold[:len(self._subs) - self.MAX_SUBS]:
                    self._subs.discard(s)
                    self._ticks.pop(s, None)
        if new and self._ws and self._connected:
            try:
                self._ws.subscribe(sorted(new))
            except Exception as e:
                self._last_error = f"subscribe: {type(e).__name__}"[:120]
        self.start()

    # --------------------------------------------------------------- readout
    def quote(self, symbol: str, max_age: float = 90.0) -> dict | None:
        """Newest tick, or None if it is older than max_age.

        None is a real answer -- it means "the socket is not covering this right
        now", and the caller should fall back rather than render a stale number
        as live.
        """
        with self._lock:
            t = self._ticks.get(symbol)
        if not t:
            return None
        age = time.time() - t["at"]
        if age > max_age:
            return None
        return {
            "symbol": symbol,
            "price": t["price"],
            "change_pct": t["change_pct"],
            "volume": t["volume"],
            "age_min": round(age / 60, 2),
            "freshness": "realtime",
            "source": "yahoo-stream",
            "ts": datetime.fromtimestamp(t["at"], tz=timezone.utc).isoformat(),
        }

    def status(self) -> dict:
        with self._lock:
            n, subs = len(self._ticks), len(self._subs)
            live = sum(1 for t in self._ticks.values() if time.time() - t["at"] < 90)
        return {"connected": self._connected, "subscribed": subs,
                "ticking": live, "seen": n, "reconnects": self._reconnects,
                "last_error": self._last_error}


STREAM = LiveStream()
