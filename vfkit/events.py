"""What the game's events mean for waking the agent. Pure functions over event dicts."""

WAKE_EVENTS = frozenset({
    "plan.completed", "plan.aborted", "standing_order.ended", "intent.failed",
    "agent.camped", "combat.died", "pvp.died", "pvp.outlaw", "world.remade",
    "spawn.ready", "needs.starving",
})
WAKE_IF_URGENT = frozenset({"combat.attacked", "pvp.attacked", "intent.interrupted"})
SELF_ENDED = ("replace", "cancel")   # the agent ended it itself: nothing to decide
_ENDS = ("plan.completed", "plan.aborted", "standing_order.ended", "intent.failed")
_FAILS = ("intent.failed", "plan.aborted", "standing_order.ended")


def _data(e) -> dict:
    return e.get("data") or {}


def _detail(data) -> str:
    return ", ".join(f"{k}={data[k]}" for k in ("plan_id", "reason", "code") if k in data)


def challenge_waiting(events) -> bool:
    """A challenge.issued event carries its challenge only while it waits. Reading it from the
    events feed never starts the 120 s clock; reading the briefing would."""
    for e in reversed(events):
        if e.get("type") == "challenge.issued":
            return bool(_data(e).get("challenge"))
    return False


def has_hold(events) -> bool:
    return any(e.get("type") == "agent.held" for e in events)


def wake_reasons(events) -> list:
    out = []
    for e in events:
        t, d = e.get("type"), _data(e)
        if d.get("reason") in SELF_ENDED:
            continue
        urgent = str(e.get("importance", "")).startswith("urgent")
        if t in WAKE_EVENTS or (t in WAKE_IF_URGENT and urgent):
            detail = _detail(d)
            out.append(t + (f" ({detail})" if detail else ""))
    return out


def failures(events) -> list:
    return [f"{e.get('type')} ({_detail(_data(e))})" for e in events
            if e.get("type") in _FAILS and _data(e).get("reason") not in SELF_ENDED]


def ended_on_failure(events) -> bool:
    ends = [e for e in events if e.get("type") in _ENDS and _data(e).get("reason") not in SELF_ENDED]
    return bool(ends) and ends[-1].get("type") != "plan.completed"


def count_passes(events, counts) -> dict:
    counts = dict(counts)
    for e in events:
        t, d = e.get("type"), _data(e)
        pid = d.get("plan_id")
        if not pid:
            continue
        if t == "standing_order.repeated":
            reported = d.get("pass") if isinstance(d.get("pass"), int) else 0
            counts[pid] = max(counts.get(pid, 0) + 1, reported)
        elif t in ("standing_order.ended", "plan.aborted", "plan.completed"):
            counts.pop(pid, None)
    return counts
