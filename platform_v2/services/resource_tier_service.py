"""
Resource Tier Service — Platform-wide resource management.

Monitors VRAM/RAM/CPU and calculates a platform tier:
  GREEN  — normal operations, full capabilities
  YELLOW — constrained, prefer smaller models, reduce non-critical job frequency
  RED    — critical, only essential dispatches, pause optional jobs
  BLACK  — overloaded, emergency mode, unload models, alert operator

Inspired by Conway Research's 4-tier survival system, adapted for
A.R.C.H.I.E.'s self-hosted architecture (Decision #TBD).

Usage:
    from services.resource_tier_service import get_current_tier, measure_resources

    tier = get_current_tier()           # "green", "yellow", "red", "black"
    snapshot = measure_resources()      # full ResourceSnapshot dict
    should = should_job_run("agent_training_tick")  # tier-gated job check
"""

import json
import logging
import os
import subprocess
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Tier Definitions ─────────────────────────────────────────────────


class ResourceTier(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    BLACK = "black"

    @property
    def severity(self):
        return {"green": 0, "yellow": 1, "red": 2, "black": 3}[self.value]

    def __ge__(self, other):
        if isinstance(other, ResourceTier):
            return self.severity >= other.severity
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, ResourceTier):
            return self.severity > other.severity
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, ResourceTier):
            return self.severity <= other.severity
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, ResourceTier):
            return self.severity < other.severity
        return NotImplemented


# ── Thresholds (configurable via env) ────────────────────────────────

# VRAM thresholds (percentage used)
VRAM_YELLOW = float(os.getenv("RESOURCE_VRAM_YELLOW", "70"))
VRAM_RED = float(os.getenv("RESOURCE_VRAM_RED", "90"))
VRAM_BLACK = float(os.getenv("RESOURCE_VRAM_BLACK", "97"))

# RAM thresholds (percentage used)
RAM_YELLOW = float(os.getenv("RESOURCE_RAM_YELLOW", "60"))
RAM_RED = float(os.getenv("RESOURCE_RAM_RED", "80"))
RAM_BLACK = float(os.getenv("RESOURCE_RAM_BLACK", "92"))

# CPU thresholds (percentage used, 1-min load average normalized)
CPU_YELLOW = float(os.getenv("RESOURCE_CPU_YELLOW", "70"))
CPU_RED = float(os.getenv("RESOURCE_CPU_RED", "85"))
CPU_BLACK = float(os.getenv("RESOURCE_CPU_BLACK", "95"))

# Hysteresis: require N consecutive readings at a NEW tier before transitioning
HYSTERESIS_COUNT = int(os.getenv("RESOURCE_HYSTERESIS", "3"))

# ── In-memory state (fast reads, DB is source of truth) ──────────────

_cache = {
    "tier": ResourceTier.GREEN,
    "snapshot": None,
    "updated_at": 0,
    "consecutive_readings": 0,
    "pending_tier": None,
}

# DB config key
_TIER_CONFIG_KEY = "resource_tier"

# ── Job Tier Requirements ────────────────────────────────────────────
# Maps job ID patterns to the minimum tier they require to run.
# Jobs not listed default to GREEN (run only when healthy).

