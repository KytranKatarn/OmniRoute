# K.I.N. Welfare — Enforcement Fix, Display Reconciliation & Shift-Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the K.I.N. welfare system actually enforce token budgets (the throttle is currently blind), make the tab honestly show *why* an agent is at limit and how it recovers, and add a Shift-Calendar subtab showing who is on shift / resting by hour.

**Architecture:** The root defect is a data-keying split: `task_execution_log.agent_id` is NULL on ~48% of rows (fleet-dispatched work logs only `agent_name`), so the enforcement path (`get_welfare_cache`, keyed by `agent_id`) sees ~9–15% of real token usage and never throttles, while the K.I.N. tab (keyed by `agent_name`) shows the true over-limit number. Fix = populate `agent_id` at write time + backfill + make per-agent aggregates resolve agent identity by `COALESCE(agent_id, name-lookup)`. Then reconcile the display to one corrected source, and build the calendar on a new `shift_state_history` table plus a formalized hardware-rest window.

**Tech Stack:** Python 3 / Flask / psycopg2 / Postgres; LCARS JS (`department-hq.js`); APScheduler jobs (`tools/department_hq/jobs.py`); pytest.

---

## Diagnosis (verified live, 2026-06-13)

| Agent | Real 24h (by `agent_name`) | Budget | Actual | Seen by enforcement (`agent_id`) |
|---|---|---|---|---|
| P.R.O.O.F. | 599,219 | 240,000 | **250% over** | undercounted |
| V.E.R.I.F.Y. | 500,198 | 300,000 | **167% over** | 45,165 (15%) |
| B.I.A.S. | 387,045 | 300,000 | **129% over** | undercounted |

- `task_execution_log` last 24h: 13,890 rows, **6,665 (48%) have NULL `agent_id`**, 0 NULL `agent_name`. V.E.R.I.F.Y.: 1,572 rows, only 219 carry `agent_id`.
- Enforcement source `services/agent_service.py:2317` `get_welfare_cache` → `SELECT agent_id, SUM(tokens_used) … GROUP BY agent_id` → undercounts → #4090 throttle (`department_coordinator.score_agent`) and break decisions never fire.
- Display source `tools/department_hq/work_routes.py:~83-99` sums by `agent_name` → shows the true (over-limit) number → tab shows 🔴 "at limit" while nothing acts. **This is the exact reported symptom.**
- The 24h window IS rolling and self-recovers (work ages out; V.E.R.I.F.Y. sheds 41,878 tokens in the next hour). Hours/actions/stress rests DO fire (42 micro_rests / 48h, recovery closing them). Only the **token throttle** is blind. NOTE: `services/agent_load_service.py:64` `real_compute_hours_today` also groups by `agent_id` → hours-rest likely under-fires from the same root cause.
- Root cause of the NULLs: `tools/department_hq/fleet_mesh_routes.py:668` and `tools/department_hq/fleet_node_routes.py:2180` INSERT into `task_execution_log` without `agent_id`. Fleet-dispatched fact-check/bias is the high-volume path → why the News team is 91% NULL.

---

## File Structure

- **Modify** `tools/department_hq/fleet_mesh_routes.py:668` — add `agent_id` (name-lookup subquery) to the insert.
- **Modify** `tools/department_hq/fleet_node_routes.py:2180` — same.
- **Create** `database/migrations/4XX_backfill_tel_agent_id.sql` — one-time backfill of NULL `agent_id` by name (CLI-suffix-aware) + verification.
- **Modify** `services/agent_service.py:2310-2321` — `get_welfare_cache` token subquery → resolve identity via `COALESCE(agent_id, agents.id by name)`, strip ` (CLI)`.
- **Modify** `services/agent_load_service.py:57-75` — `real_compute_hours_today` same identity resolution.
- **Modify** `platform_v2/services/agents/agent_jobs.py:~3826` — `recalibrate_token_budgets` p90 same resolution (so budgets reflect true usage).
- **Modify** `tools/department_hq/work_routes.py:23-271` — expose `limit_dimension` + `token_recovery_eta_min`; single corrected token source.
- **Modify** `tools/department_hq/static/js/department-hq.js:632-943` — dimension-labelled at-limit badge, throttle-vs-rest copy, recovery line, remove 150k fallback; add Shift-Calendar subtab render.
- **Create** `database/migrations/4XX_shift_state_history.sql` — `shift_state_history` table + `hardware_rest_window` config row.
- **Modify** `services/agent_service.py` `transition_shift_state` — append a `shift_state_history` row on every transition.
- **Create** `tools/department_hq/kin_calendar_routes.py` — `GET /api/kin/shift-calendar` (per-agent hourly state grid).
- **Test** `platform_v2/tests/test_welfare_token_keying.py`, `platform_v2/tests/test_kin_shift_calendar.py`.

