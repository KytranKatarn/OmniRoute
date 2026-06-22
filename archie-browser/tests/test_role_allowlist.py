"""Unit tests for the S7-P6.6 sidecar role allowlist.

A supporting_engagement account may like/share/comment but is PHYSICALLY blocked from
authoring (post / company-post / profile-edit). The restriction is a positive opt-in:
only an explicitly-supporting agent is restricted; a major/company/unknown agent or any
lookup error is unrestricted (today's 4 accounts are a strict no-op).

Run from archie-browser/:
    python3 -m pytest tests/test_role_allowlist.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")

import skill_runner as sr  # noqa: E402


class _NoMod:
    """A skill module with no MUTATING flag → _is_mutating uses the read-only allowlist."""


def test_unrestricted_can_do_anything():
    m = _NoMod()
    for skill in ("linkedin_post", "linkedin_company_post", "linkedin_like", "linkedin_feed"):
        assert sr._allowed_for_role(skill, m, "unrestricted") is True


def test_restricted_allows_read_and_engagement():
    m = _NoMod()
    for skill in ("linkedin_feed", "linkedin_notifications", "linkedin_recent_activity"):
        assert sr._allowed_for_role(skill, m, "restricted") is True
    for skill in (
        "linkedin_like",
        "linkedin_comment",
        "linkedin_first_comment",
        "linkedin_comment_reply",
        "linkedin_share",
    ):
        assert sr._allowed_for_role(skill, m, "restricted") is True


def test_restricted_blocks_authoring():
    m = _NoMod()
    for skill in (
        "linkedin_post",
        "linkedin_company_post",
        "linkedin_creed_post",
        "linkedin_message",
        "linkedin_connect",
    ):
        assert sr._allowed_for_role(skill, m, "restricted") is False


def test_role_for_fail_open_on_unreachable_db():
    # DATABASE_URL="" (or psycopg2 missing) → lookup fails → fail-open 'unrestricted'.
    sr._role_cache.clear()
    assert sr._role_for(99999) == "unrestricted"


def test_role_for_caches(monkeypatch):
    psyco = pytest.importorskip("psycopg2")
    sr._role_cache.clear()
    calls = {"n": 0}

    def _connect(*a, **k):
        calls["n"] += 1
        raise RuntimeError("nope")

    monkeypatch.setattr(psyco, "connect", _connect)
    sr._role_for(7)  # miss → 1 connect attempt
    sr._role_for(7)  # hit → cached, no extra attempt
    assert calls["n"] == 1


def test_role_for_restricted_when_only_supporting(monkeypatch):
    psyco = pytest.importorskip("psycopg2")
    sr._role_cache.clear()

    class _Cur:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (False, True)  # has_author=False, has_support=True

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass

    monkeypatch.setattr(psyco, "connect", lambda *a, **k: _Conn())
    assert sr._role_for(500) == "restricted"


def test_role_for_unrestricted_when_major_present(monkeypatch):
    psyco = pytest.importorskip("psycopg2")
    sr._role_cache.clear()

    class _Cur:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (True, True)  # major + support on the same profile → major wins

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cur()

        def close(self):
            pass

    monkeypatch.setattr(psyco, "connect", lambda *a, **k: _Conn())
    assert sr._role_for(342) == "unrestricted"
