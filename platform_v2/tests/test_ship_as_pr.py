"""Phase 2 of the self-repair lifecycle completion: git is the apply mechanism.

Spec: docs/superpowers/specs/2026-08-26-self-repair-lifecycle-completion-design.md
"""

from pathlib import Path

from tools.repair_bay.services.forge_pipeline import _proposal_fix_fields


class TestProposalFixFields:
    def test_fix_fields_resolve_from_metadata(self):
        """Audit-pipeline proposals carry file_path in metadata and the diff in
        code_changes — there is NO file_path column (information_schema 2026-08-26).
        deploy_via_forge previously read only the legacy attribute names and would
        have refused every audit proposal with 'no file_path'."""
        p = {"metadata": {"file_path": "tools/consciousness/routes.py"}, "code_changes": "--- a\n+++ b\n"}
        f = _proposal_fix_fields(p)
        assert f["file_path"] == "tools/consciousness/routes.py"
        assert f["code_diff"].startswith("---")

    def test_fix_fields_prefer_legacy_attributes_when_present(self):
        p = {"file_path": "x.py", "code_diff": "D", "metadata": {"file_path": "y.py"}, "code_changes": "C"}
        f = _proposal_fix_fields(p)
        assert f["file_path"] == "x.py" and f["code_diff"] == "D"

    def test_fix_fields_tolerate_string_metadata_and_absence(self):
        assert _proposal_fix_fields({"metadata": "{not json"})["file_path"] == ""
        assert _proposal_fix_fields({})["code_diff"] == ""


def test_no_deploy_path_reaches_the_noop_deploy():
    """Both deploy choke points must terminate in ship_as_pr. deploy_to_production
    (the #5808 no-op) may keep existing but nothing routes to it."""
    routes = Path("/app/tools/repair_bay/proposal_routes.py").read_text()
    mds = Path("/app/services/model_dispatch_service.py").read_text()
    assert "ship_as_pr(proposal_id)" in routes
    assert "proposal_service.deploy_to_production" not in routes
    assert "ship_as_pr(proposal_id, skip_gate=True)" in mds
    assert "import _sandbox_gate, deploy_to_production" not in mds


