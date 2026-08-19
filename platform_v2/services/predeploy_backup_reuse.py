"""Reuse a recent pre-deploy backup when the tree it protects has not changed (#5812).

WHY THIS EXISTS
---------------
Approving a batch of N deploys took N separate FULL snapshots. Measured 2026-08-19: a batch
of 12 deploy_approve items, every pre-deploy backup a full ~2,797 MB, so ~33 GB — of which
~30 GB was duplicate, because ``deploy_to_production`` APPLIES NO CODE (#5808, "Manual
deployment required - automatic code application disabled for safety"). The working tree does
not change between deploy #1 and deploy #12, so backups 2..12 are snapshots of an IDENTICAL
tree. They are redundant BY CONSTRUCTION, not merely by policy.

(The ADR-009 / #5279 scoped-backup optimisation does not help this class: these proposals
target services/ , consciousness/ and ai_bridge/ , which ``_predeploy_module_scope``
deliberately keeps on the full-snapshot rung.)

THE RULE THAT MAKES THIS SAFE
-----------------------------
Reuse is decided by the ARTIFACT, never by the clock. "A backup exists from 4 minutes ago" is
a STATUS check and is exactly the bug class fixed twice on 2026-08-19 (the backup freshness
gate, then the pr_merge gate). "A backup exists whose recorded fingerprint equals the tree's
CURRENT fingerprint" is an ARTIFACT check — ADR-014.

Age is still bounded, but only as a SECONDARY guard: a matching fingerprint is necessary AND
a recent timestamp is necessary. Neither alone is sufficient.

FAIL CLOSED, ALWAYS
-------------------
Every uncertain input returns None, and None means "take a fresh backup". An unreadable file,
an unparseable fingerprint, a missing column, an exception — all fall through to a real
snapshot. Wasting 2.8 GB is cheap; deploying against a restore point that does not match the
tree is not.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger("agent_loop")

# Only reuse a backup taken within this window even when the fingerprint matches. A matching
# fingerprint already proves the tree is unchanged; this bounds how stale a *restore point*
# may be for reasons the fingerprint cannot see (DB drift, external state).
REUSE_MAX_AGE_MINUTES = 90

# Marker written into backup_log.notes so a later deploy can recognise what a backup covers.
FINGERPRINT_PREFIX = "treefp="

# Only these extensions participate. A pre-deploy backup exists to protect CODE; caches,
# compiled artefacts and logs churn constantly and would defeat every match.
_CODE_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".json", ".yaml", ".yml")
_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "venv",
    ".venv",
    "static/media",
    "logs",
}


def tree_fingerprint(roots) -> Optional[str]:
    """A cheap content-change fingerprint for *roots*.

    Hashes (relative path, size, mtime_ns) for every code file — deliberately NOT the file
    contents, which would mean reading gigabytes on every deploy. Size+mtime changes on any
    write, which is the only event that must invalidate reuse here.

    Returns a 16-char hex digest, or **None** if it cannot be computed for any reason — and
    None means the caller MUST take a fresh backup.
    """
    if isinstance(roots, (str, os.PathLike)):
        roots = [roots]
    try:
        h = hashlib.sha256()
        seen_any = False
        for root in sorted(str(r) for r in roots):
            if not os.path.isdir(root):
                # A declared root that does not exist means the caller's assumption about
                # what is being protected is wrong. Refuse rather than fingerprint a subset.
                logger.debug("tree_fingerprint: root missing, refusing: %s", root)
                return None
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
                for name in sorted(filenames):
                    if not name.endswith(_CODE_SUFFIXES):
                        continue
                    full = os.path.join(dirpath, name)
                    try:
                        st = os.stat(full)
                    except OSError:
                        # A file that vanished mid-walk makes the fingerprint ambiguous.
                        logger.debug("tree_fingerprint: unreadable, refusing: %s", full)
                        return None
                    rel = os.path.relpath(full, root)
                    h.update(f"{root}|{rel}|{st.st_size}|{st.st_mtime_ns}\n".encode())
                    seen_any = True
        if not seen_any:
            # An empty walk is far more likely to be a wrong path than a genuinely empty
            # tree. Never let it produce a stable digest that everything would match.
            return None
        return h.hexdigest()[:16]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("tree_fingerprint failed (will take a fresh backup): %s", exc)
        return None


def annotate_notes(notes: str, fingerprint: Optional[str]) -> str:
    """Append the fingerprint marker to a backup's notes so a later deploy can match it."""
    base = (notes or "").strip()
    if not fingerprint:
        return base
    return f"{base} {FINGERPRINT_PREFIX}{fingerprint}".strip()


def fingerprint_from_notes(notes: str) -> Optional[str]:
    """Extract the fingerprint a backup recorded, or None if it carries none."""
    for token in (notes or "").split():
        if token.startswith(FINGERPRINT_PREFIX):
            value = token[len(FINGERPRINT_PREFIX) :].strip()
            return value or None
    return None


def pick_reusable_backup(candidates, fingerprint: Optional[str], *, max_age_minutes: int = REUSE_MAX_AGE_MINUTES):
    """Choose a backup to reuse, or None to take a fresh one.

    ``candidates`` — newest-first rows, each needing ``backup_name``, ``notes`` and
    ``age_minutes``. Pure: the caller does the SQL, so this is testable without a database.

    A candidate qualifies ONLY when all hold:
      * the run succeeded and names an artifact,
      * its recorded fingerprint EQUALS the current one (the artifact check), and
      * it is younger than ``max_age_minutes`` (the secondary staleness bound).

    Returns the ``backup_name`` to reuse, else None.
    """
    if not fingerprint or not candidates:
        return None
    for row in candidates:
        try:
            name = (row.get("backup_name") or "").strip()
            if not name:
                continue
            age = row.get("age_minutes")
            if age is None or float(age) > float(max_age_minutes) or float(age) < 0:
                continue
            if fingerprint_from_notes(row.get("notes") or "") != fingerprint:
                continue
            return name
        except Exception:  # pragma: no cover - a malformed row must never select a backup
            continue
    return None
