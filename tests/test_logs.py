import csv

from vfkit.logs import Logs


def test_log_redacts(tmp_path):
    Logs(tmp_path).log("got vf_live_secret_1 back")
    text = (tmp_path / "logs" / "watcher.log").read_text(encoding="utf-8")
    assert "vf_live" not in text and "[KEY REDACTED]" in text


def test_wake_output(tmp_path):
    Logs(tmp_path).wake_output(1_700_000_000, ["plan.completed"], "SUMMARY: ok vf_dev_x\n")
    text = (tmp_path / "logs" / "wakes.log").read_text(encoding="utf-8")
    assert "[plan.completed]" in text and "SUMMARY: ok [KEY REDACTED]" in text


def test_wake_output_redacts_reasons(tmp_path):
    Logs(tmp_path).wake_output(1_700_000_000, ["vf_dev_abc123"], "output")
    text = (tmp_path / "logs" / "wakes.log").read_text(encoding="utf-8")
    assert "vf_dev_abc123" not in text and "[KEY REDACTED]" in text


def test_wake_rows(tmp_path):
    logs = Logs(tmp_path)
    logs.wake_row(1_700_000_000, 42.4, None, ["routine check"], "exit 0")
    logs.wake_row(1_700_003_600, 30, 3600.2, ["plan.completed (plan_id=pl_12)"], "exit 0")
    with (tmp_path / "logs" / "wakes.csv").open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["time", "reason", "duration_s", "gap_s", "plan_id", "status"]
    assert rows[1][2:] == ["42", "", "", "exit 0"]
    assert rows[2][3:] == ["3600", "pl_12", "exit 0"]
