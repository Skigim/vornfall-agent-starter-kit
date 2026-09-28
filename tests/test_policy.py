from vfkit.policy import WakePolicy


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_no_gap_admits_immediately():
    p = WakePolicy(clock=Clock())
    assert p.admit(["plan.completed"]) == (["plan.completed"], "")


def test_gap_holds_then_merges():
    clock = Clock()
    p = WakePolicy(min_gap_s=600, clock=clock)
    p.woke()
    clock.t += 60
    reasons, note = p.admit(["plan.completed"])
    assert reasons is None and note.startswith("holding wake until")
    assert not p.held_due()
    clock.t += 600
    assert p.held_due()
    assert p.admit(["intent.failed"]) == (["plan.completed", "intent.failed"], "")
    assert not p.held


def test_urgent_and_gap_false_bypass_gap():
    clock = Clock()
    p = WakePolicy(min_gap_s=600, clock=clock)
    p.woke()
    assert p.admit(["challenge"], urgent=True)[0] == ["challenge"]
    assert p.admit(["orders changed"], gap=False)[0] == ["orders changed"]


def test_challenge_cap():
    p = WakePolicy(clock=Clock())
    for _ in range(5):
        assert p.admit(["c"], urgent=True)[0] == ["c"]
    reasons, note = p.admit(["c"], urgent=True)
    assert reasons is None and "cap" in note


def test_hourly_cap():
    p = WakePolicy(max_per_hour=2, clock=Clock())
    assert p.admit(["a"])[0] and p.admit(["b"])[0]
    reasons, note = p.admit(["c"])
    assert reasons is None and "hourly wake cap" in note


def test_routine_due():
    clock = Clock()
    p = WakePolicy(clock=clock)
    p.woke()
    assert not p.routine_due(3600)
    clock.t += 3601
    assert p.routine_due(3600)
