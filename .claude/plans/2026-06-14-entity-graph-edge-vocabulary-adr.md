# ADR — Shared Entity Graph: Canonical NODE + EDGE Vocabulary (FROZEN)

**ADR ID:** ADR-EG-001 (Edge Vocabulary)
**Project:** archie-platform #373 — Shared Entity Graph — Cross-Watch Identity Resolution
**Date:** 2026-06-14
**Status:** ⛔ **FROZEN / LOCKED** — supersedes the draft `chain_link_types` seed inside the blueprint (`2026-06-14-shared-entity-graph-blueprint.md` §3 step 9 and §7.2). This ADR is the single source of truth for node types and edge strings.
**Phase:** Wave-0. This ADR was locked **BEFORE** migration 034 was written and **BEFORE** any of the 5 product adapters emit a single edge string (the adapters are Wave 1, not yet built).

**Implementation & verification (2026-06-14):** the schema decisions in this ADR are implemented by **migration `034_shared_entity_graph_extend.sql`** (committed in this same PR), which was **applied to the live hub `wtf` DB and verified** (`psql -U archie -d wtf`, EXIT=0). Confirmed live: the frozen `entity_type` CHECK (`person`/`organization`/`journalist`), `shared.chain_link_types` seeded with the exact edge strings below (12 rows; Link 4 *Vote→Policy* and Link 6 *Contract→Market* carry `has_data=false`), and the 10 new dedup/merge/external-id tables. The migration is additive + idempotent (safe to re-run); re-applying it is the regression check. Edge-string conformance going forward is enforced by every adapter importing these strings verbatim (§2) — a cross-repo conformance test is tracked for Wave 1.

---

## 0. Why this ADR exists (the silent-breakage problem)

Five separate repositories — `what-the-fact` (WTF, the single writer), `gov-watch`, `civic-watch`, `legal-watch`, `market-watch` — will produce edge-type strings that land in `shared.entity_relationships.relationship_type` (hub `wtf` DB). Migration 034 **hardcodes these exact strings** into `shared.chain_link_types` (the chain-ordering + has-data catalog). The 8-link chain traversal (`traverse_chain`, recursive CTE filtered by `relationship_type IN (...)`) and the public "which links have data" catalog (`GET /api/public/chain/links`) both depend on byte-for-byte string identity.

If `gov-watch` writes `"awarded"` while migration 034 seeds `"awarded_to"`, the edge exists in the graph but is invisible to the chain walker and to the honesty catalog — a silent, untyped data-corruption that no test in any single repo will catch. Therefore the vocabulary must be frozen in one document, ahead of code, and every repo must import the strings from it verbatim.

**This ADR freezes three things:**
1. The canonical **NODE type** set (3 types only).
2. The canonical **EDGE / relationship-type** string vocabulary (the chain spine + enrichment edges).
3. The **DUAL-SCHEMA BOUNDARY RULE** — which `shared.entities` table is the truth, and the code rule for which DB to read.

### 0.1 Terminology (plain-language, for new contributors)

- **Node / entity** — a row in `shared.entities`: a real-world *thing we track identity for* (a person, an organization, or a journalist). Each has one stable canonical id that never changes or gets reused.
- **Canonical NODE type** — the frozen, closed set of allowed `entity_type` values (here: exactly `person`, `organization`, `journalist`). "Canonical" = the single agreed value (not a synonym); "frozen" = not extendable without a new ADR.
- **Edge / relationship** — a row in `shared.entity_relationships`: a typed, directional link between two nodes (e.g. an MP —`cast_vote`→ a bill-context). The **edge / relationship-type vocabulary** is the closed set of allowed link strings defined in §2.
- **Chain link** — one hop of the public 8-link accountability chain (Money→MP→Vote→Policy→Contract→Market→Coverage→Public). Each chain link maps to one or more edge types in `shared.chain_link_types`, which also records whether that link currently `has_data`.
- **Content / mention** — a document or event (a tender, a court case, a bill, a news article) that is *not* an entity; it is recorded in `shared.entity_mentions` and linked to the person/org nodes it involves (see §1.1).

### 0.2 Amendment process (how this FROZEN ADR is versioned & changed)

**Version:** v1.0 (2026-06-14). This ADR is versioned **by supersession**, never by silent in-place edits to the frozen node/edge lists:

