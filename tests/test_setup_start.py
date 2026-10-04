import importlib.util
import socket
import sys

from vfkit import KIT_DIR

sys.path.insert(0, str(KIT_DIR / "setup"))
spec = importlib.util.spec_from_file_location("start_watcher", KIT_DIR / "setup" / "start_watcher.py")
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)


def test_port_in_use():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    assert start.port_in_use(port)
    s.close()
    assert not start.port_in_use(port)


def test_last_summary():
    text = "=== a ===\nSUMMARY: first\n\n=== b ===\nthinking\nSUMMARY: second one\n"
    assert start.last_summary(text) == "SUMMARY: second one"
    assert start.last_summary("no summary") is None


import pytest
from types import SimpleNamespace


@pytest.fixture
def startup(tmp_path, monkeypatch):
    cfg = SimpleNamespace(agent_dir=tmp_path, runtime='fake', lock_port=12345, name='fixture')
    clock = {'now': 0.0}
    child = SimpleNamespace(poll=lambda: None)
    launches = []
    log = tmp_path / 'logs/watcher.log'
    log.parent.mkdir()
    def launch(folder, **kwargs):
        launches.append((folder, kwargs))
        log.write_text('watcher started\n', encoding='utf-8')
        return child
    monkeypatch.setattr(start, 'load_config', lambda folder: cfg)
    monkeypatch.setattr(start, 'load_profile', lambda runtime: {'tested': True})
    monkeypatch.setattr(start, 'port_in_use', lambda port: bool(launches))
    monkeypatch.setattr(start, 'launch', launch)
    monkeypatch.setattr(start.time, 'time', lambda: clock['now'])
    def sleep(seconds):
        clock['now'] += seconds
    monkeypatch.setattr(start.time, 'sleep', sleep)
    monkeypatch.setattr(sys, 'argv', ['start_watcher.py', '--dir', str(tmp_path), '--wait-first-wake', '10'])
    return cfg, clock, child, launches, log


def test_unverified_adapter_rejected_without_launch(startup, monkeypatch):
    cfg, clock, child, launches, log = startup
    monkeypatch.setattr(start, 'load_profile', lambda runtime: {'tested': False})
    with pytest.raises(SystemExit, match='runtime is unverified'):
        start.main()
    assert not launches


def test_failed_first_wake_is_not_gameplay_success(startup, monkeypatch, capsys):
    cfg, clock, child, launches, log = startup
    def sleep(seconds):
        clock['now'] += seconds
        if launches and seconds == 5:
            with log.open('a', encoding='utf-8') as stream:
                stream.write('2026-10-03 wake done (exit 1, 2s)\n')
    monkeypatch.setattr(start.time, 'sleep', sleep)
    with pytest.raises(SystemExit, match='first decision failed or was incomplete'):
        start.main()
    assert 'gameplay readiness is not yet verified' in capsys.readouterr().out


def test_child_exit_during_startup_fails(startup):
    cfg, clock, child, launches, log = startup
    child.poll = lambda: 1
    with pytest.raises(SystemExit, match='watcher exited during startup'):
        start.main()
    assert len(launches) == 1


def test_first_wake_timeout_fails_unverified(startup, capsys):
    cfg, clock, child, launches, log = startup
    with pytest.raises(SystemExit, match='readiness is unverified'):
        start.main()
    assert clock['now'] >= 10
    assert 'gameplay readiness is not yet verified' in capsys.readouterr().out


def test_explicit_untested_opt_in_is_forwarded(startup, monkeypatch):
    cfg, clock, child, launches, log = startup
    monkeypatch.setattr(start, 'load_profile', lambda runtime: {'tested': False})
    monkeypatch.setattr(sys, 'argv', ['start_watcher.py', '--dir', str(cfg.agent_dir), '--allow-untested'])
    start.main()
    assert launches[0][1] == {'allow_untested': True}
