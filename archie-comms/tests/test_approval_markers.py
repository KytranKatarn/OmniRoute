"""COO Cockpit Slice 1 — chat-native approval markers.

A.R.C.H.I.E. lists + approves/denies in conversation on the same rail as
{{DELEGATE}}. _extract_approval_markers harvests the markers into SSE events and
strips them from the visible reply text.
"""

import services.conversation_service as cs


def test_parse_approvals_list_marker():
    text = "Sure, here are your pending items. {{APPROVALS}}"
    events, clean = cs._extract_approval_markers(text)
    assert {"type": "approvals_list_request"} in events
    assert "{{APPROVALS}}" not in clean


def test_parse_approve_marker():
    text = 'Approving that now. {{APPROVE id="autonomy:2782"}}'
    events, clean = cs._extract_approval_markers(text)
    assert {
        "type": "approval_action",
        "verb": "approve",
        "approval_id": "autonomy:2782",
        "reason": "",
    } in events
    assert "{{APPROVE" not in clean


def test_parse_deny_marker_with_reason():
    text = 'Denying. {{DENY id="autonomy:5" reason="not now"}}'
    events, clean = cs._extract_approval_markers(text)
    assert {
        "type": "approval_action",
        "verb": "deny",
        "approval_id": "autonomy:5",
        "reason": "not now",
    } in events
    assert "{{DENY" not in clean


def test_deny_marker_without_reason_defaults_empty():
    text = 'Ok. {{DENY id="autonomy:8"}}'
    events, clean = cs._extract_approval_markers(text)
    assert {
        "type": "approval_action",
        "verb": "deny",
        "approval_id": "autonomy:8",
        "reason": "",
    } in events
    assert "{{DENY" not in clean


def test_no_markers_returns_empty_events_and_unchanged_text():
    text = "Just a normal reply with no markers."
    events, clean = cs._extract_approval_markers(text)
    assert events == []
    assert clean == text


def test_approvals_marker_is_not_confused_with_approve():
    # {{APPROVALS}} must not be parsed as an {{APPROVE id=...}} action.
    text = "Here they are {{APPROVALS}}"
    events, clean = cs._extract_approval_markers(text)
    assert events == [{"type": "approvals_list_request"}]
    assert "APPROVALS" not in clean
