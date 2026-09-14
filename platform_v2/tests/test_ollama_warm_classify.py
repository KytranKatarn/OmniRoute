"""Tests for the Ollama warm-load status classifier (KB #270033 follow-up).

Locks the single source of truth for which HTTP warm-POST statuses are
*contention* (deferred, not a failure) versus a *real* model problem.

Single-sourced in ``services.ollama_warm_classify.py`` and imported by
``ai_bridge.agent_loop._ollama_model_health``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from services.ollama_warm_classify import (
    OUTCOME_DEFERRED,
    OUTCOME_FAILED,
    OUTCOME_RELOADED,
    TRANSIENT_WARM_STATUS_CODES,
    classify_ollama_warm_status,
)


class TestWarmStatusConstants:
    """Module-level constants stay consistent with KB #270033 commitments."""

    def test_transient_set_contains_expected_statuses(self):
        assert TRANSIENT_WARM_STATUS_CODES == {409, 503, 429}


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(200, id="200_ok"),
    ],
)
def test_successful_reload(status_code: int):
    assert classify_ollama_warm_status(status_code) == OUTCOME_RELOADED


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(409, id="409_conflict_already_loading"),
        pytest.param(503, id="503_service_busy"),
        pytest.param(429, id="429_rate_limited"),
    ],
)
def test_busy_hub_contention_is_deferred(status_code: int):
    """Non-200 contention must NOT be counted as a model-health failure.

    KB #270033: counting contention false-alarms the anomaly list every busy
    cycle, producing spurious VRAM-drift misdiagnoses.
    """
    assert classify_ollama_warm_status(status_code) == OUTCOME_DEFERRED


@pytest.mark.parametrize(
    "status_code",
    [
        pytest.param(404, id="404_model_not_found"),
        pytest.param(400, id="400_bad_request"),
        pytest.param(500, id="500_internal_load_failure"),
        pytest.param(302, id="302_redirect_unexpected"),
        pytest.param(1, id="1_http1_pseudo_code"),
    ],
)
def test_real_failures_stay_failed(status_code: int):
    """A genuinely broken model must keep producing a real signal.

    404 (uninstalled), 400 (bad param), and 500 (deterministic load failure)
    must not be masked by deferral.
    """
    assert classify_ollama_warm_status(status_code) == OUTCOME_FAILED
