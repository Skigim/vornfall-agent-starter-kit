"""Directed mode, for openly driven agents only: orders.md and goal.md edits wake the agent, and it
turns autonomous after a while without the owner. Off unless watcher.json says "directed": true."""
import time

DRIVING_STALE_S = 12 * 60 * 60


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


class Directed:
    def __init__(self, cfg, state, clock=time.time):
        self.cfg = cfg
        self.state = state
        self.clock = clock
        self.orders = cfg.agent_dir / "orders.md"
        self.goal = cfg.agent_dir / "goal.md"
        self.flag = cfg.agent_dir / "driving.flag"
        state.setdefault("orders_mtime", _mtime(self.orders))
        state.setdefault("goal_mtime", _mtime(self.goal))
        state.setdefault("last_manual", state["orders_mtime"] or clock())
        state["mode"] = self.current_mode()

    def driving(self) -> bool:
        m = _mtime(self.flag)
        return m is not None and self.clock() - m < DRIVING_STALE_S

    def current_mode(self) -> str:
        away = self.clock() - self.state["last_manual"]
        return "autonomous" if away >= self.cfg.autonomy_after_s else "directed"

    def mode_line(self) -> str:
        away = self.clock() - self.state["last_manual"]
        ago = f"{away / 3600:.1f} h" if away >= 3600 else f"{away / 60:.0f} min"
        return f"Mode: {self.current_mode().upper()}. Your owner last edited your orders or drove you {ago} ago.\n"

    def change(self):
        if self.driving():
            self.state["last_manual"] = self.clock()
        m = _mtime(self.orders)
        if m != self.state.get("orders_mtime"):
            self.state.update(orders_mtime=m, last_manual=self.clock(), mode="directed")
            return ["your owner updated your orders"], False
        g = _mtime(self.goal)
        if g != self.state.get("goal_mtime"):
            self.state["goal_mtime"] = g
            return ["your owner adjusted your goal: follow the new goal from now on"], False
        mode = self.current_mode()
        if mode != self.state.get("mode"):
            self.state["mode"] = mode
            if mode == "autonomous":
                return ["your owner has been away long enough that you are now in autonomous mode: "
                        "keep their last goal and work toward it on your own judgement"], True
        return None
