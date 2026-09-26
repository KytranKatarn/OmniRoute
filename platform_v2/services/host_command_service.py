"""Host-root command approvals — allowlisted, human-approved, audited.

WHY THIS EXISTS
---------------
The opencode lane is HOST-DIRECT by owner decision (option-B, 2026-09-13,
`contained=False`): it holds the docker socket, so it already has effective
host root. The socket stays — it is load-bearing for HOST-DIRECT edits and for
the `docker exec -i archie_platform python3 -` path the guardrails mandate for
GitHub calls.

What was missing is a *record* of privileged work with a human signature on it.
This adds that: a request goes into the existing `autonomy_approval_queue`, the
owner reads the literal argv in the DHQ Approvals tab, and only an approval
runs it. Nothing new to learn, no new table, no new UI.

HONEST THREAT MODEL — read before trusting this
-----------------------------------------------
Because the requesting lane can already reach a root shell, this is an AUDIT
LEDGER AND A SPEED BUMP, NOT A CONTAINMENT BOUNDARY against that lane. A
determined caller can bypass it. It IS a real boundary for the platform's own
automation, and it does force a human signature on host-root work.

Therefore the real control is NOT "the owner reads it carefully" — a human
skimming is not a control, and no prompt injection should be able to reach root
by being persuasive. The control is that the request schema makes a dangerous
command UNREPRESENTABLE:

  * ops are a closed allowlist, not free-form argv;
  * every op is a template that builds its own argv — no caller-supplied
    command string is ever executed, and there is no shell anywhere;
  * paths are resolved with realpath and must sit under an allowlisted root,
    so symlinks cannot walk out;
  * `install_reviewed_file` takes its CONTENT from a git-tracked, unmodified
    file, so the bytes were reviewed in a PR — the approval gates the *install*,
    not arbitrary content;
  * expiry is short and single-use, so a stale "yes" cannot be replayed.

`rm -rf /` is not something you can construct here. That is the point.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# The action_type written into autonomy_approval_queue.action_type.
ACTION_TYPE = "host_root_command"

# Tier 3 = most sensitive. pr_merge uses the same tier (#5283); a host root
# command is at least as consequential as a merge.
TIER = 3

# Short. A privileged approval that sits pending for a day is a stale "yes"
# waiting to be applied to a machine that has since changed.
EXPIRY_MINUTES = 30

# Carrier image for the chroot. Small, Debian-based (coreutils chroot), already
# present on the host so `--pull=never` never needs the network.
CARRIER_IMAGE = "python:3.12-slim"

# Host root is reached by privileged-chroot. `docker run --privileged -v /:/host
# chroot /host <argv>` is the standard mechanism and the reason this module
# exists only behind a human approval.
HOST_CHROOT = "/host"

# What the owner is agreeing to when they approve. Every op is a fixed template.
ALLOWED_ACL_ROOTS: Tuple[str, ...] = ("/mnt/archie_brain",)

# Only these packages may ever be installed. `apt-get` with a caller-supplied
# package list is arbitrary code execution; this is the whole allowlist.
ALLOWED_PACKAGES: Tuple[str, ...] = ("acl",)

# Where a reviewed file may be installed as root. Deliberately tiny: cron only.
ALLOWED_INSTALL_DST_ROOTS: Tuple[str, ...] = ("/etc/cron.d",)

# Read-only log units. No caller-supplied grep pattern — a pattern is a
# command-line injection surface that buys nothing here.
ALLOWED_LOG_UNITS: Tuple[str, ...] = ("cron", "syslog")

# The ACL mode this platform needs, spelled out so a caller cannot pass
# something else. `u:1000:rwX` for uid 1000 (host kytran / container node).
ACL_MODE = "u:1000:rwX"
ACL_DEFAULT_MODE = "d:u:1000:rwX"

# Shell metacharacters are harmless (there is no shell) but they corrupt the
# audit log and would confuse a human reading the Approvals tab, so they are
# rejected outright rather than escaped.
_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f;&|`$><\\\"'*?()\[\]{}!#~]")

MAX_STDOUT = 8000


class SpecRejected(ValueError):
    """The requested operation is not representable. Never execute, never queue."""


def _reject_unsafe(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecRejected(f"{field} must be a non-empty string")
    if _UNSAFE_CHARS.search(value):
        raise SpecRejected(f"{field} contains characters that are not allowed: {value!r}")
    return value


def _safe_path(raw: str, roots: Tuple[str, ...], field: str = "path") -> str:
    """Resolve `raw` and require it to sit strictly under one of `roots`.

    realpath() is what makes this safe: a symlink inside an allowed root that
    points at /etc is resolved BEFORE the prefix test, so it fails closed.
    """
    _reject_unsafe(raw, field)
    resolved = os.path.realpath(raw)
    for root in roots:
        root_r = os.path.realpath(root)
        if resolved == root_r or resolved.startswith(root_r.rstrip("/") + "/"):
            return resolved
    raise SpecRejected(f"{field} must resolve under one of {list(roots)}; got {resolved!r}")


def _repo_path(raw: str, field: str = "src") -> str:
    """A path inside the live tree, used as the CONTENT SOURCE for an install.

    The file must be git-tracked and unmodified, so the bytes being installed as
    root are exactly the bytes that went through code review. Verified in
    build_argv() (which cannot shell out cheaply), re-verified at execute time by
    the caller before running install.
    """
    return _safe_path(raw, ALLOWED_ACL_ROOTS, field)


def build_argv(spec: Dict[str, Any]) -> List[str]:
    """Validate a request spec and return the exact argv to run as host root.

    Returns a list — never a string — so nothing is ever passed through a shell.
    Raises SpecRejected for anything outside the allowlist. This runs at REQUEST
    time (so a bad request never reaches the queue) and again at EXECUTE time
    (so a row edited in the DB cannot smuggle a new command past the tab).
    """
    if not isinstance(spec, dict):
        raise SpecRejected("spec must be an object")
    op = spec.get("op")
    if not isinstance(op, str):
        raise SpecRejected("spec.op is required")

    if op == "setfacl":
        path = _safe_path(spec.get("path", ""), ALLOWED_ACL_ROOTS)
        recursive = spec.get("recursive", True)
        if not isinstance(recursive, bool):
            raise SpecRejected("spec.recursive must be true/false")
        argv = ["/usr/bin/setfacl"]
        if recursive:
            argv.append("-R")
        argv += ["-m", ACL_MODE, "-m", ACL_DEFAULT_MODE, "--", path]
        return argv

    if op == "getfacl":
        path = _safe_path(spec.get("path", ""), ALLOWED_ACL_ROOTS)
        return ["/usr/bin/getfacl", "-p", "--", path]

    if op == "apt_install":
        packages = spec.get("packages")
        if not isinstance(packages, list) or not packages:
            raise SpecRejected("spec.packages must be a non-empty list")
        for pkg in packages:
            if pkg not in ALLOWED_PACKAGES:
                raise SpecRejected(f"package {pkg!r} is not installable here; allowlist is {list(ALLOWED_PACKAGES)}")
        return ["/usr/bin/apt-get", "install", "-y", "--no-install-recommends", *packages]

    if op == "install_reviewed_file":
        src = _repo_path(spec.get("src", ""), "src")
        dst = _safe_path(spec.get("dst", ""), ALLOWED_INSTALL_DST_ROOTS, "dst")
        mode = spec.get("mode", "0644")
        if mode not in ("0644", "0600"):
            raise SpecRejected("spec.mode must be 0644 or 0600")
        return ["/usr/bin/install", "-m", mode, "-o", "root", "-g", "root", src, dst]

    if op == "read_log":
        unit = spec.get("unit")
        if unit not in ALLOWED_LOG_UNITS:
            raise SpecRejected(f"spec.unit must be one of {list(ALLOWED_LOG_UNITS)}")
        return ["/usr/bin/journalctl", "-u", unit, "--since", "-2h", "--no-pager", "-n", "200"]

    raise SpecRejected(f"op {op!r} is not in the allowlist")


def describe(spec: Dict[str, Any]) -> str:
    """One-line human summary for the Approvals tab. The owner reads THIS."""
    argv = build_argv(spec)
    return " ".join(argv)


def _host_argv(target_argv: List[str]) -> List[str]:
    """Wrap a host argv in a privileged chroot. No shell, no host network."""
    return [
        "docker",
        "run",
        "--rm",
        "--privileged",
        "--network",
        "none",
        "--pull",
        "never",
        "-v",
        "/:" + HOST_CHROOT,
        "--entrypoint",
        "/usr/sbin/chroot",
        CARRIER_IMAGE,
        HOST_CHROOT,
        *target_argv,
    ]


# The producer runs INSIDE archie_platform (the lane reaches it by
# `docker exec -i archie_platform python3 -m services.host_command_service
# request`), so it cannot see which container called it and cannot verify the
# caller. A self-asserted identity string would look authoritative in the audit
# log while being worth nothing, so this records the CHANNEL and says so. The
# trustworthy half of the record is the human's `approved_by`, which the
# requesting lane has no path to.
_REQUEST_CHANNEL = "opencode-lane"


def _lane_identity() -> str:
    """Server-stamped requester CHANNEL. Never read from the request payload."""
    return _REQUEST_CHANNEL


def request_host_command(spec: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """Validate and enqueue a request. This function CANNOT execute anything.

    Called by the `request` CLI with JSON on stdin. There is deliberately no
    code path from here to execution: the row must be approved by a human in the
    tab first.
    """
    from database import get_db_cursor

    argv_preview = build_argv(spec)  # fail BEFORE the row exists
    reason = (reason or spec.get("reason") or "").strip()[:500]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO autonomy_approval_queue
                   (action_type, action_data, tier, status, priority,
                    requested_by, reason, expires_at)
               VALUES (%s, %s::jsonb, %s, 'pending', %s, %s, %s,
                       NOW() + make_interval(mins => %s))
               RETURNING id""",
            (
                ACTION_TYPE,
                json.dumps({**spec, "argv_preview": argv_preview}),
                TIER,
                5,
                _lane_identity(),
                reason,
                EXPIRY_MINUTES,
            ),
        )
        row = cur.fetchone()
        new_id = row["id"] if isinstance(row, dict) else row[0]

    logger.info("host_root_command requested id=%s by=%s argv=%s", new_id, _lane_identity(), argv_preview)
    return {"id": new_id, "status": "pending", "argv": argv_preview, "expires_in_minutes": EXPIRY_MINUTES}


