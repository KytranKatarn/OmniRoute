"""Comment-thread navigation must target the commentUrn's OWN activity (#6035).

A LinkedIn notification url can name TWO DIFFERENT activities. The one LinkedIn
renders is `highlightedUpdateUrn`; the one holding the comment is inside
`commentUrn`. Navigating the url verbatim renders the WRONG post, and the skill
then honestly reports `target_comment_not_found` against a thread that was never
the right one.

Every url below is the REAL one from approval #13182 — the first
`linkedin_comment_reply` ever to execute (2026-08-26). It failed exactly this way.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

_COMMON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "_linkedin_common.py"
)
_spec = importlib.util.spec_from_file_location("_linkedin_common", _COMMON)
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)

# --- the real #13182 notification url ----------------------------------------
WRAPPER_ACT = "7498293581959462912"   # highlightedUpdateUrn — what LinkedIn renders
PARENT_ACT = "7498100752179986432"    # the activity the comment actually lives on
COMMENT_ID = "7498113666677075968"

REAL_URL = (
    "https://www.linkedin.com/feed/?highlightedUpdateUrn=urn%3Ali%3Aactivity%3A"
    f"{WRAPPER_ACT}&highlightedUpdateType=MENTIONED_YOU_IN_THIS&origin=INAPP"
    "&showCommentBox=true&commentUrn=urn%3Ali%3Acomment%3A%28activity%3A"
    f"{PARENT_ACT}%2C{COMMENT_ID}%29"
    "&dashCommentUrn=urn%3Ali%3Afsd_comment%3A%28" f"{COMMENT_ID}" "%2Curn%3Ali%3Aactivity%3A"
    f"{PARENT_ACT}%29"
)


class TestTheRealFailure:
    def test_navigates_the_parent_activity_not_the_wrapper(self):
        out = lc.canonical_comment_nav_url(REAL_URL, "")
        assert PARENT_ACT in out, "must target the activity holding the comment"
        assert WRAPPER_ACT not in out, "must NOT target highlightedUpdateUrn"

    def test_the_old_behaviour_would_have_targeted_the_wrong_post(self):
        """Falsifiability: prove the bug was real and this test would catch it.

        The previous code was `nav_url = comment_url or post_url` — i.e. the raw url.
        That url names the WRAPPER activity, which is what LinkedIn renders.
        """
        old_nav_url = REAL_URL
        assert WRAPPER_ACT in old_nav_url and PARENT_ACT in old_nav_url, (
            "the raw url carries BOTH activities — that ambiguity is the whole bug"
        )
        assert lc.canonical_comment_nav_url(REAL_URL) != old_nav_url

    def test_the_comment_id_still_resolves(self):
        act, cid = lc.comment_ids_from_urn(__import__("urllib.parse", fromlist=["unquote"]).unquote(REAL_URL))
        assert (act, cid) == (PARENT_ACT, COMMENT_ID)

    def test_result_is_a_usable_permalink(self):
        out = lc.canonical_comment_nav_url(REAL_URL)
        assert out.startswith(f"https://www.linkedin.com/feed/update/urn:li:activity:{PARENT_ACT}/")
        assert "commentUrn=" in out


class TestCandidateOrder:
    def test_comment_url_wins_over_post_url(self):
        other = "https://www.linkedin.com/feed/update/urn:li:activity:111/?commentUrn=urn%3Ali%3Acomment%3A%28activity%3A111%2C222%29"
        assert PARENT_ACT in lc.canonical_comment_nav_url(REAL_URL, other)

    def test_falls_through_to_post_url_when_comment_url_is_empty(self):
        assert PARENT_ACT in lc.canonical_comment_nav_url("", REAL_URL)

    def test_skips_a_candidate_with_no_comment_urn(self):
        plain = "https://www.linkedin.com/feed/update/urn:li:activity:999/"
        assert PARENT_ACT in lc.canonical_comment_nav_url(plain, REAL_URL)


class TestNegativeControls:
    """⚠️ The fix must not damage the cases that already worked."""

    def test_a_plain_post_url_passes_through_unchanged(self):
        plain = "https://www.linkedin.com/feed/update/urn:li:activity:999/"
        assert lc.canonical_comment_nav_url(plain, "") == plain

    def test_nothing_at_all_yields_empty_not_a_crash(self):
        assert lc.canonical_comment_nav_url("", "", None) == ""
        assert lc.canonical_comment_nav_url() == ""

    def test_an_already_canonical_deeplink_is_stable(self):
        once = lc.canonical_comment_nav_url(REAL_URL)
        assert lc.canonical_comment_nav_url(once) == once, "must be idempotent"

    def test_wrapper_equal_to_parent_still_works(self):
        """The non-ambiguous case — both activities the same — must be unaffected."""
        url = (
            "https://www.linkedin.com/feed/?highlightedUpdateUrn=urn%3Ali%3Aactivity%3A555"
            "&commentUrn=urn%3Ali%3Acomment%3A%28activity%3A555%2C666%29"
        )
        assert "activity:555" in lc.canonical_comment_nav_url(url)

    @pytest.mark.parametrize("raw", ["not a url", "https://example.com/", "   "])
    def test_junk_input_is_returned_or_empty_never_raises(self, raw):
        out = lc.canonical_comment_nav_url(raw)
        assert out == raw.strip()


class TestUrnShapeTolerance:
    def test_long_sdui_urn_shape_is_accepted(self):
        """SDUI renders the LONG urn; the short form is what we store (#5650)."""
        long_url = (
            "https://www.linkedin.com/feed/?commentUrn=urn%3Ali%3Acomment%3A%28urn%3Ali%3Aactivity%3A"
            f"{PARENT_ACT}%2C{COMMENT_ID}%29"
        )
        assert PARENT_ACT in lc.canonical_comment_nav_url(long_url)

    def test_unencoded_urn_also_works(self):
        raw = f"https://www.linkedin.com/feed/?commentUrn=urn:li:comment:(activity:{PARENT_ACT},{COMMENT_ID})"
        assert PARENT_ACT in lc.canonical_comment_nav_url(raw)
