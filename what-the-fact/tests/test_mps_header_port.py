"""MPs header + container (PORT-STATUS row 10a). Real count only; ridings/parties untouched."""
import re
from pathlib import Path

C = Path(__file__).resolve().parents[1] / "consumer"
RAW = (C / "templates" / "mps.html").read_text(encoding="utf-8")
MP = re.sub(r"\{#.*?#\}", "", RAW, flags=re.S)
CSS = (C / "static" / "style.css").read_text(encoding="utf-8")


def test_header_has_design_wording_and_structure():
    assert 'class="wtf-mps-eyebrow">Both chambers<' in MP
    assert '<h1 class="wtf-mps-h1">MPs &amp; Senate</h1>' in MP
    assert "volume, not favour" in MP


def test_count_is_the_live_figure_not_the_design_sample():
    lede = re.search(r'wtf-mps-lede">(.*?)</p>', MP, re.S).group(1)
    assert "{{ mps|length }}" in lede and not re.search(r"\b343\b", lede)


def test_page_is_wrapped_once_and_old_header_is_gone():
    assert MP.count('<div class="wtf-mps-wrap">') == 1 and "{# /.wtf-mps-wrap #}" in RAW
    assert 'class="wtf-mps-header"' not in MP and 'class="wtf-mps-title"' not in MP


def test_tabs_and_filters_still_present():
    for token in ("wtfTab('hoc'", "wtfTab('senate'", "wtfTab('ridings'", "wtf-mps-filters"):
        assert token in MP, token


def test_css_is_scoped():
    block = CSS[CSS.index("MPs header + container (design row 10a)"):]
    for sel in re.findall(r"^(\.[\w-]+[^{]*)\{", block, re.M):
        assert sel.strip().startswith(".wtf-mps-"), sel
