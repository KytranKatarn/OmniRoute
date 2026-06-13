"""Milestone B / Task B2 — RSS byline capture at ingest.

Pure tests (extract_byline / canonicalize preservation) need no DB and no feedparser
(rss_generic lazily imports feedparser inside fetch_rss). The integration test drives
upsert_article against the isolated *_test schemas to prove tag-on-ingest end to end.
"""

from ingest.normalizer import canonicalize
from ingest.sources.rss_generic import extract_byline


# ── Pure: byline extraction (feedparser-free — takes a plain dict) ──────────────
def test_extract_byline_prefers_author_then_authors():
    assert extract_byline({"author": "Jane Smith"}) == "Jane Smith"
    assert extract_byline({"authors": [{"name": "John Doe"}]}) == "John Doe"
    assert extract_byline({}) is None


def test_extract_byline_strips_and_handles_blank():
    assert extract_byline({"author": "  Padded Name  "}) == "Padded Name"
    assert extract_byline({"author": ""}) is None
    assert extract_byline({"author": "   "}) is None
    assert extract_byline({"authors": [{}]}) is None


# ── Pure: canonicalize must carry the byline through to persist ─────────────────
def test_canonicalize_preserves_author():
    raw = {
        "external_id": "x",
        "url": "http://s/x",
        "title": "T",
        "body": "b",
        "published_at": "2026-05-04",
        "author": "By Jane Smith",
    }
    assert canonicalize(raw)["author"] == "By Jane Smith"


def test_canonicalize_author_absent_is_none():
    raw = {
        "external_id": "x",
        "url": "http://s/x",
        "title": "T",
        "body": "b",
        "published_at": "2026-05-04",
    }
    assert canonicalize(raw).get("author") is None


# ── Integration: tag-on-ingest (resolver dual-write through persist) ────────────
def test_upsert_article_tags_byline(entity_schema, engine, monkeypatch):
    """A byline-bearing article ingested via upsert_article tags exactly one journalist
    (the co-byline wire service 'The Canadian Press' is dropped) and writes both the
    shared.entity_mentions row and the wtf.article_author_tags mirror."""
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("WTF_SHARED_SCHEMA", "shared_test")
    from sqlalchemy import text
    from ingest.persist import upsert_article

    article = canonicalize(
        {
            "external_id": "byl-1",
            "title": "T",
            "body": "b",
            "url": "http://s/byl-1",
            "published_at": "2026-05-04",
            "author": "By Jane Smith and The Canadian Press",
        }
    )
    aid = upsert_article(
        engine,
        entity_schema["source_id"],
        article,
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "x"},
        source_slug="src",
    )
    assert aid
    with engine.connect() as c:
        tags = c.execute(
            text(
                "SELECT count(*) FROM wtf_test.article_author_tags WHERE article_id=:a"
            ),
            {"a": aid},
        ).scalar()
        ment = c.execute(
            text(
                "SELECT count(*) FROM shared_test.entity_mentions em "
                "JOIN shared_test.entities e ON e.id = em.entity_id "
                "WHERE e.slug = 'jane-smith' AND em.content_id = :a"
            ),
            {"a": str(aid)},
        ).scalar()
    assert tags == 1
    assert ment == 1


def test_upsert_article_without_byline_tags_nothing(entity_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("WTF_SHARED_SCHEMA", "shared_test")
    from sqlalchemy import text
    from ingest.persist import upsert_article

    article = canonicalize(
        {
            "external_id": "byl-2",
            "title": "T",
            "body": "b",
            "url": "http://s/byl-2",
            "published_at": "2026-05-05",
        }
    )
    aid = upsert_article(
        engine,
        entity_schema["source_id"],
        article,
        {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "x"},
        source_slug="src",
    )
    assert aid
    with engine.connect() as c:
        tags = c.execute(
            text(
                "SELECT count(*) FROM wtf_test.article_author_tags WHERE article_id=:a"
            ),
            {"a": aid},
        ).scalar()
    assert tags == 0
