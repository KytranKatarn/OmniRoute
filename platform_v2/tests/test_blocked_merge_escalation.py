"""#5413 — a merge the automation CANNOT complete must reach a human, exactly once.

A Tier-1/Tier-2 merge REFUSAL used to be a `logger.warning` and nothing else: no
Telegram, no state. Because neither guard field was written, the worker re-attempted
a merge that could never succeed on every 2-minute tick, forever, while the human who
has to act was never told. PR #2551 sat that way; PR #2547 before it.

The escalation machinery already existed — the `tier == 3` branch. These tests pin
that a governance refusal now reuses it, that a TRANSIENT failure does not (so a
GitHub blip cannot page the owner), and that both failure branches stay wired.
"""

from __future__ import annotations

import inspect
import re

import pytest

import ai_bridge.agent_loop as al

_PR_SVC = "tools.repair_bay.services.pr_review_service"


class _StubLoop:
    """Minimal stand-in for AgentLoop — the helper only uses one method off self."""

    def __init__(self):
        self.approval_calls = []

    def _request_kytran_pr_approval(self, pr_number, title, summary, reason=None):
        self.approval_calls.append({"pr": pr_number, "title": title, "summary": summary, "reason": reason})


@pytest.fixture
def wired(monkeypatch):
    """Patch everything the helper imports, recording call order.

    ``pr_is_open`` is stubbed to True by default (#5419) — without this the
    suite would hit the real GitHub API on every escalation test.
    """
    import tools.repair_bay.services.pr_review_service as svc
    import tools.repair_bay.services.github_service as gh

    order = []
    opened = []
    marked = []
    tiered = []
    state = {"open": True, "approval_id": 4242}

    def _open(pr, title, summary, repo=None):
        order.append("open_row")
        opened.append({"pr": pr, "title": title, "repo": repo})
        # MUST return an approval id. #5829 made the escalation mark "asked" only when a
        # queue ROW EXISTS, so a double that returns None silently exercises the failure
        # path and every escalation test goes red for the wrong reason. Record the
        # artifact, never the intent — the double has to honour that too.
        return state["approval_id"]

    def _mark(pr):
        order.append("mark_sent")
        marked.append(pr)

    def _tier(pr, tier=None):
        order.append("mark_tier")
        tiered.append({"pr": pr, "tier": tier})

    monkeypatch.setattr(svc, "open_pr_merge_approval", _open, raising=True)
    monkeypatch.setattr(svc, "_mark_kytran_approval_sent", _mark, raising=True)
    monkeypatch.setattr(svc, "_mark_tier_processed", _tier, raising=True)
    monkeypatch.setattr(gh, "pr_is_open", lambda pr, repo=None: state["open"], raising=True)

    loop = _StubLoop()
    return {
        "state": state,
        "loop": loop,
        "order": order,
        "opened": opened,
        "marked": marked,
        "tiered": tiered,
        "state": state,
    }


def _review(pr=2551):
    return {
        "pr_number": pr,
        "title": "fix(infra): something",
        "ai_summary": "VERDICT: APPROVE",
        "repo": "KytranKatarn/archie-platform",
    }


def _escalate(loop, review, result, tier):
    return al.AgentLoop._escalate_blocked_merge(loop, review, result, tier)


# ---------------------------------------------------------------------------
# PERMANENT refusal -> escalate
# ---------------------------------------------------------------------------


def test_governance_refusal_escalates(wired):
    """The allowlist case: the gate said no, so a human must decide."""
    result = {
        "merged": False,
        "governance_blocked": True,
        "error": "Refusing to merge PR #2551: changes files outside the auto-merge allowlist",
    }

    assert _escalate(wired["loop"], _review(), result, 2) is True
    assert wired["marked"] == [2551]
    assert len(wired["loop"].approval_calls) == 1


def test_escalation_marks_sent_so_the_retry_loop_stops(wired):
    """`kytran_approval_sent` is what the worker's own guard skips on.

    Without it the worker re-attempts an impossible merge every 2 minutes forever.
    """
    result = {"merged": False, "governance_blocked": True, "error": "nope"}
    _escalate(wired["loop"], _review(4242), result, 1)

    assert wired["marked"] == [4242], "the send-once marker is what ends the loop"


def test_durable_row_opens_before_the_telegram(wired):
    """Dual surface (#5283): a dismissed or undelivered message must not strand a PR.

    The Approvals-tab row is opened FIRST and independently of the send.
    """
    result = {"merged": False, "governance_blocked": True, "error": "nope"}
    _escalate(wired["loop"], _review(), result, 2)

    assert wired["order"] == ["open_row", "mark_sent"]
    assert wired["opened"][0]["repo"] == "KytranKatarn/archie-platform"


