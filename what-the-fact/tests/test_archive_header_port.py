"""Archive header + container (PORT-STATUS row 6a). CSS/markup only — the page keeps its
tested no-<script> invariant."""
import re
from pathlib import Path

C = Path(__file__).resolve().parents[1] / "consumer"
AR_RAW = (C / "templates" / "archive.html").read_text(encoding="utf-8")
# Comments explain WHY (and mention <script>/sample numbers); assert against the markup only.
AR = re.sub(r"\{#.*?#\}", "", AR_RAW, flags=re.S)
CSS = (C / "static" / "style.css").read_text(encoding="utf-8")


def test_header_has_design_wording_and_structure():
    assert 'class="wtf-ar-eyebrow">Complete record<' in AR
    assert '<h1 class="wtf-ar-title">The full archive</h1>' in AR
    assert "the archive is what you cite" in AR


def test_whole_page_sits_in_a_balanced_container():
    assert AR.count('<div class="wtf-ar-wrap">') == 1 and "{# /.wtf-ar-wrap #}" in AR_RAW


def test_no_script_invariant_preserved():
    assert "<script" not in AR.lower()


def test_no_hardcoded_design_sample_numbers():
    assert not re.search(r"\b241\b|\b23 / 24\b|All 33 outlets", AR)


def test_css_is_scoped_to_archive_classes():
    block = CSS[CSS.index("Archive header + container (design row 6a)"):]
    for sel in re.findall(r"^(\.[\w-]+[^{]*)\{", block, re.M):
        assert sel.strip().startswith(".wtf-ar-"), sel
