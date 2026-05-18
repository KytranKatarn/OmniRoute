# WTF DHQ Orchestration — Design Spec
**Date**: 2026-05-18
**Status**: Approved
**Project**: What The Fact — Full Fleet Orchestration via Department HQ

---

## Problem

WTF backlog workers run sequentially in a single VPS process (`run.py`). Geo blocks LLM for 25 min. No fleet coordination. Agents on Starship-246, Starship-245, outpost-us are not utilized. DHQ has zero visibility into WTF workloads.

---

## Goal

DHQ APScheduler owns scheduling of all fleet-dispatched WTF jobs. VPS keeps only local CPU work. All 4 fleet nodes (hub, outpost-us, Starship-245, Starship-246) share the load. Fleet tab shows WTF agent activity. Nodes going down fail back to VPS automatically.

---

## Architecture

```
DHQ APScheduler (Hub) — 4 parallel independent jobs
  wtf_llm_analysis_job   → dispatch(bias_analysis)   → V.E.R.I.F.Y. / B.I.A.S.
  wtf_geo_job            → dispatch(geo_extraction)  → L.O.C.A.L.
  wtf_factcheck_job      → dispatch(fact_check)      → V.E.R.I.F.Y.
  wtf_scout_job          → dispatch(web_scraping)    → S.C.O.U.T.

Fleet Escalation per job (smart_router 11-tier + explicit node preference):
  Tier 1: Starship-246  (RTX 3070, qwen2.5:7b — primary GPU)
  Tier 2: Starship-245  (RTX 3070, qwen2.5:7b — secondary GPU, same capability)
  Tier 3: outpost-us    (VPS CPU, qwen2.5:1.5b — degraded but functional)
  Tier 4: Hub           (Quadro M4000, large model fallback)
  Tier 5: VPS ingest    (local worker at low cap=50, always-on slow fallback)

VPS wtf-ingest run.py (every 30 min, unchanged loop):
  run_once()           — RSS ingestion only (primary purpose)
  cluster_backlog      — Jaccard local CPU (DHQ does not touch)
  bias_v2_backlog      — DistilBERT local CPU (DHQ does not touch)
  llm/geo/factcheck/scout — keep at cap=50 as always-on fallback
  (parallel ThreadPoolExecutor — already shipped PR #888)
```

**Duplicate-safety**: All workers check `NOT EXISTS (wtf.llm_analyses WHERE model=X)` before processing. DHQ and VPS can run simultaneously without conflict.

---

## What Already Exists (Do Not Rebuild)

| Component | Status |
|-----------|--------|
| `/tools/wtf-hub/api/analyze` | ✅ Production-ready, routes to B.I.A.S./V.E.R.I.F.Y./L.O.C.A.L. |
| B.I.A.S., V.E.R.I.F.Y., L.O.C.A.L. agent DB rows | ✅ Exist, active |
| VPS backlog workers (6 files) | ✅ Exist, parallel via PR #888 |
| `task_execution_log` WTF tracking | ✅ `module_source='wtf_hub'` already logged |
| APScheduler job pattern | ✅ `with_ctx()` + CronTrigger in `jobs.py` |
| Fleet node heartbeat (Starship-245, -246, outpost-us) | ✅ All online |

---

## Piece 1 — CAPABILITY_DEPARTMENT_MAP (department_coordinator.py)

Add 4 entries routing WTF capabilities to News & Media department:

```python
"bias_analysis":   "News & Media",   # → B.I.A.S. / V.E.R.I.F.Y.
"geo_extraction":  "News & Media",   # → L.O.C.A.L.
"fact_check":      "News & Media",   # → V.E.R.I.F.Y.
"web_scraping":    "News & Media",   # → S.C.O.U.T. (already exists? verify)
```

**File**: `platform_v2/tools/department_hq/services/department_coordinator.py`
**Where**: The `CAPABILITY_DEPARTMENT_MAP` dict (line ~46).

---

## Piece 2 — Agent Skills (agent_skills table)

Ensure each agent has the right skill rows so dispatch scoring works:

| Agent | skill_name | proficiency_level |
|-------|-----------|-------------------|
| B.I.A.S. | bias_analysis | 5 |
| V.E.R.I.F.Y. | fact_check | 5 |
| V.E.R.I.F.Y. | bias_analysis | 4 |
| L.O.C.A.L. | geo_extraction | 5 |
| S.C.O.U.T. | web_scraping | 5 |
| I.N.K. | clustering | 5 |
| D.R.A.F.T. | summarization | 5 |
| F.A.C.T. | data_ingestion | 5 |

**Migration**: `database/migrations/NNN_wtf_agent_skills.sql` — idempotent INSERT ON CONFLICT DO NOTHING.

---

## Piece 3 — DHQ APScheduler Jobs (department_hq/jobs.py)

4 new job functions. Each follows the same pattern:
1. Fetch a batch of pending articles from `wtf` schema (hub DB, same `archie_database`)
2. For each article: call `dispatch(capability=X, prompt=..., module_id='wtf_hub')`
3. Persist result to appropriate wtf table
4. Log summary via `_audit()`
5. On `DispatchResult.success=False` for all articles in batch → log warning (VPS fallback handles it at low cap)

```python
# Staggered to avoid simultaneous Gunicorn pressure:
# :00 — wtf_llm_analysis_job   (heaviest — goes first)
# :05 — wtf_geo_job
# :10 — wtf_factcheck_job
# :15 — wtf_scout_job

scheduler.add_job(
    with_ctx_app(_run_wtf_llm_analysis),
    trigger=IntervalTrigger(minutes=30, timezone="America/Toronto"),
    id="wtf_llm_analysis",
    name="WTF: LLM Analysis Backlog (DHQ)",
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
# repeat for geo, factcheck, scout with start_date offsets of +5/+10/+15 min
```

