"""DomainAuditScanner — live HTTP fetch + data-i18n gap detection.

Fetches each registered domain's pages, extracts data-i18n keys from the
rendered HTML, then checks those keys against the domain's translations.json
for all active languages. Yields ScannerResult rows for every detected gap.

Gap types produced:
  missing         — key present in DOM but absent from translations.json for a language
  quality_suspect — value is "Mock*", empty string, or identical to EN (untranslated)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterator

from bs4 import BeautifulSoup

from .base import BaseScanner, ScannerResult
from .domain_registry import EXTERNAL_DOMAINS

logger = logging.getLogger("agent_loop")

_MOCK_RE = re.compile(r"^Mock", re.IGNORECASE)
_FETCH_TIMEOUT = 15
# Hostinger's CDN (server: hcdn) answers 403 to a bare `Accept: */*`, which is
# httpx's default. Every page fetch in this scanner therefore failed and the
# domain audit reported ZERO keys — silently, apart from one log line — no
# matter how complete EXTERNAL_DOMAINS was. Send a browser-shaped Accept (and
# a real UA) so the audit can actually see the site.
_FETCH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


def _fetch_text(url: str) -> str | None:
    """Synchronous httpx GET. Returns body text or None on error."""
    try:
        import httpx

        resp = httpx.get(url, timeout=_FETCH_TIMEOUT, follow_redirects=True, headers=_FETCH_HEADERS)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("[DomainAudit] fetch failed %s: %s", url, exc)
        return None


def _fetch_translations(url: str) -> dict | None:
    """Fetch and parse a translations.json. Returns dict[lang][key]=text or None."""
    text = _fetch_text(url)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[DomainAudit] invalid JSON at %s", url)
        return None


def _extract_i18n_keys(html: str) -> set[str]:
    """Return all unique i18n key values from data-i18n* attributes in an HTML string."""
    soup = BeautifulSoup(html, "html.parser")
    keys: set[str] = set()
    for attr in ("data-i18n", "data-i18n-placeholder", "data-i18n-title", "data-i18n-aria-label"):
        for tag in soup.find_all(attrs={attr: True}):
            val = tag.get(attr, "").strip()
            if val:
                keys.add(val)
    return keys


class DomainAuditScanner(BaseScanner):
    """Scan all active EXTERNAL_DOMAINS for translation gaps."""

    gap_type = "missing"

    def scan(self) -> Iterator[ScannerResult]:
        for domain in EXTERNAL_DOMAINS:
            if not domain.get("active", True):
                continue
            yield from self._scan_domain(domain)

    def _scan_domain(self, domain: dict) -> Iterator[ScannerResult]:
        name = domain["name"]
        active_langs = domain["active_languages"]

        # Collect all data-i18n keys across all pages
        dom_keys: set[str] = set()
        for page_url in domain.get("pages", []):
            html = _fetch_text(page_url)
            if html:
                dom_keys |= _extract_i18n_keys(html)
            else:
                logger.warning("[DomainAudit] skipped page %s (fetch failed)", page_url)

        if not dom_keys:
            logger.info("[DomainAudit] no data-i18n keys found for %s", name)
            return

        translations = _fetch_translations(domain["translations_url"])
        if translations is None:
            yield ScannerResult(
                source=f"domain:{name}",
                gap_type="missing",
                language="en",
                key="_translations_json_unreachable",
                snippet=domain["translations_url"],
                confidence=1.0,
            )
            return

        en_data: dict[str, str] = translations.get("en", {})

        for key in sorted(dom_keys):
            en_value = en_data.get(key)

            for lang in active_langs:
                lang_data: dict[str, str] = translations.get(lang, {})
                value = lang_data.get(key)

                if value is None:
                    yield ScannerResult(
                        source=f"domain:{name}",
                        gap_type="missing",
                        language=lang,
                        key=key,
                        confidence=1.0,
                    )
                elif value.strip() == "":
                    yield ScannerResult(
                        source=f"domain:{name}",
                        gap_type="quality_suspect",
                        language=lang,
                        key=key,
                        snippet=repr(value),
                        confidence=0.95,
                    )
                elif _MOCK_RE.match(value):
                    yield ScannerResult(
                        source=f"domain:{name}",
                        gap_type="quality_suspect",
                        language=lang,
                        key=key,
                        snippet=value[:120],
                        confidence=0.95,
                    )
                elif lang != "en" and en_value and value.strip() == en_value.strip():
                    # Non-EN value identical to EN source = untranslated copy
                    yield ScannerResult(
                        source=f"domain:{name}",
                        gap_type="quality_suspect",
                        language=lang,
                        key=key,
                        snippet=value[:120],
                        confidence=0.80,
                    )
