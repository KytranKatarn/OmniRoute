# Platform Translation Coverage System — Design

**Date:** 2026-04-18
**Projects:** #232 (Consciousness Translation Pipeline), #231 (Website Translation QA), closes both if successful
**Author:** KytranKatarn + Claude Opus 4.7 (1M)
**Status:** Draft → pending user review

## Problem

The platform has a partial translation pipeline: 8 languages (en, fr, es, pt, de, zh, ar, he), a `translations` table, Bridge dispatch, and a Consciousness Languages tab with scan/seed/generate/export endpoints. Today it covers **3 sources** — `website_kytranempowerment.com`, `website_creed`, and `website_kso`.

The user sees missing words even on the one product that IS in the pipeline (`kytranempowerment.com`), and ~47 other surfaces are entirely outside coverage:
- **36 internal platform modules** in `platform_v2/tools/`
- **5 external websites** (kytranempowerment.com, what-the-fact.com, thenews.*, wtf.*, creed-ai.org)
- **6 standalone products** (kytran-{civic,gov,legal,market}-watch, business-suite, server-manager)

Three gap classes exist on these surfaces:
1. Strings tagged `data-i18n` but no DB row for a given language → English leakage on non-EN pages.
2. Hardcoded English text with NO `data-i18n` tag → always English, language switcher can't touch it.
3. AI translations that ARE filled but drift semantically from the source (e.g., wrong register, residual English tokens).

Without a systemic scanner + verifier, regressions accumulate silently. Today's audit already found `website_kytranempowerment.com` has 2,516 tagged strings but the user reports visible English leakage — the pipeline isn't keeping up.

## Goals

1. **Detection** — find every gap of all three classes across all 47 targets.
2. **Generation** — AI-fills `missing` gaps via Bridge with glossary priming for brand consistency.
3. **Routing** — confidence-tiered: high → auto-approve, low → human review via Dept HQ (C.O.D.E.X. / Documentation & Knowledge).
4. **Verification** — P.R.O.B.E. Playwright + OCR pass per (product, language) to catch regressions that evade text-level scanning.
5. **Prevention** — nightly cadence so regressions surface within 24 hours.
6. **Observability** — per-product per-language coverage % visible in Consciousness Languages tab.

## Non-goals (for this spec)

- Auto-editing templates to add missing `data-i18n` tags. Those land as PR-like proposals for human merge.
- Per-language agents with cultural nuance personalities. A future iteration if basic pipeline proves itself.
- Fleet-distributed crawling. 47 targets fit comfortably on the hub.
- Additional languages beyond the 8 already supported.

## Architecture

```
                         ┌─────────────────────────────────────┐
                         │  Nightly trigger (agent_loop 2am)   │
                         │  + manual "Scan Now" button         │
                         └─────────────────┬───────────────────┘
                                           │
                  ┌────────────────────────▼─────────────────────────┐
                  │          TranslationScanner (orchestrator)       │
                  │  iterate 47 sources: 36 modules + 11 external    │
                  └──────┬───────────┬───────────┬────────────────────┘
                         │           │           │
                  ┌──────▼──┐  ┌────▼─────┐ ┌───▼──────────┐
                  │ Tagged  │  │ Untagged │ │  Semantic    │
                  │ Scanner │  │ Scanner  │ │  Quality     │
                  │ (exist) │  │ (new)    │ │  (new)       │
                  └──────┬──┘  └────┬─────┘ └───┬──────────┘
                         └───────────┼───────────┘
                                     ▼
                      ┌──────────────────────────────┐
                      │    translation_gaps table    │
                      └──────────┬───────────────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  ▼                             ▼
         ┌──────────────────┐         ┌────────────────────┐
         │  Bridge generate │         │ Coverage Dashboard │
         │  (existing)      │         │ in Consciousness   │
         └────────┬─────────┘         └────────────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Confidence gate  │
         └───┬────────────┬─┘
             │ ≥ 0.85     │ < 0.85
      ┌──────▼──────┐ ┌──▼──────────────────────┐
      │ auto-approve│ │ unified_tasks → C.O.D.E.X. │
      │ → translations│ │ (Doc & Knowledge dept)   │
      └──────┬───────┘ └──────────────────────────┘
             ▼
     ┌──────────────────┐    ┌─────────────────────┐
     │ export-bundle    │───▶│ P.R.O.B.E. nightly QA│
     │ writes           │    │ Playwright + OCR     │
     │ translations.json│    │ for English residue  │
     └──────────────────┘    └─────────────────────┘
```

### Ownership

