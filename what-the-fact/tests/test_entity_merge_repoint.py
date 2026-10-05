"""Merging an entity that other entities were already merged INTO must not strand them.

2026-10-05: 14041 was merged into 14175 while 25 older entities had merged_into=14041. The site
resolves a merged slug exactly one hop (consumer/chain_routes.py), so those 25 slugs would have
resolved to 14041 — itself merged, 0 relationships — an empty page. _merge now repoints them and
snapshots their ids so revert() can point them back.

These use a recording fake connection: they assert WHAT SQL _merge/revert issue and in what order,
not what Postgres does with it (no database is needed). The live behaviour was verified separately
against the Citadel database.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import entity_graph_dedup as dd  # noqa: E402


class _Result:
    def __init__(self, scalar=None, row=None, rowcount=1):
        self._scalar, self._row, self.rowcount = scalar, row, rowcount

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def one(self):
        return self._row

    def fetchone(self):
        return self._row


class _Conn:
    """Records every statement; answers the few reads _merge / revert make."""

    def __init__(self, children=(), log_row=None):
        self.calls = []
        self.children = list(children)
        self.log_row = log_row

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        if "row_to_json(e) FROM shared.entities e" in sql:
            return _Result(scalar={"id": (params or {}).get("m"), "canonical_name": "X"})
        if "json_agg(row_to_json(r))" in sql or "json_agg(row_to_json(em))" in sql:
            return _Result(scalar=[])
        if "json_agg(id)" in sql:
            return _Result(scalar=list(self.children))
        if "SELECT aliases, roles FROM shared.entities" in sql:
            return _Result(row={"aliases": [], "roles": []})
        if "FROM shared.entity_merge_log WHERE id=" in sql:
            return _Result(row=self.log_row)
        return _Result()

    def sqls(self):
        return [c[0] for c in self.calls]


_REPOINT = re.compile(r"UPDATE shared\.entities SET merged_into=:s WHERE merged_into=:m AND status='merged'")
_MARK = re.compile(r"UPDATE shared\.entities SET status='merged', merged_into=:s WHERE id=:m")


def test_merge_repoints_prior_children_before_marking_merged():
    conn = _Conn(children=[101, 102])
    dd._merge(conn, 14175, 14041, "t", by="test")
    sqls = conn.sqls()
    rp = [i for i, q in enumerate(sqls) if _REPOINT.search(q)]
    mk = [i for i, q in enumerate(sqls) if _MARK.search(q)]
    assert len(rp) == 1 and len(mk) == 1, "expected exactly one repoint and one mark-merged statement"
    assert rp[0] < mk[0]
    assert conn.calls[rp[0]][1] == {"s": 14175, "m": 14041}


def test_merge_snapshots_the_children_for_revert():
    conn = _Conn(children=[101, 102])
    dd._merge(conn, 14175, 14041, "t", by="test")
    log = [c for c in conn.calls if "INSERT INTO shared.entity_merge_log" in c[0]]
    assert len(log) == 1
    snap = json.loads(log[0][1]["snap"])
    assert snap["repointed_children"] == [101, 102]


def test_revert_points_the_children_back(monkeypatch):
    snap = {"entity": {"canonical_name": "X", "aliases": [], "roles": []},
            "relationships": [], "mentions": [], "repointed_children": [101, 102]}
    log = {"survivor_id": 14175, "merged_id": 14041, "merged_snapshot": snap, "reverted_at": None}
    conn = _Conn(log_row=log)

    class _Eng:
        def begin(self):
            conn_ = conn

            class _Ctx:
                def __enter__(self_inner):
                    return conn_

                def __exit__(self_inner, *a):
                    return False
            return _Ctx()

    monkeypatch.setattr(dd, "_engine", lambda: _Eng())
    out = dd.revert(7, by="test")
    ups = [c for c in conn.calls if "SET merged_into=:m WHERE id = ANY(:ids)" in c[0]]
    assert len(ups) == 1
    assert ups[0][1] == {"m": 14041, "s": 14175, "ids": [101, 102]}
    assert out["restored_children"] == 1


def test_revert_of_an_old_snapshot_without_children_is_unchanged(monkeypatch):
    snap = {"entity": {"canonical_name": "X", "aliases": [], "roles": []}, "relationships": [], "mentions": []}
    log = {"survivor_id": 14175, "merged_id": 14041, "merged_snapshot": snap, "reverted_at": None}
    conn = _Conn(log_row=log)

    class _Eng:
        def begin(self):
            class _Ctx:
                def __enter__(self_inner):
                    return conn

                def __exit__(self_inner, *a):
                    return False
            return _Ctx()

    monkeypatch.setattr(dd, "_engine", lambda: _Eng())
    out = dd.revert(7, by="test")
    assert not any("id = ANY(:ids)" in q for q in conn.sqls())
    assert out["restored_children"] == 0
