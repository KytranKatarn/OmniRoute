"""Phase 2 agent-directory backfill glue (project #388, task #4946).

Loads an incomplete AI agent's current identity fields, runs the pure
`agent_identity_builder.enrich_identity` (M.U.S.E., sovereign-local — preserve
existing, fill gaps, deepen the prompt), and applies the OWNER-APPROVED result
via the `agent_service` single-writer. All inference local-only (ADR-013); no
raw SQL on `agents`. See docs/superpowers/specs/2026-07-16-agent-directory-backfill-design.md.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from database import get_db_cursor
from services import agent_identity_builder, agent_service

logger = logging.getLogger(__name__)


def _primary_capability(cur, agent_id: int, department: str) -> str:
    """The agent's main skill (highest proficiency); else the department's default
    capability; else 'general'."""
    cur.execute(
        "SELECT skill_name FROM agent_skills WHERE agent_id=%s "
        "ORDER BY proficiency_level DESC NULLS LAST, id LIMIT 1",
        (agent_id,),
    )
    row = cur.fetchone()
    if row:
        return row["skill_name"] if isinstance(row, dict) else row[0]
    try:
        from tools.department_hq.services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        for cap, dept in CAPABILITY_DEPARTMENT_MAP.items():
            if dept == department:
                return cap
    except Exception:
        pass
    return "general"


def _load_current(cur, agent_id: int) -> Optional[dict[str, Any]]:
    cur.execute(
        """SELECT id, name, department, acronym_expansion, title, bio,
                  personality_prompt, portrait_prompt, avatar_url,
                  COALESCE(LENGTH(system_prompt), 0) AS sp_len
           FROM agents WHERE id = %s""",
        (agent_id,),
    )
    r = cur.fetchone()
    if not r:
        return None
    r = dict(r)
    return {
        "id": r["id"],
        "name": r["name"],
        "department": r["department"],
        "expansion": r.get("acronym_expansion") or "",
        "title": r.get("title") or "",
        "bio": r.get("bio") or "",
        "personality": r.get("personality_prompt") or "",
        "portrait_prompt": r.get("portrait_prompt") or "",
        "has_portrait": bool((r.get("avatar_url") or "").strip()),
        "sp_len": r["sp_len"],
    }


def plan_backfill(agent_ids: list[int]) -> list[dict]:
    """For each agent: load current fields, run enrich_identity (one M.U.S.E.
    dispatch each — slow), return the before->after review payload. One agent's
    failure is logged and skipped; it never aborts the batch."""
    # The dispatcher lazily does `from db import ...`; without the ai_bridge path
    # on sys.path that raises ModuleNotFoundError, which build_identity's
    # defer-on-cold silently masks as an all-fallback result (KB #272154).
    try:
        from services.signal_calendar_service import _ensure_import_paths

        _ensure_import_paths()
    except Exception as e:  # never block the batch on the path shim
        logger.warning("plan_backfill: _ensure_import_paths failed: %s", e)

    out: list[dict] = []
    for aid in agent_ids:
        try:
            with get_db_cursor(commit=False) as (_c, cur):
                current = _load_current(cur, aid)
                if not current:
                    logger.warning("plan_backfill: agent %s not found", aid)
                    continue
                cap = _primary_capability(cur, aid, current["department"])
            res = agent_identity_builder.enrich_identity(current, cap, current["department"])
            res["agent_id"] = aid
            res["capability"] = cap
            res["department"] = current["department"]
            res["before"] = {
                "sp_len": current["sp_len"],
                "expansion": current["expansion"],
                "title": current["title"],
                "bio": current["bio"],
                "personality": current["personality"],
                "has_portrait": current["has_portrait"],
            }
            out.append(res)
        except Exception as e:
            logger.warning("plan_backfill agent %s failed: %s", aid, e)
    return out


def apply_backfill(agent_id: int, after: dict, portrait_needed: bool) -> bool:
    """Single-writer apply of an owner-approved enriched identity (+ optional
    portrait). Never raw SQL; portrait enqueue is fail-open."""
    agent_service.update_agent(
        agent_id,
        system_prompt=after["system_prompt"],
        acronym_expansion=after.get("expansion") or None,
        title=after.get("title") or None,
        bio=after.get("bio") or None,
        personality_prompt=after.get("personality") or None,
        portrait_prompt=after.get("portrait_prompt") or None,
    )
    if portrait_needed and after.get("portrait_prompt"):
        try:
            agent_service.add_portrait(agent_id, after["portrait_prompt"], style="sci-fi")
        except Exception as e:
            logger.warning("backfill portrait enqueue failed for #%s: %s", agent_id, e)
    return True
