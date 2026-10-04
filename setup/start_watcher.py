"""Start an agent's watcher in the background and confirm it is running.

Usage: python setup/start_watcher.py --dir AGENT_FOLDER [--wait-first-wake SECONDS]"""
import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import _kit  # noqa: F401

from vfkit import KIT_DIR
from vfkit.config import load_config
from vfkit.runtime import load_profile


def port_in_use(port) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def last_summary(text):
    found = re.findall(r"^SUMMARY:.*$", text or "", re.M)
    return found[-1] if found else None


def launch(agent_dir, allow_untested=False):
    python = Path(sys.executable)
    extra = ['--allow-untested'] if allow_untested else []
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else python)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen([exe, str(KIT_DIR / "watcher.py"), str(agent_dir), *extra], cwd=agent_dir,
                         creationflags=flags, close_fds=True)
    else:
        return subprocess.Popen([str(python), str(KIT_DIR / "watcher.py"), str(agent_dir), *extra], cwd=agent_dir,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--wait-first-wake", type=int, default=0)
    ap.add_argument("--allow-untested", action="store_true", help="allow a supervised rehearsal of an unverified adapter")
    a = ap.parse_args()
    cfg = load_config(a.dir)
    if not load_profile(cfg.runtime).get("tested") and not a.allow_untested:
        sys.exit("runtime is unverified; use --allow-untested only for a supervised rehearsal (RUNBOOK section 9)")
    if port_in_use(cfg.lock_port):
        sys.exit(f"a watcher is already running for this agent (port {cfg.lock_port})")
    log = cfg.agent_dir / "logs" / "watcher.log"
    start_size = log.stat().st_size if log.exists() else 0
    child = launch(cfg.agent_dir, allow_untested=a.allow_untested)
    for _ in range(30):
        time.sleep(0.5)
        if child.poll() is not None:
            sys.exit("watcher exited during startup; inspect logs and configuration")
        fresh = log.read_bytes()[start_size:].decode("utf-8", "replace") if log.exists() else ""
        if port_in_use(cfg.lock_port) and "watcher started" in fresh:
            break
    else:
        sys.exit("the watcher did not start: see logs/watcher.log")
    print(f"watcher process started for {cfg.name} (port {cfg.lock_port}); gameplay readiness is not yet verified")
    deadline = time.time() + a.wait_first_wake
    while time.time() < deadline:
        time.sleep(5)
        if child.poll() is not None:
            sys.exit("watcher exited before its first successful decision")
        new = log.read_bytes()[start_size:].decode("utf-8", "replace") if log.exists() else ""
        done = [line for line in new.splitlines() if " wake done " in line]
        if done:
            print(done[-1])
            if "wake done (exit 0," not in done[-1]:
                sys.exit("first decision failed or was incomplete; see logs/watcher.log (the watcher will retain pending work)")
            wakes = cfg.agent_dir / "logs" / "wakes.log"
            print(last_summary(wakes.read_text(encoding="utf-8")) if wakes.exists() else "(no wake output yet)")
            return
    if a.wait_first_wake:
        sys.exit("no successful decision observed before the deadline; readiness is unverified, see logs/watcher.log")


if __name__ == "__main__":
    main()
