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
    cfg.setdefault("wake_conditions", False)   # the tests that want it switch it on
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


class Routed:
    """An API that answers by path: the notebook, the events feed, and whatever else is asked."""

    def __init__(self, notebook="", batches=()):
        self.notebook = notebook
        self.batches = list(batches)
        self.calls = []

    def __call__(self, path, params=None, timeout=20):
        self.calls.append((path, dict(params or {})))
        if path == "/me/notebook":
            if isinstance(self.notebook, Exception):
                raise self.notebook
            return {"notebook": self.notebook}
        if path == "/events/wait":
            if self.batches:
                return self.batches.pop(0)
            return {"events": [], "cursor": (params or {}).get("since") or "e_0"}
        return {}

    def polls(self):
        return [p for path, p in self.calls if path == "/events/wait"]


def conditions_watcher(tmp_path, api, notebook_line, **kw):
    api.notebook = f"== NOW ==\nWAKE ON: {notebook_line}\n"
    w, sleeps, clock = make(tmp_path, api, wake_conditions=True, **kw)
    w.refresh_wake_on()
    return w, sleeps, clock


def test_wake_on_line_is_read_parsed_and_logged(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500; nonsense; mining>=40")
    assert [c.text for c in w.conditions] == ["t>=500", "mining>=40"]
    text = log_text(tmp_path)
    assert "WAKE ON: t>=500; mining>=40" in text
    assert "WAKE ON ignored: nonsense: not a condition this watcher knows" in text


def test_nothing_is_read_when_conditions_are_off(tmp_path):
    api = Routed(notebook="WAKE ON: t>=1")
    w, _, _ = make(tmp_path, api)
    w.refresh_wake_on()
    assert api.calls == [] and w.conditions == []


def test_unreadable_notebook_keeps_what_was_there(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500")
    api.notebook = http_error(500, b"")
    w.refresh_wake_on()
    assert [c.text for c in w.conditions] == ["t>=500"]
    assert "notebook not readable" in log_text(tmp_path)


def test_time_condition_fires_once_and_wakes_with_its_text(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500", status=lambda: {"tick": 600})
    w.step()
    assert "your condition fired: t>=500" in w.waker.prompts[0]
    w.policy.last_wake = w.clock()
    w.step()
    assert len(w.waker.prompts) == 1


def test_time_condition_waits_for_its_tick(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500", status=lambda: {"tick": 499})
    w.step()
    assert w.waker.prompts == []


def test_spent_condition_rearms_after_it_leaves_the_notebook(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500", status=lambda: {"tick": 600})
    w.step()
    assert w.wake_on()["spent"] == ["t>=500"]
    w.refresh_wake_on()                        # still written, still spent
    assert w.live_conditions() == []
    api.notebook = "== NOW ==\nDOUBTS: none\n"
    w.refresh_wake_on()                        # gone for one read
    api.notebook = "WAKE ON: t>=500"
    w.refresh_wake_on()                        # written again
    assert [c.text for c in w.live_conditions()] == ["t>=500"]


def test_level_condition_polls_info_and_fires(tmp_path):
    lvl = {"events": [ev("skill.level_up", "info", skill="mining", level=40)], "cursor": "e_2"}
    api = Routed(batches=[lvl])
    w, _, _ = conditions_watcher(tmp_path, api, "mining>=40")
    w.step()
    assert api.polls()[0]["min_importance"] == "info"
    assert "your condition fired: mining>=40" in w.waker.prompts[0]


def test_info_poll_pauses_when_nothing_happens(tmp_path):
    api = Routed()
    w, sleeps, _ = conditions_watcher(tmp_path, api, "event=party.invited")
    w.step()
    assert w.waker.prompts == [] and sleeps == [5]


def test_polls_notable_when_only_a_time_condition_is_declared(tmp_path):
    api = Routed()
    w, sleeps, _ = conditions_watcher(tmp_path, api, "t>=500", status=lambda: {"tick": 1})
    w.step()
    assert api.polls()[0]["min_importance"] == "notable" and sleeps == []


def state_routes(api, purse=10, banked=20, hp=(10, 10), items=None):
    base = api.__call__

    def routed(path, params=None, timeout=20):
        if path == "/me":
            return {"purse": purse, "combat": {"hp": list(hp)}}
        if path == "/bank":
            return {"coins": banked, "items": items if items is not None else {"tin_ore": 7}}
        return base(path, params, timeout)
    return routed


def test_coins_condition_fires_on_purse_plus_bank(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "coins>=30")
    w.api = state_routes(api, purse=10, banked=20)
    w.step()
    assert "your condition fired: coins>=30" in w.waker.prompts[0]


def test_hp_and_stored_item_conditions(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "hp<=3; bank:tin_ore>=5; bank:iron_ore>=1")
    w.api = state_routes(api, hp=(2, 10))
    w.step()
    prompt = w.waker.prompts[0]
    assert "hp<=3" in prompt and "bank:tin_ore>=5" in prompt and "bank:iron_ore>=1" not in prompt


def test_state_is_read_at_most_every_two_minutes(tmp_path):
    api = Routed()
    w, _, clock = conditions_watcher(tmp_path, api, "coins>=999")
    reads = []
    inner = state_routes(api)
    w.api = lambda path, params=None, timeout=20: (reads.append(path) if path == "/me" else None) or inner(path, params, timeout)
    w.step()
    w.step()
    assert reads == ["/me"]
    clock.t += 121
    w.step()
    assert reads == ["/me", "/me"]


def test_state_the_game_does_not_report_is_logged_not_fired(tmp_path):
    api = Routed()
    w, _, _ = conditions_watcher(tmp_path, api, "coins>=1")
    w.step()                                  # Routed answers /me and /bank with {}
    assert w.waker.prompts == []
    assert "WAKE ON unreadable: coins>=1" in log_text(tmp_path)


def test_a_wake_rereads_the_notebook(tmp_path):
    api = Routed(batches=[{"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"}])
    w, _, _ = conditions_watcher(tmp_path, api, "t>=500")
    api.notebook = "WAKE ON: t>=900"
    w.step()
    assert [c.text for c in w.conditions] == ["t>=900"]


def test_condition_met_in_a_challenge_batch_is_not_lost(tmp_path):
    batch = {"events": [ev("skill.level_up", "info", skill="mining", level=40),
                        ev("challenge.issued", "urgent", challenge={"id": "ch_1"})], "cursor": "e_2"}
    api = Routed(batches=[batch])
    w, _, _ = conditions_watcher(tmp_path, api, "mining>=40")
    w.step()
    assert CHALLENGE in w.waker.prompts[0] and "your condition fired: mining>=40" in w.waker.prompts[0]


def test_game_tick_is_read_at_most_every_thirty_seconds(tmp_path):
    ticks = []
    api = Routed()
    w, _, clock = conditions_watcher(tmp_path, api, "t>=500",
                                     status=lambda: ticks.append(1) or {"tick": 1})
    w.step()
    w.step()
    assert len(ticks) == 1
    clock.t += 31
    w.step()
    assert len(ticks) == 2


def test_usage_limit_sleeps_until_the_reset_time(tmp_path):
    from datetime import datetime
    now = datetime(2026, 9, 30, 14, 50).astimezone().timestamp()
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"})
    waker = FakeWaker((False, "exit 1", "You've hit your session limit · resets 4:50pm"))
    w, sleeps, clock = make(tmp_path, api, waker=waker, probe=lambda: True)
    clock.t = now
    w.policy.last_wake = now
    w.step()
    assert sleeps == [2 * 3600 + 60]
    assert "usage limit; it resets in about 121 min" in log_text(tmp_path)


def test_unreadable_failure_keeps_the_backoff(tmp_path):
    probes = iter([False, True])
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"})
    w, sleeps, _ = make(tmp_path, api, waker=FakeWaker((False, "exit 1", "boom")),
                        probe=lambda: next(probes))
    w.step()
    assert sleeps == [600, 1200]


def test_still_limited_after_the_reset_falls_back_to_the_backoff(tmp_path):
    from datetime import datetime
    now = datetime(2026, 9, 30, 14, 50).astimezone().timestamp()
    probes = iter([False, True])
    api = FakeAPI({"events": [ev("plan.completed", plan_id="pl_1")], "cursor": "e_2"})
    waker = FakeWaker((False, "exit 1", "limit resets 4:50pm"))
    w, sleeps, clock = make(tmp_path, api, waker=waker, probe=lambda: next(probes))
    clock.t = now
    w.policy.last_wake = now
    w.step()
    assert sleeps == [2 * 3600 + 60, 1200]