JOB_TIER_REQUIREMENTS = {
    # Always run (even in BLACK) — critical infrastructure
    "agent_resource_tier_monitor": ResourceTier.BLACK,
    "agent_fleet_health": ResourceTier.RED,
    "agent_security_monitor": ResourceTier.RED,
    "agent_health_check": ResourceTier.RED,
    "agent_scheduled_tasks": ResourceTier.RED,
    "agent_approvals": ResourceTier.RED,
    "agent_reminders": ResourceTier.RED,
    # Run in YELLOW+ — important but can degrade
    "agent_email_queue": ResourceTier.YELLOW,
    "agent_embedding_loop": ResourceTier.YELLOW,
    "agent_analysis_loop": ResourceTier.YELLOW,
    "agent_knowledge_processing": ResourceTier.YELLOW,
    "agent_model_state_saver": ResourceTier.YELLOW,
    # GREEN only — nice-to-have, pause under load
    "agent_training_tick": ResourceTier.GREEN,
    "agent_proactive_scan": ResourceTier.GREEN,
    "agent_quality_review": ResourceTier.GREEN,
    "agent_world_events": ResourceTier.GREEN,
    "agent_social_presence": ResourceTier.GREEN,
    "agent_competitor_scan": ResourceTier.GREEN,
    "agent_agent_reflections": ResourceTier.GREEN,
    "agent_skill_installer": ResourceTier.GREEN,
    "agent_skill_tester": ResourceTier.GREEN,
    "agent_skill_adapter": ResourceTier.GREEN,
    "agent_repo_relevance": ResourceTier.GREEN,
    "agent_github_skill_scan": ResourceTier.GREEN,
}


# ── Core Functions ───────────────────────────────────────────────────


def measure_resources() -> dict:
    """Measure current VRAM, RAM, and CPU usage. Returns a snapshot dict."""
    import psutil

    # RAM
    mem = psutil.virtual_memory()
    ram_total_gb = round(mem.total / (1024**3), 1)
    ram_used_pct = round(mem.percent, 1)
    ram_available_gb = round(mem.available / (1024**3), 1)

    # CPU — use psutil.cpu_percent for accurate measurement inside Docker
    # (os.getloadavg returns host load average which can exceed 100% per core
    #  and psutil.cpu_count inside Docker may not match host core count)
    try:
        cpu_pct = round(psutil.cpu_percent(interval=0.1), 1)
    except Exception:
        cpu_pct = 0.0

    # VRAM (nvidia-smi or Ollama fallback)
    vram_used_pct = 0.0
    vram_total_gb = 8.0  # Quadro M4000 default
    vram_used_gb = 0.0
    vram_free_gb = 8.0
    vram_source = "none"

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 3:
                vram_total_gb = round(float(parts[0]) / 1024, 1)
                vram_used_gb = round(float(parts[1]) / 1024, 1)
                vram_free_gb = round(float(parts[2]) / 1024, 1)
                vram_used_pct = round(vram_used_gb / vram_total_gb * 100, 1) if vram_total_gb > 0 else 0
                vram_source = "nvidia-smi"
    except Exception:
        pass

    # Fallback: Ollama /api/ps for VRAM data — reuse starbase cache when available
    if vram_source == "none":
        try:
            from tools.starbase.helpers import _get_cached_ollama_ps

            ps_models = _get_cached_ollama_ps()
            total_vram = sum(m.get("size_vram", 0) for m in ps_models)
            if total_vram > 0:
                vram_used_gb = round(total_vram / (1024**3), 1)
                vram_free_gb = round(vram_total_gb - vram_used_gb, 1)
                vram_used_pct = round(vram_used_gb / vram_total_gb * 100, 1)
                vram_source = "ollama_cached"
        except Exception:
            # Direct Ollama fallback if helpers unavailable
            try:
                import requests

                ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
                resp = requests.get(f"{ollama_host}/api/ps", timeout=3)
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    total_vram = sum(m.get("size_vram", 0) for m in models)
                    if total_vram > 0:
                        vram_used_gb = round(total_vram / (1024**3), 1)
                        vram_free_gb = round(vram_total_gb - vram_used_gb, 1)
                        vram_used_pct = round(vram_used_gb / vram_total_gb * 100, 1)
                        vram_source = "ollama"
            except Exception:
                pass

    # Models loaded count — reuse starbase helpers cache when available
    models_loaded = 0
    try:
        from tools.starbase.helpers import _get_cached_ollama_ps

        models_loaded = len(_get_cached_ollama_ps())
    except Exception:
        # Fallback: direct Ollama query if helpers not available
        try:
            import requests

            ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
            resp = requests.get(f"{ollama_host}/api/ps", timeout=3)
            if resp.status_code == 200:
                models_loaded = len(resp.json().get("models", []))
        except Exception:
            pass

    return {
        "ram_total_gb": ram_total_gb,
        "ram_available_gb": ram_available_gb,
        "ram_used_pct": ram_used_pct,
        "cpu_used_pct": cpu_pct,
        "vram_total_gb": vram_total_gb,
        "vram_used_gb": vram_used_gb,
        "vram_free_gb": vram_free_gb,
        "vram_used_pct": vram_used_pct,
        "vram_source": vram_source,
        "models_loaded": models_loaded,
        "measured_at": time.time(),
    }


