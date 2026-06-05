"""Record a Codex CLI run into platform telemetry so it appears in the Token
Economy ('Codex (CLI)', provider=openai, cloud=orange) and the DHQ Dispatch/ARMADA
feeds. Mirrors how scripts/ingest_claude_cli_tokens.py logs 'Claude (CLI)'.

Does NOT use department_dispatcher.log_external_call — that overrides agent_name to
A.R.C.H.I.E. and reassigns the agent. We insert directly with a fixed CLI identity.

SCHEMA NOTE: worker_type CHECK constraint allows only 'internal' or 'contract' —
'external' is not valid. We use 'contract' (same as Claude CLI ingest).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

AGENT_NAME = "Codex (CLI)"
LOG_DIR = "/mnt/archie_brain/logs/codex"


def record_codex_run(
    task_label,
    branch,
    prompt_tokens,
    completion_tokens,
    model,
    files_changed,
    tests,
    success,
    duration_ms,
    estimated=False,
    project_id=None,
):
    from database import get_db_cursor

    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    meta = {
        "branch": branch,
        "files_changed": files_changed,
        "tests": tests,
        "estimated_tokens": bool(estimated),
        "source": "run-codex-task.sh",
    }
    tel_id = None
    task_id = None
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_name, worker_type, task_type, task_description, module_source,
                 model_used, provider, prompt_tokens, completion_tokens, tokens_used,
                 duration_ms, success, request_origin, request_metadata, created_at)
            VALUES (%s,'contract','codex_implement',%s,'codex_cli',
                    %s,'openai',%s,%s,%s,%s,%s,'codex_cli',%s::jsonb,NOW())
            RETURNING id
            """,
            (
                AGENT_NAME,
                task_label[:500],
                f"codex/{model}",
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                total,
                int(duration_ms or 0),
                bool(success),
                json.dumps(meta),
            ),
        )
        tel_id = cur.fetchone()["id"]
        # Dev HQ task row so it shows in task lists too
        if project_id:
            cur.execute(
                """
                INSERT INTO unified_tasks (project_id, title, status, priority, task_type, created_at, updated_at)
                VALUES (%s,%s,%s,5,'implementation',NOW(),NOW()) RETURNING id
                """,
                (
                    project_id,
                    f"[Codex] {task_label}"[:200],
                    "completed" if success else "blocked",
                ),
            )
            task_id = cur.fetchone()["id"]

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y%m%d_%H%M%S")
    with open(f"{LOG_DIR}/{stamp}_{branch.replace('/', '_')}.json", "w") as f:
        json.dump(
            {
                "task_execution_log_id": tel_id,
                "unified_task_id": task_id,
                "branch": branch,
                "model": model,
                "tokens": total,
                "success": success,
                "meta": meta,
            },
            f,
            indent=2,
        )
    return {
        "task_execution_log_id": tel_id,
        "unified_task_id": task_id,
        "tokens": total,
    }
