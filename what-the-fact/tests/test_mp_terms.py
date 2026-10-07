"""MP stints with a dated party: parsing, the 2000 cutoff, party-change detection, and the sync's DB behaviour."""
import os
import re
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, event, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import mp_terms as mt  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")

DENTREMONT = {
    "name": "Chris d'Entremont", "given_name": "Chris", "family_name": "d'Entremont",
    "other_info": {"parl_mp_id": ["49344"]},
    "memberships": [
        {"url": "/politicians/memberships/4855/", "start_date": "2025-11-05", "end_date": None,
         "party": {"name": {"en": "Liberal Party of Canada"}, "short_name": {"en": "Liberal"}},
         "riding": {"name": {"en": "Acadie—Annapolis"}, "province": "NS", "id": 12001}},
        {"url": "/politicians/memberships/4856/", "start_date": "2025-04-28", "end_date": "2025-11-04",
         "party": {"name": {"en": "Conservative Party of Canada"}, "short_name": {"en": "Conservative"}},
         "riding": {"name": {"en": "Acadie—Annapolis"}, "province": "NS", "id": 12001}},
        {"url": "/politicians/memberships/4541/", "start_date": "2019-10-21", "end_date": "2025-04-28",
         "party": {"name": {"en": "Conservative Party of Canada"}, "short_name": {"en": "Conservative"}},
         "riding": {"name": {"en": "West Nova"}, "province": "NS", "id": 12011}},
    ],
}
OLD = {"name": "Old Timer", "given_name": "Old", "family_name": "Timer", "other_info": {},
       "memberships": [{"url": "/politicians/memberships/1/", "start_date": "1994-05-01", "end_date": "1999-12-31",
                        "party": {"short_name": {"en": "Liberal"}}, "riding": {"name": {"en": "Nowhere"}, "province": "ON"}}]}
STRADDLE = {"name": "Straddler", "given_name": "S", "family_name": "Straddler", "other_info": {},
            "memberships": [{"url": "/politicians/memberships/2/", "start_date": "1997-06-02", "end_date": "2004-06-27",
                             "party": {"short_name": {"en": "Reform"}}, "riding": {"name": {"en": "Somewhere"}, "province": "AB"}}]}


def test_parse_reads_party_riding_province_and_ids():
    t = {x["start_date"]: x for x in mt.parse_terms(DENTREMONT, "chris-dentremont")}
    lib = t[date(2025, 11, 5)]
    assert (lib["party"], lib["riding"], lib["province"], lib["end_date"], lib["op_membership_id"]) == \
        ("Liberal", "Acadie—Annapolis", "NS", None, 4855)
    assert t[date(2019, 10, 21)]["end_date"] == date(2025, 4, 28)


def test_a_party_switch_is_a_dated_change_and_a_new_riding_is_not():
    ch = mt.party_changes(mt.parse_terms(DENTREMONT, "x"))
    assert len(ch) == 1                       # Conservative→Conservative across ridings is NOT a change
    assert (ch[0]["from_party"], ch[0]["to_party"], ch[0]["changed_on"]) == ("Conservative", "Liberal", date(2025, 11, 5))
    assert ch[0]["gap_days"] == 1             # crossed the floor the next day


def test_cutoff_drops_stints_that_ended_before_2000_but_keeps_one_that_straddles_it():
    assert not mt.within_cutoff(mt.parse_terms(OLD, "old")[0])
    assert mt.within_cutoff(mt.parse_terms(STRADDLE, "s")[0])           # ended 2004, started 1997: still counts
    assert mt.within_cutoff(mt.parse_terms(DENTREMONT, "x")[0])         # open-ended stint always counts


def test_missing_or_garbled_pieces_do_not_raise():
    assert mt.parse_terms({"memberships": [{"start_date": None}, {"start_date": "garbage"}]}, "s") == []
    one = mt.parse_terms({"memberships": [{"start_date": "2010-01-01", "party": None, "riding": None}]}, "s")[0]
    assert one["party"] is None and one["riding"] is None


def test_former_mp_row_uses_the_last_stint_and_the_list_repr_pid():
    terms = [t for t in mt.parse_terms(DENTREMONT, "chris-dentremont")]
    row = mt.former_mp_row(DENTREMONT, "chris-dentremont", terms)
    assert row["party"] == "Liberal" and row["prov"] == "NS" and row["pid"] == "['49344']"
    assert mt.former_mp_row(DENTREMONT, "Bad Slug!", terms) is None
    assert mt.former_mp_row(DENTREMONT, "ok", []) is None


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    event.listen(eng, "connect", lambda c, _: c.create_function("now", 0, lambda: "now"))
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("""CREATE TABLE parliament.mps (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
            name TEXT, given_name TEXT, family_name TEXT, party TEXT, riding_name TEXT, province_code TEXT,
            parl_mp_id TEXT, openparl_url TEXT, is_current BOOLEAN)"""))
        c.execute(text("""CREATE TABLE parliament.mp_terms (id INTEGER PRIMARY KEY AUTOINCREMENT, op_slug TEXT NOT NULL,
            op_membership_id INTEGER, name TEXT NOT NULL, mp_id INTEGER, party TEXT, riding TEXT, province TEXT,
            start_date TEXT NOT NULL, end_date TEXT, source_url TEXT NOT NULL, synced_at TEXT,
            UNIQUE (op_slug, start_date, riding, party))"""))
        c.execute(text("CREATE TABLE parliament.ingest_log (task TEXT, records_fetched INT, records_upserted INT, error TEXT)"))
        c.execute(text("INSERT INTO parliament.mps (slug, name, is_current) VALUES ('sitting-mp', 'Sitting MP', 1)"))
    return eng


