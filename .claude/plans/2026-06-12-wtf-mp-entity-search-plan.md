# WTF MP Entity Search & Accountability API — Implementation Plan (Milestone A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose WTF coverage searchable/groupable by **MP**, with a read-only grouped-data API (`search` / `coverage` / `accountability`) over data that already exists in the `wtf` DB — no ingest or pipeline changes.

**Architecture:** A new `consumer/entities.py` Flask blueprint in the `wtf-consumer` app queries the existing `shared.entities` + `shared.entity_mentions` (uniform entity→article link) + `wtf.articles` (bias) + `parliament.*` (accountability, joined via `parliament.mps.entity_id`). Aggregations are plain indexed SQL (33k articles / ~6k mentions is small). One additive migration (`033`) adds indexes + extends the `entity_type` CHECK + creates the (initially-empty) `wtf.article_author_tags` table that Milestone B will populate. The `search` endpoint already accepts `type=journalist` (returns empty until Milestone B).

**Tech Stack:** Python 3 / Flask / SQLAlchemy Core (`create_engine` + `text()`); Postgres (hub `wtf` DB); pytest. Source: `/mnt/archie_brain/what-the-fact/`.

---

## Context, branching & deployment (read first)

- **Repo / source:** `/mnt/archie_brain/what-the-fact/`. Work on branch **`feat/wtf-mp-entity-search`** off `main`.
- **DB:** all `shared.*`, `wtf.*`, `parliament.*` schemas live in the **hub** Postgres `wtf` database: `docker exec archie_database psql -U archie -d wtf`.
- **Migrations are applied MANUALLY** (no runner in `deploy.sh`). Migration `033` is applied to the hub `wtf` DB by hand (Task 1, Step 6). It is additive + idempotent (`IF NOT EXISTS`), safe to run live.
- **Code deploy** (after merge): `wtf-consumer` is **image-baked** on Citadel/boston-2 → `ssh root@100.64.0.10 'cd /opt/archie-products/what-the-fact && docker compose up -d --build wtf-consumer'` (NEVER `restart` for code changes). Done in Task 6.
- **Verified facts (2026-06-11):** `parliament.mps` = 343 rows, **all 343 have `entity_id`** (FK → `shared.entities.id`). 470 `person` entities; 343 join to an MP. `shared.entity_mentions` carries MP↔article links (`product='wtf'`, `content_type='article'`, `content_id`=article id as TEXT). `wtf.articles` bias cols: `bias_ensemble_band`, `bias_ensemble_score`, `bias_v2_label`, `bias_v2_score`. No `author` column. `wtf.article_mp_tags(id, article_id, mp_id, match_type, created_at)`.

### Schema-var convention (testability + isolation)

