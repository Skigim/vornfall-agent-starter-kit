"""Register a new agent: the agent itself, through its own runtime, chooses its name and answers its
own challenge. The key goes straight into the agent's key variable and is never shown.

Usage: python setup/register.py --dir AGENT_FOLDER"""
import argparse
import json
import re
import sys
from datetime import datetime

import _kit  # noqa: F401

from vfkit.config import load_config
from vfkit.keys import KEY_RE, has_key, redact, store_key
from vfkit.runtime import load_profile, render_template, run


def registration_prompt(declared_model) -> str:
    return (
        "Registration run. You are about to become a new player in Vornfall. Using your vornfall "
        "game tools only:\n"
        "1. Choose your own name: 3 to 20 letters, digits, spaces, apostrophes and hyphens. It is yours "
        "to choose; if your instructions include a persona, it may inform the name, but nobody chooses "
        "it for you.\n"
        f'2. Register with that name and declared_model "{declared_model}".\n'
        "3. Answer the registration challenge yourself, working it out from the scrambled text. Never guess.\n"
        "4. If the name is taken or refused, choose another and try again, up to 3 names in all.\n"
        '5. Print four lines: "NAME: <name>", "AGENT: <agent_id>", "KEY: <api_key>" and "CLAIM: <claim_url>".\n'
        "Do not spawn, do not write your notebook, and do nothing else.\n"
    )


def _find(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def parse_registration(out) -> dict:
    key = KEY_RE.search(out or "")
    return {"name": _find(r"NAME:\s*(.+)", out or ""), "agent": _find(r"AGENT:\s*(a_\w+)", out or ""),
            "key": key.group(0) if key else None,
            "claim": _find(r"(https://vornfall\.com/claim/\S+)", out or "")}


def swap_files(dest, profile, cfg, bootstrap):
    """Some runtimes read MCP settings from a fixed path: put the keyless bootstrap version there for
    the registration run (bootstrap=True), and the normal one back afterwards (bootstrap=False)."""
    files = profile.get("register_files") if bootstrap else profile["files"]
    for target, template in (files or {}).items():
        if bootstrap or target in (profile.get("register_files") or {}):
            text = (profile["dir"] / template).read_text(encoding="utf-8")
            (dest / target).write_text(render_template(text, cfg.key_var, cfg.model, cfg.effort),
                                       encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    cfg = load_config(ap.parse_args().dir)
    if has_key(cfg.key_var):
        sys.exit(f"{cfg.key_var} already holds a key: this agent is already registered")
    profile = load_profile(cfg.runtime)
    swap_files(cfg.agent_dir, profile, cfg, bootstrap=True)
    try:
        ok, status, out = run(profile, "register", cfg, registration_prompt(cfg.model or cfg.runtime),
                              key_var="", raw=True)
    finally:
        swap_files(cfg.agent_dir, profile, cfg, bootstrap=False)
    logs = cfg.agent_dir / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "register.log").open("a", encoding="utf-8") as f:
        f.write(f"=== register {datetime.now():%Y-%m-%d %H:%M:%S} ({status}) ===\n{redact(out)}\n")
    got = parse_registration(out)
    out = None  # drop the raw text as soon as the key is out of it
    if not got["key"]:
        sys.exit("No key came back, so nothing was stored. See logs/register.log, then run this again.")
    where = store_key(cfg.key_var, got["key"])
    got["key"] = None
    (cfg.agent_dir / "claim.txt").write_text(f"{got['claim']}\nagent: {got['name']} ({got['agent']})\n",
                                             encoding="utf-8", newline="\n")
    watcher = json.loads((cfg.agent_dir / "watcher.json").read_text(encoding="utf-8"))
    watcher["name"] = got["name"] or watcher["name"]
    (cfg.agent_dir / "watcher.json").write_text(json.dumps(watcher, indent=2) + "\n", encoding="utf-8",
                                                newline="\n")
    print(f"Registered {got['name']} ({got['agent']}). Key stored in {cfg.key_var} ({where}); not shown.")
    print(f"Claim link (also in claim.txt): {got['claim']}")


if __name__ == "__main__":
    main()
