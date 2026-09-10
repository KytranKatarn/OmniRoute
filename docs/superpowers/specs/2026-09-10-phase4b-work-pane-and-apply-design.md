# Phase 4b — the Work pane (tasks & projects) and Apply on a Builder result

**Date:** 2026-09-10 · **Project:** #343 (master-command program) · **Tasks:** #6679 (Work pane), #6680 (Apply) · **Builds on:** Phase 4a, ADR-042 (`docs/superpowers/specs/2026-09-10-phase4-cockpit-ui-design.md`)

## Owner decisions (2026-09-10, brainstorm)

1. **Purpose of the panes: triage + delegate.** See projects and their tasks with the Dev HQ fields; create a task; change status and priority; add a note; hand a task to the fleet. No project creation, no deletes.
2. **Apply target: target file up front.** The Builder form gets a `target file` field; the hub reads that file and includes it in the prompt so the model returns a full rewrite. This sends the existing file's contents to the cloud contractor (development material under the #3256 allowlist). A path that does not exist yet means a new file.
3. **Tasks path: a new single-writer `task_service` on the hub** with seven internal routes under `tasks:read` / `tasks:write`, comms-only. The MCP handlers (`mcp_server/tools/project_tools.py`) and Dev HQ (`tools/consciousness/devhq_routes.py`) keep their inline SQL for now; converging them is a follow-up task, not this slice.
4. **Apply path: the hub.** Tier-2 approval, then branch + commit + PR through the existing generic `github_service` primitives. The engine path was rejected: its approval-gated write never reaches a PR and its PR route re-plans through an LLM instead of taking literal content. Only `archie-platform` is a valid target repo in this slice.
5. Design sections 1–4 below were approved as presented.

## Scope

**In:** two new hub scopes; `services/task_service.py`; seven `/api/internal/tasks*` and `/api/internal/projects` routes; a Work pane (Crew ⇄ Work switch on the left column, task detail in the middle column) with `+ Task`, status, priority, note, delegate; `target file` on the Builder form; `POST /api/internal/cloud-code/run/<id>/apply`; the `cloud_code_apply` Tier-2 approval type and its executor; cockpit-apply PRs forced to human merge; tests; live acceptance at 390×844 and 1280×800.

**Out (deferred):** job history search; project create/archive; task delete; other target repos; a sandbox test gate before the PR (revisit as a synthetic Repair Bay proposal later); converging MCP + Dev HQ onto `task_service`; Phase 5 TTY lanes.

## 1. Architecture and scopes

Same shape as 4a. archie-comms is a session-gated pass-through (`cockpit_routes.py` → `services/cockpit_proxy.py` → hub `/api/internal/*` with `Bearer INTERNAL_API_KEY`); the hub owns every read and write; comms holds no SQL.

- `platform_v2/services/internal_auth.py`: add `"tasks:read"` and `"tasks:write"` to `SCOPES` and to `CALLER_SCOPES["archie_comms"]` (the same two-line shape as `agents:read`, lines 90 and 107 today). No other caller gets them. `tests/test_internal_auth_scopes.py` completeness floor rises by the number of new `/api/internal/` rules: nine (eight tasks/projects rules plus the apply rule), so 48 → 57.
- `platform_v2/services/task_service.py` is the single writer for the seven routes. Module-level functions, `get_db_cursor` context-managed, RealDictCursor rows, no Flask imports, `datetime` values left aware (the route serialiser `_cockpit_json` in `app.py` already stamps naive timestamps UTC).
- Apply adds: an optional `target_path` on `POST /api/internal/cloud-code/run`; `POST /api/internal/cloud-code/run/<id>/apply`; `services/cloud_code_apply.py` (validator, fence stripper, executor); one `elif action_type == "cloud_code_apply"` branch in `ai_bridge/agent_loop.py`'s approval executor; one `github_service.get_file_at_ref` helper; the `cockpit/` branch prefix added to the human-merge gate.

## 2. Hub — tasks & projects

### 2.1 Data (live schema, measured 2026-09-10)

`unified_tasks`: `id, project_id, title varchar(500), description text, status varchar(50), priority integer (1–10, 10 = most urgent), task_type varchar(50), estimated_effort, assigned_user_id, assigned_agent_id, parent_task_id, dependencies jsonb, blockers text, metadata jsonb, tags text[], due_date, started_at, completed_at, created_at, updated_at, created_by_user_id, created_by_agent_id, delegation_source text, delegation_args jsonb, streaming_channel text`. Status has no CHECK; values in use: `pending` (439), `completed` (5,278), `cancelled` (200); the delegation worker also writes `in_progress` and `blocked`. `task_type` values in use: implementation, bugfix, research, testing, review, documentation. `unified_projects`: `id, name, slug (NOT NULL), description, status (active | planning | on_hold | completed | cancelled), priority integer, project_type, parent_project_id, metadata, tags, start_date, target_date, completed_at, …`.

