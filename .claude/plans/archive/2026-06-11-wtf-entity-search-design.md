# WTF Entity Search & Grouped Data — Design Spec

**Date:** 2026-06-11 · **Project context:** WTF (#364) + Shared Entity Graph (#373) + Parliamentary Accountability (#348) + Journalist Profiles (#3329)
**Status:** Design — pending owner review → implementation plan

## 1. Goal

Make WTF coverage searchable and groupable by **two entity types** — **MPs** and **news writers (journalists)** — exposing a **grouped-data / query API first** (reader UI is a later, separate spec). MP results cross-link to parliamentary accountability data (votes/expenses/promises/lobbying); writer results expose beats, outlet, bias lean, and which MPs/entities they cover.

This is the WTF surface of the Shared Entity Graph's accountability chain (Money→MP→Vote→Policy→Contract→Market→**Coverage**→Public).

## 2. Current state (verified 2026-06-11, `wtf` DB)

**MP side — already built, just unsurfaced:**
- `wtf.article_mp_tags`: 5,966 tags, **4,447 articles → 188 MPs** (of 33,308 articles).
- `shared.entities`: 470 `person` + 17 `organization` (canonical graph). `shared.entity_mentions`: 5,966 (MP mentions, dual-written with `article_mp_tags`).
- `parliament.*`: `mp_votes`, `mp_expenses`, `mp_expense_summary`, `mp_disclosures`, `mp_promises`, `mp_committees`, `mp_lobbying_summary`.

**Writer side — NOT built:**
- `wtf.articles` has **no author column**; no authors table; no journalist entities.
- Bylines are **not reliably in bodies** (244/33,308 match "By Name"); **83% of articles have no body** (`body_source`: 27,621 empty, 4,279 playwright, 1,408 rss_full).
- `wtf.sources` has no author field — but RSS feed *entries* very likely carry `<author>`/`<dc:creator>`, currently **dropped at ingest**.

**Implication:** MP search = surfacing existing data. Writer search = build a capture pipeline first; coverage starts **partial and grows** (forward RSS author + LLM byline on the ~5,687 body-bearing articles; body-less historical stays unattributed). This is an accepted, honest limitation — not a blocker.

## 3. Data model

Build on the **Shared Entity Graph**, not a WTF-local authors table (MPs already live there; writers should too, so the whole platform can reuse them).

- **Journalists** → `shared.entities (entity_type='journalist', canonical_name, slug, aliases jsonb, metadata jsonb)`. `metadata.outlets` = array of source slugs the byline has appeared under. Resolution is **global-canonical** (one entity per normalized name), with outlets tracked in metadata — revisit only if name collisions become a real problem.
- **Article→writer links** → `shared.entity_mentions (entity_id, product='wtf', content_type='article', content_id=article_id, confidence, mention_context)` — the exact pattern MP mentions use.
- **WTF-local mirror** → new `wtf.article_author_tags (id, article_id, entity_id, match_type, created_at)`, mirroring `wtf.article_mp_tags`, so WTF-side group-by joins stay fast and local (dual-write, same as MP tags do today).
- **Indexes:** `entity_mentions (entity_id, content_type)`, `article_author_tags (entity_id)`, `article_author_tags (article_id)`, `entities (entity_type, slug)`.

Non-goal: changing the existing MP tag pipeline. We read it as-is.

## 4. Author-capture pipeline (the new, gating component)

Two sources feeding one resolver:

1. **Ingest capture (forward, free):** modify `wtf-ingest` RSS parsing to read `entry.author` / `dc:creator` (and `<author>` in Atom). Pass the raw byline string to the resolver. No LLM.
2. **LLM byline backfill (body-bearing only):** a scheduled fleet job (DHQ dispatch → local 7B, e.g. W.A.T.C.H./S.P.E.C.T.R.A.) over the ~5,687 articles that have a body but no RSS author → extract byline → resolver. Batched, night-capped, idempotent (skip already-attributed). Follows `module-work-pattern.md` (recurring work dispatched to the fleet, never the web thread).

**Resolver** (`resolve_author(raw_byline, source_slug) -> entity_id | None`):
- Clean: strip "By ", outlet suffixes, "and"/commas → may yield multiple names (co-bylines → multiple mentions).
- Normalize: lowercase, strip punctuation/accents → `slug`.
- Drop non-bylines: wire services ("GLOBE NEWSWIRE", "The Canadian Press", "Staff", "Editorial") via a stoplist → tagged as organization or skipped (config-driven, extendable).
- Match existing `slug`/alias → else create `entity_type='journalist'`. Append `source_slug` to `metadata.outlets`.
- Write `entity_mentions` + `article_author_tags`.

**Coverage expectation:** writer attribution covers articles from feeds that publish authors + body-bearing articles; surfaced as a `coverage_pct` stat so the gap is visible, not hidden.

## 5. Grouped-data API (the deliverable)

Read-only endpoints. **Placement: `wtf-consumer` app** (owns the `wtf` DB + already serves the public site) — a new `entities` blueprint/routes module. Aggregations in SQL (33k articles / ~12k tags is small; indexed on-demand queries; add materialized views only if a hot endpoint needs it).

- `GET /api/entities/search?q=<name>&type=mp|journalist&limit=` → ranked entity matches (id, type, canonical_name, slug, article_count).
- `GET /api/entities/<id>/coverage?from=&to=` → article_count, time-trend buckets, **bias distribution** (from `bias_ensemble_score`/`bias_v2`), top outlets, top beats, sample recent articles.
- `GET /api/entities/<id>/accountability` *(mp only)* → joins `parliament.*`: recent votes, expense summary, promises, lobbying summary, disclosures — keyed by the MP's parliament id (mapping: `shared.entities.metadata.parliament_mp_id`, or a join table if not present — **confirm the existing MP↔parliament key during planning**).
- `GET /api/entities/<id>/profile` *(journalist)* → beats covered, outlet(s), bias lean of their articles, top co-mentioned MPs/entities, volume trend.

All endpoints return `coverage_pct`/freshness so consumers know the data's completeness. Auth: same paywall posture as existing WTF APIs (grouped metadata likely public; deep detail may be gated — confirm in planning).

## 6. Build order (phases → become the implementation plan)

1. **Schema** — `entity_type='journalist'` convention, `wtf.article_author_tags`, indexes. Confirm/define the MP↔`parliament` key.
2. **Resolver** — `resolve_author()` + name-normalization + wire-service stoplist, unit-tested in isolation.
3. **Ingest capture** — wtf-ingest reads RSS author → resolver (forward). Rebuild+redeploy wtf-ingest on Citadel/boston-2 (image-baked; `docker compose up -d --build wtf-ingest`).
4. **LLM backfill job** — scheduled fleet job over body-bearing unattributed articles.
5. **Grouped API** — `entities` routes in wtf-consumer; coverage/accountability/profile/search; tests.
6. *(Later, separate spec)* reader-facing search UI.

## 7. Non-goals / risks

- **No reader UI** in this spec (deferred).
- Body-less historical articles (27,621) stay unattributed — acceptable; the `coverage_pct` stat keeps it honest.
- Author disambiguation is name-based v1 (two distinct people sharing a name merge) — accept for v1; revisit if it bites.
- Deployment: ingest + API changes ship to **Citadel/boston-2** (image-baked, full rebuild); schema migrations run against the hub `wtf` DB.
- Cross-product reuse: because writers land in `shared.entities`, other Watch products can consume them later for free (the #373 payoff).

## 8. Open questions for planning

1. The existing **MP→parliament key** — how does a `shared.entities` MP row map to `parliament.*` rows today? (Find it before building `/accountability`.)
2. Writer backfill aggressiveness — all ~5,687 body-bearing in one pass, or rate-limited nightly? (Welfare/cost.)
3. Public vs paywalled split for the grouped endpoints.

## 9. Implementation grounding (source map, verified 2026-06-11)

WTF source on hub: **`/mnt/archie_brain/what-the-fact/`** (image-baked → deploy to **Citadel/boston-2** `root@100.64.0.10:/opt/archie-products/what-the-fact/`, `docker compose up -d --build wtf-ingest|wtf-consumer`). `shared.*` + `wtf.*` schemas both live in the hub Postgres **`wtf`** database (`psql -U archie -d wtf`).

- **Migrations:** `what-the-fact/migrations/NNN_*.sql`, sequential; latest = `032`; shared entity graph = **`030_shared_entity_graph.sql`**. New migration = **`033_journalist_entities.sql`** (`wtf.article_author_tags` + indexes; journalists reuse `shared.entities`). *To confirm next session: how migrations are applied in prod (deploy.sh? manual psql?).*
- **Ingest:** `ingest/sources/rss_generic.py` (generic RSS), with `cbc_english.py` / `global_news.py` overriding. Author capture goes where the per-`entry` article dict is built — `feedparser` exposes `entry.get('author')` / `entry.get('authors')[i]['name']`. *Read rss_generic.py to find the exact dict-build site.*
- **Consumer API:** Flask blueprints registered in `consumer/app.py` via `from .X import X_bp; app.register_blueprint(X_bp)`. New file `consumer/entities.py` → `entities_bp`. ⚠️ **`consumer/db.py` is SQLite (billing only)** — for the `wtf` Postgres data the new routes must use the Postgres helper that `consumer/routes.py`/`beats.py` already use (read one of them to find it; likely psycopg2 or SQLAlchemy).
- **Resolver:** lives in **`shared/`** (`shared/author_resolver.py`) so both ingest and the LLM backfill job import it — pure function, unit-testable in isolation.
- **LLM backfill:** new ingest-side scheduled job; dispatch to the hub fleet via `BRIDGE_URL=http://100.64.0.4:3000` (DHQ), local 7B, batched/night-capped (per `module-work-pattern.md`).
- **Tests:** `pytest` (config in `pyproject.toml`); `tests/conftest.py` builds a fresh `wtf_test` schema but currently applies **only `001_wtf_schema.sql`** — ⚠️ extend it to also apply `030` + `033` (and create the `shared` schema) so entity tests have the tables. Existing example: `tests/test_consumer_routes.py`.

**Next session = write the implementation plan** (`superpowers:writing-plans`) from this spec: read `rss_generic.py`, the consumer Postgres helper (in `routes.py`/`beats.py`), `030_shared_entity_graph.sql`, and `shared/` layout; then produce bite-sized TDD tasks. Branch `spec/wtf-entity-search` holds this spec.
