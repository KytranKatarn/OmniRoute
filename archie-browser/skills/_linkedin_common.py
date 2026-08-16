"""Shared LinkedIn slug resolution + comment-node hooks for the Playwright skills.

Skills are loaded by `importlib.util.spec_from_file_location(path.stem, path)`
(skill_runner._discover_skills / headed_tasks), which does NOT put the skills
dir on sys.path. So a skill imports this helper with:

    import os, sys
    _SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
    if _SKILLS_DIR not in sys.path:      # guard — see #5650
        sys.path.insert(0, _SKILLS_DIR)
    from _linkedin_common import get_company_slug

Both loaders skip `_`-prefixed files, so this module is never registered as a
runnable skill (#2599 — one place for the slug so skills stop drifting).
"""
import os
import re
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Comment-node hooks (#5650). THREE skills carried byte-identical copies of a
# class-based comment selector — linkedin_comment, linkedin_comment_like and
# linkedin_comment_reply — so LinkedIn's server-driven-UI migration broke all
# three at once and each had to be found separately. They live here now: one
# edit the next time LinkedIn moves the markup.
#
# The legacy classes resolve to ZERO on any migrated surface (measured
# 2026-08-16 on post detail: `.comments-comment-item` -> 0 of 838 elements,
# while [componentkey] -> 109). See KB #288935 and PR #2603.
# ---------------------------------------------------------------------------

# SDUI hook first, legacy classes retained as a fallback for surfaces that have
# NOT migrated (messaging and notifications were still fully legacy on
# 2026-08-16 — do not delete the legacy half).
COMMENT_NODE_SEL = (
    '[componentkey^="replaceableComment_urn:li:comment:"], '
    '[id^="replaceableComment_urn:li:comment:"], '
    "article.comments-comment-entity, .comments-comment-item, "
    ".comments-comments-list__comment-item, [data-id*='comment']"
)

# Matches BOTH urn shapes LinkedIn uses:
#   long  (SDUI componentkey) urn:li:comment:(urn:li:activity:<a>,<c>)
#   short (what we store)     urn:li:comment:(activity:<a>,<c>)
_COMMENT_URN_RE = re.compile(
    r"urn:li:comment:\((?:urn:li:)?(?:activity:)?(\d+),(\d+)\)"
)


def comment_node_selector_for_id(comment_id):
    """Selector for the ONE comment node whose urn ends in ``comment_id``.

    The SDUI componentkey embeds the full urn, so a substring match on the
    numeric comment id pins the right node without depending on urn SHAPE —
    which matters because the stored short form and the rendered long form
    differ. Legacy ``data-id`` kept for unmigrated surfaces.
    """
    cid = str(comment_id or "").strip()
    if not cid:
        return ""
    return (
        f'[componentkey*="{cid}"], '
        f'[id^="replaceableComment"][id*="{cid}"], '
        f"[data-id*='{cid}']"
    )


def comment_ids_from_urn(raw):
    """(activity_id, comment_id) from either urn shape, or (None, None)."""
    m = _COMMENT_URN_RE.search(raw or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def normalize_comment_urn(raw):
    """Canonical SHORT form: ``urn:li:comment:(activity:<a>,<c>)``.

    ⚠️ Deliberately NOT the SDUI long form. Every row already in
    ``linkedin_comments`` (written by the notification path) uses the short
    form, and the downstream regexes parse it. Emitting the long form here
    would fork the urn shape and silently break dedup between the two
    ingest paths. Both forms work as a ``?commentUrn=`` deep-link (verified
    live 2026-08-16 — each rendered the same thread).
    """
    act, cid = comment_ids_from_urn(raw)
    if not act:
        return None
    return f"urn:li:comment:(activity:{act},{cid})"


def build_comment_deeplink(raw):
    """A ``?commentUrn=`` permalink for a comment urn, or None.

    NOTE: on migrated surfaces SDUI DISCARDS the commentUrn query param (the
    final url redirects to the bare permalink) and renders the thread anyway,
    so this is no longer required just to make comments appear — KB #274178's
    "only the deep-link renders the thread" is obsolete there. Still emitted
    because it is the stable, shareable address of a specific comment.
    """
    act, cid = comment_ids_from_urn(raw)
    if not act:
        return None
    urn = f"urn:li:comment:(activity:{act},{cid})"
    return (
        f"https://www.linkedin.com/feed/update/urn:li:activity:{act}/"
        f"?commentUrn={quote(urn, safe='')}"
    )


# The Kytran Empowerment Inc. company page. The numeric id (106863155) and this
# vanity slug both resolve on LinkedIn; the vanity slug is what the already-correct
# skills (linkedin_company_inbox, linkedin_post_image) use, so it is the canonical
# fallback. Override per-container via the LINKEDIN_COMPANY_SLUG env var.
DEFAULT_COMPANY_SLUG = "kytran-empowerment-inc"

# Creed-AI company page. Numeric id used historically by linkedin_creed_post.
DEFAULT_CREED_SLUG = "115977300"


def get_company_slug(params=None):
    """Resolve the LinkedIn company-page slug.

    Precedence: explicit params['company_slug'] > LINKEDIN_COMPANY_SLUG env >
    the canonical 'kytran-empowerment-inc' default.
    """
    params = params or {}
    return (
        (params.get("company_slug") or "").strip()
        or os.getenv("LINKEDIN_COMPANY_SLUG")
        or DEFAULT_COMPANY_SLUG
    )


def get_creed_slug(params=None):
    """Resolve the Creed-AI company-page slug.

    Precedence: explicit params['company_slug'] > LINKEDIN_CREED_SLUG env >
    the canonical '115977300' default.
    """
    params = params or {}
    return (
        (params.get("company_slug") or "").strip()
        or os.getenv("LINKEDIN_CREED_SLUG")
        or DEFAULT_CREED_SLUG
    )
