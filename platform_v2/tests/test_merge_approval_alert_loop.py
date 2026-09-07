"""#6649 — the merge-approval Telegram must be bound to the ARTIFACT, not the intent.

THE BUG (measured 2026-09-07):

`_escalate_blocked_merge` sent the buttoned Telegram UNCONDITIONALLY, between the
`open_pr_merge_approval(...)` call and the `if approval_id:` guard. When that call was
DEDUPED (a live pending row already existed), it returned None — so a fresh page went
out and the flag that stops the retry was deliberately NOT set. The 2-minute
`forge_archie_pr_review` worker then re-processed the PR, hit the same governance
refusal, and did it all again.

  59 sends over 7 days, ALL of them dedups — 49 for PR #3238 across 1h43m, 6 for #3242.
  Zero draft-guard cases. Zero error cases.

The producer that opened the row was `mark_review_done`'s sensitive-path gate, which
opens the row AND sends the buttons but never set `kytran_approval_sent`.

SECOND DEFECT, independent and worse: `_mark_kytran_approval_sent` / `_mark_tier_processed`
wrote `WHERE pr_number = %s` with NO repo predicate, while `pr_reviews` HAS a repo column
and pr_number is not unique — **PR #19 exists in FIVE repos**. Marking one silently
retired four other repos' live PRs from the escalation path.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_merge_approval_alert_loop.py -v
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from tools.repair_bay.services import pr_review_service as prs  # noqa: E402


# ── the repo-scoping half ────────────────────────────────────────────────────


def test_flag_writers_accept_a_repo():
    """Both writers must be able to scope to a repo — pr_number is not unique."""
    for fn in (prs._mark_kytran_approval_sent, prs._mark_tier_processed):
        assert "repo" in inspect.signature(fn).parameters, f"{fn.__name__} must accept repo"


def test_flag_writers_actually_use_the_repo_in_sql():
    """Accepting the param is not enough — it must reach the WHERE clause.

    Guards the 'added the parameter, forgot to use it' failure, which would leave the
    cross-repo hazard intact while looking fixed.
    """
    for fn in (prs._mark_kytran_approval_sent, prs._mark_tier_processed):
        src = inspect.getsource(fn)
        assert "AND repo = %s" in src, f"{fn.__name__} must filter on repo when one is given"


def test_repo_blind_path_is_still_available():
    """repo=None must keep the historical behaviour — narrowing an existing caller's
    UPDATE without its knowledge could leave the flag unset and REINTRODUCE the loop."""
    for fn in (prs._mark_kytran_approval_sent, prs._mark_tier_processed):
        assert inspect.signature(fn).parameters["repo"].default is None


# ── the artifact-vs-intent half ──────────────────────────────────────────────


def test_pending_lookup_exists_and_is_repo_aware():
    """The dedup/no-row distinction needs a repo-aware lookup — this one SUPPRESSES a
    page, so a cross-repo false match would silence a genuine request."""
    assert hasattr(prs, "pending_pr_merge_approval")
    src = inspect.getsource(prs.pending_pr_merge_approval)
    assert "action_data->>'repo'" in src, "lookup must be repo-aware"
    assert "status = 'pending'" in src
    assert "expires_at" in src, "an expired row must not suppress a page"


def test_pending_lookup_fails_to_none(monkeypatch):
    """An unreadable DB must behave like 'no row' (keep retrying), never like
    'a row exists' (suppress the page)."""

    def boom(*a, **k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(prs, "get_db_cursor", boom)
    assert prs.pending_pr_merge_approval(123, repo="x/y") is None


def test_sensitive_gate_records_the_flag_only_when_a_row_exists():
    """mark_review_done's gate is the producer that started the loop. It must set the
    flag — but only when open_pr_merge_approval actually returned an id (ADR-014:
    record the artifact, never the intent)."""
    src = inspect.getsource(prs.mark_review_done)
    assert "_approval_id = open_pr_merge_approval(" in src, "must capture the return value"
    assert "if _approval_id:" in src, "must gate the flag on a real row id"
    assert "_mark_kytran_approval_sent(pr_number, repo=_merge_repo)" in src


# ── the escalation path (lives in ai_bridge, read as source) ─────────────────


def _escalation_source():
    """Source of the LIVE `_escalate_blocked_merge`, via import rather than a guessed path.

    ⚠️ The first version of this helper probed two hardcoded paths and called
    `pytest.skip()` when neither existed. Both were wrong in the container, so the
    three tests covering the ACTUAL fix skipped silently while the suite reported
    green — the same "unmonitored while appearing monitored" shape these tests exist
    to prevent. `agent_loop` is importable here (other suites import it), so ask the
    module where it lives instead of guessing.
    """
    import pytest

    try:
        from ai_bridge import agent_loop as al
    except Exception:
        try:
            import agent_loop as al  # some paths put ai_bridge/ directly on sys.path
        except Exception as exc:  # pragma: no cover
            pytest.fail(
                f"agent_loop is not importable, so the escalation fix is UNTESTED: {exc}. "
                "Fix the import rather than skipping — a skipped test here reports green "
                "on the exact code this file exists to pin."
            )
    return inspect.getsource(al.AgentLoop._escalate_blocked_merge)


def test_telegram_is_sent_only_when_a_row_was_created():
    """THE fix. The page must live INSIDE the `if approval_id:` branch."""
    src = _escalation_source()
    i_open = src.index("approval_id = open_pr_merge_approval(")
    i_guard = src.index("if approval_id:", i_open)
    i_page = src.index("_request_kytran_pr_approval(", i_open)
    assert i_page > i_guard, (
        "the Telegram is still sent BEFORE the `if approval_id:` guard — a deduped "
        "creation will page the owner again on every 2-minute tick"
    )


def test_dedup_is_distinguished_from_no_row():
    """The old log named three causes and committed to none. Dedup must now be handled
    explicitly, because it is the ONLY one that actually occurred (59/59)."""
    src = _escalation_source()
    assert "pending_pr_merge_approval(" in src, "must look up whether a row already exists"
    assert "NOT dedup" in src, "the remaining warning must say dedup is handled elsewhere"


def test_escalation_passes_repo_to_both_flag_writers():
    src = _escalation_source()
    assert "_mark_kytran_approval_sent(pr_num, repo=" in src
    assert "_mark_tier_processed(pr_num, tier=tier, repo=" in src
