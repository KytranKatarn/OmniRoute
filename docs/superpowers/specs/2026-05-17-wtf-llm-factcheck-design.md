# WTF "Full Cast at 100%" Backlog Workers + LLM Analysis Caching

**Date:** 2026-05-17
**Status:** Design — APPROVED, scaffolding now (no LLM runs)
**Trigger:** User wants every WTF agent at 100% coverage and LLM deep-analysis cached per-article so the consumer's "Analyze" click returns instantly.

## Current state vs goal

Read straight off the activity page (`https://what-the-fact.com/activity`):

| Agent | Now | Gap | LLM? | Notes |
|---|---|---|---|---|
| F.A.C.T. (ingest) | 100% (9,751) | 0 | n/a | RSS pull, no LLM |
| B.I.A.S. (bias) | 100% (9,751) | 0 | heuristic | Could upgrade to LLM later (out of scope) |
| D.R.A.F.T. (summary) | 100% (7,598 clusters) | 0 | extractive | Could upgrade to LLM later (out of scope) |
| **V.E.R.I.F.Y.** (fact-check) | 43% (4,194) | **5,557** | ✅ LLM | Heuristic today; LLM upgrade for backlog |
| **L.O.C.A.L.** (geo) | 40% (3,977) | **5,774** | partial | Heuristic catches obvious locations; LLM for the rest |
| **I.N.K.** (cluster) | 77% (7,598) | **2,153** | ❌ no | Jaccard similarity — CPU only, cheap |
| **LLM Analyzed** | 9% (963) | **8,788** | ✅ LLM | The headline metric — `articles.ai_analyzed=true` |

`orchestrator.pick_priority_articles()` deliberately rate-limits LLM Analyzed to ~20/cycle for cost control (only priority-scored articles cross the bar). The 9% gap is by design, not a bug. Backlog workers explicitly bypass the priority filter to reach 100%.

## Architecture decisions

1. **Storage for LLM deep analysis**: new table `wtf.llm_analyses(article_id FK, sections_json JSONB, model VARCHAR, dispatched_at, completed_at)`. Flexible — multiple analysis types per article in `sections_json`; reads are O(1) per article via FK. Sets `articles.ai_analyzed=true, ai_analyzed_at=NOW()` on success so the activity page counter updates immediately.

2. **Hub side: add one new task type**. The current wtf-hub endpoint at `/tools/wtf-hub/api/analyze` supports `bias | factcheck | geo`. Add `deep_analysis` — a single LLM call that returns `{bias_summary, key_claims, geo_entities, editorial_take}` in one JSON, routed to V.E.R.I.F.Y. (or whichever News & Media director the dispatcher picks). Saves us 3 round-trips per article.

3. **VPS side: 4 workers in `wtf-ingest/ingest/`**. All thread-based, all gated by env kill switches, all default OFF. Reuse `ai_dispatcher.analyze()` for hub calls — already mesh-routed, auth-tokened, timeout-bound.

4. **Priority bypass**. Backlog workers DO NOT call `orchestrator.pick_priority_articles()`. They process every article missing the relevant analysis in `published_at DESC` order. This is the explicit "100% coverage" lever.

5. **Caching contract** (the "instant click" goal):
   - User clicks "Analyze" on an article
   - Consumer reads `wtf.llm_analyses WHERE article_id=$1`
   - If row exists → return it immediately (no LLM call)
   - If row missing → show "AI analysis pending" badge, fall back to existing heuristic, queue for next worker cycle
   - Per-tier visibility (gated in consumer, not at the worker layer):
     - `anonymous / free` → counts only ("AI analysis available — sign up to view")
     - `starter` → bias_summary + key_claims, deducts from unlock_count
     - `pro / kytran` → full sections_json, no deduction

## Files to create

### Migration

`migrations/008_llm_analyses.sql`
```sql
CREATE TABLE IF NOT EXISTS wtf.llm_analyses (
    id              SERIAL PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    sections_json   JSONB NOT NULL,
    model           VARCHAR(64) NOT NULL,
    dispatched_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP,
    UNIQUE (article_id, model)
);
CREATE INDEX IF NOT EXISTS idx_llm_analyses_article ON wtf.llm_analyses(article_id);
CREATE INDEX IF NOT EXISTS idx_llm_analyses_completed ON wtf.llm_analyses(completed_at DESC) WHERE completed_at IS NOT NULL;
```

### Workers (kill-switched, default OFF)

