"""Per-agent watcher configuration, read from the agent folder's watcher.json."""
import json
from dataclasses import dataclass, fields
from pathlib import Path

REQUIRED = ("name", "key_var", "lock_port")


@dataclass(frozen=True)
class Config:
    agent_dir: Path
    name: str
    key_var: str
    lock_port: int
    runtime: str = "claude"
    model: str = ""
    effort: str = ""
    min_wake_gap_s: int = 0
    routine_wake_s: int = 3600
    directed: bool = False
    autonomy_after_s: int = 7200
    cli_path: str = ""
    api: str = "https://api.vornfall.com/v1"
    long_loop_passes: int = 50
    rules_check_s: int = 86400


def load_config(agent_dir) -> Config:
    agent_dir = Path(agent_dir).resolve()
    raw = json.loads((agent_dir / "watcher.json").read_text(encoding="utf-8"))
    known = {f.name for f in fields(Config)} - {"agent_dir"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown keys in watcher.json: {unknown}")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ValueError(f"watcher.json needs {', '.join(missing)}")
    return Config(agent_dir=agent_dir, **raw)
