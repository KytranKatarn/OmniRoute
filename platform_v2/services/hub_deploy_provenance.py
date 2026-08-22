"""Hub deploy provenance — is the code we merged actually the code we are running? (#5375)

THE FAILURE THIS EXISTS TO CATCH
--------------------------------
2026-07-28: PR #2543 merged cleanly on GitHub. Both containers were restarted.
The running platform still served the PRE-merge code, because ``/app`` is
bind-mounted from ``/mnt/archie_brain/platform_v2`` and that checkout was two
commits behind ``origin/main``. Merging on GitHub updates *origin*; it does not
touch the working tree the container reads, so the restart faithfully reloaded
the same old file.

Every signal read green: GitHub said merged, the PR closed, Repair Bay stored an
approved verdict, ``docker compose restart`` exited 0. Two PRs (#2543 and #2542)
were merged-but-dead simultaneously and nothing anywhere said so.

This is the volume-mounted twin of the image-baked drift that
``scripts/deploy_drift_check.py`` already guards for the nine standalone
products. The hub platform itself had no equivalent check.

WHY AN OBSERVER AND NOT AN AUTO-DEPLOYER
----------------------------------------
This module is deliberately READ-ONLY. It never runs ``git pull``, never
restarts a container:

* ``/mnt/archie_brain`` holds Kytran's uncommitted work. An automated
  fast-forward — let alone a reset — risks real data loss.
* The Telegram merge handler runs *inside* ``archie_platform``. Having it
  restart its own container would kill the handler mid-reply.

So the contract is: **make the gap impossible to miss, and let a human close
it.** Ship the observer before the fixer.

THE TWO INDEPENDENT WAYS A MERGE FAILS TO GO LIVE
-------------------------------------------------
Both must be checked; either alone gives a false all-clear.

1. ``pull_required``    — the checkout is behind origin/main. The merged code is
                          not even on disk. A restart deploys nothing.
2. ``restart_required`` — the code IS on disk but newer than the running
                          process, so the old module objects are still loaded.
                          (This is the ``inspect.getsource`` trap: reading the
                          repo file proves nothing about what is *loaded*.)

FAIL-OPEN, ALWAYS
-----------------
An unreachable GitHub API or an unreadable ``/proc`` yields ``fail_open`` —
never ``drift``. An UNKNOWN is not a fault, and a monitor that cries wolf on its
own outage gets muted, which is how the original bug stayed invisible.
"""

from __future__ import annotations

import logging
import hashlib
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# The bind-mounted checkout the container reads. Mirrors github_service.REPO_PATH.
REPO_PATH = os.getenv("HUB_REPO_PATH", "/mnt/archie_brain")
# Where that checkout is mounted inside this container.
APP_DIR = os.getenv("HUB_APP_DIR", "/app")
DEFAULT_BRANCH = "main"

STATUS_IN_SYNC = "in_sync"
STATUS_PULL_REQUIRED = "pull_required"
STATUS_RESTART_REQUIRED = "restart_required"
STATUS_FAIL_OPEN = "fail_open"

#: Directories under APP_DIR that are irrelevant to what Python has imported.
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

REMEDY = (
    "git -C /mnt/archie_brain merge --ff-only origin/main && " "docker compose restart archie_platform archie_scheduler"
)


def head_from_git_dir(repo_path: str = None) -> "str | None":
    """Read HEAD straight out of the ``.git`` directory. No git binary involved.

    THIS IS THE PRIMARY READER, and the reason is not style. Inside the
    container ``git -C /mnt/archie_brain rev-parse HEAD`` fails outright::

        fatal: detected dubious ownership in repository at '/mnt/archie_brain'

    (exit 128 — the checkout is owned by the host uid, not the container user.)
    A subprocess-only implementation therefore returns None on EVERY call, the
    check degrades to ``fail_open`` forever, and we ship a monitor that looks
    installed and can never once alarm — the very "unmonitored while appearing
    monitored" failure this module exists to prevent. Verified live 2026-07-28
    before merge; no unit test would have caught it, because the tests stub
    this function.

    Plain file reads have no ownership check and cannot mutate the repo.
    """
    path = repo_path or REPO_PATH
    try:
        git_dir = os.path.join(path, ".git")
        # A linked worktree's .git is a FILE containing "gitdir: <path>".
        if os.path.isfile(git_dir):
            with open(git_dir, "r", encoding="utf-8") as fh:
                pointer = fh.read().strip()
            if pointer.startswith("gitdir:"):
                git_dir = pointer.split(":", 1)[1].strip()

        # In a linked worktree, HEAD is per-worktree but refs/ and packed-refs
        # live in the MAIN repository, located via the `commondir` file. Looking
        # for the ref beside HEAD finds nothing and silently yields None — which
        # would degrade the whole check to fail_open. Caught by the live test.
        common_dir = git_dir
        commondir_file = os.path.join(git_dir, "commondir")
        if os.path.exists(commondir_file):
            with open(commondir_file, "r", encoding="utf-8") as fh:
                rel = fh.read().strip()
            common_dir = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(git_dir, rel))

        with open(os.path.join(git_dir, "HEAD"), "r", encoding="utf-8") as fh:
            head = fh.read().strip()

        if not head.startswith("ref:"):
            return head or None  # detached HEAD holds the sha directly

        ref = head.split(":", 1)[1].strip()

        # Per-worktree refs win over shared ones; both are legitimate locations.
        for base in (git_dir, common_dir):
            loose = os.path.join(base, ref)
            if os.path.exists(loose):
                with open(loose, "r", encoding="utf-8") as fh:
                    sha = fh.read().strip()
                if sha:
                    return sha

        for base in (git_dir, common_dir):
            packed = os.path.join(base, "packed-refs")
            if not os.path.exists(packed):
                continue
            with open(packed, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(("#", "^")):
                        continue
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0]
        return None
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] git-dir read failed: %s", exc)
        return None


