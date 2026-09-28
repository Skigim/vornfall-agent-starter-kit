"""API keys: stored outside the kit, read fresh on every use, never printed."""
import os
import re
import sys
from pathlib import Path

KEY_RE = re.compile(r"vf_(live|dev)_[A-Za-z0-9_]+")
VAR_RE = re.compile(r"[A-Z][A-Z0-9_]*")


def _on_windows() -> bool:
    return sys.platform == "win32"


def redact(text) -> str:
    return KEY_RE.sub("[KEY REDACTED]", text or "")


def keys_file() -> Path:
    return Path(os.environ.get("VORNFALL_KEYS_FILE") or Path.home() / ".config" / "vornfall" / "keys.env")


def _read_keys_file() -> dict:
    try:
        text = keys_file().read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip():
            out[name.strip()] = value.strip()
    return out


def _read_registry(var: str) -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, var)[0] or ""
    except OSError:
        return ""


def get_key(var: str) -> str:
    """Freshest first: a rotated key takes effect without restarting anything."""
    if _on_windows():
        value = _read_registry(var)
        if value:
            return value
    return _read_keys_file().get(var) or os.environ.get(var, "")


def has_key(var: str) -> bool:
    return bool(get_key(var))


def store_key(var: str, value: str) -> str:
    if not VAR_RE.fullmatch(var or ""):
        raise ValueError("the variable name must be capital letters, digits and underscores")
    if not KEY_RE.fullmatch(value or ""):
        raise ValueError("that is not a Vornfall API key")
    if _on_windows():
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, var, 0, winreg.REG_SZ, value)
        return "the Windows user environment"
    path = keys_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = _read_keys_file()
    stored[var] = value
    path.write_text("".join(f"{k}={v}\n" for k, v in stored.items()), encoding="utf-8", newline="\n")
    path.chmod(0o600)
    return str(path)
