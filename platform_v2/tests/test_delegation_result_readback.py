"""Reading a finished delegation back out (#6733).

The delegated answer has always been written to ``work_notes``. The gap was that
nothing could USE it: ``/api/internal/delegation/<id>/status`` returned every
note glued together -- dispatch banner, retries and the reply in one blob -- so
the engine kept the receipt ("Delegated to the A.R.C.H.I.E. team as task #N") as
the assistant turn and a follow-up had nothing to follow up ON.

These pin the two rules that make the answer machine-readable: which note IS the
reply, and when the task has stopped moving. Both are pure functions in
delegation_service so there is ONE definition and a caller cannot keep a private
copy that drifts.

The note-type and status vocabularies are measured against live data, not
guessed -- the fixtures below are real note shapes from the production DB
(2026-09-12).
"""

import ast
import os

import pytest

from services.delegation_service import (
    DELEGATION_TERMINAL_STATUSES,
    is_delegation_terminal,
    resolve_delegation_result,
)

# Real note text, copied from work_notes on 2026-09-12. The point of using the
# real shapes is that the banner is the trap: it is a plausible-looking string
# that is NOT the answer, and a naive reader returns it.
_LLM_BANNER = (
    "⚠️ ADVISORY ONLY -- fleet code delegation produces analysis/"
    "instructions, NOT a branch or PR.\n\nDispatched to agent=M.O.D.U.L. "
    "model=qwen2.5:7b"
)
_LLM_ANSWER = "```python\ndef clamp(value, lo, hi):\n    return max(lo, min(value, hi))\n```"
_KNOWN_TOOL_ANSWER = "Documented PR #3309 -> KB vault_note #315657"


# ---------------------------------------------------------------------------
# which note is the answer
# ---------------------------------------------------------------------------


def test_llm_path_prefers_the_output_note_over_the_banner():
    """The LLM path writes BOTH notes and only one is the reply.

    Returning result_note here would hand the caller
    "Dispatched to agent=... model=..." and present it as the agent's answer.
    """
    text, source = resolve_delegation_result(_LLM_ANSWER, _LLM_BANNER)
    assert text == _LLM_ANSWER
    assert source == "delegation_output"


def test_known_tool_path_falls_back_to_the_result_note():
    """The known-tool path writes NO delegation_output -- 379 of 451 completed
    delegations measured 2026-09-12. Reading only delegation_output returns
    nothing on 84% of tasks."""
    text, source = resolve_delegation_result(None, _KNOWN_TOOL_ANSWER)
    assert text == _KNOWN_TOOL_ANSWER
    assert source == "delegation_result"


def test_no_notes_yet_is_reported_as_absent_not_as_an_empty_answer():
    """A task still running has neither note. It must read as "no answer yet",
    never as an empty reply -- an empty string presented as the answer is the
    exact masking this change exists to remove."""
    assert resolve_delegation_result(None, None) == (None, None)


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", "\t "])
def test_whitespace_only_notes_are_absent(blank):
    """A blank note is not an answer. It must not shadow a real one either."""
    assert resolve_delegation_result(blank, None) == (None, None)
    text, source = resolve_delegation_result(blank, _KNOWN_TOOL_ANSWER)
    assert text == _KNOWN_TOOL_ANSWER
    assert source == "delegation_result"


def test_a_non_string_note_never_becomes_the_answer():
    """psycopg2 hands back None for a missing subselect, but a schema change or
    a JSONB column could hand back something else. Fail to "no answer", never to
    str(<object>)."""
    assert resolve_delegation_result({"content": "x"}, None) == (None, None)
    assert resolve_delegation_result(0, None) == (None, None)


# ---------------------------------------------------------------------------
# when the task has stopped moving
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["completed", "cancelled", "blocked"])
def test_terminal_statuses_stop_a_poller(status):
    assert is_delegation_terminal(status)


@pytest.mark.parametrize("status", ["pending", "in_progress"])
def test_running_statuses_do_not_stop_a_poller(status):
    """'blocked' IS terminal but 'pending' is not, and the distinction is load
    bearing: the reclaimer flips a retryable task back to 'pending' and only
    lands on 'blocked' once retries are exhausted."""
    assert not is_delegation_terminal(status)


@pytest.mark.parametrize("status", [None, "", "COMPLETED", "done", 3])
def test_an_unknown_status_never_reads_as_terminal(status):
    """Fail-safe direction: an unrecognised status keeps the poller polling
    until its own wall, rather than declaring a running task finished and
    reporting a missing answer as the final one."""
    assert not is_delegation_terminal(status)


# ---------------------------------------------------------------------------
# the endpoint must actually use them
# ---------------------------------------------------------------------------


def _status_endpoint_source() -> str:
    """The body of api_internal_delegation_status, from app.py's AST.

    Read from source rather than imported because importing app.py pulls in the
    whole Flask application. FAIL LOUDLY if the function is gone or renamed -- a
    contract test that silently finds nothing is worse than no test.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "app.py")
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "api_internal_delegation_status":
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(
        "api_internal_delegation_status not found in app.py -- if it was renamed, "
        "update this test; do not delete it."
    )


def test_endpoint_publishes_the_named_answer_and_terminal_flag():
    """The engine polls this endpoint and reads these keys by name.

    Dropping one does not raise anywhere -- the poller just never settles and
    the receipt stays in the conversation, which is the bug being fixed.
    """
    body = _status_endpoint_source()
    for key in ('"result"', '"result_source"', '"failure"', '"terminal"'):
        assert key in body, f"status payload lost {key} -- the engine reads it by name"


def test_endpoint_delegates_the_rules_instead_of_reimplementing_them():
    """Two definitions of "which note is the answer" is how they drift."""
    body = _status_endpoint_source()
    assert "resolve_delegation_result(" in body
    assert "is_delegation_terminal(" in body


def test_endpoint_still_returns_work_notes():
    """The human-readable blob stays: the DHQ panel and any existing reader of
    this endpoint expect it. Adding `result` must not take it away."""
    assert '"work_notes"' in _status_endpoint_source()


def test_note_aggregation_is_deterministically_ordered():
    """Measured on task 6735: the banner and the reply carry the BYTE-IDENTICAL
    created_at (18:06:46.195137), so ordering by created_at alone leaves their
    order up to the planner -- the blob could read reply-then-banner on one call
    and banner-then-reply on the next. `wn.id` breaks the tie."""
    body = _status_endpoint_source()
    assert (
        "ORDER BY wn.created_at, wn.id" in body
    ), "work_notes aggregation must tie-break on wn.id -- notes share a timestamp"


def test_result_subselects_take_the_newest_note():
    """A retried task has more than one note of a type; the LAST one is the
    outcome. Same tie-break reasoning as above, descending."""
    body = _status_endpoint_source()
    assert (
        body.count("ORDER BY wn.created_at DESC, wn.id DESC LIMIT 1") == 3
    ), "each of output/result/failure must select the newest note deterministically"


def test_terminal_set_is_not_silently_widened():
    """A frozen copy of the vocabulary. Adding a status is fine -- but it should
    be a deliberate edit here too, because every poller's stopping rule and this
    set are the same decision."""
    assert DELEGATION_TERMINAL_STATUSES == frozenset({"completed", "cancelled", "blocked"})