def local_head(repo_path: str = None) -> "str | None":
    """SHA the bind-mounted checkout is currently on. ``None`` if unreadable.

    Read-only throughout. Tries the git-dir file read first (see above), then
    falls back to the binary with an explicit ``safe.directory`` so the
    ownership guard cannot veto a read we are entitled to make.
    """
    path = repo_path or REPO_PATH

    sha = head_from_git_dir(path)
    if sha:
        return sha

    try:
        out = subprocess.run(
            ["git", "-c", f"safe.directory={path}", "-C", path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            logger.warning("[HubProvenance] rev-parse failed: %s", (out.stderr or "").strip()[:200])
            return None
        return (out.stdout or "").strip() or None
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] local_head unavailable: %s", exc)
        return None


def remote_head(branch: str = DEFAULT_BRANCH) -> "str | None":
    """SHA at the tip of origin/<branch>, via the GitHub API. ``None`` on failure.

    Uses the API rather than ``git rev-parse origin/main`` on purpose: the local
    remote-tracking ref is only as fresh as the last fetch, so it would happily
    report "in sync" against a stale mirror of the very thing being checked.
    """
    try:
        from tools.repair_bay.services.github_service import REPO_FULL, _api_get

        ok, data = _api_get(f"/repos/{REPO_FULL}/commits/{branch}")
        if not ok or not isinstance(data, dict):
            logger.warning("[HubProvenance] remote_head API said: %s", str(data)[:200])
            return None
        return data.get("sha") or None
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] remote_head unavailable: %s", exc)
        return None


def _proc_start_time(pid: int = 1) -> "float | None":
    """Unix epoch at which <pid> started.

    Same technique as ``backup_manager/_shared._proc_start_time``: field 22 of
    ``/proc/<pid>/stat`` (clock ticks since boot) plus ``btime`` from
    ``/proc/stat``. Deliberately NOT the ctime/mtime of ``/proc/<pid>``, which
    procfs reports as "now" and would make every check look freshly restarted.
    """
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            stat_line = fh.read()
        # comm can contain spaces/parens — everything after the final ')' is safe.
        after = stat_line[stat_line.rfind(")") + 1 :].split()
        starttime_ticks = float(after[19])  # field 22 overall, index 19 after pid+comm+state

        btime = None
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("btime "):
                    btime = float(line.split()[1])
                    break
        if btime is None:
            return None

        hz = os.sysconf("SC_CLK_TCK") or 100
        return btime + (starttime_ticks / hz)
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] proc start time unavailable: %s", exc)
        return None


def newest_source_mtime(app_dir: str = None) -> "tuple[float, str] | None":
    """(mtime, path) of the most recently modified ``.py`` under app_dir."""
    root = app_dir or APP_DIR
    newest: "tuple[float, str] | None" = None
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                if newest is None or mtime > newest[0]:
                    newest = (mtime, full)
        return newest
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] source walk failed: %s", exc)
        return None


# --- #5918: content, not mtime -------------------------------------------------
#
# `newest_source_mtime() > process_start` was the only restart_required signal, and
# mtime is NOT evidence the CODE changed. `git checkout` between branches, `touch`,
# an editor re-save, or Black reformatting-then-reverting all bump mtime with byte-
# identical content. A working session does that many times a day, so the observer
# cried "restart_required" on code that was already live — and an alarm that fires on
# a no-op is the same failure family this module exists to prevent (see FAIL-OPEN).
#
# Measured 2026-08-22: hashing every .py under /app is 1,150 files / 15.9 MB in
# **0.186 s**, so recording it at import costs nothing worth optimising.
_IMPORT_GRACE_S = 120.0