SITTING = {"name": "Sitting MP", "other_info": {}, "memberships": [
    {"url": "/politicians/memberships/9/", "start_date": "2021-09-20", "end_date": None,
     "party": {"short_name": {"en": "Liberal"}}, "riding": {"name": {"en": "Here"}, "province": "ON"}}]}
FORMER = {"name": "Gone Away", "given_name": "Gone", "family_name": "Away", "other_info": {"parl_mp_id": ["12345"]},
          "memberships": [{"url": "/politicians/memberships/7/", "start_date": "2008-10-14", "end_date": "2011-03-26",
                           "party": {"short_name": {"en": "NDP"}}, "riding": {"name": {"en": "There"}, "province": "BC"}}]}


def _fake(details):
    listing = {"objects": [{"url": f"/politicians/{s}/"} for s in details], "pagination": {"next_url": None}}

    def get(path):
        if path.startswith("/politicians/?"):
            return listing
        return details[path.split("/")[2]]
    return get


def test_sync_stores_stints_adds_former_mps_and_links_the_sitting_one(engine):
    details = {"sitting-mp": SITTING, "gone-away": FORMER, "old-timer": OLD}
    stats = mt.run_mp_terms_sync(engine, sleep=0, get_json=_fake(details))
    assert stats["terms"] == 2 and stats["former_added"] == 1 and stats["skipped_pre_cutoff"] == 1
    with engine.connect() as c:
        mp = c.execute(text("SELECT is_current, party, parl_mp_id, province_code FROM parliament.mps WHERE slug='gone-away'")).one()
        assert (bool(mp[0]), mp[1], mp[2], mp[3]) == (False, "NDP", "['12345']", "BC")
        assert c.execute(text("SELECT count(*) FROM parliament.mps WHERE slug='old-timer'")).scalar() == 0   # pre-2000: never stored
        assert c.execute(text("SELECT count(*) FROM parliament.mp_terms WHERE mp_id IS NULL")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM parliament.ingest_log WHERE task='mp_terms'")).scalar() == 1


def test_sync_is_idempotent_and_never_touches_a_sitting_mps_row(engine):
    details = {"sitting-mp": SITTING, "gone-away": FORMER}
    mt.run_mp_terms_sync(engine, sleep=0, get_json=_fake(details))
    mt.run_mp_terms_sync(engine, sleep=0, get_json=_fake(details))
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.mp_terms")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM parliament.mps")).scalar() == 2
        assert c.execute(text("SELECT party FROM parliament.mps WHERE slug='sitting-mp'")).scalar() is None


def test_only_current_skips_former_mps(engine):
    stats = mt.run_mp_terms_sync(engine, only_current=True, sleep=0,
                                 get_json=_fake({"sitting-mp": SITTING, "gone-away": FORMER}))
    assert stats["fetched"] == 1 and stats["former_added"] == 0


def test_one_failing_politician_does_not_abort_the_run(engine):
    good = _fake({"sitting-mp": SITTING, "gone-away": FORMER})

    def get(path):
        if "gone-away" in path:
            raise OSError("boom")
        return good(path)
    stats = mt.run_mp_terms_sync(engine, sleep=0, get_json=get)
    assert stats["fetch_failed"] == ["gone-away"] and stats["terms"] == 1


def test_zero_stints_is_reported_as_an_error_not_silence(engine):
    stats = mt.run_mp_terms_sync(engine, sleep=0, get_json=_fake({"sitting-mp": {"name": "x", "memberships": []}}))
    assert "error" in stats


def test_the_party_change_view_finds_the_floor_crossing():
    sql = open(os.path.join(ROOT, "migrations", "094_mp_terms.sql"), encoding="utf-8").read()
    view = re.search(r"CREATE OR REPLACE VIEW parliament\.v_mp_party_changes AS(.*?);\n", sql, re.S).group(1)
    view = view.replace("(start_date - lag(end_date) OVER w)", "0")          # date arithmetic is Postgres-only
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.mp_terms (id INTEGER PRIMARY KEY, op_slug TEXT, name TEXT, mp_id INT, "
                       "party TEXT, riding TEXT, start_date TEXT, end_date TEXT)"))
        c.execute(text("CREATE VIEW parliament.v_mp_party_changes AS" + view))
        for r in mt.parse_terms(DENTREMONT, "chris-dentremont"):
            c.execute(text("INSERT INTO parliament.mp_terms (op_slug, name, party, riding, start_date, end_date) "
                           "VALUES (:op_slug, :name, :party, :riding, :start_date, :end_date)"),
                      {**r, "start_date": str(r["start_date"]), "end_date": str(r["end_date"]) if r["end_date"] else None})
        rows = c.execute(text("SELECT from_party, to_party, changed_on FROM parliament.v_mp_party_changes")).fetchall()
    assert rows == [("Conservative", "Liberal", "2025-11-05")]


def test_migration_is_idempotent_and_applies_the_cutoff_note():
    sql = open(os.path.join(ROOT, "migrations", "094_mp_terms.sql"), encoding="utf-8").read()
    assert "CREATE TABLE IF NOT EXISTS parliament.mp_terms" in sql and "2000-01-01" in sql
    assert "ON CONFLICT (version) DO NOTHING" in sql
