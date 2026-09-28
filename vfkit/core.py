"""The watcher's decision loop: sleep on the game's events, wake the agent only when there is
something to decide, and tell it why. It never chooses actions, answers challenges or writes."""
import json
import time
import urllib.error

from .directed import Directed
from .events import challenge_waiting, count_passes, ended_on_failure, failures, has_hold, wake_reasons
from .policy import WakePolicy
from .reference import reference_stamp

WAIT_S = 50
MODEL_DOWN_FIRST_S = 10 * 60
MODEL_DOWN_MAX_S = 60 * 60
LOOP_CHECK_S = 10 * 60
CHALLENGE = "challenge.issued: a proof-of-mind challenge is waiting (120 s)"
BASE_PROMPT = (
    "Wake. Play one turn as described under \"On each wake\" in your instructions.\n"
    "End with a single line starting \"SUMMARY:\" saying what you saw and did (never include your key).\n"
)


def _human(seconds) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "an hour" if hours == 1 else f"{hours} hours"
    return f"{round(seconds / 60)} minutes"


class Watcher:
    def __init__(self, cfg, api, waker, probe, status, logs, sleep=time.sleep, clock=time.time):
        self.cfg, self.api, self.waker, self.probe, self.status = cfg, api, waker, probe, status
        self.logs, self.sleep, self.clock = logs, sleep, clock
        self.state_file = cfg.agent_dir / "watcher-state.json"
        self.state = self._load()
        self.policy = WakePolicy(cfg.min_wake_gap_s, clock=clock)
        self.policy.last_wake = self.state.get("last_wake", 0.0)
        self.directed = Directed(cfg, self.state, clock) if cfg.directed else None
        self.was_driving = False
        self.fail_rewakes = 0
        self.backoff = 5
        self.next_rules_check = 0.0
        self.next_loop_check = 0.0

    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self):
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")

    def do_wake(self, reasons, urgent=False, retry=True, gap=True) -> bool:
        if not urgent and self.directed and self.directed.driving():
            if not self.was_driving:
                self.logs.log("owner is driving live; ordinary wakes paused")
                self.was_driving = True
            return False
        if self.was_driving:
            self.logs.log("owner stopped driving; wakes resume")
            self.was_driving = False
        pre_cursor = self.state.get("cursor")
        reasons, note = self.policy.admit(reasons, urgent=urgent, gap=gap)
        if note:
            self.logs.log(note)
        if reasons is None:
            return False
        started = self.clock()
        gap_s = started - self.policy.last_wake if self.policy.last_wake else None
        mode = self.directed.mode_line() if self.directed else ""
        prompt = BASE_PROMPT + mode + "The watcher woke you because: " + "; ".join(reasons) + "\n"
        ok, status, out = self.waker(prompt)
        duration = self.clock() - started
        self.logs.wake_output(started, reasons, out)
        self.logs.log(f"wake done ({status}, {duration:.0f}s): {'; '.join(reasons)}")
        self.logs.wake_row(started, duration, gap_s, reasons, status)
        self.policy.woke()
        self.state["last_wake"] = self.policy.last_wake
        self.save()
        if not ok:
            self.model_down()
            return False
        r = self.api("/events/wait", {"since": pre_cursor, "min_importance": "notable", "timeout_s": 1},
                     timeout=30) if pre_cursor else {}
        during = r.get("events") or []
        if r.get("cursor"):
            self.state["cursor"] = r["cursor"]
            self.save()
        if challenge_waiting(during) and retry:
            self.logs.log("a challenge is still waiting after the wake; waking once more")
            return self.do_wake([CHALLENGE], urgent=True, retry=False)
        failed = failures(during)
        if failed and ended_on_failure(during) and self.fail_rewakes < 2:
            self.fail_rewakes += 1
            self.logs.log(f"plan failed during the agent's turn; re-waking ({self.fail_rewakes}/2)")
            return self.do_wake(["the plan you sent failed straight away: " + "; ".join(failed[-3:])], gap=False)
        self.fail_rewakes = 0
        return True

    def model_down(self):
        wait = MODEL_DOWN_FIRST_S
        self.logs.log(f"wake failed: runtime unavailable? pausing all game calls, checking again in {wait // 60} min")
        while True:
            self.sleep(wait)
            if self.probe():
                self.logs.log("model is usable again; resuming")
                return
            wait = min(wait * 2, MODEL_DOWN_MAX_S)
            self.logs.log(f"runtime still unavailable; checking again in {wait // 60} min")

    def check_rules(self):
        try:
            version = (self.status() or {}).get("rules_version")
        except Exception as e:
            self.logs.log(f"rules check failed: {type(e).__name__}: {e}")
            return
        stamp = reference_stamp(self.cfg.agent_dir)
        flag = self.cfg.agent_dir / "reference-stale.flag"
        if version and version != stamp:
            if not flag.exists():
                self.logs.log(f"REFERENCE STALE: rules_version is {version}, intents.md was generated "
                              f"from {stamp}; run refresh-reference.py")
                flag.write_text(f"{version}\n", encoding="utf-8")
        elif flag.exists():
            flag.unlink()

    def check_loops(self):
        since = self.state.get("info_cursor") or self.state.get("cursor")
        r = self.api("/events/wait", {"since": since, "min_importance": "info", "timeout_s": 1}, timeout=30)
        self.state["info_cursor"] = r.get("cursor") or since
        passes = count_passes(r.get("events") or [], self.state.get("passes", {}))
        flagged = [p for p in self.state.get("loops_flagged", []) if p in passes]
        for plan, n in passes.items():
            if n >= self.cfg.long_loop_passes and plan not in flagged:
                self.logs.log(f"LONG LOOP: {plan} at pass {n}")
                flagged.append(plan)
        self.state["passes"] = passes
        self.state["loops_flagged"] = flagged
        self.save()

    def step(self):
        now = self.clock()
        if now >= self.next_rules_check:
            self.next_rules_check = now + self.cfg.rules_check_s
            self.check_rules()
        if not self.state.get("cursor"):
            r = self.api("/events/wait", {"min_importance": "notable", "timeout_s": 1}, timeout=30)
            self.state["cursor"] = r.get("cursor")
            self.save()
            if not self.state["cursor"]:
                self.logs.log("events feed gave no cursor; retrying in 60 s")
                self.sleep(60)
            elif challenge_waiting(r.get("events") or []):
                self.do_wake([CHALLENGE], urgent=True)
            return
        if self.directed:
            change = self.directed.change()
            if change:
                self.save()
                self.do_wake(change[0], gap=change[1])
                return
        if now >= self.next_loop_check:
            self.next_loop_check = now + LOOP_CHECK_S
            self.check_loops()
        r = self.api("/events/wait", {"since": self.state["cursor"], "min_importance": "notable",
                                      "timeout_s": WAIT_S}, timeout=WAIT_S + 20)
        self.backoff = 5
        events = r.get("events") or []
        self.state["cursor"] = r.get("cursor") or self.state["cursor"]
        self.save()
        if r.get("gap"):
            self.logs.log("event gap reported; some events were missed")
        if has_hold(events):
            # A backlog can hold an old agent.held (a lifted suspension): skip this batch only. A
            # hold still in force shows on the next call as a 403.
            self.logs.log("agent.held in this batch; skipping it and checking again")
            self.sleep(60)
            return
        if challenge_waiting(events):
            self.do_wake([CHALLENGE], urgent=True)
            return
        reasons = wake_reasons(events)
        if reasons:
            self.do_wake(reasons)
        elif self.policy.held_due():
            self.do_wake([])
        elif self.policy.routine_due(self.cfg.routine_wake_s):
            self.do_wake([f"routine check: {_human(self.cfg.routine_wake_s)} without a wake"])

    def handle_http(self, e):
        try:
            body = e.read() or b""
        except Exception:
            body = b""
        if e.code == 401:
            self.logs.log("401 unauthenticated: key missing, invalid or rotated; retrying in 5 min")
            self.sleep(300)
        elif e.code == 429:
            self.logs.log("429 rate limited; backing off 60 s")
            self.sleep(60)
        elif e.code == 409 and b"NOT_SPAWNED" in body:
            if self.clock() - self.state.get("spawn_wake", 0) >= 15 * 60:
                self.state["spawn_wake"] = self.clock()
                self.save()
                self.logs.log("not spawned yet; waking the agent to spawn")
                try:
                    self.do_wake(["you are registered but not in the world yet: spawn when you are "
                                  "ready (see your first-wake routine)"])
                except Exception as e2:
                    self.logs.log(f"after spawn wake: {type(e2).__name__}: {e2}")
            else:
                self.sleep(60)
        elif e.code == 403 and b"SUSPENDED" in body:
            self.logs.log("403 SUSPENDED: suspended pending a moderator's review; checking again in 30 min")
            self.sleep(30 * 60)
        else:
            self.logs.log(f"HTTP {e.code}; backing off {self.backoff}s")
            self.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 300)

    def run_once(self):
        try:
            self.step()
        except urllib.error.HTTPError as e:
            self.handle_http(e)
        except Exception as e:
            self.logs.log(f"{type(e).__name__}: {e}; backing off {self.backoff}s")
            self.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 300)

    def run(self):
        self.logs.log("watcher started")
        while True:
            self.run_once()
