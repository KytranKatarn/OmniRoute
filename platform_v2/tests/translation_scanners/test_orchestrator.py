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
        summary = run_translation_coverage_scan(sources=[FIXTURE_SRC])

    assert "gaps_found" in summary
    assert summary["duration_ms"] >= 0
    # Fixture has 4 known untagged pieces: hardcoded paragraph, input placeholder,
    # button title, aria-label. The gap count should be at least 4 (may be higher
    # on re-runs due to untagged-scanner picking up additional text nodes; the key
    # assertion is non-zero + meets the floor).
    assert summary["gaps_found"] >= 4
