"""When a wake may happen: challenge and hourly caps, and an optional minimum gap."""
import time
from datetime import datetime


class WakePolicy:
    def __init__(self, min_gap_s=0, max_per_hour=20, max_challenge_per_hour=5, clock=time.time):
        self.min_gap_s = min_gap_s
        self.max_per_hour = max_per_hour
        self.max_challenge_per_hour = max_challenge_per_hour
        self.clock = clock
        self.last_wake = 0.0
        self.held = []
        self.recent = []
        self.challenges = []

    def admit(self, reasons, urgent=False, gap=True):
        now = self.clock()
        if urgent:
            self.challenges = [t for t in self.challenges if now - t < 3600]
            if len(self.challenges) >= self.max_challenge_per_hour:
                return None, "challenge wake cap reached; leaving it unshown (an unshown challenge can't fail)"
            self.challenges.append(now)
        elif gap and self.min_gap_s and now - self.last_wake < self.min_gap_s:
            new = [r for r in reasons if r not in self.held]
            note = ""
            if new and not self.held:
                due = datetime.fromtimestamp(self.last_wake + self.min_gap_s).strftime("%H:%M")
                note = f"holding wake until {due}: {'; '.join(new)}"
            self.held.extend(new)
            return None, note
        merged = self.held + [r for r in reasons if r not in self.held]
        if not urgent:
            self.recent = [t for t in self.recent if now - t < 3600]
            if len(self.recent) >= self.max_per_hour:
                return None, f"hourly wake cap reached; deferring: {'; '.join(merged)}"
            self.recent.append(now)
        self.held = []
        return merged, ""

    def woke(self):
        self.last_wake = self.clock()

    def held_due(self) -> bool:
        return bool(self.held) and self.clock() - self.last_wake >= self.min_gap_s

    def routine_due(self, routine_s) -> bool:
        return self.clock() - self.last_wake > routine_s
