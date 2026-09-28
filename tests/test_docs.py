import re

from vfkit import KIT_DIR

FORBIDDEN = ("Wren", "Tobin", "Caelric", "Skigim", "Grimm", "Severin")
DOCS = ["README.md", "RUNBOOK.md", "SETUP.md", "skills/vornfall-agent-setup/SKILL.md"]


def test_skill_matches_setup_guide():
    skill = (KIT_DIR / "skills/vornfall-agent-setup/SKILL.md").read_text(encoding="utf-8")
    setup = (KIT_DIR / "SETUP.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: vornfall-agent-setup\ndescription: ")
    assert "## Hard rules" in skill and "## Steps" in skill
    assert skill.split("## How to ask", 1)[1] == setup.split("## How to ask", 1)[1]


def test_docs_name_no_existing_agents():
    for rel in DOCS:
        text = (KIT_DIR / rel).read_text(encoding="utf-8")
        for word in FORBIDDEN:
            assert not re.search(rf"\b{word}\b", text), f"{word} in {rel}"


def test_every_script_the_docs_mention_exists():
    for rel in DOCS:
        text = (KIT_DIR / rel).read_text(encoding="utf-8")
        for script in set(re.findall(r"(setup/\w+\.py|[\w-]+\.py)", text)):
            assert (KIT_DIR / script).exists() or (KIT_DIR / "setup" / script).exists(), f"{script} in {rel}"
