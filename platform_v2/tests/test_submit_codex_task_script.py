"""Regression pins for scripts/agents/submit-codex-task.sh hardening.

Each pin is a defect found in the 2026-10-19 security review:
Codex-controlled file names were interpolated into `python3 -c` (host code execution) and
word-split; the worktree prune swallowed its own DB failure and could delete active worktrees.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agents" / "submit-codex-task.sh"
SRC = SCRIPT.read_text()


def test_script_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_file_names_are_never_interpolated_into_python():
    assert "'$CHANGED'" not in SRC and '"$CHANGED"' not in SRC.split("python3 -c", 1)[-1].split('")"', 1)[0]
    assert ".split()" not in SRC  # whitespace split cut 'a b.py' in two
    assert "CHANGED_FILE" in SRC and "sort -zu" in SRC and "diff -z" in SRC


def test_staging_is_limited_to_the_checked_paths():
    assert 'git -C "$WT" add -A' not in SRC
    assert 'xargs -0 -a "$CHANGED_FILE"' in SRC


def test_prune_does_not_swallow_the_query_failure():
    block = SRC.split("Prune old worktrees", 1)[1].split("Create worktree AFTER", 1)[0]
    assert "|| true)" not in block  # the old `|| true)"` hid the exit status
    assert "metadata->>'codex_branch'" in block  # the unquoted key was a SQL error
    assert "${branch#codex/}" in block  # find -name can never contain a slash
    assert "skipping prune (fail closed)" in block


def test_container_and_task_hardening():
    assert "no-new-privileges" in SRC and "--pids-limit" in SRC
    assert re.search(r"case \"\$TASK\" in -\*\)", SRC)
    assert 'LOCK_FILE="/tmp/' not in SRC