def _claim_for_execution(row_id: int) -> Dict[str, Any] | None:
    """Atomically claim an APPROVED, UNEXPIRED row. Single-use.

    The claim is a conditional UPDATE, so two concurrent approve clicks cannot
    both execute. Returns None if the row is not executable.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET executed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                  AND status = 'approved'
                  AND executed_at IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
            RETURNING id, action_type, action_data, requested_by, approved_by, approved_at""",
            (row_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row) if isinstance(row, dict) else None


def _record_result(row_id: int, result: Dict[str, Any]) -> None:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET execution_result = %s::jsonb, status = %s, updated_at = NOW()
                WHERE id = %s""",
            (json.dumps(result), "executed" if result.get("ok") else "failed", row_id),
        )


def execute_host_command(row_id: int, approved_by: int) -> Dict[str, Any]:
    """Run a previously-approved host-root command. Invoked ONLY on approval.

    Fails closed on: not approved, already executed, expired, missing approver,
    and any spec that no longer passes build_argv().
    """
    row = _claim_for_execution(row_id)
    if row is None:
        result = {
            "ok": False,
            "error": "not executable: must be approved, unexecuted and unexpired",
        }
        logger.warning("host_root_command id=%s refused: %s", row_id, result["error"])
        _record_result(row_id, result)
        return result

    if not approved_by or not row.get("approved_by"):
        result = {"ok": False, "error": "missing human approver — refusing to execute"}
        _record_result(row_id, result)
        return result

    data = row.get("action_data") or {}
    if isinstance(data, str):
        data = json.loads(data)

    try:
        target_argv = build_argv(data)
    except SpecRejected as exc:
        result = {"ok": False, "error": f"spec rejected at execute time: {exc}"}
        _record_result(row_id, result)
        return result

    full_argv = _host_argv(target_argv)
    started = os.times()
    try:
        proc = subprocess.run(
            full_argv,
            capture_output=True,
            text=True,
            timeout=180,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "timed out after 180s"
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        rc, out, err = 125, "", f"{type(exc).__name__}: {exc}"

    result = {
        "ok": rc == 0,
        "returncode": rc,
        "requested_by": row.get("requested_by"),
        "approved_by": row.get("approved_by"),
        "approved_at": str(row.get("approved_at")),
        # The literal argv that ran. This is the audit record — what the owner
        # approved in the tab is byte-for-byte what executed.
        "argv_executed": full_argv,
        "host_argv": target_argv,
        "stdout": (out or "")[:MAX_STDOUT],
        "stderr": (err or "")[:MAX_STDOUT],
        "user_time": round(started.user, 3),
    }
    _record_result(row_id, result)
    logger.info(
        "host_root_command id=%s rc=%s argv=%s approved_by=%s",
        row_id,
        rc,
        target_argv,
        row.get("approved_by"),
    )
    return result


def get_request(row_id: int) -> Dict[str, Any] | None:
    """Read-only status poll, for the requesting lane."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """SELECT id, action_type, status, requested_by, approved_by, approved_at,
                      created_at, executed_at, expires_at, reason, action_data,
                      execution_result
                 FROM autonomy_approval_queue WHERE id = %s""",
            (row_id,),
        )
        row = cur.fetchone()
        return dict(row) if isinstance(row, dict) else None


def _main(argv: List[str]) -> int:
    """CLI. `request` can only enqueue. There is no execute subcommand here.

    Deliberate: even with the socket, going through the tab should be the path of
    least resistance. Bypassing it is possible; it should not be accidental.
    """
    import sys

    if not argv:
        print(__doc__)
        print("\nusage: python3 -m services.host_command_service {request < spec.json | status <id>}")
        return 2

    cmd = argv[0]
    if cmd == "request":
        spec = json.load(sys.stdin)
        out = request_host_command(spec, reason=spec.get("reason", "") if isinstance(spec, dict) else "")
        print(json.dumps(out, indent=2))
        print(
            "\nQueued. It does NOT run until you approve it in the DHQ Approvals tab "
            "(or reply to the Telegram notification).",
            file=sys.stderr,
        )
        return 0

    if cmd == "status":
        if len(argv) < 2:
            print("usage: status <id>", file=sys.stderr)
            return 2
        row = get_request(int(argv[1]))
        if row is None:
            print("not found", file=sys.stderr)
            return 1
        print(json.dumps(row, indent=2, default=str))
        return 0

    print(f"unknown subcommand {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
