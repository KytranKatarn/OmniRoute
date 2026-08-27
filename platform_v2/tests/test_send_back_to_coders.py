"""#5932 Phase 1 — 'Send back to coders': a REQUEST CHANGES becomes actionable without Claude.

The human clicks; each blocking finding in the stored F.O.R.G.E. review becomes an
improvement_proposals row with status='fix_requested' and metadata.source='pr_review_finding'.
NO automatic execution — the rows just join the queue that already consumes fix_requested.

Pinned here:
  * only CRITICAL/WARNING findings are sent back; INFO never is
  * a finding WITHOUT an evidence line is skipped and REPORTED — the review integrity
    gates key off evidence, so an evidence-less fix request can never be verified as
    addressed (the task #5932 gotcha); nothing is dropped silently
  * a second click is idempotent — duplicates are counted, not minted (the #2896 lesson:
    dedup at CREATION)
  * pr_number / repo / head_sha / evidence all land in metadata
"""

import pytest

from tools.repair_bay.services import pr_review_service as prs
from database import get_db_cursor

PR = 990001
REPO = "KytranKatarn/archie-platform"

REVIEW = """SUMMARY
Two real problems and one nit.

ISSUES
- [CRITICAL] Connection leak on the error path — the cursor is never closed — Evidence: +    cur = conn.cursor()
- [WARNING] Bare except swallows the failure — real errors vanish silently — Evidence: +    except Exception:
- [WARNING] Prose-only concern with no citation carried
- [INFO] Style nit — cosmetic only — Evidence: +    x=1

VERDICT: REQUEST CHANGES
"""

INFO_ONLY_REVIEW = """SUMMARY
Nothing blocking.

ISSUES
- [INFO] Style nit — cosmetic only — Evidence: +    x=1

VERDICT: APPROVE
"""


def _cleanup():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM improvement_proposals WHERE metadata->>'source'='pr_review_finding'"
            " AND metadata->>'pr_number'=%s",
            (str(PR),),
        )
        cur.execute("DELETE FROM pr_reviews WHERE pr_number=%s AND repo=%s", (PR, REPO))


def _insert_review(summary):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO pr_reviews (pr_number, repo, title, state, review_status, ai_summary)
               VALUES (%s, %s, 'test send-back PR', 'open', 'reviewed', %s)
               ON CONFLICT (pr_number, repo) DO UPDATE SET ai_summary = EXCLUDED.ai_summary""",
            (PR, REPO, summary),
        )


@pytest.fixture
def review_row():
    _cleanup()
    _insert_review(REVIEW)
    yield PR
    _cleanup()


@pytest.fixture(autouse=True)
def _no_github(monkeypatch):
    monkeypatch.setattr(prs, "pr_head_sha", lambda pr, repo=None: "deadbeef1234")


def _fetch_created():
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM improvement_proposals WHERE metadata->>'source'='pr_review_finding'"
            " AND metadata->>'pr_number'=%s ORDER BY id",
            (str(PR),),
        )
        return [dict(r) for r in cur.fetchall()]


def test_blocking_findings_with_evidence_become_fix_requested(review_row):
    res = prs.create_fix_requests_from_review(PR, repo=REPO)
    assert res["success"] is True
    assert len(res["created"]) == 2, "CRITICAL + evidenced WARNING; never the INFO"
    assert res["skipped_no_evidence"] == 1, "the prose-only WARNING must be reported, not dropped"
    assert res["duplicates"] == 0

    rows = _fetch_created()
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "fix_requested"
        md = row["metadata"]
        assert md["source"] == "pr_review_finding"
        assert md["pr_number"] == str(PR)
        assert md["repo"] == REPO
        assert md["head_sha"] == "deadbeef1234"
        assert md["evidence"].startswith("+"), "the cited diff line must ride along"
        assert md["evidence"] in row["description"], "evidence must be human-visible too"
    severities = sorted(r["metadata"]["severity"] for r in rows)
    assert severities == ["CRITICAL", "WARNING"]
    crit = next(r for r in rows if r["metadata"]["severity"] == "CRITICAL")
    assert crit["priority"] == "critical"


def test_second_click_is_idempotent(review_row):
    first = prs.create_fix_requests_from_review(PR, repo=REPO)
    assert len(first["created"]) == 2
    second = prs.create_fix_requests_from_review(PR, repo=REPO)
    assert second["success"] is True
    assert second["created"] == [], "a double-click must not mint twin rows"
    assert second["duplicates"] == 2
    assert len(_fetch_created()) == 2


def test_info_only_review_has_nothing_to_send():
    _cleanup()
    _insert_review(INFO_ONLY_REVIEW)
    try:
        res = prs.create_fix_requests_from_review(PR, repo=REPO)
        assert res["success"] is False
        assert "no CRITICAL/WARNING" in res["error"]
        assert _fetch_created() == []
    finally:
        _cleanup()


def test_untracked_pr_fails_cleanly():
    _cleanup()
    res = prs.create_fix_requests_from_review(PR, repo=REPO)
    assert res["success"] is False
    assert "no tracked review" in res["error"]


def test_github_blip_does_not_block_the_send_back(review_row, monkeypatch):
    """head_sha resolution failing must degrade to None, never abort a human action."""

    def _boom(pr, repo=None):
        raise RuntimeError("github unreachable")

    monkeypatch.setattr(prs, "pr_head_sha", _boom)
    res = prs.create_fix_requests_from_review(PR, repo=REPO)
    assert res["success"] is True
    assert len(res["created"]) == 2
    assert res["head_sha"] is None
    assert all(r["metadata"]["head_sha"] is None for r in _fetch_created())
