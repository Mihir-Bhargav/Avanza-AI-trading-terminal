"""
Kes, the kestrel agent -- deterministic cockpit briefing (`/api/kes/briefing`).

No LLM here. The briefing is composed in code from the setups rows so every
number in it is one the panel also shows. Voice rules (from the approved design):
short sentences, dry, never hype; numbers carry context; says "I don't know"
when data is missing; explains and checks, never orders -- no "buy"/"sell".

Mood:
  cautious  a with-trend setup has earnings within EARNINGS_WARN_DAYS
  alert     a zone was crossed with the trend, or setup data failed to load
  pleased   nothing alerting, and a plan with TP+SL was logged today
  watching  default
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

EARNINGS_WARN_DAYS = 7
THIN_HISTORY_N = 10

_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
          "Nine", "Ten"]


def _count(n: int) -> str:
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def _href(symbol: str) -> str:
    return f"/terminal/chart/{quote(symbol, safe='')}"


def _zone_phrase(r: dict) -> str:
    if r["state"] in ("crossed_z1_up", "at_z1"):
        d, z = r["dist_z1_atr"], "zone 1"
    else:
        d, z = r["dist_z3_atr"], "zone 3"
    if r["state"].startswith("crossed"):
        return f"{abs(d):.2f} ATR through {z}"
    return f"at {z}, {abs(d):.2f} ATR away"


def _history_phrase(r: dict) -> str | None:
    up = r["state"] in ("crossed_z1_up", "at_z1")
    h = r["hist"]["z1_up" if up else "z3_dn"]
    n = h.get("n") or 0
    if n == 0:
        return "No comparable crosses in two years of history."
    if n < THIN_HISTORY_N:
        return f"History is thin: n={n}."
    wr, avg = h.get("win_rate"), h.get("avg_fwd_ret")
    if wr is None:
        return None
    direction = "higher" if up else "lower"
    s = f"History: n={n}, {wr * 100:.0f}% closed {direction} three days later"
    if avg is not None:
        s += f", average move {avg * 100:+.1f}%"
    return s + "."


def _earnings_soon(r: dict) -> bool:
    d = r.get("earnings_days")
    return d is not None and 0 <= d <= EARNINGS_WARN_DAYS


def _days(d: int) -> str:
    return "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")


def compose_briefing(rows: list[dict], errors: list[dict] | None = None,
                     plan_today: bool = False, as_of: str | None = None,
                     today: str | None = None) -> dict:
    errors = errors or []
    today = today or datetime.now().date().isoformat()
    as_of = as_of or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not rows:
        why = f" {len(errors)} symbols failed to load." if errors else ""
        return {"mood": "alert", "as_of": as_of, "links": [],
                "text": f"No setup data.{why} I don't know where anything is right now."}

    crossed = [r for r in rows if r["with_trend"] and r["state"].startswith("crossed")]
    at = [r for r in rows if r["with_trend"] and r["state"].startswith("at_")]
    focus = (crossed or at or [None])[0]
    live = crossed + at
    earn = [r for r in live if _earnings_soon(r)]

    parts: list[str] = []
    links: list[dict] = []
    if crossed:
        noun = "setup" if len(crossed) == 1 else "setups"
        parts.append(f"{_count(len(crossed))} {noun} crossed with the trend.")
    else:
        parts.append("Nothing crossed with the trend.")
    if at:
        parts.append(f"{_count(len(at))} sitting at a zone.")

    if focus is not None:
        lead = "is the interesting one" if len(live) > 1 else "is the one"
        when = ""
        if focus.get("bar_date") and focus["bar_date"] < today:
            # US names before their open are still on yesterday's bar. Say so.
            when = f" as of the {focus['bar_date']} close"
        parts.append(f"{focus['symbol']} {lead}, {_zone_phrase(focus)}{when}, "
                     f"trend {focus['trend']}.")
        hist = _history_phrase(focus)
        if hist:
            parts.append(hist)
        if _earnings_soon(focus):
            parts.append(f"Earnings land {_days(focus['earnings_days'])}, "
                         "so size for the print or leave it.")
        if focus.get("lev_cap") is not None:
            parts.append(f"Leverage cap there is {focus['lev_cap']:.1f}x.")
        links.append({"label": f"Show {focus['symbol']}", "href": _href(focus["symbol"])})
    else:
        near = rows[0]
        d = min(abs(near["dist_z1_atr"] or 0), abs(near["dist_z3_atr"] or 0))
        z = "zone 1" if abs(near["dist_z1_atr"] or 0) <= abs(near["dist_z3_atr"] or 0) else "zone 3"
        parts.append(f"{len(rows)} names watched. Closest is {near['symbol']}, "
                     f"{d:.2f} ATR from {z}.")
        links.append({"label": f"Show {near['symbol']}", "href": _href(near["symbol"])})

    for r in earn:
        if r is not focus:
            parts.append(f"{r['symbol']} reports {_days(r['earnings_days'])}.")
            links.append({"label": f"Show {r['symbol']}", "href": _href(r["symbol"])})

    if errors:
        names = ", ".join(e["symbol"] for e in errors[:3])
        more = "" if len(errors) <= 3 else f" and {len(errors) - 3} more"
        parts.append(f"No data for {names}{more}. Missing, not quiet.")

    if earn:
        mood = "cautious"
    elif crossed or errors:
        mood = "alert"
    elif plan_today:
        mood = "pleased"
        parts.append("Plan logged with a target and a stop. That is the habit that pays.")
    else:
        mood = "watching"
    return {"mood": mood, "text": " ".join(parts), "links": links, "as_of": as_of}
