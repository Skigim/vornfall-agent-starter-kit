"""The generated half of the world reference: fetch the live rules, write intents.md, diff rules."""
import json
import re
import urllib.request
from pathlib import Path

STAMP_RE = re.compile(r"rules_version `([0-9A-Za-z]+)`")
MCP_URL = "https://vornfall.com/mcp"
GUIDE_URL = "https://vornfall.com/skill.md"


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
        variants = i.get("examples") or []
        example = i.get("example") or (variants[0] if variants else None)
        rep = " (repeating)" if i.get("repeating") else ""
        shown = [example] + [v for v in variants if v != example]
        lines.append(f"- **{i['type']}**{rep}: " + "; ".join(f"`{json.dumps(e, ensure_ascii=False)}`" for e in shown))
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
    # Keep familiar intent/limit summaries, then recursively cover everything else.
    def walk(a, b, path):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), f"{path}.{key}" if path else key)
        elif isinstance(a, list) and isinstance(b, list):
            for index in range(max(len(a), len(b))):
                walk(a[index] if index < len(a) else None,
                     b[index] if index < len(b) else None, f"{path}[{index}]")
        else:
            out.append(f"{path}: {_short(json.dumps(a, ensure_ascii=False))} -> "
                       f"{_short(json.dumps(b, ensure_ascii=False))}")
    for t in sorted(oi.keys() & ni.keys()):
        walk({k: v for k, v in oi[t].items() if k not in ('params', 'notes')},
             {k: v for k, v in ni[t].items() if k not in ('params', 'notes')}, f"intent {t}")
    old_errors = {e['code']: e for e in old.get('errors', [])}
    new_errors = {e['code']: e for e in new.get('errors', [])}
    for code in sorted(old_errors.keys() & new_errors.keys()):
        walk(old_errors[code], new_errors[code], f"error {code}")
    walk({k: v for k, v in old.items() if k not in ('rules_version', 'intents', 'errors', 'limits')},
         {k: v for k, v in new.items() if k not in ('rules_version', 'intents', 'errors', 'limits')}, '')
    return out


def _get_json(url, key=None, timeout=30) -> dict:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.load(r)


def fetch_rules(api, key) -> dict:
    return _get_json(f"{api}/meta/rules", key)


def fetch_guide(url=GUIDE_URL, timeout=30) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8").replace("\r\n", "\n")


def guide_diff(old, new) -> list:
    """One line saying whether the joining guide changed, and by how many lines."""
    if old == new:
        return []
    ol, nl = old.splitlines(), new.splitlines()
    gone = sum(1 for l in ol if l not in set(nl))
    came = sum(1 for l in nl if l not in set(ol))
    return [f"vornfall-guide.md changed: {came} lines added, {gone} removed"]


def fetch_status(api) -> dict:
    return _get_json(f"{api}/status")


def parse_mcp_body(body, content_type):
    if not body.strip():
        return None
    if "text/event-stream" in (content_type or ""):
        messages, data = [], []
        for line in body.splitlines() + ['']:
            if line.startswith('data:'):
                data.append(line[5:].lstrip(' '))
            elif not line and data:
                messages.append(json.loads('\n'.join(data)))
                data = []
        # Notifications may accompany a response; choose the last response.
        replies = [m for m in messages if isinstance(m, dict) and ('result' in m or 'error' in m)]
        return replies[-1] if replies else None
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
    def result(response):
        if not isinstance(response, dict) or 'error' in response:
            raise ValueError(f"MCP request failed: {(response or {}).get('error', 'missing response') if isinstance(response, dict) or response is None else 'invalid response'}")
        if not isinstance(response.get('result'), dict):
            raise ValueError('MCP request returned no result object')
        return response['result']
    sid, response = mcp_post(url, init, key)
    result(response)
    mcp_post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, key, sid)
    tools, cursor, seen = [], None, set()
    while True:
        payload = {"jsonrpc": "2.0", "id": 2 + len(seen), "method": "tools/list"}
        if cursor:
            payload['params'] = {'cursor': cursor}
        _, response = mcp_post(url, payload, key, sid)
        page = result(response)
        if not isinstance(page.get('tools'), list):
            raise ValueError('MCP tools/list returned no tools list')
        tools.extend(page['tools'])
        cursor = page.get('nextCursor')
        if not cursor:
            return tools
        if cursor in seen:
            raise ValueError('MCP tools/list repeated a pagination cursor')
        seen.add(cursor)