Two live Dev HQ bugs are **not** copied: `devhq_api_create_project`/`create_task` default `priority` to the string `"medium"` against the INTEGER column, and `create_task`/`update_task` write a non-existent `assigned_to_user` column (`devhq_routes.py:252-290`).

**Priority order:** the cockpit sorts `priority DESC` (10 first), matching the MCP `get_my_tasks` tool; Dev HQ's list sorts ASC. The disagreement is filed as a follow-up, not resolved here.

**Notes live on the task.** `work_notes` is session-scoped (`add_work_note` needs an active `work_sessions` row), so cockpit notes append to `unified_tasks.metadata->'notes'`: a JSON array of `{"ts": <ISO UTC>, "author": "cockpit", "text": <≤2000 chars>}`, newest last, capped at 50 (oldest dropped). Reads return the newest 10.

### 2.2 `task_service` contract

| function | reads/writes | contract |
|---|---|---|
| `list_projects(status=None, limit=50, offset=0)` | R | projects with `open_tasks` (status pending/in_progress/blocked) and `total_tasks` counts; default statuses `active, planning, on_hold`; sorted `priority DESC, name` |
| `list_tasks(q=None, project_id=None, status=None, min_priority=None, limit=50, offset=0)` | R | `status` accepts a CSV of `pending, in_progress, blocked, completed, cancelled`; default `pending,in_progress,blocked`; `q` matches title/description ILIKE; sorted `priority DESC, created_at DESC`; `limit` clamped 1–200, `offset` ≥ 0 and echoed |
| `get_task(task_id)` | R | full row + `project_name` + `notes` (newest 10) + `agent_name` when `assigned_agent_id` is set; `None` when missing |
| `create_task(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit")` | W | validates project exists and is not completed/cancelled, title 1–500 chars, priority int 1–10, task_type in the six known values; inserts `status='pending'`, `metadata={"created_via":"cockpit"}` |
| `set_status(task_id, status, requested_by)` | W | status in `pending, in_progress, blocked, completed, cancelled`; sets `completed_at=now()` on completed, `started_at` on first in_progress; refuses (`ValueError`) if the task is currently delegated and `in_progress` (the worker owns it) |
| `set_priority(task_id, priority, requested_by)` | W | int 1–10 |
| `add_note(task_id, text, author="cockpit")` | W | append per 2.1; returns the new note |
| `delegate(task_id, capability, requested_by)` | W | the task must be `pending` or `blocked` and not already delegated (`delegation_source IS NULL` or the previous delegation finished); stamps **the same row**: `delegation_source='cockpit'`, `delegation_args={"capability": <cap>, "reason": <description or title>, "args": {"origin_task_id": id, "requested_by": ...}}`, `status='pending'`, and appends a note `delegated to fleet: <capability>`. The agent-loop `_run_delegate_task_worker` (`agent_loop.py:8390`) polls `delegation_source IS NOT NULL AND status='pending'` and claims it within one 30 s cycle; on completion it writes `work_notes` and flips the status itself. `capability` must be a key of `CAPABILITY_DEPARTMENT_MAP` or present in `agent_skills.skill_name` (checked via the coordinator's map + one query), else `ValueError` naming the nearest three |

`ValueError` messages are user-facing and returned verbatim as `400 {"success": false, "error": ...}`; missing rows are `404`.

### 2.3 Routes (`platform_v2/app.py`, beside the Phase 4a agents routes)

| route | scope | body → response |
|---|---|---|
| `GET /api/internal/projects?status=&limit=&offset=` | tasks:read | `{success, projects:[...], total, limit, offset}` |
| `GET /api/internal/tasks?q=&project_id=&status=&min_priority=&limit=&offset=` | tasks:read | `{success, tasks:[...], total, limit, offset, facets:{status:{...}, projects:{id: name}}}` |
| `GET /api/internal/tasks/<int:id>` | tasks:read | `{success, task:{...}}` / 404 |
| `POST /api/internal/tasks` | tasks:write | `{project_id, title, description?, priority?, task_type?}` → `201 {success, task}` |
| `POST /api/internal/tasks/<int:id>/status` | tasks:write | `{status}` → `{success, task}` |
| `POST /api/internal/tasks/<int:id>/priority` | tasks:write | `{priority}` → `{success, task}` |
| `POST /api/internal/tasks/<int:id>/note` | tasks:write | `{text}` → `{success, note, task}` |
| `POST /api/internal/tasks/<int:id>/delegate` | tasks:write | `{capability}` → `202 {success, task, worker:"delegate_task_worker", claims_within_s: 30}` |

Serialised through `_cockpit_json`. `requested_by` is always `"cockpit"` (comms is the only caller; the session user is not forwarded — same as 4a).

## 3. Hub — Apply

### 3.1 Target file up front

`POST /api/internal/cloud-code/run` (`app.py:5985-6059`) accepts optional `target_path`. When present:

1. `cloud_code_apply.validate_target(path)`: repo-relative, normalised with `posixpath.normpath`, no leading `/`, no `..` segment, no NUL, ≤ 240 chars; must start with one of `ALLOWED_PREFIXES = ("platform_v2/", "ai_bridge/", "scripts/", "docs/", "archie-comms/")` (the engine's `scope_guard.PLATFORM_SCOPE.allowed_paths` plus `archie-comms/`, where the cockpit itself lives; `database/migrations/` stays revoked as the owner ruled for the engine); must not match any of `BLOCKED_GLOBS`, copied verbatim from `scope_guard.py` (`*.env`, `.env*`, `*.key`, `*.pem`, `*.pfx`, `secrets/*`, `docker-compose*`, `Dockerfile*`, `scripts/dr/*`, `.git/*`, `.github/*`, `*agent_service.py`, `*department_dispatcher.py`, `*repair_bay/services/github_service.py`, `*repair_bay/services/pr_review_service.py`, `scripts/check_agent_single_writer.py`, `scripts/agents/*`, `scripts/backup/*`) plus `*internal_auth.py`, `*cloud_code_apply.py`, `*cloud_code_lane.py` (the lane must not be able to rewrite its own gate). The hub cannot import the engine, so the list is duplicated with a comment naming its source; a test asserts the two lists agree by reading the engine file when `/mnt/standalone/archie-code` is mounted, and skips otherwise.
2. `github_service.get_file_at_ref(path, ref="main")` → `GET /repos/{repo}/contents/{path}?ref=main` via `_api_get` (read token), base64-decoded → `{"sha": <blob sha>, "content": str, "size": int}`; 404 → `None` (new file). Files over 200 KB or non-UTF-8 are refused (`400 "target too large / not text"`).
3. Prompt assembly (hub side, never comms): the user prompt is prefixed with `You are editing the file <path> in the archie-platform repository. Return the COMPLETE new contents of that file and nothing else — no prose, no fences.` followed by `--- current contents of <path> ---` and the file (or `--- <path> does not exist yet ---`). The original prompt is kept in job metadata as `prompt`; the assembled one as `prompt_effective`.
4. Job metadata gains `target_path`, `base_sha` (blob sha or `null` for a new file), `base_size`.

Without `target_path` the route behaves exactly as today.

### 3.2 `POST /api/internal/cloud-code/run/<int:job_id>/apply` (scope `cloud:code`)

Preconditions, each a `409` with the reason verbatim: job exists and `status='completed'` with a non-empty `result.response`; job has `target_path`; no `pr_number` on the job yet; no pending `cloud_code_apply` approval for this job. Then:

1. `content = cloud_code_apply.strip_fences(result.response)`: if the whole response is one fenced block (optionally language-tagged), return its body; otherwise return the response unchanged. Trailing whitespace normalised to a single newline at EOF.
2. `request_approval(action_type="cloud_code_apply", action_data={"job_id", "target_path", "base_sha", "content_sha256", "provider", "model", "requested_by": "cockpit"}, reason=f"Apply cloud coding result to {target_path} (job #{job_id})", requested_by="cloud_code_lane", tier=2)`. `request_approval`'s per-action-type dedup means one pending apply at a time platform-wide; a second returns `409 "an apply is already waiting for approval"`.
3. Job metadata gains `apply_approval_id`, `apply_requested_at`. Response `202 {success, job_id, approval_id, status: "pending_approval"}`.

The approval reaches Telegram and the cockpit Approvals strip like every other Tier-2 (`action_type` prefix `cloud_code_` already routes to the Ship category).

### 3.3 Executor (`ai_bridge/agent_loop.py`, beside the `cloud_code_dispatch` branch at ~7423)

`elif action_type == "cloud_code_apply": return cloud_code_apply.execute(action_data)` — this one **executes** (unlike `cloud_code_dispatch`, whose approval is drained by the worker). `execute`:

1. Re-load the job; recompute `content` and check `sha256 == content_sha256` (the approval is bound to what the owner saw).
2. `current = get_file_at_ref(target_path, "main")`; if `(current["sha"] if current else None) != base_sha` → `{"executed": False, "error": f"{target_path} changed on main since the model read it (was {base_sha[:7]}, now {…})"}`; job metadata `apply_error`. The owner re-runs the job to pick up the new base. No silent overwrite.
3. `branch = f"cockpit/apply-{job_id}-{slug(target_path)[:40]}"`; `create_branch(branch, base="main")` (`github_service.py:308`); `push_changes(branch, [target_path], commit_message, content_overrides={target_path: content})` (`github_service.py:345`; overrides make the content literal — the shared tree is never read or written); `create_pr(branch, title=f"[cockpit] {target_path}: {prompt[:60]}", body=…, labels=["cockpit-apply"])` (`github_service.py:452`). The commit message is `feat(cockpit-apply): {target_path} via {provider}:{served_model} (job #{job_id})` and carries `Co-Authored-By: A.R.C.H.I.E. Cockpit <cockpit@kytranempowerment.com>`; the PR body lists job id, provider, requested and served model, prompt, base sha, and a line `Opened from the cockpit; content came from a cloud model with no test gate — human merge only.`
4. Job metadata gains `pr_number`, `pr_url`, `branch`, `applied_at`; `GET /run/<id>` returns them. Any GitHub failure → `{"executed": False, "error": <verbatim>}` and `apply_error`; a branch created before a later failure is deleted (`delete_branch`, `github_service.py:329`).

Deny → the approval row is rejected, nothing is written, job metadata `apply_denied_at`.

### 3.4 Never main, never auto-merged

- All writes go through `create_branch`/`push_changes`/`create_pr`; `main` is only ever a base.
- `pr_review_service.py:711-720` forces human merge for `engine/` branches and `[engine]` titles; this slice adds `cockpit/` and `[cockpit]` to the same gate, so F.O.R.G.E. reviews the PR but never merges it. Merge stays with the owner (or Claude on the owner's standing merge-on-APPROVE directive, which still requires a clean verdict and the coverage discharge).

## 4. Comms — the cockpit

### 4.1 Proxy (`services/cockpit_proxy.py`)

`TASK_ACTIONS = ("status", "priority", "note", "delegate")`; new functions `list_projects(params)`, `list_tasks(params)` (allowed keys `q, project_id, status, min_priority, limit, offset`), `get_task(task_id)`, `create_task(body)`, `task_action(task_id, action, body)` (unknown action → local 400), `build_apply(job_id)`. `build_run(body)` passes `target_path` through untouched. Same `_call`, same timeouts (15 s read / 30 s write), same fail-closed 503.

### 4.2 Routes (`cockpit_routes.py`, session-gated like the rest)

`GET /api/cockpit/projects`, `GET /api/cockpit/tasks`, `GET /api/cockpit/tasks/<int:id>`, `POST /api/cockpit/tasks`, `POST /api/cockpit/tasks/<int:id>/<action>`, `POST /api/cockpit/build/<int:id>/apply` — six new rules (13 → 19).

### 4.3 Template + CSS

- Left column: a two-button switch `Crew | Work` (`.ck-switch`, `aria-pressed`) above the pane; `#pane-crew` and a new `#pane-work` (`aria-label="Work"`) occupy the same grid cell; exactly one is shown. Phone: the bottom tab bar gains `Work` (`Crew · Work · Builder · Approvals`, `data-pane="work"`); the switch is hidden on phone (tabs do the job). ≥768 and ≥1024: grid unchanged (`320px 1fr 400px` at 1024); the switch is visible.
- `#pane-work`: header `Work · <open count>` + `+ Task`; search box; chips: status (`pending / in_progress / blocked` on by default, `completed`, `cancelled`), `priority ≥ 8`, projects (from `facets.projects`); list grouped by project with a collapsible header (`name · status · open/total`); task rows as buttons (title, priority pill, status, type).
- `#ck-task` sheet (middle column at ≥1024, overlay sheet on phone, same pattern as `#ck-agent`): title, project, status pill, priority, type, assignee, description, notes (newest 10), actions row: status select + `Set`, priority select 1–10 + `Set`, `Add note` (inline textarea + button, no `window.prompt`), `Delegate` (capability select + button; the options are `facets.capabilities` from the tasks list response — the hub serves the sorted keys of `CAPABILITY_DEPARTMENT_MAP` there, so comms never hardcodes a capability), and, when delegated, a `delegated · <capability> · <status>` line.
- `+ Task` form (`#ck-task-new`, same shape as `#ck-hire`): project select (from projects), title, description, priority (default 5), type select.
- Builder form: `target file` text input `name="target_path"` with placeholder `platform_v2/… (optional — the model gets the current file and returns the whole file)`. Jobs list: a completed job with `target_path` and no `pr_number` shows `Apply`; after apply it shows `apply waits for approval #<id>`; once applied it shows `PR #<n>` as a link to `pr_url`; `apply_error` is shown verbatim.

### 4.4 JS (`static/js/cockpit.js`)

- `PANES` gains `work`; the switch and the tab both call `showPane('work'|'crew')`; `showPane` remembers the left-column choice in `localStorage['ck-left']` (fallback crew).
- `loadWork(reset)`: `GET /api/cockpit/projects` and `GET /api/cockpit/tasks?…` in parallel; group tasks by `project_id`; render; `Load more` on the task list (same offset logic as the roster).
- `showTask(id)`: `GET /api/cockpit/tasks/<id>` → render the sheet; actions call `taskAct(id, action, body, okText)` → `POST /api/cockpit/tasks/<id>/<action>`; on success re-fetch the task and refresh the group count; on error toast the hub text.
- Poll: tasks refresh every 30 s (`WORK_POLL_MS = 30000`, not the 5 s job poll); a delegated task's sheet re-fetches every 10 s until its status leaves `pending`/`in_progress`.
- Builder: `runJob()` sends `target_path` when non-empty; `applyJob(id)` → `POST /api/cockpit/build/<id>/apply` → toast `Apply waits for your approval — #<approval>` → `loadJobs()`.
- Everything rendered with `textContent`; no `innerHTML` with API data (same scan tests as 4a).

## 5. Data flow

```
Work pane  ── GET /api/cockpit/tasks ──▶ comms proxy ── Bearer ──▶ hub GET /api/internal/tasks ──▶ task_service.list_tasks ──▶ unified_tasks
Delegate   ── POST …/tasks/<id>/delegate ──▶ hub task_service.delegate (stamps the row) ─▶ agent_loop delegate_task_worker (≤30 s) ─▶ DHQ dispatch ─▶ work_notes + status
Builder    ── POST /api/cockpit/build/run {prompt, target_path} ──▶ hub run route: validate → get_file_at_ref → prompt_effective → bridge_jobs + Tier-2 (cloud_code_dispatch) ─▶ worker ─▶ result.response
Apply      ── POST /api/cockpit/build/<id>/apply ──▶ hub apply route: strip_fences → Tier-2 (cloud_code_apply) ─▶ owner approves (Telegram/strip) ─▶ executor: sha check → branch → push (content_overrides) → PR ─▶ job.pr_number
```

## 6. Error handling

- Hub validation errors are `400` with the message verbatim; missing rows `404`; state conflicts `409`; the proxy passes status + JSON through; the cockpit shows `error` as a toast and never mutates optimistically.
- Hub unreachable / 15 s read timeout → `503 hub unreachable: <ExceptionClass>` (unchanged from 4a; #6681 tracks the hub-side cause).
- Apply executor failures land in `apply_error` on the job and the approval row's `execution_result`; the jobs list shows them verbatim.
- A `cloud_code_apply` approval whose job no longer exists or whose content hash no longer matches is refused with `executed: False` (never partially applied).

## 7. Security

- Scopes are the boundary: `tasks:read`/`tasks:write` and `cloud:code` are granted to `archie_comms` only; nobody gets `*`; the completeness test keeps every `/api/internal/` rule decorated.
- Comms holds no SQL, no repo path, no GitHub token, and never talks to the engine for this feature.
- Target paths: allowlisted prefixes + blocked globs + traversal/NUL/size checks, evaluated on the hub, with the lane's own files and the auth module blocked so the lane cannot rewrite its gate.
- Every apply is a Tier-2 human approval bound to a content hash and a base sha; the PR is human-merge-only; `main` is never written.
- Cloud exposure: the target file's contents leave the hub to the chosen contractor. That is the owner's decision 2 above, inside the #3256 "development and repairs" rule; the allowlist excludes product data trees (`what-the-fact/`, `kytran-*/`, `secrets/`, `.env*`).
- Reads use the read-scoped token (`FORGE_REVIEW_TOKEN` path in `_api_get`); writes use the write token exactly where `deploy_via_forge` already does.

## 8. Testing

**Hub** (`docker exec -i archie_platform python3 -m pytest /app/tests/<file> -q -p no:cacheprovider`, against `archie_test` with rows the test seeds and asserts non-vacuous per `mistake_pytest-live-data-is-vacuous`):
- `tests/test_task_service.py`: seeds two projects and six tasks; `list_projects` counts; `list_tasks` filters, CSV status, `q`, paging clamp; `get_task` notes newest-10; `create_task` validations (project state, priority range, type); `set_status` completed_at / started_at / refuses a worker-owned in_progress; `add_note` append + cap 50; `delegate` stamps the same row (`delegation_source='cockpit'`, args capability/origin_task_id), refuses a non-pending task and an unknown capability.
- `tests/test_internal_auth_scopes.py`: floor `>= 57`; both new scopes granted to comms only; each new route 401 without a key and 403 with a key lacking the scope.
- `tests/test_cloud_code_apply.py`: `validate_target` — accepts `platform_v2/x.py`, rejects `../x`, `/etc/passwd`, `platform_v2/.env`, `docker-compose.yml`, `scripts/dr/x.sh`, `platform_v2/services/agent_service.py`, `platform_v2/services/internal_auth.py`, `database/migrations/483.sql`, a 300-char path; `strip_fences` — bare code, one fenced block, language-tagged block, prose + block left unchanged; executor with a recorded fake `github_service`: base-sha mismatch refuses and creates nothing; happy path calls `create_branch` → `push_changes` (with `content_overrides`) → `create_pr` in that order with the expected branch name and stamps `pr_number`; a `create_pr` failure deletes the branch; content-hash mismatch refuses. Engine-list parity test skips when `/mnt/standalone/archie-code` is absent.
- `tests/test_cloud_code_run_target.py`: run route with `target_path` stores `target_path`/`base_sha`, assembles `prompt_effective`, rejects a blocked path with 400, treats a 404 as a new file; without `target_path` the stored metadata is byte-identical to today's.
- Human-merge gate test extended: a `cockpit/` branch and a `[cockpit]` title are refused for auto-merge.

**Comms** (`bash /mnt/archie_brain/archie-comms/scripts/run_tests.sh`): `test_cockpit_proxy.py` +6 (task functions, unknown task action refused locally, `build_apply`, `target_path` passthrough); `test_cockpit_routes.py` +7 (each new rule gated, 19 rules total); `test_cockpit_page.py` (Work pane markup, switch, four tabs, `target_path` input, no `innerHTML` with API data, `WORK_POLL_MS`, `Apply` rendering only when `target_path && !pr_number`).

**Live acceptance** (Playwright on the hub, `192.168.1.200:3002` origin after the SSO leg, at 390×844 and 1280×800): Work pane lists projects with counts → `+ Task` in project 343 (`Phase 4b acceptance probe`, priority 7) → DB row → status `in_progress` → DB → priority 9 → DB → note → `metadata->'notes'` → delegate with capability `research` → within 60 s the worker claims it (`delegation_source='cockpit'`, status leaves pending) → set `cancelled` after it finishes → Builder with `target file` `docs/cockpit-apply-probe.md` and prompt `Write a two-line markdown note saying this file was written by the cockpit apply probe.` → approve dispatch → completed → `Apply` → approval in the strip and Telegram → approve → job shows `PR #n` → the PR exists on GitHub with the file, branch `cockpit/apply-<job>-docs-cockpit-apply-probe-md`, labels `cockpit-apply`, and F.O.R.G.E. picks it up → close the PR unmerged, delete the branch, cancel the probe task; `escalation_mode` still `local_only`. Screenshots `cockpit-390-work.png`, `cockpit-390-task.png`, `cockpit-1280-work.png`, `cockpit-1280-apply.png`.

## 9. Follow-ups filed with this spec

- Converge `mcp_server/tools/project_tools.py` and `devhq_routes.py` onto `task_service` (and fix Dev HQ's `"medium"` priority default and phantom `assigned_to_user` column).
- Resolve the priority sort disagreement (cockpit + MCP DESC vs Dev HQ ASC).
- Job history search in the Builder.
- A sandbox test gate for cockpit applies (synthetic Repair Bay proposal path).
