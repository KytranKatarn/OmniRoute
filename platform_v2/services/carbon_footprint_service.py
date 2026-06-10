"""Carbon footprint estimation for A.R.C.H.I.E. inference runs.

Reads completed task_execution_log entries for the last hour,
estimates kWh + CO2 per run, and pushes one aggregated event to
the C.R.E.E.D. standalone's environmental pillar.

Grid factor: Canada average = 0.15 kg CO2eq / kWh (Ontario mix, mostly hydro).
"""

import logging
import os

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


def _watts_for_model(model_used: str) -> float:
    base = model_used.split(":")[0].lower() if model_used else ""
    return _GPU_TDP_W if base in {m.split(":")[0] for m in _GPU_MODELS} else _CPU_INFERENCE_W


def _co2_kg(watts: float, duration_ms: int) -> float:
    hours = duration_ms / 1_000 / 3_600
    kwh = watts * hours / 1000.0
    return round(kwh * _CANADA_GRID_KG_CO2_PER_KWH, 8)


# Severity bands are relative to FLEET BASELINE, not absolute energy use —
# normal 24/7 operation must rate 'info', or the environmental pillar punishes
# the cluster for existing (hub baseline ~1.4 kWh/h at ~700 runs/h incl. GPU;
# the previous bands flagged EVERY normal hour as a violation, weight 3/5 →
# pillar score ~40). 'violation' = sustained abnormal draw. Recalibrated
# 2026-06-10 (#3947, #3254 follow-up); tunable via env without deploy.
_WARN_KWH_PER_H = float(os.getenv("CARBON_WARN_KWH_PER_H", "2.5"))
_VIOLATION_KWH_PER_H = float(os.getenv("CARBON_VIOLATION_KWH_PER_H", "5.0"))


def _severity_for_kwh(kwh: float) -> str:
    if kwh > _VIOLATION_KWH_PER_H:
        return "violation"
    if kwh > _WARN_KWH_PER_H:
        return "warning"
    return "info"


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

    severity = _severity_for_kwh(total_kwh)

    summary = {
        "run_count": run_count,
        "total_kwh": total_kwh,
        "total_co2_kg": total_co2,
        "severity": severity,
    }

    # #3958: emit via creed_emit — platform-infra monitor resolves to the
    # default kytran-empowerment tenant, tagged module=Infrastructure.
    from services.creed_emit import emit_event

    ok = emit_event(
        category="environmental",
        severity=severity,
        description=(
            f"Last 1h: {run_count} inference runs · " f"{total_kwh * 1000:.3f} Wh · {total_co2 * 1000:.2f} g CO₂e"
        ),
        event_type="carbon_footprint_report",
        agent_name="A.R.C.H.I.E. Carbon Monitor",
        module="Infrastructure",
        metadata={
            "total_kwh": total_kwh,
            "total_co2_kg": total_co2,
            "run_count": run_count,
            "grid_factor_kg_per_kwh": _CANADA_GRID_KG_CO2_PER_KWH,
            "period": "last_1h",
        },
        timeout=10,
    )
    if ok:
        logger.info("[CarbonJob] Pushed environmental event: %s", summary)

    return summary
