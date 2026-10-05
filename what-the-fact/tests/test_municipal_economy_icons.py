"""/municipal and /economy used emoji where the rest of the site uses the shared stroke icons.

Emoji render as empty boxes on any machine without an emoji font and clash with the 17px stroke
set that replaced them in the nav (base.html). Both pages now call the shared `icon()` macro from
_archetypes.html. These tests pin that no pictograph creeps back and that every icon name used
actually exists in the registry (an unknown name silently falls back to the 'warn' triangle).
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL = ROOT / "consumer" / "templates"
ARCH = (TPL / "_archetypes.html").read_text(encoding="utf-8")
PAGES = ["municipal", "economy"]


def _src(name: str) -> str:
    return (TPL / f"{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", PAGES)
def test_no_pictograph_emoji_remain(name):
    left = sorted({c for c in _src(name) if ord(c) >= 0x1F000})
    assert not left, f"{name}.html still contains emoji: {left}"


@pytest.mark.parametrize("name", PAGES)
def test_page_imports_the_shared_icon_macro(name):
    assert re.search(r'\{%\s*from "_archetypes\.html" import [^%]*\bicon\b', _src(name))


@pytest.mark.parametrize("name", PAGES)
def test_every_icon_name_used_exists_in_the_registry(name):
    used = set(re.findall(r"icon\('([a-z_]+)'", _src(name)))
    assert used, f"{name}.html uses no icons — the test would pass vacuously"
    missing = [u for u in used if f"'{u}':" not in ARCH]
    assert not missing, f"{name}.html uses icon names missing from the registry: {missing}"
