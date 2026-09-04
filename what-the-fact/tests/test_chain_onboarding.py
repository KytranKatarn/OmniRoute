"""Regression coverage for /chain's onboarding + explainer + footer pieces
(2026-09-04, Batch 10 item 9, KB vault_note #304357).

Three additive pieces, no route/behavior removed:
  1. #chainEmpty gets real, live-verified example entities (was static text only).
  2. A persistent "Reading a chain honestly" explainer panel, always visible —
     distinct from the dynamic per-entity d.note the JS already renders inside
     renderEntity() for the SELECTED entity.
  3. chain_entity()'s JSON payload now exposes the entity's numeric id (it was
     computed internally as `eid = ent["id"]` but never returned), and the
     client's renderEntity() uses it to link out to the Cross-Watch footprint
     (/entity/<id>) + a coverage search (/search?q=<name>).

Deliberately NOT added: per-link hover tooltips naming each chain link's
real-world data source. shared.chain_link_types has no data_source column
(verified live: relationship_type, link_position, label, has_data, is_spine,
created_at — nothing else) and inventing attribution text would violate the
same no-fabrication rule that got /team's per-agent "weak spot" content
skipped in this same batch. Adding a real column is a separate, larger task.

Example entities (verified live against the wtf DB's shared.entities /
shared.entity_relationships, 2026-09-04 — a mix of entity_type so the
onboarding set isn't three near-identical rows):
  mark-carney                                    person/MP, 3611 edges
  public-works-and-government-services-canada    organization, 84204 edges
  the-globe-and-mail                              organization, 6611 edges
"""

from __future__ import annotations

import pathlib
import re

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL_DIR = REPO_ROOT / "consumer" / "templates"
ROUTES = REPO_ROOT / "consumer" / "chain_routes.py"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"

_EXAMPLE_SLUGS = [
    "mark-carney",
    "public-works-and-government-services-canada",
    "the-globe-and-mail",
]


def _render(chain_slug=None):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("chain.html").render(chain_slug=chain_slug, source_count=46)


def _chain_entity_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def chain_entity")
    return src[start:]  # last function in the file


# ── template: onboarding example cards ──────────────────────────────────────

def test_renders_without_a_slug():
    html = _render(chain_slug=None)
    assert "chain-wrap" in html


def test_all_three_example_entities_present_with_real_hrefs():
    html = _render()
    for slug in _EXAMPLE_SLUGS:
        assert f'href="/chain/{slug}"' in html, f"missing example link for {slug}"


def test_example_cards_show_a_type_label_not_just_a_bare_name():
    html = _render()
    assert "MP · Prime Minister" in html
    assert "Federal department" in html
    assert "Media outlet" in html


def test_example_links_are_intercepted_for_in_page_navigation():
    html = _render()
    assert "chain-example" in html
    assert "querySelectorAll('.chain-example')" in html
    assert "preventDefault()" in html


# ── template: persistent explainer panel ────────────────────────────────────

def test_persistent_explainer_present_and_distinct_from_per_entity_note():
    html = _render()
    assert "Reading a chain honestly" in html
    assert "chain-explainer" in html
    # the dynamic per-entity note (d.note) must still exist as its own thing
    assert "chain-note" in html
    assert "if(d.note)" in html


def test_explainer_is_not_gated_behind_a_slug():
    # It must render whether or not an entity is currently loaded — it explains
    # the rail's on/off chips in general, not the selected entity's own gaps.
    with_slug = _render(chain_slug="mark-carney")
    without_slug = _render(chain_slug=None)
    assert "Reading a chain honestly" in with_slug
    assert "Reading a chain honestly" in without_slug


# ── backend: entity id exposed in the payload ───────────────────────────────

def test_chain_entity_payload_includes_the_numeric_id():
    body = _chain_entity_body()
    assert '"id": ent["id"]' in body, (
        "eid = ent['id'] is computed for the internal graph queries but must "
        "also be exposed in payload['entity'] for the client's Cross-Watch link"
    )


def test_id_key_is_inside_the_entity_dict_not_top_level():
    body = _chain_entity_body()
    payload_start = body.index('payload = {')
    payload_src = body[payload_start:payload_start + 400]
    # "id" must appear before "canonical_name" inside the same entity{} block
    assert re.search(r'"entity":\s*\{\s*"id":\s*ent\["id"\]', payload_src), (
        "id must be the first key inside entity{}, alongside slug/canonical_name"
    )


# ── template: footer quick-links wired off the entity id ───────────────────

def test_footer_links_use_the_entity_id_and_canonical_name():
    html = _render()
    assert "chain-footer" in html
    assert "/entity/" in html
    assert "Cross-Watch footprint" in html
    assert "/search?q=" in html
    assert "Search coverage" in html


def test_footer_cross_watch_link_guarded_on_id_presence():
    html = _render()
    assert "if(e.id != null)" in html, (
        "must not crash / render a broken /entity/undefined link if a cached "
        "payload predates the id field"
    )


def test_footer_is_appended_after_the_note_not_before():
    html = _render()
    note_idx = html.index("if(d.note)")
    footer_idx = html.index("var footer = el(")
    assert note_idx < footer_idx


# ── no-fabrication: piece 3 (data-source tooltips) deliberately absent ─────

def test_no_fabricated_per_link_data_source_attribution():
    html = _render()
    # must never claim a source name we cannot back with a real column
    assert "data-source" not in html.lower().replace(" ", "")
    assert "data_source" not in html
