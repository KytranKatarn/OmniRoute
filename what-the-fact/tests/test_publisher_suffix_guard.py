"""A headline that is only the publisher's name is not a headline (#5775).

Measured 2026-08-18: La Presse arrived through a Google News proxy and 74 of its
180 articles carried the literal title "- La Presse+" — Google's leftover when it
has no headline for an item. That gave the source 43.9% title uniqueness while
every other source sat above 73%, and those rows were still bias-scored and
fact-checked, so the pipeline spent real work on a string that says nothing.

The guard is deliberately NARROW: it drops a title that is ONLY the publisher's
name (plus the separators Google leaves behind). A real headline that merely
CONTAINS the publisher's name must survive — over-eager filtering would be a
worse bug than the one being fixed.
"""
import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# persist.py imports sqlalchemy at module scope; stub it so this guard test can
# never SKIP for an unrelated missing dependency (KB #290497).
if "sqlalchemy" not in sys.modules:
    _m = types.ModuleType("sqlalchemy")
    _m.text = lambda x: x
    sys.modules["sqlalchemy"] = _m

_spec = importlib.util.spec_from_file_location("_persist", ROOT / "ingest" / "persist.py")
_persist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_persist)
is_junk = _persist.is_publisher_suffix_title


@pytest.mark.parametrize("title,source", [
    ("- La Presse+", "la-presse"),        # the exact live string, slug form
    ("- La Presse+", "La Presse"),        # ...and display-name form
    ("| Toronto Star", "toronto-star"),
    ("  -  CTV News  ", "ctv-news"),
])
def test_publisher_only_titles_are_rejected(title, source):
    assert is_junk(title, source) is True


@pytest.mark.parametrize("title,source", [
    # A real headline that CONTAINS the publisher name must survive.
    ("La Presse enquête sur le REM de l'Est", "la-presse"),
    ("Le NPD appelle à enquêter sur le gouvernement pour écoblanchiment", "la-presse"),
    ("Toronto Star wins a National Newspaper Award", "toronto-star"),
    # Absence is not junk — it is handled elsewhere.
    ("", "la-presse"),
    (None, "la-presse"),
    ("- La Presse+", None),
    ("- La Presse+", ""),
])
def test_real_headlines_and_missing_input_survive(title, source):
    assert is_junk(title, source) is False


def test_slug_and_display_name_both_match():
    """The caller passes a SLUG ('la-presse') while the junk title carries the
    DISPLAY NAME ('La Presse'). Without hyphen normalisation the guard silently
    never fires — which looks exactly like a clean feed."""
    assert is_junk("- La Presse+", "la-presse") is True
    assert is_junk("- La Presse+", "La Presse") is True


def test_guard_is_length_bounded():
    """A long title is never junk, even if it happens to start with the name —
    cheap protection against the guard eating a real headline."""
    long_title = "La Presse " + ("a" * 80)
    assert is_junk(long_title, "la-presse") is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
