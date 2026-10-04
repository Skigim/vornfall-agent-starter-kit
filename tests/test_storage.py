import pytest

from vfkit import storage


def test_failed_atomic_replace_retains_old_file_and_removes_temporary(tmp_path, monkeypatch):
    target = tmp_path / 'state.json'
    target.write_text('old', encoding='utf-8')
    def fail(*args):
        raise OSError('replacement failed')
    monkeypatch.setattr(storage.os, 'replace', fail)
    with pytest.raises(OSError, match='replacement failed'):
        storage.atomic_write(target, 'new')
    assert target.read_text(encoding='utf-8') == 'old'
    assert list(tmp_path.iterdir()) == [target]


def test_exclusive_lock_excludes_and_releases(tmp_path):
    lock = tmp_path / 'registration.lock'
    with storage.exclusive_lock(lock):
        with pytest.raises(OSError):
            with storage.exclusive_lock(lock):
                pytest.fail('second lock acquired')
    with storage.exclusive_lock(lock):
        pass


def test_exclusive_lock_releases_after_exception(tmp_path):
    lock = tmp_path / 'registration.lock'
    with pytest.raises(RuntimeError):
        with storage.exclusive_lock(lock):
            raise RuntimeError('interrupted')
    with storage.exclusive_lock(lock):
        pass
