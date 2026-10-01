"""Bring an existing agent up to date with the kit's template: copy the template's instruction parts
and rules snapshot into the agent's folder, then rebuild its instructions file. The agent's persona
and watcher.json are its own and are never touched; its notebook lives on the game's server.
Usage: python update-agent.py <agent folder>"""
import filecmp
import shutil
import sys
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT_DIR))

from vfkit.config import load_config  # noqa: E402
from vfkit.instructions import build  # noqa: E402
from vfkit.runtime import load_profile  # noqa: E402

TEMPLATE = KIT_DIR / "template"
SHARED = ("instructions.md", "intents.md", "world-reference.md", "vornfall-guide.md",
          "rules-snapshot.json")


def update(folder):
    cfg = load_config(folder)
    dest = Path(cfg.agent_dir)
    changed = []
    for part in SHARED:
        src, out = TEMPLATE / part, dest / part
        if not out.exists() or not filecmp.cmp(src, out, shallow=False):
            shutil.copyfile(src, out)
            changed.append(part)
    built = build(dest, load_profile(cfg.runtime)["instructions_file"])
    return changed, built


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    changed, built = update(sys.argv[1])
    print("updated: " + (", ".join(changed) if changed else "nothing (already current)"))
    print(f"wrote {built}")
    print("his next wake reads the new instructions; restart his watcher if vfkit/ changed")
