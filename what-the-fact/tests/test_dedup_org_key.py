"""Organisation dedup keys ignore spacing, punctuation, case and accents.

2026-10-05: 4,092 active-organisation groups (8,457 entities) differed only in spacing/punctuation
("LEVITT SAFETY LIMITED" / "LEVITTSAFETYLIMITED" / "Levitt- Safety Limited"). The old key,
lower(unaccent(btrim(name))), kept internal spaces and punctuation so exact-name dedup never saw
them; they were merged by hand in seven batches. These tests pin the new rule and — because the
engine auto-merges — the guards that keep it from merging people or generic names.

They use a recording fake connection (no database). The group SQL itself was run against the live
Citadel database separately (781 groups, 0 oversized).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import entity_graph_dedup as dd  # noqa: E402

classify = dd.classify_org_group


def _m(*pairs):
    return list(pairs)


class TestClassify:
    def test_clean_group_is_auto(self):
        assert classify("levittsafetylimited", _m((1, "LEVITT SAFETY LIMITED"), (2, "LEVITTSAFETYLIMITED")), set()) == "auto"

    def test_short_key_goes_to_review(self):
        assert classify("abc", _m((1, "A B C"), (2, "ABC")), set()) == "review"
        assert classify("abcde", _m((1, "A B C D E"), (2, "ABCDE")), set()) == "review"
        assert classify("abcdef", _m((1, "A B C D E F"), (2, "ABCDEF")), set()) == "auto"

    def test_comma_names_go_to_review_not_auto(self):
        # "Moyeda, Alma" / "Moyeda,Alma": a person stored as an organisation — people share names.
        assert classify("moyedaalma", _m((1, "Moyeda, Alma"), (2, "Moyeda,Alma")), set()) == "review"
        # a comma on ANY member is enough
        assert classify("acmecorp", _m((1, "ACME CORP"), (2, "Acme, Corp")), set()) == "review"

    def test_oversized_group_goes_to_review(self):
        six = [(i, f"N{i}") for i in range(6)]
        seven = [(i, f"N{i}") for i in range(7)]
        assert classify("longenoughkey", six, set()) == "auto"
        assert classify("longenoughkey", seven, set()) == "review"

    def test_a_recorded_distinct_decision_skips_the_whole_group_either_order(self):
        members = _m((1, "ACME CORP"), (2, "A C M E CORP"), (3, "Acme-Corp"))
        assert classify("acmecorp", members, {(1, 3)}) == "skip"
        assert classify("acmecorp", members, {(3, 1)}) == "skip"
        # the decision between two members taints the group even if the survivor is not in it
        assert classify("acmecorp", members, {(2, 3)}) == "skip"

    def test_distinct_beats_every_other_rule(self):
        assert classify("ab", _m((1, "A, B"), (2, "AB")), {(1, 2)}) == "skip"


class _Res:
    def __init__(self, scalar=None, rows=None, rowcount=0):
        self._s, self._rows, self.rowcount = scalar, rows or [], rowcount

    def scalar(self):
        return self._s

    def mappings(self):
        return self

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, groups, distinct=()):
        self.groups, self.distinct, self.calls = groups, list(distinct), []

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        if "FROM shared.dedup_config" in sql:
            return _Res(scalar=None)
        if "GROUP BY 1 HAVING count(*) > 1" in sql and "'organization'" in sql:
            return _Res(rows=self.groups)
        if "FROM shared.dedup_pair_decisions" in sql:
            return _Res(rows=self.distinct)
        if "INSERT INTO shared.merge_review_queue" in sql and "'squash_name'" in sql:
            return _Res(rowcount=1)
        return _Res(rowcount=0)


class _Eng:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        conn = self.conn

        class _Ctx:
            def __enter__(self):
                return conn

            def __exit__(self, *a):
                return False
        return _Ctx()


def _run(monkeypatch, groups, distinct=(), dry=False):
    conn = _Conn(groups, distinct)
    merges = []
    monkeypatch.setattr(dd, "_engine", lambda: _Eng(conn))
    monkeypatch.setattr(dd, "_merge", lambda c, s, m, reason, by="x": merges.append((s, m, reason)))
    totals = dd.run(dry_run=dry)
    return totals, merges, conn


def _g(norm, *members):
    return {"norm": norm, "ids": [m[0] for m in members], "names": [m[1] for m in members]}


class TestRun:
    def test_auto_group_merges_everyone_into_the_first_member(self, monkeypatch):
        groups = [_g("levittsafetylimited", (10, "LEVITT SAFETY LIMITED"), (11, "LEVITTSAFETYLIMITED"), (12, "Levitt- Safety Limited"))]
        totals, merges, _ = _run(monkeypatch, groups)
        assert merges == [(10, 11, "squash_name_org"), (10, 12, "squash_name_org")]
        assert totals["org_merges"] == 2

    def test_comma_group_is_queued_for_review_not_merged(self, monkeypatch):
        groups = [_g("moyedaalma", (30, "Moyeda,Alma"), (20, "Moyeda, Alma"))]
        totals, merges, conn = _run(monkeypatch, groups)
        assert merges == []
        ins = [c for c in conn.calls if "INSERT INTO shared.merge_review_queue" in c[0] and "'squash_name'" in c[0]]
        assert len(ins) == 1
        assert (ins[0][1]["a"], ins[0][1]["b"]) == (20, 30), "check constraint needs entity_id_a < entity_id_b"
        assert totals["org_review_groups"] == 1 and totals.get("org_review_queued") == 1

    def test_group_with_a_distinct_decision_is_untouched(self, monkeypatch):
        groups = [_g("acmecorp", (1, "ACME CORP"), (2, "A C M E CORP"))]
        totals, merges, conn = _run(monkeypatch, groups, distinct=[(1, 2)])
        assert merges == []
        assert totals.get("org_skipped_distinct") == 1
        assert not [c for c in conn.calls if "'squash_name'" in c[0]]

    def test_dry_run_writes_nothing(self, monkeypatch):
        groups = [_g("levittsafetylimited", (10, "A B"), (11, "AB")), _g("moyedaalma", (2, "M, A"), (3, "M,A"))]
        totals, merges, conn = _run(monkeypatch, groups, dry=True)
        assert merges == []
        assert not [c for c in conn.calls if "INSERT INTO shared.merge_review_queue" in c[0] and "'squash_name'" in c[0]]
        assert totals["org_merges"] == 1


class TestKeys:
    def test_org_grouping_uses_the_alphanumeric_key_and_persons_do_not(self, monkeypatch):
        _, _, conn = _run(monkeypatch, [])
        org = [c[0] for c in conn.calls if "GROUP BY 1 HAVING count(*) > 1" in c[0] and "'organization'" in c[0]]
        assert org, "organisation group query not found"
        assert re.search(r"regexp_replace\(lower\(unaccent\(btrim\(e\.canonical_name\)\)\), '\[\^a-z0-9\]', '', 'g'\)", org[0])
        person = [c[0] for c in conn.calls if "entity_type='person'" in c[0] and "INSERT INTO shared.merge_review_queue" in c[0]]
        assert person and "regexp_replace" not in person[0], "persons must keep the spacing-sensitive key"
