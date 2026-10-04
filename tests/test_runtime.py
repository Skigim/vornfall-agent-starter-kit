import pytest
import sys
from types import SimpleNamespace

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


def test_command_substitutes_key_var_name():
    p = {"wake": ["{cli}", "-c", "x=\"__KEY_VAR__\""]}
    assert runtime.command(p, "wake", "c", key_var="VF_K") == ["c", "-c", "x=\"VF_K\""]


REQUIRED = {"name", "label", "cli", "instructions_file", "wake", "register", "probe", "prompt_via",
            "files", "models_hint", "efforts", "tested"}


def test_all_profiles_complete():
    names = []
    for p in runtime.list_profiles():
        names.append(p["name"])
        assert REQUIRED <= set(p), (p["name"], REQUIRED - set(p))
        for target, template in p["files"].items():
            assert (p["dir"] / template).exists(), (p["name"], template)
    assert {"claude", "gemini", "codex", "custom"} <= set(names)


def test_exit_zero_without_completion_marker_is_incomplete(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cli_path='', agent_dir=tmp_path, model='', effort='')
    monkeypatch.setattr(runtime, 'find_cli', lambda *a: 'fake')
    monkeypatch.setattr(runtime, 'captured_registration', lambda *a: (True, 'exit 0', 'SUMMARY: tools unavailable'))
    ok, status, out = runtime.run({'wake': ['{cli}']}, 'wake', cfg, 'wake', '')
    assert not ok and 'incomplete turn' in status


def test_completion_marker_and_environment_redaction(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cli_path='', agent_dir=tmp_path, model='', effort='')
    monkeypatch.setattr(runtime, 'find_cli', lambda *a: 'fake')
    monkeypatch.setenv('OTHER_CHARACTER', 'vf_dev_other_fixture')
    monkeypatch.setattr(runtime, 'get_key', lambda var: 'vf_dev_active_fixture')
    def capture(argv, prompt, via_arg, cwd, env, timeout, path):
        assert 'OTHER_CHARACTER' not in env
        assert env['ACTIVE'] == 'vf_dev_active_fixture'
        return True, 'exit 0', 'SUMMARY: ok\nVORNFALL_TURN_COMPLETE\nvf_dev_active_fixture'
    monkeypatch.setattr(runtime, 'captured_registration', capture)
    ok, _, out = runtime.run({'wake': ['{cli}']}, 'wake', cfg, 'wake', 'ACTIVE')
    assert ok and 'vf_dev_' not in out


def test_local_process_timeout_keeps_private_registration_output(tmp_path):
    capture = tmp_path / 'private'
    ok, status, out = runtime.captured_registration(
        [sys.executable, '-c', "import time; print('KEY: vf_dev_offline_fixture', flush=True); time.sleep(30)"],
        '', False, tmp_path, {}, 2, capture)
    assert not ok and status == 'timed out'
    assert 'vf_dev_offline_fixture' in out and capture.read_text() == out
