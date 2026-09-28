"""Create an agent folder from the kit's template for one runtime.

  python setup/new_agent.py --suggest
  python setup/new_agent.py --dir D --runtime R --key-var V --port P --model M [--effort E] [--directed]"""
import argparse
import json
import shutil
import socket
import sys
from pathlib import Path

import _kit  # noqa: F401

from vfkit import KIT_DIR
from vfkit.instructions import build
from vfkit.keys import VAR_RE, has_key
from vfkit.runtime import load_profile, render_template

TEMPLATE = KIT_DIR / "template"
PARTS = ("instructions.md", "persona.md", "world-reference.md", "intents.md", "vornfall-guide.md")


def port_free(port) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def suggest() -> dict:
    port = next(p for p in range(47931, 48031) if port_free(p))
    names = ["VORNFALL_API_KEY"] + [f"VORNFALL_API_KEY_{i}" for i in range(2, 100)]
    return {"port": port, "key_var": next(n for n in names if not has_key(n))}


def inside_agent(path):
    for parent in Path(path).resolve().parents:
        if (parent / "watcher.json").exists():
            return parent
    return None


def create_agent(dest, runtime, key_var, port, model, effort, directed=False) -> Path:
    dest = Path(dest).resolve()
    profile = load_profile(runtime)
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"{dest} is not empty")
    owner = inside_agent(dest)
    if owner:
        raise ValueError(f"{dest} is inside another agent's folder ({owner})")
    if not VAR_RE.fullmatch(key_var):
        raise ValueError("the key variable must be capital letters, digits and underscores")
    if has_key(key_var):
        raise ValueError(f"{key_var} already holds a key: choose another variable")
    if not port_free(port):
        raise ValueError(f"port {port} is in use")
    if profile["efforts"] and effort not in profile["efforts"]:
        raise ValueError(f"effort must be one of {profile['efforts']} for {profile['label']}")
    dest.mkdir(parents=True, exist_ok=True)
    for part in PARTS:
        shutil.copyfile(TEMPLATE / part, dest / part)
    for target, template in profile["files"].items():
        out = dest / target
        out.parent.mkdir(parents=True, exist_ok=True)
        text = (profile["dir"] / template).read_text(encoding="utf-8")
        out.write_text(render_template(text, key_var, model, effort), encoding="utf-8", newline="\n")
    cfg = json.loads((TEMPLATE / "watcher.json").read_text(encoding="utf-8"))
    cfg.update(name=dest.name, runtime=runtime, key_var=key_var, lock_port=port, model=model,
               effort=effort, directed=directed)
    (dest / "watcher.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
    if directed:
        (dest / "orders.md").write_text("# Orders\n\n(Your standing orders for the agent.)\n", encoding="utf-8", newline="\n")
        (dest / "goal.md").write_text("# Current goal\n\n(What the agent should work toward now.)\n", encoding="utf-8", newline="\n")
    build(dest, profile["instructions_file"])
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--dir")
    ap.add_argument("--runtime")
    ap.add_argument("--key-var")
    ap.add_argument("--port", type=int)
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--directed", action="store_true")
    a = ap.parse_args()
    if a.suggest:
        print(json.dumps(suggest()))
        return
    if not all([a.dir, a.runtime, a.key_var, a.port]):
        ap.error("--dir, --runtime, --key-var and --port are required")
    try:
        dest = create_agent(a.dir, a.runtime, a.key_var, a.port, a.model, a.effort, a.directed)
    except ValueError as e:
        sys.exit(f"not created: {e}")
    print(f"created {dest} for {load_profile(a.runtime)['label']}")


if __name__ == "__main__":
    main()
