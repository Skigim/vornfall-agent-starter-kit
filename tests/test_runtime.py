import pytest

from vfkit import runtime


def test_load_claude_profile():
    p = runtime.load_profile("claude")
    assert p["instructions_file"] == "CLAUDE.md"
    assert p["dir"].name == "claude"
    assert (p["dir"] / "settings.json").exists()


def test_unknown_profile():
    with pytest.raises(ValueError, match="nosuch"):
        runtime.load_profile("nosuch")


def test_command_substitution_and_empty_model_dropped():
    p = {"wake": ["{cli}", "-p", "{prompt}", "-m", "{model}", "--effort={effort}"]}
    assert runtime.command(p, "wake", "/bin/x", model="m1", effort="low", prompt="hi") == \
        ["/bin/x", "-p", "hi", "-m", "m1", "--effort=low"]
    assert runtime.command(p, "wake", "/bin/x", prompt="hi") == ["/bin/x", "-p", "hi"]


def test_find_cli(monkeypatch, tmp_path):
    p = {"cli": "nosuchcli-xyz"}
    with pytest.raises(FileNotFoundError):
        runtime.find_cli(p)
    fake = tmp_path / "tool"
    fake.write_text("")
    assert runtime.find_cli(p, str(fake)) == str(fake)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "/usr/bin/" + name)
    assert runtime.find_cli({"cli": "gemini"}) == "/usr/bin/gemini"


def test_render_template():
    text = '{"k": "${__KEY_VAR__}", "m": "__MODEL__", "e": "__EFFORT__"}'
    assert runtime.render_template(text, "VF_K", "opus", "low") == '{"k": "${VF_K}", "m": "opus", "e": "low"}'


def test_list_profiles_includes_claude():
    assert "claude" in [p["name"] for p in runtime.list_profiles()]
