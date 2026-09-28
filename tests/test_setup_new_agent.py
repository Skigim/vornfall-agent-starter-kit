import importlib.util
import json
import socket
import sys

import pytest

from vfkit import KIT_DIR, keys

sys.path.insert(0, str(KIT_DIR / "setup"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, KIT_DIR / "setup" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


new_agent = load("new_agent")
check_prereqs = load("check_prereqs")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(keys, "_on_windows", lambda: False)
    monkeypatch.setenv("VORNFALL_KEYS_FILE", str(tmp_path / "keys.env"))
    monkeypatch.delenv("VF_NEW", raising=False)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_create_claude_agent(tmp_path):
    dest = tmp_path / "agent-one"
    new_agent.create_agent(dest, "claude", "VF_NEW", free_port(), "claude-opus-5-5", "low")
    cfg = json.loads((dest / "watcher.json").read_text(encoding="utf-8"))
    assert (cfg["runtime"], cfg["key_var"], cfg["model"], cfg["effort"]) == ("claude", "VF_NEW", "claude-opus-5-5", "low")
    assert "${VF_NEW}" in (dest / ".mcp.json").read_text(encoding="utf-8")
    settings = json.loads((dest / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "claude-opus-5-5" and settings["effortLevel"] == "low"
    text = (dest / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## On each wake" in text and "<!-- include:" not in text
    assert not (dest / "orders.md").exists()


def test_directed_creates_orders_and_goal(tmp_path):
    dest = tmp_path / "d"
    new_agent.create_agent(dest, "claude", "VF_NEW", free_port(), "m", "low", directed=True)
    assert (dest / "orders.md").exists() and (dest / "goal.md").exists()
    assert json.loads((dest / "watcher.json").read_text(encoding="utf-8"))["directed"] is True


def test_refuses_non_empty(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "file").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        new_agent.create_agent(tmp_path / "x", "claude", "VF_NEW", free_port(), "m", "low")


def test_refuses_inside_another_agent(tmp_path):
    outer = tmp_path / "outer"
    new_agent.create_agent(outer, "claude", "VF_NEW", free_port(), "m", "low")
    with pytest.raises(ValueError, match="inside"):
        new_agent.create_agent(outer / "inner", "claude", "VF_OTHER", free_port(), "m", "low")


def test_refuses_bad_effort_and_existing_key(tmp_path):
    with pytest.raises(ValueError, match="effort"):
        new_agent.create_agent(tmp_path / "a", "claude", "VF_NEW", free_port(), "m", "extreme")
    keys.store_key("VF_NEW", "vf_live_x")
    with pytest.raises(ValueError, match="already holds a key"):
        new_agent.create_agent(tmp_path / "b", "claude", "VF_NEW", free_port(), "m", "low")


def test_suggest():
    s = new_agent.suggest()
    assert s["port"] >= 47931 and s["key_var"].startswith("VORNFALL_API_KEY")


def test_check_python():
    assert check_prereqs.check_python((3, 12, 0))[0]
    assert not check_prereqs.check_python((3, 9, 0))[0]
