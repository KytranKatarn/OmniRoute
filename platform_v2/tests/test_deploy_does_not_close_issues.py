"""`deploy_to_production` must not report work it did not do (#5808).

WHAT THIS PATH ACTUALLY DOES
----------------------------
It fetches the proposal, takes a W.A.R.D.E.N.-cleared pre-deploy backup, builds a
deployment_log whose own third line reads:

    "Manual deployment required - automatic code application disabled for safety"

...and then stops. It never writes a production file — `_apply_fix_to_sandbox` is the
only code-writing helper in the module and it targets the staging worktree.

THE DEFECT
----------
Having applied nothing, it set `status='deployed'` AND closed the linked `code_issues`
as `fixed`. Closing them is the harmful half: the scanner stops re-proposing defects
that are still in the tree, so the debt goes invisible rather than getting resolved.

Measured 2026-08-19 on proposal 8658 ("remove unused `import zipfile`"): the file it
claimed to have fixed still contained the import in the repo, in the container AND in
the sandbox, and had an mtime three weeks old. 356 proposals carry status='deployed'
with no health check and no backup recorded.

An issue is fixed when the CODE changes — never when a proposal is approved.
Gate on the artifact, not the status field (ADR-014).
"""

import inspect


def _deploy_src() -> str:
    from services.proposal_service import deploy_to_production

    return inspect.getsource(deploy_to_production)


def test_deploy_path_does_not_close_code_issues():
    """The regression: no UPDATE that marks code_issues fixed may live in this function."""
    src = _deploy_src()
    normalised = " ".join(src.split()).lower()
    assert "update code_issues set status='fixed'" not in normalised, (
        "deploy_to_production closed code_issues as fixed, but it applies no code — "
        "that hides real defects from the scanner instead of resolving them"
    )


def test_deploy_records_that_no_code_was_applied():
    """The truth must be machine-readable, not buried in deployment_log prose."""
    src = _deploy_src()
    assert '"code_applied": False' in src, (
        "deploy_to_production must stamp code_applied=False — downstream consumers "
        "should not have to parse the deployment_log strings to learn nothing shipped"
    )


# Anything that would write a file / shell out to apply a patch. If one of these ever
# appears in deploy_to_production, the function has started applying code and the two
# assertions above must be RE-EVALUATED rather than silently inherited.
_PRODUCTION_WRITE_MARKERS = (
    "open(",
    ".write_text(",
    ".writelines(",
    "shutil.copy",
    "shutil.move",
    "git apply",
    "subprocess",
    "os.replace",
)


def test_deploy_path_performs_no_production_write():
    """Guards the PREMISE structurally, not by matching prose.

    The earlier form asserted a substring of a log line ("automatic code application
    disabled"), which F.O.R.G.E. correctly flagged as non-exhaustive: a reworded message
    would fail a test that has nothing to do with wording, while an actual production
    write could be added without the message changing at all — the test would pass and
    the premise would be silently false.

    This asserts the property that actually matters: the function contains no path that
    writes a file or shells out to apply a patch. If automatic application is ever
    enabled, this fails on purpose.
    """
    src = _deploy_src()
    found = sorted(m for m in _PRODUCTION_WRITE_MARKERS if m in src)
    assert not found, (
        f"deploy_to_production now contains write markers {found} — it may be applying code. "
        "Re-evaluate whether closing code_issues is legitimate now, instead of inheriting "
        "the no-apply assumption these tests were written under."
    )
