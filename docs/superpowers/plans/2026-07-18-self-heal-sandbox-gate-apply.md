# Self-Heal Sandbox Gate — Real Apply + Validate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the self-heal sandbox gate actually `git apply` a fix's unified diff into the staging worktree, smoke-test it on `archie_staging`, and revert — so a fix is really validated (not rubber-stamped) before any future deploy lane.

**Architecture:** Fix-gen already stores a unified diff in `improvement_proposals.code_changes` but with a basename path `git apply` can't locate; the gate's applier still expects a JSON full-file list. We (1) make fix-gen emit a repo-relative diff header, (2) rewrite the gate's applier to base-sync each touched file from live prod, `git apply --check` (fail-closed on drift) → `git apply` → and revert in a `finally`, and (3) reversibly archive the 43 legacy pre-format blobs. `deploy_to_production` stays theater — nothing here writes to production.

**Tech Stack:** Python 3, pytest 9 (in `archie_platform` container), git worktree at `/mnt/archie_sandbox` (branch `_sandbox_preview`), `docker compose -f docker-compose.staging.yml`, `qa_service.run_suite` (suite #79 `staging-smoke` → `http://archie_staging:3000`).

## Global Constraints

- **No production writes this slice.** `deploy_to_production` (`proposal_service.py:959`) stays theater. No code path here writes into `archie_platform`'s `/app` or any prod source. (ADR-001 safety invariant.)
- **Fail closed always.** Any inability to fully + cleanly apply a fix → gate returns `passed=False` WITHOUT running QA. A stale/undapplicable fix must never reach the QA run.
- **Worktree root is `/mnt/archie_sandbox`** (NOT `/mnt/archie_sandbox/platform_v2`). `.git` resolves at the root; `platform_v2/` and `ai_bridge/` are subdirs. Run all `git` from `-C /mnt/archie_sandbox`.
- **In-container prod paths differ from repo-relative.** In `archie_platform`, `platform_v2/*` is mounted at `/app`, `ai_bridge/*` at `/mnt/archie_brain/ai_bridge`. ALWAYS resolve prod source via `audit_pipeline.resolve_proposal_source(rel)` — never hardcode `/mnt/archie_brain/platform_v2/...` (that path is not present in-container).
- **Only `platform_v2/*` and `ai_bridge/*` are gateable.** Those are the sole trees in the staging worktree. A diff touching anything else (standalone/website) → fail closed with a clear message (out of scope for this gate).
- **DRY / reuse:** `resolve_proposal_source()` (`audit_pipeline.py:730`) is the single source of truth for path resolution — reuse it for both the diff header (Task 1) and base-sync (Task 2). Do not write a second resolver.
- **Test invocation:** `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/<file>::<test> -v'`.
- **Commit discipline:** feature branch `fix/self-heal-sandbox-gate-apply` (already created). One commit per task. Pre-commit runs black+flake8; re-stage if black reformats.

---

## File Structure

- **Modify** `platform_v2/services/audit_pipeline.py`
  - New pure helper `_build_fix_diff(old_content, new_content, repo_rel_path) -> (diff_text, stats)` (Task 1).
  - Diff-gen site (~L1174-1200) calls the helper with the resolved repo-relative `file_path` (Task 1).
  - New `archive_legacy_diff_proposals(dry_run=False) -> dict` + pure predicate `_is_legacy_blob(code_changes) -> bool` (Task 3).
- **Modify** `platform_v2/services/proposal_service.py`
  - Rewrite `_apply_fix_to_sandbox(sandbox_path, code_changes)` for the unified-diff contract + base-sync + fail-closed (Task 2).
  - `_sandbox_gate`: pass worktree ROOT `/mnt/archie_sandbox`; add revert-in-`finally` (Task 2).
- **Modify** `platform_v2/tests/test_audit_pipeline_fixgen.py` — add `_build_fix_diff` header test (Task 1).
- **Rewrite** `platform_v2/tests/test_sandbox_gate_fail_closed.py` — new diff-contract tests (Task 2).
- **Create** `platform_v2/tests/test_archive_legacy_blobs.py` — predicate tests (Task 3).

---

## Task 1: Fix-gen emits a git-appliable (repo-relative) diff

**Files:**
- Modify: `platform_v2/services/audit_pipeline.py` (add `_build_fix_diff`; call it at the diff-gen site ~L1174-1200)
- Test: `platform_v2/tests/test_audit_pipeline_fixgen.py`

**Interfaces:**
- Consumes: `resolve_proposal_source` already reassigns `file_path` to the resolved repo-relative path at L1000 (`abs_path, file_path, _resolve_status = resolve_proposal_source(file_path)`), and the code returns early unless status is `ok`. So at the diff-gen site `file_path` is guaranteed a repo-relative `ok` path (e.g. `platform_v2/tools/.../department_dispatcher.py`, `ai_bridge/...`).
- Produces: `_build_fix_diff(old_content: str, new_content: str, repo_rel_path: str) -> tuple[str, dict]` — returns `(diff_text, diff_stats)` where `diff_text` headers are `--- a/<repo_rel_path>` / `+++ b/<repo_rel_path>`.

- [ ] **Step 1: Write the failing test**

Add to `platform_v2/tests/test_audit_pipeline_fixgen.py`:

```python
def test_build_fix_diff_uses_repo_relative_header():
    import services.audit_pipeline as ap

    old = "def f():\n    return 1\n"
    new = "def f():\n    return 2\n"
    rel = "platform_v2/tools/department_hq/services/department_dispatcher.py"

    diff_text, stats = ap._build_fix_diff(old, new, rel)

    # git apply (from the worktree root) needs the FULL repo-relative path,
    # never a basename — a/department_dispatcher.py can't be located.
    assert f"--- a/{rel}" in diff_text
    assert f"+++ b/{rel}" in diff_text
    assert "department_dispatcher.py\n" not in diff_text.split("---")[1][:80] or rel in diff_text
    assert stats.get("added", 0) >= 1 and stats.get("removed", 0) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_audit_pipeline_fixgen.py::test_build_fix_diff_uses_repo_relative_header -v'`
Expected: FAIL — `AttributeError: module 'services.audit_pipeline' has no attribute '_build_fix_diff'`.

- [ ] **Step 3: Add the `_build_fix_diff` helper**

Insert near the other fix helpers in `audit_pipeline.py` (e.g. just above `dispatch_proposal_fix`):

```python
def _build_fix_diff(old_content, new_content, repo_rel_path):
    """Unified diff whose headers carry the REPO-RELATIVE path (a/<rel>, b/<rel>).

    git apply (run from the /mnt/archie_sandbox worktree root) needs the full
    repo-relative path to locate the file — a basename cannot be applied. Returns
    (diff_text, stats). Isolated + pure so the header contract is unit-testable.
    """
    from code_diff_engine import CodeDiffEngine

    engine = CodeDiffEngine()
    result = engine.generate_diff(
        old_content=old_content,
        new_content=new_content,
        filename=repo_rel_path,
    )
    return result.get("diff_text", ""), result.get("stats", {})
```

- [ ] **Step 4: Wire it into the diff-gen site**

In `dispatch_proposal_fix`, replace the inline diff block (currently ~L1174-1189, the `from code_diff_engine import CodeDiffEngine` ... `diff_stats = {}` block) with:

```python
    # Generate a git-appliable diff (repo-relative header — file_path was resolved
    # to an 'ok' repo-relative path by resolve_proposal_source above).
    try:
        diff_text, diff_stats = _build_fix_diff(source_content, fixed_content, file_path)
    except Exception as e:
        logger.warning("Diff generation failed for proposal #%d: %s", proposal_id, e)
        diff_text = f"--- Fix generated by {agent_name} ---\n(diff generation failed: {e})"
        diff_stats = {}
```

(The `SET code_changes = %s, status = 'ready_for_review'` UPDATE at ~L1192-1200 is unchanged — it still stores `diff_text`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_audit_pipeline_fixgen.py -v'`
Expected: PASS (the new test + all existing fixgen tests).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/audit_pipeline.py platform_v2/tests/test_audit_pipeline_fixgen.py
git commit -m "fix(self-heal): fix-gen emits git-appliable repo-relative diff header

_build_fix_diff passes the resolved repo-relative path (not a basename) to
CodeDiffEngine so the stored diff can be git applied from the worktree root.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Gate applies the diff for real (base-sync + fail-closed + revert)

**Files:**
- Modify: `platform_v2/services/proposal_service.py` — rewrite `_apply_fix_to_sandbox` (L1316-1369); update `_sandbox_gate` (L1372-1450: worktree root + revert)
- Test: `platform_v2/tests/test_sandbox_gate_fail_closed.py` (rewrite for the diff contract)

**Interfaces:**
- Consumes: `audit_pipeline.resolve_proposal_source(rel) -> (abs_path, display, status)` for the in-container prod path of each touched file. Unified-diff `code_changes` from Task 1.
- Produces: `_apply_fix_to_sandbox(sandbox_path: str, code_changes: str) -> {"applied": list[str], "expected": int, "error": str|None}` — NEW contract: `code_changes` is a unified-diff STRING; `sandbox_path` is the worktree ROOT `/mnt/archie_sandbox`. On success `applied` is the repo-relative touched files; on any failure `error` is set and nothing is left half-applied that the caller won't revert.

- [ ] **Step 1: Rewrite the tests (failing)**

Replace the body of `platform_v2/tests/test_sandbox_gate_fail_closed.py` (the module docstring at top may stay) with the new diff-contract tests:

```python
import os
import subprocess

import services.proposal_service as ps

_DIFF = (
    "--- a/platform_v2/tools/brainstorm/__init__.py\n"
    "+++ b/platform_v2/tools/brainstorm/__init__.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-x = 1\n"
    "+x = 2\n"
)


def test_apply_fails_closed_when_worktree_not_mounted(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is not None
    assert "mount" in res["error"].lower()
    assert res["applied"] == []


def test_apply_rejects_non_string_changes(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", [{"file_path": "x", "content": "y"}])
    assert res["error"] is not None


def test_apply_rejects_diff_with_no_targets(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", "not a diff, no +++ lines")
    assert res["error"] is not None
    assert res["expected"] == 0


def test_apply_rejects_out_of_worktree_target(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    diff = "--- a/standalone_x/app.py\n+++ b/standalone_x/app.py\n@@ -1 +1 @@\n-a\n+b\n"
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", diff)
    assert res["error"] is not None
    assert "worktree" in res["error"].lower()


def test_apply_fails_closed_on_git_apply_check_drift(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    # base-sync resolves + copies fine ...
    monkeypatch.setattr(ps, "_basesync_touched", lambda root, touched: None)
    # ... but git apply --check reports the diff no longer applies (drift)
    def _run(cmd, **k):
        if "--check" in cmd:
            return subprocess.CompletedProcess(cmd, 1, b"", b"patch does not apply")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(subprocess, "run", _run)
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is not None
    assert "apply" in res["error"].lower()
    assert res["applied"] == []


def test_apply_happy_path_returns_touched(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(ps, "_basesync_touched", lambda root, touched: None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, b"", b""))
    res = ps._apply_fix_to_sandbox("/mnt/archie_sandbox", _DIFF)
    assert res["error"] is None
    assert res["applied"] == ["platform_v2/tools/brainstorm/__init__.py"]


def test_sandbox_gate_bails_before_qa_when_apply_fails(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: False)  # worktree "not mounted"
    import services.qa_service as qs
    qa_called = {"v": False}
    monkeypatch.setattr(qs, "run_suite", lambda *a, **k: qa_called.__setitem__("v", True) or {"passed": 1, "total": 1, "run_id": 9})
    out = ps._sandbox_gate(1, {"id": 1, "code_changes": _DIFF})
    assert out["passed"] is False
    assert qa_called["v"] is False, "gate ran QA against stale code — not fail-closed"
    assert out.get("error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_sandbox_gate_fail_closed.py -v'`
Expected: FAIL — the old `_apply_fix_to_sandbox` treats `_DIFF` (a str) via `json.loads` → error path differs; `_basesync_touched` doesn't exist yet.

- [ ] **Step 3: Rewrite `_apply_fix_to_sandbox` + add `_basesync_touched`**

Replace `_apply_fix_to_sandbox` (proposal_service.py:1316-1369) with:

```python
def _basesync_touched(worktree_root, touched):
    """Copy each touched file's CURRENT prod source into the staging worktree so
    `git apply --check` measures drift against what the fix was cut from. Reuses
    the audit resolver (single source of truth for in-container prod paths:
    platform_v2/* -> /app, ai_bridge/* -> real path). Raises on any miss (fail-closed).
    """
    import os
    import shutil

    from services.audit_pipeline import resolve_proposal_source

    for rel in touched:
        prod_abs, _display, status = resolve_proposal_source(rel)
        if status != "ok" or not prod_abs:
            raise RuntimeError(f"cannot resolve prod source for {rel} (status={status})")
        dest = os.path.join(worktree_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(prod_abs, dest)


def _apply_fix_to_sandbox(sandbox_path, code_changes):
    """Apply a proposal's unified-diff ``code_changes`` into the staging worktree.

    NEW CONTRACT (2026-07-18, HoloDeck-P0): ``code_changes`` is a unified DIFF
    string with repo-relative headers (``a/platform_v2/...``, ``b/ai_bridge/...``);
    ``sandbox_path`` is the worktree ROOT ``/mnt/archie_sandbox``. Base-syncs each
    touched file from live prod, then ``git apply --check`` (FAIL CLOSED on drift)
    then ``git apply``. Returns {"applied":[rel,...], "expected":int, "error":str|None}.
    The caller MUST revert ``applied`` afterward.
    """
    import os
    import subprocess
    import tempfile

    result = {"applied": [], "expected": 0, "error": None}

    if not os.path.isdir(sandbox_path):
        result["error"] = (
            f"sandbox worktree {sandbox_path} is not mounted/present in this "
            f"container — cannot apply fix; gate fails closed"
        )
        return result
    if not isinstance(code_changes, str) or not code_changes.strip():
        result["error"] = "code_changes is not a unified-diff string — nothing to validate"
        return result

    touched = [ln[len("+++ b/") :].strip() for ln in code_changes.splitlines() if ln.startswith("+++ b/")]
    if not touched:
        result["error"] = "diff has no target files (+++ b/...) — nothing to validate"
        return result
    result["expected"] = len(touched)

    for rel in touched:
        if not (rel.startswith("platform_v2/") or rel.startswith("ai_bridge/")):
            result["error"] = f"{rel} is not in the staging worktree (platform_v2/ or ai_bridge/) — cannot gate"
            return result

    # Base-sync so --check measures drift against current prod.
    try:
        _basesync_touched(sandbox_path, touched)
    except Exception as sync_err:
        result["error"] = f"base-sync failed: {sync_err}"
        return result

    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
            fh.write(code_changes)
            tmp = fh.name
        check = subprocess.run(
            ["git", "-C", sandbox_path, "apply", "--check", tmp],
            capture_output=True, timeout=30,
        )
        if check.returncode != 0:
            # Revert the base-synced files so the worktree is left clean.
            subprocess.run(["git", "-C", sandbox_path, "checkout", "--", *touched], capture_output=True, timeout=30)
            result["error"] = f"git apply --check failed (drift/unapplicable): {check.stderr.decode()[:300]}"
            return result
        applied = subprocess.run(
            ["git", "-C", sandbox_path, "apply", tmp],
            capture_output=True, timeout=30,
        )
        if applied.returncode != 0:
            subprocess.run(["git", "-C", sandbox_path, "checkout", "--", *touched], capture_output=True, timeout=30)
            result["error"] = f"git apply failed: {applied.stderr.decode()[:300]}"
            return result
        result["applied"] = touched
        return result
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
```

- [ ] **Step 4: Point `_sandbox_gate` at the worktree ROOT and add revert**

In `_sandbox_gate` (proposal_service.py:1384) change:

```python
    sandbox_path = "/mnt/archie_sandbox/platform_v2"
```
to:
```python
    sandbox_path = "/mnt/archie_sandbox"  # worktree root; .git resolves here
```

Then wrap the restart + QA block (L1404-1450) so the worktree is ALWAYS reverted. Replace the "Restart archie_staging" + "Run P.R.O.B.E. suite #79" section with:

```python
    def _revert_and_restart():
        import subprocess
        if applied_files:
            subprocess.run(["git", "-C", sandbox_path, "checkout", "--", *applied_files], capture_output=True, timeout=30)
        subprocess.run(
            ["docker", "compose", "--file", "/mnt/archie_brain/docker-compose.staging.yml", "restart", "archie_staging"],
            capture_output=True, timeout=30,
        )

    try:
        import subprocess
        import time

        # Restart archie_staging so the applied change takes effect.
        subprocess.run(
            ["docker", "compose", "--file", "/mnt/archie_brain/docker-compose.staging.yml", "restart", "archie_staging"],
            timeout=30, capture_output=True,
        )
        time.sleep(5)

        from services.qa_service import run_suite

        result = run_suite(79, triggered_by=f"tiered_approval_gate_proposal_{proposal_id}")
        passed = result.get("passed", 0)
        total = result.get("total", 0)
        run_id = result.get("run_id")
        gate_passed = total > 0 and passed == total
        return {
            "passed": gate_passed,
            "passed_count": passed,
            "total": total,
            "run_id": run_id,
            "applied_files": applied_files,
            "error": None,
        }
    except Exception as qa_err:
        logger.error("sandbox_gate: QA run failed: %s", qa_err)
        return {
            "passed": False, "passed_count": 0, "total": 0, "run_id": None,
            "applied_files": applied_files, "error": str(qa_err),
        }
    finally:
        try:
            _revert_and_restart()
        except Exception as rev_err:
            logger.error("sandbox_gate: revert failed for #%s — staging may be dirty: %s", proposal_id, rev_err)
```

(The earlier `if code_changes: apply_res = _apply_fix_to_sandbox(...)` block at L1390-1402 is unchanged; `applied_files = apply_res["applied"]` feeds the revert.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_sandbox_gate_fail_closed.py -v'`
Expected: PASS (all 7 tests).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/proposal_service.py platform_v2/tests/test_sandbox_gate_fail_closed.py
git commit -m "fix(self-heal): sandbox gate git-applies the fix diff (base-sync + fail-closed + revert)

_apply_fix_to_sandbox now takes a unified diff, base-syncs each touched file from
live prod (via resolve_proposal_source), git apply --check (fail-closed on drift)
then git apply into /mnt/archie_sandbox; _sandbox_gate reverts in a finally so
staging returns clean. deploy_to_production untouched (still theater).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Reversibly archive the 43 legacy pre-format blobs

**Files:**
- Modify: `platform_v2/services/audit_pipeline.py` (add `_is_legacy_blob`, `archive_legacy_diff_proposals`)
- Test: `platform_v2/tests/test_archive_legacy_blobs.py` (create)

**Interfaces:**
- Produces: `_is_legacy_blob(code_changes: str) -> bool` — True when a `ready_for_review` diff is NOT git-appliable (no repo-relative `--- a/platform_v2/` or `--- a/ai_bridge/` header). `archive_legacy_diff_proposals(dry_run: bool=False) -> {"matched": int, "archived": int, "ids": list[int]}` — reversible via `metadata.archived_by='gate_fix_legacy_blob'`.

- [ ] **Step 1: Write the failing test**

Create `platform_v2/tests/test_archive_legacy_blobs.py`:

```python
import services.audit_pipeline as ap


def test_legacy_basename_header_is_legacy():
    # pre-format: basename-only header (2647-style), or full-file blob
    assert ap._is_legacy_blob("--- a/__init__.py\n+++ b/__init__.py\n@@ -7,4 +7,4 @@\n-x\n+y\n") is True
    assert ap._is_legacy_blob("--- a/department_dispatcher.py\n+++ b/department_dispatcher.py\n@@ -1,10815 +1,6 @@\n") is True
    assert ap._is_legacy_blob('[{"file_path": "x.py", "content": "y"}]') is True


def test_modern_repo_relative_diff_is_not_legacy():
    modern = "--- a/platform_v2/tools/brainstorm/__init__.py\n+++ b/platform_v2/tools/brainstorm/__init__.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert ap._is_legacy_blob(modern) is False
    modern_bridge = "--- a/ai_bridge/x.py\n+++ b/ai_bridge/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert ap._is_legacy_blob(modern_bridge) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_archive_legacy_blobs.py -v'`
Expected: FAIL — `_is_legacy_blob` not defined.

- [ ] **Step 3: Implement predicate + archive sweep**

Add to `audit_pipeline.py`:

```python
def _is_legacy_blob(code_changes):
    """True when a ready_for_review diff is NOT git-appliable (pre-format).

    Modern fix-gen (Task 1) emits repo-relative headers (--- a/platform_v2/... or
    --- a/ai_bridge/...). Legacy proposals carry basename headers or JSON full-file
    blobs → they can never git apply and must be archived + regenerated.
    """
    if not isinstance(code_changes, str) or not code_changes.strip():
        return True
    return not ("--- a/platform_v2/" in code_changes or "--- a/ai_bridge/" in code_changes)


def archive_legacy_diff_proposals(dry_run=False):
    """Reversibly archive ready_for_review code_health_audit proposals whose diff
    is legacy/un-appliable. Reversible via metadata.archived_by='gate_fix_legacy_blob'.
    """
    from services.time_utils import now_utc

    matched, archived, ids = 0, 0, []
    with get_db_cursor(commit=not dry_run) as (conn, cur):
        cur.execute(
            """SELECT id, code_changes FROM improvement_proposals
               WHERE status = 'ready_for_review' AND metadata->>'source' = 'code_health_audit'"""
        )
        rows = cur.fetchall()
        for row in rows:
            if not _is_legacy_blob(row["code_changes"]):
                continue
            matched += 1
            ids.append(row["id"])
            if dry_run:
                continue
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = 'archived',
                       metadata = jsonb_set(
                         jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                   '{archived_by}', '"gate_fix_legacy_blob"'),
                         '{archived_at}', to_jsonb(%s::text))
                   WHERE id = %s""",
                (now_utc().isoformat(), row["id"]),
            )
            archived += 1
    return {"matched": matched, "archived": archived, "ids": ids}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_archive_legacy_blobs.py -v'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/audit_pipeline.py platform_v2/tests/test_archive_legacy_blobs.py
git commit -m "fix(self-heal): reversible archive of legacy un-appliable ready_for_review blobs

_is_legacy_blob flags pre-format diffs (basename header / JSON full-file);
archive_legacy_diff_proposals sweeps them to archived (archived_by=gate_fix_legacy_blob,
reversible). Clears the false 43-ready signal so only git-appliable diffs flow.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Deploy, run the archive sweep, and live-verify the gate end-to-end

**Files:** none (deploy + verification + evidence capture)

**Interfaces:** consumes Tasks 1-3 (deployed).

- [ ] **Step 1: Deploy the branch code to the running platform**

Run: `docker compose restart archie_platform` then wait for healthy:
`docker exec archie_platform sh -lc 'cd /app && python3 -c "import services.proposal_service, services.audit_pipeline; print(\"import ok\")"'`
Expected: `import ok`.

- [ ] **Step 2: Dry-run then run the legacy archive sweep**

Run (dry-run first):
`docker exec archie_platform sh -lc 'cd /app && python3 -c "from services.audit_pipeline import archive_legacy_diff_proposals as a; print(a(dry_run=True))"'`
Expected: `{'matched': 43, 'archived': 0, 'ids': [...]}` (≈43 — confirm it targets the legacy set, not modern diffs).
Then commit the change for real:
`docker exec archie_platform sh -lc 'cd /app && python3 -c "from services.audit_pipeline import archive_legacy_diff_proposals as a; print(a(dry_run=False))"'`
Expected: `archived` == `matched`. Verify `ready_for_review` count via:
`docker exec archie_database psql -U archie -d archie -c "SELECT status, count(*) FROM improvement_proposals WHERE metadata->>'source'='code_health_audit' GROUP BY 1 ORDER BY 2 DESC;"`

- [ ] **Step 3: Generate ONE fresh fix on a small leaf file**

Pick a small, low-risk `platform_v2/*` proposal still `pending`/`approved` (prefer a PYFLAKES/WRONG_SUBMODULE_IMPORT in a leaf module). Generate its fix through the real app context:
`docker exec archie_platform sh -lc 'cd /app && python3 -c "from services.audit_pipeline import dispatch_proposal_fix as d; print(d(<PROPOSAL_ID>))"'`
Expected: `{'success': True, ...}`; then confirm its stored diff is repo-relative:
`docker exec archie_database psql -U archie -d archie -P pager=off -t -c "SELECT left(code_changes,90) FROM improvement_proposals WHERE id=<PROPOSAL_ID>;"`
Expected: header begins `--- a/platform_v2/...`.

- [ ] **Step 4: Run the sandbox gate against live archie_staging and confirm the full cycle**

Run:
`docker exec archie_platform sh -lc 'cd /app && python3 -c "import services.proposal_service as ps, psycopg2, os; from database import get_db_cursor;\nwith get_db_cursor() as (c,cur):\n cur.execute(\"SELECT * FROM improvement_proposals WHERE id=%s\", (<PROPOSAL_ID>,)); p=dict(cur.fetchone())\nprint(ps._sandbox_gate(<PROPOSAL_ID>, p))"'`
Expected: a dict with `error: None` and a real `total > 0` (suite #79 ran) — `passed` True or False is fine (either is a REAL result, the point is it applied + tested rather than fail-closing on format).
Then confirm the worktree reverted to clean:
`git -C /mnt/archie_sandbox status --porcelain` → empty; `git -C /mnt/archie_sandbox branch --show-current` → `_sandbox_preview`.

- [ ] **Step 5: Capture evidence + regression sweep**

Run the full relevant test set green:
`docker exec archie_platform sh -lc 'cd /app && python3 -m pytest tests/test_audit_pipeline_fixgen.py tests/test_sandbox_gate_fail_closed.py tests/test_archive_legacy_blobs.py tests/test_resolve_proposal_source.py -v'`
Expected: all PASS. Record the Step-4 gate output (applied file, suite run_id, pass/total, clean worktree) as the completion evidence.

- [ ] **Step 6: Commit any doc/evidence + open PR**

No code change expected in this task; if Step 4 forced a small correction (e.g. exact `git` invocation), commit it. Then open the PR via `/commit-push-pr` for F.O.R.G.E. review. Do NOT merge — F.O.R.G.E. review + human `/merge-pr`.

---

## Self-Review

**1. Spec coverage:**
- Component 1 (repo-relative diff) → Task 1. ✓
- Component 2 (git apply --check fail-closed + base-sync + revert; worktree root; only platform_v2/ai_bridge) → Task 2. ✓
- Component 3 (reversible archive of 43 legacy) → Task 3 + Task 4 Step 2. ✓
- Safety boundary (deploy_to_production untouched, no prod write) → Global Constraints + not modified in any task. ✓
- Base-sync requirement (diff cut vs prod, applied in staging) → Task 2 `_basesync_touched` + Global Constraints. ✓
- Verification against live archie_staging → Task 4. ✓

**2. Placeholder scan:** `<PROPOSAL_ID>` in Task 4 is a runtime-selected id (chosen at execution from live data), not a code placeholder — acceptable for a verification step. No TBD/TODO/"handle edge cases". ✓

**3. Type consistency:** `_build_fix_diff(old, new, repo_rel_path) -> (diff_text, stats)` used consistently (Task 1). `_apply_fix_to_sandbox(sandbox_path, code_changes:str) -> {"applied","expected","error"}` consistent between Task 2 impl + tests + `_sandbox_gate` consumer (`apply_res["applied"]` → `applied_files` → revert). `_basesync_touched(worktree_root, touched)` defined + monkeypatched by name in tests. `_is_legacy_blob(code_changes)->bool` + `archive_legacy_diff_proposals(dry_run)->dict` consistent (Task 3 + Task 4). ✓

**Note for executor:** Task 2 Step 4 edits a specific line range; the exact surrounding lines may shift — match on the code content (`sandbox_path = "/mnt/archie_sandbox/platform_v2"` and the restart/QA block), not the line numbers. Confirm the `git -C /mnt/archie_sandbox apply` invocation works in-container during Task 4 (the `.git` worktree file resolves because `/mnt/archie_brain/.git` is mounted rw) and adjust the invocation there if needed.
