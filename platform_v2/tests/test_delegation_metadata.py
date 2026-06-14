"""Unit tests for delegation result surfacing + code-advisory (#4167).

Background: delegated task results are persisted to the `work_notes` TABLE
(note_type='delegation_output'), but were NOT surfaced on the unified_task
itself (`unified_tasks.metadata` stayed empty). That made a completed delegation
look like "nothing happened" — it caused a real misdiagnosis (a 'code' delegation
was wrongly called a false-completion, KB #273387). Separately, capability='code'
delegation returns TEXT instructions, never a branch/PR, so it must never be
mistaken for a shipped code change.

build_delegation_metadata is the pure helper that builds the `delegation` block
merged into unified_tasks.metadata on completion: a preview + pointer to the full
output in work_notes, plus an advisory for code-merge capabilities.

Run from platform_v2/ (container path /app):
    docker exec archie_platform python3 -m pytest tests/test_delegation_metadata.py -v
"""

from services.delegation_service import (
    CODE_MERGE_CAPABILITIES,
    build_delegation_metadata,
)


def test_surfaces_output_preview_and_pointer():
    resp = "Detailed analysis line 1.\nLine 2 with findings.\n" * 20
    meta = build_delegation_metadata("research", resp)
    assert meta["outcome"] == "completed"
    assert meta["capability"] == "research"
    assert meta["result_chars"] == len(resp.strip())
    assert meta["result_note_type"] == "delegation_output"  # full text lives in work_notes
    assert meta["result_preview"] == resp.strip()[:280]
    assert len(meta["result_preview"]) <= 280


def test_code_capability_carries_advisory():
    meta = build_delegation_metadata("code", "1. Open file. 2. Remove block.")
    assert "advisory" in meta
    advisory = meta["advisory"].lower()
    assert "analysis" in advisory
    assert "pr" in advisory  # points to the PR workflow
    assert "code" in CODE_MERGE_CAPABILITIES


def test_non_code_capability_has_no_advisory():
    for cap in ("research", "documentation", "analyze", "code_review"):
        meta = build_delegation_metadata(cap, "some output")
        assert "advisory" not in meta, f"{cap} should not get a code advisory"


def test_empty_response_is_safe():
    for resp in (None, "", "   "):
        meta = build_delegation_metadata("research", resp)
        assert meta["result_chars"] == 0
        assert meta["result_preview"] == ""
        assert meta["outcome"] == "completed"


def test_via_marker_recorded_when_provided():
    meta = build_delegation_metadata("research", "out", via="queue_callback")
    assert meta["via"] == "queue_callback"
    # default (sync) path has no via marker
    assert "via" not in build_delegation_metadata("research", "out")


def test_unknown_capability_defaults_safely():
    meta = build_delegation_metadata(None, "out")
    assert meta["capability"] == "unknown"
    assert "advisory" not in meta
