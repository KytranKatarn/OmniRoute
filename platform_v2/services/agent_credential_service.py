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

# Both credential stores: the HOST root .env (the login skill greps it; the scheduler
# container reaches it via its /mnt/archie_brain mount) and the container-visible
# /app/.env (= platform_v2/.env — the two-env-files rule). Missing paths are skipped,
# never fatal: the DB hash is the source of truth, env files are the skill's cache.
_DEFAULT_ENV_PATHS = ("/mnt/archie_brain/.env", "/app/.env")


def generate_agent_password() -> str:
    """Strong random password that always satisfies validate_password_complexity
    (8+ chars, upper/lower/digit/special): a urlsafe core plus a fixed suffix that
    guarantees every required class regardless of what the core happened to draw."""
    return secrets.token_urlsafe(18) + "!A9x"


def _rewrite_env_line(path: str, key: str, value: str) -> bool:
    """Replace (or append) ``KEY=value`` in an env file, atomically, preserving mode.

    Atomic tmp+rename in the SAME directory so a crash mid-write can never leave a
    truncated .env — these files hold every platform secret, not just ours.
    """
    if not os.path.isfile(path):
        return False
    with open(path, "r") as fh:
        lines = fh.readlines()
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
    st = os.stat(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env-rotate-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.writelines(lines)
        os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


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
    for path in env_paths:
        try:
            if _rewrite_env_line(path, key, new_password):
                env_written.append(path)
        except Exception as exc:  # noqa: BLE001 — a missing env store must not undo the DB rotation
            logger.warning("agent password rotation: could not write %s: %s", path, exc)

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
        "note": "password stored only in the env files; never logged or returned",
    }
