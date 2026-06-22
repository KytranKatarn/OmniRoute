"""Unit tests for the S7-P6.5a onboarding state machine (forward-only transitions,
business-email validation). DB-backed transition/overview are validated live. No DB here.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_signal_onboarding.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import signal_onboarding_service as ob  # noqa: E402


def test_states_are_forward_only():
    assert ob.can_transition("created", "business_email_set") is True
    assert ob.can_transition("created", "active") is True  # forward skip allowed
    assert ob.can_transition("active", "created") is False  # backward never
    assert ob.can_transition("company_joined", "credentials_stored") is False  # backward
    assert ob.can_transition("created", "created") is False  # same state
    assert ob.can_transition("created", "bogus") is False
    assert ob.can_transition("bogus", "active") is False


def test_states_order_and_owner_gates():
    assert ob.STATES[0] == "created"
    assert ob.STATES[-1] == "active"
    # every state is unique and the index is monotonic
    assert len(set(ob.STATES)) == len(ob.STATES)
    assert ob.OWNER_GATED == {"profile_logged_in", "company_joined"}
    for s in ob.OWNER_GATED:
        assert s in ob.STATES


def test_validate_business_email():
    assert ob.validate_business_email("terry@kytranempowerment.com") is True
    assert ob.validate_business_email("ops@some-company.io") is True
    assert ob.validate_business_email("someone@gmail.com") is False  # free provider
    assert ob.validate_business_email("user@yahoo.com") is False
    assert ob.validate_business_email("not-an-email") is False
    assert ob.validate_business_email("") is False


def test_valid_phone():
    assert ob._valid_phone("+14155552671") is True
    assert ob._valid_phone("(415) 555-2671") is True
    assert ob._valid_phone("4155552671") is True
    assert ob._valid_phone("123") is False  # too short
    assert ob._valid_phone("not-a-phone") is False
    assert ob._valid_phone("") is False
    assert ob._valid_phone("+1234567890123456") is False  # 16 digits, too long