def source_tree_sha(app_dir: str = None) -> "str | None":
    """Stable sha256 over the CONTENT of every .py under app_dir (path + bytes)."""
    root = app_dir or APP_DIR
    try:
        h = hashlib.sha256()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    with open(full, "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue
                h.update(full.encode("utf-8", "replace"))
                h.update(hashlib.sha256(blob).digest())
        return h.hexdigest()
    except Exception:  # noqa: BLE001 — fail-open, never a fault
        return None


# Captured when THIS process imported the module — i.e. a fingerprint of the source it
# actually loaded. Cheap enough (0.19 s) to take unconditionally.
_LOADED_TREE_SHA = source_tree_sha()
_IMPORT_TIME = time.time()


def _loaded_sha_is_trustworthy(process_started: float) -> bool:
    """Is the import-time hash a faithful record of what this process LOADED?

    Only if the module was imported near process start. ⚠️ If it were imported late —
    lazily, on the first request — an edit made between startup and that import would
    ALREADY be inside _LOADED_TREE_SHA, so a content match would wrongly read as
    in_sync. That is a false NEGATIVE on the exact condition this module exists to
    catch, which is far worse than the false positive being fixed. When in doubt we
    keep the old, conservative mtime verdict.
    """
    try:
        return (_IMPORT_TIME - float(process_started)) <= _IMPORT_GRACE_S
    except Exception:  # noqa: BLE001
        return False


def check_hub_deploy(branch: str = DEFAULT_BRANCH) -> dict:
    """Is the running hub platform serving the merged code?

    Returns a dict with ``status`` in {in_sync, pull_required, restart_required,
    fail_open}, plus the evidence behind it and a ``remedy`` string. Never
    raises — a monitor that can crash is a monitor that stops monitoring.
    """
    result = {
        "status": STATUS_FAIL_OPEN,
        "local_head": None,
        "remote_head": None,
        "newest_source": None,
        "newest_source_age_s": None,
        "process_started": None,
        "reason": "",
        "remedy": REMEDY,
    }
    try:
        local = local_head()
        remote = remote_head(branch)
        result["local_head"] = local
        result["remote_head"] = remote

        if not local or not remote:
            result["reason"] = "could not read local and/or remote HEAD — reporting UNKNOWN, not drift"
            return result

        if local != remote:
            result["status"] = STATUS_PULL_REQUIRED
            result["reason"] = (
                f"checkout is at {local[:9]} but origin/{branch} is at {remote[:9]} — "
                "merged code is not on disk; restarting deploys nothing"
            )
            return result

        newest = newest_source_mtime()
        started = _proc_start_time(1)
        if newest is None or started is None:
            result["reason"] = "HEADs match but could not compare source mtime to process start"
            return result

        result["newest_source"] = newest[1]
        result["newest_source_age_s"] = round(time.time() - newest[0], 1)
        result["process_started"] = started

        if newest[0] > started:
            # mtime moved. Ask whether the CONTENT moved before alarming (#5918).
            if _LOADED_TREE_SHA and _loaded_sha_is_trustworthy(started):
                current_sha = source_tree_sha()
                if current_sha and current_sha == _LOADED_TREE_SHA:
                    result["status"] = STATUS_IN_SYNC
                    result["mtime_moved_without_content_change"] = True
                    result["reason"] = (
                        f"running {local[:9]}, matches origin/{branch} — "
                        f"{os.path.basename(newest[1])} has a newer mtime but the source "
                        "content is byte-identical to what this process loaded"
                    )
                    return result
            result["status"] = STATUS_RESTART_REQUIRED
            result["reason"] = (
                f"{newest[1]} is newer than the running process — " "the merged code is on disk but not loaded"
            )
            return result

        result["status"] = STATUS_IN_SYNC
        result["reason"] = f"running {local[:9]}, matches origin/{branch}"
        return result
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("[HubProvenance] check failed: %s", exc)
        result["reason"] = f"check errored: {exc}"
        return result


def describe(check: dict) -> str:
    """One-line human summary — for the Telegram merge reply and alerts."""
    status = (check or {}).get("status")
    if status == STATUS_IN_SYNC:
        return "✅ deployed and live"
    if status == STATUS_PULL_REQUIRED:
        return f"⚠️ MERGED BUT NOT DEPLOYED — hub checkout is behind. Run:\n{check.get('remedy')}"
    if status == STATUS_RESTART_REQUIRED:
        return f"⚠️ MERGED, PULLED, NOT LOADED — restart required. Run:\n{check.get('remedy')}"
    return f"❔ deploy state UNKNOWN ({(check or {}).get('reason') or 'no reason given'})"


def is_live(check: dict) -> bool:
    """True only on a positive in_sync. UNKNOWN is never treated as live."""
    return (check or {}).get("status") == STATUS_IN_SYNC
