"""#5934 Phase 3 — the review-fix loop's safety contract.

Pinned here:
  * fixes are committed to the PR's HEAD branch and NEVER to main/master
  * the hard cap: 2 failed attempts per finding -> owner escalation, no loops
  * an approved re-review flips the row to pr_open with apply_mode='review_fix'
    (the ship_as_pr metadata shape — complete_merged_fix_proposals settles it);
    a failed re-review costs the attempt and leaves the row fix_requested
  * repos outside the write token's scope are SKIPPED AND REPORTED, never eaten
  * a closed/merged PR archives the send-back rows with an explicit reason
  * the find/replace gates: unique find, verbatim presence, no >20% shrink
"""

import json

import pytest

from database import get_db_cursor
from tools.repair_bay.services import review_fix_service as rfs
from tools.repair_bay.services.github_service import REPO_FULL

PR = 990003

DIFF = (
    "diff --git a/pkg/mod.py b/pkg/mod.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/pkg/mod.py\n"
    "+++ b/pkg/mod.py\n"
    "@@ -1,3 +1,4 @@\n"
    " import os\n"
    "+    cur = conn.cursor()\n"
    " x = 1\n"
)

FILE = "import os\n    cur = conn.cursor()\nx = 1\n"
EVIDENCE = "+    cur = conn.cursor()"


def _cleanup():
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM improvement_proposals WHERE metadata->>'source'='pr_review_finding'"
            " AND metadata->>'pr_number'=%s",
            (str(PR),),
        )


