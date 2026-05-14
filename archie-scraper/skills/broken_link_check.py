"""Skill: broken_link_check — Spider site and report 404s."""
import logging
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def _check_url(url: str, timeout: int = 10) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def run(page, url: str, params: dict, job_id: int) -> dict:
    max_links = int(params.get("max_links") or 30)
    same_domain = params.get("same_domain", True)
    timeout_sec = int(params.get("timeout_ms") or 8000) // 1000

    page.goto(url, wait_until="networkidle", timeout=30000)
    base_domain = urlparse(url).netloc
    link_els = page.query_selector_all("a[href]")

    hrefs, seen = [], set()
    for el in link_els:
        href = el.get_attribute("href") or ""
        if not href or href.startswith(("#", "mailto:", "tel:")):
            continue
        full = urljoin(url, href)
        parsed = urlparse(full)
        if same_domain and parsed.netloc != base_domain:
            continue
        if full not in seen:
            seen.add(full)
            hrefs.append(full)
        if len(hrefs) >= max_links:
            break

    broken = []
    for link_url in hrefs:
        status = _check_url(link_url, timeout=timeout_sec)
        if status in (0, 404, 410, 500, 503):
            broken.append({"url": link_url, "status": status, "found_on": url})

    findings = f"Checked {len(hrefs)} links from {url}: {len(broken)} broken"
    return {
        "data": {"links_checked": len(hrefs), "broken_links": broken, "broken_count": len(broken)},
        "screenshots": [],
        "network_log": [],
        "findings": findings,
        "auto_approve": False,
    }
