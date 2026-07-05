from __future__ import annotations

from tools.repair_bay.services.pr_review_service import decide_reap_action


def test_reset_below_cap():
    assert decide_reap_action(0, 3) == "reset"
    assert decide_reap_action(2, 3) == "reset"


def test_skip_at_or_above_cap():
    assert decide_reap_action(3, 3) == "skip"
    assert decide_reap_action(5, 3) == "skip"


def test_default_cap_is_three():
    assert decide_reap_action(2) == "reset"
    assert decide_reap_action(3) == "skip"
