"""Senate-summary names that the roster could not match must not be silently dropped.

2026-10-06: 30 of the 144 senators on the 2023-2026 Senate summaries (8 hand-added stubs with NULL
family/given names, 22 with no row at all) never had an expense or travel row ingested, so every total built on
those tables under-counted. The matcher now reads the stubs, tolerates the Senate's trailing "*", and the syncs
create a stub for a name that has no roster row.
"""
import os
import sys

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.parliament import senator_expenses as se  # noqa: E402


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("""CREATE TABLE parliament.senators (
            id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, name TEXT, given_name TEXT,
            family_name TEXT, caucus TEXT, province TEXT, is_current BOOLEAN, synced_at TEXT DEFAULT 'x')"""))
        c.execute(text("""INSERT INTO parliament.senators (slug, name, given_name, family_name, is_current)
            VALUES ('smith-a', 'Smith, Alice', 'Alice', 'Smith', 1),
                   ('smith-b', 'Smith, Larry W.', 'Larry W.', 'Smith', 1)"""))
        # a hand-added stub: only `name`, NULL family/given (ids 100-107 in production)
        c.execute(text("""INSERT INTO parliament.senators (id, slug, name, is_current)
            VALUES (100, 'plett-donald', 'Plett, Donald Neil', 0)"""))
    return eng


def test_a_stub_with_null_family_name_is_matchable(engine):
    fam, full = se._load_senator_index(engine)
    assert se._match_senator("Plett, Donald Neil", fam, full) == 100


def test_trailing_asterisk_is_ignored(engine):
    fam, full = se._load_senator_index(engine)
    assert se._match_senator("Plett, Donald Neil *", fam, full) == 100
    assert se._match_senator("Plett, Donald Neil*", fam, full) == 100


def test_shared_surname_still_resolves_by_given_name(engine):
    fam, full = se._load_senator_index(engine)
    assert se._match_senator("Smith, Larry W.", fam, full) is not None
    assert se._match_senator("Smith, Larry W.", fam, full) != se._match_senator("Smith, Alice", fam, full)


def test_unknown_name_creates_a_stub_once(engine):
    fam, full = se._load_senator_index(engine)
    sid = se.ensure_roster_stub(engine, "Mégie, Marie-Françoise", caucus="ISG", province="Quebec (Rougemont)*",
                                fam_idx=fam, full_idx=full)
    assert sid
    with engine.connect() as c:
        row = c.execute(text("SELECT slug, name, given_name, family_name, caucus, province, is_current "
                             "FROM parliament.senators WHERE id=:i"), {"i": sid}).one()
    assert row[0] == "megie-marie-francoise"
    assert row[1:4] == ("Mégie, Marie-Françoise", "Marie-Françoise", "Mégie")
    assert row[4] == "ISG" and row[5] == "Quebec" and not row[6]
    # in-memory indexes updated: the next lookup matches and does not create a second row
    assert se._match_senator("Mégie, Marie-Françoise", fam, full) == sid
    assert se.ensure_roster_stub(engine, "Mégie, Marie-Françoise") == sid
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senators WHERE slug='megie-marie-francoise'")).scalar() == 1


@pytest.mark.parametrize("bad", ["", "Nobody", "  ,  ", None])
def test_things_that_are_not_family_given_names_create_nothing(engine, bad):
    assert se.ensure_roster_stub(engine, bad) is None
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senators")).scalar() == 3


def test_html_encoded_accents_match_the_existing_roster_senator_not_a_new_stub(engine):
    with engine.begin() as c:
        c.execute(text("INSERT INTO parliament.senators (slug, name, given_name, family_name, is_current) "
                       "VALUES ('gagne-raymonde', 'Gagné, Raymonde', 'Raymonde', 'Gagné', 1)"))
    fam, full = se._load_senator_index(engine)
    sid = se._match_senator("Gagn&#xE9;, Raymonde", fam, full)
    assert sid is not None
    assert se.ensure_roster_stub(engine, "Gagn&#xE9;, Raymonde", fam_idx=fam, full_idx=full) is not None
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM parliament.senators WHERE family_name LIKE 'Gagn%'")).scalar() == 1


def test_a_new_accented_senator_gets_a_clean_name_and_slug(engine):
    sid = se.ensure_roster_stub(engine, "Dupuis, Ren&#xE9;e")
    with engine.connect() as c:
        slug, name = c.execute(text("SELECT slug, name FROM parliament.senators WHERE id=:i"), {"i": sid}).one()
    assert (slug, name) == ("dupuis-renee", "Dupuis, Renée")
