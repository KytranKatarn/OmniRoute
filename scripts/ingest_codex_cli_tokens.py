#!/usr/bin/env python3
"""
Ingest Codex CLI token usage into task_execution_log
=====================================================
Two token sources are merged:

SOURCE A — run logs (/mnt/archie_brain/logs/codex/*.json)
  Written by run-codex-task.sh via codex_telemetry.py after each task.
  Tokens are 0 in ChatGPT sign-in mode (estimated=True).

SOURCE B — session JSONL files (~/.codex/sessions/**/*.jsonl)
  The actual OpenAI API response objects flow through Codex's tool calls as
  JSON-in-string payloads inside function_call_output events.  They contain
  real "output_tokens" and "input_tokens" fields.
  - completion_tokens = SUM(output_tokens) across events  [unique per call — add]
  - prompt_tokens     = MAX(input_tokens) across events   [grows with context — take max]
  Source B overrides Source A when real token data is found (estimated=False).

Design:
  - One row per (day, model) in task_execution_log, idempotent (delete+reinsert).
  - provider='openai', worker_type='contract' (matches CHECK constraint).
  - Dedup key: request_metadata->>'source' = 'codex_code_cli'.
  - Processed session files tracked in LOGS_DIR/.ingested_sessions.json.

Usage:
  python3 scripts/ingest_codex_cli_tokens.py            # parse + write to DB
  python3 scripts/ingest_codex_cli_tokens.py --dry-run  # print SQL only

Cron:
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
SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
STATE_FILE = os.path.join(LOGS_DIR, ".ingested_sessions.json")
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


def parse_session_files(persist_state: bool = True):
    """Return {(day, model): {prompt, completion, runs, branches, estimated}}.

    Reads ~/.codex/sessions/**/*.jsonl.  Each file is one Codex task session.
    Token data lives inside JSON-in-string payloads in function_call_output events:
      completion_tokens = SUM(output_tokens)  — unique per API call, safe to add
      prompt_tokens     = MAX(input_tokens)   — grows with context, take max not sum

    Tracks processed files in STATE_FILE to avoid double-counting on re-runs.
    """
    if not os.path.isdir(SESSIONS_DIR):
        return {}

    # Load state: {filepath: mtime} so we skip already-ingested unchanged files.
    state: dict = {}
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except Exception:
            state = {}

    agg: dict = {}
    files = sorted(glob.glob(os.path.join(SESSIONS_DIR, "**", "*.jsonl"), recursive=True))
    new_state = dict(state)

    for fp in files:
        try:
            mtime = str(os.path.getmtime(fp))
        except OSError:
            continue
        if state.get(fp) == mtime:
            continue  # already ingested this exact file version

        # Parse filename for day: rollout-YYYY-MM-DDTHH-MM-SS-...
        basename = os.path.basename(fp)
        day = None
        m = re.match(r"^rollout-(\d{4})-(\d{2})-(\d{2})T", basename)
        if m:
            day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        completion_sum = 0
        prompt_max = 0
        model = "codex-phase-a"  # Phase A (ChatGPT sign-in) has no model field

        try:
            with open(fp, errors="ignore") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue

                    # Fallback day from first timestamp line
                    if day is None and d.get("timestamp"):
                        ts = d["timestamp"]
                        day = ts[:10]  # YYYY-MM-DD

                    p = d.get("payload", {})
                    pstr = json.dumps(p)

                    # session_meta may carry model
                    if d.get("type") == "session_meta" and p.get("model"):
                        raw_model = str(p["model"])
                        if MODEL_RE.match(raw_model):
                            model = raw_model

                    # Extract output_tokens (safe to sum — unique per response)
                    for hit in re.finditer(r'"output_tokens":\s*(\d+)', pstr):
                        completion_sum += int(hit.group(1))

                    # Extract input_tokens (context grows — take running max)
                    for hit in re.finditer(r'"input_tokens":\s*(\d+)', pstr):
                        v = int(hit.group(1))
                        if v > prompt_max:
                            prompt_max = v
        except Exception:
            continue

        if day is None or (completion_sum == 0 and prompt_max == 0):
            new_state[fp] = mtime
            continue

        key = (day, model)
        a = agg.setdefault(key, {"prompt": 0, "completion": 0, "runs": 0, "branches": [], "estimated": False})
        a["completion"] += completion_sum
        # prompt = max context window seen today across sessions
        if prompt_max > a["prompt"]:
            a["prompt"] = prompt_max
        a["runs"] += 1
        a["branches"].append(basename[:60])
        new_state[fp] = mtime

    # Persist state (skip during dry-run so re-running live still works)
    if persist_state:
        os.makedirs(LOGS_DIR, exist_ok=True)
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(new_state, f)
        except Exception:
            pass

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

    # Source A: run logs (0 tokens estimated, Phase A sign-in mode)
    agg = parse_run_logs() if os.path.isdir(LOGS_DIR) else {}

    # Source B: session JSONL files — real token counts from OpenAI API responses
    session_agg = parse_session_files(persist_state=not dry)

    # Merge: Source B overrides Source A for same (day, model) key
    for key, sb in session_agg.items():
        if key in agg:
            # Prefer real data; keep branches from both
            combined_branches = list({*agg[key].get("branches", []), *sb.get("branches", [])})
            agg[key] = {**agg[key], **sb, "branches": combined_branches[:20]}
        else:
            agg[key] = sb

    if not agg:
        print("[codex-ingest] no codex data found (run logs or session files) — nothing to do")
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
