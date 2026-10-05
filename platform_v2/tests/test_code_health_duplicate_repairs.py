"""Duplicate retirement keeps real work and patches, never inventing completion."""

from contextlib import contextmanager
import services.code_health_repairs as repairs


def record(pid, path="platform_v2/tools/department_hq/jobs.py", **changes):
    row = dict(
        id=pid,
        file_path=path,
        status="approved",
        code_changes=None,
        module_name=None,
        metadata_module="department_hq",
        issue_code="LARGE_FILE",
        scan_tier=None,
    )
    row.update(changes)
    return row


def run(monkeypatch, records, dry_run=False):
    retired, cancelled = [], []

    class Cursor:
        rowcount = 0

        def execute(self, sql, params):
            if sql.lstrip().startswith("SELECT"):
                self.rows = records
                assert r"department\_hq/" in params[1]
            elif "UPDATE improvement_proposals" in sql:
                assert params[0] not in params[1]
                retired.extend(params[1])
                self.rows = [{"id": pid} for pid in params[1]]
            else:
                assert "UPDATE autonomy_approval_queue" in sql
                cancelled.extend(params[0])
                self.rowcount = len(params[0])

        def fetchall(self):
            return self.rows

    @contextmanager
    def db(commit=False):
        assert commit is not dry_run
        yield None, Cursor()

    monkeypatch.setattr(repairs, "get_db_cursor", db)
    result = repairs.reconcile_duplicate_proposals("department_hq", dry_run=dry_run)
    return result, retired, cancelled


def test_alias_twins_keep_oldest_and_cancel_duplicate_card(monkeypatch):
    result, retired, cards = run(monkeypatch, [record(1), record(2, "[APP_CORE]/tools/department_hq/jobs.py")])
    assert retired == [2] and cards == ["2"]
    assert result["superseded"] == 1


def test_prepared_fix_wins_and_is_never_retired(monkeypatch):
    result, retired, _ = run(monkeypatch, [record(1), record(2, status="ready_for_review", code_changes="patch")])
    assert retired == [1]
    assert result["superseded"] == 1


def test_two_patches_are_preserved_for_review(monkeypatch):
    result, retired, _ = run(monkeypatch, [record(1, code_changes="a"), record(2, code_changes="b")])
    assert retired == [] and result["superseded"] == 0


def test_static_symbols_and_other_modules_are_preserved(monkeypatch):
    rows = [
        record(1, scan_tier="static"),
        record(2, scan_tier="static"),
        record(3, issue_code="PYFLAKES"),
        record(4, issue_code="PYFLAKES"),
        record(5, "platform_v2/tools/faith/routes.py"),
        record(6, "[APP_CORE]/tools/faith/routes.py"),
    ]
    result, retired, _ = run(monkeypatch, rows)
    assert retired == [] and result["duplicates"] == 0


def test_dry_run_has_no_writes(monkeypatch):
    result, retired, cards = run(monkeypatch, [record(1), record(2)], dry_run=True)
    assert result["duplicates"] == 1
    assert result["superseded"] == 0 and retired == cards == []


def test_active_work_survives_unworked_duplicate(monkeypatch):
    _, retired, _ = run(monkeypatch, [record(1), record(2, status="fix_requested")])
    assert retired == [1]
