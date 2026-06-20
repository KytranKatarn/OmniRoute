"""Telemetry for A.R.C.H.I.E. Engine build runs → task_execution_log (#4257).

Mirrors services/agents/codex_telemetry.record_codex_run, but for the engine's
autonomous build loop. Each engine build run lands a row in task_execution_log so
it's visible on the Token Economy + Dispatch tabs (worker_type='internal',
task_type='engine_build', module_source='archie_engine'). The build's LLM
inference is already logged by the
DHQ dispatcher (#4252, strictly local); this row attributes the BUILD RUN itself
to the engine.
"""

import json

AGENT_NAME = "A.R.C.H.I.E. Engine"


def record_engine_run(
    task_label,
    agent_name=AGENT_NAME,
    model="archie:7b",
    prompt_tokens=0,
    completion_tokens=0,
    files_changed=None,
    success=True,
    duration_ms=0,
    summary="",
    branch=None,
    project_id=None,
):
    """Insert one engine build-run row into task_execution_log. Returns {id}.

    Optionally also creates a Dev HQ unified_tasks row when project_id is given.
    """
    from database import get_db_cursor

    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    meta = {
        "branch": branch,
        "files_changed": files_changed,
        "summary": (summary or "")[:500],
        "source": "archie-code",
    }
    # #4253(b): surface the failure reason ON the row. Failed engine runs used to
    # land with success=f and an EMPTY error_message — the real reason was buried in
    # request_metadata.summary, so failures looked silent on the Dispatch tab and in
    # triage. Copy the summary into error_message on failure (NULL on success).
    err_msg = None if success else ((summary or "").strip()[:2000] or "engine build failed (no summary)")
    tel_id = None
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_name, worker_type, task_type, task_description, module_source,
                 model_used, provider, prompt_tokens, completion_tokens, tokens_used,
                 duration_ms, success, error_message, request_origin, request_metadata, created_at)
            VALUES (%s,'internal','engine_build',%s,'archie_engine',
                    %s,'local',%s,%s,%s,%s,%s,%s,'archie_engine',%s::jsonb,NOW())
            RETURNING id
            """,
            (
                agent_name or AGENT_NAME,
                (task_label or "")[:500],
                f"engine/{model}",
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                total,
                int(duration_ms or 0),
                bool(success),
                err_msg,
                json.dumps(meta),
            ),
        )
        tel_id = cur.fetchone()["id"]
        if project_id:
            cur.execute(
                """
                INSERT INTO unified_tasks
                    (project_id, title, status, priority, task_type, created_at, updated_at)
                VALUES (%s,%s,%s,5,'implementation',NOW(),NOW())
                """,
                (
                    project_id,
                    f"[Engine] {task_label}"[:200],
                    "completed" if success else "blocked",
                ),
            )

    return {"id": tel_id}
