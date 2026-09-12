"""The opencode lane's scope config denies what it must deny (#6736).

config/agents/opencode.yaml is the ONLY thing standing between a third-party coding
agent and the rest of the platform. It is read by the same guard as codex
(services/agents/codex_scope.check_diff_paths), so this pins the CONFIG, not the guard.

Written after a live probe that did NOT prove what it looked like it proved: asked to
edit platform_v2/app.py, opencode read the scope config in the repo and refused on its
own, even flagging the prompt as suspicious. Excellent behaviour — and it meant no
out-of-scope path ever reached the guard, so the guard was still unproven. Model
self-restraint is defence in depth, never the control. This is the control.
"""

import os

import pytest
import yaml

from services.agents.codex_scope import check_diff_paths


def _find_cfg():
    """Locate config/agents/opencode.yaml by walking up from this file.

    Not a fixed relative path: the container mounts only platform_v2 at /app, so the
    repo-root config/ is simply not there, and a hardcoded ../../ resolves to /config
    and raises FileNotFoundError on all 21 cases. Walk up, then fall back to the known
    checkout, and FAIL loudly if neither works — a scope test that cannot find the
    scope must not look like a pass.
    """
    here = os.path.abspath(os.path.dirname(__file__))
    while True:
        candidate = os.path.join(here, "config", "agents", "opencode.yaml")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    fallback = "/mnt/archie_brain/config/agents/opencode.yaml"
    if os.path.exists(fallback):
        return fallback
    raise FileNotFoundError(
        "config/agents/opencode.yaml not found. Run this where the repo ROOT is "
        "available — the platform container mounts only platform_v2 at /app."
    )


@pytest.fixture(scope="module")
def cfg():
    with open(_find_cfg()) as fh:
        return yaml.safe_load(fh)["opencode"]


def _blocked(path, cfg):
    return bool(check_diff_paths([path], cfg))


# ---------------------------------------------------------------------------
# what the lane is FOR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "platform_v2/tests/test_anything.py",
        "platform_v2/tools/fitness/routes.py",
        "platform_v2/tools/therapy/services/x.py",
        "platform_v2/services/time_utils.py",
    ],
)
def test_in_scope_paths_are_allowed(path, cfg):
    """A scope that blocks everything is as useless as one that blocks nothing."""
    assert not _blocked(path, cfg), f"{path} should be editable by the lane"


# ---------------------------------------------------------------------------
# what it must never touch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "platform_v2/app.py",  # the whole Flask app
        "platform_v2/services/agent_service.py",  # single-writer for the agents table
        "platform_v2/services/delegation_service.py",
        "ai_bridge/archie_bridge.py",
        "docker-compose.yml",
        ".env",
        "platform_v2/.env",
        "scripts/dr/failover.sh",  # flips production DNS
        ".github/workflows/ci.yml",
    ],
)
def test_out_of_scope_paths_are_blocked(path, cfg):
    assert _blocked(path, cfg), f"{path} MUST be blocked for the lane"


# ---------------------------------------------------------------------------
# the lane must not edit its own cage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "config/agents/opencode.yaml",  # its own scope
        "config/agents/codex.yaml",  # or anyone else's
        "scripts/agents/run-opencode-task.sh",  # the runner that gates it
        "scripts/agents/opencode-lane-sync.sh",
        "opencode/Dockerfile.terminal",  # the image it runs in
    ],
)
def test_lane_cannot_widen_its_own_scope(path, cfg):
    """An agent that can edit its own allowlist has no allowlist.

    This is the one class where a scope bug is self-amplifying: widen the config in
    one PR and every later PR is unbounded.

    ⚠️ What actually blocks these is DENY-BY-DEFAULT — none of them appear in
    allowed_paths. Measured: deleting the `config/agents/*` entry from blocked_globs
    leaves them blocked all the same, so that glob is belt-and-braces, not the
    control. The test is still worth having: it pins the OUTCOME, which is what
    matters, and it would catch someone adding one of these to allowed_paths.
    """
    assert _blocked(path, cfg), f"{path} MUST be blocked — it is the lane's own cage"


# ---------------------------------------------------------------------------
# the config itself must stay honest
# ---------------------------------------------------------------------------


def test_deny_by_default(cfg):
    """An unlisted path is denied. Without this the allowlist means nothing."""
    assert _blocked("some/path/nobody/listed.py", cfg)


def test_scope_is_not_empty(cfg):
    assert cfg.get("allowed_paths"), "an empty allowlist makes the lane useless"
    assert cfg.get("blocked_globs"), "blocked_globs is the backstop inside allowed dirs"


def test_file_cap_is_sane(cfg):
    cap = cfg.get("max_files_changed")
    assert isinstance(cap, int) and 0 < cap <= 50, f"implausible max_files_changed: {cap}"