**Batch size per job**: 25 articles (matches existing worker defaults).
**Cap per cycle**: 500 articles (matches `_MAX_RUNS_PER_NIGHT`).
**DB connection**: Use `get_db_cursor()` from `platform_v2/database.py` — same pool the platform uses.

### Failback logic in each job:

```python
consecutive_failures = 0
for article in batch:
    result = dispatch(capability=X, prompt=...)
    if result.success:
        _persist(article_id, result.response)
        consecutive_failures = 0
    else:
        consecutive_failures += 1
        if consecutive_failures >= 3:
            logger.warning("WTF %s: fleet unavailable after 3 failures, VPS fallback active", job_name)
            break  # VPS low-cap workers handle the rest this cycle
```

No explicit VPS trigger needed — VPS is always running at cap=50 as silent backup.

---

## Piece 4 — VPS run.py Changes

**Remove** from the `ThreadPoolExecutor` backlog pool:
- `llm_analysis_backlog_worker` — moved to DHQ
- `geo_backlog_worker` — moved to DHQ
- `factcheck_backlog_worker` — moved to DHQ
- `scout_body_backlog_worker` — moved to DHQ

**Keep** in VPS (local CPU, DHQ-independent):
- `cluster_backlog_worker` — Jaccard, no fleet dispatch
- `bias_v2_backlog_worker` — DistilBERT, no fleet dispatch
- `llm_analysis_backlog_worker` — **keep at cap=50** as always-on fallback
- `geo_backlog_worker` — **keep at cap=50** as always-on fallback

The VPS fallback workers use the same `NOT EXISTS` DB guard — no duplicate work.

**VPS .env changes**:
```
WTF_LLM_BACKLOG_MAX_RUNS_PER_NIGHT=50   # reduced from 500 — fallback only
WTF_GEO_BACKLOG_MAX_RUNS_PER_NIGHT=50   # reduced from 100
WTF_LLM_BACKLOG_CONCURRENCY=2           # reduced from 8 — DHQ handles the bulk
```

---

## Piece 5 — Fleet Tab WTF Panel

New section in the Fleet tab (after CLUSTER ACTIVITY) showing WTF pipeline agent status:

**API**: `GET /tools/department-hq/api/fleet/wtf-status`

Returns per-agent stats from `task_execution_log`:
```json
{
  "agents": [
    {"name": "B.I.A.S.", "node": "outpost-us", "calls_1h": 892, "avg_sec": 7.3, "last_seen": "2min ago"},
    {"name": "V.E.R.I.F.Y.", "node": "Starship-246", "calls_1h": 187, "avg_sec": 16.9, "last_seen": "5min ago"},
    {"name": "L.O.C.A.L.", "node": "Starship-246", "calls_1h": 145, "avg_sec": 8.0, "last_seen": "3min ago"},
    {"name": "S.C.O.U.T.", "node": "outpost-us", "calls_1h": 212, "avg_sec": 45.0, "last_seen": "1min ago"}
  ],
  "backlog_pct": 16,
  "pipeline_health": "active"
}
```

**UI**: LCARS panel, teal accent, live dot per agent. Node label shows which hardware is active. If a node is down, agent row shows amber with "→ failback" label.

---

## Piece 6 — Agent Node Assignments (Starship-245 + hub)

Ensure Starship-245 and hub are registered as fallback nodes for WTF agents:
- `node_agents` table: add B.I.A.S., V.E.R.I.F.Y., L.O.C.A.L. rows for Starship-245
- DHQ smart_router already handles escalation via heartbeat + capability matching
- No code change needed — just DB rows + model pulls on Starship-245 (qwen2.5:7b, llama3.2:3b)

**Migration**: `NNN_wtf_node_agents_245.sql` — adds node_agents rows for Starship-245.

---

## Build Sequence

| Phase | What | Files | Estimated |
|-------|------|-------|-----------|
| P1 | CAPABILITY_DEPARTMENT_MAP + agent_skills migration | `department_coordinator.py`, `migrations/NNN.sql` | 30 min |
| P2 | DHQ APScheduler jobs (4 jobs) | `department_hq/jobs.py` | 2h |
| P3 | VPS run.py — reduce caps, remove fleet workers | `what-the-fact/ingest/run.py`, `.env` | 30 min |
| P4 | Fleet tab WTF panel | `fleet_node_routes.py`, fleet template | 1.5h |
| P5 | Starship-245 node_agents migration | `migrations/NNN.sql` | 20 min |

**Total**: ~4.5 hours
**Deploy order**: P1 → P2 → hub restart → P3 → VPS deploy → P4 → P5

---

## Coordination with Other Modules

- `max_instances=1` + `coalesce=True` on all 4 jobs — no pile-up
- Staggered start times (+5 min offsets) — spread Gunicorn load
- `WTF_ANALYZE_INTERVAL=5` already set on hub — rate-limits per Gunicorn worker
- Signal pipeline, LinkedIn jobs, other module jobs are unaffected — APScheduler runs them concurrently with WTF jobs since they target different agents and capabilities
- K.I.N. welfare digest + ethics_monitoring run at 02:00-03:00 UTC — WTF jobs run every 30 min throughout the day, no overlap concern

---

## Success Criteria

- [ ] LLM Analyzed climbs from 16% → 100% within 48h of deploy
- [ ] Fleet tab shows 4 WTF agents with live dispatch rates
- [ ] When Starship-246 taken offline, dispatch automatically routes to Starship-245 or outpost-us
- [ ] VPS ingest logs show cluster + bias_v2 running; llm/geo/factcheck/scout at cap=50
- [ ] `task_execution_log` shows `module_source='wtf_hub'` with staggered timing across 4 jobs