def calculate_tier(snapshot: dict) -> ResourceTier:
    """Determine the resource tier from a measurement snapshot."""
    vram = snapshot.get("vram_used_pct", 0)
    ram = snapshot.get("ram_used_pct", 0)
    cpu = snapshot.get("cpu_used_pct", 0)

    # Worst-of: the highest severity across all metrics determines the tier
    tier = ResourceTier.GREEN

    for metric, yellow, red, black in [
        (vram, VRAM_YELLOW, VRAM_RED, VRAM_BLACK),
        (ram, RAM_YELLOW, RAM_RED, RAM_BLACK),
        (cpu, CPU_YELLOW, CPU_RED, CPU_BLACK),
    ]:
        if metric >= black:
            candidate = ResourceTier.BLACK
        elif metric >= red:
            candidate = ResourceTier.RED
        elif metric >= yellow:
            candidate = ResourceTier.YELLOW
        else:
            candidate = ResourceTier.GREEN

        if candidate > tier:
            tier = candidate

    return tier


def measure_and_update() -> dict:
    """
    Measure resources, calculate tier with hysteresis, persist to DB.
    Called by agent loop job every 60 seconds.
    Returns dict with tier, snapshot, and transition info.
    """
    snapshot = measure_resources()
    new_tier = calculate_tier(snapshot)
    old_tier = _cache["tier"]

    transition = None

    # Hysteresis: only transition if we see the new tier N times consecutively
    if new_tier != old_tier:
        if _cache["pending_tier"] == new_tier:
            _cache["consecutive_readings"] += 1
        else:
            _cache["pending_tier"] = new_tier
            _cache["consecutive_readings"] = 1

        # Exception: immediate escalation to BLACK (no hysteresis for emergencies)
        if new_tier == ResourceTier.BLACK or _cache["consecutive_readings"] >= HYSTERESIS_COUNT:
            _cache["tier"] = new_tier
            _cache["pending_tier"] = None
            _cache["consecutive_readings"] = 0
            transition = {"from": old_tier.value, "to": new_tier.value}

            if new_tier > old_tier:
                logger.warning(
                    f"[ResourceTier] ESCALATION: {old_tier.value} -> {new_tier.value} "
                    f"(VRAM={snapshot['vram_used_pct']}% RAM={snapshot['ram_used_pct']}% "
                    f"CPU={snapshot['cpu_used_pct']}%)"
                )
            else:
                logger.info(
                    f"[ResourceTier] DE-ESCALATION: {old_tier.value} -> {new_tier.value} "
                    f"(VRAM={snapshot['vram_used_pct']}% RAM={snapshot['ram_used_pct']}% "
                    f"CPU={snapshot['cpu_used_pct']}%)"
                )
    else:
        # Stable at current tier — reset pending
        _cache["pending_tier"] = None
        _cache["consecutive_readings"] = 0

    _cache["snapshot"] = snapshot
    _cache["updated_at"] = time.time()

    # Persist to system_config (non-blocking — cache is the fast path)
    _persist_tier_to_db(_cache["tier"], snapshot, transition)

    return {
        "tier": _cache["tier"].value,
        "snapshot": snapshot,
        "transition": transition,
        "pending_tier": _cache["pending_tier"].value if _cache["pending_tier"] else None,
        "consecutive_readings": _cache["consecutive_readings"],
    }