- **Adding a node type or edge string** requires a **new ADR (`ADR-EG-00N`)** that explicitly supersedes the affected section here, PLUS a paired **additive migration** (e.g. `035_…`) that adds the value to the live `entity_type` CHECK and/or the `shared.chain_link_types` seed. Never silently widen a CHECK or write an unlisted edge string.
- **Propagation:** because 5 repos import these strings verbatim, any approved change must update all affected adapters **in the same wave** and is gated by the (Wave-1) cross-repo conformance test. A new edge string is invisible to chain traversal until it is seeded in `chain_link_types`.
- **Deprecation:** mark a node/edge deprecated in the superseding ADR; never delete in place (existing rows must keep resolving). Entity lifecycle uses the `active`/`merged`/`suppressed` status + tombstones, never `DELETE`.
- **Header bookkeeping:** bump the version line above and append a dated changelog entry in the superseding ADR.

---

## 1. CANONICAL NODE TYPES — FROZEN (3 only)

> **`shared.entities.entity_type` is `person`, `organization`, `journalist` — and NOTHING else.**

```
person        — a human (MP, donor, lobbyist, GIC appointee, judge, ethics-ruling subject, byline author who is also a source)
organization  — a legal/collective body (vendor, client org, government department, news outlet, party)
journalist    — a byline author (a specialization of person, kept distinct for the WTF Coverage node and byline resolution)
```

### 1.1 What is NOT a node (must-fix S1 — schema and identity-key list MUST AGREE)

`tender`, `case`, `bill`, `vote`, `policy`, `appointment-order`, `ethics-report` are **CONTENT / events, NOT entities.** They are represented as **`shared.entity_mentions` rows** (the resolved entity ↔ content ledger from migration 030), keyed by `content_type` + `content_id`, plus **typed `shared.entity_relationships`** between the real person/org nodes the content connects. They are NEVER `shared.entities` rows.

| Thing | NOT an entity row. Represented as | content_type | content_id source |
|---|---|---|---|
| Tender / procurement award | `entity_mentions` content pointer + `contracts_with` / `awarded_to` edges between vendor-org and department-org | `procurement` | `reference_number:amendment:winner` |
| SCC / court case | `entity_mentions` content pointer + (deferred) party edges; majority author is a `person` node | `legal_case` | `scc_citation` (e.g. `2024 SCC 1`) |
| Parliamentary bill | `entity_mentions` content pointer + `cast_vote` edges from MP `person` nodes | `bill` | bill number / sponsor-row id |
| A specific vote | edge attribute on `cast_vote`, NOT its own node | (n/a) | recorded on the relationship row |
| Policy / enactment | `entity_mentions` content pointer (NO DATA today — see Link 4) | `policy` | — (no pipeline) |
| GIC appointment order (OIC) | `entity_mentions` content pointer; the appointee is a `person`, the body is an `organization` | `appointment` | `oic_pc_number` (e.g. `2026-0436`) |
| Ethics ruling | `entity_mentions` content pointer; the subject is a `person` | `ethics_ruling` | `report_name` (see S4) |
| News article | `entity_mentions` content pointer (the Coverage node, materialized at query time) | `article` | WTF article id |

**Reconciling the migration-034 entity_type CHECK with this rule (correction to blueprint §3 step 1):** the blueprint's draft widened the CHECK to include `news_outlet`, `vendor`, `case`, `tender`. Per S1 this is **wrong**: `news_outlet` and `vendor` are `organization` (use `metadata.org_kind` to subtype if needed); `case` and `tender` are NOT entities at all. The frozen CHECK is:

```sql
CHECK (entity_type IN ('person','organization','journalist'))
```

The identity-key list (§4) and the schema CHECK now AGREE: only durable person/org/journalist identities live in `entity_external_ids`; all document/event keys are demoted to `entity_mentions` content pointers (must-fix S2).

### 1.2 Demoted keys (must-fix S2) — document pointers, NOT Tier-1 person keys

These were drafted as Tier-1 PERSON external IDs; they are demoted to **`entity_mentions.content_id`** because they identify a DOCUMENT/EVENT, not a durable person identity. The PERSON behind each is a **Tier-2 FUZZY name** (no FK, no postal, no `entity_external_ids` row):

