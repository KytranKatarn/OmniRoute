# Shared Entity Graph — Buildable Blueprint v2 (project #373)

**Author:** Lead architect (merge of AUDIT + 8 component designs + adversarial re-audit)
**Date:** 2026-06-14
**Project:** archie-platform #373 — Shared Entity Graph — Cross-Watch Identity Resolution
**Status:** REVISED v2. Supersedes blueprint v1. Folds in: the FROZEN edge-vocabulary ADR (ADR-EG-001), the 4 locked owner decisions, schema must-fixes S1–S7, infra must-fixes I1–I3, and wave-order must-fixes W1–W4.
**Subordinate to:** `2026-06-14-entity-graph-edge-vocabulary-adr.md` (ADR-EG-001, FROZEN). **Where this blueprint and the ADR disagree on node types, edge strings, or the `chain_link_types` seed, the ADR wins.** This blueprint's v1 draft CHECK (`+news_outlet/vendor/case/tender`) and v1 `chain_link_types` seed were WRONG and are corrected here per the ADR.
**Pace:** Author-only this wave. NO git commit/push, NO applying the migration, NO docker deploy. Sign-off happens AFTER this wave.

---

## 0. TL;DR — the decisions this blueprint settles (now LOCKED)

1. **WHERE THE GRAPH LIVES** → the hub **`wtf` PostgreSQL DB, `shared` schema** (migrations 030/033, live). NOT the hub `archie` DB. NOT per-product SQLite. The `archie.shared.*` tables (migration 393) are a **separate follow/alert SIGNAL BUS** (entity_type department/topic/keyword), NEVER read or written for node/edge/chain lookups. (ADR-EG-001 §3, must-fix S6.)
2. **SINGLE WRITER** → all 4 standalone (gov/civic/legal/market) adapters **POST mentions+edges over the mesh** to ONE ingest endpoint **inside the WTF consumer app** (`POST /api/internal/entity-graph/ingest`, reuses `_upsert_entity`). Only WTF's own hub-resident adapters write the DB directly. No third resolver. (must-fix I1.)
3. **IDENTITY STABILITY** → `shared.entities.id` is the immutable, never-reused, never-DELETEd canonical id (trigger-enforced). Merges **tombstone** (`status='merged'`, `merged_into=winner`) and are **reversible** from a JSONB audit snapshot.
4. **CONFIDENCE POLICY** → deterministic external-key match = auto-merge @ conf 1.0; fuzzy ≥ **0.92** = auto-merge (logged, reversible); **0.75–0.92** = human review queue; < 0.75 = recorded reject. Thresholds are tunable `dedup_config` rows; **start conservative**.
5. **PUBLIC vs GATED** (OWNER LOCKED) → chain **SHAPE + bias + connected/gap status is FREE** (no-auth, cached); **deep per-link records + rationale are `wtf-premium`** gated at the API. Browser→public hub ingress (Beacon); server-to-server→mesh (`100.64.0.4`).
6. **NODE + EDGE vocabulary FROZEN** (ADR-EG-001) → nodes = `person | organization | journalist` ONLY; tender/case/bill/vote/policy/appointment-order/ethics-report are CONTENT via `entity_mentions`, NOT nodes (S1/S2). 7 spine + 3 enrichment edge strings, frozen byte-for-byte.
7. **HONESTY** (OWNER LOCKED) → **Policy (Link 4 `enacted_as`)** and **Market-securities (Link 6 `market_reaction_to`)** have NO ingest pipeline → `chain_link_types.has_data=FALSE`, API returns `status:"no_data"`, UI renders permanently dim. **NEVER render an empty link as populated.**
8. **DONOR SCOPE** (OWNER LOCKED) → Elections Canada donors materialize ONLY at **≥$200 aggregate AND slug-match-to-existing-entity first pass** — avoids the 4.1M-row explosion + review-queue flood.

---

## 1. Overview

### 1.1 What we are building

The 8-link **Accountability Chain** — *Money → MP → Vote → Policy → Contract → Market → Coverage → Public* — as a **typed traversal over one canonical entity graph**, fed by all five Watch products, consumed asymmetrically (see §9). The graph is NOT a new store; it is the existing `shared.*` schema in the hub `wtf` DB, generalized from WTF-only to cross-product.

### 1.2 What ALREADY exists (do not rebuild — eliminate duplication)

