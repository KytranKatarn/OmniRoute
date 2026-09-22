"""Telegram is for CRITICAL and OUTAGES. Everything else belongs in COMs (owner, 2026-09-22).

OWNER DIRECTIVE, verbatim: "in Department HQ module we have coms tab and there is
archie.kytranempowerment.com telegram should be critical or outages. Department HQ module
has Approvals tab for approvals."

MEASURED 24h of ACTUAL deliveries (status='sent' — the log also records 'throttled' rows
that never left the building, 1,412 of them):

    system            486   watchdogs repeating standing conditions
    approval_request  318   prompts whose buttons mostly answer
                            "not found or already processed"
    everything else    38
                      ---
                      842

WHY A POLICY GATE AND NOT ANOTHER THROTTLE: this service has THREE delivery paths with
three different rules —
    send()              per-priority throttle
    submit_via_inbox()  2h cooldown (in-process, so --workers 4 lets 4x through)
    send_with_buttons() NO GATE AT ALL
Approvals and alerts use the third, which is why 318 approval prompts arrive despite
approval_request falling back to info/low, whose throttle nominally allows one per day.
Adding a fourth rule to a fourth place is how this got here. One policy, consulted by every
path, is the fix.

⚠️ FAIL-OPEN, and the asymmetry is deliberate: if the settings read fails we DELIVER.
Missing a real outage is worse than a temporary return to noise. Failing closed would make
a DB blip silence the very alerts this policy exists to protect.
"""

from __future__ import annotations

import pytest

from services.telegram_service import _should_deliver


def _ok(category, title="x", severity=None):
    delivered, _reason = _should_deliver(category, title, severity)
    return delivered


# --- what MUST still reach the phone ----------------------------------------


def test_security_is_always_delivered():
    assert _ok("security", "Intrusion attempt detected") is True


def test_explicit_critical_severity_is_delivered():
    assert _ok("system", "Something dire", severity="critical") is True


@pytest.mark.parametrize(
    "title",
    [
        "Fleet mass-offline: 5 nodes unreachable",
        "DR posture changed — failover armed",
        "Platform down — hub unreachable",
        "Backup FAILED — database dump did not complete",
        "Restore failed on staging",
        "Disk full on /mnt/data2",
    ],
)
def test_named_outage_conditions_are_delivered(title):
    """The allowlist is the whole reason this is not 'security only' — a real outage pages."""
    assert _ok("system", title) is True


# --- what must go to COMs instead -------------------------------------------


def test_approvals_go_to_the_approvals_tab():
    delivered, reason = _should_deliver("approval_request", "Approval Required — cloud_throughput_escalation #19467")
    assert delivered is False
    assert "approval" in reason.lower()


def test_routine_watchdog_pressure_is_not_an_outage():
    """DISK_PRIMARY *pressure* is a warning; 'disk full' is the outage. Do not conflate."""
    assert _ok("system", "Platform Watchdog: DISK_PRIMARY pressure") is False


def test_the_repeating_watchdog_titles_are_suppressed():
    for title in (
        "HR Alert: Ollama KEEP_ALIVE stalled on 1 model(s)",
        "⚠️ WTF ingest stalled",
        "Platform Watchdog: BACKUP_TIER_HEALTH pressure",
        "⚠️ WTF beat coverage low",
    ):
        assert _ok("system", title) is False, f"{title} should not page the owner"


def test_info_is_not_delivered():
    assert _ok("info", "Cluster overflow activated: 686 agents across 374 capabilities") is False


def test_forge_and_agent_chatter_is_not_delivered():
    assert _ok("forge", "PR reviewed") is False
    assert _ok("agent", "Agent finished a task") is False


# --- reversibility + fail-open ----------------------------------------------


def test_policy_can_be_switched_off_at_runtime(monkeypatch):
    """One platform_settings key restores the old behaviour with no deploy."""
    monkeypatch.setattr("services.telegram_service._policy_enabled", lambda: False)
    assert _ok("info", "anything at all") is True


def test_a_settings_failure_fails_OPEN(monkeypatch):
    """Missing an outage is worse than noise — a DB blip must not mute the platform."""

    def boom():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr("services.telegram_service._policy_enabled", boom)
    assert _ok("info", "anything at all") is True


# ---------------------------------------------------------------------------
# REAL production titles. A first draft of the allowlist GUESSED the wording and
# would have silenced every one of these. Replaying 60 days of deliveries caught it.
# These are verbatim from telegram_message_log — do not "tidy" them.
# ---------------------------------------------------------------------------

MUST_PAGE = [
    ("system", "[CRITICAL] SMART CRITICAL: /dev/sdb (ST3000DM008-2DM166 Z504K0DJ)"),
    ("system", "SMART CRITICAL: /dev/sdc (ST1000DM003-9YN162 W1D16EEK)"),
    ("system", "[CRITICAL] Dispatch failure rate spike"),
    ("system", "[WARNING] Fleet: 3 nodes OFFLINE"),
    ("system", "[WARNING] Fleet: 2 nodes OFFLINE"),
    ("system", "[WARNING] Backup posture: backup attempts are failing"),
    ("system", "[WARNING] DR posture: replica NOT STREAMING"),
    ("system", "[WARNING] DR posture: cold backup stale"),
    ("security", "[CRITICAL] Compliance Auto-Apply"),
]

MUST_STAY_QUIET = [
    ("system", "Platform Watchdog: DISK_PRIMARY pressure"),
    ("system", "HR Alert: Ollama KEEP_ALIVE stalled on 1 model(s)"),
    ("system", "[WARNING] ❌ Skill failed — linkedin_post"),
    ("approval_request", "[MEDIUM] Approval Required — cloud_throughput_escalation #19467"),
    # ⚠️ A PR TITLE IS NOT AN OUTAGE. This matched an outage marker in the first draft and
    # would have paged the owner for a code review.
    ("pr_reviewed", "[INFO] F.O.R.G.E. Review: APPROVE — KytranKatarn/archie-platform #3433 failover"),
    ("forge", "[CRITICAL] pipeline note"),
]


@pytest.mark.parametrize("category,title", MUST_PAGE)
def test_real_outage_titles_still_page(category, title):
    delivered, reason = _should_deliver(category, title)
    assert delivered is True, f"SILENCED a real outage: {title!r} ({reason})"


@pytest.mark.parametrize("category,title", MUST_STAY_QUIET)
def test_real_noise_titles_stay_quiet(category, title):
    delivered, reason = _should_deliver(category, title)
    assert delivered is False, f"would page for noise: {title!r} ({reason})"
