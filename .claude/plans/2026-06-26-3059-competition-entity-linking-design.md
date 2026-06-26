# Phase 2 — Legal #3059: Competition-Enforcement → Company-Entity Linking (Design)

**Date:** 2026-06-26 · **Branch:** `feat/3059-competition-entity-linking` · **Project:** #345 Legal Watch / #373 Shared Entity Graph
**Status:** Design approved (owner, 2026-06-26). Awaiting spec review → implementation plan.

---

## 1. Context & Goal

Phase 1 (cont-88, shipped 2026-06-26) put **2,019 sector-tagged Canadian listed companies** into the shared
graph (`wtf.shared.entities`, `entity_type='organization'`, `metadata.naics_source='tmx_derived'`).

Phase 2 makes Legal Watch's **Competition Bureau** feed contribute to those companies' cross-watch
accountability footprint: when a Competition Bureau item names a listed company, attach a
`competition_enforcement` **mention** to that company's existing graph node. This is the legal arm of the
8-link chain reaching the company layer.

**This is a low-yield, defamation-sensitive link by nature** — and that is the intended outcome. We prefer a
handful of *correct* links over many with one wrong.

### Ground truth (verified 2026-06-26)
- `competition_enforcement` (live Citadel `legal.db`): **50 rows** — advocacy 25, merger 12, investigation 8,
  litigation 3, deceptive_marketing 2. The table has **no structured target field**; the company is in
  free-text `title`/`summary`, usually possessive ("Keyera's proposed acquisition", "investigation into
  Sobeys'") and often a **brand ≠ listed legal name** (Sobeys → *Empire Company Limited*).
- The graph endpoint is the **single writer**: it UPSERTs entities on `slug = name_to_slug(normalize_name(name))`.
  Sending a loosely-extracted headline name would **create a duplicate node**, not link. Linking must therefore
  resolve to a company **already in the graph** and emit via that company's exact slug.
- `shared.entity_mentions` has **no `content_type` CHECK** (only `confidence ∈ [0,1]`) → **no migration needed**
  to add `competition_enforcement`.
- Company `canonical_name` casing is inconsistent ("cae inc.", "Telesat Corporation") but **slugs are clean**
  (`cae-inc`, `telesat-corporation`). Match on normalized names; emit via **slug pointers**.

## 2. Decision

- **Build now: conservative dictionary match** (Option A). Deterministic, zero-LLM, highest precision.
- **Architect for the future: a guardrailed/configurable G.A.V.E.L. extractor** (Option B) slots in behind the
  *same* match-gate + defamation guard. The match-gate and the framing ARE the guardrails; only the
  "produce a candidate name" step changes.

## 3. Architecture — three separable units

```
competition_enforcement row ──► [Extractor] ──candidate name(s)──► [resolve()] ──slug|None──► [Emitter] ──► mention POST
                                  v1: dictionary-scan                match-gate /              defamation
                                  v2 (future): GavelExtractor        guardrail (shared)        guard + framing (shared)
```

### 3a. `ingest/company_match.py` *(new, pure, unit-tested — the guardrail core)*
- `build_index(companies) -> Index` — from `[{slug, canonical_name}]`, precompute each company's normalized
  **core** (suffix-stripped token list) + distinctiveness flag.
- `resolve(text, index) -> {slug, canonical_name} | None` — return a company **iff exactly one** company core
  matches `text` under the rules in §4; 0 or ≥2 → `None`.
- No I/O, no DB, no network → fully testable in isolation.

### 3b. New `competition` source in `ingest/entity_graph_adapter.py`
- Fetches the company index **once per run** from the WTF read endpoint (§3c).
- v1 extractor = pass each row's `title + " " + summary` straight into `resolve()` (extraction + match fused).
- Builds mentions (§5) and POSTs through the **existing** batched `_post()` path. No new transport.
- Added as a third entry in `_SOURCES`, but **gated**: only runs when explicitly selected
  (`--source competition`) — it is NOT part of the default full backfill loop (see §6).

### 3c. WTF read endpoint — `consumer/entity_graph_routes.py`
- `GET /api/internal/entity-graph/companies` (auth: `X-Internal-Key`, same as ingest) →
  `{"companies": [{"slug","canonical_name"}, ...]}` for
  `entity_type='organization' AND metadata->>'naics_source' IS NOT NULL`.
- Lets the adapter (running in `kytran_legal_api` on Citadel) get the authoritative company set without DB creds
  for the `wtf` DB. Read-only, idempotent, cacheable.

## 4. The matcher (precision core) — exact rules

Normalization (`_norm`): NFKD-fold accents → lowercase → non-alphanumeric to spaces → collapse → token list.

**Core derivation:** `_norm(canonical_name)`, then drop trailing pure legal-form suffix tokens:
`{corp, corporation, inc, incorporated, ltd, limited, co, company, plc, lp, llp, llc, sa, nv, ag, ulc}`.
Keep distinctive words (holdings/group/resources/energy stay in the core).

**Match test (company core C against row token list R):**
1. C must appear in R as a **contiguous whole-word sub-sequence** (token-list match — avoids substring hits).
2. Distinctiveness guard:
   - multi-token core → eligible (e.g. "capital power" must appear as the phrase, low collision risk); OR
   - single-token core → eligible **only if** `len ≥ 4` **and** not in `COMMON_WORD_STOP`
     (starter set: capital, power, energy, gold, silver, metals, mining, first, north, south, west, royal,
     canadian, national, pacific, atlantic, premium, brands, group, holdings, resources, financial, bank,
     trust, fund, income, growth, global, american — tunable). So "cae" (len 3) is a **safe skip**.
3. Collect ALL companies passing 1+2 for the row. **Emit iff exactly one** → its slug. Else skip silently.

Rationale: single-token distinctive names (Keyera, Cineplex, Sobeys, Telesat) match well; multi-token names
need the full phrase (lower recall, higher precision — the chosen tradeoff). Brand≠legal-name (Sobeys→Empire) is
a **safe miss**, not a wrong link.

## 5. Mention semantics + defamation guard

- **Eligible categories:** `merger`, `litigation`, `investigation`, `deceptive_marketing`. **`advocacy` excluded**
  (general commentary, no defendant).
- Emit `mention`:
  - `entity = {"slug": matched_slug}` — a **pointer**: attaches to the existing node only, never creates one.
  - `content_type = "competition_enforcement"`
  - `content_id = news_url` (stable; the UPSERT key dedupes — Keyera's 4 distinct urls = 4 honest coverage mentions)
  - `mention_context = title` (verbatim, ≤280 chars; source-grounded)
- **Framing is "named in a Competition Bureau {category} item"** — never asserts guilt, wrongdoing, or a finding.
- **No relationships** emitted (frozen edge vocabulary, ADR-EG-001 §2 — identical to the existing adapter).

## 6. Safety / ops

- `--dry-run` prints every proposed `(company canonical_name ← headline)` pair for human eyeball **before any POST**.
- Run is **manual + bounded** (`python -m ingest.entity_graph_adapter --source competition [--dry-run]`).
  It is **NOT** wired to a tight scheduled loop on the live web workers — per the 2026-06-15 entity-graph DoS
  (KB #273576: row-by-row scheduled backfills starved `what-the-fact.com` gunicorn workers). 50 rows is trivial,
  but the principle holds: graph ingest stays off the hot request path.
- 2-repo change: `what-the-fact` (read endpoint) + `kytran-legal-watch` (adapter source + matcher + tests).

## 7. Testing

`tests/test_company_match.py` (legal-watch) against a small fixture index:
- **True positive:** "Competition Bureau challenges Keyera's proposed acquisition" → resolves to the Keyera node.
- **Safe miss:** "investigation into Sobeys' use of property controls" with only *Empire Company Limited* in the
  index → `None` (brand ≠ legal name).
- **Distinctiveness guard:** a headline containing "cae" with *CAE Inc.* in index → `None` (len-3 single token).
- **Common-word guard:** "capital" alone does not match *Capital Power Corporation* (multi-token core needs the phrase).
- **Ambiguity:** a row matching two companies → `None`.
- **Suffix stripping / casing:** "cae inc." index entry derives core `cae`; normalization is case-insensitive.

## 8. Future seam — Option 2 (guardrailed G.A.V.E.L.)

The future `GavelExtractor.extract(row) -> list[str]` (LLM-proposed legal target names, brand→legal mapping)
feeds the **same** `company_match.resolve()` + §5 emitter. "Guardrails/configurations" = the extractor's prompt
+ confidence threshold + category config; the match-gate and the "named in" framing remain the hard backstop, so
the LLM can only ever *propose* — it can never assert a finding or link to a node that isn't already a real
listed company. No schema or endpoint change required to add it later.

## 9. Files

| Repo | File | Change |
|------|------|--------|
| kytran-legal-watch | `ingest/company_match.py` | NEW — index + `resolve()` (pure) |
| kytran-legal-watch | `ingest/entity_graph_adapter.py` | ADD `competition` source + company-index fetch; `--source` flag |
| kytran-legal-watch | `tests/test_company_match.py` | NEW — matcher unit tests |
| what-the-fact | `consumer/entity_graph_routes.py` | ADD `GET /api/internal/entity-graph/companies` |

## 10. Open verification items (resolve during build)
- Confirm the adapter's `ENTITY_INGEST_URL` host/port in the live legal-api env (the read endpoint shares that host).
- Confirm the WTF route blueprint prefix so the companies endpoint path is exact.
- Confirm the `--source` flag does not break the existing default (ethics + regulations) run.
