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
  * Task prose is never interpolated into SQL. JSON uses hex-encoded UTF-8;
    IDs/statuses are validated. Every writeback matches the claimed attempt.
  * Attempt observations never certify Docker work has stopped. Replacement
    execution remains disabled until container lifecycle ownership is implemented.
  * Never auto-merge — promotion is a human Telegram approval.

Usage:
  codex-delegation-worker.py            # claim + run one task
  codex-delegation-worker.py --dry-run  # claim + compose + print, then release
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import uuid
from pathlib import Path

REPO = "/mnt/archie_brain"
RUNNER = f"{REPO}/scripts/agents/run-codex-task.sh"
LOCK = "/tmp/codex-delegation-worker.lock"
RUNNER_TIMEOUT = 1800  # matches codex.yaml max runtime (30 min)
BRANCH_RE = re.compile(r"codex/[a-z0-9-]+")
PR_RE = re.compile(r"PR #(\d+) created:")
GH = "/home/kytran/.local/bin/gh"


def psql(sql: str) -> str:
    """Run SQL in the DB container; return stripped -tA output (| separated)."""
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "archie_database",
            "psql",
            "-U",
            "archie",
            "-d",
            "archie",
            "-tA",
            "-F",
            "|",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    # psql -t still emits the DML command tag ("UPDATE 1", "INSERT 0 1", ...) on
    # its own line; strip those so they never leak into a claimed row's reason.
    lines = [
        ln for ln in r.stdout.splitlines() if not re.match(r"^(UPDATE|INSERT|DELETE|SELECT|MERGE)\s+\d", ln.strip())
    ]
    return "\n".join(lines).strip()


def _json_sql(value: dict) -> str:
    """Encode JSON without interpolating arbitrary text into a SQL literal."""
    encoded = json.dumps(value).encode().hex()
    return f"convert_from(decode('{encoded}', 'hex'), 'UTF8')::jsonb"


def worker_identity() -> dict:
    """Identify this poller incarnation; PID alone can be reused after a crash."""
    return {
        "id": str(uuid.uuid4()),
        "host": socket.gethostname(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "pid": os.getpid(),
        "process_start": Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19],
        "stop_confirmed": False,
    }


