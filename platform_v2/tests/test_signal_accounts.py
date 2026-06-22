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
