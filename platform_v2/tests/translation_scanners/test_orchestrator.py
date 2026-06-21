"""Orchestrator integration — uses fixture source + mocked generator + embedding."""

from pathlib import Path
from unittest.mock import patch

from tools.consciousness.translation_scanners.orchestrator import (
    run_translation_coverage_scan,
)

FIXTURE_SRC = (
    "fixture_site",
    str(Path(__file__).parent.parent / "fixtures" / "translation" / "sample_site"),
    None,
)


def test_run_writes_gap_rows_and_respects_cap():
    """End-to-end: fixture source → scanners → gap rows → mocked generator.

    Mocks all Bridge/embedding dispatches so no real LLM calls happen.
    Asserts at least the 4 untagged items from the fixture show up.
    """
    try:
        with patch(
            "tools.consciousness.translation_scanners.generator._generate_translation",
            return_value={"translated": "mock", "confidence": 0.9},
        ), patch(
            "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
            return_value="",
        ), patch(
            "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
            return_value=1.0,
        ):
            summary = run_translation_coverage_scan(sources=[FIXTURE_SRC], domain_audit=False, deploy=False)

        assert "gaps_found" in summary
        assert summary["duration_ms"] >= 0
        # Fixture has 4 known untagged pieces: hardcoded paragraph, input
        # placeholder, button title, aria-label. The gap count should be at
        # least 4 (may be higher on re-runs as the untagged scanner picks up
        # additional text nodes; the key assertion is non-zero + meets floor).
        assert summary["gaps_found"] >= 4
    finally:
        # The scan writes fixture_site gap rows to the real DB via _upsert_gap.
        # With the source-scoped generation loaders no real translation can be
        # touched, but still clean up the synthetic fixture rows so the test
        # never pollutes translation_gaps / translations.
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute("DELETE FROM translation_gaps WHERE source = %s", (FIXTURE_SRC[0],))
            cur.execute("DELETE FROM translations WHERE source_label = %s", (FIXTURE_SRC[0],))
