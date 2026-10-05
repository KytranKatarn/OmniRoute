"""A vendor must not latch onto a same-slug JOURNALIST.

Slugs are one namespace across node types and the upsert is ON CONFLICT (slug), which keeps the
existing type. So a gov-watch vendor/contact named like a byline journalist attached 3-58 awards to
that journalist (Nick Perry 50, Susan O'Brien 44, University of Calgary 58 ...): 41 journalists in
all. Splitting the data would have been undone by the next nightly push, so the endpoint now gives
the non-journalist its own node ("<slug>-organization"). Recording fakes, no database.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from consumer import entity_graph_routes as routes  # noqa: E402


def _collect(payload):
    inline, pointers, mention_rows, rel_rows = {}, set(), {}, {}
    for r in payload.get("relationships", []):
        f = routes._register_ref(r["from"], inline, pointers)
        t = routes._register_ref(r["to"], inline, pointers)
        rel_rows[(f, t, r["relationship_type"], r.get("source_id"))] = (
            f, t, r["relationship_type"], r.get("source_id"), None, None, "{}")
    for m in payload.get("mentions", []):
        slug = routes._register_ref(m["entity"], inline, pointers)
        mention_rows[(slug, m["content_type"], str(m["content_id"]))] = (
            slug, m["content_type"], str(m["content_id"]), None, None)
    return inline, mention_rows, rel_rows


ORG = lambda n: {"canonical_name": n, "entity_type": "organization"}  # noqa: E731


def test_remap_renames_everywhere_but_leaves_other_slugs_alone():
    inline, mrows, rrows = _collect({
        "relationships": [{"from": ORG("Nick Perry"), "to": ORG("Acme Ltd"),
                           "relationship_type": "awarded_to", "source_id": "c1"}],
        "mentions": [{"entity": ORG("Nick Perry"), "content_type": "contract", "content_id": "c1"}],
    })
    routes._apply_slug_remap({"nick-perry": "nick-perry-organization"}, inline, mrows, rrows)
    assert "nick-perry" not in inline and "nick-perry-organization" in inline
    assert "acme-ltd" in inline
    assert list(mrows) == [("nick-perry-organization", "contract", "c1")]
    assert mrows[("nick-perry-organization", "contract", "c1")][0] == "nick-perry-organization"
    (key,) = rrows
    assert key == ("nick-perry-organization", "acme-ltd", "awarded_to", "c1")
    assert rrows[key][:2] == ("nick-perry-organization", "acme-ltd")


def test_empty_remap_is_a_noop():
    inline, mrows, rrows = _collect({"relationships": [
        {"from": ORG("A Corp"), "to": ORG("B Corp"), "relationship_type": "awarded_to", "source_id": "x"}]})
    before = (dict(inline), dict(mrows), dict(rrows))
    routes._apply_slug_remap({}, inline, mrows, rrows)
    assert (inline, mrows, rrows) == before


class _Cur:
    def __init__(self, journalist_slugs):
        self.j, self.sql = set(journalist_slugs), []
        self._rows = []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self._rows = [(s,) for s in params[0] if s in self.j]

    def fetchall(self):
        return self._rows


def test_clash_is_detected_only_for_non_journalists_on_a_journalist_row():
    inline, _, _ = _collect({"relationships": [
        {"from": ORG("Nick Perry"), "to": ORG("Acme Ltd"), "relationship_type": "awarded_to", "source_id": "c"}]})
    cur = _Cur({"nick-perry"})
    assert routes._journalist_slug_clashes(cur, inline) == {"nick-perry": "nick-perry-organization"}
    assert "entity_type = 'journalist'" in cur.sql[0] and "status <> 'merged'" in cur.sql[0]


def test_an_incoming_journalist_never_remaps():
    inline = {"jane-doe": {"etype": "journalist", "cname": "Jane Doe", "raws": ["Jane Doe"],
                           "roles": [], "meta": {}, "ext_ids": []}}
    cur = _Cur({"jane-doe"})
    assert routes._journalist_slug_clashes(cur, inline) == {}
    assert cur.sql == []                     # no query when there is nothing to check


def test_no_clash_when_the_slug_is_not_a_journalist():
    inline, _, _ = _collect({"relationships": [
        {"from": ORG("Acme Ltd"), "to": ORG("Other Corp"), "relationship_type": "awarded_to", "source_id": "c"}]})
    assert routes._journalist_slug_clashes(_Cur({"somebody-else"}), inline) == {}


def test_the_endpoint_end_to_end_writes_the_remapped_slug():
    captured = {}

    class FakeCur:
        def __init__(self):
            self._rows, self.last = [], ""

        def execute(self, sql, params=None):
            self.last = " ".join(sql.split())
            if "entity_type = 'journalist'" in self.last:
                self._rows = [("nick-perry",)] if "nick-perry" in params[0] else []
            else:
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
            captured["slugs"] = [r[2] for r in rows]
            return [(100 + i, r[2], True) for i, r in enumerate(rows)]
        return None

    orig = (routes._eng, routes.execute_values)
    routes._eng, routes.execute_values = (lambda: FakeEngine()), fake_execute_values
    os.environ["INTERNAL_API_KEY"] = "k"
    try:
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(routes.entity_graph_bp)
        payload = {"product": "gov-watch",
                   "relationships": [{"from": ORG("Nick Perry"), "to": ORG("Acme Ltd"),
                                      "relationship_type": "awarded_to", "source_id": "c1"}],
                   "mentions": [{"entity": ORG("Nick Perry"), "content_type": "contract", "content_id": "c1"}]}
        r = app.test_client().post("/api/internal/entity-graph/ingest", data=json.dumps(payload),
                                   headers={"X-Internal-Key": "k", "Content-Type": "application/json"})
        body = r.get_json()
    finally:
        routes._eng, routes.execute_values = orig

    assert r.status_code == 200, body
    assert body["journalist_slug_remapped"] == 1
    assert "nick-perry" not in captured["slugs"] and "nick-perry-organization" in captured["slugs"]
    assert "acme-ltd" in captured["slugs"]
