"""Residency sampler (#5273/#6106): actual size_vram per loaded model, persisted.

The router's placement log says what it DECIDED; a CPU-stranded runner makes the
decision ("gpu") and the outcome (size_vram = 0) disagree. These tests pin the row
shaping, the fail-safe contract, and that the existing lifecycle job feeds it.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import residency_sampler as rs  # noqa: E402


def _snap(*models):
    return {"models": [dict(m) for m in models]}


GPU = {"name": "qwen2.5:7b", "vram_gb": 4.59, "ram_gb": 4.59, "seconds_remaining": 3300}
CPU = {"name": "qwen2.5:7b", "vram_gb": 0.0, "ram_gb": 4.29, "seconds_remaining": 1200}
PINNED = {"name": "qwen25-classify:latest", "vram_gb": 0.0, "ram_gb": 0.97, "seconds_remaining": 900}


class TestBuildRows:
    def test_one_row_per_model_with_all_fields(self):
        rows = rs.build_rows(_snap(GPU), node_name="hub")
        assert rows == [("hub", "qwen2.5:7b", 4.59, 4.59, 3300, None)]

    def test_empty_snapshot_yields_no_rows(self):
        assert rs.build_rows({}) == []
        assert rs.build_rows(_snap()) == []

    def test_nameless_entry_is_skipped(self):
        assert rs.build_rows(_snap({"vram_gb": 1.0})) == []

    def test_pin_lookup_only_consulted_for_zero_vram_models(self):
        calls = []

        def pinned(model):
            calls.append(model)
            return True

        rs.build_rows(_snap(GPU, PINNED), cpu_pinned=pinned)
        assert calls == ["qwen25-classify:latest"], "a GPU-resident model must never cost a Modelfile lookup"

    def test_pin_result_is_recorded(self):
        rows = rs.build_rows(_snap(PINNED, CPU), cpu_pinned=lambda m: m.startswith("qwen25-classify"))
        by_model = {r[1]: r[5] for r in rows}
        assert by_model["qwen25-classify:latest"] is True
        assert by_model["qwen2.5:7b"] is False

    def test_unknown_pin_is_null_not_false(self):
        def boom(_m):
            raise OSError("down")

        rows = rs.build_rows(_snap(CPU), cpu_pinned=boom)
        assert rows[0][5] is None

    def test_missing_remaining_is_null(self):
        rows = rs.build_rows(_snap({"name": "m", "vram_gb": 1, "ram_gb": 1}))
        assert rows[0][4] is None


class TestRecordSamples:
    def test_never_raises_and_warns_when_the_db_is_down(self, caplog):
        with mock.patch("database.get_db_cursor", side_effect=RuntimeError("no db"), create=True):
            with mock.patch.object(rs, "_default_cpu_pinned", return_value=None):
                with caplog.at_level("WARNING"):
                    assert rs.record_samples(_snap(GPU)) == 0
        assert any("DROPPED" in r.message for r in caplog.records), "a dropped sample must be visible, not silent"

    def test_writes_all_rows_in_one_statement(self):
        executed = []

        class Cur:
            def executemany(self, sql, rows):
                executed.append((sql, list(rows)))

        @contextlib.contextmanager
        def fake_cursor(commit=False):
            yield (object(), Cur())

        with mock.patch("database.get_db_cursor", fake_cursor, create=True):
            with mock.patch.object(rs, "_default_cpu_pinned", return_value=False):
                n = rs.record_samples(_snap(GPU, CPU))
        assert n == 2
        sql, rows = executed[0]
        assert "model_residency_samples" in sql
        assert sql.count("%s") == len(rows[0])

    def test_empty_snapshot_touches_nothing(self):
        with mock.patch("database.get_db_cursor", side_effect=AssertionError("must not connect"), create=True):
            assert rs.record_samples(_snap()) == 0


def test_lifecycle_job_feeds_the_sampler():
    """Source-level: the existing 5-min job must call record_samples on its snapshot."""
    src = (Path(__file__).resolve().parents[1] / "services" / "agent_jobs.py").read_text()
    body = src.split("def ollama_lifecycle_telemetry", 1)[1].split("def check_understaffed_capabilities", 1)[0]
    assert "record_samples(snap)" in body
    assert body.index("snapshot_ollama_lifecycle()") < body.index("record_samples(snap)")


def test_table_is_wired_into_retention():
    import services.dispatch_retention_service as drs

    spec = drs._TABLES["model_residency_samples"]
    assert spec["age_col"] == "sampled_at"
    assert spec["keep_key"] in drs.DEFAULTS
    assert "retention:model_residency_samples:keep_days" in drs._PS_KEYS
