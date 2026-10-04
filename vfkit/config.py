"""Per-agent watcher configuration, read from the agent folder's watcher.json."""
import json
from dataclasses import dataclass, fields
from pathlib import Path

REQUIRED = ("name", "key_var", "lock_port")
PRODUCTION_API = "https://api.vornfall.com/v1"


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
    wake_conditions: bool = True   # read the agent's WAKE ON line


def load_config(agent_dir) -> Config:
    agent_dir = Path(agent_dir).resolve()
    raw = json.loads((agent_dir / "watcher.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("watcher.json must contain an object")
    known = {f.name for f in fields(Config)} - {"agent_dir"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown keys in watcher.json: {unknown}")
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        raise ValueError(f"watcher.json needs {', '.join(missing)}")
    if raw.get("directed", False) is not False:
        raise ValueError("directed play is unsupported under Vornfall's autonomy rule; see RUNBOOK section 6 before migrating")
    if not isinstance(raw.get("api", PRODUCTION_API), str) or raw.get("api", PRODUCTION_API).rstrip('/') != PRODUCTION_API:
        raise ValueError("custom api is unsupported: bundled MCP and reference profiles use production; refusing a mixed-world configuration")
    for field in ("lock_port", "routine_wake_s", "rules_check_s", "long_loop_passes"):
        if field in raw and (type(raw[field]) is not int or raw[field] <= 0):
            raise ValueError(f"{field} must be a positive integer")
    if raw["lock_port"] > 65535:
        raise ValueError("lock_port must be at most 65535")
    if "min_wake_gap_s" in raw and (type(raw["min_wake_gap_s"]) is not int or raw["min_wake_gap_s"] < 0):
        raise ValueError("min_wake_gap_s must be a non-negative integer")
    if "api" in raw:
        raw["api"] = raw["api"].rstrip('/')
    return Config(agent_dir=agent_dir, **raw)
