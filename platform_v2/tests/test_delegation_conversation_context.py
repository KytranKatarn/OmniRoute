"""Conversation context reaches the delegated agent, bounded (#6729).

A follow-up used to arrive with no history at all: the engine sent
``history_length`` -- a COUNT -- and never the turns. Measured on task #6727,
one turn after answering "Titan": asked *"Is it bigger than the planet Mercury?
Answer in one sentence and name it explicitly"*, the agent could not name it and
answered "No" -- the opposite of the truth (Titan ~5,149 km, Mercury ~4,879 km).
It did not ask what "it" meant, because nothing told it a referent existed.

The bounds are the load-bearing part. The 7B fleet runs NUM_PARALLEL=1 with real
KV-cache pressure, so an unbounded history block degrades every concurrent
dispatch on that node -- which is why the caps are enforced server-side rather
than trusted from the sender.
"""

import ast
import os

import pytest

from services.delegation_service import (
    _CONV_MAX_CHARS,
    _CONV_MAX_CHARS_PER_TURN,
    _CONV_MAX_TURNS,
    clamp_conversation,
    render_conversation,
)

DELEGATION_PY = os.path.join(os.path.dirname(__file__), "..", "services", "delegation_service.py")


def _turns(n, role_cycle=("user", "assistant"), body="msg"):
    return [{"role": role_cycle[i % len(role_cycle)], "content": f"{body}{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# clamping
# ---------------------------------------------------------------------------


def test_keeps_the_newest_turns_not_the_oldest():
    """A follow-up refers to the LAST exchange; trimming the tail defeats it."""
    out = clamp_conversation(_turns(_CONV_MAX_TURNS + 4))
    assert len(out) == _CONV_MAX_TURNS
    assert out[-1]["content"] == f"msg{_CONV_MAX_TURNS + 3}"  # newest survived
    assert out[0]["content"] != "msg0"  # oldest dropped


def test_output_is_chronological():
    out = clamp_conversation(_turns(4))
    assert [t["content"] for t in out] == ["msg0", "msg1", "msg2", "msg3"]


def test_system_and_tool_rows_are_dropped():
    """Engine bookkeeping burns the budget without helping resolve a pronoun."""
    out = clamp_conversation(
        [
            {"role": "system", "content": "you are a helpful assistant"},
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": '{"ok": true}'},
            {"role": "assistant", "content": "hi"},
        ]
    )
    assert [t["role"] for t in out] == ["user", "assistant"]


def test_one_huge_turn_is_truncated_not_dropped():
    out = clamp_conversation([{"role": "user", "content": "x" * 5000}])
    assert len(out) == 1
    assert len(out[0]["content"]) <= _CONV_MAX_CHARS_PER_TURN + len(" […truncated]")
    assert out[0]["content"].endswith("[…truncated]")


def test_total_budget_drops_from_the_oldest_end():
    """Over budget, the NEWEST turns must be the ones that survive."""
    big = "y" * _CONV_MAX_CHARS_PER_TURN
    out = clamp_conversation([{"role": "user", "content": f"{i}{big}"} for i in range(_CONV_MAX_TURNS)])
    assert sum(len(t["content"]) for t in out) <= _CONV_MAX_CHARS
    assert out, "budget trimming must not empty a conversation of normal-sized turns"
    assert out[-1]["content"].startswith(str(_CONV_MAX_TURNS - 1))  # newest kept


@pytest.mark.parametrize(
    "junk",
    [
        None,
        "a string",
        123,
        {"role": "user", "content": "not in a list"},
        [None, 5, "x"],
        [{"role": "user"}],  # no content
        [{"content": "no role"}],
        [{"role": "user", "content": None}],
        [{"role": "user", "content": "   "}],  # whitespace only
        [{"role": "wizard", "content": "unknown role"}],
    ],
)
def test_malformed_input_degrades_to_no_history_and_never_raises(junk):
    """Losing context is a worse answer; raising is a lost task. Fail safe."""
    assert clamp_conversation(junk) == []
    assert render_conversation(junk) == ""


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_render_is_empty_when_there_is_nothing_to_say():
    """No history must add NO lines -- a bare label would be noise in the prompt."""
    assert render_conversation([]) == ""


def test_render_labels_speakers_and_keeps_order():
    block = render_conversation(
        [
            {"role": "user", "content": "largest moon of Saturn?"},
            {"role": "assistant", "content": "Titan"},
        ]
    )
    assert "User: largest moon of Saturn?" in block
    assert "You: Titan" in block
    assert block.index("largest moon") < block.index("Titan")


def test_render_carries_the_referent_a_followup_needs():
    """The #6727 regression, stated as an assertion."""
    block = render_conversation(
        [
            {"role": "user", "content": "Name the largest moon of Saturn."},
            {"role": "assistant", "content": "Titan"},
        ]
    )
    assert "Titan" in block


# ---------------------------------------------------------------------------
# prompt assembly -- ordering is load-bearing
# ---------------------------------------------------------------------------


def _fn(name):
    tree = ast.parse(open(DELEGATION_PY).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _appended_sources(fn):
    """Source text of each ``prompt_lines.append(...)`` argument, in order."""
    out = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "prompt_lines"
            and node.args
        ):
            out.append((node.lineno, ast.dump(node.args[0])))
    return [src for _, src in sorted(out)]


def test_conversation_is_appended_before_the_reason():
    """The agent needs referents in hand BEFORE it reads the instruction."""
    appended = _appended_sources(_fn("_execute_via_dispatcher"))
    conv = next(i for i, src in enumerate(appended) if "conversation_block" in src)
    reason = next(i for i, src in enumerate(appended) if "Reason: " in src)
    assert conv < reason, f"conversation must precede reason; got {appended}"


def test_history_does_not_ride_in_args():
    """``args`` is rendered as json.dumps(payload)[:500] -- truncated raw JSON.

    Routing history through it would silently drop most of a conversation and
    hand the model a JSON fragment cut mid-token. Pin the separation.
    """
    src = open(DELEGATION_PY).read()
    tree = ast.parse(src)
    fn = _fn("execute_delegated_task")
    reads = {
        n.args[0].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "get"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "args"
        and n.args
        and isinstance(n.args[0], ast.Constant)
    }
    assert "conversation" in reads, "conversation must be its own delegation_args key"
    # and the truncated Args line must still exist, unchanged, for payload only
    assert "json.dumps(payload)[:500]" in src
