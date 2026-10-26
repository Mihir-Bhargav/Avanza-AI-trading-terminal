"""
Trade plans and the discipline streak (`/api/plans`).

Records INTENT only. Nothing here talks to a broker, and nothing ever will:
a plan is a local JSON line saying "if I enter X, the target is T and the stop
is S". The point is the documented failure mode -- exits without a predefined
stop, profit left on the table with no target -- so a plan is only accepted
with BOTH, on the correct sides of the price, at a leverage inside the ATR cap.

Storage: data/plans.json (gitignored). Written atomically under a lock.

Streak definition (kept deliberately simple):
    Walk plans newest -> oldest. The streak counts consecutive plans while the
    gap between one plan and the next-older one is <= STREAK_GAP_DAYS. It is 0
    if the newest plan is itself older than STREAK_GAP_DAYS. Every stored plan
    passed validation, so every stored plan is a "valid" one.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "plans.json"
STREAK_GAP_DAYS = 14


class PlanError(ValueError):
    """Validation failure; message is shown to the user as-is."""


# Yahoo/terminal tickers: MU, ERIC-B.ST, ^OMX, USDSEK=X, GC=F.
SYMBOL_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9 .\-=^_&]{0,31}$")


def check_symbol(symbol: str) -> str:
    """Return the stripped symbol or raise PlanError (bounded, ticker charset)."""
    s = str(symbol or "").strip()
    if not s:
        raise PlanError("symbol is required")
    if not SYMBOL_RE.match(s):
        raise PlanError("symbol must be a ticker (letters, digits, space, . - = ^ _ &; max 32)")
    return s


def _pos_float(payload: dict, key: str) -> float:
    v = payload.get(key)
    if isinstance(v, bool):
        raise PlanError(f"{key} must be a number")
    if v is None or v == "":
        raise PlanError(f"{key} is required")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise PlanError(f"{key} must be a number") from None
    if not f > 0 or f != f or f == float("inf"):
        raise PlanError(f"{key} must be a positive number")
    return f


def validate(payload: dict, price: float | None, lev_cap: float | None) -> dict:
    """Return the cleaned plan fields, or raise PlanError with the reason."""
    if not isinstance(payload, dict):
        raise PlanError("body must be a JSON object")
    symbol = check_symbol(payload.get("symbol"))
    side = str(payload.get("side") or "").strip().lower()
    if side not in ("long", "short"):
        raise PlanError("side must be 'long' or 'short'")
    tp = _pos_float(payload, "take_profit")
    sl = _pos_float(payload, "stop_loss")
    lev = _pos_float(payload, "leverage")

    if side == "long" and not sl < tp:
        raise PlanError("long plan: stop_loss must be below take_profit")
    if side == "short" and not tp < sl:
        raise PlanError("short plan: take_profit must be below stop_loss")
    if price is not None:
        if side == "long" and not (sl < price < tp):
            raise PlanError(f"long plan: need stop_loss < price < take_profit; "
                            f"price is {price:g}")
        if side == "short" and not (tp < price < sl):
            raise PlanError(f"short plan: need take_profit < price < stop_loss; "
                            f"price is {price:g}")
    if lev_cap is not None and lev > lev_cap:
        raise PlanError(f"leverage {lev:g}x exceeds the ATR cap of {lev_cap:g}x "
                        f"for {symbol} (100 / (3.5 x ATR%))")
    note = payload.get("note")
    return {"symbol": symbol.upper(), "side": side, "take_profit": tp,
            "stop_loss": sl, "leverage": lev,
            "note": str(note)[:500] if note else None,
            "price_at_plan": price, "lev_cap": lev_cap}


def _ts(p: dict) -> datetime:
    return datetime.fromisoformat(p["created_at"])


def streak(plans: list[dict], now: datetime | None = None,
           gap_days: int = STREAK_GAP_DAYS) -> int:
    if not plans:
        return 0
    now = now or datetime.now(timezone.utc)
    ordered = sorted(plans, key=_ts, reverse=True)
    gap = timedelta(days=gap_days)
    if now - _ts(ordered[0]) > gap:
        return 0
    n = 1
    for newer, older in zip(ordered, ordered[1:]):
        if _ts(newer) - _ts(older) > gap:
            break
        n += 1
    return n


class PlanStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text())   # corrupt file raises: not hidden
        if not isinstance(data, list):
            raise ValueError(f"{self.path.name} is not a JSON list")
        return data

    def all(self) -> list[dict]:
        with self._lock:
            return sorted(self._read(), key=_ts, reverse=True)

    def add(self, clean: dict, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        plan = {"id": uuid.uuid4().hex[:12],
                "created_at": now.isoformat(timespec="seconds"), **clean}
        with self._lock:
            plans = self._read()
            plans.append(plan)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(plans, indent=1))
            tmp.replace(self.path)
        return plan

    def logged_today(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return any(_ts(p).date() == now.date() for p in self.all())
