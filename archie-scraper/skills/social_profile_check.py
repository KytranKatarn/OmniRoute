"""Skill: social_profile_check — Snapshot public social media profiles."""
import logging

logger = logging.getLogger(__name__)

_SCRIPTS = {
    "twitter": """() => ({
        name: document.querySelector('[data-testid="UserName"] span')?.textContent?.trim(),
        bio: document.querySelector('[data-testid="UserDescription"]')?.textContent?.trim(),
        followers: document.querySelector('[href$="/followers"] span')?.textContent?.trim(),
        following: document.querySelector('[href$="/following"] span')?.textContent?.trim(),
    })""",
    "linkedin": """() => ({
        name: document.querySelector('h1')?.textContent?.trim(),
        headline: document.querySelector('.text-body-medium')?.textContent?.trim(),
        followers: document.querySelector('[class*="follower"]')?.textContent?.trim(),
    })""",
    "instagram": """() => ({
        name: document.querySelector('header h2')?.textContent?.trim(),
        bio: document.querySelector('header section > div:last-child span')?.textContent?.trim(),
    })""",
    "default": """() => ({title: document.title, meta_description: document.querySelector('meta[name="description"]')?.content})""",
}


def run(page, url: str, params: dict, job_id: int) -> dict:
    platform = params.get("platform") or ""
    if not platform:
        if "linkedin" in url:
            platform = "linkedin"
        elif "twitter" in url or "x.com" in url:
            platform = "twitter"
        elif "instagram" in url:
            platform = "instagram"
        else:
            platform = "default"

    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        profile = page.evaluate(_SCRIPTS.get(platform, _SCRIPTS["default"]))
    except Exception as exc:
        profile = {"error": str(exc)}

    findings = f"{platform.title()} profile: {profile.get('name') or profile.get('title', 'unknown')} from {url}"
    return {
        "data": {"profile": profile, "platform": platform, "source_url": url},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": True,
    }
