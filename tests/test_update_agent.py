import importlib.util

from vfkit import KIT_DIR

spec = importlib.util.spec_from_file_location("update_agent", KIT_DIR / "update-agent.py")
update_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_agent)


def agent_folder(tmp_path):
    dest = tmp_path / "agent"
    dest.mkdir()
    (dest / "watcher.json").write_text('{"name": "T", "runtime": "claude", "key_var": "K", "lock_port": 1}\n',
                                       encoding="utf-8")
    for part in ("instructions.md", "intents.md", "world-reference.md", "vornfall-guide.md",
                 "rules-snapshot.json"):
        (dest / part).write_text("old " + part, encoding="utf-8")
    (dest / "persona.md").write_text("MY OWN PERSONA", encoding="utf-8")
    return dest


def test_update_copies_template_parts_and_keeps_persona_and_config(tmp_path):
    dest = agent_folder(tmp_path)
    changed, built = update_agent.update(dest)
    template = (KIT_DIR / "template" / "instructions.md").read_text(encoding="utf-8")
    assert (dest / "instructions.md").read_text(encoding="utf-8") == template
    assert set(changed) == set(update_agent.SHARED)
    assert (dest / "persona.md").read_text(encoding="utf-8") == "MY OWN PERSONA"
    assert "runtime" in (dest / "watcher.json").read_text(encoding="utf-8")
    assert "MY OWN PERSONA" in built.read_text(encoding="utf-8")


def test_update_is_a_no_op_when_current(tmp_path):
    dest = agent_folder(tmp_path)
    update_agent.update(dest)
    changed, _ = update_agent.update(dest)
    assert changed == []