def _mk_row(evidence=EVIDENCE, attempts=0, repo=REPO_FULL, title="Connection leak"):
    md = {
        "source": "pr_review_finding",
        "pr_number": str(PR),
        "repo": repo,
        "severity": "CRITICAL",
        "finding_title": title,
        "finding_why": "the cursor is never closed",
        "evidence": evidence,
        "fix_attempts": attempts,
    }
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO improvement_proposals (title, description, status, metadata)
               VALUES (%s, 'test', 'fix_requested', %s::jsonb) RETURNING id""",
            (f"[FIX REQUEST] PR #{PR}: {title}", json.dumps(md)),
        )
        return cur.fetchone()["id"]


def _fetch(proposal_id):
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM improvement_proposals WHERE id=%s", (proposal_id,))
        return dict(cur.fetchone())


@pytest.fixture(autouse=True)
def _clean():
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def happy_github(monkeypatch):
    """Open PR on a feature branch; captures every contents PUT."""
    puts = []
    monkeypatch.setattr(
        rfs,
        "_get_pr",
        lambda repo, pr: {"state": "open", "merged_at": None, "head": {"ref": "feat/x", "sha": "h1"}},
    )
    monkeypatch.setattr(rfs, "_fetch_pr_diff", lambda repo, pr: DIFF)
    monkeypatch.setattr(rfs, "_get_file_at_ref", lambda repo, path, ref: (FILE, "blobsha"))
    monkeypatch.setattr(
        rfs,
        "_put_file",
        lambda repo, path, branch, content, sha, msg: (
            puts.append({"path": path, "branch": branch, "content": content}) or "commit123"
        ),
    )
    monkeypatch.setattr(
        rfs,
        "_generate_find_replace",
        lambda md, content: (("    cur = conn.cursor()", "    with conn.cursor() as cur:  # closed"), "ok"),
    )
    return puts


@pytest.fixture
def notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(rfs, "_notify_owner", lambda title, msg: sent.append((title, msg)))
    return sent


# ---------------------------------------------------------------- pure helpers


def test_locate_evidence_file():
    assert rfs._locate_evidence_file(DIFF, EVIDENCE) == "pkg/mod.py"
    assert rfs._locate_evidence_file(DIFF, "+    never_in_the_diff()") is None
    assert rfs._locate_evidence_file("", EVIDENCE) is None


def test_validate_fix_gates():
    ok, _ = rfs._validate_fix(FILE, "    cur = conn.cursor()", "    pass")
    assert ok
    assert not rfs._validate_fix(FILE, "nowhere", "x")[0], "absent find must be refused"
    assert not rfs._validate_fix("a\na\n", "a", "b")[0], "non-unique find must be refused"
    assert not rfs._validate_fix(FILE, "    cur = conn.cursor()", "    cur = conn.cursor()")[0]
    big = "x = 1\n" * 200
    assert not rfs._validate_fix(big, "x = 1\n" * 150, "")[0], "mass deletion must be refused"
    small = "import os\nvery_long_variable_name = compute_something_expensive()\n"
    assert rfs._validate_fix(small, "very_long_variable_name = compute_something_expensive()", "result = 1")[
        0
    ], "a legitimate one-line fix on a SMALL file must not trip the shrink guard"


# ---------------------------------------------------------------- the loop


def test_approved_review_flips_row_to_pr_open(happy_github, notifications, monkeypatch):
    monkeypatch.setattr(rfs, "_run_review", lambda pr, repo: (True, True))
    pid = _mk_row()
    res = rfs.run_review_fix_cycle()
    assert res["fixes_pushed"] == 1 and res["approved"] is True
    assert happy_github[0]["branch"] == "feat/x", "the commit must target the PR's OWN branch"
    row = _fetch(pid)
    assert row["status"] == "pr_open"
    assert row["metadata"]["apply_mode"] == "review_fix"
    assert row["metadata"]["fix_attempts"] == 1
    assert row["metadata"]["fix_commit_sha"] == "commit123"
    assert notifications == []


def test_failed_review_costs_the_attempt_then_escalates(happy_github, notifications, monkeypatch):
    monkeypatch.setattr(rfs, "_run_review", lambda pr, repo: (True, False))
    pid = _mk_row()
    res1 = rfs.run_review_fix_cycle()
    assert res1["fixes_pushed"] == 1 and res1["approved"] is False
    row = _fetch(pid)
    assert row["status"] == "fix_requested" and row["metadata"]["fix_attempts"] == 1
    assert notifications == [], "one failure is not an escalation"

    res2 = rfs.run_review_fix_cycle()
    assert res2["escalated"] == 1
    row = _fetch(pid)
    assert row["metadata"]["fix_attempts"] == 2
    assert row["metadata"]["escalated"] is True
    assert len(notifications) == 1 and f"PR #{PR}" in notifications[0][0]

    res3 = rfs.run_review_fix_cycle()
    assert res3["prs_processed"] == 0, "an escalated row must never be retried"


def test_never_writes_to_a_main_head(happy_github, monkeypatch):
    monkeypatch.setattr(
        rfs,
        "_get_pr",
        lambda repo, pr: {"state": "open", "merged_at": None, "head": {"ref": "main", "sha": "h1"}},
    )
    pid = _mk_row()
    res = rfs.run_review_fix_cycle()
    assert res["fixes_pushed"] == 0
    assert happy_github == [], "no contents PUT may ever target main"
    assert _fetch(pid)["status"] == "fix_requested"


def test_attempt_cap_self_heals_on_stranded_rows(notifications):
    pid = _mk_row(attempts=2)
    res = rfs.run_review_fix_cycle()
    assert res["escalated"] == 1
    assert _fetch(pid)["metadata"]["escalated"] is True
    assert len(notifications) == 1


def test_unsupported_repo_is_skipped_and_reported():
    pid = _mk_row(repo="KytranKatarn/kytran-gov-watch")
    res = rfs.run_review_fix_cycle()
    assert res["skipped_unsupported_repo"] == 1
    assert res["prs_processed"] == 0
    assert _fetch(pid)["status"] == "fix_requested", "skipped, never mutated"


def test_closed_pr_archives_the_send_back(happy_github, monkeypatch):
    monkeypatch.setattr(
        rfs,
        "_get_pr",
        lambda repo, pr: {"state": "closed", "merged_at": None, "head": {"ref": "feat/x"}},
    )
    pid = _mk_row()
    res = rfs.run_review_fix_cycle()
    assert res["archived_pr_gone"] == 1
    row = _fetch(pid)
    assert row["status"] == "archived"
    assert row["metadata"]["archived_reason"] == "pr_closed_before_fix"


def test_generation_failure_counts_and_escalates_at_cap(happy_github, notifications, monkeypatch):
    monkeypatch.setattr(rfs, "_generate_find_replace", lambda md, content: (None, "not parseable"))
    pid = _mk_row(attempts=1)  # this failure is the second attempt
    res = rfs.run_review_fix_cycle()
    assert res["generation_failed"] == 1 and res["escalated"] == 1
    row = _fetch(pid)
    assert row["metadata"]["fix_attempts"] == 2
    assert row["metadata"]["escalated"] is True
    assert happy_github == [], "nothing may be committed when generation fails"


def test_github_blip_leaves_rows_untouched(monkeypatch):
    monkeypatch.setattr(rfs, "_get_pr", lambda repo, pr: None)
    pid = _mk_row()
    res = rfs.run_review_fix_cycle()
    assert res["fixes_pushed"] == 0 and res["escalated"] == 0
    row = _fetch(pid)
    assert row["status"] == "fix_requested"
    assert row["metadata"]["fix_attempts"] == 0, "a blip must not cost an attempt"