| Shipped artifact | What it is | Status |
|---|---|---|
| Migration **030** | `shared.entities` (person\|organization), `shared.entity_mentions` (UNIQUE entity/product/content_type/content_id), `shared.entity_relationships` (UNIQUE from/to/type/source_product/source_id), 5 relationship types: appointed_to, lobbied_by, donated_to, employs, contracts_with | LIVE in hub `wtf` DB |
| Migration **033** | CHECK extended to include `journalist`; `wtf.article_author_tags` table | LIVE |
| **Milestone A** (PR #1636) | MP entity search: `GET /api/entities/search`, `/coverage`, `/accountability`, `/profile` in `consumer/entities.py`; MPs seeded into `shared.entities` via `entity_graph.py`; `entity_mentions_sync.py` bridges `wtf.article_mp_tags` → `shared.entity_mentions` | SHIPPED — 343/343 MPs linked |
| **Milestone B / #4079** (PR #1657) | Journalist pipeline B1–B3: `shared/author_resolver.py` (`resolve_byline`), forward RSS byline capture, `wtf.article_author_tags` population, gated journalist `/profile` | **SHIPPED** (B4 LLM backfill split off as T-B4) |
| Hub `cross_watch` blueprint | `/api/cross-watch/{entities,follow,alerts,following,search,procurement,parliament-votes,legal-rulings,civic-events}` — the cross-product **consume backbone** + follow/alert system | LIVE (hub `archie` DB — the signal bus, NOT the graph) |
| `consumer/cross_watch.py` | Server-side mesh proxy (`_proxy_get/_post/_delete`, Bearer token, `CROSS_WATCH_HUB_URL=http://100.64.0.4:3000`) — the ONLY browser→hub path | LIVE — **the pattern the chain proxy copies** |

### 1.3 The 5 #373 tasks against shipped reality

| Task | Title | Reality (from REVIEW_SCHEMA audit) |
|---|---|---|
| **#3790** | Canonical entity schema + identity keys | **Partial** — 030/033 exist; needs migration 034 (external-key index, source-mention/audit tables, provenance + merge columns, pg_trgm). Node CHECK stays `person|organization|journalist` (ADR S1). |
| **#3791** | Per-dataset adapters | **WTF-only** — Gov/Civic/Legal/Market adapters do NOT exist |
| **#3792** | Dedup engine + confidence | **WTF-slug-only** — no cross-watch dedup, no reversible merge, no review queue |
| **#3793** | 8-link chain query API | **Unbuilt** — `/accountability` covers 1 segment (MP→Vote/Expense) only |
| **#4079** | WTF journalist pipeline B | **SHIPPED (B1–B3)** — **CLOSE AS SHIPPED**, B4 backfill split off to NEW T-B4 (see §11) |

---

## 2. Conflict Resolution (the merge decisions)

### 2.1 WHERE the graph lives — `wtf` DB, not `archie` DB (FROZEN, ADR §3 / S6)

**The dual-schema rule, restated as a hard boundary:**

| | **CANONICAL GRAPH (the truth)** | **SIGNAL BUS (NOT the truth)** |
|---|---|---|
| Database | hub **`wtf`** DB | hub **`archie`** DB |
| Table | `shared.entities` (+ mentions, relationships, external_ids, source_mention, chain_link_types, …) | `shared.entities` (migration 393) |
| `entity_type` | `person`, `organization`, `journalist` | `department`, `topic`, `keyword` |
| Purpose | Node/edge resolution + chain traversal | Follow/alert signal bus |
| Migration 034 | **YES — targets `wtf` DB ONLY** | **NO — never touched by 034** |
| Reconciliation | — | sync canonical `entity_id` into `archie.shared.entities.metadata->'canonical_entity_id'` over the mesh; NEVER written as truth |

**CODE RULE (paste into route docstrings):** all canonical entity/node/edge/chain/dedup/external_id lookups (slug→entity, `relationship_type`, traversal) go to the **`wtf` DB shared schema** — in-process for WTF consumer code, server-to-server over the mesh (`100.64.0.4`) for the hub `cross_watch` blueprint (federate to wtf-DB or proxy to WTF consumer `chain.py`). ONLY follow/alert/signal lookups go to `archie` DB `shared.entities`. **Never point a slug/id/relationship lookup at `archie.shared.entities`** — wrong entity_type domain returns empty/wrong nodes.

**Why:** re-homing would orphan the 343 live FK back-links (`parliament.mps/senators/officers.entity_id`); the richest civic data (`parliament.*`, `legal_watch.ethics_rulings`, `gov_watch.gic_appointments`) is co-resident in the `wtf` DB so resolution = same-DB JOINs; the cross-host write path to the `wtf` DB over the mesh is proven (wtf-ingest writes there today).

**Migration 034 carries a mandatory header comment** (ADR §3.2) stating it targets the `wtf` DB only.

### 2.2 Confidence policy — tiered, conservative, reversible

- **Tier 1 deterministic** (durable external IDs only — see §4): exact match in `shared.entity_external_ids` → auto-merge @ **conf 1.000**, logged, NOT review-queued.
- **Tier 2 fuzzy** (no durable ID — vendors, donors, DPOH, judges, lobbyist persons, journalists): blocked + scored 0–1.
  - score **≥ 0.92** → auto-merge (logged, reversible)
  - **0.75 ≤ score < 0.92** → `shared.merge_review_queue` (human decides)
  - score **< 0.75** → `shared.dedup_pair_decisions` reject (don't re-surface unless inputs change)
- **Hard vetoes → score 0:** different `entity_type`; two conflicting Tier-1 keys.
- Thresholds live in `shared.dedup_config` (tunable without deploy). **Start at 0.92 auto** — a false cross-watch merge in a public accountability product is a credibility incident.
- **Every merge reversible** via `shared.entity_merge_log.snapshot` (JSONB of every moved row + originals).

### 2.3 Public vs gated — free shape, premium depth; mesh vs ingress (OWNER LOCKED)

- **FREE (no-auth, CORS `*`, 60s cache):** chain *shape* (`links_resolved[]`/`links_missing[]`/`coverage_pct`/`has_data` per link), bias scores, connected/gap status, entity hero + stats, news coverage teaser. The civic-good loss-leader.
- **`wtf-premium` gated (at the API, via `require_product_access`):** deep per-link records, full chain depth beyond hop 2, rationale, cross-product evidence bodies. Gate at the API so the proxy can't leak gated data to free users.
- **Routing — the inverse-rule trap:**
  - **Browser-origin** widget/page calls → **public hub ingress** (`platform.kytranempowerment.com` via Beacon). Browser JS on a Citadel product **cannot reach** the mesh `100.64.0.4`. GET-only, cached.
  - **Server-to-server** (standalone → hub, hub → wtf DB) → **mesh `100.64.0.4`**. Never the public hostname (60s CDN cap).

### 2.4 Eliminate duplication with Milestone A/B

- **Do NOT** create a second journalist search endpoint — A's `GET /api/entities/search?type=journalist` already serves it.
- **Do NOT** write a third resolver — extend `_upsert_entity()` / `resolve_byline()`. New cross-watch dedup calls these, never a new normalizer. (I1.)
- **Do NOT** re-create `wtf.article_author_tags` or alter the entity_type CHECK to add content types — 033 set `journalist`; content types are NOT nodes (S1).
- **Refactor** `entities.py` `/accountability` + `/profile` co-mention block to call the shared `traverse_chain` helper — but that helper is a **Wave-3 artifact** (W1), so this refactor (T-COV-1) moves to Wave 3. Until then a Wave-1 one-hop helper covers WTF-local needs.
- **WTF is the Coverage node (Link 7) OWNER** and a CONSUMER of the other links. Its `/coverage` stays WTF-local-canonical; its chain panel PROXIES to the hub.

---

## 3. Canonical Schema + DDL (#3790 → migration 034)

**Home:** hub `wtf` DB, `shared` schema. **Apply:** manual `psql -U archie -d wtf -f migrations/034_shared_entity_graph.sql` (no auto-runner — same pattern as 033). **Owner:** run as `archie` (DB owner) not `wtfuser` — `CREATE EXTENSION` needs owner. Idempotent + additive — EXTENDS 030/033, never recreates.

> **The `entity_type` CHECK and the `chain_link_types` seed below are the ADR-EG-001 corrected versions. The v1 blueprint draft (which added `news_outlet/vendor/case/tender` to the CHECK and mis-seeded `lobbied_by` as link-2 spine) is WRONG and is replaced here.**

```sql
-- ============================================================================
-- Migration 034_shared_entity_graph.sql
-- TARGET: hub `wtf` DB, `shared` schema  (apply: psql -U archie -d wtf -f ...)
--
-- ⚠️ DUAL-SCHEMA WARNING (ADR-EG-001 §3 / must-fix S6):
--   The hub `archie` DB ALSO has a `shared.entities` table (migration 393).
--   That is a SEPARATE signal-bus (entity_type = department/topic/keyword) for
--   the follow/alert feature. THIS migration targets the `wtf` DB ONLY.
--   The canonical accountability graph (person/organization/journalist) lives
--   HERE, in the `wtf` DB. NEVER run this against the `archie` DB.
-- EXTENDS 030/033 (do not recreate entities/mentions/relationships/article_author_tags).
-- ============================================================================

-- 0. Extensions (audit: pg_trgm NOT yet enabled; vector available via pgvector/pgvector:pg16)
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- fuzzy name match (similarity / %)
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;  -- dmetaphone/soundex blocking
CREATE EXTENSION IF NOT EXISTS unaccent;       -- accent-fold names
CREATE EXTENSION IF NOT EXISTS vector;         -- vector type exists; name_embedding DEFERRED (OD-5)

-- 1. EXTEND canonical node: identity stability + provenance + merge audit
ALTER TABLE shared.entities
  ADD COLUMN IF NOT EXISTS created_by_product TEXT,
  ADD COLUMN IF NOT EXISTS first_seen_at      TIMESTAMPTZ DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS normalized_name    TEXT,
  ADD COLUMN IF NOT EXISTS status             TEXT NOT NULL DEFAULT 'active'
                                              CHECK (status IN ('active','merged','suppressed')),
  ADD COLUMN IF NOT EXISTS merged_into        INTEGER REFERENCES shared.entities(id);
  -- name_embedding VECTOR(768) DEFERRED (OD-5). Ship column ONLY if cheap; else omit.
  -- If shipped: ADD COLUMN IF NOT EXISTS name_embedding VECTOR(768);  -- nullable, populate later

-- FROZEN node CHECK (ADR-EG-001 §1.1 / must-fix S1): 3 node types ONLY.
-- news_outlet + vendor are `organization` (use metadata.org_kind to subtype);
-- case/tender/bill/vote/policy are entity_mentions CONTENT, never entity rows.
ALTER TABLE shared.entities DROP CONSTRAINT IF EXISTS entities_entity_type_check;
ALTER TABLE shared.entities ADD CONSTRAINT entities_entity_type_check
  CHECK (entity_type IN ('person','organization','journalist'));

CREATE INDEX IF NOT EXISTS idx_entities_status      ON shared.entities(status);
CREATE INDEX IF NOT EXISTS idx_entities_merged_into ON shared.entities(merged_into);
CREATE INDEX IF NOT EXISTS idx_entities_normname_trgm
  ON shared.entities USING GIN (normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entities_cname_trgm
  ON shared.entities USING GIN (canonical_name gin_trgm_ops);
-- vector index DEFERRED with name_embedding (OD-5).

-- HARD RULE: shared.entities rows are NEVER physically deleted (merge tombstones instead)
CREATE OR REPLACE FUNCTION shared.no_entity_delete() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'shared.entities rows are never deleted (merge sets status=merged)'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_no_entity_delete ON shared.entities;
CREATE TRIGGER trg_no_entity_delete BEFORE DELETE ON shared.entities
  FOR EACH ROW EXECUTE FUNCTION shared.no_entity_delete();

-- resolve any (possibly merged) id to its live canonical id
CREATE OR REPLACE FUNCTION shared.resolve_entity(p_id INT) RETURNS INT AS $$
  WITH RECURSIVE chain AS (
    SELECT id, merged_into FROM shared.entities WHERE id = p_id
    UNION ALL
    SELECT e.id, e.merged_into FROM shared.entities e JOIN chain c ON e.id = c.merged_into
  ) SELECT id FROM chain WHERE merged_into IS NULL LIMIT 1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE VIEW shared.v_entities_resolved AS
  SELECT * FROM shared.entities WHERE status = 'active';

-- 2. TIER-1 deterministic external keys — ONLY durable person/org/journalist ids (ADR §4 / S2,S3).
--    Document/event keys (procurement_reference, scc_citation, oic_pc_number, ethics_report_url)
--    are NOT here — they are entity_mentions content pointers.
CREATE TABLE IF NOT EXISTS shared.entity_external_ids (
  id          SERIAL PRIMARY KEY,
  entity_id   INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
  key_type    TEXT NOT NULL CHECK (key_type IN (
                'openparliament_slug','parl_mp_id','lobbying_comlog_id','wtf_source_slug')),
  key_value   TEXT NOT NULL,
  key_tier    SMALLINT NOT NULL DEFAULT 1,
  source_product TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (key_type, key_value)            -- a strong key maps to exactly ONE entity
);
CREATE INDEX IF NOT EXISTS idx_extids_entity ON shared.entity_external_ids(entity_id);
-- NOTE (S3): lobbying_comlog_id is UNIQUE only as the EVENT pair (comlog_id, mp_id). When a single
-- comlog_id legitimately recurs across MPs, key on the concatenated (comlog_id||':'||mp_id) value.

-- 3. RAW source mentions — every mention from every dataset, source row id preserved
--    (pre/post resolution; the alias/audit table that makes re-resolution + merges safe)
CREATE TABLE IF NOT EXISTS shared.source_mention (
  id              BIGSERIAL PRIMARY KEY,
  product         TEXT NOT NULL,
  content_type    TEXT NOT NULL,
  source_row_id   TEXT NOT NULL,        -- the ACTUAL PK in the originating table
  raw_name        TEXT NOT NULL,
  normalized_name TEXT,
  entity_type_hint TEXT,
  candidate_keys  JSONB NOT NULL DEFAULT '{}',  -- strong keys this row carried, if any
  context         JSONB NOT NULL DEFAULT '{}',  -- postal/riding/party/dept for disambiguation
  resolved_entity_id INTEGER REFERENCES shared.entities(id) ON DELETE SET NULL,
  match_method    TEXT CHECK (match_method IN
                    ('deterministic','fuzzy_auto','pending_review','manual','unmatched')),
  match_confidence NUMERIC(4,3) CHECK (match_confidence BETWEEN 0 AND 1),
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  resolved_at     TIMESTAMPTZ,
  UNIQUE (product, content_type, source_row_id, raw_name)   -- idempotent re-emit
);
CREATE INDEX IF NOT EXISTS idx_srcment_resolved ON shared.source_mention(resolved_entity_id);
CREATE INDEX IF NOT EXISTS idx_srcment_pending  ON shared.source_mention(match_method)
  WHERE resolved_entity_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_srcment_normname ON shared.source_mention
  USING GIN (normalized_name gin_trgm_ops);

-- 4. STAGE-2 blocking keys (avoid O(n^2): dmetaphone(family) | trigram bucket)
CREATE TABLE IF NOT EXISTS shared.entity_blocks (
  entity_id INT NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
  block_key TEXT NOT NULL,
  PRIMARY KEY (entity_id, block_key)
);
CREATE INDEX IF NOT EXISTS idx_blocks_key ON shared.entity_blocks(block_key);

-- 5. dedup config (tunable thresholds, no deploy)
CREATE TABLE IF NOT EXISTS shared.dedup_config (k TEXT PRIMARY KEY, v NUMERIC NOT NULL);
INSERT INTO shared.dedup_config(k,v) VALUES
  ('auto_merge',0.92),('review_lo',0.75),
  ('w_name',0.55),('w_context',0.20),('w_role',0.15),('w_geo',0.10),
  ('trgm_threshold',0.40),('donor_min_aggregate',200)
ON CONFLICT (k) DO NOTHING;

-- 6. human review queue + non-match memory
CREATE TABLE IF NOT EXISTS shared.merge_review_queue (
  id SERIAL PRIMARY KEY,
  entity_a INT NOT NULL REFERENCES shared.entities(id),
  entity_b INT NOT NULL REFERENCES shared.entities(id),
  score NUMERIC(4,3) NOT NULL,
  signals JSONB NOT NULL,                 -- {name:.88,context:.71,role:1,geo:.5}
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','merged','rejected')),
  decided_by TEXT, decided_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (entity_a, entity_b)
);
CREATE TABLE IF NOT EXISTS shared.dedup_pair_decisions (
  entity_a INT, entity_b INT, decision TEXT, score NUMERIC, decided_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (entity_a, entity_b)
);

-- 7. reversible merge audit (JSONB snapshot = undo source of truth)
CREATE TABLE IF NOT EXISTS shared.entity_merge_log (
  id BIGSERIAL PRIMARY KEY,
  winner_id INT NOT NULL, loser_id INT NOT NULL,
  confidence NUMERIC(4,3),
  method TEXT NOT NULL,                    -- deterministic|fuzzy_auto|human|unmerge|manual_relink
  actor TEXT,                              -- 'dedup_job' | 'human:<user>' | adapter name
  snapshot JSONB NOT NULL,                 -- moved mentions/relationships/external_ids + originals
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. adapter plumbing — cursor + registry (consumed by dedup + chain-query)
CREATE TABLE IF NOT EXISTS shared.adapter_sync_state (
  product TEXT NOT NULL, adapter TEXT NOT NULL,
  last_synced_id TEXT, last_run_at TIMESTAMPTZ, last_status TEXT,
  stats JSONB DEFAULT '{}',
  PRIMARY KEY (product, adapter)
);
CREATE TABLE IF NOT EXISTS shared.adapter_registry (
  product TEXT NOT NULL, adapter TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('hub_resident','remote_push','none')),
  entity_types TEXT[] NOT NULL DEFAULT '{}',
  enabled BOOLEAN NOT NULL DEFAULT TRUE, notes TEXT,
  PRIMARY KEY (product, adapter)
);
INSERT INTO shared.adapter_registry (product,adapter,mode,entity_types,notes) VALUES
 ('wtf','mp','hub_resident','{person}','existing entity_mentions_sync (SHIPPED)'),
 ('wtf','author','hub_resident','{journalist}','Milestone B forward-only (SHIPPED)'),
 ('gov-watch','gic','hub_resident','{person,organization}','pc_number=appointment CONTENT; GIC->MP fuzzy (S7)'),
 ('gov-watch','vendor','remote_push','{organization}','name_only — NO business number (fuzzy gap)'),
 ('parliament','donor','hub_resident','{person}','EC contributions; donor>=$200 + slug-match (owner)'),
 ('parliament','lobbyist','hub_resident','{person,organization}','comlog_id=event (S3)'),
 ('civic-watch','lobby','remote_push','{person,organization}','registration_num=registration, person fuzzy (S3)'),
 ('civic-watch','bill','remote_push','{person}','sponsor name_only (fuzzy gap)'),
 ('legal-watch','scc','remote_push','{person}','majority_author person; case=content via scc_citation (S1)'),
 ('legal-watch','ethics','remote_push','{person}','key report_name (S4); subject->MP by mp_slug hub-side'),
 ('market-watch','none','none','{}','ticker/chrome-only — NO civic entities (Link 6 placeholder)')
ON CONFLICT (product,adapter) DO UPDATE SET mode=EXCLUDED.mode,
  entity_types=EXCLUDED.entity_types, notes=EXCLUDED.notes;

-- 9. chain link ordering — FROZEN per ADR-EG-001 §2.5 (replaces v1 blueprint draft seed).
--    is_spine column REQUIRED. All 8 positions seeded incl. MP node (2) + Public node (8).
--    has_data=FALSE on Link 4 (enacted_as) + Link 6 (market_reaction_to). lobbied_by = ENRICHMENT.
CREATE TABLE IF NOT EXISTS shared.chain_link_types (
  relationship_type TEXT PRIMARY KEY,
  link_position SMALLINT NOT NULL,   -- 1..8 (2 + 8 are NODE positions)
  label TEXT NOT NULL,
  has_data BOOLEAN NOT NULL DEFAULT TRUE,
  is_spine BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO shared.chain_link_types(relationship_type, link_position, label, has_data, is_spine) VALUES
  ('donated_to',          1, 'Money → MP',        TRUE,  TRUE),
  ('__mp_node__',         2, 'MP (node)',          TRUE,  TRUE),
  ('cast_vote',           3, 'MP → Vote',          TRUE,  TRUE),
  ('enacted_as',          4, 'Vote → Policy',      FALSE, TRUE),   -- no ingest pipeline
  ('awarded_to',          5, 'Policy → Contract',  TRUE,  TRUE),
  ('contracts_with',      5, 'Contract',           TRUE,  TRUE),
  ('market_reaction_to',  6, 'Contract → Market',  FALSE, TRUE),   -- no securities pipeline
  ('covered_by',          7, '→ Coverage',         TRUE,  TRUE),   -- derived at query time
  ('__public_node__',     8, 'Public (node)',      TRUE,  TRUE),
  -- enrichment edges (NOT spine; link_position = attachment hint only):
  ('lobbied_by',          2, 'Lobbying (enrichment)',    TRUE, FALSE),
  ('appointed_to',        5, 'Appointment (enrichment)', TRUE, FALSE),
  ('employs',             2, 'Employs (enrichment)',     TRUE, FALSE)
ON CONFLICT (relationship_type) DO UPDATE SET
  link_position = EXCLUDED.link_position, label = EXCLUDED.label,
  has_data = EXCLUDED.has_data, is_spine = EXCLUDED.is_spine;

-- 10. traversal indexes (directional recursive-CTE walks)
CREATE INDEX IF NOT EXISTS idx_rel_from_type ON shared.entity_relationships(from_entity_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_rel_to_type   ON shared.entity_relationships(to_entity_id,   relationship_type);

-- 11. grants (mirror 033 grant block if the ingest service connects as wtfuser)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='wtfuser') THEN
    GRANT SELECT,INSERT,UPDATE,DELETE ON
      shared.entity_external_ids, shared.source_mention, shared.entity_blocks,
      shared.dedup_config, shared.merge_review_queue, shared.dedup_pair_decisions,
      shared.entity_merge_log, shared.adapter_sync_state, shared.adapter_registry,
      shared.chain_link_types TO wtfuser;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA shared TO wtfuser;
  END IF;
END $$;
```

**`shared.entity_mentions` (030) stays AS-IS** — the resolved entity↔content ledger AND the home for all CONTENT pointers (tender/case/bill/policy/appointment/ethics/article via `content_type`+`content_id`, S1/S2). `shared.source_mention` (new) is the RAW pre-resolution input + alias/audit trail.

---

## 4. Identity Resolution Keys (FROZEN, ADR §4 — only keys a dataset ACTUALLY has)

**We never invent a key.** Per S1/S2, document/event keys are NOT person/org keys — they live in `entity_mentions.content_id`.

### Tier 1 — DETERMINISTIC (exact match → auto-merge @ conf 1.0)

| key_type | Source | Identifies (node) |
|---|---|---|
| `openparliament_slug` | `parliament.mps.slug` | MP (person) |
| `parl_mp_id` | `parliament.mps.parl_mp_id` | MP (person) |
| `lobbying_comlog_id` | `parliament.lobbyist_contacts.comlog_id` | lobbyist communication **EVENT** (unique as `(comlog_id, mp_id)`, S3) |
| `wtf_source_slug` | `wtf.sources.slug` + domain | news outlet (organization) |

> Business number / CRA / BN / GST: **none exist in any dataset** — durable org identity is a real gap; org match is Tier-2 fuzzy-only.

### Tier 1 demoted → CONTENT pointers (must-fix S2 — NOT person/org keys)

| Former "key" | Identifies a DOCUMENT/EVENT → `entity_mentions` | content_type | content_id | Person behind it (Tier-2 fuzzy) |
|---|---|---|---|---|
| `procurement_reference` | tender/award doc | `procurement` | `reference_number:amendment:winner` | vendor org — name-only, no BN |
| `scc_citation` | case doc | `legal_case` | `2024 SCC 1` | majority-author judge — name-only |
| `oic_pc_number` | appointment order doc | `appointment` | `2026-0436` | appointee — name-only, no FK to MP (S7) |
| `ethics_report_url`/`report_name` | ruling doc | `ethics_ruling` | **`report_name`** (S4 — `report_url` NOT unique) | ethics subject — name-only, cross-linked to MP by `mp_slug` |

### Tier 2 — FUZZY (no durable ID → propose/queue, never silent cross-product auto-merge)

| Cohort | Best available key | Honest gap |
|---|---|---|
| Elections Canada donors | `normalized(contributor_name)` + `contributor_postal` | NO durable donor ID. Materialize **only at ≥$200 aggregate AND slug-match-to-existing first pass** (owner) |
| Vendors/suppliers | `normalized(vendor_name)` + `vendor_postal_code` | NO CRA/BN/GST anywhere — fuzzy-only |
| Civic DPOH / bill sponsor / SCC judge / lobbyist person | normalized name only | free text, no FK |
| Lobbyist registration (civic) | `registration_num` (registration, nullable, non-unique alone) | **NON-JOINABLE** cross-DB to parliament `comlog_id` — no ETL bridge (S3) |
| GIC appointee → MP | `appointee_name` (optional free text) | **NO key** — model edge as Tier-2 fuzzy/low-confidence or leave unresolved (S7) |
| Journalists | normalized-name slug + aliases | no ISNI / wire ID |

**Algorithm** (`shared.score_pair(a,b)`, §5): Tier-1 exact → conf 1.0 method `deterministic`. Else blocked trigram + context (postal/riding/party/role) → ≥0.92 `fuzzy_auto`, 0.75–0.92 `pending_review`, <0.75 reject. **Never** fuzzy-merge two entities each carrying a conflicting Tier-1 key.

---

## 5. Dedup Engine (#3792)

Runs **co-located with the `wtf` DB** (must-fix I3) — no streaming candidate pairs across the mesh. Extends `_upsert_entity()`/`resolve_byline()` — **no third resolver**.

- **Stage 1 — DETERMINISTIC MERGE (ships in WAVE 1 WITH the adapters, must-fix W2):** durable external-key collision in `entity_external_ids` → `shared.merge_entities(...,'deterministic')`. Inline in the ingest path. Cheap + safe; the only merge logic adapters need to function in Wave 1.
- **Stage 2 — FUZZY (Wave 2):** nightly fleet job `dedup_candidate_scan`: for each changed active entity → block (dmetaphone/trigram) → `score_pair` → auto-merge ≥0.92 / queue 0.75–0.92 / reject <0.75. Embedding generation (only if `name_embedding` is later enabled, OD-5) dispatches via **DHQ** (`capability='embedding'`), never direct Ollama.
- **Reversible merge** (`shared.merge_entities` / `shared.unmerge_entity`): MOVE child rows (mentions/relationships/external_ids) to winner with `ON CONFLICT DO NOTHING`, fold loser aliases into winner, tombstone loser (`status='merged'`), snapshot everything to `entity_merge_log`. Unmerge replays the snapshot in reverse.
- **Confidence model:** `0.55*name_sim + 0.20*context_sim + 0.15*role_compat + 0.10*geo`. `name_sim = max(trgm similarity, dmetaphone==1.0)`; hard vetoes → 0.
- **Review surface (Wave 2, can land with Wave-4 frontend):** admin-gated LCARS `bm-` modal. `GET /api/dedup/review?status=pending`, `POST .../<pair>/merge|reject`, `POST /api/dedup/entities/<id>/unmerge`, `GET .../audit`. Every row shows the WHY (name 0.88 / context 0.71 / geo 0.5). Mid-confidence NEVER auto-applies.
- **Relationship-move dedup gotcha:** `entity_relationships` has no per-`entity_id` UNIQUE — `merge_entities` MUST de-dupe relationships explicitly before ship or a naive move creates duplicate edges.
- **Donor cohort (OWNER LOCKED):** 4.1M EC rows, no ID. Donor entities materialize ONLY at **≥$200 aggregate AND slug-match-to-existing-entity first pass** — a SEPARATE stricter pass, NOT the general nightly scan, to bound review-queue volume + false-merge risk. Threshold tunable via `dedup_config.donor_min_aggregate`.

---

## 6. Adapters (#3791)

Two classes (no LLM in any of the 5 structured adapters — every key is a column; LLM fuzzy/byline is a deferred follow-on routed through DHQ). **All adapters import the FROZEN edge strings from ADR-EG-001 §2.4 verbatim — no repo hand-types a relationship_type.**

### Class A — HUB-RESIDENT (scheduled jobs in wtf-ingest, same-DB writes, no HTTP)
Read tables already in the `wtf` DB; call `_upsert_entity()` + mention/relationship ON-CONFLICT helpers directly.
- **WTF mp + author** — ALREADY SHIPPED (`entity_mentions_sync.py`, `author_resolver.py`). Do not rebuild.
- **gov-watch gic** — `gov_watch.gic_appointments`. The OIC order = `entity_mentions` content (`oic_pc_number`), NOT a node (S1). Appointee = `person`; body = `organization`; edge `appointed_to` (enrichment). GIC appointee who is also an MP **collapses onto the existing MP person row** via slug where the slug is known; where only free-text `appointee_name` exists, the appointee→MP link is **Tier-2 fuzzy/unresolved** (S7).
- **parliament donor + lobbyist** — extend `entity_graph.py`. Donor `-donated_to->` MP via `electoral_district = mps.riding_name` text join (mention-only + `metadata.ambiguous=true` if >1 MP). Donor gated by owner scope (≥$200 + slug-match). Lobbyist event keyed by `comlog_id` (S3); edges `lobbied_by`, `employs` (enrichment).

### Class B — REMOTE-PUSH (scheduled jobs in each Citadel standalone → POST batch over mesh to the WTF ingest endpoint)
- **gov-watch vendor** (gov standalone Postgres): `vendor_name` → organization, `metadata.identity='name_only'` (no BN — gap). Award = `entity_mentions` content (`procurement_reference`). Edge `awarded_to` dept-org → vendor-org; `contracts_with` for the durable relationship.
- **civic-watch lobby + bill + civic_event** (SQLite): `registration_num` = registration (S3, NON-JOINABLE to parliament `comlog_id`); lobbyist person fuzzy; `dpoh_name`/`sponsor` name-only.
- **legal-watch scc + ethics** (SQLite): `majority_author` (judge, name-only) `person`; case = `entity_mentions` content (`scc_citation`); ethics subject keyed on `report_name` (S4); hub-side reconciliation links subject→MP by `mp_slug`.
- **market-watch** — NO adapter. `none` stub. Honest (no civic entities — Link 6 placeholder).

### Idempotency / scheduling
- Entities dedup by `slug` (the cross-watch merge mechanism). Mentions `ON CONFLICT DO NOTHING`. Relationships `ON CONFLICT DO UPDATE`. Per-adapter cursor in `shared.adapter_sync_state.last_synced_id`.
- All `CronTrigger(timezone='America/Toronto')`. Hub-resident: gic 03:30, parliament 03:45. Remote-push: gov-vendor 03:15, civic 03:20, legal 03:25. Batched ≤500 entities/POST.
- **module-work-pattern compliance:** pure structured = scheduled job (explicit carve-out). Any fuzzy/byline LLM step → `delegate_task(capability='analyze'|'classify', delegation_source='automation')`, night-capped — NEVER inline.

### Failure handling
- Auth: missing key → 503; wrong key → 401 (gov-watch `set-tier` pattern).
- Per-entity savepoint — one bad row skipped + counted, rest commit. Abort+alert if >50% of a batch fails. Cursor advances only past ACKed rows.
- Mesh unreachable/5xx/timeout: log, DON'T advance cursor, retry next run. At-least-once + idempotent ON-CONFLICT = effectively exactly-once. Null name → drop pre-POST.

---

## 7. Query API — 8-Link Accountability Chain (#3793)

New `chain.py` blueprint in `what-the-fact/consumer/`, registered in `app.py` alongside `entities_bp`. Queries the `wtf` DB graph in-process; reaches the hub signal bus only via `cross_watch.py`. **One traversal engine** backs both public and internal surfaces. Filters `relationship_type` strictly against the FROZEN strings (ADR §2.4).

### 7.1 Core engine — recursive CTE on `shared.entity_relationships`
`traverse_chain(start_id, max_hops, edge_types[])` with depth cap (default 4, hard max 6), visited-set cycle guard, keyset pagination. Default `edge_types` = the **7 spine** strings; enrichment edges (`lobbied_by`/`appointed_to`/`employs`) included only when explicitly requested. **Coverage node (Link 7) materialized at query time** from `entity_mentions JOIN wtf.articles JOIN wtf.sources` (strict `product='wtf' AND content_type='article'`) — NOT stored as edges. (Indexes in migration 034 §10.)

> **Wave note (W1):** `traverse_chain` is a **Wave-3** artifact. No Wave-1 task may call it. Wave-1 WTF-local needs use a simple one-hop helper; the `entities.py` refactor to call `traverse_chain` is **T-COV-1, moved to Wave 3** (see §10).

### 7.2 Edge vocabulary — FROZEN (ADR-EG-001 §2; the ADR phase is DONE)
The edge-vocabulary ADR is **locked and DONE** (W3 — ahead of Wave 0). Spine: `donated_to`(1), `cast_vote`(3), `enacted_as`(4, no-data), `awarded_to`(5), `contracts_with`(5), `market_reaction_to`(6, no-data), `covered_by`(7, derived). Enrichment: `lobbied_by`, `appointed_to`, `employs`. Every repo imports §2.4 verbatim; string drift across 5 repos silently breaks traversal — which is exactly what the ADR + a CI string-diff check prevent.

### 7.3 API contracts

**PUBLIC** (no-auth · CORS `*` · `Cache-Control: public, max-age=60` · keyset pagination · OWNER: free shape):
```
GET /api/public/chain/entity/<slug>          → 8-link chain anchored on one entity (max_hops=4)
GET /api/public/chain/path?from=&to=&max_hops=4   → shortest typed path between two entities
GET /api/public/chain/article/<article_id>   → WTF-as-Coverage-CONSUMER: each tagged entity's upstream chain
GET /api/public/chain/links                  → static catalog from shared.chain_link_types (link, has_data, is_spine)
```
Every response carries `coverage_pct`, `links_resolved[]`, `links_missing[]`; **gap links (Link 4 `enacted_as`, Link 6 `market_reaction_to`) return `{"status":"no_data","reason":"no ingest pipeline"}`** and the UI renders them permanently dim. The public surface exposes SHAPE + connected/gap + bias only — NO deep per-link records.

**INTERNAL** (`X-Internal-Key` · no cache · full depth · OWNER: gated depth lives here + behind `require_product_access`):
```
GET  /api/internal/chain/entity/<slug>?max_hops=6&include_provisional=true
GET  /api/internal/chain/path?from=&to=&edge_types=donated_to,cast_vote,awarded_to
GET  /api/internal/chain/resolve?name=<freetext>&type=person|organization   → pg_trgm fuzzy resolve
POST /api/internal/chain/edges    → adapter edge write-back (UPSERT on the 030 UNIQUE; idempotent)
```

**Hub endpoints (for the cross_watch blueprint + cross-product consumers):**
```
GET /api/cross-watch/entity/<slug>/summary  → {by_product:{gov,civic,legal,market,wtf}, top_relationships} (CORS-open, 60s)
GET /api/cross-watch/entity/<slug>/chain    → federates wtf-DB graph; mesh-only, Bearer service token
```

### 7.4 Federation note
The hub `cross_watch` `/summary` + `/chain` endpoints MUST read the **`wtf` DB graph**, not the `archie` signal-bus `shared.entities` (S6). Implementation (OD-7): **proxy to the WTF consumer `chain.py`** over the mesh (keeps the graph behind one service), OR the hub holds a read connection to the `wtf` DB. Until reconciled, `/summary` returns empty rather than read the wrong table.

### 7.5 Caching / pagination
Public: keyset cursor (`base64(last_hop:last_to_entity_id)`) + in-process 60s LRU keyed on `(slug,max_hops,edges_version)`; adapter `POST /edges` bumps `edges_version` to purge. Beacon/Caddy front-door caches the 60s response. Internal: `no-store`. Public routes **fail soft** (cached/empty, never 500 a product page).

---

## 8. Frontend Surfaces (NEW work — none of this exists)

Three reader surfaces + one shared interconnect primitive. All in the WTF consumer (extend `base.html`, `mp.html`, reuse `wtf-*` classes). LCARS teal, dark cards, Orbitron/IBM Plex Mono. Gating: `require_product_access('wtf-premium')` on deep per-link records ONLY; shape/bias/gap-status is public.

### 8.1 Entity Profile page — `entity.html` (`GET /entity/<id>` + `/entity/slug/<slug>`)
Unified person/org/journalist accountability view aggregating all 5 datasets onto one page. **WTF-served page + hub-proxied chain data** (hybrid: WTF-native sections hit `entities.py`; cross-product sections hit `cross_watch.py` → hub). Sections: Hero (role-resolution badge row per dataset, `coverage_pct` honesty marker, Follow), Stats strip, the 8-link chain rail, per-dataset evidence (Money / Parliament / Contracts / Court & Regulatory / Market / Coverage / Connections), provenance footer with **"name-matched, unverified"** flags on fuzzy org links. **Other 4 products deep-link here** — one canonical page, five entry points.

### 8.2 Chain Explorer — `chain.html` (`GET /chain`, `/chain/<entity_slug>`)
Public reader page that walks the full chain for a chosen entity/issue. Entry = typeahead over `/api/entities/search`. Two view modes (localStorage-persisted): **Stepped Chain** (default, mobile-first — 8 LCARS link cards w/ elbow connectors, tap-to-expand records) and **Graph Viz** (≥1024 only, hand-rolled inline SVG like `cluster.html`, NO new CDN dep). Each link card: per-link color + owning product badge (deep-links OUT to gov/civic/legal/market/wtf) + node deep-link IN. **Gap links (Link 4 Policy, Link 6 Market) render dim "not yet connected"** with a `/transparency` 'why' tooltip; the `is_spine=FALSE` enrichment edges render visually distinct from spine links. Server-renders bootstrap JSON for first paint + SEO + no-JS fallback. Shape/bias/gap free; deep records gated.

### 8.3 WTF Coverage Node — consumer of profile/chain, NOT a second store
`entities.py` `/search`, `/coverage`, `/profile`, `/accountability` stay **WTF-local-canonical**. The chain panel **proxies** to the hub via `cross_watch.py`. Add `entity_search.html` (reader entry point) + a "People in this story" rail on `article.html`. **Ship coverage/profile/search live; feature-flag the chain panel OFF until the hub `/chain` endpoint exists — do NOT stub it with a WTF-local re-walk** (that re-creates the duplication this project removes).

### 8.4 Product-Interconnect primitive — `_graph_interconnect.html` + `interconnect.css/js` (~6KB, dependency-free)
ONE shared partial shipped into all 5 products + homepage:
1. **Entity badge** `kg-entity` — wraps any person/org name; ⌬ chip deep-links to `what-the-fact.com/entity/<slug>`; hover lazy-fetches `GET /api/cross-watch/entity/<slug>/summary` (per-product mention counts tooltip = visible CONSUME). **XSS:** names via `textContent`, never `innerHTML`.
2. **Shared footer row** `kg-footer-sites` — generalize WTF's `wtf-footer-sites` family row + C.R.E.E.D. Certified badge (`<img>` from `creed.kytranempowerment.com/api/v1/badge/overall`) onto every product.
3. **Alert bell** — port WTF's `cw-badge` to shared nav.
- **Browser calls hit the PUBLIC ingress** (`platform.kytranempowerment.com`), not the mesh.
- Per-product change scaled to the asymmetry table (§9): Gov Watch (full — wrap vendor name + "Across the Watch Series" panel); WTF (canonical — wrap names, host the chain strip); Civic/Legal (thin — footer + bell + ONE "Connected to the Accountability Graph" teaser); Market (chrome-only — footer + bell, count honestly 0); homepage (narrate-only static, full-zip deploy — "The Accountability Graph" hero with 5-node diagram + 8-link through-line + live CREED badge).

---

## 9. Interconnect Map — EXPLICIT ASYMMETRY (must-fix W4 / ADR §5.1)

The interconnect is NOT symmetric. Each product's feed depth AND consume depth are stated explicitly so no one over-builds Market or under-builds Gov.

| Product | FEED | CONSUME | Frontend scope |
|---|---|---|---|
| **WTF** | **full feed** — mp + author hub-resident adapters (SHIPPED); single writer; owns Coverage node (Link 7) | **deep consume** | canonical — `entity.html`/`chain.html`/coverage; hosts chain strip; chain panel proxies hub |
| **Gov Watch** | **full feed** — gic (hub-resident) + vendor (remote-push); writes mentions + `awarded_to`/`contracts_with`/`appointed_to` | **deep consume** | "Across the Watch Series" panel via `/entity/<slug>/summary`; deep-link to `/entity/<id>` |
| **Civic Watch** | **feed** — lobby/bill/civic_event remote-push (`registration_num`) | **shallow consume** | footer + bell + ONE teaser; existing `/api/cross-watch/civic-events` panel |
| **Legal Watch** | **feed** — scc/ethics remote-push (`report_name`, `mp_slug` cross-link) | **shallow consume** | footer + bell + ONE teaser; existing `/legal-rulings` panel |
| **Market Watch** | **NONE — chrome-only** (ticker-only; no securities entity; Link 6 placeholder) | footer + bell only | count honestly **0**; roadmap-framed |
| **Homepage** (static) | **narrate-only** — does not feed | narrate-only | "The Accountability Graph" section + 5-node diagram + 8-link through-line + live CREED badge |

**Transport invariants:** standalone→hub + hub→wtf-DB = mesh `100.64.0.4`; browser→hub = public ingress (Beacon). All cross-host writes idempotent. `INTERNAL_API_KEY`/`X-Internal-Key` for adapter ingest; `CROSS_WATCH_SERVICE_TOKEN` Bearer for the consumer proxy (never forwarded to browser).

**Compose env contract (must-fix I2):** Civic AND Market composes have **no `env_file:`** — `ENTITY_INGEST_URL` + `INTERNAL_API_KEY` (+ existing `AC_API_URL`) MUST be in the explicit `environment:` block of each, or the vars are silently absent and the adapter 503/401s. **Verify the RUNTIME env with `docker inspect <container>`, NOT by reading `.env`** (the 2026-06-11 market outage trap). Default mesh: `ENTITY_INGEST_URL=http://100.64.0.4:.../api/internal/entity-graph/ingest` resolves to the WTF consumer ingest over the mesh.

---

## 10. Dependency Waves + Task Mapping (CORRECTED — W1/W2/W3)

Strict ordering: **ADR (DONE) → schema → adapters+Stage-1-merge → Stage-2-dedup+review-UI → chain-query (incl. T-COV-1 refactor) → frontend**.

### Wave −1 — EDGE-VOCABULARY ADR — ✅ DONE (must-fix W3)
**ADR-EG-001** (`2026-06-14-entity-graph-edge-vocabulary-adr.md`) — FROZEN. Node types (3) + edge strings (7 spine + 3 enrichment) + `chain_link_types` seed + dual-schema boundary, locked BEFORE Wave 0 and BEFORE any adapter emits a string. **No remaining work — this gate is closed.**

### Wave 0 — SCHEMA (foundation, blocks everything)
**#3790.** Migration 034 (external-key index limited to durable person/org/journalist keys; source-mention; dedup/merge tables; blocking; config incl. `donor_min_aggregate`; registry; **chain_link_types seeded per ADR §2.5 with `is_spine`, both NODE positions, gaps `has_data=FALSE`**; pg_trgm/fuzzystrmatch/unaccent; traversal indexes; mandatory dual-schema header comment). Apply manually to hub `wtf` DB. Confirm pgvector live; **`name_embedding` DEFERRED (OD-5)** — ship nullable only if cheap, else omit. Reconcile `archie.shared.entities` as labelled downstream signal bus (no migration that breaks the live follow system).
- *Depends on:* Wave −1 ADR (locked). Nothing else (030/033 already live).

### Wave 1 — ADAPTERS + STAGE-1 DETERMINISTIC MERGE (parallelizable)  (must-fix W2)
**#3791** (per-dataset adapters) + **NEW T-ING-1** (hub ingest endpoint `POST /api/internal/entity-graph/ingest` INSIDE the WTF consumer app, single-writer resolver reusing `_upsert_entity`, I1) + **NEW T-DEDUP-STAGE1** (the deterministic external-key merge that ships WITH the adapters — `merge_entities(...,'deterministic')` inline in the ingest path; this is the slice of #3792 the adapters need to function).
Adapters split into parallel build tracks (all import frozen edge strings from ADR §2.4):
- T-ADAPT-GOV (gic hub-resident + vendor remote-push)
- T-ADAPT-PARL (donor [≥$200 + slug-match] + lobbyist hub-resident)
- T-ADAPT-CIVIC (lobby/bill/civic_event remote-push)
- T-ADAPT-LEGAL (scc/ethics remote-push, key on `report_name`)
- T-ADAPT-MARKET (none-stub registration)
- **NEW T-INFRA-COMPOSE** — add `ENTITY_INGEST_URL` + `INTERNAL_API_KEY` to the `environment:` block of civic + market composes; verify via `docker inspect` (I2).

**Parallel reconcile track (#4079 follow-on, no dep on adapters):**
- **NEW T-B4** — LLM byline backfill (the deferred #4079 piece): scheduled fleet job via DHQ, night-capped, idempotent (~5,687 body-bearing unattributed articles).
- *Depends on:* Wave 0 (schema). T-COV-1 is NOT here (moved to Wave 3, W1).

### Wave 2 — STAGE-2 FUZZY DEDUP (must-fix W2)
**#3792** (Stage-2 nightly `dedup_candidate_scan` + reversible merge/unmerge + review queue + admin review UI + tunable `dedup_config`). Donor cohort = separate stricter pass (≥$200 + slug-match). Runs co-located with the wtf DB (I3).
- *Depends on:* Wave 1 (adapters must write `entity_external_ids` + mentions so there's something to fuzzy-dedup; Stage-1 deterministic merge already live).

### Wave 3 — CHAIN-QUERY API (+ the T-COV-1 refactor)
**#3793** + **NEW T-CHAIN-1** (`chain.py` blueprint, `traverse_chain` engine, public + internal contracts, `chain_link_types` ordering+`is_spine` consumption, frozen edge filter) + **NEW T-HUB-CHAIN** (hub `cross_watch` `/entity/<slug>/summary` + `/chain` federating the wtf-DB graph, OD-7) + **NEW T-COV-1** (refactor `entities.py` `/accountability`+`/profile` co-mention to call the shared `traverse_chain` helper — **moved here from Wave 1 because it consumes the Wave-3 traverse_chain artifact**, W1).
- *Depends on:* Wave 2 (cross-product dedup so chains don't fragment) + Wave 1 edges. Ships for the 6/8 connected links; Policy (Link 4) + Market (Link 6) degrade to `status:no_data`.

### Wave 4 — FRONTEND (all NEW tasks)
- **NEW T-FE-PROFILE** — `entity.html` cross-watch entity profile page (§8.1)
- **NEW T-FE-CHAIN** — `chain.html` chain explorer (stepped + graph viz), honest gap-link rendering (§8.2)
- **NEW T-FE-COVNODE** — `entity_search.html` + `article.html` "People in this story" rail; wire WTF coverage-node consumer panels (§8.3)
- **NEW T-FE-INTERCONNECT** — `_graph_interconnect.html` shared primitive (entity badge + footer row + alert bell) into all 5 products + homepage, scaled to the §9 asymmetry (§8.4)
- **NEW T-FE-DEDUP-UI** — admin dedup review/unmerge LCARS surface (may also land in Wave 2)
- *Depends on:* Wave 3 (chain API) for chain panels; Wave 1 (`/summary`) for badges/panels. T-FE-INTERCONNECT P1 chrome (footer/bell/CREED badge) has NO data dep — can ship anytime.

### Structured-output wave plan
- **Wave −1 (ADR):** ADR-EG-001 → DONE (locked, no task)
- **Wave 0 (schema):** #3790 → depends_on: ADR
- **Wave 1 (adapters + Stage-1 merge + ingest + compose, parallel):** #3791, T-ING-1, T-DEDUP-STAGE1, T-INFRA-COMPOSE, T-B4 → depends_on: Wave 0
- **Wave 2 (Stage-2 dedup):** #3792 → depends_on: Wave 1
- **Wave 3 (chain-query + T-COV-1 refactor):** #3793, T-CHAIN-1, T-HUB-CHAIN, T-COV-1 → depends_on: Wave 2 + Wave 1
- **Wave 4 (frontend):** T-FE-PROFILE, T-FE-CHAIN, T-FE-COVNODE, T-FE-INTERCONNECT, T-FE-DEDUP-UI → depends_on: Wave 3

---

## 11. #4079 Journalist Pipeline — CLOSE AS SHIPPED, B4 split off

**Verdict: B1–B3 SHIPPED; B4 split off as T-B4.** Evidence (grounded read 2026-06-14):
- `what-the-fact/shared/author_resolver.py` → `resolve_byline()`, `normalize_name()` present.
- Forward RSS byline capture wired; `wtf.article_author_tags` created (migration 033) + populated forward.
- `consumer/entities.py` journalist branch in `/search` (`type=journalist`) + gated `/profile` (`@require_product_access('wtf-premium')`) present.
- B4 (LLM backfill of ~5,687 body-bearing articles) = deliberately-deferred follow-on.

**Action:**
1. **Close task #4079** as shipped (note: "B1–B3 shipped PRs #1636/#1657; B4 byline backfill split off to T-B4") — its DB status is stale `pending`.
2. **Create NEW T-B4** in Wave 1 for the deferred backfill (DHQ-dispatched fleet job).

---

## 12. Owner Decisions — STATUS (4 locked 2026-06-14)

| # | Decision | Status |
|---|---|---|
| **OD-1** | Graph DB location = hub `wtf` DB `shared` schema | **LOCKED** (ADR §3). `archie.shared.*` = signal bus only. |
| **OD-2** | Auto-merge confidence 0.92 / review floor 0.75 | Confirmed conservative; tune `dedup_config` against a labelled sample before raising. |
| **OD-3** | Public vs gated chain | **LOCKED (owner):** shape + bias + connected/gap status FREE; deep per-link records + rationale `wtf-premium`. |
| **OD-4** | Sync cadence — nightly 03:15–03:45 ET + nightly dedup | Confirmed off-peak; donor cohort on its own stricter schedule. |
| **OD-5** | `name_embedding` VECTOR(768) now or defer | **DEFER.** trgm + context covers Tier-2; ship 034 with column nullable only if cheap, else omit. |
| **OD-6** | EC donor materialization | **LOCKED (owner):** materialize only at **≥$200 aggregate AND slug-match-to-existing first pass**. |
| **OD-7** | Hub→wtf-DB federation for `/summary`+`/chain` | Recommend **proxy to WTF `chain.py`** over the mesh (graph behind one service). Final infra call at Wave-3 build. |
| **OD-8** | Human-review queue ownership | WTF consumer admin sub-tab (LCARS `bm-` modal); needed before `fuzzy_auto` goes live (Wave 2). |
| **OD-9** | Edge-vocabulary ADR | **DONE / LOCKED** (ADR-EG-001 frozen ahead of Wave 0). |
| **OD-10** | #4079 closure | **LOCKED (owner):** close as shipped, create T-B4. |

---

## 13. Top Risks

1. **Dual `shared.entities` schemas** (wtf-DB person/org/journalist vs archie-DB department/topic/keyword). Wrong-table query = empty/wrong nodes. *Mitigation:* canonical = wtf DB only (ADR §3); archie = labelled signal bus; migration 034 header comment + route docstrings; chain proxy ALWAYS over HTTP to the hub; profiles ALWAYS read wtf-DB.
2. **False cross-watch merge** (no business number for vendors/donors; common names). *Mitigation:* conservative 0.92 auto, hard vetoes on type + conflicting Tier-1 key, full reversibility via `entity_merge_log`, donor cohort handled separately (≥$200 + slug-match), "name-matched, unverified" UI flags.
3. **Fabricated chain (Policy Link 4 / Market Link 6)** — no ingest pipeline. *Mitigation:* `chain_link_types.has_data=FALSE` + `status:no_data` enum + `links_missing[]` + permanently-dim UI with `/transparency` link. NEVER render an empty link as populated.
4. **Mesh-vs-public routing inversion** — browser JS on Citadel can't reach mesh `100.64.0.4`; server-to-server can't use the public hostname (60s CDN cap). *Mitigation:* browser→public ingress, server→mesh, codified per surface.
5. **EC donor row explosion** (4.1M, no ID). *Mitigation:* ≥$200 aggregate + slug-match gate before enabling the donor adapter; separate stricter pass; `dedup_config.donor_min_aggregate`.
6. **Cross-host write non-transactionality** — Citadel POSTs can't be transactional with the hub. *Mitigation:* idempotent `UNIQUE(product,content_type,source_row_id,raw_name)` + cursor-only-advances-on-ACK = effectively exactly-once; single-writer ingest endpoint (I1).
7. **Consumer-contract drift** — chain UI depends on the unbuilt #3793. *Mitigation:* ship coverage/profile/search live, feature-flag the chain panel OFF until the hub endpoint exists; never stub with a WTF-local re-walk.
8. **Compose env-contract trap** (civic/market have no `env_file:`). *Mitigation:* explicit `environment:` block; verify with `docker inspect` runtime env (I2, T-INFRA-COMPOSE).
9. **pgvector/pg_trgm CREATE EXTENSION needs DB owner** — run 034 as `archie`, not `wtfuser`.
10. **Edge-string drift across 5 repos** — a single `"awarded"` vs `"awarded_to"` silently breaks traversal. *Mitigation:* import the frozen §2.4 list verbatim in every repo; optional CI check diffing emitted strings against `chain_link_types`; node CHECK rejects any PR adding content types.
11. **Wave inversion** — a Wave-1 task calling the Wave-3 `traverse_chain` (the v1 T-COV-1 placement bug). *Mitigation:* T-COV-1 moved to Wave 3; Wave-1 WTF-local needs use a one-hop helper.

---

*Blueprint v2 complete. ADR-EG-001 + the 4 owner decisions are LOCKED. Author-only this wave — next step is owner sign-off, then build Wave 0 (#3790 migration 034). No git/migration/deploy performed.*
