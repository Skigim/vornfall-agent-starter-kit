"""Wake conditions an agent declares on the WAKE ON line of its notebook: parse them, test them
against the game's events, the tick and its state. Pure functions; the watcher owns the state."""
import re
from dataclasses import dataclass

MAX_CONDITIONS = 5
EVENT_KINDS = ("level", "at", "event")   # matched against the event feed, which is `info` importance
STATE_KINDS = ("coins", "hp", "bank")    # need a read of the agent's state

_LINE = re.compile(r"^[ \t]*WAKE ON:[ \t]*(.*)$", re.M)
_NAME = r"[a-z][a-z_]*"
_PATTERNS = (
    ("time", re.compile(r"t>=(\d+)$")),
    ("coins", re.compile(r"coins>=(\d+)$")),
    ("hp", re.compile(r"hp<=(\d+)$")),
    ("bank", re.compile(rf"bank:({_NAME})>=(\d+)$")),
    ("at", re.compile(r"at=([A-Za-z0-9_]+)$")),
    ("event", re.compile(rf"event=({_NAME}\.{_NAME})$")),
    ("level", re.compile(rf"({_NAME})>=(\d+)$")),
)


@dataclass(frozen=True)
class Condition:
    text: str
    kind: str
    name: str = ""     # the skill, item, town id or event type
    value: int = 0


def extract_line(notebook):
    """The text after `WAKE ON:` in a notebook response of any shape (a string, or JSON holding
    the notebook text somewhere), or None."""
    if isinstance(notebook, str):
        m = _LINE.search(notebook)
        return m.group(1) if m else None
    if isinstance(notebook, dict):
        notebook = list(notebook.values())
    if isinstance(notebook, list):
        for item in notebook:
            found = extract_line(item)
            if found is not None:
                return found
    return None


def _parse_one(text):
    compact = text.replace(" ", "")
    for kind, pattern in _PATTERNS:
        m = pattern.match(compact)
        if not m:
            continue
        g = m.groups()
        if kind == "level":
            return Condition(text, kind, g[0], int(g[1]))
        if kind == "bank":
            return Condition(text, kind, g[0], int(g[1]))
        if kind in ("at", "event"):
            return Condition(text, kind, g[0])
        return Condition(text, kind, "", int(g[0]))
    return None


def parse_conditions(line):
    """(conditions, problems): problems are (text, reason) for what was dropped."""
    conditions, problems, seen = [], [], set()
    for part in (line or "").split(";"):
        text = part.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cond = _parse_one(text)
        if cond is None:
            problems.append((text, "not a condition this watcher knows"))
        elif len(conditions) >= MAX_CONDITIONS:
            problems.append((text, f"more than {MAX_CONDITIONS} conditions"))
        else:
            conditions.append(cond)
    return conditions, problems


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fired_by_events(conditions, events):
    """The conditions some event satisfies. Events are read once, so a condition only counts events
    that arrive after the line was read."""
    hit = []
    for c in conditions:
        if c.kind not in EVENT_KINDS:
            continue
        for e in events:
            t, d = e.get("type"), e.get("data") or {}
            if ((c.kind == "level" and t == "skill.level_up" and d.get("skill") == c.name
                 and (_int(d.get("level")) or 0) >= c.value)
                    or (c.kind == "at" and t == "zone.entered" and str(d.get("town")) == c.name)
                    or (c.kind == "event" and t == c.name)):
                hit.append(c)
                break
    return hit


def time_due(condition, tick):
    return condition.kind == "time" and tick is not None and tick >= condition.value


def state_met(condition, state):
    """True or False, or None when the state does not say (the condition is unreadable)."""
    if condition.kind == "coins":
        have = state.get("coins")
        return None if have is None else have >= condition.value
    if condition.kind == "hp":
        have = state.get("hp")
        return None if have is None else have <= condition.value
    if condition.kind == "bank":
        bank = state.get("bank")
        return None if bank is None else bank.get(condition.name, 0) >= condition.value
    return None


def extract_state(me, bank):
    """Normalise GET /v1/me and GET /v1/bank to {"coins", "hp", "bank": {item: count}}, leaving out
    whatever a response does not carry. Coins are the purse plus the bank; hp is the current value
    of the [current, max] pair."""
    state = {}
    purse, banked = _int((me or {}).get("purse")), _int((bank or {}).get("coins"))
    if purse is not None and banked is not None:
        state["coins"] = purse + banked
    hp = ((me or {}).get("combat") or {}).get("hp")
    if isinstance(hp, list) and hp and _int(hp[0]) is not None:
        state["hp"] = _int(hp[0])
    items = (bank or {}).get("items")
    if isinstance(items, dict):
        state["bank"] = {k: v for k, v in items.items() if isinstance(v, int)}
    return state
