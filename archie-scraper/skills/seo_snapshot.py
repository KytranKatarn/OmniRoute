"""Skill: seo_snapshot — Extract SEO metadata from a page."""
import logging

logger = logging.getLogger(__name__)

_SEO_SCRIPT = """() => {
    const get = (sel) => { const el = document.querySelector(sel); return el ? el.content || el.href || el.textContent.trim() : null; };
    const getAll = (sel) => Array.from(document.querySelectorAll(sel)).map(e => e.textContent.trim()).filter(Boolean);
    return {
        title: document.title,
        meta_description: get('meta[name="description"]'),
        og_title: get('meta[property="og:title"]'),
        og_description: get('meta[property="og:description"]'),
        og_image: get('meta[property="og:image"]'),
        canonical: get('link[rel="canonical"]'),
        robots: get('meta[name="robots"]'),
        h1: getAll('h1'),
        h2: getAll('h2').slice(0, 10),
        images_count: document.querySelectorAll('img').length,
        images_with_alt: Array.from(document.querySelectorAll('img')).filter(i => i.alt).length,
        links_internal: Array.from(document.querySelectorAll('a[href]')).filter(a => a.hostname === location.hostname).length,
        links_external: Array.from(document.querySelectorAll('a[href]')).filter(a => a.hostname && a.hostname !== location.hostname).length,
        schema_types: Array.from(document.querySelectorAll('[type="application/ld+json"]')).map(s => { try { return JSON.parse(s.textContent)['@type']; } catch(e) { return null; } }).filter(Boolean),
    };
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        seo = page.evaluate(_SEO_SCRIPT)
    except Exception as exc:
        seo = {"error": str(exc)}

    issues = []
    if not seo.get("title"):
        issues.append("Missing title tag")
    elif len(seo.get("title", "")) > 60:
        issues.append(f"Title too long ({len(seo['title'])} chars)")
    if not seo.get("meta_description"):
        issues.append("Missing meta description")
    if not seo.get("h1"):
        issues.append("No H1 tag")
    if not seo.get("canonical"):
        issues.append("No canonical URL")

    findings = f"SEO snapshot for {url}: {len(issues)} issue(s). " + ("; ".join(issues) if issues else "All clear.")
    return {
        "data": {**seo, "issues": issues},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
