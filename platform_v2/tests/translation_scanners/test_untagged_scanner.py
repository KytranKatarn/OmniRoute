"""Untagged scanner — tests against a golden fixture."""

from pathlib import Path


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


# ── #3676 false-positive regressions (HTML comments + brand strings) ──────────
# These were ~21k phantom "untagged" gaps that no resolver could ever drain.


def _snippets_from_raw(raw: str) -> list:
    scanner = UntaggedScanner(source="test", directory="/tmp")
    return [r.snippet for r in scanner._scan_file("/tmp/page.html", raw)]


def test_html_comments_are_not_gaps():
    raw = (
        "<!DOCTYPE html><html><body>"
        "<!-- Global background layers -->"
        "<!-- Navigation -->"
        "<!-- Google Analytics (fires only after consent) -->"
        "<div></div></body></html>"
    )
    assert _snippets_from_raw(raw) == []


def test_brand_and_acronym_strings_are_not_gaps():
    raw = (
        "<html><body>"
        "<span>Kytran Empowerment</span>"
        "<span>A.R.C.H.I.E.</span>"
        "<span>C.R.E.E.D.</span>"
        "</body></html>"
    )
    assert _snippets_from_raw(raw) == []


def test_genuine_ui_text_is_still_flagged():
    raw = "<html><body><p>Website Design &amp; Hosting</p><h2>Security Testing</h2></body></html>"
    found = _snippets_from_raw(raw)
    assert "Website Design & Hosting" in found
    assert "Security Testing" in found


def test_brand_inside_longer_phrase_still_counts():
    # A page title that merely *contains* the brand is still translatable.
    raw = "<html><body><h1>System Operations — Kytran Empowerment</h1></body></html>"
    assert "System Operations — Kytran Empowerment" in _snippets_from_raw(raw)
