"""The watcher's logs, all redacted: a running log, each wake's output, and one CSV row per wake."""
import csv
import re
from datetime import datetime
from pathlib import Path

from .keys import redact

PLAN_RE = re.compile(r"plan_id=(pl_\w+)")
CSV_HEADER = ["time", "reason", "duration_s", "gap_s", "plan_id", "status"]


class Logs:
    def __init__(self, agent_dir):
        self.dir = Path(agent_dir) / "logs"

    def _path(self, name) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self.dir / name

    def log(self, msg):
        with self._path("watcher.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {redact(msg)}\n")

    def wake_output(self, started, reasons, out):
        with self._path("wakes.log").open("a", encoding="utf-8") as f:
            f.write(f"=== {datetime.fromtimestamp(started):%Y-%m-%d %H:%M:%S} [{'; '.join(reasons)}] ===\n")
            f.write(redact(out).rstrip() + "\n\n")

    def wake_row(self, started, duration_s, gap_s, reasons, status):
        path = self._path("wakes.csv")
        new = not path.exists()
        joined = redact("; ".join(reasons))
        m = PLAN_RE.search(joined)
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(CSV_HEADER)
            w.writerow([datetime.fromtimestamp(started).isoformat(timespec="seconds"), joined,
                        round(duration_s), "" if gap_s is None else round(gap_s),
                        m.group(1) if m else "", status])
