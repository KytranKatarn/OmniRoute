"""Skill: network_inspect — Capture all network requests during page load."""
import logging

logger = logging.getLogger(__name__)


def run(page, url: str, params: dict, job_id: int) -> dict:
    wait_for = params.get("wait_for_selector")
    filter_domain = params.get("filter_domain", "")
    include_types = params.get("include_types") or []

    captured: list = []

    def _on_request(req):
        if filter_domain and filter_domain not in req.url:
            return
        if include_types and req.resource_type not in include_types:
            return
        captured.append({"url": req.url, "method": req.method, "resource_type": req.resource_type})

    def _on_response(resp):
        for item in captured:
            if item["url"] == resp.url and "status" not in item:
                item["status"] = resp.status

    page.on("request", _on_request)
    page.on("response", _on_response)
    page.goto(url, wait_until="networkidle", timeout=45000)
    if wait_for:
        try:
            page.wait_for_selector(wait_for, timeout=10000)
        except Exception:
            pass

    api_calls = [r for r in captured if r.get("resource_type") in ("xhr", "fetch")]
    findings = f"Captured {len(captured)} requests ({len(api_calls)} API/XHR) from {url}"
    return {
        "data": {"requests": captured[:200], "api_calls": api_calls[:50], "requests_captured": len(captured), "api_calls_captured": len(api_calls)},
        "screenshots": [], "network_log": captured[:200], "findings": findings, "auto_approve": False,
    }
