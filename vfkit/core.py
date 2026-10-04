"""The watcher's decision loop: sleep on the game's events, wake the agent only when there is
something to decide, and tell it why. It never chooses actions, answers challenges or writes."""
import json
import math
import re
import time
import urllib.error

from .directed import Directed
from .limits import seconds_until_reset
from .events import challenge_waiting, count_passes, ended_on_failure, failures, has_hold, wake_reasons
from .policy import WakePolicy
from .reference import STAMP_RE, reference_stamp
from .runtime import load_profile
from .storage import atomic_write
from .wakeon import (EVENT_KINDS, STATE_KINDS, extract_line, extract_state,
                     fired_by_events, parse_conditions, state_met, time_due)

WAIT_S = 50
MODEL_DOWN_FIRST_S = 10 * 60
MODEL_DOWN_MAX_S = 60 * 60
LOOP_CHECK_S = 10 * 60
STATE_CHECK_S = 120
TICK_CHECK_S = 30
INFO_POLL_PAUSE_S = 5
CHALLENGE = "challenge.issued: a proof-of-mind challenge is waiting (120 s)"
RECONCILE = "reconcile: read a fresh briefing and current action before deciding; an earlier action may already have succeeded"


class CompetingWatcher(RuntimeError):
    """Another long-poller owns this key; stop rather than fight over its events."""


