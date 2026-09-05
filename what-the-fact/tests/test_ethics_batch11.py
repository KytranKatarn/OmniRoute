"""Regression coverage for /ethics' stat row + search box (2026-09-04,
WTF Batch 11).

Stats and search are computed entirely from the rows already fetched in
`ethics_rulings()` — same "window" convention /gic's stat row uses (the
tiles reflect the active search filter, not a separate always-unfiltered
total query).

Deliberately NOT added here (see routes.py's comment on the route + the
PR description): a jurisdiction filter or commissioner-office dropdown
(no `legal_watch.ethics_rulings` column backs either — every one of the
30 live rows is a federal CIEC report under `report_type='act'`), the
"enforcement gap" comparison panel (no verified sourcing available in
this environment for specific commissioner powers/limits — risks
fabricating civic/legal claims on a public accountability page), and a
per-row contravention/no-contravention "kind" badge — the schema DOES
have a `finding` text column, but it is verified NULL on all 30 live
rows (`docker exec archie_database psql -U archie -d wtf`, 2026-09-04),
so there is no real outcome to classify from; building a badge now would
mean guessing.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
TPL_DIR = REPO_DIR / "consumer" / "templates"
ROUTES = REPO_DIR / "consumer" / "routes.py"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"

# Verbatim pre-fix ethics.html / ethics_rulings() body, captured BEFORE this
# batch's edit (not read via `git show HEAD:...` — HEAD moves to this batch's
# own commit the moment it lands, which would silently turn these mutation
# checks into a no-op comparing the new file against itself). Inlining the
# old source keeps the check meaningful regardless of later commits/squash.
_OLD_ETHICS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Ethics Commissioner Rulings — Conflict of Interest Reports · What The Fact{% endblock %}
{% block meta %}
<meta name="description" content="All Ethics Commissioner investigation reports on Canadian MPs, ministers, and public officials. Conflict of interest findings 2015–2026.">
{% endblock %}
{% block content %}
<style>
.wtf-eth-header { padding:20px 0 16px; border-bottom:1px solid #2a1a00; margin-bottom:20px; }
.wtf-eth-title { font-family:var(--wtf-font-mono); font-size:20px; color:#e5e7eb; margin:0 0 6px; }
.wtf-eth-sub { font-size:12px; color:#6b7280; }
.wtf-eth-list { display:flex; flex-direction:column; gap:8px; }
</style>

<div class="wtf-eth-header">
  <h1 class="wtf-eth-title">⚖️ Ethics Commissioner Reports</h1>
  <div class="wtf-eth-sub">
    {{ rulings|length }} investigation reports · 2015–2026 · Conflict of Interest and Ethics Commissioner of Canada
  </div>
</div>

<div class="wtf-eth-list">
{% for r in rulings %}
<div class="wtf-eth-row">{{ r.report_name }}</div>
{% endfor %}
</div>
{% endblock %}
'''

_OLD_ETHICS_ROUTE = '''def ethics_rulings():
    """Ethics Commissioner investigation reports."""
    with _db().begin() as c:
        rows = c.execute(text("""
            SELECT e.report_name, e.subject_name, e.ruling_date,
                   e.report_type, e.report_url, e.mp_slug,
                   m.name AS mp_name
            FROM legal_watch.ethics_rulings e
            LEFT JOIN parliament.mps m ON m.slug = e.mp_slug
            ORDER BY e.ruling_date DESC
        """)).mappings().all()
        source_count = c.execute(text(f"SELECT COUNT(*) FROM {_schema()}.sources")).scalar() or 0
    return render_template("ethics.html",
                           rulings=[dict(r) for r in rows],
                           source_count=source_count,
                           is_subscriber=is_subscriber())
'''


def _ruling(report_name, subject_name, report_type="act", mp_slug=None,
            mp_name=None, report_url=None, ruling_date=None):
    return {
        "report_name": report_name, "subject_name": subject_name,
        "report_type": report_type, "mp_slug": mp_slug, "mp_name": mp_name,
        "report_url": report_url, "ruling_date": ruling_date,
    }


_RULINGS = [
    _ruling("Fergus Report", "Fergus", mp_slug="greg-fergus", mp_name="Greg Fergus"),
    _ruling("LeBlanc Report", "LeBlanc", mp_slug="dominic-leblanc", mp_name="Dominic LeBlanc"),
    _ruling("Morneau Report", "Morneau"),
]


def _render(rulings, q="", act_count=None, code_count=None, mp_linked_count=None,
            source_count=30):
    if act_count is None:
        act_count = sum(1 for r in rulings if r["report_type"] == "act")
    if code_count is None:
        code_count = len(rulings) - act_count
    if mp_linked_count is None:
        mp_linked_count = sum(1 for r in rulings if r.get("mp_slug"))
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("ethics.html").render(
        rulings=rulings, q=q, act_count=act_count, code_count=code_count,
        mp_linked_count=mp_linked_count, source_count=source_count,
        is_subscriber=True,
    )


def _render_old_template(rulings, q="", act_count=0, code_count=0, mp_linked_count=0):
    """Renders the PRE-FIX ethics.html (inlined above) with the NEW context,
    to prove the new assertions would fail without this batch's change."""
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB, "ethics.html": _OLD_ETHICS_TEMPLATE}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("ethics.html").render(
        rulings=rulings, q=q, act_count=act_count, code_count=code_count,
        mp_linked_count=mp_linked_count, source_count=30, is_subscriber=True,
    )


