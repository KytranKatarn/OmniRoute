"""Unit tests for the S7-P1-4a engagement ledger pure logic (urn dedup key, Jaccard
similarity). The DB-backed dedup/budget paths are validated live. No DB here.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_signal_engagement_ledger.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import signal_engagement_service as es  # noqa: E402


def test_post_urn_from_activity_id_is_stable_across_url_forms():
    base = "https://www.linkedin.com/feed/update/urn:li:activity:7474809144848429056/"
    assert es._post_urn_from(base) == "urn:li:activity:7474809144848429056"
    # Query junk must not change the key for a plain post link.
    assert es._post_urn_from(base + "?utm_source=x") == es._post_urn_from(base)


def test_a_comment_deep_link_keys_on_the_COMMENT_not_the_parent_post():
    """DELIBERATE, and this test used to assert the opposite.

    It previously required a `?commentUrn=` deep-link to collapse to its PARENT post urn
    ("same post → same urn"). `_post_urn_from`'s docstring is explicit that it must not:
    a comment-like "keys on the comment, not its parent post".

    The old expectation is not merely stale, it is unsafe. This is the ENGAGEMENT LEDGER's
    dedup key — collapsing to the parent means two DIFFERENT comments on the same post
    share one key, so liking the second is deduped away as already-done. The ledger exists
    to bound automated engagement; a key that over-merges silently drops real actions.
    """
    base = "https://www.linkedin.com/feed/update/urn:li:activity:7474809144848429056/"
    deep = base + "?commentUrn=urn%3Ali%3Acomment%3A(activity%3A7474809144848429056%2C123)"

    assert es._post_urn_from(deep) == "urn:li:comment:(activity:7474809144848429056,123)"
    assert es._post_urn_from(deep) != es._post_urn_from(base), "comment must not collapse to its post"

    # The property that matters: two comments on the SAME post get DIFFERENT keys.
    other = base + "?commentUrn=urn%3Ali%3Acomment%3A(activity%3A7474809144848429056%2C456)"
    assert es._post_urn_from(deep) != es._post_urn_from(other)


def test_post_urn_from_fallback_strips_query():
    assert es._post_urn_from("https://www.linkedin.com/posts/foo-bar?utm=1") == "https://www.linkedin.com/posts/foo-bar"
    assert es._post_urn_from("") == ""


def test_tokens_drops_short_words():
    assert es._tokens("a an the platform") == {"the", "platform"}


def test_jaccard_identical_and_disjoint():
    assert es._jaccard("the quick brown fox", "the quick brown fox") == 1.0
    assert es._jaccard("apple banana cherry", "xylophone zebra widget") == 0.0
    assert es._jaccard("", "anything") == 0.0


def test_jaccard_partial_overlap_is_fractional():
    s = es._jaccard(
        "the platform ships welfare gating today",
        "the platform ships idempotent posting today",
    )
    assert 0.0 < s < 1.0


def test_jaccard_above_threshold_for_near_duplicates():
    # Differ by exactly one >2-char token out of ten → Jaccard 9/11 ≈ 0.82 > 0.8 gate.
    a = "great insight canadian civic transparency really useful important work platform"
    b = "great insight canadian civic transparency really useful important work product"
    assert es._jaccard(a, b) > es._SIMILARITY_THRESHOLD
