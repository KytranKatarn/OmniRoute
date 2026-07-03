"""Shared LinkedIn slug resolution for the company/creed Playwright skills.

Skills are loaded by `importlib.util.spec_from_file_location(path.stem, path)`
(skill_runner._discover_skills / headed_tasks), which does NOT put the skills
dir on sys.path. So a skill imports this helper with:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _linkedin_common import get_company_slug

Both loaders skip `_`-prefixed files, so this module is never registered as a
runnable skill (#2599 — one place for the slug so skills stop drifting).
"""
import os

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
