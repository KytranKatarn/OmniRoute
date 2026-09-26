"""The translation domain registry must cover every live page of a site.

A page missing from ``EXTERNAL_DOMAINS[...]["pages"]`` is invisible to the domain
audit, so its translation gaps never surface in the Consciousness Languages tab.
That is not hypothetical: kytranempowerment.com had 37 of 46 live pages
unregistered — including ``books.html`` and ``links.html``, the two pages that
were actually mid-translation — while creed-ai.org had 22 of 26 missing. The
tab could report healthy while hundreds of keys were absent from the deployed
``translations.json``.

These tests compare the registry against the pages that actually exist on disk,
so a newly added page cannot quietly fall out of coverage.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

REPO = Path(__file__).resolve().parents[2]
# creed-ai.org is a symlink to /mnt/standalone, which is mounted into the
# platform container but not into every environment that runs the suite.
SITE_DIRS = {
    "kytranempowerment_com": REPO / "website" / "kytranempowerment.com",
    "creed_ai_org": Path("/mnt/standalone/websites/creed-ai.org"),
}
# Includes and fragments are not standalone pages.
NOT_PAGES = {"_nav-partial"}


def _registered_pages(domain: dict) -> set[str]:
    return {
        url.rsplit("/", 1)[-1].replace(".html", "")
        for url in domain["pages"]
        if url.rstrip("/").count("/") >= 2 or url.endswith(".html")
    }


def _live_pages(site: Path) -> set[str]:
    pages = {f[:-5] for f in os.listdir(site) if f.endswith(".html")}
    pages.discard("index")
    return pages - NOT_PAGES


@pytest.mark.parametrize("domain", [d for d in EXTERNAL_DOMAINS if d["name"] in SITE_DIRS],
                         ids=lambda d: d["name"])
def test_every_live_page_is_registered(domain):
    site = SITE_DIRS[domain["name"]]
    if not site.is_dir():
        pytest.skip(f"{site} not mounted in this environment")
    missing = sorted(_live_pages(site) - _registered_pages(domain))
    assert not missing, (
        f"{domain['name']}: {len(missing)} live page(s) absent from the domain "
        f"registry, so their translation gaps cannot be detected: {missing}"
    )


@pytest.mark.parametrize("domain", [d for d in EXTERNAL_DOMAINS if d["name"] in SITE_DIRS],
                         ids=lambda d: d["name"])
def test_registry_has_no_duplicate_pages(domain):
    pages = domain["pages"]
    dupes = sorted({p for p in pages if pages.count(p) > 1})
    assert not dupes, f"{domain['name']}: duplicate page entries {dupes}"


@pytest.mark.parametrize("domain", [d for d in EXTERNAL_DOMAINS if d["name"] in SITE_DIRS],
                         ids=lambda d: d["name"])
def test_registered_pages_are_absolute_urls(domain):
    for url in domain["pages"]:
        assert url.startswith("http"), f"{domain['name']}: non-absolute URL {url!r}"


def test_consciousness_is_a_valid_aux_power_family():
    """Guards the AUX POWER focus used to prioritise consciousness work.

    ``fleet_dispatch_focus`` only accepts a family in ``MODULE_FAMILIES``; an
    unknown value is silently dropped by ``get_dispatch_focus()``, which would
    leave the fleet on plain platform behaviour with no visible error.
    """
    from services.fleet_dispatch_profile import MODULE_FAMILIES, get_dispatch_focus

    assert "consciousness" in MODULE_FAMILIES
    assert set(MODULE_FAMILIES["consciousness"]) == {"consciousness", "auto_tagger", "knowledge"}
    # Whatever is configured must be a real family, or the boost is a no-op.
    assert get_dispatch_focus() in set(MODULE_FAMILIES) | {""}


# --- the fetch itself -----------------------------------------------------
# Hostinger's CDN answers 403 to httpx's default `Accept: */*`. Every page
# fetch in DomainAuditScanner therefore failed and the domain audit reported
# ZERO keys — silently, apart from one log line — regardless of how complete
# EXTERNAL_DOMAINS was. Verified: with the default header every one of the 10
# previously-registered pages 403'd and the audit found 0 keys; with a
# browser-shaped Accept the same 10 pages yielded 211, and the 47-page
# registry yielded 529 (including the 38 books/links keys that were invisible).


def test_domain_audit_sends_headers_the_site_cdn_accepts():
    from tools.consciousness.translation_scanners.domain_audit_scanner import _FETCH_HEADERS

    accept = _FETCH_HEADERS.get("Accept", "")
    assert accept, "no Accept header set"
    assert accept != "*/*", "Hostinger CDN returns 403 for a bare Accept: */*"
    assert "text/html" in accept
    assert _FETCH_HEADERS.get("User-Agent"), "a real User-Agent is required alongside it"


def test_fetch_text_sends_the_headers(monkeypatch):
    """The header must actually reach httpx, not just exist as a constant."""
    import httpx

    from tools.consciousness.translation_scanners import domain_audit_scanner as das

    seen = {}

    class FakeResp:
        text = "<html></html>"

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)
    assert das._fetch_text("https://example.invalid/x") == "<html></html>"
    assert seen.get("headers") == das._FETCH_HEADERS
