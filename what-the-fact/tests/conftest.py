"""pytest fixtures: isolated DB per test using the `wtf_test` schema."""
import os
import pytest
from sqlalchemy import create_engine, text

TEST_DB_URL = os.environ.get(
    "WTF_TEST_DATABASE_URL",
    "postgresql+psycopg2://archie:archie@192.168.1.200:5432/archie",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    return eng


# ⚠️ THE TEST SCHEMA MUST CARRY EVERY COLUMN THE CODE UNDER TEST WRITES.
#
# clean_schema applied ONLY 001_wtf_schema.sql, so every column added by a later
# migration was invisible here. When migration 065 added `articles.content_type`
# and ingest/persist.py started writing it, `test_upsert_inserts_then_dedupes`
# began failing with `column "content_type" does not exist` — the test was red for
# a schema reason, not a behaviour reason, which is the worst kind of red because
# it looks like the feature is broken.
#
# List a migration here whenever it adds a column/table that production code
# writes or reads on a path a test exercises. Data backfills and migrations that
# touch other schemas are deliberately NOT applied — they are not what the test
# schema is for.
# ⚠️ REPLAYING THE MIGRATION FILES DOES NOT WORK HERE, and it is worth saying why
# so the next person does not try it again: each later migration also touches
# columns added by migrations this schema deliberately skips (063 needs
# `analyzed_by`, and so on), so applying the file fails as a whole and takes its
# ALTERs with it. What the test schema needs is the COLUMNS, not the migrations.
#
# Add a line here whenever production code starts writing a new column on a path a
# test exercises. Keep the migration number so the origin stays traceable.
_SCHEMA_PATCHES = (
    # 065 — written by ingest/persist.py on every insert.
    "ALTER TABLE wtf_test.articles "
    "ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'journalism'",
    # 063 — written by ingest/persist.py alongside every bias score.
    "ALTER TABLE wtf_test.bias_scores "
    "ADD COLUMN IF NOT EXISTS signal_detected BOOLEAN",
    # 078 — read (filtered on) by consumer/routes.py's news() verdict filter.
    # The trigger that KEEPS this column current is deliberately NOT applied
    # here — tests that exercise the filter set it directly on inserted rows;
    # a dedicated fixture layers the real migration 078 on top of this schema
    # to prove the trigger itself (see tests/test_news_verdict_filter.py).
    "ALTER TABLE wtf_test.articles "
    "ADD COLUMN IF NOT EXISTS latest_verdict character varying(50)",
    # 006 — 001_wtf_schema.sql's fact_checks predates overall_verdict entirely
    # (only `verdict` existed at the base schema). No CHECK constraint here
    # deliberately — the test schema needs the COLUMN, not every downstream
    # migration's tightening of its allowed values.
    "ALTER TABLE wtf_test.fact_checks "
    "ADD COLUMN IF NOT EXISTS overall_verdict character varying(50)",
    # pre-078 — migration 078's idx_articles_latest_verdict predicate
    # (WHERE suppressed_reason IS NULL) needs the column to exist; the base
    # 001 schema predates it entirely.
    "ALTER TABLE wtf_test.articles "
    "ADD COLUMN IF NOT EXISTS suppressed_reason TEXT",
)


def _apply(conn, path):
    with open(path) as f:
        sql = f.read().replace("wtf.", "wtf_test.").replace("SCHEMA wtf", "SCHEMA wtf_test")
    for stmt in sql.split(";\n"):
        if stmt.strip():
            conn.execute(text(stmt))


@pytest.fixture()
def clean_schema(engine):
    """Drop + recreate wtf_test schema, apply base migration + column patches."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))
        conn.execute(text("CREATE SCHEMA wtf_test"))
    with engine.begin() as conn:
        _apply(conn, "what-the-fact/migrations/001_wtf_schema.sql")
    with engine.begin() as conn:
        for stmt in _SCHEMA_PATCHES:
            conn.execute(text(stmt))
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))


@pytest.fixture()
def entity_schema(clean_schema, engine):
    """wtf_test (from clean_schema) + isolated shared_test/parliament_test schemas with a
    seeded MP graph (one MP person entity with 2 article mentions, one journalist entity,
    plus parliament votes/expenses/promises). Endpoint tests point the app at these via
    WTF_SHARED_SCHEMA=shared_test / WTF_PARLIAMENT_SCHEMA=parliament_test. Never touches
    the prod shared/parliament schemas."""
    ddl = """
    DROP SCHEMA IF EXISTS shared_test CASCADE;
    DROP SCHEMA IF EXISTS parliament_test CASCADE;
    CREATE SCHEMA shared_test;
    CREATE SCHEMA parliament_test;
    CREATE TABLE shared_test.entities (
        id SERIAL PRIMARY KEY,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('person','organization','journalist')),
        canonical_name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        aliases TEXT[] NOT NULL DEFAULT '{}',
        roles JSONB NOT NULL DEFAULT '[]',
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE TABLE shared_test.entity_mentions (
        id SERIAL PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES shared_test.entities(id) ON DELETE CASCADE,
        product TEXT NOT NULL,
        content_type TEXT NOT NULL,
        content_id TEXT NOT NULL,
        mention_context TEXT,
        confidence NUMERIC(4,3),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE (entity_id, product, content_type, content_id)
    );
    CREATE TABLE parliament_test.mps (
        id SERIAL PRIMARY KEY, slug TEXT UNIQUE, name TEXT NOT NULL,
        party TEXT, riding TEXT, entity_id INTEGER REFERENCES shared_test.entities(id)
    );
    CREATE TABLE parliament_test.mp_votes (
        id SERIAL PRIMARY KEY, mp_id INTEGER REFERENCES parliament_test.mps(id),
        bill_number TEXT, description TEXT, vote TEXT, voted_at DATE
    );
    CREATE TABLE parliament_test.mp_expense_summary (
        mp_id INTEGER PRIMARY KEY REFERENCES parliament_test.mps(id),
        total_cents BIGINT, period TEXT
    );
    CREATE TABLE parliament_test.mp_promises (
        id SERIAL PRIMARY KEY, mp_id INTEGER REFERENCES parliament_test.mps(id),
        text TEXT, status TEXT
    );
    CREATE TABLE wtf_test.article_author_tags (
        id SERIAL PRIMARY KEY,
        article_id INTEGER NOT NULL,
        entity_id INTEGER NOT NULL REFERENCES shared_test.entities(id) ON DELETE CASCADE,
        match_type VARCHAR(20) NOT NULL DEFAULT 'rss_author',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE (article_id, entity_id)
    );
    ALTER TABLE wtf_test.articles ADD COLUMN IF NOT EXISTS bias_ensemble_band TEXT;
    ALTER TABLE wtf_test.articles ADD COLUMN IF NOT EXISTS bias_ensemble_score NUMERIC;
    """
    with engine.begin() as c:
        for stmt in ddl.split(";"):
            if stmt.strip():
                c.execute(text(stmt))
    with engine.begin() as c:
        eid_mp = c.execute(text(
            "INSERT INTO shared_test.entities (entity_type, canonical_name, slug) "
            "VALUES ('person','Jane Member','jane-member') RETURNING id")).scalar()
        eid_jo = c.execute(text(
            "INSERT INTO shared_test.entities (entity_type, canonical_name, slug) "
            "VALUES ('journalist','Bob Writer','bob-writer') RETURNING id")).scalar()
        eid_jo2 = c.execute(text(
            "INSERT INTO shared_test.entities (entity_type, canonical_name, slug) "
            "VALUES ('journalist','Carol Reporter','carol-reporter') RETURNING id")).scalar()
        mp_id = c.execute(text(
            "INSERT INTO parliament_test.mps (slug,name,party,riding,entity_id) "
            "VALUES ('jane-member','Jane Member','Independent','Testville',:e) RETURNING id"),
            {"e": eid_mp}).scalar()
        c.execute(text("INSERT INTO parliament_test.mp_votes (mp_id,bill_number,description,vote,voted_at) "
                       "VALUES (:m,'C-1','Test Bill','yea','2026-05-01')"), {"m": mp_id})
        c.execute(text("INSERT INTO parliament_test.mp_expense_summary (mp_id,total_cents,period) "
                       "VALUES (:m,123456,'2026-Q1')"), {"m": mp_id})
        c.execute(text("INSERT INTO parliament_test.mp_promises (mp_id,text,status) "
                       "VALUES (:m,'Lower taxes','in_progress')"), {"m": mp_id})
        sid = c.execute(text("INSERT INTO wtf_test.sources (slug,name,url) "
                             "VALUES ('src','Src','http://s') RETURNING id")).scalar()
        for i, band in enumerate(["left", "center"]):
            aid = c.execute(text(
                "INSERT INTO wtf_test.articles (source_id,external_id,title,body,url,published_at,"
                "bias_ensemble_band,bias_ensemble_score) "
                "VALUES (:s,:x,:t,'b',:u,:p,:band,:score) RETURNING id"),
                {"s": sid, "x": f"a{i}", "t": f"Headline {i}", "u": f"http://s/a{i}",
                 "p": f"2026-05-0{i+1}", "band": band, "score": -0.5 + i}).scalar()
            c.execute(text(
                "INSERT INTO shared_test.entity_mentions (entity_id,product,content_type,content_id) "
                "VALUES (:e,'wtf','article',:cid)"), {"e": eid_mp, "cid": str(aid)})
            c.execute(text(
                "INSERT INTO shared_test.entity_mentions (entity_id,product,content_type,content_id) "
                "VALUES (:e,'wtf','article',:cid)"), {"e": eid_jo2, "cid": str(aid)})
    yield {"mp_entity_id": eid_mp, "journalist_entity_id": eid_jo,
           "journalist_with_articles_entity_id": eid_jo2, "mp_id": mp_id, "source_id": sid}
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS shared_test CASCADE"))
        c.execute(text("DROP SCHEMA IF EXISTS parliament_test CASCADE"))
