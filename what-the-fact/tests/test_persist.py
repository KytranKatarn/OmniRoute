from datetime import datetime
from sqlalchemy import text
from ingest.persist import upsert_article, record_failure


def _source_id(engine, slug):
    with engine.begin() as c:
        r = c.execute(text(
            "INSERT INTO wtf_test.sources (slug, name, url) VALUES (:s, :n, :u) RETURNING id"
        ), {"s": slug, "n": slug, "u": "http://x"})
        return r.scalar()


def test_upsert_inserts_then_dedupes(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    sid = _source_id(engine, "test")
    art = {"external_id": "g-1", "title": "T", "body": "b",
           "url": "http://x", "published_at": datetime(2026, 4, 18)}
    bias = {"band": "center", "score": 0.0, "heuristic_version": "v1", "rationale": "none"}
    # upsert_article returns the ARTICLE ID on insert and None on dedupe (see its
    # docstring). This asserted `is True` / `is False` against a return type that
    # had already changed to int|None — a stale assertion that only surfaced once
    # the test schema was repaired enough for the test to reach it at all.
    first = upsert_article(engine, sid, art, bias)
    assert isinstance(first, int) and first > 0, 'insert returns the new article id'
    assert upsert_article(engine, sid, art, bias) is None, 'dedupe returns None'

    with engine.begin() as c:
        cnt = c.execute(text("SELECT COUNT(*) FROM wtf_test.articles")).scalar()
    assert cnt == 1


def test_record_failure_writes_to_failed_ingest(clean_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    record_failure(engine, "cbc_english", {"bad": "payload"}, "parser crashed: X")
    with engine.begin() as c:
        r = c.execute(text("SELECT source_slug, error FROM wtf_test.failed_ingest")).fetchone()
    assert r[0] == "cbc_english"
    assert "parser crashed" in r[1]
