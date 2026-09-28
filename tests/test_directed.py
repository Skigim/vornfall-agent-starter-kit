import os

from vfkit.config import Config
from vfkit.directed import Directed


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def setup(tmp_path, t=1_000_000.0):
    (tmp_path / "orders.md").write_text("orders", encoding="utf-8")
    (tmp_path / "goal.md").write_text("goal", encoding="utf-8")
    os.utime(tmp_path / "orders.md", (t, t))
    os.utime(tmp_path / "goal.md", (t, t))
    cfg = Config(agent_dir=tmp_path, name="a", key_var="K", lock_port=1, directed=True,
                 autonomy_after_s=7200)
    clock = Clock(t)
    return Directed(cfg, {}, clock), clock


def test_orders_edit_wakes_and_goes_directed(tmp_path):
    d, clock = setup(tmp_path)
    assert d.change() is None
    clock.t += 100
    os.utime(tmp_path / "orders.md", (clock.t, clock.t))
    assert d.change() == (["your owner updated your orders"], False)
    assert d.current_mode() == "directed"
    assert "Mode: DIRECTED" in d.mode_line()


def test_goal_edit_wakes(tmp_path):
    d, clock = setup(tmp_path)
    os.utime(tmp_path / "goal.md", (clock.t + 5, clock.t + 5))
    reasons, gap = d.change()
    assert "adjusted your goal" in reasons[0] and gap is False


def test_goes_autonomous_once(tmp_path):
    d, clock = setup(tmp_path)
    clock.t += 7300
    reasons, gap = d.change()
    assert "autonomous mode" in reasons[0] and gap is True
    assert d.change() is None
    assert "Mode: AUTONOMOUS" in d.mode_line()


def test_driving_flag(tmp_path):
    d, clock = setup(tmp_path)
    assert not d.driving()
    (tmp_path / "driving.flag").write_text("", encoding="utf-8")
    os.utime(tmp_path / "driving.flag", (clock.t, clock.t))
    assert d.driving()
