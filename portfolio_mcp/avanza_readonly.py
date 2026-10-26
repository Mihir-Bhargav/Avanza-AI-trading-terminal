"""
Read-only access to the logged-in Avanza account.

Reuses terminal.feeds.avanza.AvanzaAuth as the ONE login path -- same env vars,
same TOTP handling, same cookie-jar session. Nothing here stores or re-reads
credentials.

READ-ONLY IS ENFORCED, NOT ASSUMED. Callers cannot pass a path. They can only
name an entry in READ_ENDPOINTS, and that table is the complete set of requests
this module will ever send. The one POST in it (insights) is a report query --
Avanza takes its filter in a body -- and changes nothing. The Qluxzz `avanza`
library, which carries place_order/stop-loss/transfer methods, is deliberately
not imported anywhere in this package.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from types import MappingProxyType

from terminal.feeds.avanza import BASE, _HDRS, AvanzaAuth

# name -> (HTTP method, path). Paths verified against avanza-api 16.2.0 source
# and against the live account on 2026-09-24.
READ_ENDPOINTS = MappingProxyType({
    "overview":     ("GET",  "/_api/account-overview/overview/categorizedAccounts"),
    "positions":    ("GET",  "/_api/position-data/positions"),
    "transactions": ("GET",  "/_api/transactions/list"),
    "insights":     ("POST", "/_api/insights-development/insights"),
})

CACHE_TTL_S = 60
TOTP_WINDOW_S = 30
TOTP_RETRY_MAX_WAIT_S = 61      # AvanzaAuth's TOTP cool-down is 60 s
# A 401/403 on a data request forces a fresh login (session expired). A
# SUCCESSFUL login is never cool-downed by AvanzaAuth, so an endpoint that keeps
# answering 401/403 would otherwise force a full login on every poll -- a login
# storm into Avanza's ~15/day throttle. At most one forced re-login per window,
# and none for a while if the retry right after a fresh login is rejected too.
RELOGIN_MIN_GAP_S = 15 * 60
RELOGIN_BLOCK_AFTER_REPEAT_S = 2 * 60 * 60


class ReadOnlyViolation(PermissionError):
    """Raised for any request not in READ_ENDPOINTS."""


class AvanzaUnavailable(RuntimeError):
    """Login or fetch failed. Message is always safe to show."""


_LONG_DIGITS = re.compile(r"\d{5,}")


def redact(text: str) -> str:
    """Mask any run of 5+ digits -- account, clearing and customer numbers."""
    return _LONG_DIGITS.sub(lambda m: "•" * len(m.group()), str(text))


class ReadOnlyAvanza:
    def __init__(self, auth: AvanzaAuth | None = None, ttl: float = CACHE_TTL_S):
        self.auth = auth or AvanzaAuth()
        self.ttl = ttl
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._relogin_at = 0.0             # last forced (fresh) re-login
        self._relogin_blocked_until = 0.0
        # One login at a time: two threads logging in inside the same 30s window
        # would send the same single-use TOTP code twice and the second fails.
        self._lock = threading.Lock()

    # ------------------------------------------------------------- public
    def fetch(self, name: str, query: dict | None = None, body: dict | None = None):
        if name not in READ_ENDPOINTS:
            raise ReadOnlyViolation(f"'{name}' is not a read-only endpoint")
        key = (name, json.dumps(query or {}, sort_keys=True),
               json.dumps(body or {}, sort_keys=True))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        data = self._request(name, query, body)
        self._cache[key] = (time.time(), data)
        return data

    # ------------------------------------------------------------ private
    def _login(self, fresh: bool) -> None:
        """Log in through AvanzaAuth, which enforces the failure cool-downs.

        At most ONE retry, and only for a TOTP-stage failure (a replayed or
        rejected code): another process may have spent this window's code. The
        retry waits out AvanzaAuth's short TOTP cool-down rather than bypassing
        it. A step-1 401/403 (bad credentials or Avanza throttling logins) is
        never retried -- its 30-minute cool-down stands.
        """
        with self._lock:
            if fresh:
                self.auth.token = None
                # A code already spent in this window is rejected as a replay;
                # waiting for the next window is the only fix, so do it here.
                wait = TOTP_WINDOW_S - (time.time() - self.auth._last_attempt)
                if 0 < wait <= TOTP_WINDOW_S:
                    time.sleep(wait + 1)
            ok, why = self.auth.ensure()
            if not ok and getattr(self.auth, "last_failure_kind", None) == "totp":
                wait = getattr(self.auth, "blocked_until", 0.0) - time.time()
                if wait <= TOTP_RETRY_MAX_WAIT_S:
                    if wait > 0:
                        time.sleep(wait + 1)
                    ok, why = self.auth.ensure()
        if not ok:
            raise AvanzaUnavailable(redact(f"Avanza login failed: {why}"))

    def _request(self, name: str, query: dict | None, body: dict | None):
        method, path = READ_ENDPOINTS[name]
        if query:
            path += "?" + urllib.parse.urlencode(query)
        self._login(fresh=False)
        for attempt in (1, 2):
            h = dict(_HDRS)
            if self.auth.security_token:
                h["X-SecurityToken"] = self.auth.security_token
            data = json.dumps(body).encode() if method == "POST" else None
            req = urllib.request.Request(BASE + path, headers=h, data=data, method=method)
            try:
                with self.auth.opener.open(req, timeout=15) as r:
                    return json.load(r)
            except Exception as e:
                code = getattr(e, "code", None)
                if code in (401, 403) and attempt == 1:
                    now = time.time()
                    if (now < self._relogin_blocked_until
                            or now - self._relogin_at < RELOGIN_MIN_GAP_S):
                        raise AvanzaUnavailable(
                            f"Avanza '{name}' request rejected (HTTP {code}); not forcing "
                            "another login so soon (logins are throttled)") from None
                    self._relogin_at = now
                    self._login(fresh=True)        # session expired: retry once
                    continue
                if code in (401, 403):             # rejected right after a fresh login
                    self._relogin_blocked_until = time.time() + RELOGIN_BLOCK_AFTER_REPEAT_S
                raise AvanzaUnavailable(redact(
                    f"Avanza '{name}' request failed: {type(e).__name__}"
                    + (f" HTTP {code}" if code else ""))) from None
