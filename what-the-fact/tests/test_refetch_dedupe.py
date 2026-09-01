"""The same story re-fetched under a new feed token must not become a second article.

10 of 46 sources come through a Google News proxy that re-encodes a story under a
NEW opaque token on a later poll, so BOTH external_id and url change while the
article is identical. `UNIQUE (source_id, external_id)` cannot see that, and
neither could a url constraint — measured over 14 days, 792 of 796 duplicate
groups had DIFFERENT urls.

These run the REAL SQL in upsert_article against a real schema, because the guard
lives in the INSERT statement — a pure-Python test would prove nothing about it.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import persist  # noqa: E402

_BIAS = {"band": "center", "score": 0.0, "heuristic_version": "test",
         "rationale": "", "trigger_phrases": []}

_GOOGLE = "https://news.google.com/rss/articles/"


@pytest.fixture()
def source_id(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    with engine.begin() as c:
        return c.execute(text(
            "INSERT INTO wtf_test.sources (slug, name, url) "
            "VALUES ('ctv_news','CTV News','http://x') RETURNING id")).scalar()


def _article(guid, title, when, url=None, body="body text here " * 20):
    return {"external_id": guid, "title": title, "body": body,
            "url": url or f"{_GOOGLE}{guid}?oc=5", "published_at": when}


def _count(engine, source_id):
    with engine.begin() as c:
        return c.execute(text(
            "SELECT count(*) FROM wtf_test.articles WHERE source_id=:s"),
            {"s": source_id}).scalar()


# ── the bug ───────────────────────────────────────────────────────────────────

def test_new_token_same_story_is_not_ingested_twice(engine, source_id):
    """The exact live shape: same title, same published_at, two Google tokens."""
    now = datetime.now(timezone.utc)
    a = persist.upsert_article(engine, source_id,
                               _article("CBMigwFBVV95cUxNMTVaVWFx", "131 WSIB jobs cut in Windsor - CTV News", now),
                               _BIAS, "ctv_news")
    b = persist.upsert_article(engine, source_id,
                               _article("CBMikwFBVV95cUxPNUVzb081", "131 WSIB jobs cut in Windsor - CTV News", now),
                               _BIAS, "ctv_news")
    assert a is not None, "first copy must be ingested"
    assert b is None, "re-fetch under a new token must be skipped"
    assert _count(engine, source_id) == 1


def test_neither_existing_key_would_have_caught_it(engine, source_id):
    """Documents WHY a url constraint was not the fix: the urls differ too."""
    now = datetime.now(timezone.utc)
    first = _article("tok-A", "Same headline", now)
    second = _article("tok-B", "Same headline", now)
    assert first["external_id"] != second["external_id"]
    assert first["url"] != second["url"]
    persist.upsert_article(engine, source_id, first, _BIAS, "ctv_news")
    assert persist.upsert_article(engine, source_id, second, _BIAS, "ctv_news") is None


@pytest.mark.parametrize("minutes", [0, 5, 60, 300, 359])
def test_duplicates_inside_the_window_are_skipped(engine, source_id, minutes):
    now = datetime.now(timezone.utc)
    persist.upsert_article(engine, source_id, _article("g1", "Windsor plant closes", now), _BIAS, "ctv_news")
    dup = persist.upsert_article(engine, source_id,
                                 _article("g2", "Windsor plant closes", now + timedelta(minutes=minutes)),
                                 _BIAS, "ctv_news")
    assert dup is None
    assert _count(engine, source_id) == 1


# ── recurring content must SURVIVE ────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Today's horoscope",
    "Before the Bell: What every Canadian investor needs to know",
    "Transaction in Own Shares",
])
def test_a_daily_column_is_not_deduped(engine, source_id, title):
    """These reuse a headline LEGITIMATELY — 8-10 times in 14 days each, live.

    A title-only rule, or a window of a day or more, would delete a publisher's
    daily column down to a single copy. This is the case the 6h window protects.
    """
    now = datetime.now(timezone.utc)
    first = persist.upsert_article(engine, source_id, _article("d1", title, now), _BIAS, "ctv_news")
    later = persist.upsert_article(engine, source_id,
                                   _article("d2", title, now + timedelta(hours=24)),
                                   _BIAS, "ctv_news")
    assert first is not None and later is not None, "a daily column must keep both days"
    assert _count(engine, source_id) == 2


def test_just_outside_the_window_is_kept(engine, source_id):
    now = datetime.now(timezone.utc)
    persist.upsert_article(engine, source_id, _article("w1", "Recurring feature", now), _BIAS, "ctv_news")
    later = persist.upsert_article(engine, source_id,
                                   _article("w2", "Recurring feature", now + timedelta(hours=6, minutes=5)),
                                   _BIAS, "ctv_news")
    assert later is not None
    assert _count(engine, source_id) == 2


# ── the guard must not over-reach ─────────────────────────────────────────────

def test_a_different_headline_is_always_ingested(engine, source_id):
    now = datetime.now(timezone.utc)
    persist.upsert_article(engine, source_id, _article("x1", "Windsor plant closes", now), _BIAS, "ctv_news")
    other = persist.upsert_article(engine, source_id,
                                   _article("x2", "Windsor plant reopens", now), _BIAS, "ctv_news")
    assert other is not None
    assert _count(engine, source_id) == 2


def test_the_same_headline_from_a_different_source_is_kept(engine, clean_schema, source_id):
    """Two outlets covering one story is the PRODUCT, not a duplicate — the whole
    point of a bias-comparison site is holding both."""
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        other_src = c.execute(text(
            "INSERT INTO wtf_test.sources (slug, name, url) "
            "VALUES ('cbc_english','CBC News','http://y') RETURNING id")).scalar()
    persist.upsert_article(engine, source_id, _article("s1", "Federal budget tabled", now), _BIAS, "ctv_news")
    second = persist.upsert_article(engine, other_src, _article("s2", "Federal budget tabled", now),
                                    _BIAS, "cbc_english")
    assert second is not None, "a different outlet's copy must be kept"


def test_an_exact_guid_repeat_is_still_deduped(engine, source_id):
    """The original ON CONFLICT path must keep working alongside the new guard."""
    now = datetime.now(timezone.utc)
    persist.upsert_article(engine, source_id, _article("same-guid", "A headline", now), _BIAS, "ctv_news")
    again = persist.upsert_article(engine, source_id, _article("same-guid", "A headline", now), _BIAS, "ctv_news")
    assert again is None
    assert _count(engine, source_id) == 1
