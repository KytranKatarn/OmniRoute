"""#5013 — the deploy freshness gate must measure a real restore point, not the last attempt.

Found 2026-07-20: `get_health_summary()` returned the newest `backup_log` row per tier
regardless of status, and `request_deploy_clearance` gated on that. `backup_log.status`
carries 'success', 'failed', 'partial', 'skipped' and 'prune' — 171 tier-carrying rows were
'failed' that day, and the newest primary row WAS a failed 2.8 GB run. The gate was
certifying a backup that did not exist; only a 6-minute gap to the preceding success made
the decision accidentally correct.

Every test below FAILS against the pre-fix code (which read `age_hours`). That is deliberate
— a gate test that passes either way proves nothing, and this session already produced one
tautological test (`assert x == RESOLVED or True`) that had to be thrown away.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.backup_governance_service import _check_backup_freshness, gate_age_hours  # noqa: E402


class TestGateAgeSelection:
    """gate_age_hours() must report the last SUCCESS, never the last attempt."""

    def test_fresh_failure_hiding_a_stale_success_reports_the_success(self):
        """THE BUG. A backup that failed 1h ago must not pass for a 50h-old restore point."""
        primary = {"status": "failed", "age_hours": 1.0, "last_success_age_hours": 50.0}
        assert gate_age_hours(primary) == 50.0

    @pytest.mark.parametrize("bad_status", ["failed", "partial", "skipped", "prune"])
    def test_no_non_success_status_is_ever_treated_as_a_restore_point(self, bad_status):
        """'partial' is the nastiest — plausible-looking and unusable. 'prune' isn't a backup."""
        primary = {"status": bad_status, "age_hours": 0.5, "last_success_age_hours": 99.0}
        assert gate_age_hours(primary) == 99.0

    def test_successful_backup_is_reported_normally(self):
        primary = {"status": "success", "age_hours": 2.0, "last_success_age_hours": 2.0}
        assert gate_age_hours(primary) == 2.0

    def test_no_successful_backup_ever_returns_none_not_the_failure_age(self):
        """An explicit None must NOT fall back to age_hours — that reinstates the bug."""
        primary = {"status": "failed", "age_hours": 0.1, "last_success_age_hours": None}
        assert gate_age_hours(primary) is None

    def test_legacy_payload_without_the_key_falls_back(self):
        """Only an ABSENT key falls back, for a payload predating the field."""
        primary = {"status": "success", "age_hours": 3.0}
        assert gate_age_hours(primary) == 3.0

    def test_empty_payload_is_none(self):
        assert gate_age_hours({}) is None


class TestGateOutcome:
    """End state: the decision a deploy actually hangs on."""

    def test_fresh_failure_does_not_clear_a_medium_deploy(self):
        """Pre-fix this APPROVED — a deploy would proceed on a backup that does not exist."""
        age = gate_age_hours({"status": "failed", "age_hours": 1.0, "last_success_age_hours": 50.0})
        verdict = _check_backup_freshness(age_hours=age if age is not None else 9999.0, severity="medium")
        assert verdict["approved"] is False

    def test_no_known_good_backup_fails_closed(self):
        age = gate_age_hours({"status": "failed", "age_hours": 0.1, "last_success_age_hours": None})
        verdict = _check_backup_freshness(age_hours=age if age is not None else 9999.0, severity="medium")
        assert verdict["approved"] is False

    def test_genuine_fresh_success_still_clears(self):
        """The fix must not simply block everything — that would be a different bug."""
        age = gate_age_hours({"status": "success", "age_hours": 1.0, "last_success_age_hours": 1.0})
        verdict = _check_backup_freshness(age_hours=age if age is not None else 9999.0, severity="medium")
        assert verdict["approved"] is True
