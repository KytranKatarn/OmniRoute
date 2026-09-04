"""Guards for the precomputed /cross-watch snapshot (migration 075, #6166).

The snapshot is an OPTIMISATION, never a dependency: every failure mode must
degrade to "compute inline", which is the behaviour that shipped before it
(and is still what happens on a snapshot miss). So most of these tests assert
that a BROKEN snapshot returns None rather than raising — the opposite of the
usual instinct, and the reason the module swallows exceptions at all.

Mirrors tests/test_activity_snapshot.py (migration 072), the same fix applied
to the other per-worker in-process cache with the same failure shape.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consumer import cross_watch_snapshot as snap  # noqa: E402


class _Row(dict):
    """A mappings()-style row."""


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _Conn:
    """Minimal stand-in for a SQLAlchemy connection.

    `raises` makes execute() blow up, which is how we simulate the table not
    existing yet — the normal state between a deploy and its migration.
    """

    def __init__(self, row=None, raises=None):
        self._row = row
        self._raises = raises
        self.last_sql = None
        self.last_params = None

    def execute(self, stmt, params=None):
        self.last_sql = str(stmt)
        self.last_params = params
        if self._raises:
            raise self._raises
        return _Result(self._row)


def _row(bundle, age_s=10.0, computed_at=None):
    return _Row(
        bundle=bundle,
        computed_at=computed_at or datetime.now(timezone.utc) - timedelta(seconds=age_s),
        age_s=age_s,
    )


_ENTITY = [{"id": 1, "name": "Example Corp", "type": "organization",
            "products": ["wtf", "gov_watch"], "mentions": 12}]


# --------------------------------------------------------------------------
# read_snapshot — every failure returns None, never raises
# --------------------------------------------------------------------------

def test_missing_table_returns_none_instead_of_raising():
    """The migration-not-yet-applied case. A deploy must not 500 on it."""
    conn = _Conn(raises=RuntimeError('relation "wtf.cross_watch_snapshot" does not exist'))
    assert snap.read_snapshot(conn) is None


def test_fresh_snapshot_is_returned():
    got = snap.read_snapshot(_Conn(_row(_ENTITY, age_s=42.0)))
    assert got == _ENTITY


def test_stale_snapshot_is_refused():
    """Past MAX_AGE the reader must fall back, not serve an old page silently."""
    stale = snap.MAX_AGE_S + 60
    assert snap.read_snapshot(_Conn(_row(_ENTITY, age_s=stale))) is None


def test_freshness_is_evaluated_in_sql_not_against_the_local_clock():
    """The writer and reader are different containers/processes.

    Comparing a local clock to a DB timestamp is how a snapshot reads as
    eternally fresh (or eternally stale) after a clock drift, so the age must
    be computed by Postgres. This asserts the SQL actually does that.
    """
    conn = _Conn(_row(_ENTITY))
    snap.read_snapshot(conn)
    sql = conn.last_sql.lower()
    assert "now() - computed_at" in sql.replace("\n", " ")


def test_empty_table_returns_none():
    assert snap.read_snapshot(_Conn(None)) is None


def test_null_bundle_returns_none():
    assert snap.read_snapshot(_Conn(_row(None))) is None


def test_non_list_bundle_is_refused():
    """A malformed bundle (e.g. a dict, or a stray scalar) would break the
    template's iteration — serving junk is worse than being slow."""
    assert snap.read_snapshot(_Conn(_row({"not": "a list"}))) is None


def test_bundle_arriving_as_a_json_string_is_parsed():
    """Some drivers hand back raw json rather than a list."""
    got = snap.read_snapshot(_Conn(_row(json.dumps(_ENTITY))))
    assert got == _ENTITY


def test_unparseable_json_string_returns_none():
    assert snap.read_snapshot(_Conn(_row("{not json"))) is None


def test_caller_can_override_the_age_limit():
    row = _row(_ENTITY, age_s=100.0)
    assert snap.read_snapshot(_Conn(row), max_age_s=50) is None
    assert snap.read_snapshot(_Conn(row), max_age_s=200) is not None


# --------------------------------------------------------------------------
# write_snapshot — a failed write must never break the page
# --------------------------------------------------------------------------

def test_write_failure_is_swallowed_and_reported_false():
    conn = _Conn(raises=RuntimeError("permission denied for table cross_watch_snapshot"))
    assert snap.write_snapshot(conn, _ENTITY, 123) is False


def test_write_serialises_bundle_and_records_duration():
    conn = _Conn()
    assert snap.write_snapshot(conn, _ENTITY, 5470) is True
    assert json.loads(conn.last_params["b"]) == _ENTITY
    assert conn.last_params["d"] == 5470
    # computed_by lets a stuck snapshot be traced back to a container.
    assert conn.last_params["who"]


def test_write_upserts_rather_than_appending():
    """One row, id=1. An unbounded log would need its own pruner — the tier
    that had a policy but no pruner is a documented failure mode here."""
    conn = _Conn()
    snap.write_snapshot(conn, _ENTITY)
    sql = conn.last_sql.lower()
    assert "on conflict (id) do update" in sql.replace("\n", " ")


# --------------------------------------------------------------------------
# Wiring — the caller must actually reach for the shared snapshot
# --------------------------------------------------------------------------

def test_crosswatch_top_reads_before_it_computes():
    """A guard against re-introducing the per-worker-only cache: the snapshot
    module must be imported and its reader called before the heavy GROUP BY
    query, or this whole migration buys nothing.

    The function's own docstring narrates the fix and mentions "GROUP BY" in
    prose before any code runs — searching the raw function text for that
    bare substring would match the docstring, not the SQL, and pass whether
    or not the wiring is actually in the right order. So this drops the
    docstring first and only inspects the executable body.
    """
    src = (Path(__file__).resolve().parents[1] / "consumer" / "routes.py").read_text()
    fn_start = src.index("def _crosswatch_top(")
    fn_end = src.index("\n\n\n", fn_start)
    fn_full = src[fn_start:fn_end]
    doc_end = fn_full.index('"""', fn_full.index('"""') + 3) + 3
    fn_body = fn_full[doc_end:]  # code only, no docstring prose
    assert "cross_watch_snapshot" in fn_full
    assert "read_snapshot" in fn_body
    assert "write_snapshot" in fn_body
    # read must come before the real SQL query, not after
    assert fn_body.index("read_snapshot") < fn_body.index("GROUP BY")
