"""Register a new agent: the agent itself, through its own runtime, chooses its name and answers its
own challenge. The key goes straight into the agent's key variable and is never shown.

Usage: python setup/register.py --dir AGENT_FOLDER"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

import _kit  # noqa: F401

from vfkit.config import load_config
from vfkit.keys import KEY_RE, get_key, has_key, redact, store_key
from vfkit.runtime import load_profile, render_template, run
from vfkit.storage import atomic_write, exclusive_lock


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
    found = {m.group(0) for m in KEY_RE.finditer(out or "")}
    if len(found) > 1:
        raise ValueError("multiple different keys in registration output; recover manually")
    return {"name": _find(r"(?m)^NAME:[ \t]*(.+)$", out or ""), "agent": _find(r"(?m)^AGENT:[ \t]*(a_\w+)[ \t]*$", out or ""),
            "key": next(iter(found), None),
            "claim": _find(r"(https://vornfall\.com/claim/\S+)", out or "")}


def swap_files(dest, profile, cfg, bootstrap):
    """Some runtimes read MCP settings from a fixed path: put the keyless bootstrap version there for
    the registration run (bootstrap=True), and the normal one back afterwards (bootstrap=False)."""
    files = profile.get("register_files") if bootstrap else profile["files"]
    for target, template in (files or {}).items():
        if bootstrap or target in (profile.get("register_files") or {}):
            text = (profile["dir"] / template).read_text(encoding="utf-8")
            atomic_write(dest / target, render_template(text, cfg.key_var, cfg.model, cfg.effort))


def recover(cfg, capture, status):
    """Persist a recovered key before logs or configuration writes can fail."""
    journal = cfg.agent_dir / "registration-pending.json"
    if not capture.exists() and journal.exists():
        saved = json.loads(journal.read_text(encoding="utf-8"))
        if saved.get("status") == "stored" and get_key(cfg.key_var):
            journal.unlink()
            return saved["identity"], "the existing key store"
    out = capture.read_text(encoding="utf-8", errors="replace") if capture.exists() else ""
    got = parse_registration(out)
    if not got["key"]:
        raise ValueError("Registration outcome is uncertain. Do not register again: the character may exist. "
                         "Keep registration-pending.json and the private capture for recovery; "
                         "use a claim link/key rotation if available.")
    existing = get_key(cfg.key_var)
    if existing and existing != got["key"]:
        raise ValueError("A different key is already stored; refusing to overwrite a rotated or another character's key. Recover manually.")
    where = store_key(cfg.key_var, got["key"])
    got["key"] = None
    # Only redacted output reaches the ordinary log, after the key is durable.
    logs = cfg.agent_dir / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "register.log").open("a", encoding="utf-8") as stream:
        stream.write(f"=== register {datetime.now():%Y-%m-%d %H:%M:%S} ({status}) ===\n{redact(out)}\n")
    out = None
    atomic_write(cfg.agent_dir / "claim.txt", f"{got['claim'] or 'Claim link not captured; use new_claim_link with the recovered character.'}\n"
                 f"agent: {got['name']} ({got['agent']})\n", private=True)
    watcher = json.loads((cfg.agent_dir / "watcher.json").read_text(encoding="utf-8"))
    watcher["name"] = got["name"] or watcher["name"]
    atomic_write(cfg.agent_dir / "watcher.json", json.dumps(watcher, indent=2) + "\n")
    atomic_write(journal, json.dumps({"status": "stored", "identity": got}), private=True)
    capture.unlink(missing_ok=True)
    journal.unlink(missing_ok=True)
    return got, where


def register_or_recover(cfg):
    capture = cfg.agent_dir / "registration-output.private"
    journal = cfg.agent_dir / "registration-pending.json"
    profile = load_profile(cfg.runtime)
    if journal.exists() or capture.exists():
        # Restore the normal configuration after a killed bootstrap process.
        swap_files(cfg.agent_dir, profile, cfg, bootstrap=False)
        try:
            got, where = recover(cfg, capture, "recovered interrupted registration")
        except ValueError as e:
            sys.exit(str(e))
        print(f"Recovered existing character; key stored in {cfg.key_var} ({where}). No registration was sent.")
        print(f"Claim link: {got['claim'] or 'see claim.txt'}")
        return
    if has_key(cfg.key_var):
        sys.exit(f"{cfg.key_var} already holds a key: this agent is already registered")
    # Exclusive creation also refuses simultaneous setup in this folder.
    with journal.open("x", encoding="utf-8") as stream:
        json.dump({"status": "registration may have started"}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    swap_files(cfg.agent_dir, profile, cfg, bootstrap=True)
    try:
        ok, status, out = run(profile, "register", cfg, registration_prompt(cfg.model or cfg.runtime),
                              key_var="", raw=True, capture_path=capture)
        out = None
    finally:
        swap_files(cfg.agent_dir, profile, cfg, bootstrap=False)
    try:
        got, where = recover(cfg, capture, status)
    except ValueError as e:
        sys.exit(str(e))
    if got['name'] and got['agent'] and got['claim']:
        print(f"Registered {got['name']} ({got['agent']}). Key stored in {cfg.key_var} ({where}); not shown.")
        print(f"Claim link (also in claim.txt): {got['claim']}")
    else:
        print(f"Credential recovered into {cfg.key_var}, but identity metadata is incomplete. "
              "Use get_character and new_claim_link with this character; do not register again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    cfg = load_config(ap.parse_args().dir)
    with exclusive_lock(cfg.agent_dir / "registration.lock"):
        register_or_recover(cfg)


if __name__ == "__main__":
    main()
