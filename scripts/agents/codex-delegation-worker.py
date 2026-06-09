#!/usr/bin/env python3
"""Host poller — Codex Phase B delegation (build steps 3 + 4).

Cron (every 60s). Claims ONE ``deferred`` ``codex_task`` row, composes a prompt
from the project goal + task reason, runs the sandboxed Codex runner
(``run-codex-task.sh``), opens a PR for the branch it pushes, writes the PR back
to the task row, and queues the Telegram promote approval (``codex_promote`` →
human approve → merge to prod). Concurrency 1 via ``flock``.

Why a HOST script (not a module/container job): it must invoke
``run-codex-task.sh``, which uses host Docker + host git worktrees. DB access
goes through ``docker exec archie_database psql`` and service calls through
``docker exec archie_platform python3`` — the exact pattern the runner already
uses. It is READ-ONLY on platform data except the single ``unified_tasks`` row
it claims (status + metadata writeback). It NEVER writes the agents table and
NEVER dispatches to the cluster (Codex is external).

Security invariants (do not violate):
  * The task ``reason`` only ever reaches Codex as a subprocess ARGUMENT (never
    interpolated into SQL). The only values interpolated into SQL are integers
    (task_id, project_id), hardcoded status literals, and a JSON blob whose
    values are an int PR number + a regex-restricted ``codex/[a-z0-9-]+`` branch.
  * Never auto-merge — promotion is a human Telegram approval.

Usage:
  codex-delegation-worker.py            # claim + run one task
  codex-delegation-worker.py --dry-run  # claim + compose + print, then release
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
import sys

REPO = "/mnt/archie_brain"
RUNNER = f"{REPO}/scripts/agents/run-codex-task.sh"
LOCK = "/tmp/codex-delegation-worker.lock"
RUNNER_TIMEOUT = 1800  # matches codex.yaml max runtime (30 min)
BRANCH_RE = re.compile(r"codex/[a-z0-9-]+")
PR_RE = re.compile(r"PR #(\d+) created:")


def psql(sql: str) -> str:
    """Run SQL in the DB container; return stripped -tA output (| separated)."""
    r = subprocess.run(
        ["docker", "exec", "-i", "archie_database", "psql", "-U", "archie",
         "-d", "archie", "-tA", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    # psql -t still emits the DML command tag ("UPDATE 1", "INSERT 0 1", ...) on
    # its own line; strip those so they never leak into a claimed row's reason.
    lines = [
        ln for ln in r.stdout.splitlines()
        if not re.match(r"^(UPDATE|INSERT|DELETE|SELECT|MERGE)\s+\d", ln.strip())
    ]
    return "\n".join(lines).strip()


def claim_one() -> dict | None:
    """Atomically claim the oldest deferred codex_task (deferred → in_progress)."""
    out = psql(
        """
        UPDATE unified_tasks SET status='in_progress', updated_at=now()
        WHERE id = (
            SELECT id FROM unified_tasks
            WHERE status='deferred' AND delegation_args->>'capability'='codex_task'
            ORDER BY created_at ASC LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, coalesce(project_id::text,''),
                  coalesce(replace(delegation_args->>'reason', E'\n', ' '), '');
        """
    )
    if not out:
        return None
    parts = out.split("|", 2)
    return {"id": int(parts[0]), "project_id": parts[1].strip(), "reason": parts[2].strip()}


def project_ctx(pid: str) -> str:
    if not pid:
        return ""
    return psql(
        "SELECT 'Project: '||name||coalesce(' — '||left(replace(description, E'\n',' '),400),'') "
        f"FROM unified_projects WHERE id={int(pid)};"
    )


def set_status(task_id: int, status: str, extra: dict | None = None) -> None:
    if extra:
        blob = json.dumps(extra)  # values are int + regex-safe branch → no quotes
        psql(
            f"UPDATE unified_tasks SET status='{status}', "
            f"metadata=coalesce(metadata,'{{}}'::jsonb)||'{blob}'::jsonb, "
            f"updated_at=now() WHERE id={int(task_id)};"
        )
    else:
        psql(f"UPDATE unified_tasks SET status='{status}', updated_at=now() WHERE id={int(task_id)};")


def compose_prompt(task: dict) -> str:
    # Lead with the TASK: run-codex-task.sh slugs the prompt's start into the
    # branch name + commit message, so the task (not the project header) must
    # come first. Project context follows as supporting detail.
    ctx = project_ctx(task["project_id"]) if task["project_id"] else ""
    tail = f"\n\nContext — {ctx}" if ctx else ""
    return (
        f"{task['reason']}\n"
        "Work ONLY within the allowed Applications/Concepts modules. "
        "Open a PR for review; do NOT merge to main." + tail
    )


def queue_promote(pr_num: int, task_id: int, module: str | None = None) -> None:
    """Queue the Tier-2 Telegram approve/merge via the container service.

    promote_codex_pr imports ai_bridge.agent_loop, which does ``from db import``
    — so ``/mnt/archie_brain/ai_bridge`` must be on sys.path (not just /app),
    else it fails with ModuleNotFoundError: No module named 'db'.
    """
    mod = f"module={module!r}, " if module else ""
    subprocess.run(
        ["docker", "exec", "-i", "archie_platform", "python3", "-c",
         "import sys; sys.path[:0]=['/app','/mnt/archie_brain','/mnt/archie_brain/ai_bridge']; "
         "from services.codex_promote_service import promote_codex_pr; "
         f"print(promote_codex_pr({int(pr_num)}, {mod}title='Codex task #{int(task_id)}'))"],
        timeout=60, check=False,
    )


def main() -> int:
    dry = "--dry-run" in sys.argv[1:]
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another codex-delegation-worker is running")
        return 0

    task = claim_one()
    if not task:
        print("no deferred codex tasks")
        return 0
    tid = task["id"]
    prompt = compose_prompt(task)
    print(f"claimed codex task #{tid} (project {task['project_id'] or 'n/a'})")

    if dry:
        print("--- composed prompt ---")
        print(prompt)
        set_status(tid, "deferred")  # release for a real run
        print(f"[dry-run] released task #{tid} back to deferred")
        return 0

    # Run the sandboxed Codex runner (pushes a codex/* branch on success).
    r = subprocess.run([RUNNER, prompt], capture_output=True, text=True, timeout=RUNNER_TIMEOUT)
    out = (r.stdout or "") + (r.stderr or "")
    # Persist the FULL runner output — the runner's scope-guard / gate decisions
    # are essential for debugging a blocked run and must not be truncated away.
    logpath = f"/tmp/codex-delegation-{tid}.log"
    try:
        with open(logpath, "w") as fh:
            fh.write(out)
    except Exception:
        pass
    m = BRANCH_RE.search(out)
    branch = m.group(0) if m else None
    # run-codex-task.sh prints "PR #N created: <url>" on success.
    mp = PR_RE.search(out)
    pr_num = int(mp.group(1)) if mp else None
    if not branch or not pr_num:
        set_status(tid, "blocked")
        print(f"codex #{tid}: no PR opened → blocked (full log: {logpath})\n{out[-500:]}")
        return 0

    set_status(tid, "in_progress", {"codex_pr": pr_num, "codex_branch": branch})
    if pr_num:
        queue_promote(pr_num, tid)
        print(f"codex #{tid} → PR #{pr_num} ({branch}); Telegram promote queued")
    else:
        print(f"codex #{tid}: branch {branch} pushed but PR open failed:\n{prout[-400:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
