#!/usr/bin/env python3
"""
Ingest Codex CLI token usage into task_execution_log
=====================================================
Codex CLI (OpenAI, ChatGPT sign-in mode) is external compute driven from this hub.
Each run of scripts/agents/run-codex-task.sh writes a JSON log to
/mnt/archie_brain/logs/codex/<timestamp>_<branch>.json containing the telemetry
already written to task_execution_log via services/agents/codex_telemetry.py.

WHY a host script (not a platform job): run-codex-task.sh executes on the HOST
(not inside the container), so its JSON logs live on the host filesystem. This
mirrors how scripts/ingest_claude_cli_tokens.py works for Claude Code sessions.

Design decisions:
  - One row per (day, model) in task_execution_log, idempotent (delete+reinsert).
  - provider='openai', worker_type='contract' (matches CHECK constraint).
  - HEADLINE metric = tokens_used (prompt + completion). In sign-in mode Codex
    does not expose per-call token counts, so tokens are 0 (estimated=True in meta).
    If Codex ever emits usage lines, parse them in run-codex-task.sh and include
    them in the JSON log.
  - Dedup key: request_metadata->>'source' = 'codex_code_cli' (same pattern as
    Claude ingest's 'claude_code_cli').

Usage:
  python3 scripts/ingest_codex_cli_tokens.py            # parse + write to DB
  python3 scripts/ingest_codex_cli_tokens.py --dry-run  # print SQL only

Cron (add after Kytran installs + signs in Codex):
  45 3 * * * /usr/bin/python3 /mnt/archie_brain/scripts/ingest_codex_cli_tokens.py >> /tmp/codex_token_ingest.log 2>&1
"""

import datetime as _dt
import glob
import json
import os
import re
import subprocess
import sys

LOGS_DIR = os.path.expanduser("/mnt/archie_brain/logs/codex")
SOURCE_TAG = "codex_code_cli"
AGENT_NAME = "Codex (CLI)"
PROVIDER = "openai"
WORKER_TYPE = "contract"
CAPABILITY = "cli_session"
MODEL_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")  # sanitise model names for SQL


def parse_run_logs():
    """Return {(day, model): {prompt, completion, runs, branches, estimated}}.

    Reads the JSON run logs written by run-codex-task.sh via codex_telemetry.py.
    Each file: {task_execution_log_id, branch, model, tokens, success, meta}.
    token counts are 0 in sign-in mode (estimated=True in meta).
    """
    agg = {}
    files = glob.glob(os.path.join(LOGS_DIR, "*.json"))
    for fp in files:
        try:
            with open(fp, "r", errors="ignore") as fh:
                data = json.load(fh)
        except Exception:
            continue

        model = data.get("model") or "gpt-5-codex"
        if not MODEL_RE.match(model):
            continue

        # Derive day from the filename timestamp prefix (YYYYMMDD_HHMMSS_...)
        basename = os.path.basename(fp)
        day = None
        m = re.match(r"^(\d{4})(\d{2})(\d{2})_", basename)
        if m:
            day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            # fallback: file mtime
            mtime = os.path.getmtime(fp)
            day = _dt.datetime.utcfromtimestamp(mtime).date().isoformat()

        meta_inner = data.get("meta") or {}
        prompt_tokens = meta_inner.get("prompt_tokens", 0) or 0
        completion_tokens = meta_inner.get("completion_tokens", 0) or 0
        tokens = data.get("tokens") or (prompt_tokens + completion_tokens)
        estimated = meta_inner.get("estimated_tokens", True)
        branch = data.get("branch") or ""

        key = (day, model)
        a = agg.setdefault(
            key,
            {
                "prompt": 0,
                "completion": 0,
                "runs": 0,
                "branches": [],
                "estimated": estimated,
            },
        )
        a["prompt"] += prompt_tokens
        a["completion"] += completion_tokens
        # tokens field is total when prompt/completion aren't broken out
        if tokens and not (prompt_tokens or completion_tokens):
            a["prompt"] += tokens
        a["runs"] += 1
        if branch:
            a["branches"].append(branch)
        # if any run has real token counts, mark as not estimated
        if not estimated:
            a["estimated"] = False

    return agg


def _sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def build_sql(agg):
    lines = [
        "BEGIN;",
        f"DELETE FROM task_execution_log WHERE request_metadata->>'source' = '{SOURCE_TAG}';",
    ]
    values = []
    for (day, model), a in sorted(agg.items()):
        if not MODEL_RE.match(model):
            continue
        total = a["prompt"] + a["completion"]
        meta = {
            "source": SOURCE_TAG,
            "prompt_tokens": a["prompt"],
            "completion_tokens": a["completion"],
            "runs": a["runs"],
            "branches": a["branches"][:20],  # cap list length
            "estimated_tokens": a["estimated"],
            "day": day,
        }
        created_at = f"{day} 12:00:00"  # naive UTC, lands in the right day bucket
        values.append(
            "(NULL, {an}, {model}, {prov}, {wt}, {cap}, {inp}, {out}, {total}, true, {ts}, {meta}::jsonb)".format(
                an=_sql_str(AGENT_NAME),
                model=_sql_str(model),
                prov=_sql_str(PROVIDER),
                wt=_sql_str(WORKER_TYPE),
                cap=_sql_str(CAPABILITY),
                inp=a["prompt"],
                out=a["completion"],
                total=total,
                ts=_sql_str(created_at),
                meta=_sql_str(json.dumps(meta)),
            )
        )
    if values:
        lines.append(
            "INSERT INTO task_execution_log "
            "(agent_id, agent_name, model_used, provider, worker_type, capability, "
            "prompt_tokens, completion_tokens, tokens_used, success, created_at, request_metadata) VALUES"
        )
        lines.append(",\n".join(values) + ";")
    lines.append("COMMIT;")
    return "\n".join(lines)


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.isdir(LOGS_DIR):
        print(f"[codex-ingest] logs dir not found: {LOGS_DIR} — no runs yet", file=sys.stderr)
        return 0  # not an error; Codex just hasn't run yet
    agg = parse_run_logs()
    if not agg:
        print("[codex-ingest] no codex run logs found — nothing to do")
        return 0
    sql = build_sql(agg)
    total_tokens = sum(a["prompt"] + a["completion"] for a in agg.values())
    total_runs = sum(a["runs"] for a in agg.values())
    days = sorted({d for (d, _m) in agg.keys()})
    estimated = any(a["estimated"] for a in agg.values())
    print(
        f"[codex-ingest] {len(agg)} (day,model) rows | {len(days)} days "
        f"({days[0]}..{days[-1]}) | {total_runs} runs | tokens: {total_tokens:,}"
        + (" (estimated)" if estimated else "")
    )
    if dry:
        print(sql)
        return 0
    proc = subprocess.run(
        ["docker", "exec", "-i", "archie_database", "psql", "-U", "archie", "-d", "archie", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print("[codex-ingest] psql FAILED:\n" + proc.stderr, file=sys.stderr)
        return 1
    print("[codex-ingest] DB updated OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
