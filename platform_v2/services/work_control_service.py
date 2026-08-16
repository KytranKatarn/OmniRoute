"""Unified work-control — one API to read/toggle whether any platform job or
backlog is enabled, routing to the correct backend store.

This is the single source of truth behind the DHQ Autonomy → Backlog & Jobs
Control Center (decision #676 / module-work-pattern). Toggles today are scattered
across four backends; this service abstracts them:

  • platform_settings  — default store for new toggles (key `work:<key>:enabled`)
  • consciousness loops — services/loop_service.py over system_config
  • env (WTF, VPS)      — read-only from the hub; set_enabled records a desired-state

Default is ALWAYS enabled, so adding this layer changes no current behavior until
an admin explicitly flips something off.
"""

import logging
import os

from database import get_db_cursor

logger = logging.getLogger(__name__)

_PS_PREFIX = "work:"  # platform_settings key shape: work:<key>:enabled
_TRUE = {"1", "true", "on", "yes", "enabled"}

# control-key -> ("loop", loop_op) | ("env", ENV_VAR)
# Anything not listed here lives in platform_settings.
_BACKEND_OVERRIDES = {
    "consciousness_analysis": ("loop", "analysis"),
    "consciousness_embedding": ("loop", "embedding"),
    "consciousness_translate": ("loop", "translate"),
    "wtf_llm_backlog": ("env", "WTF_LLM_BACKLOG_ENABLED"),
    "wtf_factcheck_backlog": ("env", "WTF_FACTCHECK_BACKLOG_ENABLED"),
}

# Curated backlog registry (jobs come from job_registry.JOB_REGISTRY).
BACKLOGS = {
    "consciousness_analysis": {"module": "Consciousness", "drains": "knowledge_base unanalyzed", "backend": "loop"},
    "consciousness_embedding": {"module": "Consciousness", "drains": "knowledge_base unembedded", "backend": "loop"},
    "consciousness_translate": {"module": "Consciousness", "drains": "untranslated keys", "backend": "loop"},
    # #5626 — the drip that ACTUALLY drains the translation backlog. Registered here
    # so it is visible and toggleable in the Autonomy tab; a work-control key that
    # nothing lists is un-toggleable from the UI and invisible to the operator, which
    # is the same "declared but never surfaced" shape as a retention tier with no
    # pruner. ⚠️ Distinct from `consciousness_translate` above: that is the legacy
    # LOOP backend, which has been enabled-but-idle (0 rows translated in the 7 days
    # before 2026-08-15). Both claim work with NOT EXISTS, so they cannot
    # double-translate a key even if both run.
    "translate_backlog_drip": {
        "module": "Consciousness",
        "drains": "translations missing keys (25/cycle, 15 min)",
        "backend": "platform_settings",
        # ⚠️ Ships OFF, and the CONTROL CENTRE MUST AGREE WITH THE JOB. `is_enabled`
        # defaults to True (fail-safe: a control-plane glitch must never stop work),
        # but this job calls it with default=False. Without carrying that default
        # here, the Autonomy tab would render the toggle ON while every cycle
        # returned {"skipped": "disabled"} — a switch that lies about its own state.
        "default": False,
    },
    # Chronicle (#5644). BOTH were invisible in the Autonomy tab before 2026-08-16:
    # `chronicle_story` has checked `work:chronicle_story:enabled` since it shipped but
    # was listed in NEITHER registry, so the operator could not see or toggle a job that
    # runs every 10 minutes. Same shape as translate_backlog_drip above.
    #
    # ⚠️ The KEY here must be the platform_settings key the JOB reads, NOT the scheduler
    # job id — the story job's id is `chronicle_story_worker` but its setting is
    # `work:chronicle_story:enabled`. Keying this off the job id would render a toggle
    # that writes a row nothing reads.
    "chronicle_ingest": {
        "module": "Chronicle",
        "drains": "new Gmail + LinkedIn items not yet in Chronicle (50/account/hour)",
        "backend": "platform_settings",
        # Ships OFF and the job reads default=False — these two MUST agree or the tab
        # shows ON while every cycle returns early.
        "default": False,
    },
    "chronicle_story": {
        "module": "Chronicle",
        "drains": "resolved entities with >=2 emails and no story yet",
        "backend": "platform_settings",
    },
    "delegate_task_worker": {
        "module": "Department HQ",
        "drains": "unified_tasks (delegated)",
        "backend": "platform_settings",
    },
    "fleet_backlog_runner": {
        "module": "Department HQ",
        "drains": "unified_tasks (pending → fleet)",
        "backend": "platform_settings",
    },
    "repair_bay_weekly_batch": {
        "module": "Repair Bay",
        "drains": "medium-severity code issues",
        "backend": "platform_settings",
    },
    "wtf_llm_backlog": {"module": "What The Fact", "drains": "wtf.articles unanalyzed", "backend": "env"},
    "wtf_factcheck_backlog": {"module": "What The Fact", "drains": "wtf.articles unfactchecked", "backend": "env"},
}


