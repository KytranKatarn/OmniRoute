#!/usr/bin/env python3
"""
Ingest Claude Code (CLI) token usage into task_execution_log
=============================================================
Claude Code is external compute (Anthropic) driven from this hub. Its per-message
token usage lives in the local transcripts at ~/.claude/projects/**/*.jsonl
(each assistant message carries message.usage). This makes Claude visible in the
Consciousness → Token Economy tab as an EXTERNAL contractor agent, alongside the
local fleet.

WHY a host script (not a platform job): the transcripts live on the HOST under the
operator's home dir, not inside the container. This runs on the host (cron, as the
operator) and writes to the DB via `docker exec -i archie_database psql`.

Design decisions (owner, 2026-06-02):
  - HEADLINE metric = OUTPUT tokens (apples-to-apples with the fleet's eval_count
    output). input / cache kept in request_metadata, never summed into the headline.
  - Granularity = one row per (day, model). Idempotent: each run deletes prior
    source='claude_code_cli' rows and re-inserts the full history (~120 rows).
  - provider='anthropic' (the Token Economy tab already classifies this as EXTERNAL).

Usage:
  python3 scripts/ingest_claude_cli_tokens.py            # parse + write to DB
  python3 scripts/ingest_claude_cli_tokens.py --dry-run  # print SQL only
"""

import datetime as _dt
import glob
import json
import os
import re
import subprocess
import sys

PROJECTS_ROOT = os.path.expanduser("~/.claude/projects")
SOURCE_TAG = "claude_code_cli"
AGENT_NAME = "Claude (CLI)"
PROVIDER = "anthropic"
WORKER_TYPE = "contract"
CAPABILITY = "cli_session"
MODEL_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")  # sanitise model names for SQL


def parse_transcripts():
    """Return {(day, model): {output, input, cache_read, cache_creation, msgs, sessions}}."""
    agg = {}
    files = glob.glob(os.path.join(PROJECTS_ROOT, "**", "*.jsonl"), recursive=True)
    for fp in files:
        session_id = os.path.splitext(os.path.basename(fp))[0]
        try:
            with open(fp, "r", errors="ignore") as fh:
                for line in fh:
                    if '"usage"' not in line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    msg = ev.get("message") or {}
                    usage = msg.get("usage") or {}
                    if not usage:
                        continue
                    model = msg.get("model") or ev.get("model") or ""
                    if not model.startswith("claude"):
                        continue  # skip <synthetic> / local-model echoes
                    ts = ev.get("timestamp") or ev.get("ts")
                    if not ts:
                        continue
                    try:
                        day = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
                    except Exception:
                        continue
                    key = (day, model)
                    a = agg.setdefault(
                        key,
                        {"output": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "msgs": 0, "sessions": set()},
                    )
                    a["output"] += usage.get("output_tokens", 0) or 0
                    a["input"] += usage.get("input_tokens", 0) or 0
                    a["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                    a["cache_creation"] += usage.get("cache_creation_input_tokens", 0) or 0
                    a["msgs"] += 1
                    a["sessions"].add(session_id)
        except Exception:
            continue
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
        meta = {
            "source": SOURCE_TAG,
            "input_tokens": a["input"],
            "cache_read_tokens": a["cache_read"],
            "cache_creation_tokens": a["cache_creation"],
            "messages": a["msgs"],
            "sessions": len(a["sessions"]),
            "day": day,
        }
        created_at = f"{day} 12:00:00"  # naive UTC, lands in the right day bucket
        values.append(
            "(NULL, {an}, {model}, {prov}, {wt}, {cap}, {inp}, {out}, {out2}, true, {ts}, {meta}::jsonb)".format(
                an=_sql_str(AGENT_NAME),
                model=_sql_str(model),
                prov=_sql_str(PROVIDER),
                wt=_sql_str(WORKER_TYPE),
                cap=_sql_str(CAPABILITY),
                inp=a["input"],
                out=a["output"],
                out2=a["output"],
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
    if not os.path.isdir(PROJECTS_ROOT):
        print(f"[claude-ingest] transcripts dir not found: {PROJECTS_ROOT}", file=sys.stderr)
        return 1
    agg = parse_transcripts()
    if not agg:
        print("[claude-ingest] no claude usage found — nothing to do")
        return 0
    sql = build_sql(agg)
    total_out = sum(a["output"] for a in agg.values())
    days = sorted({d for (d, _m) in agg.keys()})
    print(
        f"[claude-ingest] {len(agg)} (day,model) rows | {len(days)} days "
        f"({days[0]}..{days[-1]}) | output tokens: {total_out:,}"
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
        print("[claude-ingest] psql FAILED:\n" + proc.stderr, file=sys.stderr)
        return 1
    print("[claude-ingest] DB updated OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
