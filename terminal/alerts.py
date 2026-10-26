"""
Level-cross alerts -> ntfy push.

The point: you cannot watch ten charts, and today proved you do not need to.
Five of eight setups triggered while you were looking at them and four failed.
What you actually need is to be told the moment price touches a level you
already decided mattered, so the decision is made in advance and the screen is
just confirmation.

Uses the ntfy topic already in alerts_config.json -- no account, no key, the
phone app subscribes to the topic.

Every alert fires ONCE per symbol/level/session. A level that gets tapped
repeatedly must not produce twenty notifications, or you stop reading them --
the same reason Freshness.CLOSED exists.
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "alerts_config.json"


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def ntfy_topic() -> str | None:
    try:
        return json.loads(CONFIG.read_text()).get("ntfy_topic")
    except Exception:
        return None


def push(title: str, message: str, priority: str = "default",
         tags: str = "chart_with_upwards_trend", url: str | None = None) -> bool:
    topic = ntfy_topic()
    if not topic:
        return False
    try:
        headers = {"Title": title, "Priority": priority, "Tags": tags}
        # ntfy renders this as a tappable action, so a news alert opens the
        # actual story instead of leaving you to go hunt for it.
        if url:
            headers["Click"] = url
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8, context=_ctx()):
            return True
    except Exception:
        return False


@dataclass
class LevelWatch:
    symbol: str
    label: str          # PDH / PDL / Pivot / TC / BC ...
    price: float
    direction: str      # "above" | "below"


@dataclass
class AlertEngine:
    """Fire once per (symbol, label, day). Reset happens naturally on date change."""
    watches: list[LevelWatch] = field(default_factory=list)
    _fired: set = field(default_factory=set)
    _day: date = field(default_factory=date.today)

    def set_watches(self, watches: list[LevelWatch]) -> None:
        self.watches = watches

    def _key(self, w: LevelWatch) -> tuple:
        return (w.symbol, w.label, w.direction, self._day)

    def check(self, symbol: str, price: float, freshness: str = "") -> list[dict]:
        if date.today() != self._day:          # new session, clean slate
            self._day = date.today()
            self._fired.clear()

        hits = []
        for w in self.watches:
            if w.symbol != symbol:
                continue
            k = self._key(w)
            if k in self._fired:
                continue
            crossed = (price >= w.price) if w.direction == "above" else (price <= w.price)
            if not crossed:
                continue
            self._fired.add(k)
            # Freshness travels with the alert. A cross seen on 16-minute-old
            # data already happened -- you are being told about history.
            stale_note = "" if freshness in ("realtime", "") else f"  [{freshness} data]"
            msg = (f"{symbol} {w.direction} {w.label} {w.price:,.2f}\n"
                   f"now {price:,.2f}{stale_note}")
            push(f"{symbol} → {w.label}", msg,
                 priority="high" if w.label in ("PDH", "PDL") else "default")
            hits.append({"symbol": symbol, "label": w.label, "level": w.price,
                         "price": price, "direction": w.direction,
                         "freshness": freshness})
        return hits