| Layer | Owner | Rationale |
|-------|-------|-----------|
| Orchestrator + scanners + dashboard | Consciousness module | Consciousness already owns knowledge, KB, and Languages tab |
| LLM generation + semantic scoring | Bridge (via `dispatch_json`) | All LLM inference goes through Bridge per ADR-013 |
| Low-confidence review | Dept HQ / C.O.D.E.X. (Doc & Knowledge) | Dept HQ is the agent assignment engine |
| Playwright + OCR verification | P.R.O.B.E. QA suite | QA is P.R.O.B.E.'s department |
| Cron trigger | agent_loop | Autonomy module owns scheduled jobs |

## The Three Detection Passes

### Pass 1 — Tagged-but-missing (extends existing)

Reuses `scan_and_seed_keys()` in `tools/consciousness/language_routes.py`. Only change: extend `EXTERNAL_SCAN_SOURCES` from 3 → 11 entries.

New entries:
```python
("product_civic_watch",  "/mnt/standalone/kytran-civic-watch",   None),
("product_gov_watch",    "/mnt/standalone/kytran-gov-watch",     None),
("product_legal_watch",  "/mnt/standalone/kytran-legal-watch",   None),
("product_market_watch", "/mnt/standalone/kytran-market-watch",  None),
("website_what_the_fact","/mnt/standalone/websites/what-the-fact.com", "/mnt/standalone/websites/what-the-fact.com/data/translations.json"),
("website_thenews",      "/mnt/standalone/websites/thenews.kytranempowerment.com", "/mnt/standalone/websites/thenews.kytranempowerment.com/data/translations.json"),
("product_business_suite","/mnt/standalone/kytran-business-suite", None),
("product_kytran_news",  "/mnt/standalone/kytran-news",          None),
```

Output: rows in `translation_gaps` with `gap_type='missing'` where `(key, language)` has no corresponding `translations` row.

### Pass 2 — Untagged hardcoded text (new)

New file: `tools/consciousness/translation_scanners/untagged_scanner.py`.

Walks HTML via BeautifulSoup. For each visible text node and translatable attribute (`placeholder`, `title`, `alt`, `aria-label`):
1. Skip if inside `<script>`, `<style>`, `<code>`, `<pre>`, `<svg>`
2. Skip if parent or ancestor has `data-i18n*` (inherited)
3. Skip if text < 3 chars OR contains only digits/symbols
4. Skip common single-word ignorables: `"OK"`, `"×"`, `"▾"`, `"&nbsp;"`
5. Skip `data-i18n-*` attribute helpers (already handled by tagged scanner)

Output: rows in `translation_gaps` with `gap_type='untagged'`, fields:
- `file_path`, `line_number`, `snippet` (first 200 chars)
- `suggested_key` — auto-derived: `<source_slug>.<file_basename>.<slug(text)[:40]>`

Note: `gap_type='untagged'` rows have NULL `language` because they apply to all languages — the English isn't externalized yet.

### Pass 3 — Semantic quality (new)

New file: `tools/consciousness/translation_scanners/semantic_scanner.py`.

For each `translations` row with `language != 'en'` AND (`last_semantic_review_at IS NULL` OR `last_semantic_review_at < NOW() - INTERVAL '30 days'`):
1. Load the EN source text for the same key
2. Back-translate the non-EN value to English via Bridge `dispatch_json` (model: `qwen3-coder-cpu`)
3. Compute embedding of both strings via `nomic-embed-text`
4. `cosine_similarity(back_translated, original_en)` → score in [0, 1]
5. Also apply an English-residue regex: `\b(the|click|submit|save|next|back|cancel|yes|no|login|sign|email|password)\b` (case-insensitive) — if ≥2 hits inside the non-EN value, flag
6. `flag_suspect` = `similarity < 0.80 OR english_residue_hits >= 2`

Update `translations.last_semantic_review_at = NOW()` regardless. If suspect, write a row to `translation_gaps` with `gap_type='quality_suspect'` and `confidence=similarity`.

Skip very short strings (< 10 chars) — signal-to-noise too low for this pass.

### Shared output schema

New migration:

