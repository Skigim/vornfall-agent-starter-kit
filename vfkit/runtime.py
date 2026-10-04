"""Agent harnesses as profiles: how to wake, register and probe an agent on one runtime."""
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import KIT_DIR
from .keys import KEY_RE, get_key, redact

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


def command(profile, which, cli, model="", effort="", prompt="", key_var="") -> list:
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
        arg = arg.replace("__KEY_VAR__", key_var)
        out.append(arg)
    return out


def render_template(text, key_var, model, effort) -> str:
    return text.replace("__KEY_VAR__", key_var).replace("__MODEL__", model).replace("__EFFORT__", effort)


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""


def captured_registration(argv, prompt, via_arg, cwd, env, timeout, capture_path):
    """Keep registration output durably, even if the setup process dies.

    The file contains credentials: private by creation mode, never log or display it.
    An interrupted registration must be recovered, never silently repeated.
    """
    fd = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as capture:
        with subprocess.Popen(argv, stdin=subprocess.DEVNULL if via_arg else subprocess.PIPE,
                              stdout=capture, stderr=capture, cwd=cwd, env=env,
                              creationflags=NO_WINDOW, start_new_session=os.name != 'nt') as process:
            try:
                process.communicate(None if via_arg else prompt.encode("utf-8"), timeout=timeout)
                status = f"exit {process.returncode}"
            except subprocess.TimeoutExpired:
                try:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       capture_output=True, creationflags=NO_WINDOW, timeout=30)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except (OSError, subprocess.TimeoutExpired):
                    pass  # Still terminate the parent, even when tree cleanup fails.
                finally:
                    if process.poll() is None:
                        process.kill()
                process.communicate()
                status = "timed out"
            capture.flush()
            os.fsync(capture.fileno())
    return process.returncode == 0 and status != "timed out", status, Path(capture_path).read_text(encoding="utf-8", errors="replace")


def run(profile, which, cfg, prompt, key_var, timeout=900, cwd=None, raw=False, capture_path=None):
    """One headless run of the agent's harness. Returns (ok, status, output).

    By default, output is redacted. Pass raw=True to get the raw output with keys intact
    (only for registration parsing; never print the raw text).
    """
    try:
        cli = find_cli(profile, cfg.cli_path)
    except FileNotFoundError as e:
        return False, f"could not start: {e}", ""
    via_arg = profile.get("prompt_via") == "arg"
    argv = command(profile, which, cli, cfg.model, cfg.effort, prompt if via_arg else "", key_var=key_var)
    # Other Vornfall characters' keys must not leak into this model process.
    env = {name: value for name, value in os.environ.items() if not KEY_RE.fullmatch(value)}
    if key_var:
        env[key_var] = get_key(key_var)
    try:
        if capture_path is not None:
            if which != "register" or not raw:
                raise ValueError("private capture is only for registration")
            return captured_registration(argv, prompt, via_arg, cwd or cfg.agent_dir, env, timeout, capture_path)
        with tempfile.TemporaryDirectory(prefix="vornfall-turn-") as scratch:
            ok, status, out = captured_registration(argv, prompt, via_arg, cwd or cfg.agent_dir,
                                                    env, timeout, Path(scratch) / 'output.private')
    except subprocess.TimeoutExpired as e:
        out = _text(e.output) + _text(e.stderr)
        return False, "timed out", out if raw else redact(out)
    except OSError as e:
        return False, f"could not start: {e}", ""
    if ok and which == "wake" and not re.search(r"^VORNFALL_TURN_COMPLETE\s*$", out, re.M):
        ok, status = False, "incomplete turn (no completion marker)"
    return ok, status, out if raw else redact(out)


def probe(profile, cfg) -> bool:
    """Can the harness run at all? A tiny prompt with no game tools, outside the agent's folder."""
    ok, _, output = run(profile, "probe", cfg, "Do not use tools. Reply with OK.", key_var="", timeout=180,
                   cwd=tempfile.gettempdir())
    return ok and bool(re.search(r"^OK[.!]?\s*$", output.strip(), re.M))