| Key | It identifies | The person behind it (Tier-2 fuzzy) |
|---|---|---|
| `procurement_reference` | a tender/award document | (vendor org — name-only, no BN) |
| `scc_citation` | a case document | majority-author judge — name-only |
| `oic_pc_number` | an appointment order document | the appointee — name-only (no FK to MP) |
| `ethics_report_url` / `report_name` | a ruling document | the ethics subject — name-only, cross-linked to MP by `mp_slug` hub-side |

`entity_external_ids` holds **ONLY true durable person/org/journalist ids**: business number (none exist today — gap), `openparliament_slug`, `parl_mp_id`, `lobbying_comlog_id` (event-scoped, see S3), `wtf_source_slug` (outlet domain).

---

## 2. CANONICAL EDGE / RELATIONSHIP-TYPE VOCABULARY — FROZEN

> **Every string below is the EXACT, case-sensitive, snake_case value written to `shared.entity_relationships.relationship_type` and seeded into `shared.chain_link_types`. No variant, no plural, no abbreviation. Import from this ADR; never hand-type.**

### 2.1 The 8 chain-link positions (the public "which links have data" catalog)

The accountability chain is **Money → MP → Vote → Policy → Contract → Market → Coverage → Public** (company-vision §3). `chain_link_types.link_position` is 1..8. Position 2 and position 8 are **NODE positions** (the MP node and the Public), not edges — they get catalog rows so the public link-catalog is honest and complete (must-fix S5).

| Pos | Link name | Spine edge string(s) | has_data |
|---|---|---|---|
| 1 | Money → MP | `donated_to` | TRUE |
| 2 | **MP (NODE)** | — (the `person` node itself; arrival point of Link 1, origin of Link 3) | TRUE |
| 3 | MP → Vote | `cast_vote` | TRUE |
| 4 | Vote → Policy | `enacted_as` | **FALSE** (no ingest pipeline) |
| 5 | Policy → Contract | `awarded_to`, `contracts_with` | TRUE |
| 6 | Contract → Market | `market_reaction_to` | **FALSE** (no securities/issuer pipeline beyond Bank-of-Canada) |
| 7 | → Coverage | `covered_by` (derived at query time) | TRUE |
| 8 | **Public (NODE)** | — (the citizen / terminal of the chain; narrate-only) | TRUE |

**Correction to the blueprint draft seed (must-fix S5):** the blueprint mis-seeded `lobbied_by` as `link_position=2` and labeled it "Lobby → MP". That is wrong — **position 2 is the MP NODE (spine)**. `lobbied_by` is an **ENRICHMENT edge that attaches TO the MP node**, not the link-2 spine step. Mislabeling it would make the public link-catalog claim "Link 2 = lobbying" which is dishonest. `lobbied_by` is catalogued separately as enrichment (§2.3) with `link_position=2` only as an *attachment hint*, never as the spine.

### 2.2 SPINE edges — full specification

These walk the accountability chain. `traverse_chain` filters on these by default.

