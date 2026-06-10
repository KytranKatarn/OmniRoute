"""Carbon footprint estimation for A.R.C.H.I.E. inference runs.

Reads completed task_execution_log entries for the last hour,
estimates kWh + CO2 per run, and pushes one aggregated event to
the C.R.E.E.D. standalone's environmental pillar.

Grid factor: Canada average = 0.15 kg CO2eq / kWh (Ontario mix, mostly hydro).
"""

import logging
import os

import requests

from database import get_db_cursor

logger = logging.getLogger(__name__)

# TDP estimates (Watts)
_GPU_TDP_W = 120.0  # Quadro M4000
_CPU_INFERENCE_W = 50.0  # incremental CPU load during inference

_CANADA_GRID_KG_CO2_PER_KWH = 0.15

# Models that run on the GPU (VRAM <= 4 GB footprint on the M4000)
_GPU_MODELS = {
    "qwen2.5:1.5b",
    "llama3.2:3b",
    "nomic-embed-text",
    "nomic-embed-text:latest",
}

_CREED_URL = os.getenv("CREED_INGEST_URL", "http://kytran_creed:8086")
_CREED_KEY = os.getenv("CREED_INGEST_KEY", "")


def _watts_for_model(model_used: str) -> float:
    base = model_used.split(":")[0].lower() if model_used else ""
    return _GPU_TDP_W if base in {m.split(":")[0] for m in _GPU_MODELS} else _CPU_INFERENCE_W


def _co2_kg(watts: float, duration_ms: int) -> float:
    hours = duration_ms / 1_000 / 3_600
    kwh = watts * hours / 1000.0
    return round(kwh * _CANADA_GRID_KG_CO2_PER_KWH, 8)


def run_carbon_footprint_job() -> dict:
    """Called by APScheduler hourly. Returns summary dict for logging."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT model_used, duration_ms
                FROM task_execution_log
                WHERE success = true
                  AND created_at >= NOW() - INTERVAL '1 hour'
                  AND duration_ms > 0
                """,
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("[CarbonJob] DB query failed: %s", exc)
        return {"error": str(exc)}

    if not rows:
        return {"run_count": 0, "total_kwh": 0.0, "total_co2_kg": 0.0}

    total_co2 = 0.0
    total_kwh = 0.0
    for row in rows:
        model = row["model_used"] or ""
        dur = int(row["duration_ms"] or 0)
        w = _watts_for_model(model)
        co2 = _co2_kg(w, dur)
        total_co2 += co2
        total_kwh += w * (dur / 1_000 / 3_600) / 1000.0

    total_kwh = round(total_kwh, 6)
    total_co2 = round(total_co2, 6)
    run_count = len(rows)

    if total_kwh > 0.1:
        severity = "violation"
    elif total_kwh > 0.01:
        severity = "warning"
    else:
        severity = "info"

    summary = {
        "run_count": run_count,
        "total_kwh": total_kwh,
        "total_co2_kg": total_co2,
        "severity": severity,
    }

    if not _CREED_KEY:
        logger.info("[CarbonJob] CREED_INGEST_KEY not set — skipping push. Summary: %s", summary)
        return summary

    payload = {
        "event_type": "carbon_footprint_report",
        "source_platform": "archie_platform",
        "agent_id": "archie_carbon_monitor",
        "agent_name": "A.R.C.H.I.E. Carbon Monitor",
        "category": "environmental",
        "severity": severity,
        "description": (
            f"Last 1h: {run_count} inference runs · " f"{total_kwh * 1000:.3f} Wh · {total_co2 * 1000:.2f} g CO₂e"
        ),
        "metadata": {
            "total_kwh": total_kwh,
            "total_co2_kg": total_co2,
            "run_count": run_count,
            "grid_factor_kg_per_kwh": _CANADA_GRID_KG_CO2_PER_KWH,
            "period": "last_1h",
        },
    }
    try:
        resp = requests.post(
            f"{_CREED_URL}/api/v1/events",
            json=payload,
            headers={"Authorization": f"Bearer {_CREED_KEY}"},
            timeout=10,
        )
        if resp.ok:
            logger.info("[CarbonJob] Pushed environmental event: %s", summary)
        else:
            logger.warning("[CarbonJob] CREED push failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("[CarbonJob] CREED push error: %s", exc)

    return summary
