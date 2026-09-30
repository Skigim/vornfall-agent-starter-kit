import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfkit.limits import MARGIN_S, seconds_until_reset


def at(hour, minute=0):
    return datetime(2026, 9, 30, hour, minute).astimezone().timestamp()


def test_reset_later_today_in_the_machines_zone():
    text = "You've hit your session limit · resets 4:50pm (America/Chicago)"
    # the zone name is left out: it can't always be loaded, and then the machine's own zone is used
    now = at(14, 50)
    wait = seconds_until_reset(text.replace("(America/Chicago)", ""), now)
    assert wait == 2 * 3600 + MARGIN_S


def test_hour_without_minutes_and_am():
    assert seconds_until_reset("resets 5pm", at(16, 0)) == 3600 + MARGIN_S
    assert seconds_until_reset("limit resets 1:30am", at(23, 30)) == 2 * 3600 + MARGIN_S


def test_a_time_already_passed_means_tomorrow_and_is_too_long():
    assert seconds_until_reset("resets 4:50pm", at(16, 51)) is None


def test_noon_and_midnight():
    assert seconds_until_reset("resets 12pm", at(11, 0)) == 3600 + MARGIN_S
    assert seconds_until_reset("resets 12am", at(21, 0)) == 3 * 3600 + MARGIN_S


def test_no_time_of_day_or_nonsense():
    assert seconds_until_reset("", 0) is None
    assert seconds_until_reset(None, 0) is None
    assert seconds_until_reset("resets Oct 3 at 9am", at(9, 0)) is None
    assert seconds_until_reset("resets 13pm", at(9, 0)) is None
    assert seconds_until_reset("resets 4:75pm", at(9, 0)) is None
