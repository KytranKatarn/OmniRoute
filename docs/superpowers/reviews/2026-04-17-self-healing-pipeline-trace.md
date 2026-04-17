# Self-Healing Pipeline Trace — 2026-04-17

**Spec:** `docs/superpowers/specs/2026-04-17-self-healing-loop-design.md`
**Method:** Static trace (grep/read) + plant-and-follow. Read-only; no code or DB mutations.

---

## 1. Code Health scanner

### 1.1 The table the spec names (`code_health_audits`) does not exist

The spec refers to a `code_health_audits` table. It is not in the database and no code writes to it.

- **Grep:** `grep -rnE 'INSERT INTO code_health_audits|UPDATE code_health_audits|code_health_audits' /mnt/archie_brain/platform_v2 /mnt/archie_brain/ai_bridge` → **zero hits**. Confirmed absent 2026-04-17.
- **DB:** `docker exec archie_database psql -U archie -d archie -c '\d code_health_audits'` → `Did not find any relation named "code_health_audits"`. Confirmed absent 2026-04-17.

The actual physical tables are `code_audit_log` and `code_metrics_snapshots` (confirmed via `\dt` — see check_tables_similar query). Section references below use these names; anywhere the spec says `code_health_audits` should be treated as a pointer to `code_audit_log`.

### 1.2 Writers

Two tables, two writers — both in `services/code_metrics_service.py`:

| Target table | Writer | File : line |
|---|---|---|
| `code_audit_log` | `log_audit(...)` — single `INSERT INTO code_audit_log (...) RETURNING id` | `platform_v2/services/code_metrics_service.py:1729` (def), INSERT at `:1746` |
| `code_metrics_snapshots` | `save_snapshot(metrics=None)` — `INSERT INTO code_metrics_snapshots (...)` | `platform_v2/services/code_metrics_service.py:1235` (def), INSERT at `:1285` |

An additional backfill-only INSERT into `code_metrics_snapshots` exists at `code_metrics_service.py:2098` (used for git-history reconstruction; not part of the live scan path).

Call-sites of `log_audit()` (all writers to `code_audit_log`):

- `platform_v2/tools/department_hq/jobs.py:103` — scheduled per-module audit (inside `automated_module_audit()`-equivalent loop)
- `platform_v2/tools/department_hq/jobs.py:160` — scheduled
- `platform_v2/tools/department_hq/jobs.py:238` — scheduled
- `platform_v2/tools/consciousness/code_health_routes.py:460` — on-demand via `/api/code-health/audit` endpoint (`code_health_audit()` handler, decorator at `:430`-ish, function at `code_health_routes.py:432`)

### 1.3 Triggers — schedule + on-demand + deprecated-but-active comments

**Two scheduled jobs are active in `platform_v2/tools/department_hq/jobs.py`:**

- `daily_code_health_scan` — `def` at `department_hq/jobs.py:451`, registered at `:651` with `trigger=CronTrigger(hour=2, minute=0)` (2:00 AM daily). Calls `scan_codebase()` + `save_snapshot()` (`:455`-`:458`).
- `daily_code_health_digest` — `def` at `department_hq/jobs.py:337`, registered at `:642` with `trigger=CronTrigger(hour=8, minute=0)` (8:00 AM daily). Sends Telegram digest; does not itself write `code_audit_log`.
- An `automated_module_audit`-style loop is also in this file (see calls at `:103`, `:160`, `:238`) and is the per-module driver that actually writes `code_audit_log` entries with `trigger_reason='scheduled'`.

**On-demand endpoints in `platform_v2/tools/consciousness/code_health_routes.py`:**

- `POST /api/code-health/scan` → handler `code_health_scan()` at `:21` — calls `scan_codebase(force=True)` + `save_snapshot(metrics)`. Writes `code_metrics_snapshots` only.
- `POST /api/code-health/audit` (body `{module: "<name>"}` or empty for all) → handler `code_health_audit()` starting at `:432` — calls `audit_single_module()` + `log_audit(..., trigger_reason="manual", dispatched_via="F.O.R.G.E.")` at `:460`, then `process_audit_findings()` (auto-submits to Repair Bay, `:475`-ish).

**Deprecated comments — potentially misleading:**

Lines 915-937 of `ai_bridge/agent_loop.py` are a commented-out scheduler block marked `# Phase 5: Moved to dev_hq/jobs.py`. No `dev_hq/` directory exists (`find /mnt/archie_brain -type d -name dev_hq` → zero hits); the actual destination is `platform_v2/tools/department_hq/jobs.py`. The methods `_daily_code_health_scan` (`agent_loop.py:4576`) and `_daily_code_health_digest` (`agent_loop.py:4571`) remain in `agent_loop.py` as DEPRECATED stubs. Live audit activity confirms the new location works: `SELECT MAX(audited_at)` on `code_audit_log` returns `2026-04-17 08:00:00` with 1,252 total rows (`scheduled`=1,060, `manual`=192).

