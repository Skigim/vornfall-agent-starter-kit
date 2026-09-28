"""Check what launching an agent needs. Usage: python setup/check_prereqs.py --runtime NAME"""
import argparse
import subprocess
import sys

import _kit  # noqa: F401

from vfkit.reference import MCP_URL, mcp_post
from vfkit.runtime import find_cli, load_profile


def check_python(version_info=sys.version_info):
    ok = tuple(version_info[:2]) >= (3, 10)
    return ok, f"Python {version_info[0]}.{version_info[1]}" + ("" if ok else ": 3.10 or newer is needed")


def check_cli(profile):
    try:
        cli = find_cli(profile)
    except FileNotFoundError as e:
        return False, str(e)
    try:
        r = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
        return r.returncode == 0, f"{profile['label']}: {(r.stdout or r.stderr).strip()[:80]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{profile['label']} found at {cli} but did not run: {e}"


def check_mcp(url=MCP_URL):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "vornfall-kit", "version": "1"}}}
    try:
        mcp_post(url, init)
        return True, f"Vornfall MCP server reachable at {url}"
    except Exception as e:
        return False, f"Vornfall MCP server not reachable at {url}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    profile = load_profile(ap.parse_args().runtime)
    results = [check_python(), check_cli(profile), check_mcp()]
    if not profile.get("tested"):
        results.append((True, f"note: the {profile['label']} profile is untested: see runtimes/{profile['name']}/README.md"))
    for ok, msg in results:
        print(("OK   " if ok else "FAIL ") + msg)
    sys.exit(0 if all(ok for ok, _ in results) else 1)


if __name__ == "__main__":
    main()
