"""Phase 1 of the self-repair lifecycle completion (spec 2026-08-26).

Every test here pins a SILENT failure measured on 2026-08-26 (KB #296234):
statuses that flipped without their action happening, or code paths that
referenced schema that does not exist and failed invisibly. Falsifiability:
each test was run against the PRE-FIX code first and failed.
"""

import ast
import inspect
from pathlib import Path


def test_prop_meta_is_assigned_before_the_qa_trigger():
    """#6044: run_proposal called _trigger_module_qa(prop_meta, ...) with prop_meta
    never assigned — NameError on every SUCCESSFUL deploy, reported as failure,
    so post-deploy P.R.O.B.E. QA + the perf gate never fired (0 runs ever)."""
    import services.proposal_service as ps

    src = inspect.getsource(ps.run_proposal)
    fn = ast.parse(src).body[0]
    assigned = {
        t.id for node in ast.walk(fn) if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name)
    }
    calls_qa = any(
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_trigger_module_qa" for node in ast.walk(fn)
    )
    assert calls_qa, "run_proposal no longer calls _trigger_module_qa — update this test"
    assert "prop_meta" in assigned, "prop_meta is used at the QA trigger but never assigned (#6044)"


def test_archive_proposal_actually_archives():
    """#6045: archive_proposal UPDATEd nonexistent archived_at — the endpoint
    returned success:False on EVERY call (probe recorded 2026-08-26: UndefinedColumn).
    Round-trips a throwaway row through the REAL function."""
    from database import get_db_cursor
    from services.proposal_service import archive_proposal

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO improvement_proposals (title, description, status, proposed_at)
               VALUES ('t2-archive-test', 'throwaway', 'proposed', NOW()) RETURNING id"""
        )
        pid = cur.fetchone()["id"]
    try:
        result = archive_proposal(pid)
        assert result.get("success") is True, result
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, metadata->>'archived_by' AS by FROM improvement_proposals WHERE id = %s",
                (pid,),
            )
            row = cur.fetchone()
        assert row["status"] == "archived" and row["by"] == "repair_bay_api"
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (pid,))


def test_archive_proposal_unknown_id_is_not_found():
    """The bogus-id path must be a clean 404, not a column error."""
    from services.proposal_service import archive_proposal

    result = archive_proposal(999999999)
    assert result.get("success") is False
    assert "not found" in (result.get("error") or "").lower()


def test_scan_bridge_names_only_real_columns():
    """#6045: the issues-to-proposals INSERT named nonexistent file_path and put
    the string 'scan_bridge' into integer proposed_by; its dedup queried the same
    phantom column and FAILED OPEN. file_path lives in metadata."""
    src = Path("/app/tools/repair_bay/scan_routes.py").read_text()
    assert "'scan_bridge'" not in src, "string literal into integer proposed_by"
    assert "file_path, category, priority" not in src, "INSERT still names the phantom file_path column"
    assert "WHERE file_path = " not in src, "dedup still queries the phantom column (fails open)"


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


def test_stale_audit_bridge_reads_metadata_not_phantom_column():
    """#6045: deploy_via_merge's Code Health bridge SELECTed the nonexistent
    file_path column inside a swallowed except — merged fixes never invalidated
    stale module audits, silently, since the bridge shipped."""
    src = Path("/app/tools/repair_bay/services/forge_pipeline.py").read_text()
    assert "SELECT file_path FROM improvement_proposals" not in src
    assert "metadata->>'file_path' FROM improvement_proposals" in src


def test_commit_hash_capture_survives_uid_mismatch():
    """#6046: bare `git rev-parse` (cwd=) hits 'dubious ownership' in the scheduler
    container, so snapshots stored empty commit_hash since 2026-03-23, disabling
    change detection. The invocation must carry -C + safe.directory (the
    hub_deploy_state.py invariant)."""
    src = Path("/app/services/code_metrics_service.py").read_text()
    assert '"-C", repo_path, "-c", f"safe.directory={repo_path}"' in src


# --- honest dashboard tiles (2026-08-27, owner-approved) ----------------------------------


def test_get_stats_reports_honest_tile_keys_with_consistent_arithmetic():
    """The dashboard tiles read these server-side counts. The invariants must hold by
    construction: `live` excludes archived+rejected; `completed_verified` is exactly the
    proof-carrying slice of `deployed` (code_applied='true' — everything else is either
    an explicit not_applied or an unverifiable legacy unknown)."""
    from services.proposal_service import get_stats

    result = get_stats()
    assert result.get("success") is True, result
    stats = result["stats"]
    for key in ("archived", "live", "completed_verified", "shipped_24h"):
        assert key in stats, f"missing additive stats key: {key}"
    assert stats["live"] == stats["total"] - stats["archived"] - stats["rejected"]
    assert stats["completed_verified"] == stats["deployed"] - stats["not_applied"] - stats["apply_unknown"]


def test_dashboard_tiles_read_server_stats_not_raw_list_lengths():
    """The 'Repairs' tile counted every row ever (75% archived sweepings), 'Completed'
    counted no-op deploys, and loadProposals overwrote the tile with the length of a
    FILTERED list. The tiles must read /proposals/stats and nothing else."""
    src = Path("/app/templates/tools/repair_bay.html").read_text()
    assert "/proposals/stats" in src
    assert "Completed (Verified)" in src
    assert "Completed (Total)" not in src
    assert "document.getElementById('statProposals').textContent = arr.length" not in src
    assert "document.getElementById('statProposals').textContent = proposals.length" not in src
    assert "fetch(API + '/proposals?status=deployed')" not in src