```sql
CREATE TABLE translation_gaps (
  id              SERIAL PRIMARY KEY,
  source          VARCHAR(100) NOT NULL,
  gap_type        VARCHAR(30)  NOT NULL,    -- missing | untagged | quality_suspect
  language        VARCHAR(5),               -- NULL for untagged
  key             VARCHAR(500),             -- NULL for untagged
  file_path       VARCHAR(500),
  line_number     INTEGER,
  snippet         TEXT,
  suggested_key   VARCHAR(500),
  confidence      NUMERIC(3,2),
  status          VARCHAR(20) DEFAULT 'open', -- open | routed | resolved | wontfix
  task_id         INTEGER,                   -- FK unified_tasks when routed
  created_at      TIMESTAMP DEFAULT NOW(),
  resolved_at     TIMESTAMP,
  UNIQUE (source, gap_type, language, key, file_path, line_number)
);
CREATE INDEX idx_gaps_status   ON translation_gaps(status);
CREATE INDEX idx_gaps_source   ON translation_gaps(source);
CREATE INDEX idx_gaps_language ON translation_gaps(language);

ALTER TABLE translations
  ADD COLUMN IF NOT EXISTS last_semantic_review_at TIMESTAMP;
```

UPSERT on the UNIQUE constraint — re-scanning same file is idempotent.

## Generation, Confidence Gate, Dept HQ Routing

### For `missing` gaps

1. Load EN source text from `translations` where `language='en'` and `key = gap.key`
2. Check `translation_memory` for `source_text` match on the EN text — include any matches as glossary priming
3. Call Bridge `dispatch_json`:
   - Model: `qwen3-coder-cpu`
   - Prompt enforces JSON response: `{"translated": "...", "confidence": 0.0-1.0, "notes": "..."}`
   - Glossary entries injected into system prompt
4. Final confidence = `min(self_confidence, semantic_similarity_with_backtranslation)`
5. Write to `translations` with `source='ai_generated'`, `status` per the gate below
6. UPDATE `translation_gaps.status='resolved'` on success

### For `untagged` gaps

These require TEMPLATE EDITS, not DB writes. Flow:
1. Call Bridge to generate: suggested key name + extracted English text
2. Create a `unified_task` under "Platform Translation Coverage" project:
   - Title: `[untagged] <source> <file>:<line> — "<snippet>"`
   - Body: suggested key, current HTML line, proposed replacement
   - Assigned to: C.O.D.E.X. (Documentation & Knowledge)
   - Priority: 6
   - Type: implementation
3. Human merges via template edit (out of band).

### For `quality_suspect` gaps

1. Re-generate the translation (same as `missing` flow, but overwriting existing value)
2. Re-run the semantic check
3. If new version passes: UPDATE `translations` with `source='ai_regenerated'`, set `translation_gaps.status='resolved'`
4. If still fails: route to human review (same as confidence < 0.60 path)

### Confidence gate

| Final confidence | Action |
|-----------------|--------|
| ≥ 0.85 | `translations.status='approved'` — goes into next bundle export |
| 0.60 – 0.85 | `translations.status='pending_review'` + create unified_task (Priority 6, C.O.D.E.X.) |
| < 0.60 | `translations.status='pending_review'` + task (Priority 8) + Telegram notify admin |
| Any `quality_suspect` (unless regen succeeds) | Always routes to human review |

### Dept HQ routing

- **Department**: Documentation & Knowledge (director: C.O.D.E.X.)
- **Project home**: new project "Platform Translation Coverage" (P7, feature), auto-created on first run
- **Task format**:
  - Title: `Review [lang] translation for [source]: '[snippet first 60 chars]'`
  - Description: key, gap_type, suggested/current translation, confidence, file/line pointer, deep-link to Consciousness Languages tab
  - Priority: 6 (normal) or 8 (low-confidence / suspect)
  - Type: review
  - Effort: tiny

Task assignment uses the standard Dept HQ assignment pattern (agent_dispatch). C.O.D.E.X. sees pending reviews in its queue.

### Cost control

Nightly cap: `TRANSLATION_NIGHTLY_CAP=5000` Bridge calls per night (env-configurable). If hit, remaining gaps stay `open` for next night. Overflow count logged + admin Telegram notified.

## P.R.O.B.E. Verification (Pass 4, post-generation)

New QA suite: `translation_coverage` registered via existing `qa_suites/` pattern.

Runs after the generation pass each night. Per (source, language):

1. Playwright opens the product homepage + 2-3 high-traffic pages (configured per source)
2. Switches language via the product's lang selector
3. Screenshots the viewport
4. Runs Tesseract OCR on the screenshot → extracts text
5. Runs language detector (e.g., `langdetect` Python package) on the extracted text
6. If `detected_language == 'en'` but target language is non-EN → flag a `quality_suspect` gap for that `(source, lang, page)` + attach the screenshot ID
7. Optional visual diff against last night's screenshot of same lang — flag if layout metric delta > 15% (e.g., Arabic RTL not applied)

Output: written to `qa_results` (existing table) + `translation_gaps` (for findings). Per-product-per-language score surfaced as "OCR coverage".

