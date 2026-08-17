"""Stalwart Mail admin API wrapper for Email HQ.

Provisions and manages mailboxes on the Stalwart mail server.

Stalwart runs in its own Docker compose stack at /mnt/archie_brain/stalwart-mail/.
stalwart_mail is now on archie_network so archie_platform reaches it directly.

Admin URL: http://stalwart_mail:8080  (plain HTTP on shared Docker network — no TLS)
IMAP: stalwart_mail:993 (IMAP4_SSL — direct container-to-container, no hairpin NAT)

The admin API uses HTTP Basic auth. The fallback-admin user is "admin" and the
password comes from STALWART_ADMIN_PASSWORD env var (default: KytranMail2026!).
"""

from __future__ import annotations

import logging
import os
import secrets

import requests

logger = logging.getLogger(__name__)

# Stalwart admin API — plain HTTP via shared Docker network
_BASE = os.getenv("STALWART_ADMIN_URL", "http://stalwart_mail:8080")
_USER = os.getenv("STALWART_ADMIN_USER", "admin")
_PASS = os.getenv("STALWART_ADMIN_PASSWORD") or ""

# Permissions required for IMAP + SMTP access on every provisioned mailbox.
# Without these, Stalwart authenticates the password but then rejects the session
# with "Unauthorized access (security.unauthorized) details = authenticate".
_MAILBOX_PERMISSIONS = [
    "authenticate",
    "imap-authenticate",
    "email-send",
    "imap-select",
    "imap-examine",
    "imap-fetch",
    "imap-search",
    "imap-list",
    "imap-lsub",
    "imap-store",
    "imap-expunge",
    "imap-idle",
    "imap-copy",
    "imap-move",
    "imap-namespace",
    "imap-append",
]


def _auth() -> tuple:
    return (_USER, _PASS)


def _check_password() -> dict | None:
    """Return an error dict if admin password is not configured, else None."""
    if not _PASS:
        return {"ok": False, "error": "STALWART_ADMIN_PASSWORD not set in environment"}
    return None