def _ps_key(key):
    return f"{_PS_PREFIX}{key}:enabled"


def is_enabled(key, default=True):
    """Whether the job/backlog `key` is currently enabled. Fail-safe: returns
    `default` (enabled) on any error so a control-plane glitch never silently
    stops platform work."""
    ov = _BACKEND_OVERRIDES.get(key)
    if ov:
        kind, ref = ov
        if kind == "loop":
            try:
                from services.loop_service import get_server_loops

                return bool(get_server_loops().get(ref, False))
            except Exception as e:  # noqa: BLE001
                logger.warning("work_control loop read %s failed: %s", key, e)
                return default
        if kind == "env":
            return os.getenv(ref, "false").strip().lower() in _TRUE
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (_ps_key(key),))
            row = cur.fetchone()
        if not row:
            return default
        val = row["value"] if isinstance(row, dict) else row[0]
        return str(val).strip().lower() in _TRUE
    except Exception as e:  # noqa: BLE001
        logger.warning("work_control is_enabled(%s) failed: %s — default %s", key, e, default)
        return default


def _ps_set(key, enabled):
    val = "true" if enabled else "false"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value, value_type, description, updated_at)
               VALUES (%s, %s, 'boolean', %s, NOW())
               ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
            (_ps_key(key), val, f"Work-control toggle for {key}", val),
        )


def set_enabled(key, enabled):
    """Toggle `key`. Routes to the right backend. Returns a result dict."""
    enabled = bool(enabled)
    ov = _BACKEND_OVERRIDES.get(key)
    if ov:
        kind, ref = ov
        if kind == "loop":
            try:
                from services.loop_service import set_server_loop

                set_server_loop(ref, enabled)
                return {"ok": True, "backend": "loop", "key": key, "enabled": enabled}
            except Exception as e:  # noqa: BLE001
                logger.error("work_control set loop %s failed: %s", key, e)
                return {"ok": False, "key": key, "error": str(e)}
        if kind == "env":
            # VPS env-gated — record desired-state; the runner polls / redeploy applies.
            _ps_set(key, enabled)
            return {
                "ok": True,
                "backend": "env",
                "key": key,
                "enabled": enabled,
                "note": "desired-state recorded; VPS runner must poll or be redeployed to apply",
            }
    try:
        _ps_set(key, enabled)
        return {"ok": True, "backend": "platform_settings", "key": key, "enabled": enabled}
    except Exception as e:  # noqa: BLE001
        logger.error("work_control set %s failed: %s", key, e)
        return {"ok": False, "key": key, "error": str(e)}


def list_controls():
    """Every controllable job + backlog with its current enabled-state — the data
    source for the Control Center. Jobs from job_registry; backlogs from BACKLOGS."""
    out = []
    try:
        from tools.department_hq.services.job_registry import JOB_REGISTRY

        for jid, meta in JOB_REGISTRY.items():
            out.append(
                {
                    "key": jid,
                    "name": jid,
                    "kind": "job",
                    "module": meta.get("department", "?"),
                    "director": meta.get("director"),
                    "schedule": meta.get("interval"),
                    "backend": "platform_settings",
                    "enabled": is_enabled(jid),
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("list_controls jobs failed: %s", e)
    for key, meta in BACKLOGS.items():
        out.append(
            {
                "key": key,
                "name": key,
                "kind": "backlog",
                "module": meta["module"],
                "drains": meta.get("drains"),
                "backend": meta["backend"],
                # Honour a per-backlog default so the Control Centre reports the same
                # state the job itself computes. Absent a `default`, keep the historic
                # fail-safe True.
                "enabled": is_enabled(key, meta.get("default", True)),
            }
        )
    return out
