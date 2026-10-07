"""Published House names that are different NAMES for one MP (nickname, surname change, punctuation, hyphen) resolve by slug.

Found 2026-10-07: the FY2015-FY2021 archive backfill left six names unmatched — Harder/Rachael (now Rachael Thomas),
Harris/Richard (Dick Harris), Brown/Gordon (Gord Brown), Harvey/T.J. (TJ Harvey), O'Neill Gordon/Tilly (Tilly O'Neill-Gordon),
and Anderson/David (two MPs share the name; only the Cypress Hills one overlaps 2014+).
"""
from sqlalchemy import create_engine, text

from ingest.parliament import mp_expenses as me

ROWS = [  # id, name, family_name, slug
    (34, "Rachael Thomas", "Thomas", "rachael-harder"),
    (12186, "Dick Harris", "Harris", "dick-harris"),
    (12187, "Dan Harris", "Harris", "dan-harris"),
    (11951, "Gord Brown", "Brown", "gord-brown"),
    (11950, "Lois Brown", "Brown", "lois-brown"),
    (12192, "TJ Harvey", "Harvey", "tj-harvey"),
    (12435, "Tilly O'Neill-Gordon", "O'Neill-Gordon", "tilly-oneill-gordon"),
    (11839, "David Anderson", "Anderson", "3160"),            # Victoria
    (11840, "David Anderson", "Anderson", "david-anderson"),  # Cypress Hills-Grasslands
    (39, "Scott Anderson", "Anderson", "scott-anderson"),
]


def _index():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE mps (id INTEGER, name TEXT, family_name TEXT, slug TEXT)"))
        c.execute(text("ATTACH DATABASE ':memory:' AS parliament"))
        c.execute(text("CREATE TABLE parliament.mps (id INTEGER, name TEXT, family_name TEXT, slug TEXT)"))
        for r in ROWS:
            c.execute(text("INSERT INTO parliament.mps VALUES (:a,:b,:c,:d)"), dict(zip("abcd", r)))
    return me._build_mp_index(eng)


def test_each_of_the_six_published_names_resolves_to_the_right_mp():
    fam, full = _index()
    want = {"Harder, Rachael": 34, "Harris, Richard": 12186, "Brown, Gordon": 11951, "Harvey, T.J.": 12192,
            "O'Neill Gordon, Tilly": 12435, "Anderson, David": 11840}
    for published, mp_id in want.items():
        assert me._match_mp(published, fam, full) == mp_id, published
        assert me._match_mp(published.replace(", ", ", Hon. "), fam, full) == mp_id, published  # 'Hon.' form too


def test_without_aliases_these_names_were_not_matched():
    """Non-vacuity: with the alias table emptied, the nickname/surname-change cases fail to match the right MP."""
    saved = dict(me.PUBLISHED_NAME_ALIASES)
    me.PUBLISHED_NAME_ALIASES.clear()
    try:
        fam, full = _index()
        assert me._match_mp("Harder, Rachael", fam, full) is None
        assert me._match_mp("Harris, Richard", fam, full) != 12186     # ambiguous between two Harrises -> None
        assert me._match_mp("Anderson, David", fam, full) is None      # two David Andersons -> ambiguous
    finally:
        me.PUBLISHED_NAME_ALIASES.update(saved)


def test_other_mps_with_the_same_surname_are_untouched():
    fam, full = _index()
    assert me._match_mp("Brown, Lois", fam, full) == 11950
    assert me._match_mp("Harris, Dan", fam, full) == 12187
    assert me._match_mp("Anderson, Scott", fam, full) == 39


def test_an_alias_whose_slug_is_missing_is_skipped_not_raised():
    saved = dict(me.PUBLISHED_NAME_ALIASES)
    me.PUBLISHED_NAME_ALIASES["nobody, noone"] = "no-such-slug"
    try:
        fam, full = _index()
        assert "nobody, noone" not in full and me._match_mp("nobody, noone", fam, full) is None
    finally:
        me.PUBLISHED_NAME_ALIASES.clear()
        me.PUBLISHED_NAME_ALIASES.update(saved)
