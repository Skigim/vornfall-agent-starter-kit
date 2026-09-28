from vfkit.sites import digest, home_town, town_sites

TOWNS = {"home": "tw_2", "towns": [
    {"id": "tw_1", "name": "Crownford", "lord_id": 0},
    {"id": "tw_2", "name": "Ashby", "lord_id": 7, "home": True},
]}
SITES = {"sites": [
    {"id": "s_far", "type": "library", "lord": 3, "dist": 300, "missing": {"pine_log": 20}},
    {"id": "s_b", "type": "stable", "lord": 7, "pos": [5, 6], "dist": 19.2, "missing": {"pine_log": 30},
     "ready": False, "work": 50, "work_left": 50, "slots_free": 4},
    {"id": "s_a", "type": "farm", "lord": 7, "pos": [1, 2], "dist": 12.6, "missing": {},
     "ready": True, "work": 40, "work_left": 10, "slots_free": 3},
]}


def test_home_town_by_flag_or_top_level_id():
    assert home_town(TOWNS)["id"] == "tw_2"
    assert home_town({"home": "tw_1", "towns": TOWNS["towns"][:1]})["id"] == "tw_1"
    assert home_town({"towns": TOWNS["towns"][:1]}) is None


def test_town_sites_keeps_one_lord_nearest_first():
    assert [s["id"] for s in town_sites(SITES, 7)] == ["s_a", "s_b"]
    assert town_sites({"sites": []}, 7) == []


def test_digest_lists_each_site():
    text = digest(TOWNS["towns"][1], town_sites(SITES, 7))
    assert "home town, Ashby" in text
    assert "- s_a farm at [1,2], 13 tiles away: ready to build, all materials in; work 10 of 40 left" in text
    assert "- s_b stable at [5,6], 19 tiles away: not ready, missing 30 pine_log; work 50 of 50 left" in text
    assert text.index("s_a") < text.index("s_b")


def test_digest_says_when_none_are_open():
    assert "- none open right now" in digest({"id": "tw_2"}, [])
