"""P.R.O.B.E. suite: translation_coverage — Playwright + Tesseract OCR + langdetect.

For each (external source, language) combo, open a small set of pages, switch
language via the UI, OCR the viewport, and flag any non-EN page where the
detected language of extracted text is still English.

Entry point: run(sources) -> dict
"""

from __future__ import annotations

import logging
import tempfile
from typing import Iterable

logger = logging.getLogger(__name__)

TARGET_PAGES = {
    "website_kytranempowerment": ["/", "/pricing", "/about"],
}

# Public, user-facing URLs for every translation source in the canonical
# EXTERNAL_SCAN_SOURCES list (tools/consciousness/language_routes.py). These are the
# PUBLIC domains a real visitor hits — external QA of the deployed site, so public
# hostnames are correct here (this is NOT an inter-cluster dispatch path). Kept in
# sync with .claude/rules/operational-state.md.
BASE_URLS = {
    # Marketing / brand sites
    "website_kytranempowerment": "https://www.kytranempowerment.com",
    "website_creed": "https://creed-ai.org",
    "website_kso": "https://server.kytranempowerment.com",
    # What The Fact — consumer (.com) + tech (.tech) surfaces
    "website_what_the_fact": "https://what-the-fact.com",
    "product_what_the_fact": "https://what-the-fact.tech",
    # Watch products
    "product_civic_watch": "https://civic.kytranempowerment.com",
    "product_gov_watch": "https://gov.kytranempowerment.com",
    "product_legal_watch": "https://legal.kytranempowerment.com",
    "product_market_watch": "https://market.kytranempowerment.com",
    # Standalones
    "product_business_suite": "https://business.kytranempowerment.com",
    "product_creed_governance": "https://creed.kytranempowerment.com",
}

# All sources the suite knows how to check — run(None) covers every one.
ALL_SOURCES = tuple(BASE_URLS.keys())

LANGS = ["fr", "es", "pt", "de", "zh", "ar", "he"]


def _paths_for(source: str):
    return TARGET_PAGES.get(source, ["/"])


def _base_url_for(source: str) -> str:
    return BASE_URLS.get(source, "")


def run(sources: Iterable[str] | None = None) -> dict:
    """Run Playwright + OCR translation coverage checks for each source.

    Args:
        sources: Iterable of source identifiers (e.g. "website_what_the_fact").
                 Pass None (the default) to check ALL_SOURCES — every source in the
                 canonical EXTERNAL_SCAN_SOURCES list. Unknown labels are skipped.

    Returns:
        dict with keys: checks (int), failures (int), details (list of dicts).
        Each failure detail: {source, path, lang, detected}.
    """
    import pytesseract
    from langdetect import detect, DetectorFactory
    from playwright.sync_api import sync_playwright
    from database import get_db_cursor

    if sources is None:
        sources = ALL_SOURCES

    DetectorFactory.seed = 0
    summary: dict = {"checks": 0, "failures": 0, "details": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        for source in sources:
            base = _base_url_for(source)
            if not base:
                logger.warning("[translation_coverage] unknown source %s — skipping", source)
                continue
            for path in _paths_for(source):
                for lang in LANGS:
                    summary["checks"] += 1
                    page = browser.new_page(
                        locale=lang,
                        viewport={"width": 1440, "height": 900},
                    )
                    try:
                        page.goto(
                            base + path,
                            timeout=15000,
                            wait_until="networkidle",
                        )
                        # Signal the page to switch to the requested language
                        page.evaluate(
                            "document.documentElement.lang = arguments[0];"
                            "window.dispatchEvent("
                            "  new CustomEvent('archie:set-lang', {detail: arguments[0]})"
                            ");",
                            lang,
                        )
                        page.wait_for_timeout(800)

                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            page.screenshot(path=tmp.name, full_page=False)
                            text = pytesseract.image_to_string(tmp.name) or ""

                        try:
                            detected = detect(text) if text.strip() else "unknown"
                        except Exception:  # noqa: BLE001
                            detected = "unknown"

                        if detected == "en" and lang != "en":
                            summary["failures"] += 1
                            summary["details"].append(
                                {
                                    "source": source,
                                    "path": path,
                                    "lang": lang,
                                    "detected": detected,
                                }
                            )
                            with get_db_cursor(commit=True) as (_c, cur):
                                cur.execute(
                                    """INSERT INTO translation_gaps
                                           (source, gap_type, language, file_path,
                                            snippet, confidence)
                                       VALUES (%s, 'quality_suspect', %s, %s, %s, 0.0)
                                       ON CONFLICT DO NOTHING""",
                                    (
                                        source,
                                        lang,
                                        path,
                                        f"OCR detected EN on {lang} page",
                                    ),
                                )

                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "[translation_coverage] error %s %s %s: %s",
                            source,
                            path,
                            lang,
                            e,
                        )
                    finally:
                        page.close()

        browser.close()

    return summary