| # | Edge string | from-type → to-type | Source product (writer) | Chain link pos | Spine/Enrich | has_data | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `donated_to` | person (donor) → person (MP) | parliament (donor adapter, hub-resident) | 1 | **spine** | TRUE | EC contributions. Donor↔MP via `electoral_district = mps.riding_name` text join; `metadata.ambiguous=true` if >1 MP. Donor materialized only at ≥$200 aggregate AND slug-match-to-existing first pass (owner decision). |
| 2 | `cast_vote` | person (MP) → (bill content) | parliament / WTF (hub-resident) | 3 | **spine** | TRUE | The vote outcome (yea/nay/paired) is an attribute on the relationship row (`metadata.vote`), NOT a separate node. `to_entity_id` points at the bill-sponsor person OR is recorded via `entity_mentions` content_id when the bill has no person target. |
| 3 | `enacted_as` | (bill content) → (policy content) | — (NO WRITER) | 4 | **spine** | **FALSE** | Placeholder. No ingest pipeline maps a vote to an enacted policy. API returns `status:"no_data"`; UI permanently dims. NEVER render as populated. |
| 4 | `awarded_to` | organization (department) → organization (vendor) | gov-watch (vendor adapter, remote-push) | 5 | **spine** | TRUE | The award is `entity_mentions` content (`procurement_reference`), the edge is dept-org → vendor-org. Vendor identity is name-only (no BN — fuzzy gap). |
| 5 | `contracts_with` | organization (vendor) ↔ organization (department) | gov-watch | 5 | **spine** | TRUE | Inverse-direction companion to `awarded_to` (one of the original 5 from migration 030). Use `awarded_to` for the dept→vendor direction; `contracts_with` for the durable contractual relationship. |
| 6 | `market_reaction_to` | organization (issuer) → (contract/event content) | market-watch | 6 | **spine** | **FALSE** | Placeholder. Market Watch is ticker/chrome-only — there is no securities/issuer ENTITY to feed beyond Bank-of-Canada rate context. API returns `status:"no_data"`; UI permanently dims. NEVER render as populated. |
| 7 | `covered_by` | (any entity) → journalist / news_outlet-org | WTF (derived at query time) | 7 | **spine** | TRUE | NOT a stored edge. Materialized at query time from `entity_mentions JOIN wtf.articles JOIN wtf.sources` filtered `product='wtf' AND content_type='article'`. Seeded in `chain_link_types` so the catalog lists Link 7, but adapters do NOT write `covered_by` rows. |

### 2.3 ENRICHMENT edges — attach context to nodes, NOT spine steps

These enrich entity profiles and the chain rail but are NOT the spine traversal. `traverse_chain` includes them only when explicitly requested via `edge_types=`.

| # | Edge string | from-type → to-type | Source product (writer) | Attaches at link | Spine/Enrich | has_data | Notes |
|---|---|---|---|---|---|---|---|
| 8 | `lobbied_by` | person (MP) / organization → person (lobbyist) | parliament (hub-resident) + civic-watch (remote-push) | 2 (attach to MP node) | **enrichment** | TRUE | One of the original 5 (migration 030). **Explicitly NOT link-2 spine** (S5). Parliament writer keys on `lobbying_comlog_id` (event); civic writer keys on `lobbyist_registration_num` (registration). See S3 — these are NON-JOINABLE cross-DB. |
| 9 | `appointed_to` | person (appointee) → organization (department/body) | gov-watch (gic adapter, hub-resident) | 5 (attach near Contract) | **enrichment** | TRUE | One of the original 5 (migration 030). GIC appointee who is also an MP **collapses onto the existing MP person row** via slug. Appointee→MP edge has NO deterministic key (S7) — model as Tier-2 fuzzy, low-confidence, or leave unresolved. The OIC order is `entity_mentions` content (`oic_pc_number`), NOT a node. |
| 10 | `employs` | organization (client) → person (lobbyist/employee) | parliament + civic-watch | 2 (attach to lobbyist) | **enrichment** | TRUE | One of the original 5 (migration 030). Links a client org to the lobbyist it employs. |

### 2.4 Frozen string list (the literal import set)

```
# SPINE (walk the chain — traverse_chain default filter):
donated_to            # 1  has_data=TRUE
cast_vote             # 3  has_data=TRUE
enacted_as            # 4  has_data=FALSE  (placeholder, no writer)
awarded_to            # 5  has_data=TRUE
contracts_with        # 5  has_data=TRUE
market_reaction_to    # 6  has_data=FALSE  (placeholder, no writer)
covered_by            # 7  has_data=TRUE   (derived at query time, never written by adapters)

# ENRICHMENT (attach to nodes — opt-in via edge_types=):
lobbied_by            # attach@2  has_data=TRUE
appointed_to          # attach@5  has_data=TRUE
employs               # attach@2  has_data=TRUE
```

### 2.5 Corrected `chain_link_types` seed (replaces blueprint §3 step 9)

Migration 034 MUST seed exactly this — all 8 positions, both NODE positions, gaps marked `has_data=FALSE`, `lobbied_by` correctly labeled enrichment-not-spine. NODE positions carry a sentinel `relationship_type` (`__mp_node__`, `__public_node__`) so the PRIMARY KEY holds while the catalog stays honest that they are nodes, not edges.

