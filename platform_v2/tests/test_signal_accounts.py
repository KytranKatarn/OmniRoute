"""Tests for services.signal_accounts (scale Slice 4a) — registry resolver + the
hardcoded fallback that guarantees zero behavior change while call sites migrate.
"""

from unittest.mock import MagicMock, patch

import pytest

from services import signal_accounts as sa


@pytest.fixture(autouse=True)
def _fresh_cache():
    sa.invalidate()
    yield
    sa.invalidate()


def _cursor_cm(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows

    class _CM:
        def __enter__(self):
            return (MagicMock(), cur)

        def __exit__(self, *a):
            return False

    return _CM()


class TestFallbackEqualsLegacyLiterals:
    """When the registry is unreachable, the resolver MUST return exactly the old
    literal values (so no call site can regress when it moves onto the resolver)."""

    def setup_method(self):
        sa.invalidate()

    def _force_fallback(self):
        # get_db_cursor raising → fallback path
        return patch.object(sa, "get_db_cursor", side_effect=RuntimeError("no db"), create=True)

    def test_agent_ids_match_legacy(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.agent_id_for("personal") == 342
            assert sa.agent_id_for("terry") == 377
            assert sa.agent_id_for("company") == 342
            assert sa.agent_id_for("creed") == 342

    def test_browser_ids_match_legacy(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.browser_id_for("personal") == 342
            assert sa.browser_id_for("terry") == 377
            assert sa.browser_id_for("creed") == 342

    def test_labels_and_slugs_match_legacy(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.label_for("company") == "🏢 Kytran Empowerment Inc."
            assert sa.company_slug_for("company") == "106863155"
            assert sa.company_slug_for("creed") == "115977300"
            assert sa.company_slug_for("personal") is None

    # ------------------------------------------------------------------ #5653
    # Identity must never silently default to 342 (Kytran) on a publish path.

    def test_kytran_resolves_by_alias_not_by_the_342_default(self):
        """'kytran' is what linkedin_comments.account stores for the owner.

        It used to hit browser_id_for()'s hardcoded `or 342` — right answer, wrong
        reason. resolve_key must map it to the 'personal' account explicitly, so the
        correctness does not depend on what the default happens to be.
        """
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.resolve_key("kytran") == "personal"
            assert sa.resolve_key("KYTRAN") == "personal"  # case-insensitive
            assert sa.resolve_key("owner") == "personal"
            assert sa.resolve_key("terry") == "terry"
            assert sa.resolve_key("company_page") == "company"

    def test_resolve_key_returns_none_for_unknown(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            for bad in ("bogus", "", None, "   "):
                assert sa.resolve_key(bad) is None, bad

    def test_require_browser_id_refuses_unknown_instead_of_defaulting_to_342(self):
        """THE REGRESSION THIS EXISTS FOR: a typo / NULL / not-yet-registered account
        must NOT publish under Kytran's personal profile."""
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.require_browser_id("terry") == 377
            assert sa.require_browser_id("kytran") == 342  # correct, and now BY DESIGN
            for bad in ("bogus", "", None):
                with pytest.raises(sa.UnknownAccountError):
                    sa.require_browser_id(bad)

    def test_browser_id_for_stays_lenient_for_read_callers(self):
        """browser_id_for keeps its 342 default on purpose — ~15 read/reporting callers
        rely on it. Only the publish boundary uses the strict variant."""
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.browser_id_for("bogus") == 342
            assert sa.browser_id_for("terry") == 377

    def test_post_type_aliases_match_legacy(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.post_type_to_account("company_page") == "company"
            assert sa.post_type_to_account("creed_ai") == "creed"
            assert sa.post_type_to_account("terry") == "terry"

    def test_fallback_has_the_four_working_accounts(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert set(sa.account_keys(can_post=True)) == {"personal", "terry", "company", "creed"}


class TestRegistryRead:
    def test_reads_registry_rows_incl_archie(self):
        rows = [
            {
                "account_key": "personal",
                "agent_id": 342,
                "browser_agent_id": 342,
                "role": "major_author",
                "post_type": "personal",
                "company_slug": None,
                "display_label": "👤 Kytran Katarn",
                "can_post": True,
                "can_engage": False,
                "egress_pref": None,
                "profile_established": True,
            },
            {
                "account_key": "archie",
                "agent_id": 2,
                "browser_agent_id": 2,
                "role": "major_author",
                "post_type": "archie",
                "company_slug": None,
                "display_label": "🤖 A.R.C.H.I.E.",
                "can_post": False,
                "can_engage": False,
                "egress_pref": "outpost-uk",
                "profile_established": False,
            },
        ]
        with patch("database.get_db_cursor", return_value=_cursor_cm(rows)):
            assert sa.agent_id_for("archie") == 2
            assert sa.get("archie")["can_post"] is False
            assert sa.egress_for("archie") == "outpost-uk"
            assert "archie" in sa.account_keys(role="major_author")
            # archie is NOT postable yet → excluded from can_post filter
            assert sa.account_keys(can_post=True) == ["personal"]

    def test_engage_filter_for_supporting_fleet(self):
        rows = [
            {
                "account_key": "scout_uk",
                "agent_id": 500,
                "browser_agent_id": 500,
                "role": "supporting_engagement",
                "post_type": "scout_uk",
                "company_slug": None,
                "display_label": "🛰️ Scout UK",
                "can_post": False,
                "can_engage": True,
                "egress_pref": "outpost-uk",
                "profile_established": True,
            },
        ]
        with patch("database.get_db_cursor", return_value=_cursor_cm(rows)):
            assert sa.account_keys(can_engage=True) == ["scout_uk"]
            assert sa.account_keys(can_post=True) == []


class TestPostTypeHelpers:
    """post_type_for / post_types_for must match the legacy _ACCOUNT_TO_POST_TYPES exactly
    (Slice 4b migrates signal_calendar_live_service + the calendar onto these)."""

    def test_post_types_for_matches_legacy(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.post_types_for("company") == ("company", "company_page")
            assert sa.post_types_for("creed") == ("creed", "creed_ai")
            assert sa.post_types_for("personal") == ("personal",)
            assert sa.post_types_for("terry") == ("terry",)

    def test_post_types_for_unknown_defaults_to_self(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.post_types_for("scout_uk") == ("scout_uk",)

    def test_post_type_for_is_canonical_first(self):
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.post_type_for("company") == "company"
            assert sa.post_types_for("company")[0] == "company"

    def test_post_type_to_account_default_none_skips_unknown(self):
        # signal_calendar_service relies on default=None to SKIP an unknown post_type
        # (legacy _POST_TYPE_TO_ACCOUNT.get() returned None → `if account:` skipped it).
        with patch("database.get_db_cursor", side_effect=RuntimeError("no db")):
            assert sa.post_type_to_account("zzz-unknown", default=None) is None
            assert sa.post_type_to_account("company_page") == "company"
            assert sa.post_type_to_account("zzz-unknown") == "personal"  # default kept