def claim_one() -> dict | None:
    """Atomically claim the oldest deferred codex_task (deferred → in_progress)."""
    attempt = worker_identity()
    out = psql(
        f"""
        UPDATE unified_tasks SET status='in_progress', updated_at=now(),
            metadata=coalesce(metadata,'{{}}'::jsonb)||jsonb_build_object(
                'codex_worker_attempt', {_json_sql(attempt)} || jsonb_build_object(
                    'claimed_at', now(), 'lease_expires_at', now()+interval '1800 seconds'))
        WHERE id = (
            SELECT id FROM unified_tasks
            WHERE status='deferred' AND delegation_args->>'capability'='codex_task'
              AND NOT (coalesce(metadata,'{{}}'::jsonb) ? 'codex_worker_attempt')
              AND (metadata->>'codex_pr') IS NULL  -- idempotency (#4422): never re-run a task that already opened a PR → no duplicate PRs
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
    return {
        "id": int(parts[0]),
        "project_id": parts[1].strip(),
        "reason": parts[2].strip(),
        "attempt_id": attempt["id"],
    }


def project_ctx(pid: str) -> str:
    if not pid:
        return ""
    return psql(
        "SELECT 'Project: '||name||coalesce(' — '||left(replace(description, E'\n',' '),400),'') "
        f"FROM unified_projects WHERE id={int(pid)};"
    )


def owns_attempt(task_id: int, attempt_id: str, status: str = "in_progress") -> bool:
    attempt_id = str(uuid.UUID(attempt_id))
    if status not in {"in_progress", "review"}:
        raise ValueError("Unsupported ownership status")
    return psql(
        f"SELECT id FROM unified_tasks WHERE id={int(task_id)} AND status='{status}' "
        f"AND metadata->'codex_worker_attempt'->>'id'='{attempt_id}';"
    ) == str(int(task_id))


def set_status(
    task_id: int,
    status: str,
    extra: dict | None = None,
    *,
    attempt_id: str,
    outcome: str = "runner_returned",
) -> bool:
    """CAS writeback. Terminal observation is NEVER proof that Docker work stopped.

    Each task has one durable attempt; replacement will use a new task. A deferred
    status alone cannot make a previously claimed task runnable again.
    """
    attempt_id = str(uuid.UUID(attempt_id))
    if status not in {"blocked", "review", "deferred"}:
        raise ValueError("Unsupported worker status")
    extra = extra or {}
    if set(extra) - {"codex_pr", "codex_branch"}:
        raise ValueError("Unsupported worker metadata")
    if "codex_pr" in extra and (type(extra["codex_pr"]) is not int or extra["codex_pr"] <= 0):
        raise ValueError("Invalid PR number")
    if "codex_branch" in extra and not BRANCH_RE.fullmatch(extra["codex_branch"]):
        raise ValueError("Invalid branch")
    if status == "deferred":
        if outcome != "dry_run" or extra:
            raise ValueError("Only a dry run may release its claim")
        metadata = "metadata-'codex_worker_attempt'"
    else:
        terminal = _json_sql({"outcome": outcome, "stop_confirmed": False})
        metadata = (
            f"metadata||{_json_sql(extra)}||jsonb_build_object('codex_worker_attempt', "
            f"(metadata->'codex_worker_attempt')||{terminal}||jsonb_build_object('observed_at',now()))"
        )
    out = psql(
        f"UPDATE unified_tasks SET status='{status}', metadata={metadata}, updated_at=now() "
        f"WHERE id={int(task_id)} AND status='in_progress' "
        f"AND metadata->'codex_worker_attempt'->>'id'='{attempt_id}' RETURNING id;"
    )
    return out == str(int(task_id))


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


def fallback_pr(branch: str, task_id: int, reason: str) -> int | None:
    """Recover a PR number when the runner pushed the branch but gh pr create failed.

    Step 1: gh pr list --head <branch> — PR may have been opened despite the
            runner printing an error (race / partial success).
    Step 2: gh pr create — open it ourselves with a minimal body.

    Returns the PR number as int, or None if both steps fail.
    """
    # Step 1 — look for an existing open PR on this branch
    try:
        r = subprocess.run(
            [
                GH,
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        existing = r.stdout.strip()
        if existing.isdigit():
            print(f"fallback_pr: found existing PR #{existing} for branch {branch}")
            return int(existing)
    except Exception as exc:
        print(f"fallback_pr: gh pr list error: {exc}")

    # Step 2 — create the PR ourselves
    title = f"feat(codex): task #{task_id} — {reason[:60]}"
    body = (
        f"## Codex (autonomous)\n\n"
        f"- **Task #{task_id}**: {reason}\n"
        f"- **Branch**: `{branch}`\n"
        f"- **Note**: PR created by delegation worker (runner gh-create failed)\n\n"
        f"## Test Plan\n- [ ] F.O.R.G.E. review passes\n- [ ] Deploy via `/merge-pr` after Telegram approval\n\n"
        f"🤖 Codex CLI (autonomous loop)"
    )
    try:
        r = subprocess.run(
            [GH, "pr", "create", "--head", branch, "--title", title, "--body", body],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # gh pr create prints the PR URL as the last line on success
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        m = re.search(r"/pull/(\d+)$", url)
        if m:
            pr_num = int(m.group(1))
            print(f"fallback_pr: created PR #{pr_num} for branch {branch}")
            return pr_num
        print(f"fallback_pr: gh pr create output: {r.stdout.strip()!r} | err: {r.stderr.strip()!r}")
    except Exception as exc:
        print(f"fallback_pr: gh pr create error: {exc}")

    return None


def queue_promote(pr_num: int, task_id: int, module: str | None = None) -> None:
    """Queue the Tier-2 Telegram approve/merge via the container service.

    promote_codex_pr imports ai_bridge.agent_loop, which does ``from db import``
    — so ``/mnt/archie_brain/ai_bridge`` must be on sys.path (not just /app),
    else it fails with ModuleNotFoundError: No module named 'db'.
    """
    mod = f"module={module!r}, " if module else ""
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "archie_platform",
            "python3",
            "-c",
            "import sys; sys.path[:0]=['/app','/mnt/archie_brain','/mnt/archie_brain/ai_bridge']; "
            "from services.codex_promote_service import promote_codex_pr; "
            f"print(promote_codex_pr({int(pr_num)}, {mod}title='Codex task #{int(task_id)}'))",
        ],
        timeout=60,
        check=False,
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
    attempt_id = task["attempt_id"]
    try:
        prompt = compose_prompt(task)
    except Exception:
        set_status(tid, "blocked", attempt_id=attempt_id, outcome="prompt_failed")
        raise
    print(f"claimed codex task #{tid} (project {task['project_id'] or 'n/a'})")

    if dry:
        print("--- composed prompt ---")
        print(prompt)
        released = set_status(tid, "deferred", attempt_id=attempt_id, outcome="dry_run")
        print(f"[dry-run] task #{tid} claim released: {released}")
        return 0

    # Run the sandboxed Codex runner (pushes a codex/* branch on success).
    # Recheck after prompt lookup; an operator may have cancelled this claim.
    if not owns_attempt(tid, attempt_id):
        return 0
    outcome = "runner_returned"
    try:
        r = subprocess.run([RUNNER, prompt], capture_output=True, text=True, timeout=RUNNER_TIMEOUT)
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills its direct child, NOT daemon-owned Docker work.
        # Preserve partial PR/branch evidence, but never start fallback on timeout.
        outcome = "runner_timeout_stop_unconfirmed"

        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")

        out = decoded(exc.stdout) + decoded(exc.stderr)
    except OSError:
        set_status(tid, "blocked", attempt_id=attempt_id, outcome="runner_start_failed")
        raise
    # Persist the FULL runner output — the runner's scope-guard / gate decisions
    # are essential for debugging a blocked run and must not be truncated away.
    logpath = f"/tmp/codex-delegation-{tid}-{attempt_id}.log"
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

    evidence = {}
    if branch:
        evidence["codex_branch"] = branch
    if pr_num:
        evidence["codex_pr"] = pr_num
    if outcome != "runner_returned":
        set_status(tid, "blocked", evidence, attempt_id=attempt_id, outcome=outcome)
        print(f"codex #{tid}: timeout; stop unconfirmed (full log: {logpath})")
        return 0

    # Branch pushed but gh pr create failed inside the runner — attempt recovery.
    if branch and not pr_num:
        if not owns_attempt(tid, attempt_id):
            return 0
        print(f"codex #{tid}: branch {branch} pushed but no PR in runner output — trying fallback")
        pr_num = fallback_pr(branch, tid, task["reason"])
        if pr_num:
            evidence["codex_pr"] = pr_num

    if not branch or not pr_num:
        set_status(tid, "blocked", evidence, attempt_id=attempt_id, outcome="pr_unconfirmed")
        print(f"codex #{tid}: no PR opened → blocked (full log: {logpath})\n{out[-500:]}")
        return 0

    # On SUCCESS, park the source task in a NON-reapable 'review' state (awaiting
    # the human Telegram promote). Leaving it 'in_progress' (bug #4422) let
    # reclaim_stale_delegations false-mark a SUCCESSFUL task 'blocked' after 2-3
    # idle cycles — which then got re-run → DUPLICATE PRs. The promote→merge
    # writeback (ai_bridge/agent_loop.py) flips 'review' → 'completed' on approval.
    written = set_status(tid, "review", evidence, attempt_id=attempt_id)
    if written and owns_attempt(tid, attempt_id, "review"):
        queue_promote(pr_num, tid)
        print(f"codex #{tid} → PR #{pr_num} ({branch}); Telegram promote queued")
    else:
        print(f"codex #{tid}: attempt superseded; writeback/promotion refused (log: {logpath})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
