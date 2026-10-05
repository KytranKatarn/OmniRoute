"""Hardening against writers that resolve an entity by slug/name and so land on a MERGED row.

Follow-up to #3650 (122,660 edges stranded on 20 merged entities). Audit 2026-10-05 found no live
exposure but four latent holes, closed here:
  1. shared `_upsert_entity` looked up by slug with no status check (GIC `appointed_to` edges).
  2. `_merge` never repointed parliament.mps/senators/officers.entity_id, so merging a person who is
     an MP would have stranded every edge written through those columns.
  3. securities + WTF reconcile joined entities with no status filter.
  4. nothing stopped a NEW adapter from doing (3) — hence the lint test at the bottom.
Recording fakes, no database.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import entity_graph_dedup as dd  # noqa: E402
from ingest.shared import entity_graph as eg  # noqa: E402

ING = os.path.join(os.path.dirname(__file__), "..", "ingest")


class _M:
    """A mapping row."""

    def __init__(self, **kw):
        self.d = kw

    def __getitem__(self, k):
        return self.d[k]


class _Res:
    def __init__(self, row=None, scalar=None, rowcount=0):
        self._row, self._s, self.rowcount = row, scalar, rowcount

    def mappings(self):
        return self

    def fetchone(self):
        return self._row

    def one(self):
        return self._row

    def scalar(self):
        return self._s


class TestUpsertEntityFollowsMerges:
    def _conn(self, rows_by_slug_or_id):
        calls = []

        class C:
            def execute(self, stmt, params=None):
                sql = " ".join(str(stmt).split())
                calls.append((sql, dict(params or {})))
                if "INSERT INTO shared.entities" in sql:
                    return _Res(row=None)  # conflict -> DO NOTHING -> no RETURNING row
                if "WHERE slug = :slug" in sql:
                    return _Res(row=rows_by_slug_or_id.get(("slug", params["slug"])))
                if "WHERE id = :id" in sql and sql.startswith("SELECT"):
                    return _Res(row=rows_by_slug_or_id.get(("id", params["id"])))
                return _Res()
        return C(), calls

    def test_a_slug_that_belongs_to_a_merged_row_resolves_to_the_survivor(self):
        rows = {
            ("slug", "org-acme"): _M(id=10, roles=[], aliases=[], status="merged", merged_into=20),
            ("id", 20): _M(id=20, roles=[], aliases=["Acme"], status="active", merged_into=None),
        }
        conn, calls = self._conn(rows)
        eid, action = eg._upsert_entity(conn, canonical_name="Acme", slug="org-acme", entity_type="organization",
                                        role={"type": "x", "external_id": "1"}, raw_name="ACME Corp")
        assert eid == 20 and action == "updated"
        upd = [c for c in calls if c[0].startswith("UPDATE shared.entities")]
        assert upd and upd[0][1]["id"] == 20, "roles/aliases must be written to the SURVIVOR, not the dead row"

    def test_chains_are_followed_and_an_active_row_is_returned_unchanged(self):
        rows = {
            ("slug", "s"): _M(id=1, roles=[], aliases=[], status="merged", merged_into=2),
            ("id", 2): _M(id=2, roles=[], aliases=[], status="merged", merged_into=3),
            ("id", 3): _M(id=3, roles=[], aliases=[], status="active", merged_into=None),
        }
        conn, _ = self._conn(rows)
        assert eg._live_entity_row(conn, "s")["id"] == 3
        rows2 = {("slug", "t"): _M(id=9, roles=[], aliases=[], status="active", merged_into=None)}
        conn2, _ = self._conn(rows2)
        assert eg._live_entity_row(conn2, "t")["id"] == 9
        assert eg._live_entity_row(self._conn({})[0], "nope") is None

    def test_dry_run_also_resolves(self):
        rows = {
            ("slug", "org-acme"): _M(id=10, roles=[], aliases=[], status="merged", merged_into=20),
            ("id", 20): _M(id=20, roles=[], aliases=[], status="active", merged_into=None),
        }
        conn, _ = self._conn(rows)
        eid, action = eg._upsert_entity(conn, canonical_name="Acme", slug="org-acme", entity_type="organization",
                                        role={"type": "x", "external_id": "1"}, raw_name="ACME", dry_run=True)
        assert eid == 20


class _MC:
    def __init__(self, parliament_ids=None, log_row=None):
        self.calls, self.pids, self.log_row = [], parliament_ids or {}, log_row

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        if "row_to_json(e) FROM shared.entities e" in sql:
            return _Res(scalar={"id": (params or {}).get("m"), "canonical_name": "X"})
        if "json_agg(row_to_json(" in sql:
            return _Res(scalar=[])
        if "json_agg(id) FROM shared.entities" in sql:
            return _Res(scalar=[])
        for tbl, ids in self.pids.items():
            if f"FROM {tbl} WHERE entity_id=:m" in sql:
                return _Res(scalar=ids)
        if "json_agg(id) FROM parliament." in sql:
            return _Res(scalar=[])
        if "SELECT aliases, roles FROM shared.entities" in sql:
            return _Res(row={"aliases": [], "roles": []})
        if "FROM shared.entity_merge_log WHERE id=" in sql:
            return _Res(row=self.log_row)
        return _Res(rowcount=1)


TABLES = ("parliament.mps", "parliament.senators", "parliament.officers")


class TestMergeRepointsParliament:
    def test_merge_repoints_each_table_and_records_the_row_ids(self):
        conn = _MC({"parliament.mps": [7], "parliament.senators": [], "parliament.officers": [3, 4]})
        dd._merge(conn, 100, 200, "t", by="test")
        for tbl in TABLES:
            ups = [c for c in conn.calls if c[0].startswith(f"UPDATE {tbl} SET entity_id=:s")]
            assert len(ups) == 1 and ups[0][1] == {"s": 100, "m": 200}
        log = [c for c in conn.calls if "INSERT INTO shared.entity_merge_log" in c[0]][0]
        snap = json.loads(log[1]["snap"])
        assert snap["parliament_refs"] == {"parliament.mps": [7], "parliament.senators": [], "parliament.officers": [3, 4]}

    def test_the_repoint_happens_before_the_merge_is_logged(self):
        conn = _MC()
        dd._merge(conn, 100, 200, "t", by="test")
        sqls = [c[0] for c in conn.calls]
        last_ref = max(i for i, q in enumerate(sqls) if q.startswith("UPDATE parliament."))
        assert last_ref < next(i for i, q in enumerate(sqls) if "INSERT INTO shared.entity_merge_log" in q)

    def test_revert_points_the_parliament_rows_back(self, monkeypatch):
        snap = {"entity": {"canonical_name": "X", "aliases": [], "roles": []}, "relationships": [], "mentions": [],
                "parliament_refs": {"parliament.mps": [7], "parliament.senators": [], "parliament.officers": [3, 4]}}
        conn = _MC(log_row={"survivor_id": 100, "merged_id": 200, "merged_snapshot": snap, "reverted_at": None})

        class E:
            def begin(self):
                class X:
                    def __enter__(s): return conn
                    def __exit__(s, *a): return False
                return X()
        monkeypatch.setattr(dd, "_engine", lambda: E())
        dd.revert(1, by="test")
        back = {c[0].split()[1]: c[1] for c in conn.calls if c[0].startswith("UPDATE parliament.") and "id = ANY" in c[0]}
        assert back["parliament.mps"]["ids"] == [7] and back["parliament.officers"]["ids"] == [3, 4]
        assert "parliament.senators" not in back, "an empty id list must not issue an UPDATE"
        assert all(v["m"] == 200 and v["s"] == 100 for v in back.values())

    def test_an_old_snapshot_without_parliament_refs_reverts_unchanged(self, monkeypatch):
        snap = {"entity": {"canonical_name": "X", "aliases": [], "roles": []}, "relationships": [], "mentions": []}
        conn = _MC(log_row={"survivor_id": 100, "merged_id": 200, "merged_snapshot": snap, "reverted_at": None})

        class E:
            def begin(self):
                class X:
                    def __enter__(s): return conn
                    def __exit__(s, *a): return False
                return X()
        monkeypatch.setattr(dd, "_engine", lambda: E())
        dd.revert(1, by="test")
        assert not [c for c in conn.calls if c[0].startswith("UPDATE parliament.")]


class TestRevertToleratesAnyShapeOfParliamentRefs:
    """F.O.R.G.E. (PR #3652) claimed revert 'assumes the snapshot holds every _ENTITY_REF_TABLES key and may
    raise if one is missing'. It iterates the keys that ARE present, so a missing one cannot raise; these pin it."""

    def _revert(self, monkeypatch, refs, include_key=True):
        snap = {"entity": {"canonical_name": "X", "aliases": [], "roles": []}, "relationships": [], "mentions": []}
        if include_key:
            snap["parliament_refs"] = refs
        conn = _MC(log_row={"survivor_id": 100, "merged_id": 200, "merged_snapshot": snap, "reverted_at": None})

        class E:
            def begin(self):
                class X:
                    def __enter__(s): return conn
                    def __exit__(s, *a): return False
                return X()
        monkeypatch.setattr(dd, "_engine", lambda: E())
        out = dd.revert(1, by="test")
        self.all_calls = conn.calls
        return out, [c for c in conn.calls if c[0].startswith("UPDATE parliament.")]

    def test_a_snapshot_missing_some_table_keys_reverts_the_rest(self, monkeypatch):
        out, ups = self._revert(monkeypatch, {"parliament.mps": [7]})  # senators + officers keys absent
        assert out["reverted"] is True and len(ups) == 1 and ups[0][1]["ids"] == [7]

    def test_none_and_empty_refs_are_fine(self, monkeypatch):
        for refs in (None, {}):
            out, ups = self._revert(monkeypatch, refs)
            assert out["reverted"] is True and ups == []

    def test_an_unknown_table_name_in_a_snapshot_is_ignored_never_executed(self, monkeypatch):
        out, ups = self._revert(monkeypatch, {"public.users; DROP TABLE x": [1], "parliament.mps": [7]})
        assert out["reverted"] is True
        assert [u[0].split()[1] for u in ups] == ["parliament.mps"], "only whitelisted tables are ever touched"
        # check EVERY statement, not just parliament.* ones: an injected name starts with some other schema
        assert not [c for c in self.all_calls if "DROP TABLE" in c[0] or "public.users" in c[0]]


def _src(name):
    return open(os.path.join(ING, name), encoding="utf-8").read()


def test_securities_and_wtf_reconcile_only_match_active_entities():
    assert "e.entity_type = 'organization' AND e.status = 'active'" in _src("entity_graph_securities_reconcile.py")
    wtf = _src("entity_graph_wtf_reconcile.py")
    assert wtf.count("emp.status = 'active'") == 2 and wtf.count("eo.status = 'active'") == 2


# ── lint: an entity JOIN by slug/name with no status filter is the bug class ─────────────────────
_JOIN = re.compile(r"JOIN\s+shared\.entities\s+(\w+)\s+ON\s+(.*?)(?=\bJOIN\b|\bWHERE\b|\bON\s+CONFLICT\b|\)\s*x\b|\"\"\"|\n\s*\n)",
                   re.S | re.I)
# join conditions that are exempt, with the reason
_EXEMPT = (
    ("legislation", "legislation nodes are never deduped (dedup_config.legislation_fuzzy_enabled=0)"),
)


def _violations():
    out = []
    for dirpath, _, files in os.walk(ING):
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            src = open(path, encoding="utf-8").read()
            for m in _JOIN.finditer(src):
                alias, cond = m.group(1), m.group(2)
                by_name = re.search(rf"\b{alias}\.(slug|canonical_name)\b", cond)
                by_id = re.search(rf"\b{alias}\.id\b", cond)
                if not by_name or by_id:
                    continue
                # the status filter may sit in the ON clause OR in the statement's WHERE
                end = src.find('"""', m.end())
                statement = src[m.start(): end if end != -1 else len(src)]
                if re.search(rf"\b{alias}\.status\b", statement):
                    continue
                if any(k in cond for k, _ in _EXEMPT):
                    continue
                out.append((os.path.relpath(path, ING), alias, " ".join(cond.split())[:90]))
    return out


def test_no_adapter_joins_entities_by_slug_or_name_without_a_status_filter():
    bad = _violations()
    assert not bad, (
        "entity JOIN by slug/canonical_name with no status filter — it can match a MERGED row and strand "
        f"edges on it: {bad}")


def test_the_lint_actually_catches_the_pattern():
    # non-vacuity: the regex must flag a deliberately bad join and pass a good one
    bad = "JOIN shared.entities pe ON lower(pe.canonical_name) = lower(d.party) AND pe.entity_type = 'organization'\n\n"
    good = bad.replace("'organization'", "'organization' AND pe.status = 'active'")
    def flagged(sql):
        m = _JOIN.search(sql)
        a, c = m.group(1), m.group(2)
        return bool(re.search(rf"\b{a}\.(slug|canonical_name)\b", c)) and not re.search(rf"\b{a}\.status\b", c)
    assert flagged(bad) and not flagged(good)
