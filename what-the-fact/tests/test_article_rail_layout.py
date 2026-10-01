"""Article two-column rail (PORT-STATUS row 7a).

The old CSS claimed dense auto-flow packs two grid columns independently. It does not: rows are
shared, so a tall right-hand panel stretched the left content beside it into big blank gaps
(measured live on /article/<id>: boxes separated by ~250px of empty space). The panels now move
into a real <aside> that spans the main rows plus one flexible spacer row.
"""
import re
from pathlib import Path

ART = (Path(__file__).resolve().parents[1] / "consumer" / "templates" / "article.html").read_text(encoding="utf-8")
SEL = ".wtf-art-rail-item,.wtf-bias-panel,.wtf-factcheck-panel,.wtf-paywall-panel,.wtf-mp-claims-panel,.wtf-crosswatch-panel,.wtf-how-scored"


def _script():
    return re.findall(r"<script>(.*?)</script>", ART, re.S)[-1]


def test_rail_selector_matches_the_css_column_rule():
    css = ART[ART.index("@media (min-width: 981px)"):ART.index(".wtf-art-header {")]
    for cls in SEL.split(","):
        assert cls in css and cls in _script(), cls


def test_a_flexible_spacer_row_absorbs_the_extra_height():
    js = _script()
    assert "auto) 1fr" in js and "span ' + (Math.max(1, main) + 1)" in js


def test_it_only_runs_wide_and_restores_order_when_narrow():
    js = _script()
    assert "(min-width: 981px)" in js and "function join()" in js and "insertBefore(p[1], p[0])" in js


def test_no_js_fallback_keeps_the_old_single_flow_rules():
    assert "grid-auto-flow: row dense" in ART and ".wtf-art-rail { grid-column: 2; min-width: 0; }" in ART
