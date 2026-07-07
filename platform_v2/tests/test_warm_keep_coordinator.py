"""Regression test — the cluster keep-warm registry follows the configured
coordinator model instead of hardcoding it (Task 6, coordinator-lane Phase 1).

Source-level check: `AgentLoop._keep_cluster_models_warm()` can't be unit-booted
(APScheduler + Flask app context + a live DB), so this asserts on the source
text directly. Repo-root resolution mirrors test_no_raw_api_generate.py:
inside the container, platform_v2/ mounts at /app but ai_bridge/ only exists
at /mnt/archie_brain/ai_bridge — a bare relative "ai_bridge/agent_loop.py"
path resolves against the wrong cwd there.
"""

from __future__ import annotations

from pathlib import Path


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "ai_bridge" / "agent_loop.py").exists():
            return parent
    # Absolute fallback for the container mount point
    return Path("/mnt/archie_brain")


REPO = _find_repo_root()
SRC = (REPO / "ai_bridge" / "agent_loop.py").read_text()


def test_warm_keep_uses_configured_coordinator_model():
    assert "get_coordinator_model()" in SRC, "keep-warm registry must include the configured coordinator model"
