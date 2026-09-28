from vfkit.events import (challenge_waiting, count_passes, ended_on_failure, failures,
                          has_hold, wake_reasons)


def ev(type_, importance="notable", **data):
    return {"type": type_, "importance": importance, "data": data}


def test_challenge_waiting_uses_latest_issue():
    assert challenge_waiting([ev("challenge.issued", challenge={"id": "ch_1"})])
    assert not challenge_waiting([ev("challenge.issued")])
    assert not challenge_waiting([ev("plan.completed")])


def test_has_hold():
    assert has_hold([ev("plan.completed"), ev("agent.held")])
    assert not has_hold([ev("plan.completed")])


def test_wake_reasons_with_detail_and_self_ends_skipped():
    events = [ev("plan.completed", plan_id="pl_1"),
              ev("intent.failed", plan_id="pl_2", code="MISSING_ITEM"),
              ev("plan.aborted", plan_id="pl_3", reason="replace"),
              ev("combat.attacked", importance="info"),
              ev("combat.attacked", importance="urgent"),
              ev("standing_order.repeated", importance="info", plan_id="pl_4")]
    assert wake_reasons(events) == ["plan.completed (plan_id=pl_1)",
                                    "intent.failed (plan_id=pl_2, code=MISSING_ITEM)",
                                    "combat.attacked"]


def test_failures_and_ended_on_failure():
    events = [ev("intent.failed", plan_id="pl_2", code="NO_TARGET"),
              ev("plan.aborted", plan_id="pl_2", reason="intent_failed")]
    assert failures(events) == ["intent.failed (plan_id=pl_2, code=NO_TARGET)",
                                "plan.aborted (plan_id=pl_2, reason=intent_failed)"]
    assert ended_on_failure(events)
    assert not ended_on_failure(events + [ev("plan.completed", plan_id="pl_3")])
    assert not ended_on_failure([ev("plan.aborted", plan_id="pl_2", reason="cancel")])


def test_count_passes():
    rep = lambda pid, **d: ev("standing_order.repeated", importance="info", plan_id=pid, **d)
    counts = count_passes([rep("pl_1"), rep("pl_1"), rep("pl_2", **{"pass": 40})], {})
    assert counts == {"pl_1": 2, "pl_2": 40}
    counts = count_passes([ev("standing_order.ended", plan_id="pl_1"), rep("pl_2")], counts)
    assert counts == {"pl_2": 41}