Scope discipline: only 3-5 pages per product. Full-product visual regression is Project #239 territory.

## Scheduling

New agent_loop job registered in `services/fleet_jobs.py`:

```python
scheduler.add_job(
    with_ctx(run_translation_coverage_scan),
    trigger=CronTrigger(hour=2, minute=0),
    id="translation_coverage_scan",
    name="Agent Loop: Translation Coverage Scan",
    replace_existing=True,
)
```

Sequence inside `run_translation_coverage_scan`:
1. Pass 1 — tagged scanner across all 47 sources
2. Pass 2 — untagged scanner across same
3. Pass 3 — semantic quality on stale rows (older than 30 days)
4. Generate for `missing` (capped at `TRANSLATION_NIGHTLY_CAP`)
5. Regen for `quality_suspect`
6. Route low-confidence to Dept HQ
7. Export `translations.json` bundles for every source with a bundle path
8. Pass 4 — P.R.O.B.E. QA suite `translation_coverage`
9. Emit admin Telegram summary with coverage deltas

Manual trigger: "Scan Now" button in Consciousness Languages tab POSTs to `/api/translations/full-scan`. `@admin_required` + rate-limited to once per 15 min. Enqueues the same function in a background thread.

Also add `JOB_DEPARTMENT_MAP["translation_coverage_scan"] = "Documentation & Knowledge"` in `ai_bridge/agent_loop.py`.

## Error Handling

| Failure mode | Behavior |
|--------------|----------|
| Source directory doesn't exist | Log warning, skip, continue |
| Bridge dispatch fails for a language | Leave `translation_gaps` row `status='open'` for next night; if ALL Bridge calls fail, send infra alert |
| Playwright crashes for one page | Capture traceback, skip page, continue |
| `translation_gaps` UPSERT conflict | Handled by UNIQUE constraint — idempotent |
| Nightly cap exceeded | Log overflow count + admin Telegram with tally |
| C.O.D.E.X. task queue stuck | Weekly reminder Telegram if any task > 7 days old |
| `translations.json` export fails | Log error, continue; next night retries |

Every step wraps in `try/except` with `_log_cycle(... items_failed=N)` so failures show in Department HQ activity feed, not silent.

## Admin Observability

New "Coverage Health" card in Consciousness Languages tab:

- Per-product grid: rows = sources (11 external + 36 internal), columns = 8 languages, cell = coverage % + last-scanned timestamp
- Cell click → drill into gap list filtered by `(source, language)`
- Top banner: "Last full scan: 2026-04-18 02:07 — 24,738 keys checked, 142 gaps auto-fixed, 18 routed to review"
- Download CSV of current gap list (per source or all)

## Build Order

Translated into the implementation plan:

1. Migration 320 — `translation_gaps` table + `translations.last_semantic_review_at` column
2. Extend `EXTERNAL_SCAN_SOURCES` in `language_routes.py` (8 new entries)
3. New `translation_scanners/untagged_scanner.py` (BS4 walker) + unit tests
4. New `translation_scanners/semantic_scanner.py` (back-translate + cosine) + unit tests
5. Refactor `language_routes.py` to use the scanner classes and write to `translation_gaps`
6. Add confidence gate + Dept HQ task creation to generation path
7. Coverage Health dashboard (consciousness template + JS)
8. `/api/translations/full-scan` manual trigger endpoint
9. `run_translation_coverage_scan` orchestrator + scheduler registration in `services/fleet_jobs.py`
10. `JOB_DEPARTMENT_MAP` update for the new job
11. New P.R.O.B.E. suite `translation_coverage` (Playwright + OCR)
12. Admin Telegram summary notification

## Testing

- **Unit tests** — each scanner class has golden-HTML tests (sample input → expected gap rows).
- **Integration test** — run the orchestrator against a controlled fixture source, assert rows in `translation_gaps` + `translations` + `unified_tasks`.
- **P.R.O.B.E. suite** — the `translation_coverage` QA suite itself is also the integration test for the live pipeline after deploy.
- **Manual verification** — after first nightly run, spot-check at least one new product's coverage in the Languages tab + confirm bundle export lands in the product's `data/translations.json`.

## Out of Scope (tracked as follow-ups)

- Auto-apply `data-i18n` tags via F.O.R.G.E. PR (requires separate trust gate)
- Per-language agents with cultural nuance personalities
- Fleet-distributed scanning
- Support for languages beyond en/fr/es/pt/de/zh/ar/he
- Translation of dynamic content (chat messages, user-generated content)
