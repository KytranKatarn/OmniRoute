"""Skill: accessibility_check — Basic WCAG checks via page.evaluate()."""
import logging

logger = logging.getLogger(__name__)

_CHECK_SCRIPT = """() => {
    const results = {};
    const imgs = document.querySelectorAll('img');
    results.images_total = imgs.length;
    results.images_missing_alt = Array.from(imgs).filter(i => !i.alt).length;
    const inputs = document.querySelectorAll('input:not([type=hidden]):not([type=submit])');
    results.inputs_total = inputs.length;
    results.inputs_missing_label = Array.from(inputs).filter(i => {
        return !i.labels?.length && !i.getAttribute('aria-label') && !i.getAttribute('aria-labelledby');
    }).length;
    results.headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(h => h.tagName.toLowerCase());
    results.has_h1 = results.headings.includes('h1');
    results.h1_count = results.headings.filter(h => h === 'h1').length;
    results.links_no_text = Array.from(document.querySelectorAll('a')).filter(l => !l.textContent.trim() && !l.getAttribute('aria-label')).length;
    results.html_lang = document.documentElement.lang || null;
    return results;
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        checks = page.evaluate(_CHECK_SCRIPT)
    except Exception as exc:
        checks = {"error": str(exc)}

    issues = []
    if checks.get("images_missing_alt", 0) > 0:
        issues.append(f"{checks['images_missing_alt']} image(s) missing alt text")
    if checks.get("inputs_missing_label", 0) > 0:
        issues.append(f"{checks['inputs_missing_label']} input(s) missing label")
    if not checks.get("has_h1"):
        issues.append("No H1 heading found")
    if checks.get("h1_count", 0) > 1:
        issues.append(f"Multiple H1s ({checks['h1_count']})")
    if not checks.get("html_lang"):
        issues.append("Missing lang attribute on <html>")
    if checks.get("links_no_text", 0) > 0:
        issues.append(f"{checks['links_no_text']} link(s) without accessible text")

    findings = f"{len(issues)} accessibility issue(s) on {url}: " + ("; ".join(issues) if issues else "None")
    return {
        "data": {"checks": checks, "issues": issues, "issue_count": len(issues)},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
