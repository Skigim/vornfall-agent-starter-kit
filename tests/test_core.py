import io
import urllib.error

import pytest

from vfkit.config import Config
from vfkit.core import CHALLENGE, Watcher
from vfkit.logs import Logs


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeAPI:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, path, params=None, timeout=20):
        self.calls.append((path, dict(params or {})))
        if self.responses:
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return {"events": [], "cursor": (params or {}).get("since") or "e_0"}


class FakeWaker:
    def __init__(self, *results):
        self.results = list(results)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.results.pop(0) if self.results else (True, "exit 0", "SUMMARY: ok")


def ev(type_, importance="notable", **data):
    return {"type": type_, "importance": importance, "data": data}


def make(tmp_path, api, waker=None, probe=None, status=None, **cfg):
    config = Config(agent_dir=tmp_path, name="t", key_var="VF_TEST", lock_port=1, **cfg)
    sleeps = []
    clock = Clock()
    w = Watcher(config, api, waker or FakeWaker(), probe or (lambda: True),
                status or (lambda: {"rules_version": "abc"}), Logs(tmp_path),
                sleep=sleeps.append, clock=clock)
    w.state["cursor"] = "e_1"
    w.policy.last_wake = clock()
    w.next_rules_check = float("inf")
    w.next_loop_check = float("inf")
    return w, sleeps, clock


def log_text(tmp_path):
    return (tmp_path / "logs" / "watcher.log").read_text(encoding="utf-8")


def http_error(code, body):
    return urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(body))


def test_challenge_wakes_urgently(tmp_path):
    api = FakeAPI({"events": [ev("challenge.issued", "urgent", challenge={"id": "ch_1"})], "cursor": "e_2"})
    w, _, _ = make(tmp_path, api)
    w.step()
    assert CHALLENGE in w.waker.prompts[0]


def test_plan_completed_wakes_with_detail(tmp_path):
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"})
    w, _, _ = make(tmp_path, api)
    w.step()
    assert "plan.completed (plan_id=pl_1)" in w.waker.prompts[0]
    assert w.state["cursor"] == "e_2"


def test_agent_held_skips_batch(tmp_path):
    api = FakeAPI({"events": [ev("agent.held"), ev("plan.completed")], "cursor": "e_2"})
    w, sleeps, _ = make(tmp_path, api)
    w.step()
    assert w.waker.prompts == [] and sleeps == [60]


def test_quiet_then_routine(tmp_path):
    w, _, clock = make(tmp_path, FakeAPI())
    w.step()
    assert w.waker.prompts == []
    clock.t += 3601
    w.step()
    assert "routine check: an hour without a wake" in w.waker.prompts[0]


def test_failed_wake_pauses_until_probe_ok(tmp_path):
    probes = iter([False, True])
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"})
    w, sleeps, _ = make(tmp_path, api, waker=FakeWaker((False, "exit 1", "")), probe=lambda: next(probes))
    w.step()
    assert sleeps == [600, 1200]
    assert "model is usable again" in log_text(tmp_path)


def test_wake_writes_csv_row(tmp_path):
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_7")], "cursor": "e_2"})
    w, _, _ = make(tmp_path, api)
    w.step()
    rows = (tmp_path / "logs" / "wakes.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and ",pl_7,exit 0" in rows[1]


def test_challenge_after_wake_rewakes_once(tmp_path):
    challenge = {"events": [ev("challenge.issued", "urgent", challenge={"id": "ch_1"})], "cursor": "e_3"}
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"}, challenge, challenge)
    w, _, _ = make(tmp_path, api)
    w.step()
    assert len(w.waker.prompts) == 2


def test_failed_plan_during_wake_rewakes(tmp_path):
    failed = {"events": [ev("intent.failed", plan_id="pl_2", code="MISSING_ITEM"),
                         ev("plan.aborted", plan_id="pl_2", reason="intent_failed")], "cursor": "e_3"}
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"}, failed)
    w, _, _ = make(tmp_path, api)
    w.step()
    assert len(w.waker.prompts) == 2
    assert "failed straight away" in w.waker.prompts[1] and "MISSING_ITEM" in w.waker.prompts[1]


def test_long_loop_flagged_once(tmp_path):
    rep = ev("standing_order.repeated", "info", plan_id="pl_9", **{"pass": 50})
    api = FakeAPI({"events": [rep], "cursor": "e_5"}, {"events": [], "cursor": "e_5"},
                  {"events": [ev("standing_order.repeated", "info", plan_id="pl_9")], "cursor": "e_6"},
                  {"events": [], "cursor": "e_6"})
    w, _, _ = make(tmp_path, api)
    w.next_loop_check = 0
    w.step()
    w.next_loop_check = 0
    w.step()
    assert log_text(tmp_path).count("LONG LOOP: pl_9") == 1


def test_rules_check_flags_and_clears(tmp_path):
    (tmp_path / "intents.md").write_text("Generated from rules_version `abc` by x\n", encoding="utf-8")
    versions = iter([{"rules_version": "def"}, {"rules_version": "abc"}])
    w, _, _ = make(tmp_path, FakeAPI(), status=lambda: next(versions))
    w.check_rules()
    assert (tmp_path / "reference-stale.flag").exists()
    assert "REFERENCE STALE" in log_text(tmp_path)
    w.check_rules()
    assert not (tmp_path / "reference-stale.flag").exists()


def test_not_spawned_wakes_to_spawn(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI(http_error(409, b'{"error":{"code":"NOT_SPAWNED"}}')))
    w.run_once()
    assert "not in the world yet" in w.waker.prompts[0]


def test_suspended_sleeps_half_an_hour(tmp_path):
    w, sleeps, _ = make(tmp_path, FakeAPI(http_error(403, b'{"error":{"code":"SUSPENDED"}}')))
    w.run_once()
    assert sleeps == [1800] and w.waker.prompts == []


def test_directed_orders_edit(tmp_path):
    import os
    (tmp_path / "orders.md").write_text("o", encoding="utf-8")
    (tmp_path / "goal.md").write_text("g", encoding="utf-8")
    w, _, clock = make(tmp_path, FakeAPI(), directed=True)
    os.utime(tmp_path / "orders.md", (clock.t + 10, clock.t + 10))
    w.step()
    assert "your owner updated your orders" in w.waker.prompts[0]
    assert "Mode: DIRECTED" in w.waker.prompts[0]
