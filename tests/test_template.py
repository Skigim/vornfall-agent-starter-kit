import json
import re

from vfkit import KIT_DIR
from vfkit.instructions import INCLUDE_RE, flatten

TEMPLATE = KIT_DIR / "template"
FORBIDDEN = ("Wren", "Tobin", "Caelric", "Skigim", "Grimm", "Severin", "Anthropic")
KIT_AUTHORED = ["template/instructions.md", "template/persona.md", "template/world-reference.md"]


def test_every_include_exists():
    for line in (TEMPLATE / "instructions.md").read_text(encoding="utf-8").splitlines():
        m = INCLUDE_RE.match(line.strip())
        if m:
            assert (TEMPLATE / m.group(1)).exists(), m.group(1)


def test_flattens():
    text = flatten(TEMPLATE)
    for heading in ("## Your notebook", "## Your first wake", "## On each wake", "## Planning a plan",
                    "## Spending your owner's quota well", "## Safety", "## Who you are",
                    "### World reference", "#### Writing, maps and surveys"):
        assert heading in text, heading
    assert "almost blank" in text
    assert "<!-- include:" not in text


def test_no_named_agents_or_vendors():
    for rel in KIT_AUTHORED:
        text = (KIT_DIR / rel).read_text(encoding="utf-8")
        for word in FORBIDDEN:
            assert not re.search(rf"\b{word}\b", text), f"{word} in {rel}"


def test_watcher_defaults_parse():
    raw = json.loads((TEMPLATE / "watcher.json").read_text(encoding="utf-8"))
    assert raw["min_wake_gap_s"] == 0 and raw["routine_wake_s"] == 3600 and raw["directed"] is False
