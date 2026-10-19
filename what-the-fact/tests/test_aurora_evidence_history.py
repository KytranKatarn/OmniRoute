"""Regression tests for append-only A.U.R.O.R.A. source provenance."""

import hashlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone

from flask import Flask
import pytest

from ingest.weather.evidence import capture_source_records, record_capture_failure
from ingest.weather.firms import parse_csv_records, run_firms_capture
from ingest.weather import alerts as alerts_ingest
from ingest.weather import cwfis as cwfis_ingest
from ingest.weather import firms as firms_ingest
from consumer import routes
from consumer.routes import _parse_evidence_timestamp

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Result:
    rowcount = 1

    def scalar_one(self):
        return 41


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Result()


class _EvidenceRows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _EvidenceConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    def execute(self, statement, params=None):
        self.statement = str(statement)
        self.params = params
        return _EvidenceRows(self.rows)


class _EvidenceTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


class _EvidenceDB:
    def __init__(self, rows):
        self.connection = _EvidenceConnection(rows)

    def begin(self):
        return _EvidenceTransaction(self.connection)


def test_capture_keeps_source_times_separate_from_retrieval_and_ingest():
    conn = _Connection()
    published = "2026-10-17T18:30:00Z"
    observed = "2026-10-17T19:00:00Z"
    raw_xml = "<alert><sent>%s</sent></alert>" % published

    capture_source_records(
        conn,
        dataset_key="eccc_cap",
        source_url="https://example.invalid/cap",
        started_at=datetime(2026, 10, 17, 19, 2, tzinfo=timezone.utc),
        rows=[
            {
                "source_record_key": "cap-id|Alert|" + published,
                "source_observed_at": observed,
                "source_published_at": published,
                "payload": {"identifier": "cap-id", "sent": published},
                "raw_payload": raw_xml,
            }
        ],
    )

    assert len(conn.calls) == 3
    run_sql, run_params = conn.calls[0]
    assert "retrieved_at" in run_sql and "record_count" in run_sql
    assert run_params["started_at"].isoformat().startswith("2026-10-17T19:02")
    version_sql, version_params = conn.calls[1]
    assert (
        "ON CONFLICT (dataset_key, source_record_key, payload_sha256) "
        "DO NOTHING" in version_sql
    )
    record = json.loads(version_params["records"])[0]
    assert record["source_published_at"] == published
    assert record["source_observed_at"] == observed
    assert record["raw_payload"] == raw_xml
    raw_digest = hashlib.sha256(raw_xml.encode()).hexdigest()
    assert record["payload_sha256"] == raw_digest
    assert "first_retrieved_at" in record
    assert conn.calls[2][1]["run_id"] == 41


def test_empty_capture_is_recorded_without_inventing_source_versions():
    conn = _Connection()
    capture_source_records(
        conn,
        dataset_key="cwfis_hotspot_point",
        source_url="https://example.invalid/wfs",
        started_at=datetime.now(timezone.utc),
        rows=[],
    )
    assert len(conn.calls) == 1
    assert conn.calls[0][1]["count"] == 0


def test_partial_capture_run_remains_distinct_from_complete_empty_run():
    conn = _Connection()
    capture_source_records(
        conn,
        dataset_key="eccc_cap",
        source_url="https://example.invalid/cap",
        started_at=datetime.now(timezone.utc),
        rows=[],
        status="partial",
    )
    assert conn.calls[0][1]["status"] == "partial"


def test_failed_capture_is_recorded_without_error_text_or_source_secret():
    conn = _Connection()
    result = record_capture_failure(
        conn,
        dataset_key="nasa_firms_point",
        source_url="https://example.invalid/[MAP_KEY_REDACTED]/<product>/<area>/1",
        started_at=datetime(2026, 10, 19, 15, tzinfo=timezone.utc),
    )

    assert result == {"run_id": 41, "status": "failed"}
    sql, params = conn.calls[0]
    assert "'failed', 0" in sql
    assert params["dataset_key"] == "nasa_firms_point"
    assert "MAP_KEY_REDACTED" in params["source_url"]
    assert "error" not in sql.lower()