---

## PART A — Enforcement fix (token + hours keying)  ⚠️ HIGHEST PRIORITY (live: agents 130–250% over budget with no brake)

### Task A1: Populate `agent_id` on the two fleet insert paths

**Files:** Modify `tools/department_hq/fleet_mesh_routes.py:668`, `tools/department_hq/fleet_node_routes.py:2180`.

- [ ] **Step 1:** Read each insert (the current columns are `agent_name, station_code, capability, module_source, success, duration_ms` + `tokens_used`). Confirm the exact column list and the params dict.
- [ ] **Step 2:** Add `agent_id` to the column list, resolved by name (mirror the working pattern at `jobs.py:769`):

```sql
INSERT INTO task_execution_log (agent_id, agent_name, station_code, capability, module_source, success, duration_ms, tokens_used, created_at)
VALUES ((SELECT id FROM agents WHERE name = %(agent_name)s LIMIT 1), %(agent_name)s, …)
```
(Keep `agent_name` too — it's the canonical fallback.)

- [ ] **Step 3:** Grep the remaining insert sites for any other that omits `agent_id` (`social_video_worker.py:396`, `jobs.py` lines 884/1081/1343/1636/2402/2597/2913/3085/3276/3516/3701/3972/4302). For each, verify it sets `agent_id`; if not, apply the same subquery. Report which were already correct.
- [ ] **Step 4:** Deploy (`docker compose restart archie_platform` + the `archie_scheduler` sidecar — both run jobs.py) and verify NEW rows carry `agent_id`:

```sql
SELECT count(*) FILTER (WHERE agent_id IS NULL) AS null_id, count(*) AS total
FROM task_execution_log WHERE created_at > NOW() - INTERVAL '10 minutes';
```
Expected: `null_id` trends to 0 for new rows. **Step 5: Commit** (`fix(dhq): log agent_id on fleet task_execution_log inserts`).

### Task A2: Backfill historical NULL `agent_id`

**Files:** Create `database/migrations/4XX_backfill_tel_agent_id.sql`.

- [ ] **Step 1:** Write the idempotent backfill (CLI-suffix-aware; `agent_name` is unique in `agents`):

```sql
-- Backfill task_execution_log.agent_id from agent_name (handles '<Name> (CLI)' telemetry suffix).
UPDATE task_execution_log t
SET agent_id = a.id
FROM agents a
WHERE t.agent_id IS NULL
  AND a.name = regexp_replace(t.agent_name, ' \(CLI\)$', '');
```

- [ ] **Step 2:** Apply: `docker exec -i archie_database psql -U archie -d archie < database/migrations/4XX_backfill_tel_agent_id.sql` (NOTE: use `-i` for stdin; `docker cp` to the DB container fails — KB #268830).
- [ ] **Step 3:** Verify the undercount is gone for the 24h window:

```sql
SELECT a.name, SUM(t.tokens_used) FILTER (WHERE t.agent_id IS NOT NULL) AS by_id,
       SUM(t.tokens_used) AS total
FROM task_execution_log t JOIN agents a ON a.name = regexp_replace(t.agent_name,' \(CLI\)$','')
WHERE t.created_at > NOW()-INTERVAL '24 hours' AND a.name='V.E.R.I.F.Y.' GROUP BY a.name;
```
Expected: `by_id` ≈ `total` (both ≈ 500k). **Step 4: Commit.**

### Task A3: Make `get_welfare_cache` identity-resolve (defensive, even if a row slips through)

**Files:** Modify `services/agent_service.py:2310-2321`. Test `platform_v2/tests/test_welfare_token_keying.py`.

- [ ] **Step 1: Write the failing test** (drives the real query against seeded rows where `agent_id` is NULL but `agent_name` is set):

```python
def test_get_welfare_cache_counts_tokens_logged_without_agent_id(db_cursor, seed_agent):
    # seed_agent creates agent 'TESTAGENT' id=A with token_limit_per_day=100000
    # insert two tel rows: one WITH agent_id=A (10000 tok), one with agent_id=NULL agent_name='TESTAGENT' (90000 tok)
    insert_tel(agent_id=A, agent_name='TESTAGENT', tokens=10000)
    insert_tel(agent_id=None, agent_name='TESTAGENT', tokens=90000)
    cache = get_welfare_cache()
    assert cache[A]['budget']['token_ratio'] == pytest.approx(1.0, abs=0.01)  # 100000/100000, NOT 0.10
```

- [ ] **Step 2: Run → FAIL** (current code returns 0.10 — only the agent_id=A row). `docker exec archie_platform python3 -m pytest platform_v2/tests/test_welfare_token_keying.py -v`
- [ ] **Step 3: Replace the token subquery** (lines ~2316-2321) so identity is resolved by id OR name:

```sql
LEFT JOIN (
    SELECT COALESCE(t.agent_id, a2.id) AS aid, SUM(t.tokens_used) AS tokens_24h
    FROM task_execution_log t
    LEFT JOIN agents a2 ON a2.name = regexp_replace(t.agent_name, ' \(CLI\)$', '')
    WHERE t.created_at > NOW() - INTERVAL '24 hours'
    GROUP BY COALESCE(t.agent_id, a2.id)
) tk ON tk.aid = a.id
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** (`fix(welfare): get_welfare_cache resolves token usage by id OR name`).

### Task A4: Same identity resolution in `real_compute_hours_today` + `recalibrate_token_budgets`

**Files:** Modify `services/agent_load_service.py:57-75`, `platform_v2/services/agents/agent_jobs.py:~3826`.

- [ ] **Step 1:** In `real_compute_hours_today`, change the `GROUP BY agent_id` / join to the same `COALESCE(agent_id, agents.id by name)` resolution so hours (and the 12h/8h rest triggers) reflect ALL dispatches, not just the ~52% with agent_id. Write a test mirroring A3 asserting hours include name-only rows.
- [ ] **Step 2:** In `recalibrate_token_budgets`, change the per-agent daily-token aggregation to the same resolution so the weekly p90×1.3 reflects true usage (currently undercounts → budgets set near the floor). Keep the existing `clamp_budget_to_band` ceiling.
- [ ] **Step 3:** Run the existing welfare/dispatch suites green. **Step 4: Commit.**

### Task A5: Live verification the throttle now fires

- [ ] **Step 1:** In-container, call `get_welfare_cache()` and assert the News team shows the real ratios:

```bash
docker exec archie_platform python3 -c "import sys;sys.path.insert(0,'/app');from services.agent_service import get_welfare_cache as g;c=g();[print(n, round(c[i]['budget']['token_ratio'],2)) for i,n in [(116,'V.E.R.I.F.Y.'),(378,'P.R.O.O.F.')]]"
```
Expected: V.E.R.I.F.Y. ≥ 1.5, P.R.O.O.F. ≥ 2.0 (was ~0.15).

- [ ] **Step 2:** Confirm `department_coordinator.score_agent` now applies the −1.0 penalty for these agents (a fact_check dispatch routes to the least-over agent / P.R.O.O.F. drains first). Run `tests/test_dispatch_scoring.py` green.

---

## PART B — Display reconciliation (K.I.N. tab honesty)

### Task B1: Endpoint exposes dimension + recovery

**Files:** Modify `tools/department_hq/work_routes.py:23-271`.

- [ ] **Step 1:** For each agent row, compute and add to the JSON: `limit_dimension` (one of `token`/`task`/`hours`/`stress`/`none`, picked by which ratio is highest and ≥ its threshold) and `token_recovery_eta_min` (minutes until the rolling ratio drops back under 1.0, derived from the hourly `history_map` buckets aging out). Reuse the corrected by-name token sum already in the velocity query — make it the single token source the card uses.
- [ ] **Step 2:** Add a test asserting an over-budget agent returns `limit_dimension='token'` and a positive `token_recovery_eta_min`. Run green. **Step 3: Commit.**

### Task B2: Frontend — label the dimension, explain throttle-vs-rest, show recovery, drop the fallback

**Files:** Modify `tools/department_hq/static/js/department-hq.js:782-910, 844-845`.

- [ ] **Step 1:** Replace the bare "⚠ at limit" (line ~782) with the labelled dimension: e.g. `⚠ TOKEN 167% (throttled)` / `⚠ QUEUE FULL` / `⚠ 9.2h on shift`.
- [ ] **Step 2:** For `limit_dimension==='token'`, render a recovery line: `Throttled — recovering as work ages out · back under budget in ~{token_recovery_eta_min}m (no rest needed for tokens)`. This is the key UX fix: it explains *why there is no rest card* for a token-limited agent.
- [ ] **Step 3:** Remove the hardcoded `150000` fallback for `token_limit_per_day` (line ~844). If a budget is missing, show `no budget set` rather than a fake denominator.
- [ ] **Step 4:** Verify in the browser (login as Claude via the archie-platform-login skill → DHQ → K.I.N. tab): an over-budget agent shows the dimension + recovery ETA, and the number matches `get_welfare_cache` (enforcement == display). Screenshot. **Step 5: Commit.**

---

## PART C — Shift-Calendar subtab

> **DECISION LOCKED (owner, 2026-06-13): reactive state-timeline.** A.R.C.H.I.E. agents are reactive (wake-on-demand), so "on shift" is not a planned 9-5 roster — it is *active/deployed* state minus the **hardware-rest window** (8PM–6AM ET, fleet-global) and minus per-agent rest cycles. The calendar is a **state-history timeline**, with the hardware-rest window as the only true "schedule." **NOT building** the optional `agent_shift_schedule` roster table, and the hardware-rest window stays **advisory** (no dispatcher-enforced 8PM–6AM block) — both deferred unless re-requested.

### Task C1: `shift_state_history` table + hardware-rest window config

**Files:** Create `database/migrations/4XX_shift_state_history.sql`.

- [ ] **Step 1:** Create the table:

```sql
CREATE TABLE IF NOT EXISTS shift_state_history (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    reason     TEXT,
    changed_by TEXT,
    changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssh_agent_time ON shift_state_history (agent_id, changed_at DESC);
-- Formalize the hardware-rest window (was an ad-hoc system_config row, fleet_helpers.py:570).
INSERT INTO system_config (key, value) VALUES
  ('welfare:hardware_rest_window', '{"start_hour":20,"end_hour":6,"tz":"America/Toronto","enabled":true}')
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2:** Apply via `psql -i`. Verify table + config row exist. **Step 3: Commit.**

### Task C2: Record transitions

**Files:** Modify `services/agent_service.py` `transition_shift_state`.

- [ ] **Step 1: Write the failing test:** calling `transition_shift_state(agent_id, 'active', 'cooldown', reason='token_throttle')` inserts one `shift_state_history` row with the from/to/reason.
- [ ] **Step 2: Run → FAIL.** **Step 3:** In `transition_shift_state`, after the `agents.shift_state` UPDATE, `INSERT INTO shift_state_history (agent_id, from_state, to_state, reason, changed_by)`. **Step 4: Run → PASS. Step 5: Commit.**

### Task C3: Calendar endpoint

**Files:** Create `tools/department_hq/kin_calendar_routes.py`; register in `tools/department_hq/__init__.py`. Test `platform_v2/tests/test_kin_shift_calendar.py`.

- [ ] **Step 1: Write the failing test** for `GET /api/kin/shift-calendar?date=YYYY-MM-DD` returning `{agents:[{id,name,department,segments:[{start,end,state}], hours_on_shift, rests:[…]}], hardware_rest:{start,end}}`.
- [ ] **Step 2: Run → FAIL.** **Step 3:** Implement: build per-agent hourly segments from `shift_state_history` (fall back to current `agents.shift_state` for agents with no history yet), overlay `agent_rest_cycles` (rest windows) and `real_compute_hours_today` (compute hours), and the `welfare:hardware_rest_window` config. Admin-gated.
- [ ] **Step 4: Run → PASS. Step 5: Commit.**

### Task C4: Calendar subtab UI

**Files:** Modify `tools/department_hq/static/js/department-hq.js` (add a 5th K.I.N. sub-section `calendar` to the existing welfare/workload/work/performance set at line ~639) + the K.I.N. template.

- [ ] **Step 1:** Add the "📅 Calendar" subtab button + a render function `loadKinCalendar()` calling `/api/kin/shift-calendar`.
- [ ] **Step 2:** Render an LCARS hour-grid (rows = agents, 24 hour columns), cells colour-coded: active (teal), deployed (blue), resting (amber), cooldown (grey), off_duty/barracked (dim), hardware-rest band (red overlay 20:00–06:00). Tooltip = state + reason + hours. Use existing LCARS tokens; no new CSS framework.
- [ ] **Step 3:** Browser-verify (login → DHQ → K.I.N. → Calendar). Screenshot. **Step 4: Commit.**

---

## PART D — Welfare-model reevaluation (OWNER DECISIONS — answer before/with build)

These are policy choices the data exposed; each changes the build:

- **Q-D1 (capacity vs throttle):** Fixing the throttle means over-budget specialists (V.E.R.I.F.Y., P.R.O.O.F.) will have work *queue/route to peers* instead of silently over-running. The durable lever is staffing. **Enable `recommend()` `staffing_gap` → auto-propose a hire when a capability has a sustained-over-budget agent and < N backups?** (You already hired P.R.O.O.F.; this automates the signal.)
- **Q-D2 (score volatility):** The welfare/governance score is point-in-time and swings as agents rest (handoff note). **Switch to a time-weighted "agent-hours-within-budget over 24h" score** so the grade is steady and honest?
- **Q-D3 (budget realism):** V.E.R.I.F.Y. true p90 ≈ 1.46M/day vs a 240k band ceiling (clamp_budget_to_band). Is 240k a real cap (→ work must queue / more agents) or should fact-check budgets be raised / the fact-check backlog scoped down (e.g. 90-day window)?
- **Q-D4 (token policy):** Keep throttle-only for tokens, or add a **sustained-overload cooldown** (a longer rest/deprioritization when an agent is >1.0 for H consecutive hours) so a chronically-over agent visibly steps back?
- **Q-C (calendar model):** Reactive state-timeline only (this plan), or also a **planned per-agent roster** (`agent_shift_schedule`: day_of_week, start, end, max_hours)? And should the hardware-rest window be **enforced in the dispatcher** (block dispatch 20:00–06:00) or remain advisory?

---

## Deploy & sequencing notes

- Parts A & B touch hub platform code (volume-mounted) → `docker compose restart archie_platform` AND the `archie_scheduler` sidecar (jobs.py runs there too). DB migrations via `docker exec -i archie_database psql … < file` (KB #268830).
- Recommend shipping **Part A first as its own PR** (live enforcement is broken — agents 130–250% over with no brake), then B, then C; D answers gate C's scope and any D-code.
- Pre-commit runs Black + timezone-drift guardrail — keep new datetimes UTC-aware via `services.time_utils` / `now_utc()`; CronTriggers need `timezone="America/Toronto"`.

## Risks / gotchas

1. **CLI-suffix double-count** — telemetry logs `'<Name> (CLI)'` while `agents.name` is plain; every by-name resolution MUST `regexp_replace(agent_name,' \(CLI\)$','')` (work_routes.py already does `.removesuffix(" (CLI)")`). Tested in A3.
2. **Backfill volume** — `task_execution_log` is large; the A2 UPDATE is a full scan of NULL rows. Run off-peak; it's idempotent and re-runnable.
3. **Hours under-fire** — A4 will make `real_compute_hours_today` jump for fleet agents (they were undercounted) → some may newly cross the 8h/12h rest thresholds. Expected/correct, but watch for a burst of new rests right after deploy.
4. **No shift history before C2** — the calendar is forward-filling; pre-deploy past will be sparse (only current state + rest cycles). Acceptable; note it in the UI ("history from <deploy date>").
5. **Don't re-introduce the 150k fallback** — it masks underfunded agents (B2).

## Self-Review

- Symptom ("at limit, no rest/recovery") → Part A (enforcement keying) + B2 (explains throttle-vs-rest). ✅
- "Not shown properly" → B1/B2 (dimension label, recovery, single source, drop fallback). ✅
- "Token totals changing / recovery?" → documented (rolling window) + surfaced in B1/B2 (`token_recovery_eta_min`). ✅
- Shift calendar → Part C (history table + endpoint + UI), reactive model with hardware-rest window; planned-roster deferred to Q-C. ✅
- Reevaluation → Part D decisions. ✅
- Placeholder scan: Part A/B/C steps carry concrete SQL/code; Part D is explicitly decisions (not code), Q-C gates the optional roster table. No silent TODOs.