`consumer/entities.py` reads schema names **at call time** (NOT module-level constants like `beats.py`'s `_S`, which breaks under test import-ordering). Three helpers:

```python
import os
def _wtf():    return os.environ.get("WTF_SCHEMA", "wtf")
def _shared(): return os.environ.get("WTF_SHARED_SCHEMA", "shared")
def _parl():   return os.environ.get("WTF_PARLIAMENT_SCHEMA", "parliament")
```

Tests set all three to `*_test` schemas built by the `entity_schema` fixture (Task 1) so they never touch prod `shared`/`parliament`.

---

## File structure

- **Create** `what-the-fact/migrations/033_journalist_entities.sql` — extend `entity_type` CHECK to allow `journalist`; create `wtf.article_author_tags` (empty until Milestone B); add search indexes on `shared.entity_mentions`, `shared.entities`, `wtf.article_author_tags`.
- **Create** `what-the-fact/consumer/entities.py` — `entities_bp` blueprint: `/api/entities/search`, `/api/entities/<id>/coverage`, `/api/entities/<id>/accountability`. Engine singleton + call-time schema helpers + a shared response envelope.
- **Modify** `what-the-fact/consumer/app.py` — register `entities_bp`.
- **Modify** `what-the-fact/tests/conftest.py` — add an `entity_schema` fixture that builds `*_test` `shared`/`parliament` schemas (minimal tables) + applies `033`, and seeds a deterministic graph used by endpoint tests.
- **Create** `what-the-fact/tests/test_entities_api.py` — endpoint tests (search, coverage, accountability, envelope, edge cases).

---

## Task 1: Migration 033 + test schema fixture

**Files:**
- Create: `what-the-fact/migrations/033_journalist_entities.sql`
- Modify: `what-the-fact/tests/conftest.py`
- Test: (fixture is exercised by Task 2+ tests; add a smoke test `tests/test_migration_033.py`)

- [ ] **Step 1: Write `033_journalist_entities.sql`**

```sql
-- 033_journalist_entities.sql — entity-search indexes + journalist support (Milestone A creates; B populates)
-- Idempotent + additive. Apply to hub `wtf` DB manually.

-- 1. Allow journalist entities (030 CHECK was person|organization only)
ALTER TABLE shared.entities DROP CONSTRAINT IF EXISTS entities_entity_type_check;
ALTER TABLE shared.entities
    ADD CONSTRAINT entities_entity_type_check
    CHECK (entity_type IN ('person', 'organization', 'journalist'));

-- 2. WTF-local writer-tag mirror (parallels wtf.article_mp_tags; stays empty until Milestone B)
CREATE TABLE IF NOT EXISTS wtf.article_author_tags (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    entity_id  INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    match_type VARCHAR(20) NOT NULL DEFAULT 'rss_author',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (article_id, entity_id)
);

-- 3. Search/group indexes
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity_ctype
    ON shared.entity_mentions (entity_id, content_type);
CREATE INDEX IF NOT EXISTS idx_entities_type_slug
    ON shared.entities (entity_type, slug);
CREATE INDEX IF NOT EXISTS idx_article_author_tags_entity
    ON wtf.article_author_tags (entity_id);
CREATE INDEX IF NOT EXISTS idx_article_author_tags_article
    ON wtf.article_author_tags (article_id);
```

- [ ] **Step 2: Add the `entity_schema` fixture to `tests/conftest.py`**

Append after the existing `clean_schema` fixture. It creates isolated `shared_test` + `parliament_test` schemas with only the tables the entity API touches, applies `033`-equivalent objects into them, and seeds a deterministic graph. (We hand-roll the minimal DDL rather than substitution-applying `030` because `030` also alters parliament tables that `001` doesn't create.)

```python
@pytest.fixture()
def entity_schema(clean_schema, engine):
    """wtf_test (from clean_schema) + isolated shared_test/parliament_test with a seeded
    MP graph. Endpoint tests set WTF_SHARED_SCHEMA=shared_test, WTF_PARLIAMENT_SCHEMA=parliament_test."""
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
    """
    with engine.begin() as c:
        for stmt in ddl.split(";"):
            if stmt.strip():
                c.execute(text(stmt))
    # --- seed deterministic graph ---
    with engine.begin() as c:
        # one MP person entity + one journalist entity
        eid_mp = c.execute(text(
            "INSERT INTO shared_test.entities (entity_type, canonical_name, slug) "
            "VALUES ('person','Jane Member','jane-member') RETURNING id")).scalar()
        eid_jo = c.execute(text(
            "INSERT INTO shared_test.entities (entity_type, canonical_name, slug) "
            "VALUES ('journalist','Bob Writer','bob-writer') RETURNING id")).scalar()
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
        # one source + two articles in wtf_test, mention the MP from both
        sid = c.execute(text("INSERT INTO wtf_test.sources (slug,name,url) "
                             "VALUES ('src','Src','http://s') RETURNING id")).scalar()
        for i, band in enumerate(["left", "center"]):
            aid = c.execute(text(
                "INSERT INTO wtf_test.articles (source_id,external_id,title,body,url,published_at,"
                "bias_ensemble_band,bias_ensemble_score) "
                "VALUES (:s,:x,:t,'b','http://s/'||:x,:p,:band,:score) RETURNING id"),
                {"s": sid, "x": f"a{i}", "t": f"Headline {i}",
                 "p": f"2026-05-0{i+1}", "band": band, "score": -0.5 + i}).scalar()
            c.execute(text(
                "INSERT INTO shared_test.entity_mentions (entity_id,product,content_type,content_id) "
                "VALUES (:e,'wtf','article',:cid)"), {"e": eid_mp, "cid": str(aid)})
    return {"mp_entity_id": eid_mp, "journalist_entity_id": eid_jo, "mp_id": mp_id, "source_id": sid}
```

> NOTE: if `wtf_test.articles` lacks `bias_ensemble_band`/`bias_ensemble_score` (they were added by a later migration than `001`), the executor must, in this same fixture, `ALTER TABLE wtf_test.articles ADD COLUMN IF NOT EXISTS bias_ensemble_band TEXT, ADD COLUMN IF NOT EXISTS bias_ensemble_score NUMERIC;` immediately before seeding. Verify with `\d wtf.articles` vs `001_wtf_schema.sql` and add the guard if needed.

- [ ] **Step 3: Write a migration smoke test** `tests/test_migration_033.py`

```python
from sqlalchemy import text

def test_entity_schema_seeds_mp(entity_schema, engine):
    with engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM shared_test.entity_mentions "
                           "WHERE entity_id=:e AND content_type='article'"),
                      {"e": entity_schema["mp_entity_id"]}).scalar()
    assert n == 2
```

- [ ] **Step 4: Run it — expect PASS**

Run: `cd /mnt/archie_brain/what-the-fact && WTF_DATABASE_URL=$WTF_DATABASE_URL pytest tests/test_migration_033.py -v`
Expected: PASS (fixture builds + seeds cleanly).

- [ ] **Step 5: Commit**

```bash
git add migrations/033_journalist_entities.sql tests/conftest.py tests/test_migration_033.py
git commit -m "feat(wtf): migration 033 (entity indexes + journalist support) + entity_schema test fixture"
```

- [ ] **Step 6: Apply 033 to the live hub `wtf` DB** (manual — additive/idempotent)

```bash
docker cp /mnt/archie_brain/what-the-fact/migrations/033_journalist_entities.sql archie_database:/tmp/033.sql
docker exec archie_database psql -U archie -d wtf -f /tmp/033.sql
# verify:
docker exec archie_database psql -U archie -d wtf -c "\d wtf.article_author_tags"
docker exec archie_database psql -U archie -d wtf -c "SELECT conname FROM pg_constraint WHERE conname='entities_entity_type_check';"
```
Expected: table exists; CHECK constraint present (now allows journalist).

---

## Task 2: `GET /api/entities/search`

**Files:**
- Create: `what-the-fact/consumer/entities.py`
- Modify: `what-the-fact/consumer/app.py`
- Test: `what-the-fact/tests/test_entities_api.py`

- [ ] **Step 1: Write the failing test**

```python
import os, pytest
from sqlalchemy import text
from consumer.app import create_app

@pytest.fixture()
def client(entity_schema, engine, monkeypatch):
    monkeypatch.setenv("WTF_SCHEMA", "wtf_test")
    monkeypatch.setenv("WTF_SHARED_SCHEMA", "shared_test")
    monkeypatch.setenv("WTF_PARLIAMENT_SCHEMA", "parliament_test")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    import consumer.entities as ent
    ent._engine = None  # engine bound to the test DB URL
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()

def test_search_mp_by_name(client, entity_schema):
    r = client.get("/api/entities/search?q=jane&type=mp")
    assert r.status_code == 200
    body = r.get_json()
    hits = body["results"]
    assert any(h["slug"] == "jane-member" and h["type"] == "mp" for h in hits)
    jane = next(h for h in hits if h["slug"] == "jane-member")
    assert jane["article_count"] == 2
    assert "coverage_pct" in body  # response envelope

def test_search_journalist_empty_until_milestone_b(client):
    r = client.get("/api/entities/search?q=bob&type=journalist")
    assert r.status_code == 200
    # Bob has an entity row but ZERO article mentions yet → article_count 0, still returned
    hits = r.get_json()["results"]
    assert all(h["article_count"] == 0 for h in hits if h["slug"] == "bob-writer")

def test_search_requires_valid_type(client):
    r = client.get("/api/entities/search?q=x&type=senator")
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /mnt/archie_brain/what-the-fact && pytest tests/test_entities_api.py -v`
Expected: FAIL — `consumer.entities` import error / 404 route.

- [ ] **Step 3: Create `consumer/entities.py` with the search route + shared helpers**

```python
import os
from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine, text

entities_bp = Blueprint("entities", __name__)

_engine = None
def _eng():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine

def _wtf():    return os.environ.get("WTF_SCHEMA", "wtf")
def _shared(): return os.environ.get("WTF_SHARED_SCHEMA", "shared")
def _parl():   return os.environ.get("WTF_PARLIAMENT_SCHEMA", "parliament")

# Writer attribution coverage of the WTF corpus. MP coverage is "as-tagged".
# Milestone B replaces this with a live computed stat; for now it is a static
# honesty marker so consumers never mistake partial data for complete.
def _coverage_pct(conn):
    total = conn.execute(text(f"SELECT count(*) FROM {_wtf()}.articles")).scalar() or 0
    attributed = conn.execute(text(
        f"SELECT count(DISTINCT content_id) FROM {_shared()}.entity_mentions "
        f"WHERE product='wtf' AND content_type='article'")).scalar() or 0
    return round(100.0 * attributed / total, 1) if total else 0.0

def _envelope(conn, results):
    return {"results": results, "coverage_pct": _coverage_pct(conn)}

def _mp_filter(alias=""):
    # an MP = a person entity that joins to a parliament MP row
    p = _parl()
    return (f"e.entity_type='person' AND EXISTS "
            f"(SELECT 1 FROM {p}.mps m WHERE m.entity_id=e.id)")

@entities_bp.get("/api/entities/search")
def search_entities():
    q = (request.args.get("q") or "").strip()
    etype = (request.args.get("type") or "").strip().lower()
    if etype not in ("mp", "journalist"):
        return jsonify({"error": "type must be 'mp' or 'journalist'"}), 400
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
    except ValueError:
        limit = 20

    s, p = _shared(), _parl()
    type_clause = _mp_filter() if etype == "mp" else "e.entity_type='journalist'"
    like = f"%{q.lower()}%"
    sql = text(f"""
        SELECT e.id, e.canonical_name, e.slug,
               (SELECT count(DISTINCT em.content_id) FROM {s}.entity_mentions em
                 WHERE em.entity_id=e.id AND em.product='wtf' AND em.content_type='article')
                 AS article_count
          FROM {s}.entities e
         WHERE {type_clause}
           AND (:q='' OR lower(e.canonical_name) LIKE :like OR :q = ANY(SELECT lower(a) FROM unnest(e.aliases) a))
         ORDER BY article_count DESC, e.canonical_name ASC
         LIMIT :lim
    """)
    with _eng().connect() as c:
        rows = c.execute(sql, {"q": q.lower(), "like": like, "lim": limit}).mappings().all()
        results = [{"id": r["id"], "type": etype, "canonical_name": r["canonical_name"],
                    "slug": r["slug"], "article_count": int(r["article_count"])} for r in rows]
        return jsonify(_envelope(c, results))
```

- [ ] **Step 4: Register the blueprint in `consumer/app.py`**

Add alongside the existing `register_blueprint` calls (mirror the `beats_bp` lines):

```python
from .entities import entities_bp
app.register_blueprint(entities_bp)
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/test_entities_api.py -v -k search`
Expected: PASS (3 search tests).

- [ ] **Step 6: Commit**

```bash
git add consumer/entities.py consumer/app.py tests/test_entities_api.py
git commit -m "feat(wtf): /api/entities/search (mp|journalist) over shared entity graph"
```

---

## Task 3: `GET /api/entities/<id>/coverage`

**Files:**
- Modify: `what-the-fact/consumer/entities.py`
- Test: `what-the-fact/tests/test_entities_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_coverage_returns_counts_trend_and_bias(client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = client.get(f"/api/entities/{eid}/coverage")
    assert r.status_code == 200
    b = r.get_json()
    assert b["article_count"] == 2
    # bias distribution from bias_ensemble_band across the 2 seeded articles
    assert b["bias_distribution"]["left"] == 1
    assert b["bias_distribution"]["center"] == 1
    # monthly trend buckets present
    assert isinstance(b["trend"], list) and b["trend"]
    assert "coverage_pct" in b

def test_coverage_unknown_entity_404(client):
    r = client.get("/api/entities/999999/coverage")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_entities_api.py -v -k coverage`
Expected: FAIL — route 404.

- [ ] **Step 3: Add the coverage route to `consumer/entities.py`**

```python
@entities_bp.get("/api/entities/<int:entity_id>/coverage")
def entity_coverage(entity_id):
    frm = request.args.get("from")
    to = request.args.get("to")
    s, w = _shared(), _wtf()
    date_clause = ""
    params = {"eid": entity_id}
    if frm:
        date_clause += " AND a.published_at >= :frm"; params["frm"] = frm
    if to:
        date_clause += " AND a.published_at <= :to"; params["to"] = to
    with _eng().connect() as c:
        ent = c.execute(text(f"SELECT id, entity_type, canonical_name, slug "
                             f"FROM {s}.entities WHERE id=:eid"), {"eid": entity_id}).mappings().first()
        if not ent:
            return jsonify({"error": "entity not found"}), 404
        # join mentions -> articles (content_id is TEXT)
        base = (f"FROM {s}.entity_mentions em JOIN {w}.articles a "
                f"ON a.id = em.content_id::integer "
                f"WHERE em.entity_id=:eid AND em.product='wtf' AND em.content_type='article'{date_clause}")
        count = c.execute(text(f"SELECT count(DISTINCT a.id) {base}"), params).scalar()
        bias_rows = c.execute(text(
            f"SELECT COALESCE(a.bias_ensemble_band,'unknown') band, count(DISTINCT a.id) n {base} "
            f"GROUP BY 1"), params).mappings().all()
        trend_rows = c.execute(text(
            f"SELECT to_char(date_trunc('month', a.published_at),'YYYY-MM') bucket, "
            f"count(DISTINCT a.id) n {base} GROUP BY 1 ORDER BY 1"), params).mappings().all()
        outlet_rows = c.execute(text(
            f"SELECT src.slug, src.name, count(DISTINCT a.id) n {base} "
            f"JOIN {w}.sources src ON src.id=a.source_id GROUP BY src.slug, src.name "
            f"ORDER BY n DESC LIMIT 10"), params).mappings().all()
        body = {
            "entity": {"id": ent["id"], "type": ("mp" if ent["entity_type"] == "person" else ent["entity_type"]),
                       "canonical_name": ent["canonical_name"], "slug": ent["slug"]},
            "article_count": int(count or 0),
            "bias_distribution": {r["band"]: int(r["n"]) for r in bias_rows},
            "trend": [{"month": r["bucket"], "count": int(r["n"])} for r in trend_rows],
            "top_outlets": [{"slug": r["slug"], "name": r["name"], "count": int(r["n"])} for r in outlet_rows],
            "coverage_pct": _coverage_pct(c),
        }
        return jsonify(body)
```

> NOTE on the `outlet_rows` SQL: the extra `JOIN {w}.sources` must appear inside `base` ordering — since `base` already ends at the WHERE clause, append the join via a derived query. If SQLAlchemy rejects the join-after-where ordering, rewrite as: `SELECT src.slug, src.name, count(DISTINCT a.id) n FROM {s}.entity_mentions em JOIN {w}.articles a ON a.id=em.content_id::integer JOIN {w}.sources src ON src.id=a.source_id WHERE em.entity_id=:eid AND em.product='wtf' AND em.content_type='article'{date_clause} GROUP BY src.slug, src.name ORDER BY n DESC LIMIT 10`. Prefer the explicit form; the `base` reuse is only a convenience.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_entities_api.py -v -k coverage`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add consumer/entities.py tests/test_entities_api.py
git commit -m "feat(wtf): /api/entities/<id>/coverage — counts, bias dist, monthly trend, top outlets"
```

---

## Task 4: `GET /api/entities/<id>/accountability` (MP only)

**Files:**
- Modify: `what-the-fact/consumer/entities.py`
- Test: `what-the-fact/tests/test_entities_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_accountability_for_mp(client, entity_schema):
    eid = entity_schema["mp_entity_id"]
    r = client.get(f"/api/entities/{eid}/accountability")
    assert r.status_code == 200
    b = r.get_json()
    assert b["mp"]["name"] == "Jane Member"
    assert b["expense_summary"]["total_cents"] == 123456
    assert any(v["bill_number"] == "C-1" for v in b["recent_votes"])
    assert any(p["text"] == "Lower taxes" for p in b["promises"])

def test_accountability_404_for_journalist(client, entity_schema):
    eid = entity_schema["journalist_entity_id"]
    r = client.get(f"/api/entities/{eid}/accountability")
    assert r.status_code == 404  # not an MP
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_entities_api.py -v -k accountability`
Expected: FAIL — route 404.

- [ ] **Step 3: Add the accountability route to `consumer/entities.py`**

```python
@entities_bp.get("/api/entities/<int:entity_id>/accountability")
def entity_accountability(entity_id):
    s, p = _shared(), _parl()
    with _eng().connect() as c:
        mp = c.execute(text(
            f"SELECT m.id, m.name, m.party, m.riding FROM {p}.mps m "
            f"JOIN {s}.entities e ON e.id=m.entity_id WHERE e.id=:eid"),
            {"eid": entity_id}).mappings().first()
        if not mp:
            return jsonify({"error": "entity is not a mapped MP"}), 404
        mp_id = mp["id"]
        votes = c.execute(text(
            f"SELECT bill_number, description, vote, voted_at FROM {p}.mp_votes "
            f"WHERE mp_id=:m ORDER BY voted_at DESC NULLS LAST LIMIT 20"),
            {"m": mp_id}).mappings().all()
        exp = c.execute(text(
            f"SELECT total_cents, period FROM {p}.mp_expense_summary WHERE mp_id=:m"),
            {"m": mp_id}).mappings().first()
        promises = c.execute(text(
            f"SELECT text, status FROM {p}.mp_promises WHERE mp_id=:m LIMIT 50"),
            {"m": mp_id}).mappings().all()
        return jsonify({
            "mp": {"id": mp["id"], "name": mp["name"], "party": mp["party"], "riding": mp["riding"]},
            "recent_votes": [dict(v) for v in votes],
            "expense_summary": (dict(exp) if exp else None),
            "promises": [dict(pr) for pr in promises],
        })
```

> NOTE: production `parliament.*` also has `mp_lobbying_summary`, `mp_disclosures`, `mp_committees` (per spec §2). They are OPTIONAL extras — add them only after confirming their columns with `\d parliament.mp_lobbying_summary` etc.; do NOT block this task on them. The test fixture intentionally seeds only votes/expenses/promises. If you add them, extend the fixture + assertions in the same commit.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_entities_api.py -v -k accountability`
Expected: PASS.

- [ ] **Step 5: Run the FULL suite**

Run: `pytest tests/test_entities_api.py tests/test_migration_033.py -v`
Expected: all PASS. Also run `pytest tests/test_consumer_routes.py -v` to confirm no regression in existing routes.

- [ ] **Step 6: Commit**

```bash
git add consumer/entities.py tests/test_entities_api.py
git commit -m "feat(wtf): /api/entities/<id>/accountability — votes, expenses, promises via parliament.mps.entity_id"
```

---

## Task 5: Paywall posture + final review

**Files:**
- Modify: `what-the-fact/consumer/entities.py` (only if gating is required)
- Test: `what-the-fact/tests/test_entities_api.py`

- [ ] **Step 1: Decide gating (OPEN QUESTION — confirm with owner before coding).** Spec §5/§8: grouped metadata is likely public; deep detail may be gated. Default for Milestone A: **all three endpoints PUBLIC** (they expose only aggregate counts + public parliamentary data — nothing paywalled). If the owner wants `/accountability` or `/coverage` detail gated, wrap with the same auth dependency the existing gated WTF routes use (find it in `consumer/auth.py` / `consumer/routes.py`; mirror that decorator). Record the decision in the commit message.

- [ ] **Step 2: (If gating chosen) add the test first**, asserting `401`/redirect for an unauthenticated request to the gated endpoint, then apply the decorator. (If public, skip — note "endpoints public per owner decision" and move on.)

- [ ] **Step 3: Self-review the suite for completeness**, then commit any gating change:

```bash
git add -A && git commit -m "chore(wtf): entity API auth posture (public aggregates) per owner decision"
```

---

## Task 6: Deploy + live verification

- [ ] **Step 1: Push branch + open PR**

```bash
git push -u origin feat/wtf-mp-entity-search
gh pr create --head feat/wtf-mp-entity-search --title "feat(wtf): MP entity search & accountability API (Milestone A)" --body "Read-only grouped-data API over existing shared entity graph + parliament data. Migration 033 (additive) applied to hub wtf DB. No ingest changes."
```
(Use `/commit-push-pr` + `/merge-pr` per repo convention so F.O.R.G.E. reviews.)

- [ ] **Step 2: After merge — deploy wtf-consumer on Citadel/boston-2 (image-baked)**

```bash
ssh root@100.64.0.10 'cd /opt/archie-products/what-the-fact && git pull && docker compose up -d --build wtf-consumer'
```
(If the boston-2 tree is not a git checkout, sync first: `rsync -avz --exclude=.env /mnt/archie_brain/what-the-fact/ root@100.64.0.10:/opt/archie-products/what-the-fact/`.)

- [ ] **Step 3: Confirm 033 already applied to hub `wtf` DB** (done in Task 1 Step 6 — re-verify):

```bash
docker exec archie_database psql -U archie -d wtf -c "\dt wtf.article_author_tags"
```

- [ ] **Step 4: Live smoke (real data)** — from a host that reaches boston-2 (mesh) or via the public site host:

```bash
# search a real MP (188 are tagged):
curl -s 'http://100.64.0.10:8103/api/entities/search?q=trudeau&type=mp' | head
# coverage + accountability on the returned id:
curl -s 'http://100.64.0.10:8103/api/entities/<ID>/coverage' | head
curl -s 'http://100.64.0.10:8103/api/entities/<ID>/accountability' | head
```
(Per cluster rules curl is blocked in this harness — run these via `ctx_execute` shell or have P.R.O.B.E. hit them; do NOT use the public CDN hostname for verification, use the boston-2 mesh host.)
Expected: search returns ranked MPs with non-zero `article_count`; accountability returns real votes/expenses.

- [ ] **Step 5: P.R.O.B.E. smoke (optional but preferred)** — add the 3 endpoints to the WTF QA smoke suite (ties into task #3350) or delegate: `mcp__archie__delegate_task(capability='research', reason='Smoke-test WTF /api/entities/{search,coverage,accountability} on boston-2 wtf-consumer and report status codes + sample payloads')`.

- [ ] **Step 6: Update Dev HQ** — `complete_task` #4078-equivalent milestone-A note, `log_decision` (split into Milestones A/B; entity_mentions as uniform link; manual 033 apply), `update_project_understanding` for project #373.

---

## Self-Review (run against the spec)

**Spec coverage (§5 endpoints):**
- `search?type=mp|journalist` → Task 2 ✅ (journalist returns rows w/ 0 count until Milestone B).
- `<id>/coverage` (counts, trend, bias dist, top outlets) → Task 3 ✅.
- `<id>/accountability` (mp only; votes/expenses/promises) → Task 4 ✅. Lobbying/disclosures/committees flagged optional.
- `<id>/profile` (journalist) → **Milestone B** (deferred — needs journalist data).
- `coverage_pct`/freshness envelope → `_coverage_pct` + envelope ✅.

**Deferred to Plan 2 (Milestone B — journalist capture):** `033` already lays the groundwork (CHECK + `article_author_tags` + indexes). Plan 2 = `shared/author_resolver.py` (pure, unit-tested) + RSS author capture in `rss_generic.py`/`cbc_english.py`/`global_news.py` + tag-write hook in `persist.py` after `aid = upsert_article(...)` + `/api/entities/<id>/profile` + journalist `search` populating + (deferred further) the LLM byline backfill fleet job (needs ingest-scheduler grounding + welfare/cost decision, spec §8 Q2).

**Placeholder scan:** all SQL + route + test code is concrete. Two explicit "confirm in code" notes: (a) `wtf_test.articles` bias columns may need an `ADD COLUMN IF NOT EXISTS` guard in the fixture (Task 1 Step 2 note); (b) optional parliament extras in Task 4. Both are guarded, not blocking.

**Type consistency:** schema helpers `_wtf()/_shared()/_parl()` used identically across all routes; `entity_mentions.content_id::integer = articles.id` join used consistently; `type=mp` ⇔ `entity_type='person' AND EXISTS(parliament.mps)` consistently; response keys (`results`, `article_count`, `coverage_pct`, `bias_distribution`, `trend`, `top_outlets`) consistent between routes + tests.

**Open questions carried to execution:** (1) public vs gated (Task 5, owner decision); (2) whether boston-2 WTF tree is git vs rsync (Task 6 Step 2 handles both); (3) optional parliament tables (Task 4 note).