def test_collector_failures_create_feed_capture_attempts_without_storing_errors(monkeypatch):
    class _Engine:
        def __init__(self):
            self.connection = _Connection()

        def begin(self):
            return _EvidenceTransaction(self.connection)

    engine = _Engine()
    monkeypatch.setattr(alerts_ingest, "_run_alerts", lambda *_args: {"error": "fetch failed"})
    monkeypatch.setattr(alerts_ingest, "_heartbeat", lambda *_args: None)
    alerts_ingest.run_aurora_alerts(engine)
    assert engine.connection.calls[-1][1]["dataset_key"] == "eccc_cap"

    engine = _Engine()
    monkeypatch.setattr(cwfis_ingest, "run_hotspot_capture", lambda *_args, **_kwargs: {"error": "empty source"})
    monkeypatch.setattr(cwfis_ingest, "_heartbeat", lambda *_args: None)
    cwfis_ingest.run_aurora_hotspot_capture(engine)
    assert engine.connection.calls[-1][1]["dataset_key"] == "cwfis_hotspot_point"

    engine = _Engine()
    monkeypatch.setattr(cwfis_ingest, "run_firewx_sync", lambda *_args, **_kwargs: {"error": "empty station source"})
    monkeypatch.setattr(cwfis_ingest, "run_fire_sync", lambda *_args, **_kwargs: {})
    cwfis_ingest.run_aurora_cwfis(engine)
    assert engine.connection.calls[0][1]["dataset_key"] == "cwfis_firewx_station_daily"

    engine = _Engine()
    monkeypatch.setattr(firms_ingest, "run_firms_capture", lambda *_args, **_kwargs: {"error": "request failed"})
    monkeypatch.setattr(firms_ingest, "_heartbeat", lambda *_args: None)
    firms_ingest.run_aurora_firms_capture(engine)
    sql, params = engine.connection.calls[-1]
    assert params["dataset_key"] == "nasa_firms_point"
    assert "MAP_KEY_REDACTED" in params["source_url"]
    assert "request failed" not in sql and "request failed" not in str(params)


def test_firewx_retries_transient_empty_feature_collection(monkeypatch):
    responses = iter([
        {"type": "FeatureCollection", "features": []},
        {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"wmo": "71118", "rep_date": "2026-10-17T18:00:00Z", "agency": "MSC"},
        }]},
    ])
    calls = []
    delays = []
    monkeypatch.setattr(cwfis_ingest, "_fetch", lambda layer: (calls.append(layer), next(responses))[1])
    monkeypatch.setattr(cwfis_ingest.time, "sleep", delays.append)

    result = cwfis_ingest.run_firewx_sync(None, dry_run=True)

    assert result["fetched"] == 1
    assert result["parsed"] == 1
    assert calls == ["public:firewx_stns_current"] * 2
    assert delays == [2.0]


def test_firewx_fails_closed_after_all_empty_feature_attempts(monkeypatch):
    calls = []
    delays = []
    monkeypatch.setattr(
        cwfis_ingest,
        "_fetch",
        lambda layer: (calls.append(layer), {"type": "FeatureCollection", "features": []})[1],
    )
    monkeypatch.setattr(cwfis_ingest.time, "sleep", delays.append)

    result = cwfis_ingest.run_firewx_sync(None, dry_run=True)

    assert "0 features after 3 attempts" in result["error"]
    assert calls == ["public:firewx_stns_current"] * 3
    assert delays == [2.0, 6.0]


def test_firewx_does_not_retry_fetch_errors(monkeypatch):
    calls = []
    delays = []

    def fail_fetch(layer):
        calls.append(layer)
        raise RuntimeError("HTTP Error 404: Not Found")

    monkeypatch.setattr(cwfis_ingest, "_fetch", fail_fetch)
    monkeypatch.setattr(cwfis_ingest.time, "sleep", delays.append)

    result = cwfis_ingest.run_firewx_sync(None, dry_run=True)

    assert result == {"error": "firewx fetch failed: HTTP Error 404: Not Found"}
    assert calls == ["public:firewx_stns_current"]
    assert delays == []