```sql
-- chain_link_types: ALL 8 positions seeded (must-fix S5). has_data FALSE on Link 4 + Link 6.
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
  ('lobbied_by',          2, 'Lobbying (enrichment)',   TRUE, FALSE),
  ('appointed_to',        5, 'Appointment (enrichment)',TRUE, FALSE),
  ('employs',             2, 'Employs (enrichment)',    TRUE, FALSE)
ON CONFLICT (relationship_type) DO UPDATE SET
  link_position = EXCLUDED.link_position,
  label         = EXCLUDED.label,
  has_data      = EXCLUDED.has_data,
  is_spine      = EXCLUDED.is_spine;
```

> The blueprint's draft `chain_link_types` table did NOT have an `is_spine` column and did NOT seed positions 2 or 8. Migration 034 MUST add `is_spine BOOLEAN NOT NULL DEFAULT TRUE` to the table definition and seed all 12 rows above. The public catalog (`GET /api/public/chain/links`) reads `is_spine` to render enrichment edges differently from spine links, and `has_data=FALSE` rows render permanently dim.

### 2.6 Honesty contract (owner decision — data gaps)

- The full 8-link chain SHIPS, but **Link 4 (Policy / `enacted_as`)** and **Link 6 (Market / `market_reaction_to`)** have `has_data=FALSE`.
- The chain API returns `{"status":"no_data","reason":"no ingest pipeline"}` for these links.
- The UI renders them **permanently dim** with a `/transparency` "why" tooltip.
- **NEVER render an empty link as populated.** Fabricating a traversal the data cannot support is a credibility incident and is forbidden.

---

## 3. DUAL-SCHEMA BOUNDARY RULE — FROZEN (must-fix S6)

> **There are TWO tables named `shared.entities` on TWO different databases. They are NOT the same thing and must NEVER be confused. The canonical accountability graph is the hub `wtf` DB only.**

| | **CANONICAL GRAPH (the truth)** | **SIGNAL BUS (NOT the truth)** |
|---|---|---|
| Database | hub **`wtf`** DB | hub **`archie`** DB |
| Schema/table | `shared.entities` (+ `shared.entity_mentions`, `shared.entity_relationships`, `shared.entity_external_ids`, `shared.source_mention`, `shared.chain_link_types`, …) | `shared.entities` (migration 393) |
| `entity_type` values | `person`, `organization`, `journalist` | `department`, `topic`, `keyword` / org-signal |
| Purpose | The accountability graph. Node + edge resolution. Chain traversal. | The cross-watch follow/alert **signal bus**. Lighter follow-subject store. |
| Migration 034 target | **YES — 034 targets the `wtf` DB ONLY** | **NO — 034 never touches the `archie` DB** |
| Written by | WTF single-writer resolver (`_upsert_entity` / `resolve_byline`) via the hub ingest endpoint | the follow/alert feature |
| Reconciliation | — | syncs the canonical `entity_id` into `archie.shared.entities.metadata->'canonical_entity_id'` over the mesh `/api/internal/` pattern; NEVER written as truth |

### 3.1 Code rule — which DB to read (paste into route docstrings)

```
CANONICAL ENTITY / NODE / EDGE / CHAIN lookups (slug→entity, entity_type person/org/journalist,
relationship_type, chain traversal, dedup, external_ids):
    -> ALWAYS the hub `wtf` DB `shared` schema.
    -> In-process for WTF consumer code (it owns WTF_DATABASE_URL).
    -> Server-to-server over the MESH (100.64.0.4) for the hub cross_watch blueprint
       (federate to wtf-DB graph or proxy to WTF consumer chain.py — never read archie.shared.entities for nodes).

FOLLOW / ALERT / SIGNAL lookups (a user's followed subjects, department/topic/keyword signals):
    -> the hub `archie` DB `shared.entities` (migration 393) — the signal bus, NOT the graph.

NEVER point a slug/id/relationship lookup at archie.shared.entities. It has the wrong
entity_type domain (department/topic/keyword) and will return empty/wrong nodes.
```

### 3.2 Migration 034 header comment (REQUIRED — must-fix S6)

Migration 034 MUST open with this header so no future coder points a lookup at the wrong table:

