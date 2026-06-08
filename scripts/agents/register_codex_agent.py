#!/usr/bin/env python3
"""Register Codex as a contract team agent (Codex Phase B, step 1).

Idempotent: safe to re-run. Creates a single 'Codex' agent via the sanctioned
agent_service single-writer path (NEVER raw SQL on the agents table) and gives
it the ``codex_task`` skill at proficiency 5.

Codex is an EXTERNAL CLI coding agent — it does NOT run on Ollama and is never
dispatched to the cluster. The ``codex_task`` capability is intercepted in
delegation_service.delegate_task() and created 'deferred'; the host poller
(scripts/agents/codex-delegation-worker.sh) runs the sandboxed Codex runner.
This registration only gives Codex roster visibility + makes ``codex_task`` a
real, owned capability for tracking/welfare. The model field is a label.

Run:  docker exec archie_platform python3 /app/../scripts/agents/register_codex_agent.py
  (or from the host with DB env set; it uses the platform DB via agent_service)
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor  # noqa: E402
from services import agent_service  # noqa: E402

AGENT_NAME = "Codex"
DISPLAY_NAME = "Codex (CLI)"
DEPARTMENT = "Engineering & Technology"
MODEL = "codex-cli"  # label only — Codex is external (OpenAI), not an Ollama model
SKILL = "codex_task"


def _existing_codex_id():
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM agents WHERE name = %s AND status != 'decommissioned' LIMIT 1",
            (AGENT_NAME,),
        )
        row = cur.fetchone()
        return (row["id"] if isinstance(row, dict) else row[0]) if row else None


def main() -> int:
    agent_id = _existing_codex_id()
    if agent_id:
        print(f"Codex agent already exists: id={agent_id} — ensuring skill only")
    else:
        agent_id = agent_service.create_agent(
            name=AGENT_NAME,
            display_name=DISPLAY_NAME,
            department=DEPARTMENT,
            model=MODEL,
            worker_type="contractor",
            shift_state="active",
            tier=4,  # Lv4 = cloud-capable; Codex is an external cloud agent
            is_department_ai=False,
            capabilities={"codex_task": True},
            system_prompt=(
                "Codex is an external CLI coding agent that works headless on "
                "Applications/Concepts modules inside a sandboxed runner, opens a "
                "PR, and waits for human Telegram approval. It never runs on the "
                "local cluster."
            ),
        )
        print(f"Created Codex agent: id={agent_id}")

    # Idempotent skill add (skip if already present).
    have = {s["skill_name"] for s in agent_service.get_skills(agent_id)}
    if SKILL not in have:
        agent_service.add_skill(agent_id, SKILL, level=5, category="engineering")
        print(f"Added skill {SKILL} (Lv5) to Codex #{agent_id}")
    else:
        print(f"Skill {SKILL} already present on Codex #{agent_id}")

    print(f"OK: Codex agent id={agent_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