def test_cwfis_point_payload_retains_geometry_and_source_identity():
    feature = {
        "type": "Feature",
        "id": "hotspot.123",
        "geometry": {"type": "Point", "coordinates": [-110.2, 52.8]},
        "properties": {
            "agency": "AB",
            "rep_date": "2026-10-17T18:00:00Z",
            "frp": 4.2,
            "confidence": "nominal",
        },
    }
    conn = _Connection()
    capture_source_records(
        conn,
        dataset_key="cwfis_hotspot_point",
        source_url="https://example.invalid/wfs",
        started_at=datetime.now(timezone.utc),
        rows=[
            {
                "source_record_key": feature["id"],
                "source_observed_at": feature["properties"]["rep_date"],
                "payload": feature,
            }
        ],
    )
    stored = json.loads(conn.calls[1][1]["records"])[0]
    assert stored["payload"]["geometry"] == feature["geometry"]
    assert stored["source_record_key"] == "hotspot.123"
    assert stored["source_observed_at"] == "2026-10-17T18:00:00Z"


def test_firms_csv_preserves_original_fields_and_utc_acquisition_time():
    rows = parse_csv_records(
        "VIIRS_NOAA20_NRT",
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
        "satellite,confidence,frp\n"
        "52.8,-110.2,302.1,0.4,0.4,2026-10-17,2217,N,nominal,6.2\n",
    )
    assert len(rows) == 1
    record = rows[0]
    assert record["source_observed_at"] == datetime(
        2026, 10, 17, 22, 17, tzinfo=timezone.utc
    )
    assert record.get("source_published_at") is None
    assert record["payload"]["detection"]["frp"] == "6.2"
    assert record["payload"]["evidence_class"] == "satellite_thermal_anomaly"


def test_firms_missing_map_key_is_disabled_without_database_access(
    monkeypatch,
):
    monkeypatch.delenv("NASA_FIRMS_MAP_KEY", raising=False)
    result = run_firms_capture(engine=None)
    assert result == {
        "disabled": True,
        "reason": "NASA_FIRMS_MAP_KEY is not configured",
    }


def test_evidence_cutoff_requires_timezone_and_normalizes_to_utc():
    assert _parse_evidence_timestamp("2026-10-17T16:00:00-06:00") == datetime(
        2026, 10, 17, 22, 0, tzinfo=timezone.utc
    )
    assert _parse_evidence_timestamp("2026-10-17T22:00:00Z") == datetime(
        2026, 10, 17, 22, 0, tzinfo=timezone.utc
    )
    assert _parse_evidence_timestamp("2026-10-17T22:00:00") is False


def test_evidence_api_rejects_unknown_datasets_before_database_access(
    monkeypatch,
):
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    monkeypatch.setattr(routes, "_api_rate_check", lambda: None)

    response = app.test_client().get("/api/weather/evidence?dataset=internal")

    assert response.status_code == 400
    assert response.get_json()["error"] == "unsupported dataset"


def _evidence_api(monkeypatch, rows=()):
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    db = _EvidenceDB(list(rows))
    monkeypatch.setattr(routes, "_api_rate_check", lambda: None)
    monkeypatch.setattr(routes, "_db", lambda: db)
    return app.test_client(), db


