#!/bin/bash
# ARCHIE Session Stats — reads local Claude Code data to estimate session metrics

python3 << 'PYSCRIPT'
import json, os, subprocess
from datetime import datetime
from pathlib import Path

home = os.path.expanduser("~")
sessions_dir = Path(home) / ".claude" / "sessions"
history_file = Path(home) / ".claude" / "history.jsonl"
settings_file = Path("/mnt/archie_brain/.claude/settings.json")
creds_file = Path(home) / ".claude" / ".credentials.json"

# Find most recent session
sessions = sorted(sessions_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
if not sessions:
    print(json.dumps({"error": "No session found"}))
    exit()

with open(sessions[0]) as f:
    session = json.load(f)

session_id = session.get("sessionId", "")
started_ms = session.get("startedAt", 0)
started = datetime.fromtimestamp(started_ms / 1000)
now = datetime.now()
elapsed = now - started
hours = int(elapsed.total_seconds() // 3600)
minutes = int((elapsed.total_seconds() % 3600) // 60)
total_mins = int(elapsed.total_seconds() // 60)

# Count messages for this session
msg_count = 0
if history_file.exists():
    with open(history_file) as f:
        for line in f:
            if session_id in line:
                msg_count += 1

# Plan info from credentials
plan_type = "unknown"
rate_tier = "unknown"
if creds_file.exists():
    try:
        with open(creds_file) as f:
            creds = json.load(f)
        oauth = creds.get("claudeAiOauth", {})
        plan_type = oauth.get("subscriptionType", "unknown")
        rate_tier = oauth.get("rateLimitTier", "unknown")
    except Exception:
        pass

# Count active plugins
active_plugins = 0
if settings_file.exists():
    with open(settings_file) as f:
        s = json.load(f)
        active_plugins = sum(1 for v in s.get("enabledPlugins", {}).values() if v)

# Count rules files
rules_dir = Path("/mnt/archie_brain/.claude/rules")
rules_count = len(list(rules_dir.glob("*.md"))) if rules_dir.exists() else 0

# Git stats
try:
    r = subprocess.run(["git", "log", "--oneline", "--since=6 hours ago"],
                       capture_output=True, text=True, cwd="/mnt/archie_brain", timeout=5)
    commit_count = len(r.stdout.strip().split("\n")) if r.stdout.strip() else 0
    r2 = subprocess.run(["git", "diff", "--shortstat"],
                        capture_output=True, text=True, cwd="/mnt/archie_brain", timeout=5)
    diff_stat = r2.stdout.strip() if r2.stdout.strip() else "clean"
    r3 = subprocess.run(["git", "branch", "--show-current"],
                        capture_output=True, text=True, cwd="/mnt/archie_brain", timeout=5)
    branch = r3.stdout.strip()
except Exception:
    commit_count = 0
    diff_stat = "unknown"
    branch = "unknown"

# Real context tokens from JSONL session file
context_max = 1000000
est_total = 0
real_input = 0
real_output = 0
real_cache_read = 0
real_cache_create = 0
total_output_session = 0
tool_use_count = 0
assistant_turns = 0

# Find current session JSONL
jsonl_dir = Path(home) / ".claude" / "projects" / "-mnt-archie-brain"
jsonl_files = list(jsonl_dir.glob(f"{session_id}*.jsonl"))
if not jsonl_files:
    # Try partial match
    jsonl_files = sorted(jsonl_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True)[:1]

if jsonl_files:
    try:
        with open(jsonl_files[0]) as jf:
            for jline in jf:
                try:
                    entry = json.loads(jline.strip())
                    if entry.get("type") == "assistant":
                        usage = entry.get("message", {}).get("usage", {})
                        if usage:
                            assistant_turns += 1
                            real_input = usage.get("input_tokens", 0)
                            real_cache_read = usage.get("cache_read_input_tokens", 0)
                            real_cache_create = usage.get("cache_creation_input_tokens", 0)
                            total_output_session += usage.get("output_tokens", 0)
                        content = entry.get("message", {}).get("content", [])
                        if isinstance(content, list):
                            tool_use_count += sum(1 for c in content if isinstance(c, dict) and c.get("type") == "tool_use")
                except Exception:
                    pass
        # Last turn's context = input + cache_read + cache_create
        est_total = real_input + real_cache_read + real_cache_create
        real_output = total_output_session
    except Exception:
        est_total = 0

# Fallback to estimate if JSONL parsing failed
if est_total == 0:
    est_total = 15000 + (active_plugins * 800) + (msg_count * 500) + (msg_count * 300)

est_pct = round((est_total / context_max) * 100, 1)

# Session usage estimate (rate limit bucket)
# Max 20x resets every 5 hours. Rough: heavy msg = more API calls
session_reset_mins = 300  # 5 hours
session_elapsed_pct = min(99, round((total_mins / session_reset_mins) * 100))
session_remaining_mins = max(0, session_reset_mins - total_mins)

# Recommendation — 50% is the REAL limit (model degrades beyond this)
usable_pct = round((est_total / 500000) * 100, 1)  # 500K usable, not 1M

if est_pct >= 50:
    recommendation = "CONTEXT CRITICAL — quality degrading. /archie-save and start fresh NOW"
elif est_pct >= 40:
    recommendation = "Context heavy — wrap up current task, then /archie-save"
elif est_pct >= 30:
    recommendation = "Context building — plan remaining work carefully"
elif hours >= 4 or msg_count > 80:
    recommendation = "Extended session — consider /archie-save checkpoint"
elif hours >= 2 or msg_count > 40:
    recommendation = f"Active session — {commit_count} commits shipped"
elif msg_count < 10:
    recommendation = "Fresh session — plenty of room for work"
else:
    recommendation = "Healthy session — keep going"

print(json.dumps({
    "session_id": session_id[:8],
    "session_name": session.get("name", "unnamed"),
    "branch": branch,
    "started": started.strftime("%H:%M"),
    "elapsed": f"{hours}h {minutes}m",
    "elapsed_mins": total_mins,
    "messages": msg_count,
    "assistant_turns": assistant_turns,
    "tool_uses": tool_use_count,
    "commits": commit_count,
    "diff_stat": diff_stat,
    "active_plugins": active_plugins,
    "rules_files": rules_count,
    "context_tokens": est_total,
    "context_k": round(est_total / 1000),
    "context_max_k": context_max // 1000,
    "context_pct": est_pct,
    "usable_pct": usable_pct,
    "output_tokens": total_output_session,
    "output_k": round(total_output_session / 1000),
    "cache_read_k": round(real_cache_read / 1000),
    "cache_create_k": round(real_cache_create / 1000),
    "plan": plan_type,
    "rate_tier": rate_tier,
    "session_elapsed_pct": session_elapsed_pct,
    "session_remaining_mins": session_remaining_mins,
    "model": "Opus 4.6 (1M context)",
    "recommendation": recommendation,
}))
PYSCRIPT
