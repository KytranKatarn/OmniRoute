"""Browser Test Service — headless HTTP testing for agents.

Provides page verification, status checking, and element detection.
Used by /archie-test-browser skill and the repair pipeline verification step.

Import:
    from services.browser_test_service import test_page, test_all_modules
"""

import logging
import re
import time
import urllib.request

logger = logging.getLogger(__name__)


def test_page(url, checks=None):
    """Test a web page — navigate, check status, verify elements.

    Args:
        url: URL to test (e.g., http://192.168.1.200:3000/tools/department-hq)
        checks: Optional list of element selectors to verify exist

    Returns:
        {
            "url": str,
            "status": "pass" | "fail" | "warning" | "partial",
            "status_code": int,
            "title": str,
            "load_time_ms": int,
            "errors": [],
            "checks": [{"selector": str, "found": bool}],
            "screenshot_path": None,
        }
    """
    result = {
        "url": url,
        "status": "fail",
        "status_code": 0,
        "title": "",
        "load_time_ms": 0,
        "errors": [],
        "checks": [],
        "screenshot_path": None,
    }

    try:
        start = time.time()
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "ARCHIE-BrowserTest/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.status
            html = resp.read().decode("utf-8", errors="ignore")
            load_ms = int((time.time() - start) * 1000)

        result["status_code"] = status_code
        result["load_time_ms"] = load_ms

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        result["title"] = title_match.group(1).strip() if title_match else ""

        # Check for error indicators in HTML
        error_patterns = [
            (r"500 Internal Server Error", "500 error page"),
            (r"Traceback \(most recent call last\)", "Python traceback in HTML"),
            (r"TemplateNotFound", "Missing template error"),
            (r"502 Bad Gateway", "502 gateway error"),
            (r"404 Not Found", "404 not found"),
        ]
        for pattern, desc in error_patterns:
            if re.search(pattern, html):
                result["errors"].append(desc)

        # Check for required elements
        if checks:
            for selector in checks:
                if selector.startswith("#"):
                    found = f'id="{selector[1:]}"' in html or f"id='{selector[1:]}'" in html
                elif selector.startswith("."):
                    found = f'class="{selector[1:]}' in html or f"class='{selector[1:]}" in html or selector[1:] in html
                else:
                    found = selector in html
                result["checks"].append({"selector": selector, "found": found})

        # Status determination
        if status_code == 200 and not result["errors"]:
            if checks:
                all_found = all(c["found"] for c in result["checks"])
                result["status"] = "pass" if all_found else "partial"
            else:
                result["status"] = "pass"
        elif status_code == 200:
            result["status"] = "warning"
        else:
            result["status"] = "fail"

    except Exception as e:
        result["errors"].append(str(e))
        result["status"] = "fail"

    return result


def test_all_modules(base_url="http://192.168.1.200:3000"):
    """Test all critical platform module pages. Returns summary."""
    # Known critical routes (no auth required or admin-accessible)
    routes = [
        "/",
        "/login",
        "/tools/department-hq",
        "/tools/consciousness",
        "/tools/dev-hq",
        "/creed",
        "/tools/dev-pipeline",
        "/tools/system-operations",
        "/tools/security-network",
        "/tools/media-hub",
        "/tools/media-studio",
    ]

    results = []
    for route in routes:
        url = f"{base_url}{route}"
        result = test_page(url)
        results.append(result)
        status_icon = "pass" if result["status"] == "pass" else "FAIL"
        logger.info("Browser test [%s] %s (%dms)", status_icon, url, result["load_time_ms"])

    passed = sum(1 for r in results if r["status"] in ("pass", "warning"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
