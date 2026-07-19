# Spec — Async hire-name Generate (#4969)

**Status:** designed (investigation complete), not yet built. Owner chose the async-flow option.

## Problem
The DHQ Approvals "✨ Generate" name button calls `POST /api/approvals/hire/<id>/suggest-name`
→ `agent_identity_builder.build_identity(capability)` → `agent_name_generator.suggest_name`
**synchronously**. `suggest_name` bounds each dispatch at 20s and retries `MAX_ATTEMPTS=3`, so the
request (and the button) spins **6–23s typically, up to ~60s worst case** (cold model → attempt-1
timeout → fallback; or 3 invalid responses → ~18s → fallback). #2328 already fixed the
always-PORTAL bug + hang-forever (warm `llama3.2:3b`, randomized fallback, per-dispatch bound). The
remaining flaw is the long synchronous wait holding a gunicorn worker thread.

## Hard constraint (why the naive design fails)
`docker-compose.yml` runs archie_platform with **`--workers 4 --threads 8`**. An in-memory job
store BREAKS: the POST (worker A) and the poll GET (worker B) hit different processes. The async job
result **must** live in shared storage (DB), not a module-level dict.

## Design (async flow)
1. **Migration** `NNN_hire_name_jobs.sql`:
   ```sql
   CREATE TABLE IF NOT EXISTS hire_name_jobs (
     job_id UUID PRIMARY KEY,
     hire_id INT,
     capability TEXT,
     status TEXT NOT NULL DEFAULT 'generating',  -- generating | done | error
     result JSONB,
     created_at TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   ```
2. **Service** `services/hire_name_job_service.py`:
   - `create_job(hire_id, capability) -> job_id`: INSERT row (status='generating'); spawn a
     **daemon `threading.Thread`** that (a) calls `signal_calendar_service._ensure_import_paths()`
     FIRST (KB #272154 — dispatch needs it), (b) runs `agent_identity_builder.build_identity`,
     (c) UPDATEs `result` + status. A gunicorn worker stays alive, so the daemon thread survives
     (unlike the `python3 -c` trap KB #270002 — that killed the thread on process exit).
   - `get_job(job_id) -> {status, result}`.
   - `prune_old()` — delete rows > ~15 min (call opportunistically on create, or a small job).
3. **Routes** (`approvals_routes.py`) — add ALONGSIDE the existing sync endpoint (no regression):
   - `POST /api/approvals/hire/<id>/generate-name` → `{ok, job_id, status:'generating'}` (instant).
   - `GET  /api/approvals/hire/<id>/generate-name/<job_id>` → `{ok, status, name, expansion, ...}`.
   - Keep `POST .../suggest-name` until the frontend fully switches.
4. **Frontend** (`department_hq.html` ~L1448 inline handler): POST generate-name → get job_id →
   poll GET every ~1.5s (cap ~30 polls) → render into `nameInput` + `hireState.newAgent`. Keep the
   existing `_dhqApprovalsBusy` guard held across the WHOLE poll loop (clear in finally). Keep the
   fallback hint. Button shows "Generating…" but the request returns instantly.
5. **Tests** — service unit (create→thread writes result→get; error path), route (POST returns
   job_id; GET returns status). Mock the dispatch/build_identity seam.

## MANDATORY final gate
Live browser drive of DHQ Approvals → ✨ Generate (login as claude): click → button shows
"Generating…" → poll → name renders. **DHQ UI changes MUST be verified in a real DOM drive, not
just API QA** (mistake #281727 — a DHQ profile UI change rendered nowhere, caught only live).

## Files
- NEW: `database/migrations/NNN_hire_name_jobs.sql`, `services/hire_name_job_service.py`
- EDIT: `tools/department_hq/approvals_routes.py`, `tools/department_hq/templates/department_hq.html`
- TESTS: `platform_v2/tests/test_hire_name_job_service.py`

## Current facts (verified live 2026-07-19)
- Warm-path LLM name works: `research → E.R.U.I.N.E. source=llm 5.3s`.
- `fact_check → P.O.R.T.A.L. source=fallback 17.9s` (3 attempts failed validation/dedup).
- Bare `python3 -c` name-gen FALSELY fails `No module named 'db'` — need `_ensure_import_paths()`
  first (KB #272154). The Flask route works.
