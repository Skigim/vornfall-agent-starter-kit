"""The home town's open construction sites, read from GET /v1/sites for agents whose tools can't.

The game's MCP tools have no sites listing, and the briefing names a site only when a Lord's buy
order is tied to it, so an MCP-only agent can miss open sites entirely. The watcher reads the
listing and passes it on as it stands; the agent decides what, if anything, to do about it."""


def home_town(towns: dict) -> dict | None:
    """The agent's home town from a GET /v1/towns response, or None if it has none."""
    home = towns.get("home")
    for town in towns.get("towns") or []:
        if town.get("home") is True or (home and town.get("id") == home):
            return town
    return None


def town_sites(sites: dict, lord_id) -> list:
    """The sites in a GET /v1/sites response posted by one Lord, nearest first."""
    mine = [s for s in sites.get("sites") or [] if s.get("lord") == lord_id]
    return sorted(mine, key=lambda s: s.get("dist") or 0)


def _site_line(s: dict) -> str:
    missing = s.get("missing") or {}
    if missing:
        needs = "missing " + ", ".join(f"{n} {item}" for item, n in missing.items())
    else:
        needs = "all materials in"
    state = "ready to build" if s.get("ready") else "not ready"
    pos = s.get("pos")
    where = f" at [{pos[0]},{pos[1]}]" if pos else ""
    return (f"- {s.get('id')} {s.get('type')}{where}, {round(s.get('dist') or 0)} tiles away: {state}, "
            f"{needs}; work {s.get('work_left')} of {s.get('work')} left, "
            f"{s.get('slots_free')} builder slots free")


def digest(town: dict, sites: list) -> str:
    """Prompt text listing the home town's open sites (the ids stay private to the agent)."""
    name = town.get("name") or town.get("id")
    head = (f"Open construction sites in your home town, {name} (from GET /v1/sites, which your "
            "game tools don't list; the briefing names a site only when a buy order is tied to it):\n")
    if not sites:
        return head + "- none open right now\n"
    return head + "".join(_site_line(s) + "\n" for s in sites)