class TestShipAsPr:
    """ship_as_pr with the two expensive boundaries monkeypatched. Uses a real
    throwaway DB row so the status CHECK (migration 479) is exercised for real."""

    def _mk(self, status="ready_for_review"):
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals (title, description, status, proposed_at, code_changes)
                   VALUES ('t10-ship-test', 'throwaway', %s, NOW(), '--- a/x.py') RETURNING id""",
                (status,),
            )
            return cur.fetchone()["id"]

    def _rm(self, pid):
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM improvement_deployments WHERE proposal_id = %s", (pid,))
            cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (pid,))

    def _row(self, pid):
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT status, metadata, (SELECT count(*) FROM improvement_deployments d WHERE d.proposal_id = ip.id) AS deployments FROM improvement_proposals ip WHERE id = %s",
                (pid,),
            )
            return cur.fetchone()

    def test_gate_failure_ships_nothing(self, monkeypatch):
        import services.proposal_service as ps

        pid = self._mk()
        try:
            monkeypatch.setattr(ps, "_sandbox_gate", lambda i, p: {"passed": False, "passed_count": 0, "total": 3})
            r = ps.ship_as_pr(pid)
            assert r["success"] is False and "gate" in r
            row = self._row(pid)
            assert row["status"] == "ready_for_review", "gate failure must not move the status"
            assert row["deployments"] == 0, "gate failure must not create a deployment row"
        finally:
            self._rm(pid)

    def test_success_flips_to_pr_open_with_provenance(self, monkeypatch):
        import services.proposal_service as ps
        import tools.repair_bay.services.forge_pipeline as fp

        pid = self._mk()
        try:
            monkeypatch.setattr(ps, "_sandbox_gate", lambda i, p: {"passed": True, "passed_count": 3, "total": 3})
            monkeypatch.setattr(
                fp,
                "deploy_via_forge",
                lambda proposal, deployment_id, sandbox_results=None: {
                    "success": True,
                    "pr_number": 4242,
                    "pr_url": "https://github.com/x/pull/4242",
                    "branch": "archie/forge/test",
                    "method": "forge_pr",
                },
            )
            r = ps.ship_as_pr(pid)
            assert r["success"] is True
            row = self._row(pid)
            md = row["metadata"] or {}
            assert row["status"] == "pr_open"
            assert md.get("pr_number") == 4242 and md.get("apply_mode") == "forge_pr"
            assert md.get("code_applied") is False, "a PR is not applied code"
            assert row["deployments"] == 1
        finally:
            self._rm(pid)

    def test_no_change_leaves_status_alone(self, monkeypatch):
        import services.proposal_service as ps
        import tools.repair_bay.services.forge_pipeline as fp

        pid = self._mk()
        try:
            monkeypatch.setattr(ps, "_sandbox_gate", lambda i, p: {"passed": True, "passed_count": 3, "total": 3})
            monkeypatch.setattr(
                fp,
                "deploy_via_forge",
                lambda proposal, deployment_id, sandbox_results=None: {"success": True, "method": "no_change"},
            )
            r = ps.ship_as_pr(pid)
            assert r.get("method") == "no_change"
            assert self._row(pid)["status"] == "ready_for_review", "never claim a PR that does not exist"
        finally:
            self._rm(pid)

    def test_unshippable_status_is_refused(self):
        import services.proposal_service as ps

        pid = self._mk(status="deployed")
        try:
            r = ps.ship_as_pr(pid)
            assert r["success"] is False and "not shippable" in r["error"]
        finally:
            self._rm(pid)


class TestMergeCompletion:
    """complete_merged_fix_proposals with pr_merge_state monkeypatched."""

    def _mk_pr_open(self, pr_number):
        import json

        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals (title, description, status, proposed_at, metadata)
                   VALUES ('t11-completion-test', 'throwaway', 'pr_open', NOW(), %s::jsonb) RETURNING id""",
                (json.dumps({"pr_number": pr_number, "apply_mode": "forge_pr", "code_applied": False}),),
            )
            pid = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO improvement_deployments (proposal_id, backup_name, deployment_type, status)
                   VALUES (%s, 'forge_pr:git-revert', 'manual', 'deploying')""",
                (pid,),
            )
            return pid

    def _rm(self, pid):
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM improvement_deployments WHERE proposal_id = %s", (pid,))
            cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (pid,))

    def _row(self, pid):
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT status, metadata,
                          (SELECT status FROM improvement_deployments d
                           WHERE d.proposal_id = ip.id ORDER BY d.id DESC LIMIT 1) AS dep_status
                   FROM improvement_proposals ip WHERE id = %s""",
                (pid,),
            )
            return cur.fetchone()

    def test_merged_pr_completes_the_proposal_for_real(self, monkeypatch):
        import tools.repair_bay.services.github_service as gs
        from tools.repair_bay.services.forge_pipeline import complete_merged_fix_proposals

        pid = self._mk_pr_open(910001)
        try:
            monkeypatch.setattr(gs, "pr_merge_state", lambda pr, repo=None: "merged")
            res = complete_merged_fix_proposals()
            assert res["completed"] >= 1
            row = self._row(pid)
            md = row["metadata"] or {}
            assert row["status"] == "deployed"
            assert md.get("code_applied") is True, "deployed now MEANS merged (spec §6.4)"
            assert md.get("merged_pr") == 910001
            assert (
                row["dep_status"] == "deployed"
            ), "improvement_deployments must complete (370 stuck rows was the old state)"
        finally:
            self._rm(pid)

    def test_closed_unmerged_pr_reopens_the_fix(self, monkeypatch):
        import tools.repair_bay.services.github_service as gs
        from tools.repair_bay.services.forge_pipeline import complete_merged_fix_proposals

        pid = self._mk_pr_open(910002)
        try:
            monkeypatch.setattr(gs, "pr_merge_state", lambda pr, repo=None: "closed")
            complete_merged_fix_proposals()
            row = self._row(pid)
            assert row["status"] == "fix_requested"
            assert (row["metadata"] or {}).get("pr_closed_unmerged") == 910002
        finally:
            self._rm(pid)

    def test_github_blip_leaves_pr_open_rows_alone(self, monkeypatch):
        """The pr_is_open None rule: unreadable GitHub must never complete or
        fail a proposal — a blip costs a later sweep, a wrong flip costs truth."""
        import tools.repair_bay.services.github_service as gs
        from tools.repair_bay.services.forge_pipeline import complete_merged_fix_proposals

        pid = self._mk_pr_open(910003)
        try:
            monkeypatch.setattr(gs, "pr_merge_state", lambda pr, repo=None: None)
            complete_merged_fix_proposals()
            assert self._row(pid)["status"] == "pr_open"
        finally:
            self._rm(pid)