**No git-hook triggers.** Grep for `pre-commit`, `post-commit`, `.git/hooks` scan wiring: not found in the code-health path. Confirmed absent via the batch greps above on 2026-04-17.

### 1.4 Severity schema — no CHECK constraint, assignment is in Python

The `code_audit_log` table does **not** store severity as a column. Schema from `\d code_audit_log` (2026-04-17):

```
 id                     | integer                | not null
 module_name            | character varying(100) | not null
 category               | character varying(50)  |
 files_reviewed         | integer                | default 0
 lines_before           | integer                | default 0
 lines_after            | integer                | default 0
 issues_found           | integer                | default 0
 issues_fixed           | integer                | default 0
 notes                  | text                   |
 status                 | character varying(20)  | default 'pending'
 audited_at             | timestamp              | default now()
 stale                  | boolean                | default false
 last_audit_snapshot_id | integer                | FK → code_metrics_snapshots(id)
 audit_profile          | character varying(20)  | default 'python'
 trigger_reason         | character varying(30)  | default 'scheduled'
 dispatched_via         | character varying(50)  |
```

**No `severity` column and no CHECK constraints of any kind** (confirmed by absence from the `\d` output). Severity is stashed inside `notes` as a semicolon-delimited string of `CODE: detail` pairs and recomputed at read time.

**Severity assignment (code pointers):**

Three levels exist — `red`, `yellow`, `info` — assigned in Python by matching the finding code against hardcoded sets:

- **Write path** (severity attached to each finding before persistence): `platform_v2/services/code_metrics_service.py:1416`, `:1499`, `:1579` — all use `severity = SEVERITY_MAP.get(code, "info")` inside `audit_single_module()` (def at `:1662`).
- **Read-path recomputation** (from `notes` text) lives in `code_health_routes.py`:
  - `code_health_severity_summary()` at `:254` — `RED_CODES = {"SQL_INJECTION", "HARDCODED_SECRET", "DIRECT_OLLAMA", "DIRECT_CLOUD"}`, `YELLOW_CODES = {"BARE_EXCEPT", "LARGE_FILE", "MISSING_INIT"}`. Highest severity bubbles up: `red > yellow > green` (green = clean).
  - `code_health_audit_details()` at `:430` uses a **different, larger set**: `red_codes = {SQL_INJECTION_RISK, HARDCODED_SECRET, DIRECT_OLLAMA, DIRECT_CLOUD, INSECURE_DEFAULT}`, `yellow_codes = {BARE_EXCEPT, LARGE_FILE, MISSING_INIT, INLINE_SCRIPT, CONSOLE_LOG, LATEST_TAG, MISSING_RESOURCE_LIMIT}`. Default falls to `info`. See `code_health_routes.py:543` (`severity = "info"` default), `:676` (same pattern in a parallel handler).
  - Note the mismatch: `SQL_INJECTION` vs `SQL_INJECTION_RISK`, and `severity-summary` does not count `INSECURE_DEFAULT` as red. **Flagged for Phase 1** — two handlers disagree on the severity taxonomy for the same stored data.

**Severity `critical` / `high` / `medium` / `low`** (the conventional SOC2/CVE ladder) appear in `github_routes.py:786-798` but are **not used** by the code-health scanner. Confirmed via the grep_severity_assignment batch: only `info`, `red`, `yellow`, `green` are referenced by `code_health_routes.py` and `code_metrics_service.py`.

### 1.5 Summary answers

- **Writers:** `log_audit()` at `code_metrics_service.py:1729` writes `code_audit_log`; `save_snapshot()` at `code_metrics_service.py:1235` writes `code_metrics_snapshots`. The table the spec names (`code_health_audits`) does not exist — confirmed absent via grep + `\d` on 2026-04-17.
- **Triggers:** Both scheduled and on-demand. Scheduled via APScheduler in `platform_v2/tools/department_hq/jobs.py` — `daily_code_health_scan` at 02:00 (`:651`) and `daily_code_health_digest` at 08:00 (`:642`), with the per-module audit loop producing `trigger_reason='scheduled'` rows. On-demand via `POST /api/code-health/scan` (snapshots only) and `POST /api/code-health/audit` (writes audit rows with `trigger_reason='manual'`, `dispatched_via='F.O.R.G.E.'`) in `code_health_routes.py`. No git hooks. `ai_bridge/agent_loop.py:915-937` comments are stale — they claim "Moved to dev_hq/jobs.py" but `dev_hq/` does not exist; real home is `department_hq/jobs.py`.
- **Severity:** No DB column, no CHECK constraint — `code_audit_log` has only `notes text`. Three levels (`red`, `yellow`, `info`) assigned in Python by code-string matching against hardcoded sets in `code_metrics_service.py` (write path via `SEVERITY_MAP.get(code, "info")` at `:1416/:1499/:1579`) and recomputed at read time in `code_health_routes.py:254` and `:430`. The two read-side handlers use different code sets — flagged for Phase 1.