def _ethics_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def ethics_rulings")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


# ── stat tiles ───────────────────────────────────────────────────────────

def test_reports_in_view_tile_shows_filtered_count():
    html = _render(_RULINGS)
    assert "Reports in view" in html
    assert ">3<" in html


def test_act_and_code_tiles_show_the_real_report_type_split():
    # 3 rulings all report_type='act' in the fixture -> 3 Act / 0 Code.
    html = _render(_RULINGS)
    idx = html.find("Act examinations")
    assert ">3<" in html[idx:idx + 200]
    idx = html.find("Code inquiries")
    assert ">0<" in html[idx:idx + 200]


def test_code_inquiries_tile_reflects_non_act_rows():
    rulings = _RULINGS + [_ruling("Test Code Report", "Test Subject", report_type="code")]
    html = _render(rulings)
    idx = html.find("Code inquiries")
    assert ">1<" in html[idx:idx + 200]


def test_mp_linked_tile_counts_only_rows_with_a_real_mp_slug():
    # 2 of 3 fixture rulings carry a non-empty mp_slug.
    html = _render(_RULINGS)
    idx = html.find("Linked to an MP profile")
    assert ">2<" in html[idx:idx + 200]


def test_empty_rulings_list_does_not_crash_the_stat_row():
    html = _render([], act_count=0, code_count=0, mp_linked_count=0)
    assert "Reports in view" in html
    assert ">0<" in html


# ── search box ───────────────────────────────────────────────────────────

def test_search_input_preserves_the_current_query_value():
    html = _render(_RULINGS, q="Morneau")
    assert 'value="Morneau"' in html
    assert 'name="q"' in html


def test_search_input_present_and_empty_with_no_query():
    html = _render(_RULINGS, q="")
    assert 'name="q"' in html
    assert 'value=""' in html


def test_clear_link_only_renders_when_a_query_is_active():
    with_q = _render(_RULINGS, q="Morneau")
    without_q = _render(_RULINGS, q="")
    assert "Clear search" in with_q
    assert "Clear search" not in without_q


def test_empty_state_message_when_search_matches_nothing():
    html = _render([], q="nonexistent-name-xyz")
    assert "No ethics rulings matched" in html
    assert "nonexistent-name-xyz" in html


def test_no_empty_state_message_without_an_active_query():
    html = _render([])
    assert "No ethics rulings matched" not in html


# ── route logic (source-inspection, per house test convention) ──────────

def test_route_filters_with_a_parameterized_ilike_not_string_interpolation():
    body = _ethics_route_body()
    assert "ILIKE :q" in body, "search must be parameterized, not f-string interpolated"
    assert 'params["q"] = f"%{q}%"' in body


def test_route_computes_act_and_code_counts_from_report_type():
    body = _ethics_route_body()
    assert 'r.get("report_type") == "act"' in body
    assert "code_count = len(rulings) - act_count" in body


def test_route_computes_mp_linked_count_from_mp_slug_presence():
    body = _ethics_route_body()
    assert 'mp_linked_count = sum(1 for r in rulings if r.get("mp_slug"))' in body


def test_route_does_not_select_a_kind_or_contravention_field():
    # Guards against a future change silently building a badge off the
    # `finding` column while it is still empty on every live row.
    body = _ethics_route_body()
    assert "e.finding" not in body
    assert "kind_count" not in body


# ── mutation check (HARD RULE #7): assertions must fail pre-fix ─────────

def test_old_template_had_no_stat_tiles_or_search_box():
    old_html = _render_old_template(_RULINGS)
    assert "Reports in view" not in old_html
    assert 'name="q"' not in old_html
    assert "wtf-a-tiles" not in old_html


def test_old_route_had_no_search_filter_or_stat_computation():
    assert "ILIKE :q" not in _OLD_ETHICS_ROUTE
    assert "act_count" not in _OLD_ETHICS_ROUTE
    assert "mp_linked_count" not in _OLD_ETHICS_ROUTE
