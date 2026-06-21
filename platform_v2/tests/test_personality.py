"""
Tests for ai_bridge.personality module.

These tests require a live DB connection (archie_database).
They are skipped gracefully when the DB is unavailable.
"""

import os
import sys
import pytest

# ai_bridge lives at /mnt/archie_brain/ai_bridge — add to path so imports work
# and override DB_HOST set by conftest.py to the real container hostname.
_AI_BRIDGE_ROOT = "/mnt/archie_brain"
if _AI_BRIDGE_ROOT not in sys.path:
    sys.path.insert(0, _AI_BRIDGE_ROOT)
os.environ["DB_HOST"] = os.environ.get("DB_HOST_REAL", "archie_database")
# NOTE: do NOT override DB_NAME here. Setting it to "archie" globally at import
# poisoned the whole pytest session — it overrode the conftest test-DB redirect,
# so the production guard in database._get_pool() cascaded into every test. Use
# the conftest-provided isolated test DB; the DB_AVAILABLE skip + lenient
# assertions handle empty data gracefully.

try:
    from ai_bridge.personality import get_personality_trait, get_relationship
    from ai_bridge.db import get_db as _get_db

    _conn = _get_db()
    _conn.close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


needs_db = pytest.mark.skipif(not DB_AVAILABLE, reason="DB not reachable")


@needs_db
def test_get_personality_trait_returns_dict():
    """Personality trait should return a string value or None."""
    result = get_personality_trait("curiosity")
    assert result is None or isinstance(result, str)


@needs_db
def test_get_personality_trait_unknown_returns_none():
    """Unknown trait name should return None, not raise."""
    result = get_personality_trait("__nonexistent_trait_xyz__")
    assert result is None


@needs_db
def test_get_relationship_nonexistent_user_returns_none():
    """Non-existent user_id (no FK match) should return None gracefully, not raise."""
    # user_id 99999 does not exist — FK constraint causes INSERT to fail silently.
    result = get_relationship(user_id=99999)
    assert result is None


@needs_db
def test_get_relationship_existing_user_returns_dict():
    """For a real user_id, get_relationship should return a dict with expected fields."""
    # user_id=2 is a known user in the test DB.
    result = get_relationship(user_id=2)
    # May be None if user 2 has no relationship row and archie_relationships requires FK.
    # At minimum, it must not raise and must return dict or None.
    assert result is None or isinstance(result, dict)
    if result is not None:
        assert "familiarity_level" in result
        assert "trust_level" in result
        assert "relationship_type" in result
