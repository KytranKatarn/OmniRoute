"""Skill: site_change_monitor — Diff URL content vs stored hash."""
import hashlib
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    content_sel = params.get("content_selector") or "body"
    stored_hash = params.get("stored_hash") or ""

    page.goto(url, wait_until="networkidle", timeout=30000)
    content = ""
    try:
        els = page.query_selector_all(content_sel)
        content = "\n".join(el.inner_text().strip() for el in els if el.inner_text().strip())
    except Exception:
        content = ""

    current_hash = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()
    changed = bool(stored_hash) and (current_hash != stored_hash)
    findings = (f"CHANGED: {url} (hash {stored_hash[:8]}→{current_hash[:8]})" if changed
                else f"NO CHANGE: {url} (hash {current_hash[:8]})")
    return {
        "data": {"changed": changed, "current_hash": current_hash, "stored_hash": stored_hash, "content_preview": content[:500], "url": url},
        "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True,
    }
