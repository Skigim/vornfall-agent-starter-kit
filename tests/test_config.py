import json

import pytest

from vfkit.config import Config, load_config


def write(tmp_path, data):
    (tmp_path / "watcher.json").write_text(json.dumps(data), encoding="utf-8")


def test_loads_required_and_defaults(tmp_path):
    write(tmp_path, {"name": "a", "key_var": "VF_KEY", "lock_port": 47931})
    cfg = load_config(tmp_path)
    assert cfg == Config(agent_dir=tmp_path.resolve(), name="a", key_var="VF_KEY", lock_port=47931)
    assert cfg.runtime == "claude"
    assert cfg.routine_wake_s == 3600
    assert cfg.min_wake_gap_s == 0
    assert cfg.directed is False


def test_overrides(tmp_path):
    write(tmp_path, {"name": "a", "key_var": "K", "lock_port": 1, "runtime": "gemini",
                     "model": "m", "min_wake_gap_s": 600, "directed": True})
    cfg = load_config(tmp_path)
    assert (cfg.runtime, cfg.model, cfg.min_wake_gap_s, cfg.directed) == ("gemini", "m", 600, True)


def test_unknown_key_rejected(tmp_path):
    write(tmp_path, {"name": "a", "key_var": "K", "lock_port": 1, "colour": "red"})
    with pytest.raises(ValueError, match="colour"):
        load_config(tmp_path)


def test_missing_required_rejected(tmp_path):
    write(tmp_path, {"name": "a", "lock_port": 1})
    with pytest.raises(ValueError, match="key_var"):
        load_config(tmp_path)