```sql
-- ============================================================================
-- Migration 034_shared_entity_graph.sql
-- TARGET: hub `wtf` DB, `shared` schema  (apply: psql -U archie -d wtf -f ...)
--
-- ⚠️ DUAL-SCHEMA WARNING (ADR-EG-001 §3):
--   The hub `archie` DB ALSO has a `shared.entities` table (migration 393).
--   That is a SEPARATE signal-bus (entity_type = department/topic/keyword) for
--   the follow/alert feature. THIS migration targets the `wtf` DB ONLY.
--   The canonical accountability graph (person/organization/journalist) lives
--   HERE, in the `wtf` DB. NEVER run this against the `archie` DB.
-- ============================================================================
```

---

## 4. IDENTITY KEYS — frozen alignment with the node rule

`entity_external_ids` holds ONLY durable person/org/journalist ids. Document/event keys are `entity_mentions` content pointers (S2). The keys below are the only Tier-1 deterministic keys; everything else is Tier-2 fuzzy.

### 4.1 Tier-1 DETERMINISTIC (exact match → auto-merge @ conf 1.0)

| key_type | Source | Identifies (node) |
|---|---|---|
| `openparliament_slug` | `parliament.mps.slug` | MP (person) |
| `parl_mp_id` | `parliament.mps.parl_mp_id` | MP (person) |
| `lobbying_comlog_id` | `parliament.lobbyist_contacts.comlog_id` | lobbyist communication EVENT (see S3) |
| `wtf_source_slug` | `wtf.sources.slug` + domain | news outlet (organization) |

### 4.2 Lobbyist identity (must-fix S3) — event vs registration vs person

- `lobbying_comlog_id` is UNIQUE only as the pair **`(comlog_id, mp_id)`** = a communication EVENT, not a person.
- `lobbyist_registration_num` (civic-watch) = a REGISTRATION (nullable, non-unique alone) — NOT a Tier-1 person key.
- The lobbyist **PERSON** identity is **Tier-2 fuzzy** (registrant / lobbyist name).
- **`civic` `registration_num` and `parliament` `comlog_id` are NON-JOINABLE cross-DB** — there is no ETL bridge between them. Do NOT attempt a deterministic join across the two lobbying datasets. Document this in both adapters.

### 4.3 Ethics ruling key (must-fix S4)

- `ethics_report_url` is **NOT UNIQUE** in the canonical `wtf` DB (migration 026 made only `report_name` unique).
- The ethics adapter MUST key on **`report_name`**, not `report_url`.
- Do **NOT** alter another product's table to add a `report_url` UNIQUE constraint unless the ALTER is additive + safe. Prefer keying on the existing unique column.
- The ethics ruling is `entity_mentions` content (`content_type='ethics_ruling'`, `content_id=report_name`); the SUBJECT is a Tier-2 fuzzy `person`, cross-linked to an MP by `mp_slug` hub-side.

### 4.4 Tier-2 FUZZY (no durable ID → propose/queue, never silent cross-product auto-merge)

- Elections Canada donors — `normalized(contributor_name)` + `contributor_postal`. No durable donor ID. Materialize only at **≥$200 aggregate** AND slug-match-to-existing-entity on first pass (owner decision — avoids the 4.1M-row explosion + review-queue flood).
- Vendors/suppliers — `normalized(vendor_name)` + `vendor_postal_code`. **No CRA/BN/GST number in ANY dataset** — org match is fuzzy-only.
- Civic DPOH / bill sponsor / SCC judge — normalized name only; free text, no FK.
- GIC appointee → MP (S7) — `gic_appointments.appointee_name` is optional free text with NO key. Model the appointee→MP edge as a **Tier-2 fuzzy, low-confidence** edge or leave unresolved. Do NOT assume a deterministic join.

---

## 5. SINGLE-WRITER + INGEST INVARIANTS (frozen, for adapter authors)

So the frozen edge strings reach the graph through exactly one resolver (must-fix I1):

