"""The generated half of the world reference: fetch the live rules, write intents.md, diff rules."""
import json
import re
import urllib.request
from pathlib import Path

STAMP_RE = re.compile(r"rules_version `([0-9A-Za-z]+)`")
MCP_URL = "https://vornfall.com/mcp"


def _short(text, n=90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _first_sentence(text) -> str:
    text = " ".join(str(text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return _short(m.group(1) if m else text, 140)


def intents_md(rules, tools=()) -> str:
    v = rules.get("rules_version", "?")
    lines = [
        "### Every intent, from the live rules",
        "",
        f"Generated from rules_version `{v}` by refresh-reference.py. Do not edit by hand.",
        "",
        "One line per intent: its type, a working example, then its fields. Send intents inside",
        '`{"plan": [...]}`, each one flat, its fields beside `"type"`.',
        "",
    ]
    for i in rules.get("intents", []):
        example = (i.get("examples") or [i.get("example")])[0]
        rep = " (repeating)" if i.get("repeating") else ""
        lines.append(f"- **{i['type']}**{rep}: `{json.dumps(example, ensure_ascii=False)}`")
        params = i.get("params") or {}
        if params:
            lines.append("  fields: " + "; ".join(f"`{k}` {_short(v)}" for k, v in params.items()))
    lim = rules.get("limits", {})
    lines += ["", "#### Limits", "",
              f"plan intents {lim.get('plan_max_intents')}, setup intents {lim.get('plan_setup_max_intents')}, "
              f"action ticks {lim.get('action_max_ticks')}, pack slots {lim.get('inventory_slots')}, "
              f"notebook bytes {lim.get('notebook_max_bytes')}, thought characters {lim.get('thought_max_chars')}"]
    if tools:
        lines += ["", "#### Your game tools", ""]
        lines += [f"- `{t['name']}`: {_first_sentence(t.get('description'))}" for t in tools]
    return "\n".join(lines) + "\n"


def reference_stamp(directory):
    try:
        text = (Path(directory) / "intents.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = STAMP_RE.search(text)
    return m.group(1) if m else None


def rules_diff(old, new) -> list:
    out = []
    if old.get("rules_version") != new.get("rules_version"):
        out.append(f"rules_version {old.get('rules_version')} -> {new.get('rules_version')}")
    oi = {i["type"]: i for i in old.get("intents", [])}
    ni = {i["type"]: i for i in new.get("intents", [])}
    out += [f"intent added: {t}" for t in sorted(ni.keys() - oi.keys())]
    out += [f"intent removed: {t}" for t in sorted(oi.keys() - ni.keys())]
    for t in sorted(oi.keys() & ni.keys()):
        if oi[t].get("params") != ni[t].get("params"):
            out.append(f"intent fields changed: {t}")
        if oi[t].get("notes") != ni[t].get("notes"):
            out.append(f"intent notes changed: {t}")
    oe = {e["code"] for e in old.get("errors", [])}
    ne = {e["code"] for e in new.get("errors", [])}
    out += [f"error added: {c}" for c in sorted(ne - oe)]
    out += [f"error removed: {c}" for c in sorted(oe - ne)]
    ol, nl = old.get("limits", {}), new.get("limits", {})
    for k in sorted(set(ol) | set(nl)):
        if ol.get(k) != nl.get(k):
            out.append(f"limit {k}: {ol.get(k)} -> {nl.get(k)}")
    return out


def _get_json(url, key=None, timeout=30) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.load(r)


def fetch_rules(api, key) -> dict:
    return _get_json(f"{api}/meta/rules", key)


def fetch_status(api) -> dict:
    return _get_json(f"{api}/status")


def parse_mcp_body(body, content_type):
    if not body.strip():
        return None
    if "text/event-stream" in (content_type or ""):
        datas = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        body = datas[-1] if datas else ""
        if not body:
            return None
    return json.loads(body)


def mcp_post(url, payload, key=None, session=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        sid = r.headers.get("Mcp-Session-Id") or session
        return sid, parse_mcp_body(r.read().decode("utf-8"), r.headers.get("Content-Type", ""))


def fetch_mcp_tools(url=MCP_URL, key=None) -> list:
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "vornfall-kit", "version": "1"}}}
    sid, _ = mcp_post(url, init, key)
    mcp_post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, key, sid)
    _, resp = mcp_post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, key, sid)
    return ((resp or {}).get("result") or {}).get("tools") or []
