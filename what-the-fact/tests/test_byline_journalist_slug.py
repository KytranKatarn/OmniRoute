"""A byline must attach to a JOURNALIST, never to whatever node happens to hold the slug.

Mirror of the ingest-side collision (PR #3657): slugs are one namespace across node types, and
resolve_byline looked a journalist up by slug with no type or status filter. A vendor/contact named
"Nick Perry" owns slug `nick-perry`, so the byline "Nick Perry" put news-article mentions and an
outlet list on a procurement node; a MERGED row kept its slug too, stranding the mention where the
site follows it only one hop. Recording fake connection, no database.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared import author_resolver as ar  # noqa: E402


class _Res:
    def __init__(self, row=None, scalar=None):
        self._row, self._scalar = row, scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def scalar(self):
        return self._scalar


class FakeConn:
    """entities: {id: {slug, entity_type, status, merged_into, metadata}}"""

    def __init__(self, entities):
        self.entities, self.next_id, self.writes = dict(entities), 1000, []

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split())
        params = params or {}
        if sql.startswith("SELECT") and "WHERE slug=:slug" in sql:
            for i, e in self.entities.items():
                if e["slug"] == params["slug"]:
                    return _Res({"id": i, **e})
            return _Res(None)
        if sql.startswith("SELECT") and "WHERE id=:i" in sql:
            e = self.entities.get(params["i"])
            return _Res({"id": params["i"], **e} if e else None)
        if sql.startswith("INSERT"):
            self.next_id += 1
            self.entities[self.next_id] = {"slug": params["slug"], "entity_type": "journalist",
                                           "status": "active", "merged_into": None,
                                           "metadata": {"outlets": [params["o"]] if params["o"] else []}}
            self.writes.append(("insert", self.next_id, params["slug"]))
            return _Res(scalar=self.next_id)
        if sql.startswith("UPDATE"):
            self.writes.append(("outlet", params["id"], params["o"]))
            return _Res()
        raise AssertionError(sql)


def E(slug, etype="journalist", status="active", merged_into=None, outlets=()):
    return {"slug": slug, "entity_type": etype, "status": status, "merged_into": merged_into,
            "metadata": {"outlets": list(outlets)}}


def test_a_byline_reuses_its_active_journalist():
    c = FakeConn({1: E("jane-smith", outlets=["a"])})
    assert ar.resolve_byline(c, "Jane Smith", "a", shared_schema="shared") == [1]
    assert c.writes == []


def test_a_byline_does_not_attach_to_a_vendor_holding_the_slug():
    c = FakeConn({7: E("nick-perry", etype="organization")})
    (eid,) = ar.resolve_byline(c, "Nick Perry", "src", shared_schema="shared")
    assert eid != 7
    assert c.entities[eid]["slug"] == "nick-perry-journalist"
    assert c.entities[eid]["entity_type"] == "journalist"
    assert not any(w[0] == "outlet" and w[1] == 7 for w in c.writes)   # vendor untouched


def test_the_second_byline_finds_the_journalist_specific_slug():
    c = FakeConn({7: E("nick-perry", etype="organization")})
    a = ar.resolve_byline(c, "Nick Perry", "src", shared_schema="shared")
    b = ar.resolve_byline(c, "Nick Perry", "src", shared_schema="shared")
    assert a == b and sum(1 for w in c.writes if w[0] == "insert") == 1


def test_a_merged_row_is_followed_to_its_surviving_journalist():
    c = FakeConn({1: E("jane-smith", status="merged", merged_into=2), 2: E("jane-smith-2")})
    assert ar.resolve_byline(c, "Jane Smith", "", shared_schema="shared") == [2]


def test_a_merged_row_whose_survivor_is_not_a_journalist_gets_its_own_node():
    c = FakeConn({1: E("jane-smith", status="merged", merged_into=2), 2: E("jane-acme", etype="organization")})
    (eid,) = ar.resolve_byline(c, "Jane Smith", "", shared_schema="shared")
    assert eid not in (1, 2) and c.entities[eid]["slug"] == "jane-smith-journalist"


def test_a_suppressed_journalist_slug_is_treated_as_taken():
    c = FakeConn({1: E("phd", status="suppressed")})
    (eid,) = ar.resolve_byline(c, "PhD", "", shared_schema="shared")
    assert eid != 1 and c.entities[eid]["slug"] == "phd-journalist"


def test_a_new_name_is_created_at_the_plain_slug():
    c = FakeConn({})
    (eid,) = ar.resolve_byline(c, "Brand New", "src", shared_schema="shared")
    assert c.entities[eid]["slug"] == "brand-new"


def test_the_lookup_filters_in_python_not_by_assuming_the_slug():
    """Guard the shape: the SELECT must fetch type/status/merged_into so the decision is explicit."""
    src = open(ar.__file__).read()
    sel = re.search(r"SELECT id, metadata, entity_type, status, merged_into FROM", src)
    assert sel
