# Self-Repair Lifecycle Phases 1–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Repair Bay status true (Phase 1), then make "deploy" actually apply code — via a sandbox-gated branch+PR whose governed merge is the apply mechanism (Phase 2).

**Architecture:** No new subsystems. Phase 1 repairs five silent failures so the ledger tells the truth. Phase 2 wires the existing-but-uncalled `deploy_via_forge`/`deploy_via_merge` PR machinery into both deploy choke points behind a mandatory sandbox gate, adds a merge-completion hook at the `sync_closed_prs` choke point, and an advisory observer for the hub's volume-mounted tree.

**Tech Stack:** Flask + psycopg2 (platform), APScheduler (archie_scheduler), existing `forge_pipeline`/`github_service`/`sandbox gate` services, one SQL migration.

**Spec:** `docs/superpowers/specs/2026-08-26-self-repair-lifecycle-completion-design.md`

## Global Constraints

- **No repair path may ever write production files directly** — git is the apply mechanism (spec §2). `deploy_to_production`'s no-op stays; its callers move to `ship_as_pr`.
- Feature branch + PR for every task group; NEVER commit to main. Black pre-commit reformats — re-stage and re-commit after the first attempt fails.
- Every `CronTrigger(...)` carries `timezone="America/Toronto"` (timezone.md).
- Every new work-control key is ALSO registered in `work_control_service` `BACKLOGS` so the Autonomy tab surfaces it — an unsurfaced key is the "declared but never applied" trap.
- `telegram_service.send_system` dedups on (title, source): distinct conditions get distinct titles.
- psql verification always merges stderr (`2>&1`); writes verified with `RETURNING` + re-SELECT — an empty result is NOT a pass.
- `improvement_proposals.proposed_at`/`deployed_at` are `timestamp without time zone` — compute ages in SQL, never with aware datetimes in Python.
- Never restart `archie_platform`/`archie_scheduler` while a F.O.R.G.E. review is in flight.
- Each silent-failure fix ships a test **proven to fail against the pre-fix code** (run the test BEFORE the fix, or import a copy of the old module via `importlib` — never mutate the live file to re-break it).
- UI edits follow `.claude/rules/ui-refactoring.md`: screenshot before/after, one component at a time, verify in a live browser (source assertions do not count — KB #283579).
- All platform tests run inside the container: `docker exec archie_platform python3 -m pytest tests/<file> -v` (path `/app` = `platform_v2/`).
- After any merge that touches `platform_v2/`: `git checkout main && git pull --ff-only` on the hub **is** the deploy; verify through the running process (`docker exec … python3 -c "import …"`), never grep.

## File Structure

| File | Change |
|---|---|
| `platform_v2/services/proposal_service.py` | T1 prop_meta fix · T2 archive fix · T7 serialisation · T10 `ship_as_pr` |
| `platform_v2/tools/repair_bay/scan_routes.py` | T3 dedup + INSERT fix |
| `platform_v2/tools/repair_bay/services/forge_pipeline.py` | T4 stale-audit SELECT · T9 adapter · T11 completion functions |
| `platform_v2/services/code_metrics_service.py` | T5 `_get_commit_hash` |
| `platform_v2/tools/department_hq/jobs.py` | T6 reverify job · T12 hub-deploy observer |
| `platform_v2/services/work_control_service.py` | T6/T12 BACKLOGS entries |
| `platform_v2/services/model_dispatch_service.py` | T10 gate promotion + callback rewire |
| `platform_v2/tools/repair_bay/proposal_routes.py` | T10 deploy endpoint rewire |
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | T11 sync hook |
| `platform_v2/tools/repair_bay/sandbox_routes.py` | T13 gate-runs endpoint |
| `platform_v2/templates/tools/repair_bay.html` + `platform_v2/static/js/repair-bay-main.js` | T7/T13 UI |
| `database/migrations/<next>_pr_open_status.sql` | T8 |
| `platform_v2/tests/test_repair_ledger_honesty.py` (new) | T1–T5 tests |
| `platform_v2/tests/test_ship_as_pr.py` (new) | T9–T11 tests |

---

## PHASE 1 — Make the ledger honest

### Task 1: `prop_meta` NameError — post-deploy QA can fire (#6044)

**Files:** Modify `platform_v2/services/proposal_service.py` (~:524 SELECT, ~:527 fetch, ~:683 call site). Test: `platform_v2/tests/test_repair_ledger_honesty.py`.

**Interfaces:** Produces: `run_proposal` internally binds `prop_meta: dict` (proposal metadata) before `_trigger_module_qa(prop_meta, proposal_id)`. `_trigger_module_qa` (:475) reads `prop_meta.get("suite_id")` / `.get("file_path")` — unchanged.

- [ ] **Step 1: Write the failing test** (AST-based — pins assignment-before-use without needing a DB):

```python
"""tests/test_repair_ledger_honesty.py — Phase 1 of the lifecycle completion (spec 2026-08-26).

Every test here pins a SILENT failure measured on 2026-08-26 (KB #296234):
statuses that flipped without their action happening. Falsifiability: each
test was run against the PRE-FIX code first and failed.
"""
import ast
import inspect


def test_prop_meta_is_assigned_before_the_qa_trigger():
    """#6044: run_proposal called _trigger_module_qa(prop_meta, ...) with prop_meta
    never assigned — NameError on every SUCCESSFUL deploy, reported as failure,
    so post-deploy P.R.O.B.E. QA + the perf gate never fired (0 runs ever)."""
    import services.proposal_service as ps

    src = inspect.getsource(ps.run_proposal)
    fn = ast.parse(src).body[0]
    assigned = {
        t.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    calls_qa = any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_trigger_module_qa"
        for node in ast.walk(fn)
    )
    assert calls_qa, "run_proposal no longer calls _trigger_module_qa — update this test"
    assert "prop_meta" in assigned, "prop_meta is used at the QA trigger but never assigned (#6044)"
```

- [ ] **Step 2: Run it — must FAIL against current code**
Run: `docker exec archie_platform python3 -m pytest tests/test_repair_ledger_honesty.py::test_prop_meta_is_assigned_before_the_qa_trigger -v`
Expected: FAIL with "prop_meta is used at the QA trigger but never assigned".

- [ ] **Step 3: Fix** — in `run_proposal`, widen the SELECT and bind the variable:

```python
        cur.execute(
            "SELECT id, status, plan_steps, title, metadata FROM improvement_proposals WHERE id = %s",
            (proposal_id,),
        )
        proposal = cur.fetchone()
```

and immediately after the `if not proposal:` / empty-`plan_steps` guards:

```python
        # #6044: _trigger_module_qa(prop_meta, ...) at the bottom of this function
        # referenced a name that was never assigned — post-deploy QA never fired.
        prop_meta = proposal.get("metadata") or {}
```

- [ ] **Step 4: Re-run the test** — Expected: PASS.
- [ ] **Step 5: Live-verify through the running process** (after the branch merges and the hub is on main + restarted — fold into the Task 7 restart, do not restart per-task):
`docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); import ast, inspect, services.proposal_service as ps; src=inspect.getsource(ps.run_proposal); print('prop_meta' in src)"` → `True`.
- [ ] **Step 6: Commit** `fix(repair-bay): assign prop_meta in run_proposal so post-deploy QA can fire (#6044)`

### Task 2: `archive_proposal` updates a column that does not exist (#6045a)

**Files:** Modify `platform_v2/services/proposal_service.py:927-945`. Test: same test file.

- [ ] **Step 1: Failing test** (DB round-trip in a rolled-back transaction):

```python
def test_archive_proposal_sql_matches_schema():
    """#6045: archive_proposal UPDATEd nonexistent archived_at — the endpoint
    returned success:False on EVERY call. Archive metadata must follow the
    audit_pipeline convention (8,964 rows archived that way)."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """INSERT INTO improvement_proposals (title, description, status, proposed_at)
               VALUES ('t2-archive-test', 'throwaway', 'proposed', NOW()) RETURNING id"""
        )
        pid = cur.fetchone()["id"]
        cur.execute(
            """UPDATE improvement_proposals
               SET status = 'archived',
                   metadata = COALESCE(metadata, '{}'::jsonb)
                              || jsonb_build_object('archived_at', NOW()::text,
                                                    'archived_by', 'repair_bay_api')
               WHERE id = %s RETURNING status, metadata->>'archived_by' AS by""",
            (pid,),
        )
        row = cur.fetchone()
        assert row["status"] == "archived" and row["by"] == "repair_bay_api"
        conn.rollback()
```

(This passes standalone — the falsifiability check for this task is Step 2.)

- [ ] **Step 2: Prove the OLD code fails** — run the current function against a throwaway row once:
`docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.proposal_service import archive_proposal; print(archive_proposal(999999999))" 2>&1` → expect `success: False` with an `archived_at` UndefinedColumn error in the message (not "not found" — the column error fires first in planning). Record the output in the task notes.
- [ ] **Step 3: Fix** — replace the UPDATE in `archive_proposal` with the metadata form from Step 1 (keep the `rowcount == 0 → not found` handling).
- [ ] **Step 4: Run the test** — PASS. Re-run Step 2's probe → now `{"success": False, "error": "Proposal not found"}` (correct 404 semantics for a bogus id).
- [ ] **Step 5: Commit** `fix(repair-bay): archive_proposal writes metadata archive stamps, not a phantom column (#6045)`

### Task 3: Diagnose→Proposals bridge is schema-broken (#6045b)

**Files:** Modify `platform_v2/tools/repair_bay/scan_routes.py` (`_has_open_proposal` :15-34; the INSERT :349-355). Test: same file.

Verified against `information_schema` 2026-08-26: `improvement_proposals` has **no `file_path` column**; `proposed_by` is **integer**; `priority` is **varchar**; `category` exists.

- [ ] **Step 1: Failing regression pin** (source-level — the broken artifacts must be gone):

```python
def test_scan_bridge_names_only_real_columns():
    """#6045: the issues-to-proposals INSERT named nonexistent file_path and put
    the string 'scan_bridge' into integer proposed_by; its dedup queried the same
    phantom column and FAILED OPEN. file_path lives in metadata."""
    from pathlib import Path

    src = Path("/app/tools/repair_bay/scan_routes.py").read_text()
    assert "'scan_bridge'" not in src, "string literal into integer proposed_by"
    assert "file_path, category, priority" not in src, "INSERT still names the phantom file_path column"
    assert "WHERE file_path = " not in src, "dedup still queries the phantom column (fails open)"
```

- [ ] **Step 2: Run — FAIL** on all three asserts.
- [ ] **Step 3: Fix the dedup** — metadata-based, and widen the status set to the live vocabulary:

```python
            cur.execute(
                """SELECT 1 FROM improvement_proposals
                   WHERE metadata->>'file_path' = %s
                     AND category = %s
                     AND status IN ('proposed', 'pending', 'in_review', 'approved',
                                    'ready_for_review', 'fix_requested', 'pr_open')
                   LIMIT 1""",
                (file_path, category),
            )
```

- [ ] **Step 4: Fix the INSERT** — drop the phantom column and the type-mismatched writer (file_path is already inside the `metadata` JSON this route builds; `proposed_by` is nullable — omit it; `priority` is varchar — cast):

```python
                cur.execute(
                    """INSERT INTO improvement_proposals
                       (title, description, category, priority, status, proposed_at, metadata)
                       VALUES (%s, %s, %s, %s, 'proposed', NOW(), %s::jsonb)
                       RETURNING id""",
                    (title, description, category, str(priority), metadata),
                )
```

- [ ] **Step 5: DB-shape test** (rolled back):

```python
def test_scan_bridge_insert_shape_matches_schema():
    import json
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """INSERT INTO improvement_proposals
               (title, description, category, priority, status, proposed_at, metadata)
               VALUES ('t3', 'd', 'general', '3', 'proposed', NOW(), %s::jsonb) RETURNING id""",
            (json.dumps({"file_path": "x.py", "source": "scan_issues_to_proposals"}),),
        )
        assert cur.fetchone() is not None
        conn.rollback()
```

- [ ] **Step 6: Run both tests** — PASS. **Step 7: Commit** `fix(repair-bay): issues-to-proposals bridge matches the real schema; dedup no longer fails open (#6045)`

### Task 4: `mark_stale_audits` reads the phantom column inside a swallowed except (#6045c)

**Files:** Modify `platform_v2/tools/repair_bay/services/forge_pipeline.py:402-405`.

- [ ] **Step 1:** Change the SELECT to `"SELECT metadata->>'file_path' FROM improvement_proposals WHERE id = %s"` (the module-derivation `split("/")` logic below is unchanged — it receives the same string).
- [ ] **Step 2:** In the surrounding `except` add `logger.warning("mark_stale_audits bridge failed for proposal %s: %s", proposal_id, db_err)` — the silent swallow is how this stayed broken.
- [ ] **Step 3: Regression pin** in the test file: `assert "SELECT file_path FROM improvement_proposals" not in Path("/app/tools/repair_bay/services/forge_pipeline.py").read_text()` (run before fix → FAIL; after → PASS).
- [ ] **Step 4: Commit** `fix(forge): merged fixes invalidate stale module audits again (#6045)`

### Task 5: `_get_commit_hash` dead in the scheduler since 2026-03-23 (#6046)

**Files:** Modify `platform_v2/services/code_metrics_service.py` (`_get_commit_hash`).

- [ ] **Step 1: Verify the precondition** (if this fails, STOP — it is a compose-volume decision, not a code fix):
`docker exec archie_scheduler sh -c 'test -f /mnt/archie_brain/.git/HEAD && echo GIT-OK || echo NO-GIT'`
- [ ] **Step 2: Reproduce** the failure in-container:
`docker exec archie_scheduler python3 -c "import subprocess; r=subprocess.run(['git','rev-parse','HEAD'], cwd='/mnt/archie_brain', capture_output=True, text=True); print(r.returncode, (r.stderr or '')[:120])"` → expect non-zero with `dubious ownership` (the safe.directory refusal). Record the output.
- [ ] **Step 3: Fix** — adopt the `hub_deploy_state.py` invariant (`git -C <root> -c safe.directory=<root>`), and stop eating the error:

```python
def _get_commit_hash(repo_path="/mnt/archie_brain"):
    """Current git commit hash.

    The scheduler container runs as a different uid than the host-owned checkout,
    so bare git refuses with 'dubious ownership' — every snapshot since 2026-03-23
    stored an empty hash, disabling change detection (#6046). Same trap and same
    fix as services/hub_deploy_state.py: -C plus an explicit safe.directory.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "-c", f"safe.directory={repo_path}", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning("_get_commit_hash: %s", (result.stderr or "").strip()[:200])
    except Exception as e:
        logger.warning("_get_commit_hash: %s", e)
    return None
```

- [ ] **Step 4: Verify in the failing container**: same Step-2 probe but with the new arg list → `0` + a 40-hex hash.
- [ ] **Step 5: Post-deploy proof** (next nightly, or force one snapshot): `docker exec archie_database psql -U archie -d archie -c "SELECT id, created_at, commit_hash <> '' AS has_hash FROM code_metrics_snapshots ORDER BY id DESC LIMIT 1;" 2>&1` → `has_hash = t`.
- [ ] **Step 6: Commit** `fix(code-health): commit-hash capture survives the scheduler's uid mismatch — change detection revived (#6046)`

### Task 6: Scheduled re-verify + the first consumer of `still_open`

**Files:** Modify `platform_v2/tools/department_hq/jobs.py` (new job beside the drain, registration beside the other CronTriggers ~:1420-1440) and `platform_v2/services/work_control_service.py` (`BACKLOGS` entry).

**Interfaces:** Consumes `audit_pipeline.reverify_deployed_findings()` (existing). Produces work-control key `code_health_reverify` (default ON) and `platform_settings` key `code_health:reverify:last_still_open`.

- [ ] **Step 1:** Read the neighbouring jobs in `jobs.py` for the exact `wc.is_enabled` / `_log_cycle` / `send_system` call shapes used in this file, then add:

```python
    def _run_code_health_reverify():
        """Daily loop closure: re-audit deployed proposals INDEPENDENTLY of audit-all.

        Before this job, reverified stamps rode only on the audit-all tail — if that
        stalled, verdicts silently froze (last 'fixed' was 2026-06-02 while deploys
        continued into August; KB #296234). Also the FIRST consumer of still_open:
        growth means shipped fixes are not removing their findings — alert, dedup'd
        on the count so a standing backlog pages once, not daily.
        """
        from database import get_db_cursor
        from services import audit_pipeline

        if not wc.is_enabled("code_health_reverify", default=True):
            return
        audit_pipeline.reverify_deployed_findings()
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "SELECT count(*) AS n FROM improvement_proposals "
                    "WHERE status = 'deployed' AND metadata->>'reverified' = 'still_open'"
                )
                n = int(cur.fetchone()["n"])
                cur.execute(
                    "SELECT value FROM platform_settings WHERE key = 'code_health:reverify:last_still_open'"
                )
                row = cur.fetchone()
                prev = int(row["value"]) if row and str(row["value"]).isdigit() else n
                cur.execute(
                    """INSERT INTO platform_settings (key, value)
                       VALUES ('code_health:reverify:last_still_open', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    (str(n),),
                )
            if n > prev:
                telegram_service.send_system(
                    f"Code Health re-verify: still_open grew to {n}",
                    f"{n - prev} deployed fix(es) did not remove their finding "
                    f"(was {prev}). Repair Bay → Repairs lists them.",
                )
        except Exception as e:
            logger.warning("code_health_reverify still_open alert failed: %s", e)
```

(Match this file's actual `telegram_service` import/alias and `platform_settings` upsert shape — copy a neighbouring job's, e.g. the drain's; if `platform_settings` carries an `updated_at`, include it as the neighbours do.)

- [ ] **Step 2: Register** (daily 04:40 ET — after the 02:00–03:30 scan/audit train):

```python
    scheduler.add_job(
        with_ctx(_run_code_health_reverify),
        CronTrigger(hour=4, minute=40, timezone="America/Toronto"),
        id="code_health_reverify",
        max_instances=1,
        coalesce=True,
    )
```

- [ ] **Step 3: Surface the toggle** — add a `BACKLOGS` entry in `work_control_service.py` (copy an existing entry's exact dict shape): key `code_health_reverify`, default `True`, description "Daily re-audit of deployed proposals + still_open growth alert".
- [ ] **Step 4: Test** — invoke the job function once in-container (`docker exec archie_scheduler python3 -c ...` importing and calling it) → confirm a `platform_settings` row exists with `RETURNING`-style re-SELECT, and `reverified_at` stamps advanced: `SELECT max((metadata->>'reverified_at')) FROM improvement_proposals WHERE metadata->>'reverified' IS NOT NULL` (adjust to the real stamp key by reading `reverify_deployed_findings` first).
- [ ] **Step 5: Commit** `feat(code-health): dedicated daily reverify job — still_open gets its first consumer`

### Task 7: Surface the truth in the Repairs tab

**Files:** Modify `platform_v2/services/proposal_service.py` (`list_proposals` serialisation loop :56-81), `platform_v2/templates/tools/repair_bay.html` (`renderProposals` ~:2435 + detail ~:2600), CSS if a new badge class is needed.

- [ ] **Step 1:** In `list_proposals`'s row loop, add ISO serialisation for the skipped fields and a top-level honesty flag:

```python
            md = p.get("metadata") or {}
            p["code_applied"] = md.get("code_applied") is True
            p["pr_url"] = md.get("pr_url")
            for _k in ("deployed_at", "deployment_started_at"):
                if p.get(_k) is not None and hasattr(p[_k], "isoformat"):
                    p[_k] = p[_k].isoformat()
```

- [ ] **Step 2:** Test: `list_proposals(status='deployed', limit=1)` in-container → the row carries boolean `code_applied` and ISO-string `deployed_at` (no RFC-1123 dates).
- [ ] **Step 3 (UI, ui-refactoring protocol — screenshot before/after):** in `renderProposals` card markup and the detail view, for `status === 'deployed'` render one badge: `code_applied === true` → `LIVE`; else → `NOT APPLIED` with `title="Backed up and cleared to apply — code was never written (#5808)"`. Use `textContent`-safe construction consistent with the surrounding renderer.
- [ ] **Step 4:** Browser-verify on the live Repairs tab (P.R.O.B.E. or Playwright, logged in as claude): a deployed proposal shows NOT APPLIED. Screenshot.
- [ ] **Step 5: Commit** `feat(repair-bay): deployed rows show whether code is actually live`

**Phase 1 ships as one PR** (Tasks 1–7, branch `fix/repair-ledger-honesty`): push, F.O.R.G.E. review, merge, then on the hub `git checkout main && git pull --ff-only` and restart `archie_platform` + `archie_scheduler` (T5/T6 live in the scheduler) — outside review windows.

---

## PHASE 2 — The deploy that deploys

### Task 8: Migration — `pr_open` joins the status vocabulary

**Files:** Create `database/migrations/<next>_pr_open_status.sql` (take the next free number: `ls database/migrations | sort -V | tail -3`).

- [ ] **Step 1:** Write (idempotent; the current constraint enumerates exactly the 14 statuses below — verified live 2026-08-26):

```sql
-- pr_open: proposal shipped as a branch+PR, awaiting the governed merge (spec 2026-08-26 §6).
ALTER TABLE improvement_proposals DROP CONSTRAINT IF EXISTS improvement_proposals_status_check;
ALTER TABLE improvement_proposals ADD CONSTRAINT improvement_proposals_status_check
  CHECK (status::text = ANY (ARRAY[
    'proposed','approved','sandboxed','deployed','regression','paused_for_perf_review',
    'rejected','archived','fix_requested','pending','pending_approval','ready_for_review',
    'agent_assigned','needs_claude','pr_open'
  ]::text[]));
```

- [ ] **Step 2: Apply** — `docker exec -i archie_database psql -U archie -d archie < database/migrations/<file>.sql 2>&1` (the DB container is read-only to `docker cp` — stdin is the way).
- [ ] **Step 3: Verify** — insert+rollback a `pr_open` row in a transaction; also confirm an invalid status still refuses.
- [ ] **Step 4: Commit** `feat(db): pr_open proposal status (migration <n>)`

### Task 9: `_proposal_fix_fields` — adapt `deploy_via_forge` to real proposals

**Files:** Modify `platform_v2/tools/repair_bay/services/forge_pipeline.py` (new helper above `deploy_via_forge`; rewire :195-197 where `file_path`/`code_diff`/`suggested_fix` are read). Test: `platform_v2/tests/test_ship_as_pr.py`.

**Interfaces:** Produces `_proposal_fix_fields(proposal: dict) -> dict{file_path, code_diff, suggested_fix}`. Consumed by `deploy_via_forge` step 3.

- [ ] **Step 1: Failing tests:**

```python
"""tests/test_ship_as_pr.py — Phase 2: git is the apply mechanism."""
from tools.repair_bay.services.forge_pipeline import _proposal_fix_fields


def test_fix_fields_resolve_from_metadata():
    """Audit-pipeline proposals carry file_path in metadata and the diff in
    code_changes — there is NO file_path column (information_schema 2026-08-26).
    deploy_via_forge previously read only the legacy column names and would have
    refused every audit proposal with 'no file_path'."""
    p = {"metadata": {"file_path": "tools/consciousness/routes.py"}, "code_changes": "--- a\n+++ b\n"}
    f = _proposal_fix_fields(p)
    assert f["file_path"] == "tools/consciousness/routes.py"
    assert f["code_diff"].startswith("---")


def test_fix_fields_prefer_legacy_columns_when_present():
    p = {"file_path": "x.py", "code_diff": "D", "metadata": {"file_path": "y.py"}, "code_changes": "C"}
    f = _proposal_fix_fields(p)
    assert f["file_path"] == "x.py" and f["code_diff"] == "D"


def test_fix_fields_tolerate_string_metadata_and_absence():
    assert _proposal_fix_fields({"metadata": "{not json"})["file_path"] == ""
    assert _proposal_fix_fields({})["code_diff"] == ""
```

- [ ] **Step 2: Run — FAIL** (helper does not exist). **Step 3: Implement:**

```python
def _proposal_fix_fields(proposal: Dict) -> Dict:
    """Resolve target file + fix diff across BOTH proposal generations.

    Legacy shape used file_path/code_diff attributes; audit-pipeline rows keep
    file_path in metadata jsonb and the unified diff in code_changes. Column
    names win when present so any legacy caller is byte-identical.
    """
    md = proposal.get("metadata") or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            md = {}
    return {
        "file_path": proposal.get("file_path") or md.get("file_path") or "",
        "code_diff": proposal.get("code_diff") or proposal.get("code_changes") or "",
        "suggested_fix": proposal.get("suggested_fix") or "",
    }
```

and in `deploy_via_forge` replace the three direct reads with `fields = _proposal_fix_fields(proposal)` / `file_path = fields["file_path"]` etc.
- [ ] **Step 4: Run tests** — PASS. **Step 5: Commit** `feat(forge): deploy_via_forge understands audit-pipeline proposals`

### Task 10: `ship_as_pr` — one terminal action, both choke points, gate mandatory

**Files:** Modify `platform_v2/services/model_dispatch_service.py` (promote `_sandbox_gate` → public `sandbox_gate` + alias; rewire the `deploy_to_production` call at ~:992), `platform_v2/services/proposal_service.py` (new `ship_as_pr`), `platform_v2/tools/repair_bay/proposal_routes.py:229-236` (endpoint rewire). Tests in `test_ship_as_pr.py`.

**Interfaces:** Produces `proposal_service.ship_as_pr(proposal_id, skip_gate=False) -> dict{success, pr_number?, pr_url?, branch?, gate?, error?}`. Consumes `sandbox_gate(proposal_id, proposal)` (promoted), `deploy_via_forge(proposal, deployment_id)` (T9).

- [ ] **Step 1:** In `model_dispatch_service.py` rename `def _sandbox_gate(` → `def sandbox_gate(` and add `_sandbox_gate = sandbox_gate` beneath it (the existing callback keeps working; a public name is importable without a private-symbol smell).
- [ ] **Step 2:** Check `improvement_deployments` for a CHECK on `deployment_type` (`SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='improvement_deployments'::regclass AND contype='c';` 2>&1). If `'forge_pr'` is not permitted, use `'manual'` and record `apply_mode` in proposal metadata only.
- [ ] **Step 3:** Add to `proposal_service.py` (imports `json`, `RealDictCursor`, `datetime` already present):

```python
def ship_as_pr(proposal_id, skip_gate=False):
    """Terminal deploy action for BOTH deploy paths: sandbox-gate, then open a fix PR.

    #5808 made direct production writes a dead end by design; git is the apply
    mechanism — the merge, through the governed merge_pr choke point, applies code.
    skip_gate=True is for deploy_approve_gate, which has ALREADY run the gate.
    Gate failure returns {'success': False, 'gate': ...} — never raises.
    """
    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    if not proposal:
        return {"success": False, "error": "Proposal not found"}
    if proposal.get("status") not in ("approved", "ready_for_review", "fix_requested", "pending_approval"):
        return {"success": False, "error": f"status '{proposal.get('status')}' is not shippable"}

    if not skip_gate:
        from services.model_dispatch_service import sandbox_gate  # late: avoids import cycle

        gate = sandbox_gate(proposal_id, dict(proposal))
        if not gate.get("passed"):
            return {"success": False, "error": "sandbox gate failed", "gate": gate}

    with _get_db_cursor(commit=True) as (dconn, dcur):
        dcur.execute(
            """INSERT INTO improvement_deployments (proposal_id, deployment_type, status)
               VALUES (%s, %s, 'deploying') RETURNING id""",
            (proposal_id, "forge_pr"),
        )
        deployment_id = dcur.fetchone()["id"]

    from tools.repair_bay.services.forge_pipeline import deploy_via_forge  # late import

    result = deploy_via_forge(dict(proposal), deployment_id)
    if not result.get("success") or result.get("method") == "no_change":
        return result

    with _get_db_cursor(commit=True) as (uconn, ucur):
        ucur.execute(
            """UPDATE improvement_proposals
               SET status = 'pr_open',
                   metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
               WHERE id = %s""",
            (
                json.dumps(
                    {
                        "pr_number": result.get("pr_number"),
                        "pr_url": result.get("pr_url"),
                        "branch": result.get("branch"),
                        "apply_mode": "forge_pr",
                        "code_applied": False,
                        "shipped_at": datetime.now().isoformat(),
                    }
                ),
                proposal_id,
            ),
        )
    return result
```

- [ ] **Step 4: Rewire the two choke points:** `proposal_routes.py` `proposals_deploy` → `result = proposal_service.ship_as_pr(proposal_id)` (route path unchanged so the existing UI button keeps working); `model_dispatch_service` `deploy_approve_gate` → replace `result = deploy_to_production(proposal_id)` with `result = ship_as_pr(proposal_id, skip_gate=True)` (import beside the existing `deploy_to_production` import, which can then be removed if unused).
- [ ] **Step 5: Pin the rewire with a test:**

```python
def test_no_deploy_path_reaches_the_noop_deploy():
    """Both deploy choke points must terminate in ship_as_pr. deploy_to_production
    (the #5808 no-op) may keep existing but nothing routes to it."""
    from pathlib import Path

    routes = Path("/app/tools/repair_bay/proposal_routes.py").read_text()
    mds = Path("/app/services/model_dispatch_service.py").read_text()
    assert "ship_as_pr" in routes and "deploy_to_production" not in routes
    assert "ship_as_pr(proposal_id, skip_gate=True)" in mds
```

plus unit tests for `ship_as_pr` with `deploy_via_forge`/`sandbox_gate` monkeypatched: gate-fail → no deployment row + no status change; success → `pr_open` + metadata fields; `no_change` → status untouched.
- [ ] **Step 6: Commit** `feat(repair-bay): ship_as_pr — sandbox-gated PR is the only deploy (#5808 made permanent)`

### Task 11: Merge completion at the `sync_closed_prs` choke point

**Files:** Modify `forge_pipeline.py` (extract `complete_proposal_after_merge(proposal_id, pr_number)` from `deploy_via_merge`'s step-5 block; new `complete_merged_fix_proposals()`), `github_service.py` (helper `pr_merge_state(pr_number) -> 'merged'|'closed'|'open'|None`, mirroring `pr_is_open`'s None-on-error contract), `pr_review_service.py` (`sync_closed_prs` hook beside `close_stale_pr_merge_approvals`). Tests in `test_ship_as_pr.py`.

- [ ] **Step 1:** Extract the completion block (proposal→deployed, `improvement_deployments`→`status='deployed', completed_at=NOW()`, `mark_stale_audits` bridge) into `complete_proposal_after_merge`, ADDING the honesty stamp the old block lacked: `metadata || {"code_applied": true, "merged_pr": <n>, "merged_at": <iso>}` and guarding the UPDATE with `AND status = 'pr_open'` for the new path (`deploy_via_merge` passes its own status context — keep its behavior identical by parameterising the expected-status guard, default `('pr_open',)`, with `deploy_via_merge` passing `None` = no guard, byte-compatible).
- [ ] **Step 2:** Implement the scanner:

```python
def complete_merged_fix_proposals() -> Dict:
    """Settle every pr_open proposal against GitHub. Called from sync_closed_prs —
    the choke point all three PR pollers share (#2736 pattern).

    FAIL-SAFE: pr_merge_state() None (GitHub unreadable) leaves the row ALONE —
    a blip must never complete or fail a proposal (the pr_is_open None rule).
    """
```

merged → `complete_proposal_after_merge`; closed-unmerged → `status='fix_requested'` + `metadata.pr_closed_unmerged=<n>`; open/None → untouched. Return `{checked, completed, reopened}` counts for the poller's log line.
- [ ] **Step 3:** Hook: in `sync_closed_prs`, after the approvals reconcile call, `try: complete_merged_fix_proposals() except Exception as e: logger.warning(...)` — the poller must never die on it. Place it BELOW the early returns exactly as the approvals sweep is (#5707: a failed PR list must not read as "everything closed").
- [ ] **Step 4: Tests** — monkeypatch `pr_merge_state`: three transitions + the None-untouched pin (`test_github_blip_leaves_pr_open_rows_alone`).
- [ ] **Step 5: Commit** `feat(forge): merged fix PRs complete their proposals — deployed now means merged`

### Task 12: `hub_deploy_state_monitor` — "advise when to deploy"

**Files:** Modify `tools/department_hq/jobs.py` (job + registration beside `deploy_drift_monitor` :1686/:1732), `work_control_service.py` (`BACKLOGS` key `hub_deploy_advisor`, default True). Possibly `platform_v2/app.py` (internal alias — only if Step 1 forces branch B).

- [ ] **Step 1: Decide the read path.** `docker exec archie_scheduler sh -c 'test -S /var/run/docker.sock && echo SOCKET || echo NOSOCKET'`. **Branch A (SOCKET):** the job imports `services.hub_deploy_state.hub_deploy_state` directly (its git half already carries safe.directory; its container-inspect half needs the socket). **Branch B (NOSOCKET):** add `GET /api/internal/deploy/hub-state` in `app.py` beside the `/api/internal/code-health/*` aliases (:5402-5458, Bearer `INTERNAL_API_KEY`) returning `jsonify(hub_deploy_state())`, and the job requests it at `http://archie_platform:3000`.
- [ ] **Step 2:** Read `services/hub_deploy_state.py` for the exact result keys, then add the job:

```python
    def _run_hub_deploy_state_monitor():
        """'Advise when to deploy' (spec 2026-08-26 §6.5): watch the volume-mounted
        hub tree. deploy_drift_monitor covers the 9 image-baked products; nothing
        watched the hub half — a merged fix that never got checkout+restart is the
        #2718 trap. ADVISORY ONLY: nothing restarts automatically. Dedup'd on a
        state fingerprint so a standing condition pages once, not every 30 min.
        """
        if not wc.is_enabled("hub_deploy_advisor", default=True):
            return
        state = _read_hub_deploy_state()  # branch A import or branch B internal GET
        status = state.get("status")
        if status not in ("needs_pull", "needs_restart"):
            return
        fingerprint = f"{status}:{str(state.get('head_sha', ''))[:9]}:{state.get('behind_main', '')}"
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'deploy:advisory:last'")
                row = cur.fetchone()
                if row and row["value"] == fingerprint:
                    return  # standing condition already advised — page once, not every 30 min
                cur.execute(
                    """INSERT INTO platform_settings (key, value)
                       VALUES ('deploy:advisory:last', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    (fingerprint,),
                )
        except Exception as e:
            logger.warning("hub_deploy_state_monitor dedup failed (alerting anyway): %s", e)
        telegram_service.send_system(
            f"Hub deploy advised: {status}",
            "The hub working tree has merged changes not yet running "
            f"(behind_main={state.get('behind_main')}, warnings={state.get('warnings')}). "
            "Apply: git checkout main && git pull --ff-only, then restart archie_platform/archie_scheduler.",
        )
```

(`...` is the Task-6 dedup block verbatim with the `deploy:advisory:last` key — copy it, don't re-derive.)
- [ ] **Step 3: Register** with `IntervalTrigger(minutes=30)`, `id="hub_deploy_state_monitor"`, `max_instances=1`, `coalesce=True`; add the `BACKLOGS` entry.
- [ ] **Step 4: Test live** — invoke once in-container while the tree is deliberately one commit behind (right after a merge, before pulling): advisory fires once; second invocation is silent (fingerprint dedup). Then pull and confirm a third invocation stays silent (`in_sync`).
- [ ] **Step 5: Commit** `feat(dhq): hub deploy advisor — merged fixes now ask to be shipped`

### Task 13: UI — the four tabs meet the new lifecycle

**Files:** `templates/tools/repair_bay.html`, `static/js/repair-bay-main.js`, `tools/repair_bay/sandbox_routes.py` (one new read endpoint). One component at a time per ui-refactoring.md, screenshot before/after each.

- [ ] **Step 1 (Repairs):** add a **PR Open** filter chip beside the existing chips (template:377-384); in the card/detail renderers, `status === 'pr_open'` renders the chip + a link from `p.pr_url` (T7 already serialises it) with the F.O.R.G.E. review state text. Verdict logic stays server-side — the template must not re-derive verdicts (the `test_merge_state_ui.py` rule).
- [ ] **Step 2 (Ship › Provenance):** a **Hub Deploy State** card above the product matrix, fed by the existing `GET /tools/repair-bay/api/deploy/hub-state` (deploy_routes.py:408): status pill (`in_sync` green / `needs_pull`/`needs_restart` amber / `dirty`/`unknown` grey), `behind_main`, and the advice line. Render `unknown` as unknown — never as healthy.
- [ ] **Step 3 (Test Bay › Staging):** new endpoint in `sandbox_routes.py`:

```python
    @bp.route("/api/sandbox/gate-runs", methods=["GET"])
    @login_required
    @admin_required
    def sandbox_gate_runs():
        """Recent proposal rehearsals: the sandbox gate + post-deploy QA runs."""
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, suite_id, status, triggered_by, started_at
                   FROM qa_test_runs
                   WHERE triggered_by LIKE 'tiered_approval_gate_proposal_%%'
                      OR triggered_by LIKE 'repair_bay_deploy:%%'
                   ORDER BY id DESC LIMIT 20"""
            )
            return jsonify({"success": True, "runs": [dict(r) for r in cur.fetchall()]})
```

(verify `qa_test_runs` column names with `\d qa_test_runs` first; render as a simple list under the staging status card).
- [ ] **Step 4 (Diagnose › Issues):** a **→ Proposals** button posting to the (Task-3-fixed) `/api/scan/issues-to-proposals` with a confirm dialog stating the grouping rule, then a toast with `created` count and a pointer to the Repairs tab.
- [ ] **Step 5:** Live browser drive of all four tabs (claude login, 192.168.1.200:3000) + screenshots; console clean of new 404s.
- [ ] **Step 6: Commit** `feat(repair-bay): four tabs surface the PR lifecycle (pr_open, hub state, gate runs, issues bridge)`

### Task 14: Acceptance — one finding through the whole loop

**The definition of done for Phases 1–2: the first machine-verified `fixed` since 2026-05-12.**

- [ ] **Step 1:** Pick one mechanical `ready_for_review` proposal (F401 class) whose stored diff is valid against the current file (`git apply --check` on a temp copy). Record its id.
- [ ] **Step 2:** Repairs tab → Deploy (now Ship as PR): sandbox gate runs (visible in Test Bay Gate Runs), PR opens, proposal flips `pr_open` with `pr_url`.
- [ ] **Step 3:** F.O.R.G.E. reviews the PR (auto via poll); merge via `/merge-pr` after APPROVE.
- [ ] **Step 4:** Trigger `sync_closed_prs` (or wait for the poll) → proposal `deployed` with `code_applied: true`; its `improvement_deployments` row `deployed/completed_at`.
- [ ] **Step 5:** Advisory fires (`hub_deploy_state_monitor`, forced run) → apply on the hub: `git checkout main && git pull --ff-only`, restart the affected container outside review windows.
- [ ] **Step 6:** Force the reverify job → `metadata.reverified = 'fixed'` on the proposal, and grep the actual file to confirm the finding is gone (gate on the artifact).
- [ ] **Step 7:** Record the evidence chain (proposal id, PR #, merge SHA, reverify stamp) in the Dev HQ completion notes + a KB vault_note; update `.claude/rules/module-capability-index.md` Repair Bay + Consciousness entries.

---

## Self-review notes

- Type consistency: `ship_as_pr` returns `deploy_via_forge`'s dict unchanged on success — T13's UI reads `pr_url` from proposal metadata (written in T10), not from the route response, so the shapes cannot drift.
- T11's status-guard parameterisation keeps `deploy_via_merge` byte-compatible for its existing UI caller.
- Order matters: T8 (migration) before T10 (first `pr_open` write); T9 before T10 (`deploy_via_forge` must understand the proposal before anything ships one); T4 before T11 (the completion hook calls the fixed stale-audit bridge).
- Deliberately absent: re-labelling historical rows, drain source-widening, engine/coder wiring, per-project toggles — spec §7.
