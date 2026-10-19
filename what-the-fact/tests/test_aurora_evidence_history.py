"""Regression tests for append-only A.U.R.O.R.A. source provenance."""

import hashlib
import json
import pathlib
from datetime import datetime, timezone

from flask import Flask

from ingest.weather.evidence import capture_source_records
from ingest.weather.firms import parse_csv_records, run_firms_capture
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

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result()


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
    assert "ON CONFLICT (version) DO NOTHING" in sql


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
