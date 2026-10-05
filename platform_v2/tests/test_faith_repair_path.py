"""Faith's clean audit must settle provably stale repairs without hiding real work."""

from contextlib import contextmanager
from collections import Counter

import pytest

import services.code_health_repairs as repairs
import services.code_issue_reconciler as reconciler
import services.code_metrics_service as metrics
import services.audit_pipeline as pipeline
import tools.consciousness.code_health_routes as routes


@pytest.fixture
def faith_path(monkeypatch, tmp_path):
    records = [
        {
            "id": 2533,
            "status": "approved",
            "module_name": None,
            "metadata_module": "faith",
            "file_path": "platform_v2/tools/faith/routes.py",
            "issue_code": "LARGE_FILE",
            "detail": "996 lines",
        },
        {
            "id": 2534,
            "status": "approved",
            "module_name": None,
            "metadata_module": "[APP_CORE]",
            "file_path": "[APP_CORE]/tools/faith/routes.py",
            "issue_code": "LARGE_FILE",
            "detail": "996 lines",
        },
        {
            "id": 9999,
            "status": "approved",
            "module_name": None,
            "metadata_module": "fitness",
            "file_path": "platform_v2/tools/fitness/routes.py",
            "issue_code": "LARGE_FILE",
            "detail": "996 lines",
        },
    ]
    cards = {2533: "pending", 2534: "pending", 9999: "pending"}
    source = tmp_path / "routes.py"
    (tmp_path / "__init__.py").write_text('"""Isolated Faith fixture."""\n')

    class Cursor:
        rowcount = 0

        def execute(self, sql, params):
            if "COUNT(*) AS cnt" in sql:
                groups = Counter(
                    (r["module_name"], r["metadata_module"], r["file_path"])
                    for r in records
                    if r["status"] not in params[0]
                )
                self.rows = [
                    dict(module_name=k[0], metadata_module=k[1], file_path=k[2], cnt=v) for k, v in groups.items()
                ]
            elif sql.lstrip().startswith("SELECT id,"):
                self.rows = []
                for r in records:
                    if r["status"] not in params[0]:
                        continue
                    if len(params) > 2 and repairs.module_from_file_path(r["file_path"]) != params[1]:
                        continue
                    self.rows.append({**r, "runtime_file": None, "line": None})
            elif "UPDATE improvement_proposals" in sql:
                self.rowcount = 0
                for r in records:
                    if r["id"] in params[1] and r["status"] in params[2]:
                        r["status"] = "archived"
                        self.rowcount += 1
            elif "UPDATE autonomy_approval_queue" in sql:
                self.rowcount = 0
                for pid in params[0]:
                    if cards[int(pid)] == "pending":
                        cards[int(pid)] = "cancelled"
                        self.rowcount += 1
            else:
                raise AssertionError(sql)

        def fetchall(self):
            return self.rows

    @contextmanager
    def cursor(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(repairs, "get_db_cursor", cursor)
    monkeypatch.setattr(reconciler, "get_db_cursor", cursor)
    monkeypatch.setattr(reconciler, "_read_proposal_file", lambda *args: source.read_text())
    audit = metrics.audit_single_module
    monkeypatch.setattr(metrics, "audit_single_module", lambda key, **kwargs: audit(key, module_path=str(tmp_path)))
    monkeypatch.setattr(metrics, "log_audit", lambda **kwargs: None)
    monkeypatch.setattr(
        pipeline, "process_audit_findings", lambda *args: {"proposals_created": 0, "skipped_duplicates": 2}
    )
    return source, records, cards


def test_faith_full_reaudit_path_and_repeat(faith_path):
    source, records, cards = faith_path
    source.write_text("# valid source\n" * 996)
    first = routes._audit_one("faith", {"files": 1, "lines": 996})
    assert first["issues"] > 0
    assert first["pending_repairs"] == 2
    assert first["repair_reconciliation"]["still_present"] == 2
    assert records[2]["status"] == "approved"

    source.write_text("# valid source\n" * 396)
    second = routes._audit_one("faith", {"files": 1, "lines": 396})
    assert second["status"] == "completed"
    assert second["issues"] == 0
    assert second["pending_repairs"] == 0
    assert second["repair_reconciliation"]["archived"] == 2
    assert cards == {2533: "cancelled", 2534: "cancelled", 9999: "pending"}
    assert repairs.open_proposal_counts(code_health_only=False).get("faith", 0) == 0
    assert records[2]["status"] == "approved"

    repeat = routes._audit_one("faith", {"files": 1, "lines": 396})
    assert repeat["pending_repairs"] == 0
    assert repeat["repair_reconciliation"]["archived"] == 0


def test_clean_audit_preserves_unknown_scanner_findings(faith_path):
    source, records, _ = faith_path
    source.write_text("# valid source\n" * 396)
    records[0].update(issue_code="UNRECOGNIZED_CHECK", detail="requires another scanner")
    result = routes._audit_one("faith", {"files": 1, "lines": 396})
    assert result["issues"] == 0
    assert result["pending_repairs"] == 1
    assert records[0]["status"] == "approved"


def test_unreadable_source_never_closes_proposals(faith_path, monkeypatch):
    monkeypatch.setattr(reconciler, "_read_proposal_file", lambda *args: None)
    result = reconciler.reconcile_open_proposals(module_name="faith", dry_run=False)
    assert result["unreadable"] == 2
    assert result["archived"] == 0


@pytest.mark.parametrize("lines,expected", [(599, False), (600, True)])
def test_large_file_matches_scanner_boundary(lines, expected):
    assert reconciler.finding_still_reproduces("LARGE_FILE 996 lines", "# source\n" * lines) is expected


@pytest.mark.parametrize("status", repairs.TERMINAL_STATUSES)
def test_terminal_proposals_are_not_counted(faith_path, status):
    _, records, _ = faith_path
    records[0]["status"] = status
    records[1]["status"] = status
    assert repairs.open_proposal_counts().get("faith", 0) == 0


def test_failed_reconciliation_does_not_claim_zero_repairs(faith_path, monkeypatch):
    source, _, _ = faith_path
    source.write_text("# source\n")

    def unavailable(**kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(reconciler, "reconcile_open_proposals", unavailable)
    result = routes._audit_one("faith", {"files": 1, "lines": 1})
    assert result["issues"] == 0
    assert result["pending_repairs"] is None
