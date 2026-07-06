"""#2092 — the P.R.O.B.E. translation_coverage QA suite must cover ALL sources.

Config-only assertions (no Playwright / OCR / network), so they run in plain pytest
and give the P.R.O.B.E. runner a pytest entry point for this suite.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qa_suites import translation_coverage as tc

# The canonical translation sources with a PUBLIC, browsable URL — mirrors
# EXTERNAL_SCAN_SOURCES (tools/consciousness/language_routes.py). If a new external
# translation source ships, add it here AND to translation_coverage.BASE_URLS.
EXPECTED_SOURCES = {
    "website_kytranempowerment",
    "website_creed",
    "website_kso",
    "website_what_the_fact",
    "product_what_the_fact",
    "product_civic_watch",
    "product_gov_watch",
    "product_legal_watch",
    "product_market_watch",
    "product_business_suite",
    "product_creed_governance",
}


def test_covers_all_sources():
    # No source is missing (the whole point of #2092).
    missing = EXPECTED_SOURCES - set(tc.BASE_URLS)
    assert not missing, f"translation_coverage BASE_URLS missing sources: {missing}"


def test_all_sources_matches_base_urls():
    assert set(tc.ALL_SOURCES) == set(tc.BASE_URLS)


def test_every_url_is_public_https():
    for source, url in tc.BASE_URLS.items():
        assert url.startswith("https://"), f"{source}: {url!r} is not https"
        assert "." in url.split("//", 1)[1], f"{source}: {url!r} has no domain"
        # A QA suite of the PUBLIC site must not use an inter-cluster mesh IP.
        assert "100.64." not in url and "192.168." not in url, f"{source}: mesh/LAN IP {url!r}"


def test_wtf_consumer_and_tech_are_distinct():
    # what-the-fact.com (consumer) vs what-the-fact.tech (product/backend).
    assert tc.BASE_URLS["website_what_the_fact"] == "https://what-the-fact.com"
    assert tc.BASE_URLS["product_what_the_fact"] == "https://what-the-fact.tech"


def test_langs_are_the_seven_non_english():
    assert tc.LANGS == ["fr", "es", "pt", "de", "zh", "ar", "he"]
    assert "en" not in tc.LANGS


def test_helpers_resolve_for_every_source():
    for source in tc.BASE_URLS:
        assert tc._base_url_for(source) == tc.BASE_URLS[source]
        paths = tc._paths_for(source)
        assert isinstance(paths, list) and paths, f"{source}: empty target paths"
        assert all(p.startswith("/") for p in paths)
