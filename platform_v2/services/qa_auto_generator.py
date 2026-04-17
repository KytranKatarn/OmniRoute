"""P.R.O.B.E. auto-generator — produce a QA spec from a public URL.

Used by QA-as-a-Service (Task #1728). Takes a customer-supplied URL,
discovers paths via sitemap.xml + home-page navigation links, and emits
a ``qa_test_suites.spec``-shaped dict full of ``page_load`` tests. The
result can be inserted as a ``suite_type='customer'`` suite and run
through the existing P.R.O.B.E. pipeline.

Discovery sources (in order of trust):

1. ``<base_url>/sitemap.xml`` — parsed for ``<loc>`` URLs on the same host
2. ``<base_url>/`` — parsed for ``<a href>`` links inside ``<nav>``,
   ``<header>``, and ``<footer>`` (plus top-level anchors if those are
   absent)

Anything that can't be fetched is skipped silently — this needs to work
on customers' sites without SSH, credentials, or cooperation.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("probe.autogen")

DEFAULT_MAX_PATHS = 15
DEFAULT_REQUEST_TIMEOUT = 10
USER_AGENT = "P.R.O.B.E./1.0 (+https://kytranempowerment.com)"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _normalize_base_url(raw: str) -> str:
    """Strip trailing slash + query + fragment; ensure scheme."""
    if not raw:
        raise ValueError("url is required")
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {raw!r}")
    # Drop path/query/fragment — we build paths ourselves
    return f"{parsed.scheme}://{parsed.netloc}"


def _same_host(url: str, base_host: str) -> bool:
    try:
        return urlparse(url).netloc.lower() == base_host.lower()
    except Exception:
        return False


def _as_path(url: str, base_host: str) -> Optional[str]:
    """Return the path portion of ``url`` if it's on ``base_host``, else None."""
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.lower() != base_host.lower():
        return None
    path = parsed.path or "/"
    # Never return fragments/anchors as distinct paths
    if not path.startswith("/"):
        path = "/" + path
    # Strip trailing slash (except root) so "/about" and "/about/" dedupe
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _fetch(url: str) -> Optional[requests.Response]:
    try:
        return requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException as e:
        logger.debug("auto-generator: fetch failed for %s: %s", url, e)
        return None


def _paths_from_sitemap(base_url: str, base_host: str) -> List[str]:
    resp = _fetch(f"{base_url}/sitemap.xml")
    if not resp or resp.status_code != 200 or not resp.text.strip():
        return []
    out = []
    try:
        # Strip XML namespaces so findall works without namespace gymnastics
        text = re.sub(r'\sxmlns(:[a-z0-9]+)?="[^"]+"', "", resp.text)
        root = ET.fromstring(text)
        for loc in root.findall(".//loc"):
            url = (loc.text or "").strip()
            path = _as_path(url, base_host)
            if path:
                out.append(path)
    except ET.ParseError as e:
        logger.debug("auto-generator: sitemap parse failed: %s", e)
    return out


def _paths_from_home(base_url: str, base_host: str) -> List[str]:
    resp = _fetch(base_url + "/")
    if not resp or resp.status_code != 200 or not resp.text.strip():
        return []
    soup = BeautifulSoup(resp.text, "html.parser")

    # Prefer links inside structural nav/header/footer. Fall back to all <a>
    # if none found.
    containers = soup.find_all(["nav", "header", "footer"])
    anchors = []
    for c in containers:
        anchors.extend(c.find_all("a", href=True))
    if not anchors:
        anchors = soup.find_all("a", href=True)

    out = []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url + "/", href)
        path = _as_path(absolute, base_host)
        if path:
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _slug(path: str) -> str:
    """Convert a URL path to a test-name-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return s or "root"


def generate_spec_from_url(
    url: str,
    name: Optional[str] = None,
    max_paths: int = DEFAULT_MAX_PATHS,
    description: Optional[str] = None,
) -> dict:
    """Return a spec dict suitable for ``qa_test_suites.spec``.

    Raises ``ValueError`` on malformed URL. Never raises on fetch failures
    — unreachable sites just produce a spec with a single root page_load.
    """
    base_url = _normalize_base_url(url)
    base_host = urlparse(base_url).netloc

    paths = {"/"}
    paths.update(_paths_from_sitemap(base_url, base_host))
    paths.update(_paths_from_home(base_url, base_host))

    # Deterministic order: root first, then alphabetical
    ordered = ["/"] + sorted(p for p in paths if p != "/")
    # Dedup preserving order
    seen = set()
    trimmed = []
    for p in ordered:
        if p in seen:
            continue
        seen.add(p)
        trimmed.append(p)
        if len(trimmed) >= max_paths:
            break

    suite_name = name or f"Auto suite — {base_host}"
    tests = [
        {
            "name": f"load-{_slug(p)}",
            "type": "page_load",
            "path": p,
            "expect": {"status": [200, 301, 302, 304]},
        }
        for p in trimmed
    ]

    return {
        "suite": {
            "name": suite_name,
            "description": description or f"Auto-generated P.R.O.B.E. spec for {base_url} ({len(tests)} paths).",
            "base_url": base_url,
        },
        "tests": tests,
    }


def generate_and_save(
    url: str,
    name: Optional[str] = None,
    user_id: Optional[int] = None,
    max_paths: int = DEFAULT_MAX_PATHS,
) -> dict:
    """Generate a spec and insert it into qa_test_suites.

    Returns ``{suite_id, paths, tests_generated}``.
    """
    from database import get_db_cursor
    from psycopg2.extras import Json

    spec = generate_spec_from_url(url, name=name, max_paths=max_paths)
    base_url = spec["suite"]["base_url"]

    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(
            """INSERT INTO qa_test_suites
               (name, description, target_url, spec, suite_type, user_id)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                spec["suite"]["name"],
                spec["suite"]["description"],
                base_url,
                Json(spec),
                "customer",
                user_id,
            ),
        )
        suite_id = cur.fetchone()["id"]

    return {
        "suite_id": suite_id,
        "tests_generated": len(spec["tests"]),
        "paths": [t["path"] for t in spec["tests"]],
        "base_url": base_url,
        "name": spec["suite"]["name"],
    }
