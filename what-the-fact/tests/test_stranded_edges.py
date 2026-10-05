"""Edges must not be attached to MERGED entities.

2026-10-05: 20 merged entities were still gaining relationships on every ingest run — one
("Liberal Party Of Canada", merged into 483 on 2026-06-16) held 122,253 elections_canada edges, 100%
of them created AFTER the merge. A merged entity keeps its slug and its canonical name, so:
  * the entity-graph ingest API upserted by slug and attached edges to the id of the OLD row;
  * the Elections Canada reconcile found the party by lower(canonical_name) with no status
    filter, matching the merged row AND its survivor.
The site resolves a merged slug exactly one hop, so the survivor was missing everything the old row
accumulated. Fixed at both sources, plus an idempotent self-heal in the dedup engine.

Recording fakes, no database. The repair SQL was also run against live Citadel inside a rolled-back
transaction: 122,660 stranded edges -> 0, and no new self-edges.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from consumer import entity_graph_routes as routes  # noqa: E402
from ingest import entity_graph_dedup as dd  # noqa: E402


class _Cur:
    """Answers `SELECT id, merged_into ... WHERE id = ANY(...) AND status='merged'`."""

    def __init__(self, merged):
        self.merged, self.queries = dict(merged), []
        self._rows = []

    def execute(self, sql, params=None):
        self.queries.append(" ".join(sql.split()))
        ids = set(params[0]) if params else set()
        self._rows = [(i, self.merged[i]) for i in ids if i in self.merged]

    def fetchall(self):
        return self._rows


class TestFollowMerges:
    def test_a_merged_id_is_rewritten_to_its_survivor(self):
        m = {"liberal-party-of-canada": 1475428, "other": 7}
        routes._follow_merges(_Cur({1475428: 483}), m)
        assert m == {"liberal-party-of-canada": 483, "other": 7}

    def test_a_chain_is_followed_to_the_end(self):
        m = {"a": 1}
        routes._follow_merges(_Cur({1: 2, 2: 3}), m)
        assert m == {"a": 3}

    def test_active_ids_are_untouched_and_an_empty_map_is_fine(self):
        m = {"a": 5}
        routes._follow_merges(_Cur({}), m)
        assert m == {"a": 5}
        assert routes._follow_merges(_Cur({}), {}) == {}

    def test_a_merge_cycle_cannot_loop_forever(self):
        m = {"a": 1}
        routes._follow_merges(_Cur({1: 2, 2: 1}), m)  # bounded by the hop limit
        assert m["a"] in (1, 2)

    def test_handler_resolves_before_using_the_ids(self):
        src = open(routes.__file__, encoding="utf-8").read()
        body = src[src.index("# 1) Entities"): src.index("cur.close()")]
        first_resolve = body.index("_follow_merges(cur, slug_to_id)")
        assert first_resolve < body.index("# 1b) External ids"), "external ids must attach to the survivor"
        assert body.count("_follow_merges(cur, slug_to_id)") == 2, "both the upsert path and the pointer lookup"
        assert body.rindex("_follow_merges(cur, slug_to_id)") < body.index("# 3) Mentions")


def test_ec_reconcile_only_matches_active_party_and_donor():
    p = os.path.join(os.path.dirname(dd.__file__), "entity_graph_ec_donations_reconcile.py")
    src = open(p, encoding="utf-8").read()
    block = src[src.index("totals[\"donated_to_edges\"]"): src.index("# 6) direct donor")]
    assert "de.status = 'active'" in block, "a merged donor must not receive new edges"
    assert re.search(r"pe\.entity_type = 'organization'\s+AND pe\.status = 'active'", block), \
        "the party lookup is by NAME — the merged row and its survivor share it"


class _Res:
    def __init__(self, n):
        self.rowcount = n


class _Conn:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append(sql)
        return _Res(3 if sql.startswith("UPDATE") else 0)


class TestRepointStranded:
    def test_deletes_collisions_before_each_update_in_both_directions(self):
        conn = _Conn()
        out = dd.repoint_stranded_edges(conn)
        rel = [c for c in conn.calls if "entity_relationships" in c]
        kinds = [("DEL" if c.startswith("DELETE") else "UPD", "from" if "r.from_entity_id" in c.split("WHERE")[1] else "to") for c in rel]
        assert kinds == [("DEL", "from"), ("UPD", "from"), ("DEL", "to"), ("UPD", "to")]
        assert out == {"relationships": 6, "mentions": 3}

    def test_only_merged_entities_with_a_survivor_are_touched(self):
        conn = _Conn()
        dd.repoint_stranded_edges(conn)
        for c in conn.calls:
            assert "e.status = 'merged'" in c and "e.merged_into IS NOT NULL" in c

    def test_mentions_are_deduplicated_then_repointed(self):
        conn = _Conn()
        dd.repoint_stranded_edges(conn)
        ment = [c for c in conn.calls if "entity_mentions" in c]
        assert [c.split()[0] for c in ment] == ["DELETE", "UPDATE"]

    def test_run_calls_it_and_dry_run_does_not(self, monkeypatch):
        calls = []

        class _R:
            rowcount = 0
            def scalar(self): return None
            def mappings(self): return self
            def fetchall(self): return []
        class _C:
            def execute(self, *a, **k): return _R()
        class _E:
            def begin(self):
                class _X:
                    def __enter__(s): return _C()
                    def __exit__(s, *a): return False
                return _X()
        monkeypatch.setattr(dd, "_engine", lambda: _E())
        monkeypatch.setattr(dd, "repoint_stranded_edges", lambda conn: calls.append(1) or {"relationships": 0, "mentions": 0})
        dd.run(dry_run=True)
        assert calls == []
        dd.run(dry_run=False)
        assert calls == [1]