def test_reason_tells_the_owner_what_actually_blocked_it(wired):
    """The message must carry the gate's own refusal text, not 'Tier 3'.

    The PR was NOT classified Tier 3 — saying so would misdescribe why he is
    being asked.
    """
    result = {
        "merged": False,
        "governance_blocked": True,
        "error": "outside the auto-merge allowlist (platform_v2/services/x.py)",
    }
    _escalate(wired["loop"], _review(), result, 2)

    reason = wired["loop"].approval_calls[0]["reason"]
    assert "REFUSED" in reason
    assert "allowlist" in reason
    assert "Tier 2" in reason


# ---------------------------------------------------------------------------
# TRANSIENT failure -> do NOT escalate (this is the half that protects the owner)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        {"merged": False, "error": "502 Bad Gateway"},
        {"merged": False, "error": "merge conflict"},
        {"merged": False, "governance_blocked": False, "error": "CI still pending"},
        {"merged": False, "governance_blocked": None, "error": "timeout"},
        {"merged": False},
    ],
)
def test_transient_failure_does_not_escalate(wired, result):
    """Only the gate's refusal is permanent. Everything else may clear on its own.

    Escalating these would page the owner on a GitHub blip AND mark the PR
    approval-sent, which would stop the retry that was going to succeed.
    """
    assert _escalate(wired["loop"], _review(), result, 2) is False
    assert wired["marked"] == []
    assert wired["loop"].approval_calls == []
    assert wired["order"] == []


def test_discrimination_is_not_string_matching():
    """The permanent/transient split must key on the flag, not on error text.

    Error strings get reworded; a matcher against them rots silently.
    """
    src = inspect.getsource(al.AgentLoop._escalate_blocked_merge)
    assert 'result.get("governance_blocked")' in src
    for smell in ("allowlist" + '"', "in error", ".lower()", "startswith("):
        assert smell not in src.split('"""')[-1], f"looks like string matching: {smell}"


# ---------------------------------------------------------------------------
# The Tier 3 path must be unchanged by the additive `reason` parameter
# ---------------------------------------------------------------------------


def test_tier3_default_wording_unchanged(monkeypatch):
    """`reason` is additive — omitting it must reproduce today's Tier 3 message."""
    import services.telegram_service as tg

    sent = {}
    monkeypatch.setattr(tg, "send_with_buttons", lambda **kw: sent.update(kw), raising=True)

    al.AgentLoop._request_kytran_pr_approval(_StubLoop(), 99, "a title", "a summary")

    assert "Tier 3 — requires your approval before merge." in sent["message"]
    labels = [b["text"] for b in sent["buttons"]]
    assert labels == ["✅ Merge", "❌ Deny"]
    assert sent["buttons"][0]["callback_data"] == "pr_merge_approve_99"


def test_reason_replaces_only_the_trailing_line(monkeypatch):
    import services.telegram_service as tg

    sent = {}
    monkeypatch.setattr(tg, "send_with_buttons", lambda **kw: sent.update(kw), raising=True)

    al.AgentLoop._request_kytran_pr_approval(
        _StubLoop(), 99, "a title", "a summary", reason="⛔ blocked because reasons"
    )

    assert "⛔ blocked because reasons" in sent["message"]
    assert "Tier 3 — requires your approval" not in sent["message"]
    assert "a summary" in sent["message"], "the F.O.R.G.E. review must still be included"


# ---------------------------------------------------------------------------
# Wiring — and proof this test FAILS if the wiring is removed.
# Per .claude/rules/repair-bay.md: a test that cannot fail is worse than none.
# The live file is never mutated; the strip happens on an in-memory copy.
# ---------------------------------------------------------------------------

_WIRE_RE = re.compile(r"elif self\._escalate_blocked_merge\(review, result, tier=(\d)\)")


def test_both_failure_branches_are_wired():
    """A refusal on EITHER tier must escalate — Tier 1 hit this too (PR #2547)."""
    src = inspect.getsource(al.AgentLoop._run_archie_pr_review_worker)
    tiers = sorted(_WIRE_RE.findall(src))
    assert tiers == ["1", "2"], f"expected both tiers wired, found {tiers}"


def test_wiring_check_fails_against_prefix_code():
    """Strip the wiring from a COPY and confirm the check above would fail.

    Without this, test_both_failure_branches_are_wired could be vacuously true.
    """
    src = inspect.getsource(al.AgentLoop._run_archie_pr_review_worker)
    stripped, n = _WIRE_RE.subn("elif False", src)

    assert n == 2, f"expected to strip 2 wiring sites, stripped {n}"
    assert _WIRE_RE.findall(stripped) == [], "pre-fix copy still looks wired"


# ---------------------------------------------------------------------------
# #5419 — never page about a PR that is already merged
#
# pr_reviews.state is refreshed by sync_closed_prs only every 4 HOURS, so a PR
# merged out-of-band still reads 'open' to the worker. The gate refuses BEFORE
# any GitHub call, so it never learns the PR is merged. An allowlist-refused PR
# can ONLY be merged by hand — so every one of them opens this window. Observed
# live on PR #2552, which paged the owner about an already-completed merge.
# ---------------------------------------------------------------------------


