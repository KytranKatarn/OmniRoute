# Two-tier LLM Design (Task #2943)

**Status:** Design — not yet implemented
**Author:** Claude / 2026-05-17
**Tracking:** Task #2943, WTF project #341

---

## Problem

The WTF ingest pipeline is **single-tier hub-only** today. `ingest/ai_dispatcher.py` posts every bias / fact-check / geo task to `WTF_HUB_URL/tools/wtf-hub/api/analyze` via mesh. Symptoms:

1. **Hub-pinned latency.** A 90s `WTF_HUB_TIMEOUT` per call. With ~388 articles/cycle and ~6 tasks per article, a 5% timeout rate alone wedges the cycle.
2. **Rate-limit cascades.** When hub returns `rate_limited:true`, the article waits a full cycle. Backlog grows.
3. **All-or-nothing quality.** Every article goes through the same qwen2.5:7b prompts whether it's a syndicated wire blurb or a long investigative piece.
4. **Bottleneck on the big model.** 9,245 articles are LLM-pending right now (activity-page proxy), most stuck behind qwen2.5:7b cycles.

## Constraint: cluster-arch mandate

**ALL inference goes through Department HQ.** No direct Ollama calls from any module, ever (KB #263641, feedback_never-direct-ollama.md, ADR-013). The two-tier mechanism must respect this — "local VPS fallback" in the original task title is reframed below as **hub-side fast capability via DHQ**, optionally dispatched to outpost-us by the fleet router.

## Proposal

Add a **hub-routed quick tier** alongside the existing full tier. Both go through DHQ dispatch. The gate decides which articles need the full tier.

```
┌───────────────────────────────────────────────────────────────┐
│ wtf-ingest cycle (every 30 min, outpost-us)                   │
└───────────────────────────────────────────────────────────────┘
       │
       ▼
  fetch + canonicalize
       │
       ▼
  ┌─────────────────────────────┐
  │ Tier 1 — quick_v1           │  capability=bias_quick / factcheck_quick / geo_quick
  │ (always runs)               │  DHQ → small model (qwen2.5:1.5b) on hub OR outpost-us
  │                             │  ~3-8s/article via mesh, no rate limit
  └─────────────────────────────┘
       │ result.gate_to_full?  ── no ──▶ done (analysis_tier='quick_v1')
       │ yes
       ▼
  ┌─────────────────────────────┐
  │ Tier 2 — full               │  capability=bias_analysis / fact_check / geo_extraction
  │ (selective)                 │  DHQ → qwen2.5:7b / mistral:7b on Starship-246 or hub
  └─────────────────────────────┘
       │
       ▼
  bias_scores / fact_checks / geo / summaries
```

### Capabilities

New entries in `CAPABILITY_DEPARTMENT_MAP` (or the equivalent registration on hub):

| Capability | Tier | Dept routing | Default model | Notes |
|---|---|---|---|---|
| `bias_quick` | 1 | News & Media → B.I.A.S. (or sibling) | qwen2.5:1.5b | band only (5 labels), no rationale |
| `factcheck_quick` | 1 | News & Media → V.E.R.I.F.Y. | qwen2.5:1.5b | claim extraction only, no verdict |
| `geo_quick` | 1 | News & Media → L.O.C.A.L. | qwen2.5:1.5b | Canadian provinces only (existing L.O.C.A.L. scope) |
| `bias_analysis` | 2 | (existing) | qwen2.5:7b | band + score + rationale + trigger phrases |
| `fact_check` | 2 | (existing) | qwen2.5:7b | claims + per-claim verdict + sources |
| `geo_extraction` | 2 | (existing) | qwen2.5:7b | country_code + non-Canadian regions |

`prefer_node` hint can be passed by wtf-ingest so DHQ's fleet router prefers outpost-us (the same VPS the ingest runs on) — it minimises hub-load contribution AND keeps inference physically near the data. DHQ remains the sole authority deciding final routing.

### Tier-1 → Tier-2 gate

Tier 1 returns a structured response with `gate_to_full` set true when ANY of:

- `tier1.bias_band ∈ {left, right}` — extremes get a full review with rationale
- `tier1.claims_extracted >= 3` AND article body length >= 1500 chars — substantive
- Article source has `bias_lean = 'right'` OR is Indigenous press — known reviewer-attention buckets
- Article in a cluster of size >= 4 (trending)
- User-explicit `force_tier_2` via consumer "Deep Dive" click

Tier-1-only articles get bias band + claim count + geo — enough for the consumer page to render correctly. Upgradeable later via Tier 2.

### Fallback rules (Tier 2)

Tier 1 failures are exceptional (DHQ-side); on failure log and continue. Tier 2 failure handling:

| Hub status | Action |
|---|---|
| `ok` + valid result | Use Tier 2 result, record `tier2_at` |
| `rate_limited` | **Retain Tier 1 result**, re-queue for Tier 2 next cycle, mark `tier_2_pending=true` |
| `failed` (timeout / 5xx / dispatcher error) | **Retain Tier 1 result**, mark `tier_2_failures += 1`. After 3 consecutive failures, accept Tier 1 as canonical (`analysis_tier='quick_v1+failed'`) until next ingest update. |

The pipeline never blocks waiting for Tier 2. Consumer can show "Tier 1 — deep review pending" badging.

## Implementation sketch

### Hub side (platform_v2)

- New file: `platform_v2/tools/wtf_hub/quick_routes.py` (or extend existing wtf_hub/routes.py).
  Adds `/tools/wtf-hub/api/analyze-quick` endpoint that dispatches `bias_quick` / `factcheck_quick` / `geo_quick` via `dispatch(capability=..., prompt=..., context={'prefer_node':'outpost_us_001'})`.
- New entries in `services/department_coordinator.CAPABILITY_DEPARTMENT_MAP` for the three `*_quick` capabilities → News & Media department.
- Pre-warm `qwen2.5:1.5b` on outpost-us via existing fleet model-warm mechanism (already in scope of the resource-aware routing path).

### VPS side (what-the-fact)

- `ingest/quick_analyzer.py` — thin HTTP client: POST to `/tools/wtf-hub/api/analyze-quick` with `{task, article_id, title, body}`. Mirrors `ai_dispatcher.analyze_with_status()` contract (returns `{result, status}`).
- `ingest/tier_router.py` — single entry point `analyze_tiered(task, article_id, title, body, source_slug, force_tier=None) -> AnalysisResult`. Runs Tier 1, applies gate, optionally calls existing `ai_dispatcher.analyze_with_status()`, returns merged result.
- `ingest/llm_analysis_backlog_worker.py` / `factcheck_backlog_worker.py` / `geo_backlog_worker.py` — switch per-article dispatch to `tier_router.analyze_tiered()`.

### Schema

`migrations/013_two_tier_columns.sql`:

```sql
ALTER TABLE wtf.articles
  ADD COLUMN IF NOT EXISTS analysis_tier VARCHAR(16) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS tier1_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS tier2_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS tier2_failures INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tier2_pending BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_articles_tier2_pending
  ON wtf.articles(tier2_pending) WHERE tier2_pending = TRUE;
```

`analysis_tier` values: `pending`, `quick_v1`, `quick_v1+full`, `quick_v1+failed`.

### Config (.env)

```bash
WTF_TIER1_ENABLED=true
WTF_TIER1_PATH=/tools/wtf-hub/api/analyze-quick
WTF_TIER1_TIMEOUT=15
WTF_TIER2_GATE_MIN_CLAIMS=3
WTF_TIER2_GATE_MIN_BODY_CHARS=1500
WTF_TIER2_MAX_RETRIES=3
```

`WTF_HUB_URL` stays as-is (mesh: `http://100.64.0.4:3000`). Both tiers POST to the same hub.

### Tier-1 response contract (strict)

```json
{
  "tier": "quick_v1",
  "model": "qwen2.5:1.5b",
  "node": "outpost_us_001",
  "bias": { "band": "center-left", "confidence": 0.6 },
  "claims": ["claim1", "claim2", "claim3"],
  "geo": { "province_code": "ON", "country_code": "CA" },
  "gate_to_full": true,
  "duration_ms": 4231
}
```

Bias band ∈ `{left, center-left, center, center-right, right}`. Confidence 0-1. Claims ≤ 3 short strings. Geo follows existing column conventions. `gate_to_full` is the explicit hand-off signal.

**Reject** Tier 1 responses that don't parse or have bias band outside the fixed set — log `tier1_parse_failed=true` and proceed directly to Tier 2. Don't poison the DB with garbage.

## Migration plan

| Phase | Scope | PRs | ETA |
|---|---|---|---|
| **A** | Migration 013 + register `*_quick` capabilities on hub + `/api/analyze-quick` endpoint with no callers wired. Verifies the DHQ path returns sub-8s responses for qwen2.5:1.5b. | 1 platform PR | ~2h |
| **B** | `quick_analyzer.py` + `tier_router.py` + wire `llm_analysis_backlog_worker`. Leave fact-check / geo on single-tier for one cycle to A/B. | 1 wtf PR | ~2h |
| **C** | Wire fact-check + geo workers. Update activity page to show `analysis_tier` distribution + tier2_pending count. | 1 wtf PR | ~1.5h |
| **D** (opt) | Consumer "Deep Dive" → force Tier 2 upgrade on click. | 1 wtf PR | ~1h |

## Open questions

1. **prefer_node hint behaviour.** DHQ's fleet router today scores nodes by `current_load / fail_rate / staleness` and may override `prefer_node`. For Tier 1 we want it to *strongly* prefer outpost-us — verify the existing `node_preference` field in dispatch metadata is honored when capacity is available.
2. **qwen2.5:1.5b warm guarantee.** Outpost-us has qwen2.5:1.5b in `/api/tags` but may not be loaded. Need either `OLLAMA_KEEP_ALIVE=15m` on outpost-us OR a seed-load via the existing `services/model_service.ensure_model_ready()` on a scheduled job.
3. **Cluster-arch compliance check.** Hub-side change adds three new entries in `CAPABILITY_DEPARTMENT_MAP`. Must NOT bypass DHQ. The new `/api/analyze-quick` endpoint is the WTF-facing wrapper, but internally calls `dispatch()` — no shortcuts.
4. **Concurrency.** With ~388 articles/cycle and ~5s per Tier 1 call, single-thread Tier 1 takes ~32 min — borderline for a 30-min cycle. Parallelize via thread pool in `ai_dispatcher`-style (same pattern as PR #801 `scout_body_backlog_worker`, configurable `WTF_TIER1_WORKERS=4`). Concurrency is bounded by hub-DHQ throughput and outpost-us VRAM/RAM headroom.
5. **Cost.** Both tiers use own Ollama (no cloud). Win is latency + reliability, not $.
6. **True offline fallback (out of scope).** If hub-DHQ itself is unreachable, the VPS would need a local dispatcher shim to serve Tier 1. That's a separate architectural conversation — would require a mini-DHQ on each outpost. Not addressed here; today's design assumes mesh to hub is up.

## Test plan

- [ ] Migration 013 applies cleanly on outpost-us
- [ ] `dispatch(capability='bias_quick', ...)` on hub returns a parseable response in < 8s with a sample 1500-char article
- [ ] `prefer_node=outpost_us_001` honored — verify via `task_execution_log.node_used_id`
- [ ] Gate logic: trending cluster (size ≥ 4) → `gate_to_full=true`; syndicated wire blurb → `gate_to_full=false`
- [ ] Hub rate-limit simulation: confirm `tier2_pending=true` set, retry on next cycle
- [ ] Activity page shows `analysis_tier` distribution (target: Tier-1-only majority, Tier-1+full ~30%)
- [ ] No regression in `wtf.bias_scores` / `wtf.fact_checks` row counts after Phase C lands

## Out of scope

- Direct Ollama bypass on VPS (violates cluster-arch mandate — see KB #263641)
- Streaming Tier 1 inference (single-shot blocking is fine for ~5s calls)
- Cross-VPS Ollama fleet for non-WTF products (gov-watch / civic-watch / etc. could adopt the same pattern later as separate tasks)
- Replacing extractive summarizer (still in scope of original #2912 LLM upgrade, separate work)
- VPS-local dispatcher shim for hub-down scenarios (separate architectural decision)

---

## Decisions needed before implementation

1. **Tier-1 model on hub:** `qwen2.5:1.5b` (faster, lower quality) vs `llama3.2:3b` (slower, better instruction-following). **Recommendation: `qwen2.5:1.5b` for Phase A**, sample-evaluate bias-band accuracy at end of Phase B against existing Tier-2 ground truth; swap to `llama3.2:3b` if accuracy < 80%.
2. **Phase boundary:** Ship Phase A (migration + endpoint, no callers) alone as a no-op PR, OR bundle A+B. **Recommendation: separate PRs per phase** — Phase A is verifiable in isolation (just exercise the new endpoint via curl/test harness), keeps review scope tight.
3. **Gate threshold tuning:** Starting values (`MIN_CLAIMS=3`, `MIN_BODY_CHARS=1500`) are guesses. Publish a `tier2_gate_stats` daily summary after Phase B so we can adjust empirically before Phase C lands.
