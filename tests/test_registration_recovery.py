"""Offline registration recovery; no real key stores or runtime calls."""
import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from vfkit import KIT_DIR

sys.path.insert(0, str(KIT_DIR / 'setup'))
spec = importlib.util.spec_from_file_location('registration_recovery', KIT_DIR / 'setup/register.py')
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)
KEY = 'vf_dev_offline_recovery_fixture'
OUTPUT = f'NAME: Fixture\nAGENT: a_fixture\nKEY: {KEY}\nCLAIM: https://vornfall.com/claim/fixture\n'


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    (tmp_path / 'watcher.json').write_text(json.dumps({'name': 'pending'}), encoding='utf-8')
    monkeypatch.setattr(registration, 'load_profile', lambda runtime: {})
    monkeypatch.setattr(registration, 'swap_files', lambda *args, **kwargs: None)
    monkeypatch.setattr(registration, 'has_key', lambda var: False)
    monkeypatch.setattr(registration, 'get_key', lambda var: '')
    monkeypatch.setattr(registration, 'store_key', lambda var, key: 'fake store')
    return SimpleNamespace(agent_dir=tmp_path, runtime='fake', model='fake', key_var='FIXTURE_KEY')


def pending(cfg, output=OUTPUT):
    capture = cfg.agent_dir / 'registration-output.private'
    capture.write_text(output, encoding='utf-8')
    (cfg.agent_dir / 'registration-pending.json').write_text('{}', encoding='utf-8')
    return capture


@pytest.mark.parametrize('status', ['timed out', 'exit 1'])
def test_failed_runtime_capture_is_recovered(cfg, monkeypatch, capsys, status):
    calls = []
    def run(*args, capture_path, **kwargs):
        calls.append(True)
        capture_path.write_text(OUTPUT, encoding='utf-8')
        return False, status, OUTPUT
    monkeypatch.setattr(registration, 'run', run)
    registration.register_or_recover(cfg)
    assert calls == [True]
    assert not (cfg.agent_dir / 'registration-pending.json').exists()
    assert KEY not in capsys.readouterr().out
    assert KEY not in (cfg.agent_dir / 'logs/register.log').read_text(encoding='utf-8')


def test_interrupted_journal_never_invokes_runtime(cfg, monkeypatch):
    pending(cfg)
    monkeypatch.setattr(registration, 'run', lambda *args, **kwargs: pytest.fail('duplicate registration'))
    registration.register_or_recover(cfg)
    assert json.loads((cfg.agent_dir / 'watcher.json').read_text())['name'] == 'Fixture'


@pytest.mark.parametrize('output', ['', 'NAME: Fixture\nAGENT: a_fixture\n'])
def test_missing_key_refuses_duplicate_registration(cfg, monkeypatch, output):
    capture = pending(cfg, output)
    monkeypatch.setattr(registration, 'run', lambda *args, **kwargs: pytest.fail('duplicate registration'))
    with pytest.raises(SystemExit, match='Do not register again'):
        registration.register_or_recover(cfg)
    assert capture.exists()
    assert (cfg.agent_dir / 'registration-pending.json').exists()


def test_multiple_keys_refused_before_storage(cfg, monkeypatch):
    capture = pending(cfg, OUTPUT + 'vf_dev_different_fixture')
    monkeypatch.setattr(registration, 'store_key', lambda *args: pytest.fail('ambiguous key stored'))
    with pytest.raises(ValueError, match='multiple different keys'):
        registration.recover(cfg, capture, 'interrupted')
    assert capture.exists()


def test_storage_failure_keeps_private_capture_and_journal(cfg, monkeypatch):
    capture = pending(cfg)
    def fail(*args):
        raise OSError('fake store unavailable')
    monkeypatch.setattr(registration, 'store_key', fail)
    with pytest.raises(OSError, match='fake store unavailable'):
        registration.recover(cfg, capture, 'interrupted')
    assert capture.read_text(encoding='utf-8') == OUTPUT
    assert (cfg.agent_dir / 'registration-pending.json').exists()
    assert not (cfg.agent_dir / 'logs/register.log').exists()


def test_durable_key_precedes_redacted_log_and_capture_cleanup(cfg, monkeypatch):
    capture = pending(cfg)
    stored = []
    def store(var, key):
        assert capture.exists()
        assert (cfg.agent_dir / 'registration-pending.json').exists()
        assert not (cfg.agent_dir / 'logs/register.log').exists()
        stored.append((var, key))
        return 'fake store'
    monkeypatch.setattr(registration, 'store_key', store)
    got, where = registration.recover(cfg, capture, 'interrupted')
    assert stored == [('FIXTURE_KEY', KEY)]
    assert got['key'] is None and where == 'fake store'
    assert not capture.exists()
    assert not (cfg.agent_dir / 'registration-pending.json').exists()
    log = (cfg.agent_dir / 'logs/register.log').read_text(encoding='utf-8')
    assert KEY not in log and '[KEY REDACTED]' in log


def test_recovery_never_overwrites_rotated_key(cfg, monkeypatch):
    capture = pending(cfg)
    monkeypatch.setattr(registration, 'get_key', lambda var: 'vf_dev_rotated_fixture')
    monkeypatch.setattr(registration, 'store_key', lambda *args: pytest.fail('rotated key overwritten'))
    with pytest.raises(ValueError, match='refusing to overwrite'):
        registration.recover(cfg, capture, 'interrupted')
    assert capture.exists()


def test_cleanup_crash_recovers_without_capture_or_new_registration(cfg, monkeypatch):
    identity = {'name': 'Fixture', 'agent': 'a_fixture', 'claim': 'https://vornfall.com/claim/fixture', 'key': None}
    journal = cfg.agent_dir / 'registration-pending.json'
    journal.write_text(json.dumps({'status': 'stored', 'identity': identity}))
    monkeypatch.setattr(registration, 'get_key', lambda var: KEY)
    monkeypatch.setattr(registration, 'run', lambda *a, **kw: pytest.fail('duplicate registration'))
    registration.register_or_recover(cfg)
    assert not journal.exists()
