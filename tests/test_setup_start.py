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
