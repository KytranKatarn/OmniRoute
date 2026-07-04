#!/usr/bin/env python3
"""
Estimate PRE-MEASUREMENT Claude Code token usage (the build-out story)
======================================================================
Claude Code auto-deletes transcripts older than ~30 days (cleanupPeriodDays),
so real per-message token data only exists from 2026-05-03 onward. The platform
was built mostly by Claude Code well before that (project origin 2025-12-17).

This script APPROXIMATES the missing Jan–Apr 2026 Claude output tokens from two
independent activity proxies and BLENDS them, so the Token Economy tab can honestly
show "cloud built this from here" without fabricating precision:

  proxy A — lines of code inserted/month (git numstat)
  proxy B — commits/month (git log)

Both are scaled by ratios measured from the REAL window (2026-05-03+):
  tokens_per_line   = real_claude_output_tokens / lines_inserted_in_window
  tokens_per_commit = real_claude_output_tokens / commits_in_window
  monthly_estimate  = mean(lines_m * tokens_per_line, commits_m * tokens_per_commit)

Rows are written to task_execution_log tagged request_metadata.token_source=
'estimated_historical' — kept as a SEPARATE chart series, NEVER summed into the
measured local/external headline (the token-usage endpoint excludes it from real
sums and includes it only in the dotted 'estimated' line).

HONESTY CAVEATS (also stored in each row's metadata):
  - tokens/line and tokens/commit are rough — Claude also reasons/debugs/writes
    non-code, and lines churn/delete. This is order-of-magnitude, not exact.
  - git history starts at repo-init 2026-01-26. The Jan-26 initial commit dumps the
    whole pre-repo codebase (built Dec 17 → Jan), so January's estimate is spread
    across Dec 17 → Jan 31 (the genesis window) rather than invented as a separate
    December figure. Daily spread also avoids single-day chart spikes.

Runs on the HOST (needs the git repo + DB via docker exec). Idempotent: each run
deletes prior estimated_historical rows and recomputes.

Usage:
  python3 scripts/estimate_historical_claude_tokens.py            # write to DB
  python3 scripts/estimate_historical_claude_tokens.py --dry-run  # print only
"""

import datetime as dt
import json
import subprocess
import sys

# Date range each month's estimate is SPREAD across (daily rows → smooth chart, no
# single-day spikes). January is spread back to the 2025-12-17 origin: the Jan-26
# initial commit (~444k lines) is the whole pre-repo codebase built Dec 17→Jan, so
# attributing it across the genesis window is more accurate than cramming it into
# January — and it extends the ALL chart back to December.
MONTH_RANGES = {
    "2026-01": ("2025-12-17", "2026-01-31"),
    "2026-02": ("2026-02-01", "2026-02-28"),
    "2026-03": ("2026-03-01", "2026-03-31"),
    "2026-04": ("2026-04-01", "2026-04-30"),
}

# CAPACITY-CEILING token estimate (NOT lines×ratio). These are conservative, realistic
# Claude OUTPUT-token monthly totals for the early period — bounded by the account caps
# AND by how little got used when AI was brand new (exploratory, copy-paste workflow).
# Max 20× started ~May 2026, so ALL of Dec–Apr was capacity-limited (Dec 1× Pro,
# Jan–Feb 2× parallel). Far below the theoretical ceilings. Tweak freely.
#   key window (per MONTH_RANGES) -> monthly Claude output tokens
CAPACITY_TOKENS = {
    "2026-01": 1_800_000,  # Dec 17→Jan 31 (46d): 1× Pro fresh + 2× ramping, ~40k/day avg
    "2026-02": 1_800_000,  # Feb (28d): 2× parallel, ~65k/day
    "2026-03": 2_900_000,  # Mar (31d): heavier, ~95k/day
    "2026-04": 3_600_000,  # Apr (30d): heaviest pre-Max, ~120k/day
}

REPO = "/mnt/archie_brain"
MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04"]  # measured window starts 2026-05-03
MEASURED_SINCE = "2026-05-03"
ORIGIN = "2025-12-17"
SOURCE_TAG = "estimated_historical"


def _git(args):
    return subprocess.run(["git", "-C", REPO] + args, text=True, capture_output=True).stdout


def lines_by_month(since):
    """{month: lines_inserted} from git numstat."""
    out = _git(["log", f"--since={since}-01", "--pretty=C%ad", "--date=format:%Y-%m", "--numstat"])
    cur, agg = None, {}
    for ln in out.splitlines():
        if ln.startswith("C"):
            cur = ln[1:]
        elif ln and ln[0].isdigit():
            ins = ln.split("\t")[0]
            if ins.isdigit():
                agg[cur] = agg.get(cur, 0) + int(ins)
    return agg


