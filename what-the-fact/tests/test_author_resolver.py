from sqlalchemy import text

from shared.author_resolver import (
    normalize_name,
    clean_byline,
    is_wire_service,
    resolve_byline,
    tag_article_author,
)


# --- pure helpers (no DB) -------------------------------------------------

def test_normalize_name_slugifies():
    assert normalize_name("Élise Tremblay") == "elise-tremblay"
    assert normalize_name("  John   O'Brien ") == "john-obrien"


def test_clean_byline_strips_prefix_and_splits_cobylines():
    assert clean_byline("By Jane Smith and John Doe") == ["Jane Smith", "John Doe"]
    assert clean_byline("Jane Smith, CBC News") == ["Jane Smith"]
    assert clean_byline("") == []


def test_is_wire_service_detects_agencies():
    assert is_wire_service("The Canadian Press")
    assert is_wire_service("GLOBE NEWSWIRE")
    assert not is_wire_service("Jane Smith")


# --- DB find-or-create + tag ----------------------------------------------

def test_resolve_byline_creates_journalist_and_drops_wire(entity_schema, engine):
    with engine.begin() as c:
        ids = resolve_byline(c, "By Jane Smith and The Canadian Press", "src",
                             shared_schema="shared_test")
        assert len(ids) == 1  # wire service dropped
        row = c.execute(text("SELECT entity_type, slug, metadata FROM shared_test.entities "
                             "WHERE id=:i"), {"i": ids[0]}).mappings().first()
        assert row["entity_type"] == "journalist"
        assert row["slug"] == "jane-smith"
        assert "src" in row["metadata"]["outlets"]


def test_resolve_byline_is_idempotent_and_appends_outlet(entity_schema, engine):
    with engine.begin() as c:
        a = resolve_byline(c, "Jane Smith", "src", shared_schema="shared_test")
        b = resolve_byline(c, "jane  smith", "other", shared_schema="shared_test")
        assert a == b  # same entity by normalized slug
        meta = c.execute(text("SELECT metadata FROM shared_test.entities WHERE id=:i"),
                         {"i": a[0]}).scalar()
        assert set(meta["outlets"]) == {"src", "other"}  # appended, not duplicated


def test_tag_article_author_writes_mention_and_tag(entity_schema, engine):
    with engine.begin() as c:
        eid = resolve_byline(c, "Jane Smith", "src", shared_schema="shared_test")[0]
        aid = c.execute(text(
            "INSERT INTO wtf_test.articles (source_id,external_id,title,body,url,published_at) "
            "VALUES (:s,'jx','t','b','http://s/jx','2026-05-03') RETURNING id"),
            {"s": entity_schema["source_id"]}).scalar()
        tag_article_author(c, aid, eid, "src", wtf_schema="wtf_test", shared_schema="shared_test")
        # idempotent: second call must not duplicate
        tag_article_author(c, aid, eid, "src", wtf_schema="wtf_test", shared_schema="shared_test")
        m = c.execute(text("SELECT count(*) FROM shared_test.entity_mentions "
                           "WHERE entity_id=:e AND content_id=:a"), {"e": eid, "a": str(aid)}).scalar()
        t = c.execute(text("SELECT count(*) FROM wtf_test.article_author_tags "
                           "WHERE entity_id=:e AND article_id=:a"), {"e": eid, "a": aid}).scalar()
        assert m == 1 and t == 1
