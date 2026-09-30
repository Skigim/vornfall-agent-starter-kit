"""Usage-limit messages: when the harness says a limit resets, wait until then."""
import re
from datetime import datetime, timedelta

_RESETS = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)(?:\s*\(([^)]+)\))?", re.I)
MARGIN_S = 60
MAX_WAIT_S = 8 * 3600


def _zone(name):
    try:
        from zoneinfo import ZoneInfo   # needs the tzdata package on Windows
        return ZoneInfo(name.strip())
    except Exception:
        return None


def seconds_until_reset(text, now):
    """Seconds from `now` (a timestamp) to the reset time a limit message names, plus a minute's
    margin, or None when the text names no time of day or the wait would exceed eight hours. A zone
    that can't be loaded is read as the machine's own."""
    m = _RESETS.search(text or "")
    if not m:
        return None
    hour, minute, ampm, zone = int(m[1]), int(m[2] or 0), m[3].lower(), m[4]
    if not 1 <= hour <= 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if ampm == "pm" else 0)
    tz = _zone(zone) if zone else None
    local = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now).astimezone()
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    wait = int((target - local).total_seconds()) + MARGIN_S
    return wait if wait <= MAX_WAIT_S else None
