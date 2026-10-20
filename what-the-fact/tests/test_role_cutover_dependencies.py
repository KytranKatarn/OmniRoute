"""Runtime DML and service-surface checks; no external network or database."""
from contextlib import contextmanager
from datetime import date
import re
from types import SimpleNamespace

import pytest

from consumer.app import create_ingest_app
from ingest.gov import gic_appointments
from ingest import securities_issuer_ingest
from ingest.market import boc_rates, statcan_indicators, fiscal_federal, fx_rates, oda_canada


class DmlOnlyEngine:
    """A runtime that rejects schema/owner operations instead of silently accepting them."""
    def __init__(self):
        self.statements = []

    @contextmanager
    def begin(self):
        yield self

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if re.search(r"\b(CREATE|ALTER|DROP|TRUNCATE|GRANT)\b", sql, re.I):
            raise PermissionError("runtime cannot perform DDL")
        self.statements.append((sql, params))
        return SimpleNamespace(rowcount=1)


@pytest.mark.parametrize("module,method,row,table", [
    (boc_rates, "_upsert", {"decision_date": date(2026, 1, 1), "rate_pct": 2.5, "change_bps": 0, "press_release_url": None}, "boc_rate_decisions"),
    (statcan_indicators, "_upsert", {"indicator_key": "cpi", "ref_date": date(2026, 1, 1), "value": 1, "vector_id": 1, "table_id": "test", "release_time": None}, "economic_indicators"),
    (fiscal_federal, "_upsert", {"ref_year": 2025, "item_key": "revenue", "value_millions": 1, "vector_id": 1, "source_table": "test", "derived": False, "release_time": None}, "fiscal_federal_annual"),
    (fiscal_federal, "_upsert_quarterly", {"ref_quarter": date(2026, 1, 1), "item_key": "revenue", "value_millions": 1, "vector_id": 1, "source_table": "test", "release_time": None}, "fiscal_federal_quarterly"),
    (fx_rates, "_upsert", {"rate_date": date(2026, 1, 1), "usd_cad": 1.3}, "fx_rates"),
    (oda_canada, "_upsert", {"ref_year": 2025, "item_key": "oda", "value": 1, "unit": "test", "source": "test"}, "oda_canada_annual"),
    (gic_appointments, "_upsert", {"pc_number": "test", "oic_date": date(2026, 1, 1), "department": "test", "subject": "test", "precis": "test", "oic_url": None, "appointee_name": "test", "organization": "test", "action_type": "appointment"}, "gic_appointments"),
])
def test_preprovisioned_ingest_needs_only_dml(module, method, row, table):
    engine = DmlOnlyEngine()
    assert getattr(module, method)(engine, [row]) == 1
    assert len(engine.statements) == 1
    sql, params = engine.statements[0]
    assert "INSERT INTO" in sql and table in sql
    assert "ON CONFLICT" in sql and params == row


def test_securities_run_needs_only_dml(monkeypatch):
    engine = DmlOnlyEngine()
    monkeypatch.setattr(securities_issuer_ingest, "_engine", lambda: engine)
    monkeypatch.setattr(securities_issuer_ingest, "fetch_tsx_issuers",
                        lambda: [("Issuer", f"T{i}", "TSX60") for i in range(50)])
    assert securities_issuer_ingest.run()["upserted"] == 1
    assert len(engine.statements) == 1
    assert "INSERT INTO securities.issuers" in engine.statements[0][0]


def test_ingest_service_has_only_its_intended_surface():
    app = create_ingest_app()
    assert {r.rule for r in app.url_map.iter_rules()} == {
        "/api/internal/entity-graph/ingest", "/api/internal/entity-graph/companies",
        "/health", "/version",
    }
    with app.test_client() as client:
        assert client.get("/health").json == {"status": "ok", "scope": "process"}
        assert client.get("/version").json["product"] == "wtf_ingest_api"
        for path in ("/", "/news", "/admin/dedup", "/api/keys", "/billing", "/static/test"):
            assert client.get(path).status_code == 404


def test_ingest_service_retains_fail_closed_auth(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    client = create_ingest_app().test_client()
    assert client.post("/api/internal/entity-graph/ingest", json={}).status_code == 503
    monkeypatch.setenv("INTERNAL_API_KEY", "test-key")
    assert client.post("/api/internal/entity-graph/ingest", json={}).status_code == 401
    assert client.get("/api/internal/entity-graph/companies").status_code == 401
    # Correct authentication reaches request validation without touching a DB.
    assert client.post("/api/internal/entity-graph/ingest", json={},
                       headers={"X-Internal-Key": "test-key"}).status_code == 400


def test_public_factory_keeps_its_existing_routes(monkeypatch, tmp_path):
    from consumer.app import create_app
    monkeypatch.setenv("FLASK_SECRET_KEY", "synthetic-test-key")
    monkeypatch.setattr("consumer.db._DB_PATH", str(tmp_path / "billing.db"))
    app = create_app()
    paths = {r.rule for r in app.url_map.iter_rules()}
    assert {"/news", "/admin/dedup", "/api/internal/entity-graph/ingest", "/version"} <= paths


def test_bootstrap_migration_meets_guarded_runner_contract():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("bootstrap_guard", root / "scripts/migrations_apply.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    sql = (root / "migrations/107_ingest_schema_bootstrap.sql").read_text()
    assert guard.problems("107", sql) == []
