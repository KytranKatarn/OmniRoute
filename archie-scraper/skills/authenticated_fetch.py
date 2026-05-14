"""Skill: authenticated_fetch — Login then fetch content behind paywall."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    login_url = params.get("login_url") or url
    username = params.get("username", "")
    password = params.get("password", "")
    username_sel = params.get("username_selector", "input[type=email],input[name=username],input[name=email]")
    password_sel = params.get("password_selector", "input[type=password]")
    submit_sel = params.get("submit_selector", "button[type=submit]")
    content_sel = params.get("content_selector")
    wait_after = params.get("wait_after_login")

    page.goto(login_url, wait_until="networkidle", timeout=30000)
    try:
        page.fill(username_sel, username)
        page.fill(password_sel, password)
        btn = page.query_selector(submit_sel)
        if btn:
            btn.click()
        else:
            page.press(password_sel, "Enter")
    except Exception as exc:
        findings = f"Login interaction failed"
        return {"data": {}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": False}

    if wait_after:
        try:
            page.wait_for_selector(wait_after, timeout=15000)
        except Exception:
            pass
    else:
        page.wait_for_load_state("networkidle", timeout=15000)

    if url and url != login_url:
        page.goto(url, wait_until="networkidle", timeout=30000)

    content = ""
    items = []
    if content_sel:
        els = page.query_selector_all(content_sel)
        items = [el.inner_text().strip() for el in els if el.inner_text().strip()]
        content = "\n".join(items[:50])
    else:
        try:
            content = page.inner_text("body")[:2000]
        except Exception:
            content = ""

    findings = f"Fetched {len(items) or 1} item(s) from {url} (authenticated)"
    return {"data": {"content": content, "items": items, "url": page.url}, "screenshots": [], "network_log": [], "findings": findings, "auto_approve": True}
