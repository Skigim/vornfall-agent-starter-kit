"""Vornfall agent watcher. Usage: python watcher.py <agent folder>

Long-polls the game's events (no model tokens) and wakes the agent through its runtime only when
there is something to decide. Fair play: it never chooses actions, never answers challenges and
never writes thoughts; it only decides *when* the agent is woken, and tells it why."""
import json
import socket
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vfkit import runtime  # noqa: E402
from vfkit.config import load_config  # noqa: E402
from vfkit.core import Watcher  # noqa: E402
from vfkit.keys import get_key  # noqa: E402
from vfkit.logs import Logs  # noqa: E402
from vfkit.reference import fetch_status  # noqa: E402


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    cfg = load_config(argv[1])
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", cfg.lock_port))
    except OSError:
        print(f"a watcher is already running on port {cfg.lock_port}", file=sys.stderr)
        return 1
    profile = runtime.load_profile(cfg.runtime)

    def api(path, params=None, timeout=20):
        url = f"{cfg.api}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {get_key(cfg.key_var)}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    Watcher(cfg, api,
            waker=lambda prompt: runtime.run(profile, "wake", cfg, prompt, cfg.key_var),
            probe=lambda: runtime.probe(profile, cfg),
            status=lambda: fetch_status(cfg.api),
            logs=Logs(cfg.agent_dir)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
