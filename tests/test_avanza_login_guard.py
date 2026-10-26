"""AvanzaAuth failure cool-downs. A fake opener stands in for the network:
no socket is opened and no real login happens."""
import io
import json
import time
import urllib.error

import pytest

from portfolio_mcp import avanza_readonly as RO
from terminal.feeds import avanza as AV


class Resp(io.BytesIO):
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode())
        self.headers = {"X-SecurityToken": "sec"}


class FakeOpener:
    """Scripted responses: 'step1' is dict-or-HTTP-code, 'step2' likewise."""
    def __init__(self, script):
        self.script, self.calls = script, []

    def open(self, req, timeout=None):
        step = "step2" if req.full_url.endswith("/totp") else "step1"
        self.calls.append(step)
        r = self.script[step]
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "x", {}, None)
        return Resp(r)


@pytest.fixture
def auth(monkeypatch):
    openers = []

    def make(script):
        a = AV.AvanzaAuth()
        a.user, a.pw, a.secret = "u", "p", "JBSWY3DPEHPK3PXP"
        op = FakeOpener(script)
        openers.append(op)
        monkeypatch.setattr(AV.urllib.request, "build_opener", lambda *h: op)
        return a, op
    return make


TWO_FACTOR = {"twoFactorLogin": {"transactionId": "t", "method": "TOTP"}}


def test_step1_401_blocks_for_30_min_without_network(auth):
    a, op = auth({"step1": 401})
    ok, why = a.ensure()
    assert not ok and "HTTP 401" in why and op.calls == ["step1"]
    assert a.last_failure_kind == "auth"
    assert a.blocked_until - time.time() == pytest.approx(30 * 60, abs=5)
    for _ in range(5):
        ok, why = a.ensure()
        assert not ok and "next attempt allowed in 30 min" in why
    assert op.calls == ["step1"]                       # no further requests
    st = a.status()
    assert st["login_blocked_until"] and "HTTP 401" in st["last_login_failure"]


def test_cooldown_expiry_allows_one_new_attempt(auth):
    a, op = auth({"step1": 401})
    a.ensure()
    a.blocked_until = time.time() - 1                  # cool-down elapsed
    assert a.status()["login_blocked_until"] is None
    op.script["step1"] = {"authenticationSession": "tok"}
    ok, _ = a.ensure()
    assert ok and a.token == "tok" and op.calls == ["step1", "step1"]
    assert a.last_failure is None and a.blocked_until == 0.0


def test_totp_failure_gives_short_cooldown(auth):
    a, op = auth({"step1": TWO_FACTOR, "step2": 401})
    ok, why = a.ensure()
    assert not ok and "TOTP" in why and op.calls == ["step1", "step2"]
    assert a.last_failure_kind == "totp"
    assert a.blocked_until - time.time() == pytest.approx(60, abs=5)
    assert not a.ensure()[0] and op.calls == ["step1", "step2"]


def test_other_failure_gives_5_min(auth):
    a, op = auth({"step1": 500})
    assert not a.ensure()[0]
    assert a.last_failure_kind == "other"
    assert a.blocked_until - time.time() == pytest.approx(300, abs=5)


def test_unconfigured_never_blocks_or_calls(auth):
    a, op = auth({"step1": 401})
    a.user = None
    assert not a.ensure()[0] and op.calls == [] and a.blocked_until == 0.0


def test_success_first_try(auth):
    a, op = auth({"step1": TWO_FACTOR, "step2": {"authenticationSession": "tok"}})
    assert a.ensure() == (True, "authenticated") and a.security_token == "sec"


def test_readonly_never_retries_after_step1_401(auth, monkeypatch):
    a, op = auth({"step1": 401})
    monkeypatch.setattr(RO.time, "sleep", lambda s: pytest.fail("must not wait/retry"))
    ro = RO.ReadOnlyAvanza(auth=a)
    for _ in range(3):
        with pytest.raises(RO.AvanzaUnavailable):
            ro.fetch("overview")
    assert op.calls == ["step1"]                       # one login across all calls


def test_readonly_retries_totp_once_after_cooldown(auth, monkeypatch):
    a, op = auth({"step1": TWO_FACTOR, "step2": 401})
    slept = []

    def fake_sleep(s):                                 # "wait" = cool-down expires
        slept.append(s)
        a.blocked_until = 0.0
    monkeypatch.setattr(RO.time, "sleep", fake_sleep)
    ro = RO.ReadOnlyAvanza(auth=a)
    with pytest.raises(RO.AvanzaUnavailable):
        ro.fetch("overview")
    assert op.calls == ["step1", "step2", "step1", "step2"]   # exactly one retry
    assert len(slept) == 1 and 55 <= slept[0] <= 62


def test_readonly_data_403_does_not_force_a_login_per_poll(auth, monkeypatch):
    """A data endpoint that keeps answering 403 after a SUCCESSFUL login must not
    trigger a fresh login on every request (successful logins have no cool-down)."""
    a, op = auth({"step1": {"authenticationSession": "tok", "pushSubscriptionId": "p"}})
    a.token, a.opener = "tok", None

    class DataOpener:
        def __init__(self):
            self.calls = 0

        def open(self, req, timeout=None):
            self.calls += 1
            raise urllib.error.HTTPError(req.full_url, 403, "x", {}, None)
    data = DataOpener()
    a.opener = data
    logins = []
    monkeypatch.setattr(RO.time, "sleep", lambda s: None)

    def fake_ensure():
        logins.append(1)
        a.token, a.opener = "tok", data
        return True, "authenticated"
    monkeypatch.setattr(a, "ensure", fake_ensure)
    ro = RO.ReadOnlyAvanza(auth=a, ttl=0)
    for _ in range(5):
        with pytest.raises(RO.AvanzaUnavailable):
            ro.fetch("overview")
    # first call: initial ensure + one forced re-login; later calls: ensure only
    # returns the existing session (no network), and no further forced re-login.
    forced = len(logins) - 5
    assert forced == 1


def test_repeated_totp_failure_escalates_to_30_min(auth):
    a, op = auth({"step1": TWO_FACTOR, "step2": 401})
    a.ensure()
    a.blocked_until = time.time() - 1                  # 60 s cool-down elapsed
    assert not a.ensure()[0]
    assert a.blocked_until - time.time() == pytest.approx(30 * 60, abs=5)
