"""Pure parser for the LinkedIn `/recent-activity/comments/` card text (#5644 slice 2).

The `linkedin_own_comments` browser skill deliberately does NOT parse — it returns each
card's raw innerText. Parsing lives here because this module is volume-mounted (a fix ships
with a container restart, not an image rebuild) and because it can then be unit-tested
against real captured cards instead of a live browser.

CARD SHAPE (measured on Terry 2026-08-16, 5 real cards):

    Feed post number 1
    Terry Caetano commented on this      <- attribution
    Pierre Poilievre                     <- post author
     • Following
    <author headline>
    23h •
    <post body ...>
    …more
    281
    163 comments
    Like / Comment / Repost / Send       <- post action bar
    Terry Caetano                        <- HIS comment block starts
       • You                             <- the self marker
    <his headline>
    3h
    <HIS COMMENT TEXT — the voice sample>
    …more                                <- present only if truncated
    Like
    Reply
    9 impressions
    Load more comments

WHAT IS DELIBERATELY NOT EXTRACTED: the post author / post body. A card renders a post AND
his comment, but the comment URN embeds a DIFFERENT parent activity than the card's
`data-urn` (measured: 5/5 mismatch), and it could not be proven that the rendered post is
the comment's parent. Asserting "he said this in reply to <author>" on an unproven pairing
would fabricate provenance — the same class as the search-card `<p>`-order bug (KB #288935).
The comment text and its URN-derived deep-link are both verified; the post context is not,
so it is omitted rather than guessed.

ONE CARD CAN HOLD MORE THAN ONE COMMENT: card 4 of 5 had TWO `• You` blocks (he commented
twice on one post). That is also why the older positional URN pairing was unsafe.
"""

import re

# The self marker. LinkedIn renders "<name>\n   • You" for the viewer's own comment; the
# bullet form is what distinguishes HIS comment from every other commenter on the card.
_SELF_MARKER = "• You"

# A relative timestamp line ("3h", "2d", "1w", "23h •"). Marks the end of the comment
# header (name / headline / time) and therefore the start of the comment body.
_TIME_RE = re.compile(r"^\d+\s*(s|m|h|d|w|mo|y)\b\s*•?\s*$", re.I)

# Lines that terminate a comment body. These are affordances and counters, never content.
_END_EXACT = {
    "like",
    "reply",
    "load more comments",
    "see more comments",
    "…more",
    "...more",
    "see more",
    "comment",
    "repost",
    "send",
    "share",
    "follow",
    "following",
}
_END_RE = re.compile(
    r"^(\d[\d,]*\s+(impressions?|repl(?:y|ies)|likes?|comments?|reposts?)"
    r"|activate to view larger image.*|feed post number \d+)$",
    re.I,
)

_TRUNCATION_MARKERS = ("…more", "...more")


def _clean_lines(text):
    return [ln.strip() for ln in (text or "").split("\n")]


def _is_end(line):
    low = line.strip().lower().rstrip(",")
    if not low:
        return False
    return low in _END_EXACT or bool(_END_RE.match(low))


def parse_own_comments(raw_text, self_marker=_SELF_MARKER):
    """Extract the viewer's OWN comment bodies from one card's innerText.

    Returns a list of {text, truncated, age} — one entry per `• You` block, in DOM order.
    Empty list when the marker is absent (a card whose comment did not render), which the
    caller must treat as "nothing to ingest", never as an empty comment.
    """
    lines = _clean_lines(raw_text)
    out = []

    for idx, line in enumerate(lines):
        if self_marker not in line:
            continue

        # Walk forward past the header: headline line(s) then the relative timestamp.
        # The body starts on the first line AFTER the timestamp. If no timestamp is found
        # within a short window the card shape changed — skip rather than guess a body.
        cursor, age = None, None
        for j in range(idx + 1, min(idx + 8, len(lines))):
            if _TIME_RE.match(lines[j]):
                age = lines[j].rstrip(" •")
                cursor = j + 1
                break
        if cursor is None:
            continue

        body, truncated = [], False
        for k in range(cursor, len(lines)):
            ln = lines[k]
            if not ln:
                # A blank line inside a comment is a paragraph break; keep it only if more
                # body follows, so trailing blanks never pad the sample.
                body.append("")
                continue
            if ln.strip().lower() in _TRUNCATION_MARKERS:
                truncated = True
                break
            if _is_end(ln):
                break
            if self_marker in ln:  # the next own-comment block on the same card
                break
            body.append(ln)

        text = "\n".join(body).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text:
            out.append({"text": text, "truncated": truncated, "age": age})

    return out


def parse_parent_activity(comment_urn):
    """The post a comment belongs to, read from INSIDE the comment URN.

    `urn:li:comment:(activity:7494433315593027584,7494732556052119552)` -> the FIRST id.
    This is the authoritative parent: the card's own `data-urn` is the feed-wrapper
    activity for the "X commented on this" event and mismatched the real parent on 5/5
    measured cards. Building a permalink from the wrapper points at the wrong object.
    Returns None when the URN carries no activity (bare `urn:li:comment:123` form).
    """
    m = re.search(r"activity:(\d+)", comment_urn or "")
    return m.group(1) if m else None


def post_url_for(comment_urn):
    """Canonical post permalink for a comment URN, or None when it cannot be derived."""
    parent = parse_parent_activity(comment_urn)
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{parent}/" if parent else None
