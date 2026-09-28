import pytest

from vfkit import keys

KEY = "vf_live_abc123_XYZ"


@pytest.fixture
def posix_store(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "_on_windows", lambda: False)
    monkeypatch.setenv("VORNFALL_KEYS_FILE", str(tmp_path / "keys.env"))
    monkeypatch.delenv("VF_TEST_KEY", raising=False)
    return tmp_path / "keys.env"


def test_redact():
    assert keys.redact(f"key {KEY} and vf_dev_q1") == "key [KEY REDACTED] and [KEY REDACTED]"
    assert keys.redact(None) == ""


def test_store_and_get_roundtrip(posix_store):
    where = keys.store_key("VF_TEST_KEY", KEY)
    assert where == str(posix_store)
    assert keys.get_key("VF_TEST_KEY") == KEY
    assert keys.has_key("VF_TEST_KEY")


def test_store_keeps_other_keys(posix_store):
    keys.store_key("VF_A", "vf_live_a")
    keys.store_key("VF_B", "vf_live_b")
    assert keys.get_key("VF_A") == "vf_live_a"
    assert keys.get_key("VF_B") == "vf_live_b"


def test_env_fallback(posix_store, monkeypatch):
    monkeypatch.setenv("VF_TEST_KEY", KEY)
    assert keys.get_key("VF_TEST_KEY") == KEY


def test_missing_is_empty(posix_store):
    assert keys.get_key("VF_TEST_KEY") == ""
    assert not keys.has_key("VF_TEST_KEY")


@pytest.mark.parametrize("var,value", [("VF_X", "not-a-key"), ("bad name", KEY), ("VF_X", KEY + " extra")])
def test_store_rejects(posix_store, var, value):
    with pytest.raises(ValueError):
        keys.store_key(var, value)
