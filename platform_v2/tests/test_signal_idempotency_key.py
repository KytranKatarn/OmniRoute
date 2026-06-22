"""Unit tests for signal_accounts.idempotency_key_for (S6-P1-8a).

The key is the SINGLE source shared by the calendar release (producer) and the
approved-action publish executor (consumer); drift would silently break dedup and
allow a double-publish. Pure — no DB.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_signal_idempotency_key.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import signal_accounts as sa  # noqa: E402


def test_deterministic_and_32_hex():
    k1 = sa.idempotency_key_for("personal", "personal", "Hello world", 42)
    k2 = sa.idempotency_key_for("personal", "personal", "Hello world", 42)
    assert k1 == k2
    assert len(k1) == 32 and all(c in "0123456789abcdef" for c in k1)


def test_content_sensitive():
    assert sa.idempotency_key_for("personal", "personal", "Hello", 42) != sa.idempotency_key_for(
        "personal", "personal", "Hello!", 42
    )


def test_account_sensitive():
    assert sa.idempotency_key_for("personal", "personal", "X", 42) != sa.idempotency_key_for("terry", "terry", "X", 42)


def test_slot_disambiguates_same_day_rerelease():
    assert sa.idempotency_key_for("personal", "personal", "X", 1) != sa.idempotency_key_for(
        "personal", "personal", "X", 2
    )


def test_whitespace_normalized():
    assert sa.idempotency_key_for("personal", "personal", "  Hello  ", 42) == sa.idempotency_key_for(
        "personal", "personal", "Hello", 42
    )


def test_none_slot_stable():
    a = sa.idempotency_key_for("company", "company", "X", None)
    b = sa.idempotency_key_for("company", "company", "X", None)
    assert a == b


def test_no_field_boundary_collision():
    # The \x1f separator prevents "ab"+"c" colliding with "a"+"bc".
    assert sa.idempotency_key_for("ab", "c", "X", 1) != sa.idempotency_key_for("a", "bc", "X", 1)
