"""Unit tests for services.dispatch_cycle.classify_dispatch_cycle (#4151).

The weekly warden_compliance_check job dispatches one capability to a cold 7B
model, which returns queued=True instead of a finished result. The old job
treated queued-as-failed AND swallowed the real reason (error_message NULL).
These tests pin the queue-tolerant classification.

PURE — no DB. Run from platform_v2/:
    docker exec archie_platform python3 -m pytest services/tests/test_dispatch_cycle.py -v
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.dispatch_cycle import classify_dispatch_cycle, CycleOutcome  # noqa: E402


def _result(**kw):
    base = {"success": False, "queued": False, "queue_id": None, "response": None, "error": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_sync_success_warm_model():
    out = classify_dispatch_cycle(_result(success=True, response="all good"))
    assert (out.items_processed, out.items_failed) == (1, 0)
    assert out.error_message is None
    assert out.response == "all good"


def test_queued_then_done_is_success_with_report():
    out = classify_dispatch_cycle(
        _result(queued=True, queue_id=63704),
        {"status": "done", "result_response": "weekly report body", "error": None},
    )
    assert (out.items_processed, out.items_failed) == (1, 0)
    assert out.error_message is None
    assert out.response == "weekly report body"


def test_queued_then_failed_captures_real_reason():
    # The exact failure that produced today's blank observer error.
    out = classify_dispatch_cycle(
        _result(queued=True, queue_id=63704),
        {"status": "failed", "result_response": None, "error": "zombie: stuck running >30 min"},
    )
    assert (out.items_processed, out.items_failed) == (0, 1)
    assert "zombie" in out.error_message  # reason is no longer swallowed → NULL


def test_queued_then_expired_is_failure():
    out = classify_dispatch_cycle(
        _result(queued=True, queue_id=1),
        {"status": "expired", "result_response": None, "error": None},
    )
    assert out.items_failed == 1
    assert "expired" in out.error_message


def test_queued_still_pending_is_not_a_false_failure():
    # queue_final None => still in progress at poll timeout. Must NOT log a failure.
    out = classify_dispatch_cycle(_result(queued=True, queue_id=42), None)
    assert out.items_failed == 0
    assert out.items_processed == 1
    assert out.error_message is None
    assert "in progress" in out.response


def test_queued_non_terminal_status_treated_as_in_progress():
    out = classify_dispatch_cycle(
        _result(queued=True, queue_id=7),
        {"status": "running", "result_response": None, "error": None},
    )
    assert out.items_failed == 0
    assert out.items_processed == 1


def test_immediate_failure_captures_error():
    out = classify_dispatch_cycle(_result(success=False, error="no skilled agent available"))
    assert (out.items_processed, out.items_failed) == (0, 1)
    assert out.error_message == "no skilled agent available"


def test_immediate_failure_default_reason_when_no_error():
    out = classify_dispatch_cycle(_result(success=False))
    assert out.items_failed == 1
    assert out.error_message == "dispatch returned success=False"


def test_none_result_is_failure_not_crash():
    out = classify_dispatch_cycle(None, None)
    assert out.items_failed == 1
    assert out.error_message == "dispatch returned success=False"


def test_cycle_outcome_equality():
    a = CycleOutcome(1, 0, None, "x")
    b = CycleOutcome(1, 0, None, "x")
    assert a == b
