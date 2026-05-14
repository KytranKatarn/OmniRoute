"""Skill: form_audit — Analyze all forms on a page."""
import logging

logger = logging.getLogger(__name__)

_FORM_SCRIPT = """() => {
    return Array.from(document.querySelectorAll('form')).map(form => {
        const fields = Array.from(form.querySelectorAll('input,select,textarea')).map(f => ({
            name: f.name || f.id || null,
            type: f.type || f.tagName.toLowerCase(),
            required: f.required,
            label: (() => {
                if (f.id) { const lbl = document.querySelector('label[for="' + f.id + '"]'); if (lbl) return lbl.textContent.trim(); }
                return f.getAttribute('aria-label') || f.placeholder || null;
            })(),
        }));
        return {
            action: form.action || null,
            method: (form.method || 'GET').toUpperCase(),
            field_count: fields.length,
            has_csrf: !!(form.querySelector('[name*="csrf"],[name*="token"],[name*="_token"]')),
            fields: fields,
        };
    });
}"""


def run(page, url: str, params: dict, job_id: int) -> dict:
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        forms = page.evaluate(_FORM_SCRIPT)
    except Exception:
        forms = []

    issues = []
    for i, form in enumerate(forms):
        if form.get("method") == "POST" and not form.get("has_csrf"):
            issues.append(f"Form {i + 1} missing CSRF token")
        for field in form.get("fields", []):
            if field.get("required") and not field.get("label"):
                issues.append(f"Required field '{field.get('name')}' in form {i + 1} has no label")

    findings = f"Found {len(forms)} form(s) on {url}. {len(issues)} issue(s): " + ("; ".join(issues) if issues else "None")
    return {
        "data": {"forms": forms, "form_count": len(forms), "issues": issues},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