| File | Backlog target | Default OFF env var | Cost |
|---|---|---|---|
| `ingest/factcheck_backlog_worker.py` | V.E.R.I.F.Y. gap (5,557 articles) | `WTF_FACTCHECK_BACKLOG_ENABLED` | ~46h hub |
| `ingest/geo_backlog_worker.py` | L.O.C.A.L. gap (5,774, some no-geo) | `WTF_GEO_BACKLOG_ENABLED` | mix heuristic + LLM |
| `ingest/cluster_backlog_worker.py` | I.N.K. gap (2,153) | `WTF_CLUSTER_BACKLOG_ENABLED` | CPU only, fast |
| `ingest/llm_analysis_backlog_worker.py` | `ai_analyzed=false` (8,788) | `WTF_LLM_BACKLOG_ENABLED` | ~73h hub |

Each worker:
- Reads env config (`*_BATCH_SIZE`, `*_DISPATCH_SLEEP_SEC`, `*_MAX_AGE_DAYS`, `*_MAX_RUNS_PER_NIGHT`)
- Loops batch → dispatch → write → sleep
- Hard cap per process lifetime
- Stops itself if kill switch flips false
- Logs to `wtf.audit_trail` on success/fail

### Hub-side change

`platform_v2/tools/wtf_hub/routes.py`: add `"deep_analysis"` to the `capabilities` dict + a `prompts["deep_analysis"]` template that asks for the four-section JSON output. Routes via DHQ `capability="deep_analysis"` → News & Media → V.E.R.I.F.Y. (or whoever the coordinator picks).

### Worker entrypoint wiring

`ingest/run.py` already exists. Add a `start_backlog_workers()` call that spawns each worker as a daemon thread IFF its env flag is true. Workers stop on SIGTERM gracefully.

## Build order (each step independently kill-switched)

1. **Tonight (no LLM runs)**: migration 008 + 4 worker files (env defaults OFF) + hub `deep_analysis` task. Commit, PR, merge. Deploy to VPS via `scp + docker compose up -d --build`.

2. **Smoke test (you flip 1 switch)**: enable `WTF_CLUSTER_BACKLOG_ENABLED=true` first — no LLM cost, just CPU Jaccard. Verify it closes the I.N.K. 2,153 gap. ~30 min.

3. **Smoke test #2 (you flip 1 switch)**: enable `WTF_LLM_BACKLOG_ENABLED=true` with `MAX_RUNS_PER_NIGHT=1`. Verifies hub round-trip + `wtf.llm_analyses` write + activity-page counter increments by 1. ~1 min.

4. **First overnight run**: enable `WTF_LLM_BACKLOG_ENABLED=true` with `MAX_RUNS_PER_NIGHT=127, MAX_AGE_DAYS=1`. Processes last-24h backlog (~1h). Wakes up Kytran with first batch of cached analyses to review.

5. **Multi-night ramp**: bump to `MAX_AGE_DAYS=7` then `MAX_AGE_DAYS=30` then no cap. Track activity-page % climbing.

6. **(Separate session)** Activity page tier-gating UI + unlock-count plumbing.

## Constraints honored

| Rule | Where in design |
|---|---|
| DHQ owns dispatch (ADR-013) | All workers go through `ai_dispatcher.analyze()` → wtf-hub endpoint → `dispatch()` |
| Mesh-only transport | `WTF_HUB_URL=http://100.64.0.4:3000` already in container env; workers reuse |
| VPS deploy via scp + rebuild | New file list documented for deploy step |
| Default OFF kill switches | Every worker has its own env flag, default false |
| Hard caps | Per-night max, max-age, batch size — all env-driven |
| Owner identity | Bearer token already provisioned (`WTF_HUB_TOKEN`), no new auth |
| Single writer per table | Each worker owns one analysis stage |
| LLM-only via Bridge | Workers call hub HTTP, never direct Ollama |

## Open questions deferred

- LLM upgrade for the existing 9,751 heuristic bias_scores (separate scope)
- LLM upgrade for the existing 7,598 extractive summaries (separate scope)
- Anti-abuse for activity page anonymous views (Tier 2 work)
- M.A.V.E.N. (Media Hub agent) — not actually in the activity-page cast, separate domain
- Reactivating Starships 245/246 to parallelize the LLM backlog (would cut ~73h to ~25h)

## Risk register

| Risk | Mitigation |
|---|---|
| Worker overshoots, runs millions of LLM calls | `MAX_RUNS_PER_NIGHT` hard cap per process lifetime + env kill switch |
| Hub overloaded by 4 workers | Hub's existing `_ANALYZE_INTERVAL` rate limiter applies; workers honor `retry_after` |
| Bad JSON from LLM breaks downstream | sections_json is JSONB — invalid parse → row marked with `model='ERROR'` and skipped on retry |
| Worker crashes leave articles in limbo | `completed_at IS NULL` rows can be retried; no `ai_analyzed=true` flip until row complete |
| Container restart kills workers | Workers are daemon threads; will resume on next container start if env still ON |
| Hub DHQ dispatcher routes to wrong agent | Capability `deep_analysis` registered explicitly in CAPABILITY_DEPARTMENT_MAP → News & Media |
