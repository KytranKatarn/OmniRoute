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


# Non-LLM model sentinels (mirror the Token Economy exclude-list in
# code_health_routes.py + telemetry_writer.MARKER_MODEL_SENTINEL). Rows with
# these "models" are NOT inference — orchestration/job MARKERS (bridge-managed /
# internal), web scraping (browser), image gen (comfyui), or embeddings (batch /
# *embed*). Their duration is cycle/job wall-clock, NOT model runtime, so a
# watts x duration estimate would FABRICATE carbon. CO2/Wh are n/a (None) for them.
_NON_LLM_MODELS = {"bridge-managed", "internal", "batch", "browser", "comfyui", ""}


def _is_llm_model(model_used) -> bool:
    """True only for a real LLM-inference model — the set that legitimately burns
    watts per token. Markers/scrape/image/embeddings return False (carbon n/a)."""
    m = (model_used or "").strip().lower()
    return bool(m) and m not in _NON_LLM_MODELS and "embed" not in m


def _co2_kg(watts: float, duration_ms: int) -> float:
    hours = duration_ms / 1_000 / 3_600
    kwh = watts * hours / 1000.0
    return round(kwh * _CANADA_GRID_KG_CO2_PER_KWH, 8)


def co2_g_for(model_used, duration_ms):
    """Grams CO2 for ONE dispatch (local-cluster energy only). Same methodology
    as the hourly carbon job: _watts_for_model x duration x Canada grid factor.
    Reused by the DHQ Dispatch/TRAFFIC views so their CO2 reconciles with the
    C.R.E.E.D. environmental pillar. Returns **None (n/a)** for non-LLM rows
    (orchestration/job markers, scrape, embeddings — their duration is cycle
    wall-clock, not model runtime, so a carbon estimate would be fabricated) or
    missing duration."""
    if not _is_llm_model(model_used) or not duration_ms:
        return None
    return round(_co2_kg(_watts_for_model(model_used or ""), int(duration_ms)) * 1000.0, 4)


def energy_wh_for(model_used, duration_ms):
    """Watt-hours for ONE dispatch = watts(model) x duration. The meaningful
    per-row 'power used' figure (basis for CO2). Same _watts_for_model basis as
    co2_g_for(), so feed/history energy reconciles with the CREED carbon pillar.
    Returns **None (n/a)** for non-LLM rows (markers/scrape/embeddings) or
    missing/zero duration — they did no inference, so there is no model runtime."""
    if not _is_llm_model(model_used) or not duration_ms:
        return None
    return round(_watts_for_model(model_used or "") * int(duration_ms) / 3_600_000.0, 4)


# GPU model base names (derived once) so the SQL fragment below can't drift
# from _GPU_MODELS / _watts_for_model.
_GPU_BASES = sorted({m.split(":")[0] for m in _GPU_MODELS})


def co2_g_sql(model_col: str = "model_used", dur_col: str = "duration_ms", worker_col: str = "worker_type") -> str:
    """SQL fragment (grams CO2 per row) for SUM() aggregations — IDENTICAL
    methodology to co2_g_for(), built from the python constants. Returns **NULL**
    (skipped by SUM) for non-inference rows so they never inflate a CO2 total:
    cloud/contractor (worker_type='contract' — not our cluster) AND non-LLM model
    sentinels (markers bridge-managed/internal, scrape browser, image comfyui,
    embeddings batch/*embed* — their duration is cycle wall-clock, not model
    runtime). co2_g = watts * ms * grid / 3_600_000 for real LLM rows only."""
    bases = ", ".join("'%s'" % b for b in _GPU_BASES)
    sentinels = ", ".join("'%s'" % s for s in sorted(_NON_LLM_MODELS) if s)
    return (
        "(CASE "
        "WHEN {w} = 'contract' THEN NULL "
        "WHEN lower(COALESCE({m}, '')) IN ({s}) THEN NULL "
        "WHEN lower(COALESCE({m}, '')) LIKE '%%embed%%' THEN NULL "
        "WHEN COALESCE({m}, '') = '' THEN NULL "
        "ELSE (CASE WHEN split_part(lower(COALESCE({m}, '')), ':', 1) IN ({b}) "
        "THEN {gpu} ELSE {cpu} END) * COALESCE({d}, 0) * {grid} / 3600000.0 END)"
    ).format(
        w=worker_col,
        m=model_col,
        s=sentinels,
        b=bases,
        gpu=_GPU_TDP_W,
        cpu=_CPU_INFERENCE_W,
        d=dur_col,
        grid=_CANADA_GRID_KG_CO2_PER_KWH,
    )


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


