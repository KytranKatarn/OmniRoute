"""Page headers are centred as in the mockup, part 2 of 3: races, ridings, journalists, sources, cost, economy, rates, divergence (task #6604).

The shared helper `.wtf-pg-centre` and its real-browser behaviour are tested in test_centred_headers_part1.py. This file checks that each template
puts the class on the right element: the header wrapper where one exists, otherwise the individual label / title / intro (never the page's content).
"""
import re
from pathlib import Path

import jinja2
import pytest

T = Path(__file__).resolve().parents[1] / "consumer" / "templates"
STYLE = (T.parent / "static" / "style.css").read_text(encoding="utf-8")


def _tpl(name):
    return (T / name).read_text(encoding="utf-8")


CASES = [
    ("races.html", '<h1 class="wtf-pg-centre">Candidates and races</h1>'),
    ("races.html", '<p class="wtf-rc-lede wtf-pg-centre">'),
    ("races.html", '<p class="wtf-rc-src wtf-pg-centre">'),
    ("ridings.html", '<h1 class="wtf-pg-centre">Ridings directory</h1>'),
    ("ridings.html", '<p class="wtf-rd-lede wtf-pg-centre">'),
    ("ridings.html", '<p class="wtf-rd-src wtf-pg-centre">'),
    ("journalists.html", '<div class="wtf-pg-centre" style="padding:16px 0;border-bottom:1px solid var(--wtf-border);margin-bottom:16px;">'),
    ("sources.html", '<div class="wtf-pg-centre" style="margin-bottom:26px;">'),
    ("cost.html", '<div class="cost-kicker wtf-pg-centre">'),
    ("cost.html", '<h1 class="cost-title wtf-pg-centre">'),
    ("cost.html", '<p class="cost-lede wtf-pg-centre">'),
    ("economy.html", '<div class="wtf-ec-page-header wtf-pg-centre">'),
    ("rates.html", '<div class="wtf-pg-centre" style="padding:20px 0 16px;border-bottom:1px solid var(--wtf-border);margin-bottom:4px;">'),
    ("divergence.html", '<div class="wtf-dv-header wtf-pg-centre">'),
]


@pytest.mark.parametrize("template,needle", CASES, ids=[f"{t}:{n[:34]}" for t, n in CASES])
def test_template_marks_its_header_for_centring(template, needle):
    assert needle in _tpl(template)


def test_the_helper_these_templates_rely_on_exists():
    assert ".wtf-pg-centre { text-align:center; }" in STYLE


def test_the_empty_state_intro_further_down_is_not_centred():
    """races/ridings repeat the intro class in an empty-state branch; only the header's copy is centred."""
    for name, cls in (("races.html", "wtf-rc-lede"), ("ridings.html", "wtf-rd-lede")):
        marked = len(re.findall(rf'<p class="{cls} wtf-pg-centre">', _tpl(name)))
        total = len(re.findall(rf'<p class="{cls}', _tpl(name)))
        assert marked == 1 and total >= 2, (name, marked, total)


def test_every_template_compiles():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(T)))
    for name in sorted({t for t, _ in CASES}):
        env.get_template(name)
