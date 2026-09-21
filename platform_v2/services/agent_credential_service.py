"""Agent-account credential rotation — Account Center-governed, approval-gated (#5303).

Owner direction (2026-07-27): agent logins are managed by the Account Center module,
any ADMIN account can reset them, and a rotation must ride the Tier-2 (human) approval
queue — Kytran taps Approve on Telegram, THEN the rotation executes, performed by a
named platform agent (P.R.O.B.E. requested it; the service itself is agent-agnostic).

HARD SCOPE: only the two AGENT accounts created for AI use. The service refuses every
other username BEFORE touching anything — `kytran`, `admin`, and every human account
are structurally unreachable (Claude locked Kytran out on 2026-05-08 by guessing at
his account; this module makes that class of mistake impossible).

The new password is NEVER returned, logged, or stored in the approval row — it lands
ONLY in the .env files the login skill reads (root .env for the host-side skill,
/app/.env for in-container consumers; both are gitignored).
"""

from __future__ import annotations

import logging
import os
import secrets
import tempfile

from database import get_db_cursor

logger = logging.getLogger(__name__)

# The ONLY resettable accounts — the agent identities Kytran provisioned via Account
# Center for Claude + A.R.C.H.I.E. Additions require an explicit owner decision.
_AGENT_ACCOUNTS = ("claude", "archie")

_ENV_KEYS = {
    "claude": "ARCHIE_CLAUDE_PASSWORD",
    "archie": "ARCHIE_ARCHIE_PASSWORD",
}

# Legacy env stores, best-effort only. #5311 CORRECTION: NEITHER container can
# actually see /mnt/archie_brain/.env (verified 2026-07-27 — the earlier claim
# that the scheduler reaches it was wrong; that is exactly why #5303's rotation
# reported env_written=['/app/.env'] and the root .env needed a hand-sync).
# Missing paths are skipped, never fatal: the DB hash is the source of truth.
_DEFAULT_ENV_PATHS = ("/mnt/archie_brain/.env", "/app/.env")

# Which of the above the RUNTIME actually loads. docker-compose gives
# archie_platform `env_file: .env` — the ROOT one — so a rotation that misses it
# leaves every in-container `os.getenv(ARCHIE_*_PASSWORD)` holding a credential
# that no longer authenticates.
#
# ⚠️ That path is NOT visible from inside the scheduler: only
# /mnt/archie_brain/credentials and /mnt/archie_brain/platform_v2 are mounted, so
# `/mnt/archie_brain/.env` does not exist there and `_rewrite_env_line(create=False)`
# returns False for it. Measured 2026-09-20 rotating `claude` from the container:
# env_written came back ['/app/credentials/agent_passwords.env', '/app/.env'] and
# root .env silently kept its Sep-13 value — CLAUDE.md's "root .env and
# platform_v2/.env must match" invariant broken with nothing reporting it.
#
# The skip is legitimate (a single-FILE rw bind mount would break the atomic
# tmp+rename writer — see _CREDENTIALS_FILE_CANDIDATES below). What was NOT
# legitimate is that it was SILENT: `env_written` lists successes, so a path that
# could not be written looked exactly like a path that was never configured. Run
# the rotation ON THE HOST to reach root .env; from a container, expect the
# warning below and sync it out of band.
_RUNTIME_ENV_FILES = frozenset({"/mnt/archie_brain/.env"})

# #5311: the CANONICAL store. A single-FILE rw bind mount of the root .env
# would break the atomic tmp+rename writer (a file mount pins the inode), so
# rotation writes agent_passwords.env inside the scheduler's EXISTING rw
# directory mount /mnt/archie_brain/credentials -> /app/credentials (0600,
# atomic rename — directory mounts survive renames; host-visible, so the
# login skill reads it first). Container path first; host path covers
# host-run invocations and tests.
_CREDENTIALS_FILE_CANDIDATES = (
    "/app/credentials/agent_passwords.env",
    "/mnt/archie_brain/credentials/agent_passwords.env",
)


def generate_agent_password() -> str:
    """Strong random password that always satisfies validate_password_complexity
    (8+ chars, upper/lower/digit/special): a urlsafe core plus a fixed suffix that
    guarantees every required class regardless of what the core happened to draw."""
    return secrets.token_urlsafe(18) + "!A9x"