def test_evidence_api_bounds_require_a_complete_valid_point_query(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    monkeypatch.setattr(routes, "_api_rate_check", lambda: None)
    monkeypatch.setattr(routes, "_db", lambda: pytest.fail("database should not be queried"))

    partial = app.test_client().get("/api/weather/evidence?west=-111&south=50")
    inverted = app.test_client().get(
        "/api/weather/evidence?west=-110&east=-111&south=50&north=53"
    )
    unsupported = app.test_client().get(
        "/api/weather/evidence?dataset=eccc_cap&west=-111&east=-109&south=50&north=53"
    )

    assert partial.status_code == 400
    assert inverted.status_code == 400
    assert unsupported.status_code == 400


def test_evidence_api_binds_search_time_and_geographic_filters(monkeypatch):
    client, db = _evidence_api(monkeypatch)
    response = client.get(
        "/api/weather/evidence?dataset=nasa_firms_point&q=NOAA_20&"
        "observed_after=2026-10-17T10:00:00-06:00&"
        "observed_before=2026-10-18T10:00:00-06:00&"
        "available_before=2026-10-18T16:00:00-06:00&"
        "west=-111&south=50&east=-109&north=53&limit=20"
    )

    assert response.status_code == 200
    assert db.connection.params["dataset"] == "nasa_firms_point"
    assert db.connection.params["search_pattern"] == "%NOAA!_20%"
    assert db.connection.params["west"] == -111
    assert db.connection.params["east"] == -109
    assert db.connection.params["point_datasets_only"] is False
    assert db.connection.params["observed_after"] == datetime(
        2026, 10, 17, 16, 0, tzinfo=timezone.utc
    )
    assert db.connection.params["available_before"] == datetime(
        2026, 10, 18, 22, 0, tzinfo=timezone.utc
    )
    assert "source_latitude BETWEEN :south AND :north" in db.connection.statement
    assert "ILIKE :search_pattern ESCAPE '!'" in db.connection.statement
    assert "NOAA_20" not in db.connection.statement


def test_evidence_api_bounds_unfiltered_archive_search_to_point_feeds(monkeypatch):
    client, db = _evidence_api(monkeypatch)
    response = client.get(
        "/api/weather/evidence?west=-111&south=50&east=-109&north=53"
    )

    assert response.status_code == 200
    assert db.connection.params["dataset"] is None
    assert db.connection.params["point_datasets_only"] is True


def test_evidence_api_returns_cap_lifecycle_as_page_scoped_projection(monkeypatch):
    client, _db = _evidence_api(monkeypatch, [{
        "id": 7,
        "dataset_key": "eccc_cap",
        "source_record_key": "cap-7|Update|2026-10-17T18:00:00Z",
        "source_url": "https://example.invalid/cap/update",
        "payload_sha256": "a" * 64,
        "source_observed_at": None,
        "source_published_at": "2026-10-17T18:00:00Z",
        "operational_received_at": None,
        "first_retrieved_at": "2026-10-17T18:01:00Z",
        "ingested_at": "2026-10-17T18:01:01Z",
        "payload": {"identifier": "cap-7", "msg_type": "Update", "sent_utc": "2026-10-17T18:00:00Z"},
        "source_latitude": None,
        "source_longitude": None,
    }])

    response = client.get("/api/weather/evidence?dataset=eccc_cap")
    body = response.get_json()

    assert response.status_code == 200
    assert body["cap_lifecycle"]["scope"] == "matched_result_page"
    assert body["cap_lifecycle"]["groups"][0]["identifier"] == "cap-7"
    assert body["cap_lifecycle"]["groups"][0]["versions"][0]["msg_type"] == "Update"
    assert body["evidence"][0]["source_record_key"] == "cap-7|Update|2026-10-17T18:00:00Z"


def test_evidence_api_uses_stable_cursor_and_returns_next_page_token(monkeypatch):
    client, db = _evidence_api(monkeypatch, [
        {"id": 8, "dataset_key": "eccc_cap", "source_record_key": "cap-b",
         "source_sort_at": datetime(2026, 10, 17, 18, tzinfo=timezone.utc),
         "payload": {"identifier": "cap-b"}},
        {"id": 7, "dataset_key": "eccc_cap", "source_record_key": "cap-a",
         "source_sort_at": datetime(2026, 10, 17, 17, tzinfo=timezone.utc),
         "payload": {"identifier": "cap-a"}},
    ])

    first = client.get("/api/weather/evidence?dataset=eccc_cap&limit=1")
    body = first.get_json()
    assert first.status_code == 200
    assert body["has_more"] is True
    assert body["next_cursor"]
    assert "source_sort_at < :cursor_time" in db.connection.statement
    assert "(dataset_key, source_record_key, id) >" in db.connection.statement

    client.get("/api/weather/evidence?dataset=eccc_cap&limit=1&cursor=" + body["next_cursor"])
    assert db.connection.params["cursor_time"] == datetime(
        2026, 10, 17, 18, tzinfo=timezone.utc
    )
    assert db.connection.params["cursor_key"] == "cap-b"
    assert db.connection.params["cursor_id"] == 8
    changed_filter = client.get(
        "/api/weather/evidence?dataset=eccc_cap&limit=1&q=changed&cursor="
        + body["next_cursor"]
    )
    assert changed_filter.status_code == 400


def test_evidence_api_rejects_malformed_cursor_shape(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    monkeypatch.setattr(routes, "_api_rate_check", lambda: None)
    monkeypatch.setattr(routes, "_db", lambda: pytest.fail("database should not be queried"))

    response = app.test_client().get("/api/weather/evidence?cursor=W10")
    assert response.status_code == 400


def test_cap_lifecycle_endpoint_pages_all_matching_versions(monkeypatch):
    client, db = _evidence_api(monkeypatch, [
        {"id": 10, "dataset_key": "eccc_cap", "source_record_key": "cap-x|Update",
         "source_sort_at": datetime(2026, 10, 17, 18, tzinfo=timezone.utc),
         "payload": {"identifier": "cap-x", "msg_type": "Update"}},
        {"id": 11, "dataset_key": "eccc_cap", "source_record_key": "cap-x|Cancel",
         "source_sort_at": datetime(2026, 10, 17, 19, tzinfo=timezone.utc),
         "payload": {"identifier": "cap-x", "msg_type": "Cancel"}},
    ])

    response = client.get(
        "/api/weather/evidence/cap-lifecycle?identifier=cap-x&limit=1&"
        "available_before=2026-10-18T00:00:00Z"
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["scope"] == "all_retained_versions_for_identifier_with_filters"
    assert body["count"] == 1 and body["has_more"] is True
    assert body["versions"][0]["payload"]["msg_type"] == "Update"
    assert db.connection.params["identifier"] == "cap-x"
    assert "payload->>'identifier' = :identifier" in db.connection.statement
    assert "first_retrieved_at <= :available_before" in db.connection.statement


def test_coverage_endpoint_reports_archive_and_attempt_health_without_error_details(monkeypatch):
    client, db = _evidence_api(monkeypatch, [
        {"dataset_key": "eccc_cap", "retained_versions": 0, "runs_7d": 0,
         "failures_7d": 0, "empty_successes_7d": 0, "last_attempt_status": None},
    ])

    response = client.get("/api/weather/evidence/coverage")
    body = response.get_json()
    cap = next(feed for feed in body["feeds"] if feed["dataset_key"] == "eccc_cap")
    assert response.status_code == 200
    assert cap["archive_state"] == "no_archive_coverage"
    assert "last attempt" not in cap
    assert "FROM wtf.aurora_capture_run" in db.connection.statement
    assert "FROM wtf.aurora_source_version" in db.connection.statement
    assert "raw_payload" not in db.connection.statement
    assert "error" not in db.connection.statement


def test_cap_lifecycle_groups_versions_without_replacing_messages():
    rows = [
        {
            "id": 3, "dataset_key": "eccc_cap", "source_record_key": "cap-1|Cancel|2026-10-17T20:00:00Z",
            "source_published_at": "2026-10-17T20:00:00Z", "source_observed_at": None,
            "payload": {"identifier": "cap-1", "msg_type": "Cancel"},
        },
        {
            "id": 2, "dataset_key": "eccc_cap", "source_record_key": "cap-1|Update|2026-10-17T18:00:00Z",
            "source_published_at": "2026-10-17T18:00:00Z", "source_observed_at": None,
            "payload": {"identifier": "cap-1", "msg_type": "Update"},
        },
        {
            "id": 1, "dataset_key": "eccc_cap", "source_record_key": "cap-1|Alert|2026-10-17T16:00:00Z",
            "source_published_at": "2026-10-17T16:00:00Z", "source_observed_at": None,
            "payload": {"identifier": "cap-1", "msg_type": "Alert"},
        },
    ]

    lifecycle = routes._cap_lifecycle(rows)

    assert len(lifecycle) == 1
    assert lifecycle[0]["identifier"] == "cap-1"
    assert lifecycle[0]["scope"] == "matched_result_page"
    assert [v["msg_type"] for v in lifecycle[0]["versions"]] == [
        "Alert", "Update", "Cancel"
    ]


def test_evidence_migration_is_append_only_and_tracks_its_ledger_entry():
    sql = (ROOT / "migrations" / "106_aurora_evidence_history.sql").read_text()
    for column in (
        "source_observed_at",
        "source_published_at",
        "operational_received_at",
        "first_retrieved_at",
        "ingested_at",
        "raw_payload",
    ):
        assert column in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE" in sql
    assert "'106', '106_aurora_evidence_history.sql'" in sql


def test_weather_history_ui_tracks_provenance_clocks_and_pages_results():
    template = (ROOT / "consumer" / "templates" / "weather.html").read_text()
    section = template.split('id="aurora-evidence-history"', 1)[1].split(
        "{% if aurora_map %}", 1
    )[0]

    assert '"/api/weather/evidence?' in section
    assert "source_observed_at" in section
    assert "source_published_at" in section
    assert "first_retrieved_at" in section
    assert "operational_received_at" in section
    assert "available_before" in section
    assert "Load older records" in section
    assert "thermal anomaly is not, by itself, a confirmed fire" in section
    assert "textContent" in section


def test_weather_history_maps_only_valid_source_coordinates():
    template = (ROOT / "consumer" / "templates" / "weather.html").read_text()
    assert 'data-layer="history"' in template
    assert 'id: "history"' in template
    assert "WTFHistoricalEvidenceMapPoints" in template
    assert "coordinate plot" not in template.lower()

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    start = template.index("  function coordinates(row) {")
    end = template.index("\n  function mapPoints()", start)
    coordinates_fn = template[start:end]
    setup = """
      %(coordinates)s
      var feature = {payload:{geometry:{type:"Point",coordinates:[-110.2,52.8]}}};
      var firms = {payload:{detection:{latitude:"52.9",longitude:"-110.3"}}};
      var missing = {payload:{detection:{latitude:null,longitude:null}}};
      var invalid = {payload:{detection:{latitude:"91",longitude:"-110"}}};
      globalThis.__result = [coordinates(feature), coordinates(firms),
                             coordinates(missing), coordinates(invalid)];
    """ % {"coordinates": coordinates_fn}
    harness = """
      const vm = require('vm');
      const ctx = {};
      vm.createContext(ctx);
      vm.runInContext(%(setup)s, ctx);
      console.log(JSON.stringify(ctx.__result));
    """ % {"setup": json.dumps(setup)}
    result = subprocess.run([node, "-e", harness], capture_output=True,
                            text=True, check=False, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [[52.8, -110.2], [52.9, -110.3], None, None]


def test_weather_history_search_ui_exposes_bounded_filters_and_cap_chain():
    template = (ROOT / "consumer" / "templates" / "weather.html").read_text()

    for control in (
        "wtf-wx-history-query", "wtf-wx-history-observed-after",
        "wtf-wx-history-observed-before", "wtf-wx-history-west",
        "wtf-wx-history-south", "wtf-wx-history-east", "wtf-wx-history-north",
        "wtf-wx-history-coverage", "wtf-wx-history-export-json",
        "wtf-wx-history-export-csv", "Load full captured history",
        "lifecycle_filter_keys", "search_text_and_geographic_bounds_apply_to_lifecycle_versions",
    ):
        assert control in template
    for api_contract in (
        '[observedAfter, "observed_after"]', '[observedBefore, "observed_before"]',
        '[cutoff, "available_before"]', 'params.set("q"',
        'body.cap_lifecycle',
        "CAP message lifecycle", "Original alert text",
    ):
        assert api_contract in template
    assert '"matched_result_page"' in (ROOT / "consumer" / "routes.py").read_text()
    assert "Source time before (UTC)" in template
    assert "filters preserve the archive cutoff and source-time window" in template
    routes_source = (ROOT / "consumer" / "routes.py").read_text()
    assert '@bp.get("/api/weather/evidence/cap-lifecycle")' in routes_source
    assert '@bp.get("/api/weather/evidence/coverage")' in routes_source
