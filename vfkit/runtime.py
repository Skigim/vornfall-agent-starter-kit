"""Agent harnesses as profiles: how to wake, register and probe an agent on one runtime."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import KIT_DIR
from .keys import get_key, redact

RUNTIMES_DIR = KIT_DIR / "runtimes"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_profile(name) -> dict:
    path = RUNTIMES_DIR / name / "runtime.json"
    if not path.exists():
        raise ValueError(f"no runtime profile named {name!r} in {RUNTIMES_DIR}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["dir"] = path.parent
    return profile


def list_profiles() -> list:
    return [load_profile(p.parent.name) for p in sorted(RUNTIMES_DIR.glob("*/runtime.json"))]


def find_cli(profile, configured="") -> str:
    if configured:
        if Path(configured).exists():
            return configured
        raise FileNotFoundError(f"{configured} does not exist")
    name = profile["cli"]
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if sys.platform == "win32" else "")
    local = Path.home() / ".local" / "bin" / exe
    if local.exists():
        return str(local)
    raise FileNotFoundError(f"{name} not found on PATH: install it, or set cli_path in watcher.json")


def command(profile, which, cli, model="", effort="", prompt="") -> list:
    values = {"cli": cli, "model": model, "effort": effort, "prompt": prompt}
    out = []
    for arg in profile[which]:
        empty = any(f"{{{k}}}" in arg and not values[k] for k in ("model", "effort"))
        if empty:
            if out and out[-1].startswith("-") and "=" not in out[-1] and out[-1] not in ("-p",):
                out.pop()
            continue
        for k, v in values.items():
            arg = arg.replace(f"{{{k}}}", v)
        out.append(arg)
    return out


def render_template(text, key_var, model, effort) -> str:
    return text.replace("__KEY_VAR__", key_var).replace("__MODEL__", model).replace("__EFFORT__", effort)


def run(profile, which, cfg, prompt, key_var, timeout=900, cwd=None):
    """One headless run of the agent's harness. Returns (ok, status, redacted output)."""
    try:
        cli = find_cli(profile, cfg.cli_path)
    except FileNotFoundError as e:
        return False, f"could not start: {e}", ""
    via_arg = profile.get("prompt_via") == "arg"
    argv = command(profile, which, cli, cfg.model, cfg.effort, prompt if via_arg else "")
    env = dict(os.environ)
    if key_var:
        env[key_var] = get_key(key_var)
    try:
        r = subprocess.run(argv, input=None if via_arg else prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=cwd or cfg.agent_dir, env=env,
                           timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, "timed out", ""
    except OSError as e:
        return False, f"could not start: {e}", ""
    return r.returncode == 0, f"exit {r.returncode}", redact((r.stdout or "") + (r.stderr or ""))


def probe(profile, cfg) -> bool:
    """Can the harness run at all? A tiny prompt with no game tools, outside the agent's folder."""
    ok, _, _ = run(profile, "probe", cfg, "Reply with OK.", key_var="", timeout=180,
                   cwd=tempfile.gettempdir())
    return ok
