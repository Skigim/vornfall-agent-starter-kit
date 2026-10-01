"""Regenerate intents.md from the live rules and fetch the current joining guide (vornfall-guide.md),
rebuild agents' instructions, and print what changed.

Usage: python refresh-reference.py --key-var VAR [--dir DIR ...]
  --key-var  the environment variable holding any registered agent's key (meta/rules needs one)
  --dir      a folder to refresh: the kit's template (default) and/or agent folders
The hand-written world-reference.md is never rewritten: review it against the printed diff."""
import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

from vfkit.config import load_config  # noqa: E402
from vfkit.instructions import build  # noqa: E402
from vfkit.keys import get_key  # noqa: E402
from vfkit.reference import (MCP_URL, fetch_guide, fetch_mcp_tools, fetch_rules, guide_diff,  # noqa: E402
                             intents_md, rules_diff)
from vfkit.runtime import load_profile  # noqa: E402

API = "https://api.vornfall.com/v1"


def refresh(dirs, rules, tools, guide=None) -> list:
    diff = None
    guide_changes = None
    for d in dirs:
        d = Path(d)
        snap = d / "rules-snapshot.json"
        try:
            old = json.loads(snap.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        if diff is None:
            diff = rules_diff(old, rules) if old else ["no previous snapshot: nothing to compare"]
        (d / "intents.md").write_text(intents_md(rules, tools), encoding="utf-8", newline="\n")
        if guide is not None:
            gp = d / "vornfall-guide.md"
            if guide_changes is None:
                guide_changes = guide_diff(gp.read_text(encoding="utf-8") if gp.exists() else "", guide)
            gp.write_text(guide, encoding="utf-8", newline="\n")
        snap.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        (d / "reference-stale.flag").unlink(missing_ok=True)
        if (d / "watcher.json").exists() and (d / "instructions.md").exists():
            cfg = load_config(d)
            if cfg.runtime.startswith("__"):
                continue
            build(d, load_profile(cfg.runtime)["instructions_file"])
    return (diff or []) + (guide_changes or [])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key-var", required=True)
    ap.add_argument("--dir", action="append", default=[])
    args = ap.parse_args()
    key = get_key(args.key_var)
    if not key:
        sys.exit(f"{args.key_var} holds no key")
    rules = fetch_rules(API, key)
    tools = fetch_mcp_tools(MCP_URL, key)
    guide = fetch_guide()
    dirs = [Path(d) for d in args.dir] or [KIT / "template"]
    diff = refresh(dirs, rules, tools, guide)
    print(f"rules_version {rules.get('rules_version')}; refreshed {', '.join(str(d) for d in dirs)}")
    print("\n".join(diff) if diff else "no rules changes")
    print("Review world-reference.md and the \"How you run\" notes in instructions.md against the changes\n"
          "above, then update the rules_version line.")


if __name__ == "__main__":
    main()
