"""Guard: the /archive page — route wiring, honesty and shared-shell rules (#6149).

Pure file reads + imports — no DB, no network, no app context, so this cannot
silently SKIP.

The filter-validation and URL-assembly guards live in tests/test_archive_filters.py,
which shipped with those helpers in #3061. This file covers what THIS PR adds:
the query builders, the template and the nav wiring.

🔴 THE LOAD-BEARING TEST IS
   test_the_omitted_geo_filters_are_STATED_not_silently_dropped.

province_code is 66% populated and city 10% (#6174). Offering either as a
filter would tell a reader "these are all the matches" when a third — or nine
tenths — of the archive cannot match at all. The page must keep SAYING that;
dropping the controls and looking complete is the failure ADR-020 names.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATES = ROOT / "consumer" / "templates"
ARCHIVE_HTML = TEMPLATES / "archive.html"
ROUTES_PY = ROOT / "consumer" / "routes.py"

from consumer.routes import _ARCHIVE_SORTS, _archive_filters  # noqa: E402


def _rendered() -> str:
    """archive.html with Jinja comments stripped — assert on what a reader sees.

    The template documents the traps it avoids by NAMING them, so a naive
    substring check would fail on the very comment proving the trap was avoided.
    """
    return re.sub(r"\{#.*?#\}", "", ARCHIVE_HTML.read_text(), flags=re.DOTALL)


# ───────────────── 🔴 the omitted geo filters are stated, not quietly dropped

def test_the_omitted_geo_filters_are_STATED_not_silently_dropped():
    body = _rendered()
    assert "no province or city filter" in body.lower()
    assert "province" in body.lower() and "city" in body.lower()


def test_province_and_city_are_NOT_offered_as_controls():
    """Non-vacuity for the test above: if someone adds the control, the honest
    paragraph alone becomes a lie. Fail then, loudly."""
    body = _rendered()
    for bad in ('name="province"', 'name="city"'):
        assert bad not in body, f"{bad} added without revisiting the coverage note"


# ────────────────────── the companion to the sort guard in test_archive_filters

def test_the_query_builder_reads_the_sort_MAP_not_the_request():
    """ORDER BY cannot be parameterised. test_archive_filters.py pins that the
    sort KEY is closed and the clauses are inert; this is the other half —
    that `_archive_rows` actually indexes the constant map. Both are needed:
    a closed key is worthless if the builder interpolates the raw value."""
    src = ROUTES_PY.read_text()
    assert 'order = _ARCHIVE_SORTS[f["sort"]][1]' in src
    assert 'ORDER BY {order}' in src
    assert _archive_filters({"sort": "; DROP TABLE x"})["sort"] in _ARCHIVE_SORTS


def test_the_story_and_article_queries_both_exclude_suppressed_rows():
    """Both shapes share _archive_where, but the story shape adds its own
    clause — a future edit could bypass the shared fragment."""
    src = ROUTES_PY.read_text()
    assert src.count("{base}") >= 2, "both query shapes must build on the shared base"


# ──────────────────────────────────────── the outlet label cannot go stale

def test_the_outlet_count_is_not_hardcoded():
    """The prototype's control reads 'All 33 outlets'; there are 46 sources."""
    body = _rendered()
    assert "All {{ outlets|length }} outlets" in body
    assert "33 outlets" not in body


# ──────────────────────────────────────────────────── the paywall is real

def test_the_gate_is_applied_in_the_route_not_the_template():
    """A template-side slice would ship the withheld rows to the browser and
    merely not draw them — the data would still be in the HTML."""
    assert "rows = rows[:cap]" in ROUTES_PY.read_text()
    body = _rendered()
    assert "[:cap]" not in body and "[:10]" not in body


# ───────────────────────────────────── shared-shell + wiring (as /clusters)

def test_no_template_uses_a_filter_this_app_does_not_register():
    """This app registers NO custom Jinja filters; an unknown one is a 500."""
    from jinja2.filters import FILTERS
    used = set(re.findall(r"\|\s*([a-zA-Z_][a-zA-Z0-9_]*)", ARCHIVE_HTML.read_text()))
    unknown = sorted(used - set(FILTERS))
    assert not unknown, f"archive.html uses unregistered filter(s): {unknown}"


def test_the_page_is_reachable_from_the_site_nav():
    base = (TEMPLATES / "base.html").read_text()
    assert "'/archive'" in base or '"/archive"' in base, "/archive would be orphaned"


def test_every_internal_link_is_a_real_route():
    routes = set(re.findall(r'@bp\.(?:get|route)\(\s*["\']([^"\']+)', ROUTES_PY.read_text()))
    assert len(routes) > 50, "route parse looks wrong — guard would be vacuous"

    def known(h: str) -> bool:
        return (h in routes or h.rstrip("/") in routes
                or (h.endswith("/") and any(r.startswith(h) for r in routes)))

    dead = sorted({h for h in re.findall(r"""['"](/[a-z0-9\-/]*)['"]""", _rendered())
                   if not known(h)})
    assert not dead, f"link(s) to non-existent route(s): {dead}"


def test_the_template_extends_the_site_shell():
    body = ARCHIVE_HTML.read_text()
    assert body.lstrip().startswith('{% extends "base.html" %}')
    assert "<html" not in body.lower()
    assert "<style" not in body.lower(), "page CSS belongs in style.css or an archetype"


def test_the_page_works_without_javascript():
    """Every control is a link or a plain GET form, so filtering survives
    scripting being off — the spec's URL-state requirement, met server-side."""
    body = _rendered()
    assert "<script" not in body.lower()
    assert 'method="get"' in body


def test_urls_are_built_server_side_not_in_the_template():
    """Jinja macros cannot take **kwargs — the first draft tried and raised
    TemplateSyntaxError at render time. URL assembly stays in _archive_qs."""
    body = ARCHIVE_HTML.read_text()
    assert "macro qs(" not in body
    for name in ("url_story", "url_article", "url_windows", "url_sorts", "url_clear"):
        assert name in body, f"{name} not consumed by the template"
