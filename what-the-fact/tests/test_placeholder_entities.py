"""A "no value" marker ("N/A", "unknown", ...) must never become a graph node.

2026-10-05: entity 749 "NA" held 116,602 gov-watch awarded_to edges to 22,955 unrelated
counterparties — every award whose vendor was blank or "N/A" — so it was ~200x the most connected
node and tied everyone to everyone. The aliases show how the source wrote it: ".N/A .", "#N/A",
"n/a", "N/A", "NA", "na". The ingest endpoint now drops placeholders (and any edge/mention that
references one) instead of creating the node. Recording fakes, no database.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from consumer import entity_graph_routes as routes  # noqa: E402
from ingest.shared.entity_graph import is_placeholder_name  # noqa: E402


@pytest.mark.parametrize("name", [
    "NA", "na", "N/A", "n/a", ".N/A .", "#N/A", "n-a", "N.A.", " N/A ",
    "Unknown", "UNKNOWN", "Not applicable", "Not Available", "TBD", "None", "null", "NaN",
    "Various", "Undisclosed", "-", "--", ".", "", "   ", None,
])
def test_placeholders_are_recognised(name):
    assert is_placeholder_name(name)


@pytest.mark.parametrize("name", [
    "Nathan", "Natalie Roy", "Na Zhang", "Navigator Ltd", "Unknown Pleasures Inc", "Nonesuch Corp",
    "Tba Holdings", "Canada Post", "NA Engineering",
])
def test_real_names_are_not_placeholders(name):
    assert not is_placeholder_name(name)


def _reg(ref):
    inline, pointers = {}, set()
    return routes._register_ref(ref, inline, pointers), inline, pointers


def test_inline_placeholder_creates_no_node():
    slug, inline, pointers = _reg({"canonical_name": "N/A", "entity_type": "organization"})
    assert slug is None and inline == {} and pointers == set()


def test_pointer_to_the_na_slug_is_dropped():
    slug, inline, pointers = _reg({"slug": "na"})
    assert slug is None and pointers == set()


def test_pointer_to_a_real_slug_still_works():
    slug, _, pointers = _reg({"slug": "canada-post"})
    assert slug == "canada-post" and pointers == {"canada-post"}


def test_real_inline_entity_still_registers():
    slug, inline, _ = _reg({"canonical_name": "Canada Post Corp.", "entity_type": "organization"})
    assert slug and slug in inline


def test_the_endpoint_drops_edges_and_mentions_that_touch_a_placeholder():
    """End to end through the real view with the DB layer faked out: only the clean edge lands."""
    import json

    captured = {"rels": [], "mentions": []}

    class FakeCur:
        def __init__(self):
            self._rows = []

        def execute(self, sql, params=None):
            self._rows = []

        def fetchall(self):
            return self._rows

        def close(self):
            pass

    class FakeConn:
        connection = type("C", (), {"cursor": staticmethod(lambda: FakeCur())})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeEngine:
        def begin(self):
            return FakeConn()

    def fake_execute_values(cur, sql, rows, template=None, page_size=None, fetch=False):
        if "entity_relationships" in sql:
            captured["rels"] = list(rows)
        elif "entity_mentions" in sql:
            captured["mentions"] = list(rows)
        elif "shared.entities" in sql and fetch:
            return [(100 + i, r[2], True) for i, r in enumerate(rows)]
        return None

    orig = (routes._eng, routes.execute_values)
    routes._eng, routes.execute_values = (lambda: FakeEngine()), fake_execute_values
    os.environ["INTERNAL_API_KEY"] = "k"
    try:
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(routes.entity_graph_bp)
        vendor = {"canonical_name": "Acme Ltd", "entity_type": "organization"}
        dept = {"canonical_name": "Dept of Works", "entity_type": "organization"}
        na = {"canonical_name": "N/A", "entity_type": "organization"}
        payload = {
            "product": "gov-watch",
            "relationships": [
                {"from": vendor, "to": dept, "relationship_type": "awarded_to", "source_id": "c1"},
                {"from": na, "to": dept, "relationship_type": "awarded_to", "source_id": "c2"},
                {"from": vendor, "to": na, "relationship_type": "awarded_to", "source_id": "c3"},
            ],
            "mentions": [{"entity": na, "content_type": "contract", "content_id": "c2"}],
        }
        r = app.test_client().post("/api/internal/entity-graph/ingest", data=json.dumps(payload),
                                   headers={"X-Internal-Key": "k", "Content-Type": "application/json"})
        body = r.get_json()
    finally:
        routes._eng, routes.execute_values = orig

    assert r.status_code == 200, body
    assert body["skipped_placeholder"] == 3          # two edges + one mention
    assert len(captured["rels"]) == 1                # only the clean edge
    assert captured["mentions"] == []
    assert not any("n-a" in str(x) or x[0:2] == ("na",) for x in captured["rels"])
