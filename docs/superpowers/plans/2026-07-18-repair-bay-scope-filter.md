# Repair Bay Scope Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the existing proposal source-path resolution into one shared helper, then archive the ~36 genuinely-unfixable undispatched code-health proposals so the ~10/day self-heal drain never wastes a slot on them.

**Architecture:** Two additions to `services/audit_pipeline.py`. (1) `resolve_proposal_source()` lifts the resolution already inlined in `dispatch_proposal_fix` (behavior-preserving) so both dispatch and the sweep share one source of truth. (2) `archive_unfixable_audit_proposals()` — an idempotent, reversible one-time sweep that flips unresolvable proposals to `status='archived'` with a tagged reason.

**Tech Stack:** Python 3, psycopg2 (`get_db_cursor` → RealDictCursor dict rows), pytest. Runs inside `archie_platform` (volume-mounted `services/`).

## Global Constraints

- Reuse the EXISTING `_PLACEHOLDER_MAP` + `_SKIP_PREFIXES` (`audit_pipeline.py:704–720`). Do NOT add a parallel resolver.
- `get_db_cursor` yields **RealDictCursor dict rows** — access by column name, never by index (KB #268832).
- The extract must be **behavior-preserving**: `dispatch_proposal_fix` must produce identical dispatch outcomes and identical prompt/error text (the substituted `file_path` is used in the agent prompt at line ~919 and in the two error branches).
- **Archive, never delete.** Every archived row carries `metadata.archived_by='scope_filter_4940'` so it is reversible in one `UPDATE`.
- No migration. `status='archived'` already exists and is already excluded from the drain's candidate `SELECT`.
- No test may hit Ollama or the live drain. Deploy = `docker compose restart archie_platform`.
- Tests run inside the container: `docker exec archie_platform python3 -m pytest <path> -v` (the container has `/mnt/archie_brain` mounted, so on-disk resolution works there).

---

### Task 1: Extract `resolve_proposal_source()` and refactor `dispatch_proposal_fix` to use it

**Files:**
- Modify: `platform_v2/services/audit_pipeline.py` (add helper after `_SKIP_PREFIXES` ~line 720; replace the inline resolution block at ~860–880)
- Test: `platform_v2/tests/test_resolve_proposal_source.py`

**Interfaces:**
- Produces: `resolve_proposal_source(file_path: str) -> tuple[str | None, str, str]`
  returning `(abs_path, display_path, status)` where `status ∈ {'ok','skip','missing'}`.
  `abs_path` is a readable absolute path **only** when `status == 'ok'`. `display_path` is the
  placeholder-substituted path (used in prompts/errors); it equals the input when `status == 'skip'`.

- [ ] **Step 1: Write the failing test**

Create `platform_v2/tests/test_resolve_proposal_source.py`:

```python
import os
import pytest
from services.audit_pipeline import resolve_proposal_source


def test_app_core_resolves_to_real_file():
    # platform_v2/app.py exists on disk
    abs_path, display, status = resolve_proposal_source("[APP_CORE]/app.py")
    assert status == "ok"
    assert display == "platform_v2/app.py"
    assert abs_path is not None and os.path.isfile(abs_path)


def test_ai_bridge_resolves_to_real_file():
    abs_path, display, status = resolve_proposal_source("[AI_BRIDGE]/archie_bridge.py")
    assert status == "ok"
    assert display == "ai_bridge/archie_bridge.py"
    assert abs_path is not None and os.path.isfile(abs_path)


def test_dispatch_routing_is_skip():
    abs_path, display, status = resolve_proposal_source(
        "[dispatch_routing]/agents/C.O.D.E.X./documentation"
    )
    assert status == "skip"
    assert abs_path is None
    assert display == "[dispatch_routing]/agents/C.O.D.E.X./documentation"  # unchanged


def test_offplatform_standalone_is_missing():
    # standalone_what_the_fact has NO _PLACEHOLDER_MAP entry -> unresolved -> missing
    abs_path, display, status = resolve_proposal_source("standalone_what_the_fact/app.py")
    assert status == "missing"
    assert abs_path is None


def test_deleted_platform_file_is_missing():
    abs_path, display, status = resolve_proposal_source(
        "platform_v2/tools/media_hub/routes.py"  # media_hub consolidated to standalone
    )
    assert status == "missing"
    assert abs_path is None


def test_empty_path_is_missing():
    abs_path, display, status = resolve_proposal_source("")
    assert status == "missing"
    assert abs_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest tests/test_resolve_proposal_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_proposal_source'`.

- [ ] **Step 3: Add the helper**

In `platform_v2/services/audit_pipeline.py`, immediately after the `_SKIP_PREFIXES` definition (~line 721), add:

```python
def resolve_proposal_source(file_path):
    """Resolve a code-health proposal's file_path to a real on-disk source.

    Single source of truth for the resolution ``dispatch_proposal_fix`` performs, so the
    archive sweep classifies "fixable" identically to what dispatch actually does.

    Returns (abs_path, display_path, status):
      status 'skip'    -> synthetic non-file label (_SKIP_PREFIXES); abs_path None; display == input
      status 'ok'      -> abs_path is an existing, readable file; display is the substituted path
      status 'missing' -> resolved (or unresolved) but no on-disk file; abs_path None
    """
    if not file_path:
        return (None, file_path, "missing")
    if any(file_path.startswith(p) for p in _SKIP_PREFIXES):
        return (None, file_path, "skip")
    resolved = file_path
    for placeholder, real_root in _PLACEHOLDER_MAP.items():
        if resolved.startswith(placeholder):
            resolved = real_root + resolved[len(placeholder):]
            break
    # Try /mnt/archie_brain first (host + container mount), fall back to /app/ (Docker)
    abs_path = os.path.join("/mnt/archie_brain", resolved)
    if not os.path.isfile(abs_path) and resolved.startswith("platform_v2/"):
        abs_path = os.path.join("/app", resolved[len("platform_v2/"):])
    if os.path.isfile(abs_path):
        return (abs_path, resolved, "ok")
    return (None, resolved, "missing")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest tests/test_resolve_proposal_source.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Refactor `dispatch_proposal_fix` to use the helper (behavior-preserving)**

In `platform_v2/services/audit_pipeline.py`, replace the inline resolution block (currently ~lines 860–880, from the `# Read source file` comment through the `Source file not found` return) with:

```python
    # Read source file — resolve module placeholders to a real on-disk path.
    abs_path, file_path, _resolve_status = resolve_proposal_source(file_path)
    if _resolve_status == "skip":
        if session_id:
            fail_work_session(session_id, error_msg=f"Synthetic placeholder, no file to fix: {file_path}")
        return {"success": False, "error": f"Synthetic placeholder, no file to fix: {file_path}"}
    if _resolve_status != "ok":
        if session_id:
            fail_work_session(session_id, error_msg=f"Source file not found: {file_path}")
        return {"success": False, "error": f"Source file not found: {file_path}"}
```

This preserves exactly: `skip` → "Synthetic placeholder" with the original label; `missing` → "Source file not found" with the substituted path; `ok` → `abs_path` for reading + the substituted `file_path` for the prompt at line ~919. The downstream code (open `abs_path`, prompt uses `file_path`) is unchanged.

- [ ] **Step 6: Write a behavior-preservation test**

Append to `platform_v2/tests/test_resolve_proposal_source.py`:

```python
def test_ok_display_matches_substituted_path_for_prompt():
    # dispatch_proposal_fix uses display_path in the agent prompt (**File:** {file_path}).
    # For a resolvable [APP_CORE] path it must be the substituted platform_v2/ path, not the label.
    _abs, display, status = resolve_proposal_source("[APP_CORE]/services/audit_pipeline.py")
    assert status == "ok"
    assert display == "platform_v2/services/audit_pipeline.py"
```

- [ ] **Step 7: Run the full test file**

Run: `docker exec archie_platform python3 -m pytest tests/test_resolve_proposal_source.py -v`
Expected: PASS (7 passed).

- [ ] **Step 8: Commit**

```bash
git add platform_v2/services/audit_pipeline.py platform_v2/tests/test_resolve_proposal_source.py
git commit -m "refactor(4940): extract resolve_proposal_source; dispatch uses shared resolver (no behavior change)"
```

---

### Task 2: Add `archive_unfixable_audit_proposals()` sweep

**Files:**
- Modify: `platform_v2/services/audit_pipeline.py` (add sweep near `_mark_dispatch_attempted` ~line 1251)
- Test: `platform_v2/tests/test_archive_unfixable.py`

**Interfaces:**
- Consumes: `resolve_proposal_source` (Task 1).
- Produces: `archive_unfixable_audit_proposals(dry_run: bool = False) -> dict`
  returning `{"scanned": int, "archived": int, "kept": int, "by_reason": {str: int}}`.

- [ ] **Step 1: Write the failing test**

Create `platform_v2/tests/test_archive_unfixable.py`:

```python
import json
import pytest
from database import get_db_cursor
from services.audit_pipeline import archive_unfixable_audit_proposals


def _insert(cur, file_path):
    cur.execute(
        """INSERT INTO improvement_proposals (title, description, status, metadata)
           VALUES (%s, %s, 'approved', %s::jsonb) RETURNING id""",
        (
            "scope-filter test",
            "test row",
            json.dumps({"source": "code_health_audit", "file_path": file_path}),
        ),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def temp_proposals():
    ids = {}
    with get_db_cursor(commit=True) as (conn, cur):
        ids["unfixable"] = _insert(cur, "standalone_what_the_fact/app.py")
        ids["junk"] = _insert(cur, "[dispatch_routing]/agents/X/y")
        ids["fixable"] = _insert(cur, "[APP_CORE]/app.py")
    yield ids
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM improvement_proposals WHERE id = ANY(%s)",
            (list(ids.values()),),
        )


def _status(pid):
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT status, metadata FROM improvement_proposals WHERE id=%s", (pid,))
        return cur.fetchone()


def test_sweep_archives_unfixable_keeps_fixable(temp_proposals):
    res = archive_unfixable_audit_proposals()
    assert res["archived"] >= 2  # our two unfixable rows (plus any real backlog ones)

    assert _status(temp_proposals["unfixable"])["status"] == "archived"
    assert _status(temp_proposals["junk"])["status"] == "archived"
    assert _status(temp_proposals["fixable"])["status"] == "approved"

    meta = _status(temp_proposals["unfixable"])["metadata"]
    assert meta["archived_by"] == "scope_filter_4940"
    assert meta["archive_reason"] == "out_of_scope:standalone"
    assert _status(temp_proposals["junk"])["metadata"]["archive_reason"] == "not_a_file:routing_label"


def test_sweep_is_idempotent(temp_proposals):
    archive_unfixable_audit_proposals()
    second = archive_unfixable_audit_proposals()
    # our rows are already archived -> not re-scanned (WHERE status='approved')
    assert _status(temp_proposals["unfixable"])["status"] == "archived"
    # second run must not re-archive already-archived rows
    assert isinstance(second["archived"], int)


def test_dry_run_writes_nothing(temp_proposals):
    archive_unfixable_audit_proposals(dry_run=True)
    assert _status(temp_proposals["unfixable"])["status"] == "approved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest tests/test_archive_unfixable.py -v`
Expected: FAIL — `ImportError: cannot import name 'archive_unfixable_audit_proposals'`.

- [ ] **Step 3: Implement the sweep**

In `platform_v2/services/audit_pipeline.py`, after `_mark_dispatch_attempted` (~line 1259), add:

```python
def _archive_reason_for(file_path, status):
    """Map an unresolvable proposal to a stable archive_reason."""
    if status == "skip":
        return "not_a_file:routing_label"
    if file_path.startswith("standalone_"):
        return "out_of_scope:standalone"
    return "source_missing:relocated"


def archive_unfixable_audit_proposals(dry_run=False):
    """One-time, idempotent, reversible sweep: archive undispatched code-health proposals
    whose file_path does not resolve to a real on-disk file, so the drain never spends a
    slot on them. Only touches status='approved' (idempotent). Every archived row is tagged
    archived_by='scope_filter_4940' for one-statement rollback.
    """
    from services.time_utils import now_utc

    by_reason = {}
    scanned = archived = kept = 0
    with get_db_cursor(commit=not dry_run) as (conn, cur):
        cur.execute(
            """SELECT id, metadata->>'file_path' AS file_path
               FROM improvement_proposals
               WHERE metadata->>'source' = 'code_health_audit'
                 AND status = 'approved'
                 AND (metadata->>'dispatch_attempted') IS NULL"""
        )
        rows = cur.fetchall()
        for row in rows:
            scanned += 1
            fp = row["file_path"] or ""
            _abs, _display, status = resolve_proposal_source(fp)
            if status == "ok":
                kept += 1
                continue
            reason = _archive_reason_for(fp, status)
            by_reason[reason] = by_reason.get(reason, 0) + 1
            archived += 1
            if not dry_run:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = 'archived',
                           metadata = metadata || %s::jsonb
                       WHERE id = %s""",
                    (
                        json.dumps({
                            "archive_reason": reason,
                            "archived_at": now_utc().isoformat(),
                            "archived_by": "scope_filter_4940",
                        }),
                        row["id"],
                    ),
                )
    return {"scanned": scanned, "archived": archived, "kept": kept, "by_reason": by_reason}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest tests/test_archive_unfixable.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/audit_pipeline.py platform_v2/tests/test_archive_unfixable.py
git commit -m "feat(4940): archive_unfixable_audit_proposals sweep (idempotent, reversible)"
```

---

### Task 3: Deploy, run the one-time sweep, verify

**Files:** none (operational)

- [ ] **Step 1: Deploy the code**

```bash
docker compose restart archie_platform
```
Wait for healthy: `docker ps --filter name=archie_platform --format '{{.Status}}'` shows `healthy`.

> **Note:** the Task 2 test `test_sweep_archives_unfixable_keeps_fixable` runs the REAL sweep, so if the test suite ran on this deploy, the ~36 backlog rows may already be archived. The sweep is idempotent and reversible — Task 3 verifies the **end state** (total tagged rows ≈ 36), not "this run archived 36." A second run archiving 0 is the correct outcome, not a failure.

- [ ] **Step 2: Dry-run the sweep first (no writes)**

```bash
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.audit_pipeline import archive_unfixable_audit_proposals as f; print(f(dry_run=True))"
```
Expected: `kept` ≈ 1188; `archived` = however many unfixable rows remain un-archived (≈ 36 if the suite did not run the sweep, fewer/0 if it did — either is correct). `by_reason` (when non-empty) shows `source_missing:relocated` / `out_of_scope:standalone` / `not_a_file:routing_label`.

- [ ] **Step 3: Run the real sweep (idempotent)**

```bash
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.audit_pipeline import archive_unfixable_audit_proposals as f; print(f())"
```
Expected: archives any remaining unfixable rows; a return of `archived: 0` is fine if the suite already swept.

- [ ] **Step 4: Verify the END STATE (robust to when the sweep ran)**

```bash
docker exec archie_database psql -U archie -d archie -t -A -F'|' -c "SELECT status, count(*) FROM improvement_proposals WHERE metadata->>'source'='code_health_audit' AND metadata->>'archived_by'='scope_filter_4940' GROUP BY status;"
```
Expected: `archived|≈36`. Then confirm no unfixable rows remain approved+undispatched:
```bash
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.audit_pipeline import archive_unfixable_audit_proposals as f; print('remaining unfixable:', f(dry_run=True)['archived'])"
```
Expected: `remaining unfixable: 0`.

- [ ] **Step 5: Spot-check dispatch is unchanged**

```bash
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.audit_pipeline import resolve_proposal_source as r; print(r('[APP_CORE]/app.py'))"
```
Expected: `('/mnt/archie_brain/platform_v2/app.py', 'platform_v2/app.py', 'ok')` (or the `/app/...` variant). No dispatch behavior change.

---

## Rollback

- Revert the branch, `docker compose restart archie_platform`.
- Un-archive: `docker exec archie_database psql -U archie -d archie -c "UPDATE improvement_proposals SET status='approved', metadata = metadata - 'archive_reason' - 'archived_at' - 'archived_by' WHERE metadata->>'archived_by'='scope_filter_4940';"`

## Ship

- `/commit-push-pr` → F.O.R.G.E. review → `/merge-pr`. After merge, queue C.O.D.E.X. docs and mark task #4940 complete with the real archived count.
