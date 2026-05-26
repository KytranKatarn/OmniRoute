# Session Handoff — 2026-05-26

## What was done this session (latest at top)

### T3167 Phase 2 — C.R.E.E.D. Welfare Alignment (PR #1127, branch: feat/creed-kin-welfare-alignment)

**Problem**: News & Media dept at F/10 ethics — V.E.R.I.F.Y. at 0.90 stress/winding_down while 7 agents sat idle. Root cause: V.E.R.I.F.Y.-B had fact_check at Lv3 only (dispatcher score 1.6 vs Lv5=2.0), and NO overflow bids existed for T3167 to auto-enable.

**Migration 397** (`database/migrations/397_news_media_welfare_alignment.sql`) — applied:
- V.E.R.I.F.Y.-B (id=370): fact_check Lv3→Lv4, add bias_analysis Lv4, classify Lv3
- 8 overflow bids seeded (`enabled=false`, T3167 will auto-enable when queue depth ≥5):
  - V.E.R.I.F.Y.-B: fact_check(p8), fact_check_backlog(p6), bias_analysis(p7), classify(p5)
  - B.I.A.S. (id=49): bias_analysis(p9), bias_quick(p8)
  - L.O.C.A.L. (id=361): geo_extraction(p9), geo_quick(p8)

**`creed_routes.py`** — per-department ethics in `/api/creed/public-stats`:
- `ethics.by_department` array — 17 depts, sorted worst-first
- Each entry: department, score, grade, success_rate, high_stress_agents, avg_stress, welfare_status
- Zero extra DB queries — computed from already-queried welfare+job_health dicts
- Live verified: News & Media = F/10 (correctly worst), Ops = A+/98

**`jobs.py`** — 2 new monitoring jobs:
- Job #130 `_run_token_welfare_monitor` (daily 06:00 ET): flags agents >100k tokens/24h + stress >0.75 → `token_overload_warning` governance_audit_log + Telegram alert
- Job #131 `_run_creed_kin_weekly_digest` (Mon 09:00 ET): 7d ethics score, top-stress depts, top token consumers, overflow events, ≥5x dispatch imbalance → governance_audit_log + Telegram digest

**Dev HQ**:
- ADR #635 (per-dept ethics), ADR #636 (Job #130+#131), ADR #637 (migration 397)
- Task #3233: Surface by_department in creed standalone UI
- Task #3234: Investigate F.A.C.T. token logging gap

**PR #1127** — open at https://github.com/KytranKatarn/archie-platform/pull/1127 — awaiting merge.

**Gotchas**:
- Black pre-commit reformats Python — re-stage + recommit after first attempt
- agent_emotional_state LATERAL subquery pattern (same as fleet fix in #1126) — never direct JOIN (183k+ rows)
- Per-dept ethics formula: `success_rate - (high_stress_agents × 2)`, capped 0-100

---

### T3167 — Dynamic Skill Activation + C.R.E.E.D. Fleet Visibility (PR #1125, MERGED)

**`jobs.py`** — Job #129 `_run_dynamic_skill_activation` (IntervalTrigger 5m, coalesce=True):
- HIGH_WATER=5: enables disabled overflow bids on hot capabilities after K.I.N. welfare gate (stress<0.8 + not in_rest)
- Writes governance_audit_log: overflow_skill_activated / overflow_welfare_blocked / overflow_skill_deactivated
- >5 activations/cycle → request_approval(tier=2) for human oversight
- Registered confirmed: `[DeptHQ] Registered dynamic_skill_activation job (every 5 min, T3167)`

**`creed_routes.py`** — 2 new public endpoints:
- `GET /api/creed/fleet-agents` (60s cache) — 7 nodes, 417 agents ✅ live
- `GET /api/creed/overflow-activations` (30s cache) ✅ live
- Key fix: `node_agents.status = 'active'` (NOT `is_active` — that column doesn't exist)

**`department-hq.js`** `loadCreed()`:
- Fleet Node Health Grid (green/yellow/red by avg stress, per-node cards)
- Overflow Activation Timeline (10 visible, show-all expands to 50)
- C.R.E.E.D. Institute link → creed.kytranempowerment.com

**Hot-patch** `/mnt/standalone/kytran-creed/kytran_creed/services/platform_stats.py`:
- URL: `192.168.1.200` → `100.64.0.4` (mesh IP, canonical)
- Applied: `docker cp` + `docker compose restart creed` ✅

---

## What to do next

### Immediate (after PR #1127 merges)

1. **Restart scheduler** to register Job #130 + #131:
   ```bash
   docker compose restart archie_scheduler
   docker logs archie_scheduler --since 60s | grep -E 'token_welfare|creed_kin_weekly'
   ```

2. **Verify T3167 overflow activation**: Wait 5 min after scheduler restart, check:
   ```sql
   SELECT event_type, agent_id, reason, outcome, timestamp
   FROM governance_audit_log
   WHERE event_type = 'overflow_skill_activated'
   ORDER BY timestamp DESC LIMIT 10;
   ```
   V.E.R.I.F.Y.-B fact_check bid should auto-activate if `cluster_work_queue` has ≥5 pending fact_check jobs.

3. **Surface `ethics.by_department` in creed standalone** (Task #3233):
   - File: `/mnt/standalone/kytran-creed/kytran_creed/templates/welfare.html`
   - API already returns `welfare.ethics.by_department` — add a table/grid below the global score
   - Deploy: `docker cp` + `docker compose restart creed`

4. **Investigate F.A.C.T. token logging gap** (Task #3234):
   - F.A.C.T. shows 0 tokens despite 198 dispatches — check `task_execution_log.tokens_used` for News & Media capabilities

### Near-term

5. **T3224** — Satellite node tier (lightweight connect-only mesh clients) — medium effort

6. **4 Dependabot vulnerabilities** on main (1 high, 3 moderate) — review when convenient

7. **Check creed-ai.org** — `ethics.by_department` now powering standalone; confirm it renders after merge + restart

---

## Critical context for next session

- **`agent_emotional_state` is a time-series** — 183k+ rows. Always use `DISTINCT ON (agent_id) ORDER BY agent_id, id DESC` subquery. Never direct JOIN.
- **`node_agents.status = 'active'`** — NOT `is_active` (column doesn't exist)
- **Migration 397 was applied** — overflow bids are in DB. T3167 will auto-enable them. Check governance_audit_log to confirm.
- **Job #130 threshold**: `_TOKEN_DAY_LIMIT = 100_000`, `_TOKEN_STRESS_GATE = 0.75` — tunable constants at top of the relevant section in jobs.py
- **Job #131 imbalance threshold**: ≥5x ratio (max_dispatches/min_dispatches per dept) — also tunable
- **Black pre-commit**: reformats Python on first commit attempt. Always `git add` again before second commit.
- **creed standalone compose**: service=`creed`, container=`kytran_creed`
- **Per-dept ethics formula**: `max(0, min(100, round(success_rate - high_stress_agents * 2)))` — same scale as global score
