"""Page headers are centred as in the mockup, part 3 of 3: weather, ethics, municipal, officers, coming-soon (task #6604).

The shared helper `.wtf-pg-centre` and its real-browser behaviour are tested in test_centred_headers_part1.py. This file checks the class is on the
header wrapper (weather, ethics, municipal, officers) or on the title and intro (the shared coming-soon template, which serves /platforms and
every other stub page).
"""
from pathlib import Path

import jinja2
import pytest

T = Path(__file__).resolve().parents[1] / "consumer" / "templates"
STYLE = (T.parent / "static" / "style.css").read_text(encoding="utf-8")

CASES = [
    ("weather.html", '<div class="wtf-wx-header wtf-pg-centre">'),
    ("ethics.html", '<div class="wtf-eth-header wtf-pg-centre">'),
    ("municipal.html", '<div class="wtf-mu-page-header wtf-pg-centre">'),
    ("officers.html", '<div class="wtf-of-head wtf-pg-centre">'),
    ("_coming_soon.html", '<h1 class="wtf-pg-centre">{{ page_h1 }}</h1>'),
    ("_coming_soon.html", '<p class="wtf-cs-lede wtf-pg-centre">{{ page_lede }}</p>'),
]


@pytest.mark.parametrize("template,needle", CASES, ids=[f"{t}:{n[:30]}" for t, n in CASES])
def test_template_marks_its_header_for_centring(template, needle):
    assert needle in (T / template).read_text(encoding="utf-8")


def test_the_helper_these_templates_rely_on_exists():
    assert ".wtf-pg-centre { text-align:center; }" in STYLE


def test_every_template_compiles():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(T)))
    for name in sorted({t for t, _ in CASES}):
        env.get_template(name)
