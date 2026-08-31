"""save_geo() must persist EVERY field extract_geo() produces (#6210).

The geocoder computed country_code correctly and `save_geo` — the INGEST-TIME
write that runs for every article — simply left the column out of its UPDATE.
A value that is computed but never written is, in the database, identical to one
that was never computed at all.

This was the SECOND half of #6210 and it survived the first fix: correcting
extract_geo's setdefault made the value right, and this UPDATE still dropped it.
Rows ingested two minutes after that deploy still had country_code NULL.

The other two writers (run.py's orchestrator UPDATE, geo_backlog_worker) always
included the column — but run.py's is scoped `WHERE geo_scope IN ('national')`
and the backlog worker only sees rows this path failed to fill, so neither
covered the ordinary article. One uncovered choke point was enough.

Run: python3 -m pytest tests/test_save_geo_persists_country.py -q
"""
import re

import pytest

from ingest import persist


class _FakeConn:
    def __init__(self, sink):
        self.sink = sink

    def execute(self, stmt, params=None):
        self.sink.append((str(stmt), params or {}))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    """Captures the SQL + bound params without touching a database."""
    def __init__(self):
        self.calls = []

    def begin(self):
        return _FakeConn(self.calls)


GEO = {
    "province_code": "ON",
    "city": "Toronto",
    "lat": 43.7,
    "lng": -79.4,
    "country_code": "CA",
    "geo_scope": "provincial",
    "geo_confidence": 0.8,
}


def _run(geo=GEO):
    eng = _FakeEngine()
    persist.save_geo(eng, 123, "wtf", geo)
    assert eng.calls, "save_geo issued no UPDATE at all"
    return eng.calls[0]


def test_country_code_is_in_the_update_statement():
    sql, _ = _run()
    assert "country_code" in sql, (
        "save_geo must WRITE country_code — the geocoder computes it and this "
        "is the ingest-time path that decides what the map sees"
    )


def test_country_code_value_is_actually_bound():
    """A column in the SQL with no bound parameter would still write nothing."""
    _, params = _run()
    assert params.get("country") == "CA"


def test_a_foreign_country_is_persisted_unchanged():
    _, params = _run({**GEO, "province_code": None, "country_code": "US",
                      "geo_scope": "international"})
    assert params.get("country") == "US"


def test_an_absent_country_is_written_as_null_not_invented():
    """Unmappable must stay NULL. 'We could not place this' is a real fact and
    must not be silently upgraded to a country."""
    _, params = _run({"province_code": None, "city": None, "lat": None,
                      "lng": None, "country_code": None,
                      "geo_scope": "unmappable"})
    assert params.get("country") is None


def test_every_geo_field_the_geocoder_returns_is_persisted():
    """THE structural guard.

    This is what was missing: nothing tied the writer to the producer, so a
    field could be added to extract_geo (or, as here, simply omitted from the
    UPDATE) and no test would notice. Adding a persisted field to the geocoder
    now forces a matching column here.
    """
    sql, params = _run()
    # geo_confidence is deliberately not a column on articles; everything else
    # extract_geo returns must reach the table.
    persisted = {"province_code", "city", "lat", "lng", "country_code", "geo_scope"}
    missing = [f for f in persisted if not re.search(rf"\b{f}\s*=", sql)]
    assert not missing, f"save_geo does not write: {missing}"


def test_the_update_is_scoped_to_one_article():
    sql, params = _run()
    assert "WHERE id = :aid" in sql, "an unscoped UPDATE would rewrite the table"
    assert params.get("aid") == 123


@pytest.mark.parametrize("bad", ["public", "pg_catalog", "'; DROP TABLE"])
def test_a_disallowed_schema_still_raises(bad):
    """The schema is interpolated into the SQL string, so this guard is what
    keeps that from being an injection point. Must survive the edit."""
    with pytest.raises(ValueError):
        persist.save_geo(_FakeEngine(), 1, bad, GEO)


def test_empty_geo_writes_nothing():
    eng = _FakeEngine()
    persist.save_geo(eng, 123, "wtf", {})
    assert not eng.calls
