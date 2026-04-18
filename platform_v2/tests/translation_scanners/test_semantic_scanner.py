"""Semantic scanner — tests with mocked Bridge + embedding service."""

from unittest.mock import patch

import pytest

from tools.consciousness.translation_scanners.semantic_scanner import (
    SemanticScanner,
    _english_residue_count,
    _should_skip_short,
)


def test_residue_count_flags_english_tokens_in_french():
    assert _english_residue_count("Cliquez sur le bouton Submit puis Cancel") >= 2
    assert _english_residue_count("Cliquez sur le bouton d'envoi puis annuler") == 0


def test_short_strings_skipped():
    assert _should_skip_short("Hi") is True
    assert _should_skip_short("Submit form here") is False


def test_scan_flags_low_cosine():
    rows = [
        {"id": 1, "language": "fr", "key": "home.title", "text": "Le titre d'accueil", "source_en_text": "Welcome Home"}
    ]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="The home title",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.5,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert len(results) == 1
        r = results[0]
        assert r.gap_type == "quality_suspect"
        assert r.language == "fr"
        assert r.confidence == pytest.approx(0.5)


def test_scan_passes_when_similarity_high_and_no_residue():
    rows = [{"id": 2, "language": "fr", "key": "home.title", "text": "Titre d'accueil", "source_en_text": "Home Title"}]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="Home Title",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.95,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert results == []


def test_scan_flags_on_residue_even_with_high_cosine():
    rows = [
        {
            "id": 3,
            "language": "fr",
            "key": "cta.submit",
            "text": "Cliquez sur Submit pour Cancel",
            "source_en_text": "Click to continue",
        }
    ]
    with patch(
        "tools.consciousness.translation_scanners.semantic_scanner.back_translate_to_en",
        return_value="Click Submit to Cancel",
    ), patch(
        "tools.consciousness.translation_scanners.semantic_scanner.cosine_similarity",
        return_value=0.90,
    ):
        scanner = SemanticScanner(source="website_kytranempowerment", rows=rows)
        results = list(scanner.scan())
        assert len(results) == 1
        assert results[0].gap_type == "quality_suspect"