def _blocked():
    return {
        "merged": False,
        "governance_blocked": True,
        "error": "outside the auto-merge allowlist (ai_bridge/agent_loop.py)",
    }


def test_already_merged_pr_is_not_escalated(wired):
    """Resolved work must not page the owner — but must still leave the loop."""
    wired["state"]["open"] = False

    assert _escalate(wired["loop"], _review(), _blocked(), 2) is True, "handled"
    assert wired["loop"].approval_calls == [], "must NOT page about a merged PR"
    assert wired["marked"] == [], "no approval was sent, so nothing to mark sent"
    assert wired["tiered"] == [{"pr": 2551, "tier": 2}], "must still end the retry loop"


def test_unknown_pr_state_STILL_escalates(wired):
    """FAIL-SAFE DIRECTION — the asymmetry is the whole point.

    `None` means we could not determine the state (API error, rate limit).
    Staying silent then would reintroduce the #5413 bug, where a genuinely
    blocked PR reached nobody. A redundant ping is merely noise; silence is a
    stuck PR. These are not equally bad, so they are not treated equally.
    """
    wired["state"]["open"] = None

    assert _escalate(wired["loop"], _review(), _blocked(), 2) is True
    assert len(wired["loop"].approval_calls) == 1, "unknown state must still notify"
    assert wired["marked"] == [2551]


def test_open_pr_still_escalates(wired):
    """The normal case is unchanged."""
    wired["state"]["open"] = True

    assert _escalate(wired["loop"], _review(), _blocked(), 2) is True
    assert len(wired["loop"].approval_calls) == 1


def test_suppression_requires_an_explicit_False():
    """A truthiness check would swallow `None` and re-create the silence bug."""
    src = inspect.getsource(al.AgentLoop._escalate_blocked_merge)
    assert "is False" in src, "must compare identity, not truthiness"
    assert "if not pr_is_open" not in src


# --- pr_is_open itself -----------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"state": "open"}, True),
        ({"state": "closed"}, False),
        ({"state": "open", "merged_at": "2026-07-29T18:11:22Z"}, False),
        ({"state": "closed", "merged": True}, False),
        ({}, None),
    ],
    ids=["open", "closed", "merged_at-wins", "merged-flag", "empty-payload"],
)
def test_pr_is_open_classification(monkeypatch, payload, expected):
    """`merged_at` is checked before `state` — GitHub reports merged PRs closed,
    but a squash-merge briefly races the state field."""
    import tools.repair_bay.services.github_service as gh

    monkeypatch.setattr(gh, "_api_get", lambda path, **kw: (True, payload))
    assert gh.pr_is_open(1) is expected


def test_pr_is_open_returns_none_on_api_failure(monkeypatch):
    """Unknown, NOT closed — the caller treats None as 'still open'."""
    import tools.repair_bay.services.github_service as gh

    monkeypatch.setattr(gh, "_api_get", lambda path, **kw: (False, {"error": "rate limited"}))
    assert gh.pr_is_open(1) is None


def test_pr_is_open_is_repo_aware(monkeypatch):
    """F.O.R.G.E. reviews non-default repos; get_pr_status is hardcoded to REPO_FULL."""
    import tools.repair_bay.services.github_service as gh

    seen = []

    def _fake(path, **kw):
        seen.append(path)
        return (True, {"state": "open"})

    monkeypatch.setattr(gh, "_api_get", _fake)
    gh.pr_is_open(7, repo="KytranKatarn/kytran-business-suite")

    assert seen == ["/repos/KytranKatarn/kytran-business-suite/pulls/7"]


def test_pr_is_open_makes_exactly_one_api_call(monkeypatch):
    """get_pr_status fires FOUR calls; a state check on the refusal path must not."""
    import tools.repair_bay.services.github_service as gh

    calls = []

    def _fake(path, **kw):
        calls.append(path)
        return (True, {"state": "open"})

    monkeypatch.setattr(gh, "_api_get", _fake)
    gh.pr_is_open(1)

    assert len(calls) == 1, f"expected 1 API call, made {len(calls)}"


def test_a_failed_approval_row_is_NOT_marked_as_asked(wired):
    """#5829, previously UNPINNED — which is why the stale double went red instead.

    `kytran_approval_sent` permanently suppresses re-escalation. Setting it when the row
    was never created (draft guard, dedup, or error) retires an OPEN, UNMERGED PR from the
    queue forever. So a falsy approval id must NOT mark, and must report failure so the
    next cycle retries. Same principle as ADR-014: record the artifact, never the intent.
    """
    wired["state"]["approval_id"] = None
    result = {"merged": False, "governance_blocked": True, "error": "nope"}

    assert _escalate(wired["loop"], _review(7777), result, 1) is False
    assert wired["marked"] == [], "a PR with no queue row must never be marked as asked"
