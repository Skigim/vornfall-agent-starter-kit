import importlib.util
import sys

from vfkit import KIT_DIR

sys.path.insert(0, str(KIT_DIR / "setup"))
spec = importlib.util.spec_from_file_location("register", KIT_DIR / "setup" / "register.py")
register = importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)

OUT = """Chose a name.
NAME: Brannoc Vale
AGENT: a_7hk2
KEY: vf_live_k3x9_abcdef
CLAIM: https://vornfall.com/claim/cl_9f3m
"""


def test_parse_registration():
    assert register.parse_registration(OUT) == {
        "name": "Brannoc Vale", "agent": "a_7hk2", "key": "vf_live_k3x9_abcdef",
        "claim": "https://vornfall.com/claim/cl_9f3m"}


def test_parse_registration_without_key():
    got = register.parse_registration("NAME taken three times; stopped.")
    assert got["key"] is None and got["agent"] is None


def test_prompt_lets_the_agent_choose_and_answer():
    p = register.registration_prompt("model-x")
    assert 'declared_model "model-x"' in p
    assert "Choose your own name" in p
    assert "Answer the registration challenge yourself" in p
    assert "Do not spawn" in p
