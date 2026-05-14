"""Skill: crm_enrich — LinkedIn company/person profile scraping."""
import logging

logger = logging.getLogger(__name__)

_PROFILE_SCRIPT = """() => {
    const get = sel => { const el = document.querySelector(sel); return el ? el.textContent.trim() : null; };
    return {
        name: get('.text-heading-xlarge,h1'),
        headline: get('.text-body-medium.break-words'),
        location: get('[class*="location"]'),
        followers: get('[class*="follower"]'),
        about: get('#about ~ div .pv-shared-text-with-see-more'),
        company: get('.experience-group-position__company-name'),
    };
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        profile = page.evaluate(_PROFILE_SCRIPT)
    except Exception as exc:
        profile = {"error": str(exc)}

    findings = f"LinkedIn profile: {profile.get('name', 'unknown')} @ {profile.get('company', '?')} from {url}"
    return {
        "data": {"profile": profile, "source_url": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
