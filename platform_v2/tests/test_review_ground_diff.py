"""Grounding is checked against the FULL diff, not the chunk (#5848 Decision 2).

Task 2 of docs/superpowers/plans/2026-08-20-chunked-multipass-pr-review.md.

Inside `_structured_review` the single `diff` argument serves FIVE consumers, and chunking
splits them into two kinds:

  what the MODEL SEES     -> the chunk        (_build_json_prompt)
  what a finding is JUDGED AGAINST -> the full diff  (evidence, self-refute, provenance,
                                                      artifact-absence claims)

If grounding used the chunk, a finding whose evidence lives in another chunk would be dropped
as ungrounded — and that is a REAL defect class that splitting itself manufactures (a caller
in chunk 1 broken by a signature change in chunk 3). Decision 2 of the spec resolves it: judge
against the whole PR, show only the chunk.

These assertions are source-level on purpose. `_structured_review` dispatches to a live model,
so a behavioural test would need the whole dispatcher stubbed; the property that matters here
is purely which argument reaches which call, which the source states exactly.
"""

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SRC = (_ROOT / "tools" / "repair_bay" / "services" / "pr_diff_analyzer.py").read_text()

# Consumers that judge a finding — these must see the WHOLE PR.
_GROUNDING_CONSUMERS = (
    "_verify_evidence",
    "_self_refute_criticals",
    "_check_dockerfile_provenance",
    "strip_unsupported_claims",
)


def _fn(name):
    for n in ast.walk(ast.parse(_SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            seg = ast.get_source_segment(_SRC, n)
            assert seg, f"could not extract source for {name}"
            return seg
    raise AssertionError(f"{name} not found — renamed?")


def test_structured_review_accepts_ground_diff():
    body = _fn("_structured_review")
    signature = body.split("\n)")[0] if body.startswith("def _structured_review(\n") else body.splitlines()[0]
    assert "ground_diff" in signature, "ground_diff must be a parameter of _structured_review"


def test_ground_diff_defaults_so_existing_callers_are_unchanged():
    """Every pre-chunking caller passes no ground_diff and must behave exactly as before."""
    body = _fn("_structured_review")
    assert "ground_diff: str = None" in body or "ground_diff=None" in body


def test_grounding_consumers_judge_against_the_full_diff():
    body = _fn("_structured_review")
    for consumer in _GROUNDING_CONSUMERS:
        idx = body.find(consumer + "(")
        assert idx > 0, f"{consumer} call not found in _structured_review"
        call = body[idx : idx + 140]
        assert "ground_diff" in call, (
            f"{consumer} must judge against the FULL diff (ground_diff), not the chunk — "
            "otherwise a cross-chunk finding is dropped as ungrounded"
        )


def test_the_prompt_still_shows_only_the_chunk():
    """The MODEL must see the chunk. Widening the prompt to the full diff would defeat
    the entire point of chunking."""
    body = _fn("_structured_review")
    assert "_build_json_prompt(" in body
    for idx in range(len(body)):
        idx = body.find("_build_json_prompt(", idx)
        if idx < 0:
            break
        call = body[idx : idx + 90]
        assert "ground_diff" not in call, "the prompt must show the CHUNK, never the full diff"
        idx += 1
