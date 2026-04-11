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

# Estimate context tokens (1M window for Opus)
base_overhead = 15000
plugin_overhead = active_plugins * 800
conversation = msg_count * 500
tool_io = msg_count * 300
est_total = base_overhead + plugin_overhead + conversation + tool_io
context_max = 1000000
est_pct = round((est_total / context_max) * 100, 1)

# Session usage estimate (rate limit bucket)
# Max 20x resets every 5 hours. Rough: heavy msg = more API calls
session_reset_mins = 300  # 5 hours
session_elapsed_pct = min(99, round((total_mins / session_reset_mins) * 100))
session_remaining_mins = max(0, session_reset_mins - total_mins)

# Recommendation
if hours >= 4 or msg_count > 80:
    recommendation = "Extended session — consider /archie-save or /archie-end"
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
    "commits": commit_count,
    "diff_stat": diff_stat,
    "active_plugins": active_plugins,
    "rules_files": rules_count,
    "est_context_k": round(est_total / 1000),
    "context_max_k": context_max // 1000,
    "est_context_pct": est_pct,
    "plan": plan_type,
    "rate_tier": rate_tier,
    "session_elapsed_pct": session_elapsed_pct,
    "session_remaining_mins": session_remaining_mins,
    "model": "Opus 4.6 (1M context)",
    "recommendation": recommendation,
}))
PYSCRIPT
