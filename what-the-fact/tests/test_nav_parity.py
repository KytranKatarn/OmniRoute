"""Nav parity with the Claude Design shell (PORT-STATUS row 1, second scope).

Source-level checks on the two templates, because the nav renders on every page and
a structural regression here is site-wide. Each assertion states the design rule.
"""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "consumer" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
INDEX = (TEMPLATES / "index.html").read_text(encoding="utf-8")

# wtf-home.html: ALL, PARLIAMENT, ECONOMY, CLIMATE, HEALTH, CRIME, BUSINESS, SPORTS
DESIGN_BEAT_ORDER = ["all", "parliament", "economy", "climate", "healthcare", "crime", "business", "sports"]


def _region(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i : src.index(end, i)]


def test_beat_chips_follow_the_design_order():
    strip = _region(INDEX, 'id="wtf-beat-strip"', "</div>")
    assert re.findall(r'data-beat="(\w+)"', strip) == DESIGN_BEAT_ORDER


def test_beat_chips_carry_no_emoji():
    """House rule (design-handoff README): emoji are replaced by the icon set."""
    strip = _region(INDEX, 'id="wtf-beat-strip"', "</div>")
    assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", strip)


def test_search_lives_in_the_actions_cluster_not_the_link_row():
    links = _region(BASE, 'class="wtf-nav-links"', "wtf-nav-live")
    actions = _region(BASE, 'class="wtf-nav-actions"', 'id="wtfNavMobile"')
    assert "wtf-nav-search" not in links
    assert "wtf-nav-search" in actions


def test_actions_follow_design_order_lang_search_signin_subscribe():
    actions = _region(BASE, 'class="wtf-nav-actions"', 'id="wtfNavMobile"')
    pos = [actions.index(m) for m in ('id="wtfLangBtn"', "wtf-nav-search", 'href="/login"', 'href="/join"')]
    assert pos == sorted(pos), pos


def test_language_button_shows_the_current_code():
    assert 'id="wtfLangCur"' in BASE
    assert "wtfLangCur" in _region(BASE, "function updateActiveLang", "updateActiveLang(localStorage")


def test_ids_the_nav_script_depends_on_survive():
    for ident in ("wtfLangBtn", "wtfMenuBtn", "wtfNavMobile", "wtfLangOverlay"):
        assert f'id="{ident}"' in BASE
