"""News header (PORT-STATUS row 5a): eyebrow + serif title + lede, tiles held to content width.
Real counts only — the design's sample figures (241, 33) are never hard-coded."""
import re
from pathlib import Path

C = Path(__file__).resolve().parents[1] / "consumer"
NEWS = (C / "templates" / "news.html").read_text(encoding="utf-8")
CSS = (C / "static" / "style.css").read_text(encoding="utf-8")


def test_header_uses_the_design_wording_and_structure():
    assert 'class="wtf-nw-eyebrow">Every story, every lean<' in NEWS
    assert '<h1 class="wtf-nw-title">Latest news</h1>' in NEWS
    assert "Lean is scored per story, not assigned to the outlet" in NEWS


def test_lede_count_is_the_live_source_count_not_a_sample():
    lede = re.search(r'wtf-nw-lede">(.*?)</p>', NEWS, re.S).group(1)
    assert "{{ source_count }}" in lede and not re.search(r"\b33\b", lede)


def test_old_uppercase_header_is_gone():
    assert "LATEST NEWS" not in NEWS and "wtf-nw-h1" not in NEWS


def test_stat_tiles_still_read_the_four_real_figures():
    for v in ("articles_24h", "source_count", "clustered_stories_24h", "blindspot_flags_24h"):
        assert f'"value": {v}' in NEWS


def test_tiles_are_scoped_so_other_pages_are_unaffected():
    assert '<div class="wtf-nw-stats">' in NEWS
    block = CSS[CSS.index("News header (design row 5a)"):]
    for sel in re.findall(r"^(\.[\w-]+[^{]*)\{", block, re.M):
        assert sel.strip().startswith(".wtf-nw-"), sel