# ── Public API ───────────────────────────────────────────────────────


def get_current_tier() -> str:
    """Get the current resource tier. Fast (in-memory cache)."""
    # If cache is stale (>120s), try DB fallback
    if time.time() - _cache["updated_at"] > 120:
        _load_tier_from_db()
    return _cache["tier"].value


def get_current_tier_enum() -> ResourceTier:
    """Get the current resource tier as enum. Fast (in-memory cache)."""
    if time.time() - _cache["updated_at"] > 120:
        _load_tier_from_db()
    return _cache["tier"]


def get_tier_snapshot() -> dict:
    """Get the full tier state including snapshot and pending transitions."""
    return {
        "tier": _cache["tier"].value,
        "snapshot": _cache["snapshot"],
        "updated_at": _cache["updated_at"],
        "pending_tier": _cache["pending_tier"].value if _cache["pending_tier"] else None,
        "consecutive_readings": _cache["consecutive_readings"],
    }


def should_job_run(job_id: str) -> bool:
    """
    Check if a job should run given the current resource tier.

    Jobs specify a minimum tier they can tolerate. If the current tier
    is worse than the job's minimum, the job is skipped.

    Jobs not in JOB_TIER_REQUIREMENTS default to GREEN-only.
    """
    current = get_current_tier_enum()
    minimum = JOB_TIER_REQUIREMENTS.get(job_id, ResourceTier.GREEN)

    # A job with minimum=YELLOW runs in GREEN and YELLOW, but not RED/BLACK.
    # A job with minimum=RED runs in GREEN, YELLOW, and RED, but not BLACK.
    # A job with minimum=BLACK always runs.
    return current <= minimum or current == ResourceTier.GREEN


def get_model_preference(current_tier: Optional[str] = None) -> dict:
    """
    Get model selection hints based on current resource tier.

    Returns a dict with flags the dispatcher can use:
        prefer_small: bool — prefer smaller models
        force_local: bool — no cloud escalation
        block_non_critical: bool — reject low-priority requests
        prefer_loaded: bool — prefer already-loaded models to avoid swaps
    """
    tier = ResourceTier(current_tier) if current_tier else get_current_tier_enum()

    return {
        "tier": tier.value,
        "prefer_small": tier >= ResourceTier.YELLOW,
        "force_local": tier >= ResourceTier.RED,
        "block_non_critical": tier >= ResourceTier.BLACK,
        "prefer_loaded": tier >= ResourceTier.YELLOW,
    }


# ── DB Persistence ───────────────────────────────────────────────────


def _persist_tier_to_db(tier: ResourceTier, snapshot: dict, transition: Optional[dict]):
    """Write current tier state to system_config table."""
    try:
        from database import get_db

        payload = json.dumps(
            {
                "tier": tier.value,
                "vram_used_pct": snapshot.get("vram_used_pct", 0),
                "ram_used_pct": snapshot.get("ram_used_pct", 0),
                "cpu_used_pct": snapshot.get("cpu_used_pct", 0),
                "models_loaded": snapshot.get("models_loaded", 0),
                "last_transition": transition,
                "updated_at": snapshot.get("measured_at", time.time()),
            }
        )

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO system_config (key, value) VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = %s::jsonb
            """,
            (_TIER_CONFIG_KEY, payload, payload),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"[ResourceTier] DB persist failed (non-critical): {e}")


def _load_tier_from_db():
    """Load tier from DB into cache (fallback when cache is stale)."""
    try:
        from database import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = %s", (_TIER_CONFIG_KEY,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            _cache["tier"] = ResourceTier(data.get("tier", "green"))
            _cache["updated_at"] = data.get("updated_at", time.time())
    except Exception as e:
        logger.debug(f"[ResourceTier] DB load failed (using cached): {e}")
