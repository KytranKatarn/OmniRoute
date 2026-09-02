"""Guards for the precomputed /activity snapshot (migration 072).

The snapshot is an OPTIMISATION, never a dependency: every failure mode must
degrade to "compute inline", which is the behaviour that shipped before it. So
most of these tests assert that a BROKEN snapshot returns None rather than
raising — the opposite of the usual instinct, and the reason the module
swallows exceptions at all.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consumer import activity_snapshot as snap  # noqa: E402


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


# --------------------------------------------------------------------------
# read_snapshot — every failure returns None, never raises
# --------------------------------------------------------------------------

def test_missing_table_returns_none_instead_of_raising():
    """The migration-not-yet-applied case. A deploy must not 500 on it."""
    conn = _Conn(raises=RuntimeError('relation "wtf.activity_snapshot" does not exist'))
    assert snap.read_snapshot(conn) is None


def test_fresh_snapshot_is_returned_with_its_timestamp():
    got = snap.read_snapshot(_Conn(_row({"stats": {"articles_24h": 7}}, age_s=42.0)))
    assert got is not None
    bundle, computed_at = got
    assert bundle["stats"]["articles_24h"] == 7
    # The timestamp must come back too — it is what the page renders as
    # "as of HH:MM", so dropping it would silently hide staleness.
    assert computed_at is not None


def test_stale_snapshot_is_refused():
    """Past MAX_AGE the reader must fall back, not serve an old page silently."""
    stale = snap.MAX_AGE_S + 60
    assert snap.read_snapshot(_Conn(_row({"stats": {}}, age_s=stale))) is None


def test_freshness_is_evaluated_in_sql_not_against_the_local_clock():
    """The refresher and the reader are different containers.

    Comparing a local clock to a DB timestamp is how a snapshot reads as
    eternally fresh (or eternally stale) after a clock drift, so the age must be
    computed by Postgres. This asserts the SQL actually does that — the
    behaviour above would pass just as well with a Python-side comparison.
    """
    conn = _Conn(_row({"stats": {}}))
    snap.read_snapshot(conn)
    sql = conn.last_sql.lower()
    assert "now() - computed_at" in sql.replace("\n", " ")


def test_empty_table_returns_none():
    assert snap.read_snapshot(_Conn(None)) is None


def test_null_bundle_returns_none():
    assert snap.read_snapshot(_Conn(_row(None))) is None


def test_bundle_without_stats_is_refused():
    """A bundle missing `stats` would raise inside the template.

    Serving junk is worse than being slow, so it must be refused here rather
    than blowing up at render time.
    """
    assert snap.read_snapshot(_Conn(_row({"newsroom": {}}))) is None


def test_bundle_arriving_as_a_json_string_is_parsed():
    """Some drivers hand back raw json rather than a dict."""
    got = snap.read_snapshot(_Conn(_row(json.dumps({"stats": {"x": 1}}))))
    assert got is not None and got[0]["stats"]["x"] == 1


def test_unparseable_json_string_returns_none():
    assert snap.read_snapshot(_Conn(_row("{not json"))) is None


def test_caller_can_override_the_age_limit():
    row = _row({"stats": {}}, age_s=100.0)
    assert snap.read_snapshot(_Conn(row), max_age_s=50) is None
    assert snap.read_snapshot(_Conn(row), max_age_s=200) is not None


# --------------------------------------------------------------------------
# write_snapshot — a failed write must never break the page
# --------------------------------------------------------------------------

def test_write_failure_is_swallowed_and_reported_false():
    conn = _Conn(raises=RuntimeError("permission denied for table activity_snapshot"))
    assert snap.write_snapshot(conn, {"stats": {}}, 123) is False


def test_write_serialises_bundle_and_records_duration():
    conn = _Conn()
    assert snap.write_snapshot(conn, {"stats": {"a": 1}}, 5514) is True
    assert json.loads(conn.last_params["b"])["stats"]["a"] == 1
    assert conn.last_params["d"] == 5514
    # computed_by lets a stuck snapshot be traced back to a container.
    assert conn.last_params["who"]


def test_write_survives_a_non_json_native_value():
    """default=str keeps one stray datetime from aborting the whole write."""
    conn = _Conn()
    assert snap.write_snapshot(conn, {"stats": {}, "t": datetime.now(timezone.utc)}, 1) is True
    assert isinstance(json.loads(conn.last_params["b"])["t"], str)


def test_write_upserts_rather_than_appending():
    """One row, id=1. An unbounded log would need its own pruner — the tier
    that had a policy but no pruner is a documented failure mode here."""
    conn = _Conn()
    snap.write_snapshot(conn, {"stats": {}})
    sql = conn.last_sql.lower()
    assert "on conflict (id) do update" in sql.replace("\n", " ")


# --------------------------------------------------------------------------
# The refresher
# --------------------------------------------------------------------------

def test_ingest_run_imports_urllib_request():
    """The refresh POST lives inside a try/except that logs and continues.

    Without the import that block raises NameError on EVERY cycle and refreshes
    NOTHING, while looking like a handled error in the logs — unmonitored while
    appearing monitored. This caught exactly that before it shipped.
    """
    src = (Path(__file__).resolve().parents[1] / "ingest" / "run.py").read_text()
    assert "import urllib.request" in src
    assert "activity-snapshot/refresh" in src


def test_refresh_targets_the_internal_api_not_the_public_consumer():
    """A multi-second job on a public worker starves page loads — which is the
    entire reason wtf-ingest-api exists as a separate service."""
    src = (Path(__file__).resolve().parents[1] / "ingest" / "run.py").read_text()
    assert "wtf-ingest-api:8106" in src


@pytest.mark.parametrize("needle", ["stats_as_of", "as of "])
def test_activity_template_discloses_staleness(needle):
    """A transparency page states when it measured, rather than implying live."""
    tpl = (Path(__file__).resolve().parents[1]
           / "consumer" / "templates" / "activity.html").read_text()
    assert needle in tpl