def per_agent_efficiency(hours: int = 24):
    """P2-D (#381): per-AGENT energy / CO2 / token efficiency over the last ``hours``, using the SAME
    methodology as the hourly carbon job (_watts_for_model x duration -> Canada grid factor). Aggregates
    task_execution_log by (agent, model) then rolls up per agent. Read-only; no schema change.
    Returns a list sorted by CO2 desc: [{agent_id, agent_name, dispatches, tokens, energy_kwh, co2_kg,
    tokens_per_dispatch}]."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT agent_id, agent_name, model_used,
                   COUNT(*) AS n,
                   COALESCE(SUM(duration_ms), 0) AS dur_ms,
                   COALESCE(SUM(tokens_used), 0) AS toks
            FROM task_execution_log
            WHERE created_at > NOW() - INTERVAL '%s hours'
              AND agent_id IS NOT NULL
              AND model_used IS NOT NULL
              -- Exclude cloud/contractor rows: once cloud dispatch carries the real
              -- escalating agent_id, the agent_id IS NOT NULL filter no longer excludes
              -- them, so guard explicitly or we'd fabricate local carbon for cloud calls.
              AND worker_type IS DISTINCT FROM 'contract'
            GROUP BY agent_id, agent_name, model_used
            """,
            (hours,),
        )
        rows = cur.fetchall()
    agg = {}
    for r in rows:
        # Skip non-LLM (orchestration markers / scrape / embeddings) — same
        # exclusion as run_carbon_footprint_job so this "same methodology" stays
        # consistent and per-agent energy/CO2 isn't fabricated from marker duration.
        if not _is_llm_model(r["model_used"]):
            continue
        aid = r["agent_id"]
        a = agg.setdefault(
            aid,
            {
                "agent_id": aid,
                "agent_name": r["agent_name"],
                "dispatches": 0,
                "tokens": 0,
                "energy_kwh": 0.0,
                "co2_kg": 0.0,
            },
        )
        watts = _watts_for_model(r["model_used"])
        dur_ms = int(r["dur_ms"])
        a["dispatches"] += int(r["n"])
        a["tokens"] += int(r["toks"] or 0)
        a["energy_kwh"] += watts * (dur_ms / 1_000 / 3_600) / 1000.0
        a["co2_kg"] += _co2_kg(watts, dur_ms)
    out = []
    for a in agg.values():
        a["energy_kwh"] = round(a["energy_kwh"], 6)
        a["co2_kg"] = round(a["co2_kg"], 8)
        a["tokens_per_dispatch"] = round(a["tokens"] / a["dispatches"], 1) if a["dispatches"] else 0
        out.append(a)
    out.sort(key=lambda x: x["co2_kg"], reverse=True)
    return out


def efficiency_summary(hours: int = 24):
    """P2-D (#381): org-wide efficiency snapshot for the K.I.N. tab + the public CREED efficiency
    pillar — totals + per-dispatch intensity + the count of current right-size opportunities (pending
    downsizing proposals; None if benchmark data is unavailable)."""
    agents = per_agent_efficiency(hours)
    disp = sum(a["dispatches"] for a in agents)
    tok = sum(a["tokens"] for a in agents)
    kwh = sum(a["energy_kwh"] for a in agents)
    co2 = sum(a["co2_kg"] for a in agents)
    opportunities = None
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from tools.agent_academy.services.benchmark_service import propose_model_rightsizing

        opportunities = len(propose_model_rightsizing())
    except Exception:
        opportunities = None
    return {
        "window_hours": hours,
        "agents_tracked": len(agents),
        "dispatches": disp,
        "tokens": tok,
        "energy_kwh": round(kwh, 6),
        "co2_kg": round(co2, 8),
        "co2_g_per_dispatch": round(co2 * 1000 / disp, 4) if disp else 0,
        "tokens_per_dispatch": round(tok / disp, 1) if disp else 0,
        "grid_factor_kg_per_kwh": _CANADA_GRID_KG_CO2_PER_KWH,
        "right_size_opportunities": opportunities,
    }


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
                  -- Cloud/contractor inference does NOT run on our cluster, so applying
                  -- our GPU/CPU wattage to it would FABRICATE local carbon. Mirror the
                  -- A.R.M.A.D.A. feed (co2_g_sql) + per_agent_efficiency exclusion so the
                  -- public CREED environmental pillar reconciles across all consumers.
                  AND worker_type IS DISTINCT FROM 'contract'
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
    run_count = 0
    for row in rows:
        model = row["model_used"] or ""
        # Skip non-LLM rows (orchestration/job MARKERS, scrape, embeddings). Their
        # duration is cycle/job wall-clock, NOT model runtime — counting it as
        # inference energy fabricated carbon AND double-counted (the real inference
        # a marker's cycle triggers is logged + counted on its own row). Mirrors the
        # A.R.M.A.D.A. display (co2_g_for/co2_g_sql) so the pillar reconciles. (#4571 follow-up)
        if not _is_llm_model(model):
            continue
        dur = int(row["duration_ms"] or 0)
        w = _watts_for_model(model)
        total_co2 += _co2_kg(w, dur)
        total_kwh += w * (dur / 1_000 / 3_600) / 1000.0
        run_count += 1

    total_kwh = round(total_kwh, 6)
    total_co2 = round(total_co2, 6)

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
