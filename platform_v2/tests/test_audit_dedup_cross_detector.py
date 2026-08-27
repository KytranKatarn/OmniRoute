"""Cross-detector dedup at proposal creation (2026-08-27).

The ruff tier (F401) and the static tier (blanket code PYFLAKES) report the SAME
pyflakes-class defect under different issue codes. On 2026-08-20 that minted twin live
rows (11235/11259) for one finding; both reached the owner's Approvals tab and the
orphan burned a human approval on an already-merged fix. _has_open_audit_proposal must
treat lint-family rows with equal fingerprints as one finding — and must NOT over-dedup
distinct findings or non-lint codes.
"""

import json

import pytest

from database import get_db_cursor
from services.audit_pipeline import _has_open_audit_proposal

FILE_PATH = "[AI_BRIDGE]/test_dedup_xdetector_fixture.py"


def _insert(cur, issue_code, detail):
    cur.execute(
        """INSERT INTO improvement_proposals (title, description, status, metadata)
           VALUES (%s, %s, 'ready_for_review', %s::jsonb) RETURNING id""",
        (
            f"[MEDIUM] {issue_code}: dedup fixture",
            "cross-detector dedup test row",
            json.dumps(
                {
                    "source": "code_health_audit",
                    "file_path": FILE_PATH,
                    "issue_code": issue_code,
                    "detail": detail,
                }
            ),
        ),
    )
    return cur.fetchone()["id"]


@pytest.fixture
def pyflakes_row():
    with get_db_cursor(commit=True) as (conn, cur):
        pid = _insert(cur, "PYFLAKES", "'psycopg2' imported but unused (line 15)")
    yield pid
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (pid,))


def test_exact_code_match_still_dedups(pyflakes_row):
    assert _has_open_audit_proposal(FILE_PATH, "PYFLAKES", "'psycopg2' imported but unused (line 15)") is True


def test_same_finding_other_detector_is_a_duplicate(pyflakes_row):
    """The ruff spelling (backticks, F401) of the stored PYFLAKES finding is the same defect."""
    assert _has_open_audit_proposal(FILE_PATH, "F401", "`psycopg2` imported but unused (line 15)") is True


def test_different_import_name_is_not_deduped(pyflakes_row):
    assert _has_open_audit_proposal(FILE_PATH, "F401", "`os` imported but unused (line 3)") is False


def test_non_lint_codes_keep_exact_matching(pyflakes_row):
    """The fingerprint pass is scoped to the lint family — a non-lint code on the same
    file must never be swallowed by it."""
    assert _has_open_audit_proposal(FILE_PATH, "SQL_INJECTION_RISK", "raw f-string SQL") is False


def test_missing_detail_falls_back_to_exact_matching(pyflakes_row):
    """No detail -> no fingerprint to compare; only the exact-code path may answer."""
    assert _has_open_audit_proposal(FILE_PATH, "F401", None) is False
