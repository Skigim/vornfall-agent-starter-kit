import importlib.util
import json

import pytest

from vfkit import KIT_DIR

spec = importlib.util.spec_from_file_location("refresh_reference", KIT_DIR / "refresh-reference.py")
refresh_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh_mod)

OLD = {"rules_version": "aaa", "intents": [{"type": "wait", "example": {"type": "wait", "ticks": 5}}],
       "errors": [], "limits": {}}
NEW = {**OLD, "rules_version": "bbb"}


def test_refresh_writes_and_diffs(tmp_path):
    d = tmp_path / "agent"
    d.mkdir()
    (d / "rules-snapshot.json").write_text(json.dumps(OLD), encoding="utf-8")
    (d / "reference-stale.flag").write_text("bbb", encoding="utf-8")
    diff = refresh_mod.refresh([d], NEW, [])
    assert diff == ["rules_version aaa -> bbb"]
    assert "rules_version `bbb`" in (d / "intents.md").read_text(encoding="utf-8")
    assert json.loads((d / "rules-snapshot.json").read_text(encoding="utf-8"))["rules_version"] == "bbb"
    assert not (d / "reference-stale.flag").exists()


def test_refresh_rebuilds_agent_instructions(tmp_path):
    d = tmp_path / "agent"
    d.mkdir()
    (d / "instructions.md").write_text("top\n<!-- include: intents.md -->\n", encoding="utf-8")
    (d / "watcher.json").write_text(json.dumps({"name": "a", "key_var": "K", "lock_port": 1,
                                                "runtime": "claude"}), encoding="utf-8")
    refresh_mod.refresh([d], NEW, [])
    assert "rules_version `bbb`" in (d / "CLAUDE.md").read_text(encoding="utf-8")


def test_refresh_skips_template_placeholder_runtime(tmp_path):
    d = tmp_path / "template"
    d.mkdir()
    (d / "instructions.md").write_text("top\n<!-- include: intents.md -->\n", encoding="utf-8")
    (d / "watcher.json").write_text(json.dumps({"name": "__NAME__", "key_var": "__KEY_VAR__", "lock_port": 0,
                                                "runtime": "__RUNTIME__"}), encoding="utf-8")
    refresh_mod.refresh([d], NEW, [])
    assert "rules_version `bbb`" in (d / "intents.md").read_text(encoding="utf-8")
    assert not (d / "CLAUDE.md").exists()


def test_refresh_raises_on_unknown_runtime(tmp_path):
    d = tmp_path / "agent"
    d.mkdir()
    (d / "instructions.md").write_text("top\n<!-- include: intents.md -->\n", encoding="utf-8")
    (d / "watcher.json").write_text(json.dumps({"name": "a", "key_var": "K", "lock_port": 1,
                                                "runtime": "nosuch"}), encoding="utf-8")
    with pytest.raises(ValueError, match="no runtime profile named"):
        refresh_mod.refresh([d], NEW, [])