def _rewrite_env_line(path: str, key: str, value: str, create: bool = False) -> bool:
    """Replace (or append) ``KEY=value`` in an env file, atomically, preserving mode.

    Atomic tmp+rename in the SAME directory so a crash mid-write can never leave a
    truncated .env — these files hold every platform secret, not just ours.
    ``create=True`` (#5311) starts a missing file at mode 0600 — used only for the
    canonical credentials store, never for the shared .env files.
    """
    exists = os.path.isfile(path)
    if not exists and not create:
        return False
    if exists:
        with open(path, "r") as fh:
            lines = fh.readlines()
    else:
        lines = []
    prefix = key + "="
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={value}\n"
            replaced = True
            break
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    mode = (os.stat(path).st_mode & 0o777) if exists else 0o600
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env-rotate-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.writelines(lines)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def _write_credentials_file(key: str, value: str) -> str | None:
    """#5311: persist the rotated secret to the canonical credentials store.

    Picks the first candidate whose PARENT directory exists (container path in
    the scheduler, host path for host-run invocations) and creates/updates
    ``agent_passwords.env`` at mode 0600 via the same atomic writer. Returns
    the path written, or None when no candidate directory is reachable — the
    caller treats that like any other missing env store (DB stays canonical
    for AUTH; this file is canonical for the agents' own login lookup).
    """
    for candidate in _CREDENTIALS_FILE_CANDIDATES:
        try:
            if os.path.isdir(os.path.dirname(candidate)):
                if _rewrite_env_line(candidate, key, value, create=True):
                    _align_store_ownership(candidate)
                    return candidate
        except Exception as exc:  # noqa: BLE001 — try the next candidate, never abort rotation
            logger.warning("agent password rotation: credentials store %s failed: %s", candidate, exc)
    return None


def _align_store_ownership(path: str) -> None:
    """#5311 (live-probed 2026-07-27): BOTH archie_platform and archie_scheduler
    run as root, so a rotation used to leave ``agent_passwords.env`` at
    root:root 0600 — unreadable by the host-side owner (kytran), which is the
    very consumer the host-visible store exists for (the login skill reads it
    first). Align the file's ownership with its PARENT DIRECTORY's owner, so
    whoever owns the credentials dir on the host can read the store. Only
    meaningful (and only possible) when running as root; best-effort — an
    ownership hiccup must never undo a completed rotation.
    """
    try:
        if os.geteuid() != 0:
            return
        parent = os.stat(os.path.dirname(path))
        os.chown(path, parent.st_uid, parent.st_gid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent password rotation: could not align ownership of %s: %s", path, exc)


def reset_agent_password(username: str, env_paths: tuple = _DEFAULT_ENV_PATHS) -> dict:
    """Rotate an AGENT account's login password.

    Returns a bookkeeping dict that deliberately EXCLUDES the password — approval-queue
    results are logged/stored, and a credential must never ride them. Also clears
    failed_login_count so a rotation always leaves the account immediately usable.
    """
    username = str(username or "").strip().lower()
    if username not in _AGENT_ACCOUNTS:
        return {
            "success": False,
            "error": f"refused: '{username}' is not an agent account (only {', '.join(_AGENT_ACCOUNTS)})",
        }

    from werkzeug.security import generate_password_hash

    new_password = generate_agent_password()
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE users
               SET password_hash = %s, failed_login_count = 0
               WHERE username = %s AND is_active = true
               RETURNING id""",
            (generate_password_hash(new_password), username),
        )
        row = cur.fetchone()
    if not row:
        return {"success": False, "error": f"user '{username}' not found or inactive"}

    key = _ENV_KEYS[username]
    env_written = []
    # #5311: canonical store FIRST — the credentials-dir file is the one place
    # both the executing container and the host (login skill) can see.
    credentials_file = _write_credentials_file(key, new_password)
    if credentials_file:
        env_written.append(credentials_file)
    env_skipped = []
    for path in env_paths:
        try:
            if _rewrite_env_line(path, key, new_password):
                env_written.append(path)
            else:
                # Not an error — but it MUST be reported. See _RUNTIME_ENV_FILES.
                env_skipped.append({"path": path, "reason": "not present in this filesystem"})
        except Exception as exc:  # noqa: BLE001 — a missing env store must not undo the DB rotation
            logger.warning("agent password rotation: could not write %s: %s", path, exc)
            env_skipped.append({"path": path, "reason": f"{type(exc).__name__}: {exc}"})

    # A skipped store the RUNTIME loads is the one case a caller must act on: the
    # DB and the canonical file are correct, but the deployed env var is now stale.
    stale_runtime = sorted(e["path"] for e in env_skipped if e["path"] in _RUNTIME_ENV_FILES)
    warning = None
    if stale_runtime:
        warning = (
            "rotation did not reach " + ", ".join(stale_runtime) + " (not visible from here) — "
            "the DB hash and the canonical credentials file are correct, but that env file still "
            "holds the OLD password and is what the container loads. Sync it, then apply with "
            "`docker compose up -d --no-deps <service>` (a restart does NOT re-read env_file)."
        )
        logger.warning("agent password rotation: %s", warning)

    logger.info(
        "agent password rotated for '%s' (user id %s) — env stores updated: %s",
        username,
        row["id"] if isinstance(row, dict) else row[0],
        env_written or "NONE (DB hash is still authoritative)",
    )
    return {
        "success": True,
        "username": username,
        "user_id": row["id"] if isinstance(row, dict) else row[0],
        "env_written": env_written,
        "env_skipped": env_skipped,
        "warning": warning,
        "credentials_file": credentials_file,
        "note": "password stored only in the credential/env files; never logged or returned",
    }