def _get(path: str, params: dict = None, timeout: int = 10) -> requests.Response | None:
    """Internal GET helper. Returns None on connection error."""
    try:
        return requests.get(
            f"{_BASE}{path}",
            auth=_auth(),
            params=params,
            timeout=timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        logger.warning("Stalwart unreachable (GET %s): %s", path, exc)
        return None
    except Exception as exc:
        logger.error("Stalwart GET %s error: %s", path, exc)
        return None


def test_connection() -> dict:
    """Check if Stalwart admin API is reachable. Returns {ok, status, error}."""
    if not _PASS:
        return {"ok": False, "error": "STALWART_ADMIN_PASSWORD not set in environment"}
    try:
        resp = requests.get(
            f"{_BASE}/api/principal",
            auth=_auth(),
            params={"limit": "1"},
            timeout=5,
        )
        return {"ok": resp.status_code == 200, "status": resp.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Outbound queue health (#4035) — delivery-failure alerting
# ---------------------------------------------------------------------------

# Tunables (env-overridable, sane defaults). A queued message is "failing" when
# it has been retried this many times, has aged past this many hours, or a domain
# reports a non-scheduled status. A large total backlog is also flagged.
_QUEUE_RETRY_THRESHOLD = int(os.getenv("STALWART_QUEUE_RETRY_THRESHOLD", "3"))
_QUEUE_AGE_HOURS = float(os.getenv("STALWART_QUEUE_AGE_HOURS", "6"))
_QUEUE_BACKLOG_THRESHOLD = int(os.getenv("STALWART_QUEUE_BACKLOG_THRESHOLD", "25"))
_QUEUE_DETAIL_CAP = int(os.getenv("STALWART_QUEUE_DETAIL_CAP", "60"))


def check_outbound_queue_health() -> dict:
    """Inspect the Stalwart outbound queue for delivery FAILURES (#4035).

    Reads GET /api/queue/messages (+ per-message detail) and classifies a message
    as 'failing' when a domain has been retried >= the retry threshold, the message
    has aged past the age threshold, or a domain reports a failed/bounced status.
    A large total backlog is flagged separately. Fail-safe: if Stalwart is
    unreachable or the API errors, returns severity='unknown' and NEVER raises.

    Returns {ok, severity in ('ok','warning','error','unknown'), total,
             failing:[{id, age_h, retry, domain, status}], failing_count,
             reasons:[...], alert_key, error?}.
    """
    from datetime import datetime, timezone

    if not _PASS:
        return {"ok": False, "severity": "unknown", "error": "STALWART_ADMIN_PASSWORD not set"}

    resp = _get("/api/queue/messages", params={"limit": "1000"})
    if resp is None or resp.status_code != 200:
        return {
            "ok": False,
            "severity": "unknown",
            "error": f"queue API unavailable (status={getattr(resp, 'status_code', None)})",
        }
    data = (resp.json() or {}).get("data", {}) or {}
    ids = data.get("items", []) or []
    total = data.get("total", len(ids))

    now = datetime.now(timezone.utc)

    def _parse(ts):
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return None

    failing: list = []
    for mid in ids[:_QUEUE_DETAIL_CAP]:
        d = _get(f"/api/queue/messages/{mid}")
        if d is None or d.status_code != 200:
            continue
        m = (d.json() or {}).get("data", {}) or {}
        created = _parse(m.get("created"))
        age_h = (now - created).total_seconds() / 3600.0 if created else 0.0
        for dom in m.get("domains", []) or []:
            retry = int(dom.get("retry_num", 0) or 0)
            status = str(dom.get("status", "")).lower()
            if (
                retry >= _QUEUE_RETRY_THRESHOLD
                or age_h >= _QUEUE_AGE_HOURS
                or status
                in (
                    "failed",
                    "bounced",
                    "error",
                )
            ):
                failing.append(
                    {
                        "id": mid,
                        "age_h": round(age_h, 1),
                        "retry": retry,
                        "domain": dom.get("name"),
                        "status": status,
                    }
                )

    reasons: list = []
    severity = "ok"
    if failing:
        severity = "error"
        reasons.append(
            f"{len(failing)} message(s) failing delivery "
            f"(retry>={_QUEUE_RETRY_THRESHOLD} / age>={_QUEUE_AGE_HOURS}h / failed status)"
        )
    if total >= _QUEUE_BACKLOG_THRESHOLD:
        severity = "error" if severity == "error" else "warning"
        reasons.append(f"outbound backlog {total} >= {_QUEUE_BACKLOG_THRESHOLD}")

    # Dedup key — alert only re-fires when the failing-count / backlog band changes.
    alert_key = f"{severity}:{len(failing)}:{int(total >= _QUEUE_BACKLOG_THRESHOLD)}"
    return {
        "ok": True,
        "severity": severity,
        "total": total,
        "failing": failing[:20],
        "failing_count": len(failing),
        "reasons": reasons,
        "alert_key": alert_key,
    }


def list_accounts() -> list:
    """List all individual mailbox accounts in Stalwart."""
    resp = _get("/api/principal", params={"type": "individual", "limit": "500"})
    if resp is None:
        return []
    if resp.status_code == 200:
        data = resp.json()
        # Stalwart v0.11 wraps the payload: {"data": {"items": [...], "total": N}}
        # Earlier versions returned {"items": [...]} or a plain list directly.
        if isinstance(data, list):
            return data
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        return data.get("items", [])
    logger.error("Stalwart list_accounts failed: %s %s", resp.status_code, resp.text[:200])
    return []


def grant_default_permissions(address: str) -> bool:
    """Grant IMAP + SMTP permissions to an existing Stalwart mailbox.

    Must be called after create_mailbox (or for any account created without permissions).
    Returns True on success.
    """
    if _check_password():
        logger.error("Stalwart grant_permissions skipped — admin password not configured")
        return False
    local_part = address.split("@")[0]
    ops = [{"action": "addItem", "field": "enabledPermissions", "value": p} for p in _MAILBOX_PERMISSIONS]
    try:
        resp = requests.patch(
            f"{_BASE}/api/principal/{local_part}",
            auth=_auth(),
            json=ops,
            timeout=10,
        )
        if resp.status_code in (200, 204):
            logger.info("Stalwart: granted permissions to %s", address)
            return True
        logger.error("Stalwart grant_permissions failed for %s: %s %s", address, resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.error("Stalwart grant_permissions error for %s: %s", address, exc)
        return False


def _account_exists(local_part: str) -> bool:
    """True if a Stalwart principal with this name already exists.

    Fails SAFE (returns True) when the roster cannot be read: assuming the account
    exists only costs one redundant password reset, whereas assuming it is new
    leaves a mailbox holding a password the server never accepted.

    NOTE: do NOT use ``get_mailbox()`` for this — it returns None even for
    accounts that demonstrably authenticate (verified 2026-08-15 against
    access@), so it cannot distinguish "absent" from "present".
    """
    try:
        accounts = list_accounts() or []
        return local_part.lower() in {(a.get("name") or "").lower() for a in accounts}
    except Exception as exc:
        logger.warning("Stalwart: account-existence check failed for %s: %s", local_part, exc)
        return True


def _protected_mailbox_type(address: str):
    """The mailbox_type when this address is an owner/business mailbox, else None.

    #5698: on 2026-08-16 the OWNER principal's Stalwart secret was rotated to an
    unattributed token while email_mailboxes was untouched — a forked credential
    that took all 156 mailboxes' sync down for ~20h. Owner/business principals
    must never be reset as a side effect of an 'ensure mailbox' sweep.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT mailbox_type FROM email_mailboxes WHERE lower(address) = lower(%s)",
                (address,),
            )
            row = cur.fetchone()
        mtype = (row["mailbox_type"] if row else None) or None
        return mtype if mtype in ("owner", "business") else None
    except Exception as exc:
        # Fail SAFE for the guard's purpose: unknown type -> treat as protected
        # is tempting, but it would brick agent provisioning on any DB blip.
        # The guard exists for owner/business rows we could not read — log loud.
        logger.warning("Stalwart: mailbox-type lookup failed for %s: %s", address, exc)
        return None


def _audit_secret_rotation(address: str, caller: str, ok: bool, note: str = "") -> None:
    """Durable (DB) record of every Stalwart secret rotation — #5698.

    The 2026-08-16 rotation could not be attributed because Stalwart does not
    log principal updates and docker-log rotation ate the window. This row in
    audit_log survives both.
    """
    try:
        from database import get_db_cursor
        from psycopg2.extras import Json

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO audit_log (action, resource_type, details, metadata, severity, category)
                   VALUES ('STALWART_SECRET_ROTATION', 'mailbox', %s, %s, %s, 'email_security')""",
                (
                    f"{address}: rotation {'applied' if ok else 'refused/failed'} via {caller}. {note}".strip(),
                    Json({"address": address, "caller": caller, "ok": ok, "note": note}),
                    "warning" if ok else "info",
                ),
            )
    except Exception as exc:
        logger.error("Stalwart: audit write for %s rotation failed: %s", address, exc)


def _caller_name() -> str:
    """Best-effort name of the code calling into this module (for the audit row)."""
    try:
        import inspect

        for frame in inspect.stack()[2:8]:
            fn = frame.filename
            if "stalwart_service" not in fn:
                return f"{fn.rsplit('/', 1)[-1]}:{frame.function}:{frame.lineno}"
    except Exception:
        pass
    return "unknown"


def create_mailbox(
    address: str, display_name: str = "", password: str = None, quota_gb: int = 1, force_reset: bool = False
) -> dict:
    """Provision a new mailbox in Stalwart.

    Returns {ok: bool, password: str, error: str}.

    force_reset: required to reset the secret of an ALREADY-EXISTING principal
    whose mailbox is owner/business (#5698). Explicit admin provisioning routes
    pass True; sweeps and agent provisioning must not.
    The generated password is returned so the caller can store it.
    """
    err = _check_password()
    if err:
        return err
    local_part = address.split("@")[0]
    _password = password or secrets.token_urlsafe(20)
    # Record whether the principal already exists BEFORE we POST — afterwards the
    # two cases are indistinguishable (both answer 2xx). Fails SAFE: if the lookup
    # errors we assume it existed, which only costs a redundant password reset.
    _existed_before = _account_exists(local_part)

    try:
        resp = requests.post(
            f"{_BASE}/api/principal",
            auth=_auth(),
            json={
                "type": "individual",
                "name": local_part,
                "description": display_name or local_part,
                "secrets": [_password],
                "emails": [address],
                "quota": quota_gb * 1024 * 1024 * 1024,
                "roles": ["user"],
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            # A 2xx does NOT prove our password was applied. When the principal
            # already exists, Stalwart keeps its EXISTING secret and still answers
            # 2xx — so the caller stores a password the server will never accept,
            # producing a mailbox that looks provisioned and cannot authenticate.
            # Measured 2026-08-15: axiom@ and tester@ were created "successfully"
            # and both failed IMAP login; every other new mailbox worked. Force the
            # secret so the returned credential is always the usable one.
            if _existed_before:
                _protected = _protected_mailbox_type(address)
                if _protected and not force_reset:
                    # #5698: never rotate an owner/business principal as a side
                    # effect. The caller gets a hard refusal, and the attempt is
                    # durably recorded so the NEXT mystery rotation has a trail.
                    _audit_secret_rotation(
                        address,
                        _caller_name(),
                        ok=False,
                        note=f"create_mailbox refused reset of existing {_protected} principal (force_reset not set)",
                    )
                    return {
                        "ok": False,
                        "error": f"refusing to reset existing {_protected} principal {address} — pass force_reset=True",
                    }
                reset = update_password(address, _password)
                if not reset.get("ok"):
                    logger.error(
                        "Stalwart: %s already existed and password reset failed: %s",
                        address,
                        reset.get("error"),
                    )
                    return {"ok": False, "error": f"account exists, password reset failed: {reset.get('error')}"}
                logger.info("Stalwart: %s already existed — password reset to the stored one", address)
            else:
                logger.info("Stalwart: provisioned mailbox %s", address)
            grant_default_permissions(address)
            return {"ok": True, "password": _password}
        err = resp.text[:300]
        logger.error("Stalwart create_mailbox failed for %s: %s %s", address, resp.status_code, err)
        return {"ok": False, "error": f"{resp.status_code}: {err}"}
    except requests.exceptions.ConnectionError as exc:
        return {"ok": False, "error": f"Connection refused — is stalwart_mail running? {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_mailbox(address: str) -> dict:
    """Remove a mailbox from Stalwart. Returns {ok: bool, error: str}."""
    err = _check_password()
    if err:
        return err
    local_part = address.split("@")[0]
    try:
        resp = requests.delete(
            f"{_BASE}/api/principal/{local_part}",
            auth=_auth(),
            timeout=10,
        )
        if resp.status_code in (200, 204):
            logger.info("Stalwart: deleted mailbox %s", address)
            return {"ok": True}
        return {"ok": False, "error": f"{resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.ConnectionError as exc:
        return {"ok": False, "error": f"Connection refused — is stalwart_mail running? {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def update_password(address: str, password: str = None) -> dict:
    """Set a new password for an existing Stalwart mailbox.

    Returns {ok: bool, password: str, error: str}.
    """
    err = _check_password()
    if err:
        return err
    local_part = address.split("@")[0]
    _password = password or secrets.token_urlsafe(20)
    try:
        resp = requests.patch(
            f"{_BASE}/api/principal/{local_part}",
            auth=_auth(),
            json=[{"action": "set", "field": "secrets", "value": [_password]}],
            timeout=10,
        )
        if resp.status_code in (200, 204):
            logger.info("Stalwart: rotated password for %s", address)
            # #5698: every applied rotation leaves a durable DB audit row —
            # Stalwart doesn't log principal updates and docker logs rotate.
            _audit_secret_rotation(address, _caller_name(), ok=True)
            return {"ok": True, "password": _password}
        err = resp.text[:300]
        logger.error("Stalwart update_password failed for %s: %s %s", address, resp.status_code, err)
        return {"ok": False, "error": f"{resp.status_code}: {err}"}
    except requests.exceptions.ConnectionError as exc:
        return {"ok": False, "error": f"Connection refused: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_mailbox(address: str) -> dict | None:
    """Fetch a single mailbox account. Returns the account dict or None."""
    local_part = address.split("@")[0]
    resp = _get(f"/api/principal/{local_part}")
    if resp is None:
        return None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    logger.error("Stalwart get_mailbox %s: %s", address, resp.status_code)
    return None
