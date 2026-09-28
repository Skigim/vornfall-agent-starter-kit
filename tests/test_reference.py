from vfkit.reference import intents_md, parse_mcp_body, reference_stamp, rules_diff

RULES = {
    "rules_version": "abc123",
    "intents": [
        {"type": "gather", "repeating": True,
         "examples": [{"type": "gather", "resource": "pine_tree", "until": {"count": 30}}],
         "params": {"resource": "resource name or site type", "until": "optional: {\"count\":30}"},
         "notes": "n1"},
        {"type": "deposit", "example": {"type": "deposit", "items": "all"},
         "params": {"items": "all or item/count map"}, "notes": "n2"},
    ],
    "errors": [{"code": "MISSING_ITEM", "http": 422}, {"code": "NO_TARGET", "http": 422}],
    "limits": {"plan_max_intents": 5, "plan_setup_max_intents": 3, "action_max_ticks": 600,
               "inventory_slots": 24, "notebook_max_bytes": 4096, "thought_max_chars": 200},
}


def test_intents_md_and_stamp(tmp_path):
    text = intents_md(RULES, [{"name": "act", "description": "Send a plan. More words here."}])
    assert "Generated from rules_version `abc123`" in text
    assert '- **gather** (repeating): `{"type": "gather", "resource": "pine_tree", "until": {"count": 30}}`' in text
    assert "- **deposit**:" in text
    assert "plan intents 5" in text
    assert "- `act`: Send a plan." in text
    (tmp_path / "intents.md").write_text(text, encoding="utf-8")
    assert reference_stamp(tmp_path) == "abc123"
    assert reference_stamp(tmp_path / "missing") is None


def test_rules_diff():
    new = {**RULES, "rules_version": "def456",
           "intents": RULES["intents"][:1] + [{"type": "farm", "params": {}, "notes": ""}],
           "errors": [{"code": "MISSING_ITEM"}, {"code": "LEVEL_BAND"}],
           "limits": {**RULES["limits"], "inventory_slots": 28}}
    new["intents"][0] = {**new["intents"][0], "params": {"resource": "changed"}}
    assert rules_diff(RULES, new) == [
        "rules_version abc123 -> def456",
        "intent added: farm",
        "intent removed: deposit",
        "intent fields changed: gather",
        "error added: LEVEL_BAND",
        "error removed: NO_TARGET",
        "limit inventory_slots: 24 -> 28",
    ]


def test_parse_mcp_body():
    assert parse_mcp_body('{"result": 1}', "application/json") == {"result": 1}
    sse = 'event: message\ndata: {"result": {"tools": []}}\n\n'
    assert parse_mcp_body(sse, "text/event-stream") == {"result": {"tools": []}}
    assert parse_mcp_body("", "application/json") is None