def commits_by_month(since):
    out = _git(["log", f"--since={since}-01", "--pretty=%ad", "--date=format:%Y-%m"])
    agg = {}
    for ln in out.splitlines():
        ln = ln.strip()
        if ln:
            agg[ln] = agg.get(ln, 0) + 1
    return agg


def measured_window_proxies():
    """lines + commits inserted in the real measured window (for the ratios)."""
    ins = _git(["log", f"--since={MEASURED_SINCE}", "--pretty=tformat:", "--numstat"])
    lines = sum(int(x.split("\t")[0]) for x in ins.splitlines() if x and x[0].isdigit() and x.split("\t")[0].isdigit())
    commits = len([x for x in _git(["log", f"--since={MEASURED_SINCE}", "--pretty=%h"]).splitlines() if x.strip()])
    return lines, commits


def real_claude_output_tokens():
    sql = "SELECT COALESCE(SUM(tokens_used),0) FROM task_execution_log WHERE request_metadata->>'source'='claude_code_cli';"
    out = subprocess.run(
        ["docker", "exec", "-i", "archie_database", "psql", "-U", "archie", "-d", "archie", "-t", "-A"],
        input=sql,
        text=True,
        capture_output=True,
    ).stdout.strip()
    try:
        return int(out)
    except ValueError:
        return 0


def main():
    dry = "--dry-run" in sys.argv
    real_tok = real_claude_output_tokens()
    mlines, mcommits = measured_window_proxies()
    if not (real_tok and mlines and mcommits):
        print(
            f"[hist-est] missing anchors (real_tok={real_tok}, lines={mlines}, commits={mcommits}) — abort",
            file=sys.stderr,
        )
        return 1
    lbm = lines_by_month(MONTHS[0])  # git lines (for the impact 'lines built' metric only)

    rows = []
    total = 0
    print(f"[hist-est] capacity-ceiling method | real measured output (May+): {real_tok:,}")
    for m in MONTHS:
        lines = lbm.get(m, 0)
        blended = CAPACITY_TOKENS.get(m, 0)  # conservative capacity-bounded monthly tokens
        total += blended
        print(f"  {m}: {lines:,} git lines | capacity-est tokens = {blended:,}")
        s, e = MONTH_RANGES.get(m, (f"{m}-01", f"{m}-28"))
        sd, ed = dt.date.fromisoformat(s), dt.date.fromisoformat(e)
        days = [sd + dt.timedelta(days=i) for i in range((ed - sd).days + 1)]
        per_day = blended // len(days)
        remainder = blended - per_day * len(days)  # keep the monthly total exact
        meta = {
            "source": SOURCE_TAG,
            "token_source": SOURCE_TAG,
            "method": "capacity-ceiling: conservative daily Claude output under 1x/2x account caps (AI was new); spread daily",
            # per-day share so the impact endpoint's SUM(lines_inserted) over daily
            # rows returns the true monthly/total git lines (not days×monthly).
            "lines_inserted": round(lines / len(days)) if days else 0,
            "month_lines": lines,
            "monthly_tokens_est": blended,
            "month": m,
            "spread_range": [s, e],
            "spread_days": len(days),
            "note": "rough capacity-limited estimate; Dec 1x Pro + Jan-Feb 2x parallel + DeepSeek(web) + hand-written; Max 20x ~May; not measured",
        }
        meta_json = json.dumps(meta)
        mid = len(days) // 2
        for idx, day in enumerate(days):
            tok = per_day + (remainder if idx == mid else 0)
            rows.append((f"{day.isoformat()} 12:00:00", tok, meta_json))

    sql = ["BEGIN;", f"DELETE FROM task_execution_log WHERE request_metadata->>'token_source' = '{SOURCE_TAG}';"]
    vals = []
    for ts, tok, meta in rows:
        meta_sql = "'" + meta.replace("'", "''") + "'"
        vals.append(
            f"(NULL, 'Claude (CLI)', 'claude (historical est)', 'anthropic', 'contract', 'cli_session', "
            f"0, {tok}, {tok}, true, '{ts}', {meta_sql}::jsonb)"
        )
    sql.append(
        "INSERT INTO task_execution_log (agent_id, agent_name, model_used, provider, worker_type, capability, "
        "prompt_tokens, completion_tokens, tokens_used, success, created_at, request_metadata) VALUES"
    )
    sql.append(",\n".join(vals) + ";")
    sql.append("COMMIT;")
    sql_text = "\n".join(sql)
    print(f"[hist-est] TOTAL estimated historical output tokens (Jan–Apr 2026): {total:,} | origin {ORIGIN}")

    if dry:
        print(sql_text)
        return 0
    proc = subprocess.run(
        ["docker", "exec", "-i", "archie_database", "psql", "-U", "archie", "-d", "archie", "-v", "ON_ERROR_STOP=1"],
        input=sql_text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print("[hist-est] psql FAILED:\n" + proc.stderr, file=sys.stderr)
        return 1
    print("[hist-est] DB updated OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
