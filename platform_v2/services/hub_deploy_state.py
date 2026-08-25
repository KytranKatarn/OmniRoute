"""What the HUB is actually running — the volume-mounted half of deploy provenance (#5867).

## Why this exists

`deploy_drift_check.py` answers the question for IMAGE-BAKED products: the container holds
a `COPY .` snapshot, so you compare its baked SHA against the source head. That covers the
9 standalones and nothing else.

`archie_platform` and `archie_scheduler` are the opposite shape. They **bind-mount the
working tree** (`platform_v2 -> /app`), so:

  * a GitHub merge deploys **NOTHING** — `git checkout main && git pull` IS the deploy step
  * whatever branch the host tree happens to sit on is what the platform SERVES
  * even after a pull, a long-lived process keeps the modules it imported at boot until
    it restarts

None of those three were visible anywhere. Measured 2026-08-25: the live platform served
`feat/backup-docs` — four unmerged commits — for an entire working session, which was
deliberate but relied entirely on remembering it.

## The four questions, and why each is separate

  branch      Is the tree even on main? A feature branch means the platform is serving
              unmerged code to every user.
  behind      Is main ahead of the tree? Then a merge has happened and was never pulled.
  restarted   Is the code on disk NEWER than the running process? Then it is pulled but
              not loaded — the trap `deploy-provenance.md` prescribes ORDERING for
              (commit time vs container start), because grepping a bind-mounted file
              always shows the current text and proves nothing about the process.
  dirty       Uncommitted edits mean the running code is in no commit at all.

## Honesty constraints

- Every unreadable input yields `unknown`, NEVER a confident `in_sync`. A monitor that
  cannot see is not a monitor that approves.
- `behind_main` is measured against the LAST FETCHED `origin/main`. This process does not
  fetch (that is a network side effect on a shared repo), so a stale fetch UNDER-reports
  drift. `origin_fetched_age_hours` is returned alongside so the caller can see how much
  to trust it — reporting the number without its freshness would be the same mistake as
  measuring backup recency without measuring success.
- ⚠️ Git refuses this repo with "dubious ownership" (host uid owns it, the container runs
  as another), so every call passes `-c safe.directory=`. Without it every read fails and
  the whole thing reports `unknown` forever — a guard that can never fire.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

REPO_ROOT = os.getenv("ARCHIE_REPO_ROOT", "/mnt/archie_brain")
DEFAULT_BRANCH = "main"

# The containers that bind-mount the tree. A merge does not reach either until it restarts.
HUB_CONTAINERS = ("archie_platform", "archie_scheduler")

_GIT_TIMEOUT = 10


def _git(*args: str) -> tuple[bool, str]:
    """Run one read-only git command against the repo. Never raises.

    `-C` (not a cd) because the repo is a separate mount and discovery stops at the
    boundary; `-c safe.directory` because the checkout is owned by the host user.
    """
    cmd = ["git", "-C", REPO_ROOT, "-c", f"safe.directory={REPO_ROOT}", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=_GIT_TIMEOUT)
        if p.returncode != 0:
            logger.debug("[hub_deploy] %s -> rc=%s %s", args[0], p.returncode, (p.stderr or "")[:120])
            return False, ""
        return True, (p.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[hub_deploy] %s failed: %s", args[0], exc)
        return False, ""


def _container_starts() -> dict:
    """{name: epoch_seconds} for the bind-mounting containers. {} when undiscoverable."""
    try:
        import docker
        from dateutil import parser as _dt  # docker ships this

        client = docker.from_env()
        out = {}
        for name in HUB_CONTAINERS:
            try:
                c = client.containers.get(name)
                started = (c.attrs.get("State") or {}).get("StartedAt")
                if started:
                    out[name] = _dt.parse(started).timestamp()
            except Exception:  # noqa: BLE001 - one missing container must not blank the rest
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug("[hub_deploy] container starts unavailable: %s", exc)
        return {}


def derive_status(facts: dict) -> tuple[str, list]:
    """PURE. Facts in, (status, warnings) out — no git, no docker, no clock.

    Split out so the DECISION can be tested without a repository. The gathering above is
    all I/O; this is the part that can be wrong in a way that matters, and an untestable
    verdict is one nobody can check.

    `stale_containers` is the ORDERING result (process started before the current commit),
    already computed by the caller — this function never inspects a container itself.
    """
    warnings: list = []
    branch = facts.get("branch")
    default = facts.get("default_branch") or DEFAULT_BRANCH
    on_default = facts.get("on_default_branch")
    behind = facts.get("behind_main") or 0
    stale = list(facts.get("stale_containers") or [])
    dirty = facts.get("dirty")
    fetch_age = facts.get("origin_fetched_age_hours")

    if on_default is False:
        warnings.append(
            f"The live tree is on '{branch}', NOT {default} — the platform is serving "
            f"unmerged code. A merge will not change what runs; a checkout will."
        )
    if behind:
        warnings.append(
            f"{behind} commit(s) on origin/{default} are not in the live tree. A merge "
            f"alone deploys nothing: pull, then restart."
        )
    if stale:
        warnings.append(
            f"{', '.join(stale)} started BEFORE the current commit — the code is on disk "
            f"but the running process has not loaded it. Restart to deploy."
        )
    if dirty:
        warnings.append("The tree has uncommitted changes — the running code is in no commit.")
    if fetch_age is not None and fetch_age > 24:
        warnings.append(
            f"origin was last fetched {fetch_age}h ago, so 'behind' is measured against a "
            f"stale reference and may UNDER-report."
        )

    # Loudest first. Serving unmerged code beats everything else; an unreadable repo is
    # never reported as in_sync.
    if on_default is None:
        status = "unknown"
    elif on_default is False:
        status = "feature_branch"
    elif stale:
        status = "needs_restart"
    elif behind:
        status = "needs_pull"
    elif dirty:
        status = "dirty"
    else:
        status = "in_sync"
    return status, warnings


def hub_deploy_state() -> dict:
    """Report what the hub is running vs what `main` holds. NEVER raises."""
    now = time.time()
    state: dict = {
        "repo_root": REPO_ROOT,
        "default_branch": DEFAULT_BRANCH,
        "branch": None,
        "head_sha": None,
        "head_committed_at": None,
        "on_default_branch": None,
        "behind_main": None,
        "ahead_of_main": None,
        "dirty": None,
        "origin_fetched_age_hours": None,
        "containers": [],
        "warnings": [],
        "status": "unknown",
        "detail": "",
        "checked_at": now,
    }

    ok_branch, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    ok_sha, sha = _git("rev-parse", "--short", "HEAD")
    if not (ok_branch and ok_sha):
        state["detail"] = (
            "Could not read the repository. If this persists, git is refusing it — the "
            "checkout is host-owned and every call needs -c safe.directory."
        )
        return state

    state["branch"] = branch
    state["head_sha"] = sha
    state["on_default_branch"] = branch == DEFAULT_BRANCH

    ok_ct, ct = _git("log", "-1", "--format=%ct", "HEAD")
    head_at = int(ct) if (ok_ct and ct.isdigit()) else None
    state["head_committed_at"] = head_at

    ok_b, behind = _git("rev-list", "--count", f"HEAD..origin/{DEFAULT_BRANCH}")
    ok_a, ahead = _git("rev-list", "--count", f"origin/{DEFAULT_BRANCH}..HEAD")
    state["behind_main"] = int(behind) if (ok_b and behind.isdigit()) else None
    state["ahead_of_main"] = int(ahead) if (ok_a and ahead.isdigit()) else None

    ok_d, dirty = _git("status", "--porcelain")
    state["dirty"] = bool(dirty.strip()) if ok_d else None

    # How much to trust `behind_main`: this process deliberately does not fetch.
    try:
        fh = os.path.join(REPO_ROOT, ".git", "FETCH_HEAD")
        if os.path.exists(fh):
            state["origin_fetched_age_hours"] = round((now - os.path.getmtime(fh)) / 3600.0, 1)
    except Exception:  # noqa: BLE001
        pass

    # ORDERING, not content: a bind-mounted file always reads current, which proves
    # nothing about what the long-lived process imported at boot.
    starts = _container_starts()
    for name in HUB_CONTAINERS:
        started = starts.get(name)
        entry = {"name": name, "started_at": started, "loaded_current_head": None}
        if started is not None and head_at is not None:
            entry["loaded_current_head"] = started >= head_at
        state["containers"].append(entry)

    stale = [c["name"] for c in state["containers"] if c["loaded_current_head"] is False]
    status, warnings = derive_status({**state, "stale_containers": stale})
    state["status"] = status
    state["warnings"] = warnings
    state["detail"] = warnings[0] if warnings else f"Live tree is {DEFAULT_BRANCH}@{sha}, loaded and current."
    return state