BASE_PROMPT = (
    "Wake. Play one turn as described under \"On each wake\" in your instructions.\n"
    "Write one SUMMARY: line saying what you saw and did (never include your key).\n"
    "Only after completing the required game calls, answering any challenge and saving your notebook "
    "when available (a confirmed spawn queue is also a completed turn), "
    "end with VORNFALL_TURN_COMPLETE on its own line. If tools or credentials fail, do not emit it.\n"
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
        self.policy.restore(self.state.get("policy", {"last_wake": self.state.get("last_wake", 0.0)}))
        self.directed = Directed(cfg, self.state, clock) if cfg.directed else None
        self.was_driving = False
        self.fail_rewakes = 0
        self.backoff = 5
        self.next_rules_check = 0.0
        self.next_loop_check = 0.0
        self.next_state_check = 0.0
        self.next_tick_check = 0.0
        self.conditions = parse_conditions(" ; ".join(self.wake_on()["texts"]))[0]
        self.logged = set()

    def wake_on(self) -> dict:
        return self.state.setdefault("wake_on", {"texts": [], "spent": []})

    def _load(self) -> dict:
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("state must be an object")
            if not isinstance(state.get("pending", {}), dict):
                raise ValueError("pending must be an object")
            if any(not isinstance(k, str) or v not in (0, 1, 2) for k, v in state.get("pending", {}).items()):
                raise ValueError("invalid pending decisions")
            wake = state.get("wake_on", {"texts": [], "spent": []})
            if not isinstance(wake, dict) or any(not isinstance(wake.get(k), list) or
                    any(not isinstance(v, str) for v in wake[k]) for k in ("texts", "spent")):
                raise ValueError("invalid wake conditions")
            policy = state.get("policy", {})
            if not isinstance(policy, dict):
                raise ValueError("invalid policy")
            for value in (state.get("last_wake", 0), state.get("spawn_wake", 0), policy.get("last_wake", 0)):
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("invalid wake time")
            for name, typ in (("held", str), ("recent", (int, float)), ("challenges", (int, float))):
                if not isinstance(policy.get(name, []), list) or any(not isinstance(v, typ) for v in policy.get(name, [])):
                    raise ValueError("invalid policy history")
            if any(not math.isfinite(v) for k in ("recent", "challenges") for v in policy.get(k, [])):
                raise ValueError("invalid policy time")
            for name in ("cursor", "info_cursor"):
                if state.get(name) is not None and (not isinstance(state[name], str) or not re.fullmatch(r'e_\d+', state[name])):
                    raise ValueError("invalid cursor")
            for name in ("features", "loops_flagged"):
                if not isinstance(state.get(name, []), list) or any(not isinstance(v, str) for v in state.get(name, [])):
                    raise ValueError("invalid state list")
            passes = state.get("passes", {})
            if not isinstance(passes, dict) or any(type(v) is not int for v in passes.values()):
                raise ValueError("invalid pass counts")
            return state
        except (OSError, ValueError):
            return {"pending": {RECONCILE: 0}} if self.state_file.exists() else {}

    def save(self):
        self.state["policy"] = self.policy.snapshot()
        atomic_write(self.state_file, json.dumps(self.state))

    def queue(self, reasons, priority=0):
        pending = self.state.setdefault("pending", {})
        for reason in reasons:
            pending[reason] = max(priority, pending.get(reason, 0))

    def consume(self, response):
        """Save effects and cursor together; no poll may silently acknowledge work."""
        if response.get("replaced"):
            self.queue([RECONCILE])
            self.save()
            raise CompetingWatcher("another process is polling this character; stop the other watcher before restarting")
        events = response.get("events") or []
        if response.get("gap") or has_hold(events):
            self.queue([RECONCILE])
        self.queue(wake_reasons(events))
        if any(str(e.get("importance", "")).startswith("urgent") for e in events):
            self.queue(wake_reasons(events), priority=1)
        if challenge_waiting(events):
            self.queue([CHALLENGE], priority=2)
        self.fired_conditions(events)
        if response.get("cursor"):
            self.state["cursor"] = response["cursor"]
        self.save()
        return events

    def do_wake(self, reasons, urgent=False, retry=True, gap=True) -> bool:
        self.queue(reasons, priority=2 if urgent else 0)
        pending = dict(self.state.setdefault("pending", {}))
        urgent = any(p == 2 for p in pending.values())
        safety = any(p == 1 for p in pending.values())
        self.save()
        if not urgent and self.directed and self.directed.driving():
            if not self.was_driving:
                self.logs.log("owner is driving live; ordinary wakes paused")
                self.was_driving = True
            return False
        if self.was_driving:
            self.logs.log("owner stopped driving; wakes resume")
            self.was_driving = False
        pre_cursor = self.state.get("cursor")
        reasons, note = self.policy.admit(list(pending), urgent=urgent, gap=gap, safety=safety)
        self.save()
        if note:
            self.logs.log(note)
        if reasons is None:
            self.sleep(INFO_POLL_PAUSE_S)
            return False
        started = self.clock()
        gap_s = started - self.policy.last_wake if self.policy.last_wake else None
        mode = self.directed.mode_line() if self.directed else ""
        prompt = BASE_PROMPT + mode + "The watcher woke you because: " + "; ".join(reasons) + "\n"
        if (self.cfg.agent_dir / "reference-stale.flag").exists():
            prompt += "Your bundled reference is stale. Read current rules for any action you are about to plan.\n"
        ok, status, out = self.waker(prompt)
        duration = self.clock() - started
        self.logs.wake_output(started, reasons, out)
        self.logs.log(f"wake done ({status}, {duration:.0f}s): {'; '.join(reasons)}")
        self.logs.wake_row(started, duration, gap_s, reasons, status)
        if not ok:
            self.queue([RECONCILE])
            self.save()
            self.model_down(out)
            return False
        self.policy.woke()
        self.state["last_wake"] = self.policy.last_wake
        for reason in pending:
            self.state["pending"].pop(reason, None)
        self.save()
        importance = "info" if any(c.kind in EVENT_KINDS for c in self.live_conditions()) else "notable"
        r = self.api("/events/wait", {"since": pre_cursor, "min_importance": importance, "timeout_s": 1},
                     timeout=30) if pre_cursor else {}
        during = self.consume(r)
        self.refresh_wake_on()
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

    def model_down(self, detail=""):
        backoff = MODEL_DOWN_FIRST_S
        wait = seconds_until_reset(detail, self.clock())
        if wait:
            self.logs.log(f"wake failed: usage limit; it resets in about {wait // 60} min. "
                          f"Pausing all game calls until then")
        else:
            wait = backoff
            self.logs.log(f"wake failed: runtime unavailable? pausing all game calls, checking again in {wait // 60} min")
        while True:
            self.sleep(wait)
            if self.probe():
                self.logs.log("model is usable again; resuming")
                return
            backoff = min(backoff * 2, MODEL_DOWN_MAX_S)
            wait = backoff
            self.logs.log(f"runtime still unavailable; checking again in {wait // 60} min")

    def check_rules(self):
        try:
            status = self.status() or {}
            version = status.get("rules_version")
        except Exception as e:
            self.logs.log(f"rules check failed: {type(e).__name__}: {e}")
            return
        stamp = reference_stamp(self.cfg.agent_dir)
        built = self.cfg.agent_dir / load_profile(self.cfg.runtime)["instructions_file"]
        if built.exists():
            match = STAMP_RE.search(built.read_text(encoding="utf-8"))
            stamp = match.group(1) if match else None
        flag = self.cfg.agent_dir / "reference-stale.flag"
        if self.state.get("features_stale") and not flag.exists():
            # A completed operator refresh removes the flag as its final step.
            self.state["features_stale"] = False
        features = sorted(status.get("features") or [])
        previous = self.state.get("features")
        if previous is not None and features != previous:
            self.logs.log("FEATURES CHANGED: review live rules and the agent API")
            self.state["features_stale"] = True
        self.state["features"] = features
        if version and version != stamp or self.state.get("features_stale"):
            if not flag.exists():
                self.logs.log(f"REFERENCE STALE: rules_version is {version}, intents.md was generated "
                              f"from {stamp}; run refresh-reference.py")
                atomic_write(flag, f"{version}\n")
        # Only a completed reference refresh may clear the flag: a failed guide-only
        # rebuild can leave the same rules version in the old active instructions.
        self.save()

    def refresh_wake_on(self):
        """Read the WAKE ON line from the agent's notebook. A line that cannot be read or parsed
        costs at most a missed extra wake: plan ends and every other wake reason still apply."""
        if not self.cfg.wake_conditions:
            return
        try:
            line = extract_line(self.api("/me/notebook"))
        except Exception as e:
            self.logs.log(f"WAKE ON: notebook not readable ({type(e).__name__}: {e}); keeping what I had")
            return
        conditions, problems = parse_conditions(line)
        for text, why in problems:
            if (text, why) not in self.logged:
                self.logged.add((text, why))
                self.logs.log(f"WAKE ON ignored: {text}: {why}")
        texts = [c.text for c in conditions]
        record = self.wake_on()
        if texts != record["texts"]:
            self.logs.log("WAKE ON: " + ("; ".join(texts) if texts else "none"))
        record["texts"] = texts
        record["spent"] = [t for t in record["spent"] if t in texts]   # absent for one read: re-armed
        self.conditions = conditions
        self.save()

    def live_conditions(self):
        spent = set(self.wake_on()["spent"])
        return [c for c in self.conditions if c.text not in spent]

    def tick(self):
        try:
            tick = (self.status() or {}).get("tick")
            return int(tick) if tick is not None else None
        except Exception as e:
            self.logs.log(f"WAKE ON: could not read the game tick: {type(e).__name__}: {e}")
            return None

    def read_state(self):
        return extract_state(self.api("/me"), self.api("/bank"))

    def fired_conditions(self, events) -> list:
        """One-shot: a condition that fires is spent until it leaves the notebook and returns."""
        live = self.live_conditions()
        if not live:
            return []
        hit = fired_by_events(live, events)
        timed = [c for c in live if c.kind == "time"]
        if timed and self.clock() >= self.next_tick_check:
            self.next_tick_check = self.clock() + TICK_CHECK_S
            tick = self.tick()
            hit += [c for c in timed if time_due(c, tick)]
        stated = [c for c in live if c.kind in STATE_KINDS]
        if stated and self.clock() >= self.next_state_check:
            self.next_state_check = self.clock() + STATE_CHECK_S
            try:
                state = self.read_state()
            except Exception as e:
                self.logs.log(f"WAKE ON: state not readable ({type(e).__name__}: {e})")
                state = {}
            for c in stated:
                met = state_met(c, state)
                if met is None and ("unreadable", c.text) not in self.logged:
                    self.logged.add(("unreadable", c.text))
                    self.logs.log(f"WAKE ON unreadable: {c.text}: the game did not report it")
                if met:
                    hit.append(c)
        if hit:
            self.wake_on()["spent"] += [c.text for c in hit]
            self.queue([f"your condition fired: {c.text}" for c in hit])
            self.save()
        return [f"your condition fired: {c.text}" for c in hit]

    def check_loops(self):
        since = self.state.get("info_cursor") or self.state.get("cursor")
        r = self.api("/events/wait", {"since": since, "min_importance": "info", "timeout_s": 1}, timeout=30)
        if r.get("replaced"):
            raise CompetingWatcher("another process is polling this character")
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
            self.queue([RECONCILE])
            self.consume(r)
            if not self.state.get("cursor"):
                self.logs.log("events feed gave no cursor; retrying in 60 s")
                self.sleep(60)
            else:
                self.do_wake([])
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
        info_poll = any(c.kind in EVENT_KINDS for c in self.live_conditions())
        r = self.api("/events/wait", {"since": self.state["cursor"],
                                      "min_importance": "info" if info_poll else "notable",
                                      "timeout_s": 1 if self.state.get("pending") else WAIT_S}, timeout=WAIT_S + 20)
        self.backoff = 5
        self.consume(r)
        if self.state.get("pending"):
            self.do_wake([])
        elif self.policy.held_due():
            self.do_wake([])
        elif self.policy.routine_due(self.cfg.routine_wake_s):
            self.do_wake([f"routine check: {_human(self.cfg.routine_wake_s)} without a wake"])
        elif info_poll:
            self.sleep(INFO_POLL_PAUSE_S)   # the info feed answers at once while the agent is busy

    def handle_http(self, e):
        try:
            body = e.read() or b""
        except Exception:
            body = b""
        if e.code == 401:
            self.logs.log("401 unauthenticated: key missing, invalid or rotated; retrying in 5 min")
            self.sleep(300)
        elif e.code == 429:
            try:
                retry = json.loads(body).get("error", {}).get("retry_after_s", 60)
                retry = max(1, min(int(retry), 3600))
            except (ValueError, TypeError, AttributeError):
                retry = 60
            self.logs.log(f"429 rate limited; backing off {retry} s")
            self.sleep(retry)
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
        elif e.code == 403 and (b"AGENT_PAUSED" in body or b"AGENT_RETIRED" in body):
            self.logs.log("agent paused or retired by its owner; checking again in 5 min")
            self.sleep(300)
        else:
            self.logs.log(f"HTTP {e.code}; backing off {self.backoff}s")
            self.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 300)

    def run_once(self):
        try:
            self.step()
        except urllib.error.HTTPError as e:
            self.handle_http(e)
        except CompetingWatcher:
            raise
        except Exception as e:
            self.logs.log(f"{type(e).__name__}: {e}; backing off {self.backoff}s")
            self.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 300)

    def run(self):
        self.logs.log("watcher started")
        self.queue([RECONCILE])
        self.save()
        self.refresh_wake_on()
        while True:
            self.run_once()
