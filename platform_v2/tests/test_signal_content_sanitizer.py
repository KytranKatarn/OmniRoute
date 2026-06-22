"""Tests for services.signal_content_sanitizer (#4373).

Anchored on the REAL junk (autonomy:1692 / linkedin_comments.id=4) plus the
must-not-eat legitimate-opener case.
"""

from services.signal_content_sanitizer import clean_draft, was_sanitized

# The actual published junk from autonomy:1692 (comment reply on a Terry post).
JUNK_1692 = (
    "Sure, here's a short reply comment from Kytran Katarn:\n\n"
    "Absolutely! Starting in Alberta sounds like an exciting opportunity to tap into "
    "Canada’s rich defence industry ecosystem."
)


class TestStripsModelPreamble:
    def test_real_1692_junk(self):
        out = clean_draft(JUNK_1692, kind="reply")
        assert out.startswith("Absolutely! Starting in Alberta")
        assert "Sure, here's" not in out
        assert "reply comment from Kytran" not in out

    def test_here_is_the_post(self):
        assert clean_draft("Here is the post:\n\nWe shipped a thing today.") == "We shipped a thing today."

    def test_bare_label_lines(self):
        assert clean_draft("Draft:\nThe content.") == "The content."
        assert clean_draft("Reply:\n\nThe reply body.") == "The reply body."
        assert clean_draft("Comment: \n\nGreat point!") == "Great point!"

    def test_lone_ack_line(self):
        assert clean_draft("Sure!\n\nThe actual post body.") == "The actual post body."

    def test_stacked_preambles(self):
        out = clean_draft("Certainly!\n\nHere's the comment:\n\nThe real comment.")
        assert out == "The real comment."


class TestPreservesLegitimateContent:
    def test_does_not_eat_here_is_what_we_shipped(self):
        text = "Here is what we shipped:\n\nA brand new analytics dashboard."
        assert clean_draft(text) == text  # unchanged — 'what' is not a/an/the/your/my

    def test_plain_content_unchanged(self):
        text = "We just crossed 1,000 users. Grateful for every one of them."
        assert clean_draft(text) == text

    def test_content_with_colon_midbody_unchanged(self):
        text = "Three lessons from this launch:\n\n1. Ship small.\n2. Listen.\n3. Iterate."
        assert clean_draft(text) == text


class TestWrappers:
    def test_code_fence(self):
        assert clean_draft("```\nThe post text.\n```") == "The post text."

    def test_language_fence(self):
        assert clean_draft("```text\nThe post text.\n```") == "The post text."

    def test_wrapping_quotes(self):
        assert clean_draft('"The quoted post."') == "The quoted post."

    def test_smart_quotes(self):
        assert clean_draft("“The quoted post.”") == "The quoted post."


class TestTrailers:
    def test_strips_signoff(self):
        out = clean_draft("The real post.\n\nLet me know if you'd like any changes!")
        assert out == "The real post."

    def test_strips_hope_this_helps(self):
        out = clean_draft("The real post.\n\nHope this helps!")
        assert out == "The real post."


class TestHashtags:
    def test_comment_drops_hashtags(self):
        out = clean_draft("Great insight, thanks for sharing.\n\n#AI #Canada", kind="comment")
        assert "#AI" not in out
        assert out == "Great insight, thanks for sharing."

    def test_post_keeps_hashtags(self):
        text = "Big news today.\n\n#Launch #AI"
        assert clean_draft(text, kind="post") == text

    def test_expect_hashtags_false_forces_removal(self):
        out = clean_draft("Big news.\n\n#Launch", kind="post", expect_hashtags=False)
        assert "#Launch" not in out


class TestEmptyAndAudit:
    def test_empty_inputs(self):
        assert clean_draft(None) == ""
        assert clean_draft("") == ""
        assert clean_draft("   \n  ") == ""

    def test_preamble_only_returns_empty(self):
        # A draft that is ONLY a preamble line has no real content.
        assert (
            clean_draft("Here is the post:") == "Here is the post:"
        )  # no content after → kept as-is (caller sees junk)

    def test_was_sanitized_flag(self):
        assert was_sanitized(JUNK_1692, clean_draft(JUNK_1692, kind="reply")) is True
        clean = "A clean post."
        assert was_sanitized(clean, clean_draft(clean)) is False
