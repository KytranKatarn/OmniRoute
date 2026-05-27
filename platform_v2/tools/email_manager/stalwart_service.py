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


def create_mailbox(address: str, display_name: str = "", password: str = None, quota_gb: int = 1) -> dict:
    """Provision a new mailbox in Stalwart.

    Returns {ok: bool, password: str, error: str}.
    The generated password is returned so the caller can store it.
    """
    err = _check_password()
    if err:
        return err
    local_part = address.split("@")[0]
    _password = password or secrets.token_urlsafe(20)

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
