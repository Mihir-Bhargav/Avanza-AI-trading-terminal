"""Test setup. No network and no Avanza logins anywhere in this suite.

Avanza credentials are blanked BEFORE any terminal module is imported, so even
an accidental AvanzaAuth() would be unconfigured and could not log in.
"""
import os
import socket
import sys
from pathlib import Path

import pytest

for k in ("AVANZA_USERNAME", "AVANZA_PASSWORD", "AVANZA_TOTP_SECRET", "ALPHAVANTAGE_API_KEY",
          "SEC_USER_AGENT"):
    os.environ[k] = ""

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def guard(*a, **k):
        raise RuntimeError("network access attempted in a unit test")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
