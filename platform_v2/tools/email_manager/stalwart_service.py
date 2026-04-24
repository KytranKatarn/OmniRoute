"""Stalwart Mail admin API wrapper for Email HQ.

Provisions and manages mailboxes on the Stalwart mail server.

Stalwart runs in its own Docker compose stack at /mnt/archie_brain/stalwart-mail/.
It is NOT on the archie_internal network, so we reach it via the host IP.

External admin URL: https://192.168.1.200:8443  (host port 8443 -> container port 443)
Container HTTP (internal, plain): http://stalwart_mail:8080  (NOT reachable from archie_platform)

The admin API uses HTTP Basic auth. The fallback-admin user is "admin" and the
password comes from STALWART_ADMIN_PASSWORD env var (default: KytranMail2026!).

Self-signed TLS is used on port 8443, so verify=False is intentional.
"""

from __future__ import annotations

import logging
import os
import secrets

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning  # type: ignore

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Stalwart admin API — HTTPS on host port 8443 (container :443)
_BASE = os.getenv("STALWART_ADMIN_URL", "https://192.168.1.200:8443")
_USER = os.getenv("STALWART_ADMIN_USER", "admin")
_PASS = os.getenv("STALWART_ADMIN_PASSWORD") or ""


def _auth() -> tuple:
    return (_USER, _PASS)


def _get(path: str, params: dict = None, timeout: int = 10) -> requests.Response | None:
    """Internal GET helper. Returns None on connection error."""
    try:
        return requests.get(
            f"{_BASE}{path}",
            auth=_auth(),
            params=params,
            timeout=timeout,
            verify=False,
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
            verify=False,
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
        # Stalwart v0.11 returns {"items": [...], "total": N} or a plain list
        if isinstance(data, list):
            return data
        return data.get("items", [])
    logger.error("Stalwart list_accounts failed: %s %s", resp.status_code, resp.text[:200])
    return []


def create_mailbox(address: str, display_name: str = "", password: str = None) -> dict:
    """Provision a new mailbox in Stalwart.

    Returns {ok: bool, password: str, error: str}.
    The generated password is returned so the caller can store it.
    """
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
                "quota": 1073741824,  # 1 GB
            },
            timeout=10,
            verify=False,
        )
        if resp.status_code in (200, 201):
            logger.info("Stalwart: provisioned mailbox %s", address)
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
    local_part = address.split("@")[0]
    try:
        resp = requests.delete(
            f"{_BASE}/api/principal/{local_part}",
            auth=_auth(),
            timeout=10,
            verify=False,
        )
        if resp.status_code in (200, 204):
            logger.info("Stalwart: deleted mailbox %s", address)
            return {"ok": True}
        return {"ok": False, "error": f"{resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.ConnectionError as exc:
        return {"ok": False, "error": f"Connection refused — is stalwart_mail running? {exc}"}
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
