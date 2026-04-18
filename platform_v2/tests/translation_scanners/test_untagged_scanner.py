"""Untagged scanner — tests against a golden fixture."""

from pathlib import Path

import pytest

from tools.consciousness.translation_scanners.untagged_scanner import (
    UntaggedScanner,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "translation" / "sample_site"


def _results():
    scanner = UntaggedScanner(source="test_sample", directory=str(FIXTURE))
    return list(scanner.scan())


def test_flags_hardcoded_paragraph():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Hardcoded paragraph that should be flagged" in s for s in snippets)


def test_flags_input_placeholder():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Enter email here" in s for s in snippets)


def test_flags_title_attribute():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Submit form" in s for s in snippets)


def test_flags_aria_label():
    results = _results()
    snippets = [r.snippet for r in results]
    assert any("Open menu" in s for s in snippets)


def test_skips_tagged_elements():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any("Tagged Title" in s for s in snippets)
    assert not any(s == "Menu" for s in snippets)


def test_skips_code_and_style():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any('var x = "not translatable"' in s for s in snippets)


def test_skips_single_symbol_and_ok():
    results = _results()
    snippets = [r.snippet or "" for r in results]
    assert not any(s.strip() == "×" for s in snippets)
    assert not any(s.strip() == "OK" for s in snippets)


def test_result_has_file_and_suggested_key():
    results = _results()
    assert results, "expected at least one result"
    for r in results:
        assert r.source == "test_sample"
        assert r.gap_type == "untagged"
        assert r.language is None
        assert r.file_path is not None
        assert r.suggested_key is not None
        assert r.suggested_key.startswith("test_sample.")
