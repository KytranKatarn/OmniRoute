"""S.I.G.N.A.L. content sanitizer (#4373).

Local 7B models frequently wrap the actual post/comment in conversational meta —
e.g. a comment reply that began literally with "Sure, here's a short reply comment
from Kytran Katarn:\\n\\n<real text>". That preamble (and trailing "let me know if
you'd like changes!" sign-offs, wrapping code fences/quotes, and stray hashtags on
comments) must NEVER be published.

`clean_draft()` is a PURE function applied at every draft site AND, defensively, at
the publish boundary. It is deliberately CONSERVATIVE: it only strips text it can
positively identify as model meta, so it never eats legitimate content like
"Here is what we shipped:" (an opener that is itself the message).
"""

from __future__ import annotations

import re

# A leading line is a model PREAMBLE iff it ends with ':' and is one of:
#   • an "ack + here is a/the/your/my <≤40 chars>:"  (e.g. "Sure, here's a short reply comment from X:")
#   • a bare label line: "Draft:", "Reply:", "Comment:", "Response:", "Post:", "Caption:", "Message:"
# "Here is what we shipped:" does NOT match — "what" is not in (a|an|the|your|my), so real
# content openers are preserved.
_PREAMBLE_RE = re.compile(
    r"""^\s*
        (?:(?:sure|certainly|of\s+course|absolutely|got\s+it|okay|ok|alright|here\s+goes)[!,.\s]*)?
        (?:
            here(?:\s+is|'s|’s)\s+(?:a|an|the|your|my)\s+[^:\n]{0,40}?
          | (?:draft|reply|comment|response|post|caption|message)(?:\s+(?:reply|comment|post))?
        )
        \s*:\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A lone acknowledgement line ("Sure!", "Certainly.", "Of course —") with no other content.
_ACK_ONLY_RE = re.compile(
    r"^\s*(?:sure|certainly|of\s+course|absolutely|got\s+it|okay|ok|alright|no\s+problem)[!,.—\-\s]*$",
    re.IGNORECASE,
)

# Trailing model sign-offs that are meta, not message.
_TRAILER_RE = re.compile(
    r"^\s*(?:"
    r"let\s+me\s+know\s+if.*|hope\s+(?:this|that)\s+helps.*|feel\s+free\s+to.*|"
    r"(?:i\s+)?hope\s+you\s+(?:like|find).*|would\s+you\s+like.*|"
    r"is\s+there\s+anything\s+else.*|let\s+me\s+know\s+your\s+thoughts.*"
    r")\s*$",
    re.IGNORECASE,
)

_HASHTAG_LINE_RE = re.compile(r"^\s*(?:#\w[\w-]*\s*)+$")
_TRAILING_HASHTAGS_RE = re.compile(r"(?:\s+#\w[\w-]*)+\s*$")
_SMART = {"“": '"', "”": '"', "‘": "'", "’": "'"}


def _strip_wrapping_quotes(text: str) -> str:
    t = text.strip()
    for q in ('"', "'"):
        if len(t) >= 2 and t[0] == q and t[-1] == q and t.count(q) == 2:
            return t[1:-1].strip()
    # smart-quote wrap
    if len(t) >= 2 and t[0] in "“‘" and t[-1] in "”’":
        return t[1:-1].strip()
    return t


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        # drop opening fence (+ optional lang) and a matching closing fence
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t


def clean_draft(text: str | None, kind: str = "post", expect_hashtags: bool | None = None) -> str:
    """Return publish-ready text with model meta stripped.

    kind: "post" | "company" | "creed" | "terry" | "comment" | "reply" | "message".
          comment/reply/message → hashtags removed (they read as spam on a comment).
    expect_hashtags: override — False forces hashtag removal, True keeps them.
    Returns "" if nothing meaningful remains (caller should treat as a failed draft).
    """
    if not text or not str(text).strip():
        return ""
    t = str(text).strip()

    t = _strip_code_fence(t)
    t = _strip_wrapping_quotes(t)

    # Drop a leading preamble / lone-ack line (only the FIRST block).
    for _ in range(2):  # at most two stacked preambles ("Sure!\n\nHere's the post:\n\n...")
        if not t:
            break
        first, _sep, rest = t.partition("\n")
        # preamble line ending in ':' followed by content
        if _PREAMBLE_RE.match(first) and rest.strip():
            t = rest.strip()
            continue
        # lone ack line as the very first line
        if _ACK_ONLY_RE.match(first) and rest.strip():
            t = rest.strip()
            continue
        break

    # Strip a trailing model sign-off paragraph.
    parts = [p for p in t.split("\n")]
    while parts and (_TRAILER_RE.match(parts[-1]) or not parts[-1].strip()):
        if parts[-1].strip() and _TRAILER_RE.match(parts[-1]):
            parts.pop()
        elif not parts[-1].strip():
            parts.pop()
        else:
            break
    t = "\n".join(parts).strip()

    # Hashtags: comments/replies/messages should not carry them.
    drop_tags = expect_hashtags is False or (expect_hashtags is None and kind in ("comment", "reply", "message"))
    if drop_tags:
        kept = [ln for ln in t.split("\n") if not _HASHTAG_LINE_RE.match(ln)]
        t = "\n".join(kept)
        t = _TRAILING_HASHTAGS_RE.sub("", t).strip()

    # Collapse 3+ blank lines to a single blank line.
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def was_sanitized(original: str | None, cleaned: str) -> bool:
    """True if clean_draft materially changed the text (for an audit flag)."""
    return (original or "").strip() != (cleaned or "").strip()
