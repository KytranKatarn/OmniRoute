"""Unit tests for the drain-worker liveness decisions (#5699).

These target the PURE decision helpers in services/dispatch_drain_monitor.py —
no DB, no Telegram. Per the backup_posture_monitor lesson: an end-to-end run
against an empty test DB reports 'unknown' everywhere and exercises nothing,
so we test the decision, not the wiring. Every assertion below fails against
an inverted implementation (verified by construction: each case pins a
different branch of the truth table).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dispatch_drain_monitor import (  # noqa: E402
    HEARTBEAT_STALL_MIN_DEFAULT,
    QUEUE_STALL_MIN_DEFAULT,
    heartbeat_is_stale,
    queue_is_stalled,
)


class TestHeartbeatIsStale:
    def test_no_heartbeat_rows_is_unknown_not_stale(self):
        # A fresh deploy (heartbeats ship with this change) must not page.
        assert heartbeat_is_stale(None, HEARTBEAT_STALL_MIN_DEFAULT) is False

    def test_fresh_heartbeat_is_not_stale(self):
        assert heartbeat_is_stale(0.25, 5.0) is False

    def test_exactly_at_limit_is_not_stale(self):
        # Boundary: the alert fires strictly PAST the limit, so a threshold-touching
        # slow cycle does not page on its own.
        assert heartbeat_is_stale(5.0, 5.0) is False

    def test_past_limit_is_stale(self):
        assert heartbeat_is_stale(5.1, 5.0) is True

    def test_fifty_hour_outage_is_stale(self):
        # The 2026-08-13 scheduler outage: ~3,001 minutes without a cycle.
        assert heartbeat_is_stale(3001.0, HEARTBEAT_STALL_MIN_DEFAULT) is True


class TestQueueIsStalled:
    def test_empty_queue_is_never_stalled(self):
        # Even with no claim progress at all: no waiting work, no alarm.
        assert queue_is_stalled(0, None, QUEUE_STALL_MIN_DEFAULT) is False
        assert queue_is_stalled(0, 999.0, QUEUE_STALL_MIN_DEFAULT) is False

    def test_waiting_work_with_no_claim_ever_is_stalled(self):
        # claimed_at NULL everywhere = the worker has never claimed anything —
        # the worst case, not an excuse.
        assert queue_is_stalled(3, None, 30.0) is True

    def test_waiting_work_with_recent_claims_is_not_stalled(self):
        # Old rows can exist while the drain is merely behind — claims advancing
        # within the window means progress, not liveness failure.
        assert queue_is_stalled(10, 2.0, 30.0) is False

    def test_waiting_work_with_stale_claims_is_stalled(self):
        assert queue_is_stalled(1, 45.0, 30.0) is True

    def test_claim_age_boundary_is_not_stalled(self):
        assert queue_is_stalled(5, 30.0, 30.0) is False
