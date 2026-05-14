"""Skill: competitor_snapshot — Full competitive intelligence snapshot."""
import logging
from urllib.parse import urljoin
from screenshot_store import save_screenshot, screenshot_entry

logger = logging.getLogger(__name__)

_TECH_SCRIPT = """() => {
    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
    const tech = [];
    if (scripts.some(s => s.includes('react'))) tech.push('React');
    if (scripts.some(s => s.includes('vue'))) tech.push('Vue');
    if (scripts.some(s => s.includes('angular'))) tech.push('Angular');
    if (scripts.some(s => s.includes('jquery'))) tech.push('jQuery');
    if (scripts.some(s => s.includes('next'))) tech.push('Next.js');
    if (document.querySelector('[data-wf-page]')) tech.push('Webflow');
    if (document.querySelector('.wp-content,.wp-block')) tech.push('WordPress');
    return {tech, jobs_links: document.querySelectorAll('a[href*="career"],a[href*="job"],a[href*="hiring"]').length, meta_generator: document.querySelector('meta[name=generator]')?.content || null};
}"""

_PAGE_PATHS = {"homepage": "", "pricing": "/pricing", "features": "/features", "careers": "/careers", "about": "/about"}


def run(page, url: str, params: dict, job_id: int) -> dict:
    pages = params.get("pages") or ["homepage", "pricing", "features"]
    screenshots = []
    snapshot: dict = {"pages": {}}

    for page_name in pages:
        path = _PAGE_PATHS.get(page_name, f"/{page_name}")
        page_url = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
        try:
            page.goto(page_url, wait_until="networkidle", timeout=30000)
            sc_path = save_screenshot(job_id, page_name, page)
            screenshots.append(screenshot_entry(page_name, sc_path, f"{page_name.title()} page"))
            page_data: dict = {"title": page.title(), "url": page.url}
            if page_name == "homepage":
                try:
                    page_data.update(page.evaluate(_TECH_SCRIPT))
                except Exception:
                    pass
            snapshot["pages"][page_name] = page_data
        except Exception as exc:
            snapshot["pages"][page_name] = {"error": str(exc)}

    tech = snapshot.get("pages", {}).get("homepage", {}).get("tech", [])
    findings = f"Captured {len(screenshots)}/{len(pages)} pages from {url}. Tech: {', '.join(tech) or 'unknown'}"
    return {
        "data": snapshot,
        "screenshots": screenshots,
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
