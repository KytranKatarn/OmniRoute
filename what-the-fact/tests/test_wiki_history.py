"""Wikipedia infobox parser + collector (pure). Run: python3 tests/test_wiki_history.py"""
import datetime as dt, os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("sqlalchemy", types.SimpleNamespace(text=lambda s: s))
from ingest.elections.wiki_parse import parse_election
from ingest.elections import wiki_history

PAGE = """{{Short description|x}}
{{Infobox election
| election_name = 2022 Quebec general election
| election_date = {{Start date|2022|10|3}}
| seats_for_election = All 125 seats in the [[National Assembly of Quebec]]
| turnout = 66.1%<ref>x</ref>
| party1 = [[Coalition Avenir Québec]]
| seats1 = 90{{increase}} / 125
| popular_vote1 = 1,685,573
| party2 = [[Quebec Liberal Party|Liberal]]
| seats2 = 21
| party3 = [[Québec solidaire]]
| seats3 = 11
}}
text"""


def test_parse():
    r = parse_election(PAGE, 2022)
    assert r["election_date"] == dt.date(2022, 10, 3) and r["seats_total"] == 125
    assert [x["party"] for x in r["results"]][:3] == ["Coalition Avenir Québec", "Liberal", "Québec solidaire"]
    assert r["results"][0] == {"party": "Coalition Avenir Québec", "seats": 90, "votes": 1685573}
    assert r["turnout_pct"] == 66.1


def test_refuses_bad_shapes():
    assert parse_election("no infobox", 2022) is None
    assert parse_election(PAGE, 2018) is None                       # year mismatch
    assert parse_election(PAGE.replace("seats2 = 21", "seats2 = 99"), 2022) is None  # sum > total


def test_collect_skips_and_sources():
    def fake(titles):
        t = "2022 Quebec general election"
        return {t: (t, PAGE)} if t in titles else {}
    rows, skipped = wiki_history.collect(dt.date(2026, 10, 2), fake)
    assert len(rows) == 1 and rows[0]["code"] == "QC" and not skipped
    assert rows[0]["source_url"].endswith("2022_Quebec_general_election")


MAYOR = """{{Infobox election
| election_date = {{Start date|2022|10|24}}
| turnout = 29.2%
| candidate1 = [[John Tory]]
| popular_vote1 = 342,509
| percentage1 = 62.2%
| candidate2 = [[Gil Penalosa]]
| popular_vote2 = 169,545
| percentage2 = 30.8%
| candidate3 = [[Stephen Brown]]
| percentage3 = 7.0%
}}"""


def test_other_row_is_arithmetic():
    r = parse_election(PAGE, 2022)
    assert r["results"][-1] == {"party": "Other / not itemised", "seats": 3, "derived": True}
    assert sum(x["seats"] for x in r["results"]) == r["seats_total"] == 125


def test_mayoral():
    from ingest.elections.wiki_parse import parse_mayoral
    r = parse_mayoral(MAYOR, 2022)
    assert r["results"][0]["candidate"] == "John Tory" and r["turnout_pct"] == 29.2
    assert parse_mayoral(MAYOR.replace("62.2", "92.2"), 2022) is None   # shares > 100


def test_collect_municipal():
    def fake(titles):
        t = "2022 Toronto mayoral election"
        return {t: (t, MAYOR)} if t in titles else {}
    rows, _ = wiki_history.collect(dt.date(2026, 10, 2), fake)
    assert [r["code"] for r in rows] == ["MUN-toronto"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