## 2. Code Health → Repair Bay bridge
_(populated by Task 4)_

## 3. Repair Bay proposal pipeline
_(populated by Task 5)_

## 4. Repair Bay → DHQ dispatch
_(populated by Task 6)_

## 5. Telegram unification status
_(populated by Task 7)_

## 6. ARCHIE decision infrastructure
_(populated by Task 8)_

## 7. Plant-and-follow results
_(populated by Task 3 outcome reviewed at Task 9)_

### 7.1 Planted finding

**Marker string:** `CH_TRACE_MARKER_20260418`

**Seed file:** `/mnt/archie_brain/sandbox/ch_trace_seed.py`
- **SHA256:** `df6455b4ee0864f69f1604d5a5da561d538645730ecf43f79b098eff62f274b1`
- **Size:** 9 lines. Git-safe: `sandbox/.gitignore` (`*` + `!.gitignore`) blocks commit; `git status` shows only `?? sandbox/` (the dir itself as untracked, contents masked).

**Local flake8 baseline (3 violations as designed):**
```
sandbox/ch_trace_seed.py:4:5: F841 local variable 'x' is assigned to but never used
sandbox/ch_trace_seed.py:7:5: E722 do not use bare 'except'
sandbox/ch_trace_seed.py:9:12: F821 undefined name 'undefined_name'
```

**Scan trigger attempted:** `POST http://192.168.1.200:3000/api/code-health/audit` with body `{"module": "[SHARED]"}` via `urllib.request`.
- **Response:** HTTP 200 returning the platform login HTML (`<title>A.R.C.H.I.E. - System Access</title>`). The route is decorated `@login_required @admin_required`; Flask-Login redirects unauthenticated POSTs to the login page as a 200 rather than 401/302 JSON. No audit was actually dispatched.

**DB rows reached (post-trigger attempt):**
- `code_audit_log` where `notes ILIKE '%ch_trace_seed%' OR notes ILIKE '%CH_TRACE_MARKER_20260418%'` → **0 rows**.
- `code_metrics_snapshots` in the last 10 minutes → **0 new rows**.

**Two structural reasons the finding cannot reach `code_audit_log` via the current pipeline — even with a valid admin session:**

1. **Sandbox is outside the scan roots.** `services/code_metrics_service.py` defines `PLATFORM_ROOT=/mnt/archie_brain/platform_v2` (or `/app` in-container), `AI_BRIDGE_ROOT=/mnt/archie_brain/ai_bridge`, `MIGRATIONS_ROOT=/mnt/archie_brain/database/migrations`. `scan_codebase()` only walks those three trees. `/mnt/archie_brain/sandbox/` is never visited, so the seed is invisible to `audit_single_module(...)` regardless of auth.
2. **`code_audit_log` is module-granular, not file-granular.** Re-inspecting the schema (correcting Task 2's note): columns are `id, module_name, category, files_reviewed, lines_before, lines_after, issues_found, issues_fixed, notes, status, audited_at, stale, last_audit_snapshot_id, audit_profile, trigger_reason, dispatched_via`. There is **no `file_path` column.** Per-file detail lives only in the in-memory `issues_list` returned by `audit_single_module()` and flows to Repair Bay via `process_audit_findings(...)` — `code_audit_log` records only the module-level rollup. The only way the marker string could show up in DB is embedded in the free-text `notes` column, and only for a module that the scan roots cover.

**Phase 1 implication:** any tooling that claims to "follow a finding from file to DB to Repair Bay" must key off Repair Bay proposal rows (and/or the in-memory `issues_list`), not off `code_audit_log`. The audit log is a summary, not an evidence log.

**Seed retention:** file stays in place locally (blocked from git) pending Task 9 cleanup; subsequent tasks can reference the same SHA256 for continuity.

## 8. Gap list for Phases 1-4
_(populated by Task 9)_