- The entity ingest endpoint lives **INSIDE the WTF consumer app** (it already holds `WTF_DATABASE_URL` + the `_upsert_entity` helper, on Citadel) as **`POST /api/internal/entity-graph/ingest`** (auth: `X-Internal-Key`).
- `gov-watch`, `civic-watch`, `legal-watch`, `market-watch` adapters **POST** their edges/mentions to that endpoint over the **mesh**. They do NOT open a cross-host DB connection. Only WTF's own hub-resident adapters write the DB directly (single-writer; reuse `_upsert_entity`; NO third resolver).
- **Compose env contract (must-fix I2):** add `ENTITY_INGEST_URL` + `INTERNAL_API_KEY` to the **`environment:` block** of the **civic** AND **market** composes (they have NO `env_file:` — vars are silently absent otherwise). Verify the RUNTIME env with `docker inspect`, never by reading `.env`.
- The nightly dedup scan runs **co-located with the `wtf` DB** (must-fix I3) — no streaming of candidate pairs across the mesh.
- Edge writes are idempotent: UPSERT on the migration-030 `UNIQUE (from_entity_id, to_entity_id, relationship_type, source_product, source_id)`.

### 5.1 Interconnect asymmetry (must-fix W4) — stated explicitly

| Product | Role in the graph |
|---|---|
| **WTF** | full feed (mp + author, SHIPPED) + deep consume; owns the Coverage node (Link 7); single writer |
| **Gov Watch** | full feed (gic + vendor) + deep consume |
| **Civic Watch** | feed (lobby/bill/civic_event) + **shallow** consume |
| **Legal Watch** | feed (scc/ethics) + **shallow** consume |
| **Market Watch** | **chrome-only** — NO securities entity to feed (Link 6 placeholder); footer + bell only; count honestly 0 |
| **Homepage** | **narrate-only** — does not feed; static "Accountability Graph" section + live CREED badge |

---

## 6. CHAIN ACCESS POLICY (owner decision — frozen)

- **FREE (public, no-auth, CORS `*`, 60s cache):** chain SHAPE + bias + connected/gap status (`links_resolved[]`, `links_missing[]`, `coverage_pct`, `has_data` per link). The civic-good loss-leader.
- **GATED to `wtf-premium`:** deep per-link records + rationale + full chain depth beyond hop 2. Gated at the API (`require_product_access`) so the proxy cannot leak gated data to free users.

---

## 7. ENFORCEMENT — how the freeze is kept

1. **One import set.** Every repo imports the §2.4 string list verbatim (a shared constants module / copied frozen list). No repo hand-types an edge string.
2. **Migration 034 is the seed of record.** It seeds exactly the §2.5 rows. Adapters that emit a string not present in `chain_link_types` should be treated as a bug (optionally enforced by a FK or a CI check that diffs emitted strings against the catalog).
3. **No new edge string ships without amending this ADR first** and re-seeding `chain_link_types`. String drift across the 5 repos silently breaks traversal — that is exactly the failure this ADR prevents.
4. **Node CHECK is `person|organization|journalist` only.** Any PR widening it to add content types (`case`/`tender`/`bill`/`vote`/`policy`) must be rejected — those are `entity_mentions` content (S1).

---

## 8. Decisions captured (locked 2026-06-14)

- **NODE types frozen:** `person`, `organization`, `journalist` only. Content/events via `entity_mentions` (S1/S2).
- **EDGE vocabulary frozen:** 7 spine (`donated_to`, `cast_vote`, `enacted_as`, `awarded_to`, `contracts_with`, `market_reaction_to`, `covered_by`) + 3 enrichment (`lobbied_by`, `appointed_to`, `employs`). `enacted_as` (Link 4) and `market_reaction_to` (Link 6) are `has_data=FALSE` placeholders.
- **All 8 chain positions seeded**, including the MP node (pos 2) and Public node (pos 8); `lobbied_by` is enrichment, NOT the link-2 spine (S5).
- **Dual-schema boundary frozen:** canonical graph = hub `wtf` DB `shared`; `archie` DB `shared.entities` is a separate signal bus; migration 034 targets `wtf` DB only with the §3.2 header comment (S6).
- **Identity-key corrections locked:** S2 (document keys demoted to content pointers), S3 (lobbyist event vs registration, non-joinable cross-DB), S4 (ethics key on `report_name`), S7 (GIC→MP fuzzy/unresolved).
- **Author-only this wave.** No git commit/push, no migration applied, no deploy. Sign-off AFTER this wave.

---

*ADR-EG-001 FROZEN 2026-06-14. This document is the single source of truth for the Shared Entity Graph node + edge vocabulary. Migration 034 and all 5 product adapters derive their strings from §2.4 and §2.5. Any change requires amending this ADR first.*
