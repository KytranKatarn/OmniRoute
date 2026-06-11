"""Browser platform registry (#4006 — S.C.O.U.T. auth fabric phase 2a).

Data-driven replacement for the hardcoded platform allowlists (sidecar
login_app.py dicts, session_routes._SUPPORTED_PLATFORMS). The registry says
which sites the auth fabric may touch: interactive login capture (login_url
+ allowed_hosts), cookie import, and the opt-in generic health probe
(probe_url).

Validation is the point of this module — platform keys flow into filesystem
paths on the sidecar and hosts gate what a headed browser inside the owner's
trusted profile may navigate to. The sidecar re-validates independently
(never trusts the hub payload), but the hub rejects garbage first.

NO DNS-resolution check on hosts: hub split-horizon DNS maps our own public
subdomains to private IPs, so resolve-and-reject-private would block
capturing sessions on our own products.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Optional

from psycopg2.extras import Json

PLATFORM_RE = re.compile(r"^[a-z0-9_-]{2,32}$")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_BLOCKED_SUFFIXES = (".local", ".internal", ".lan")


def valid_public_host(host: str) -> bool:
    """Public FQDN only — reject IP literals, single-label (Docker service)
    names, and obviously-internal suffixes."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or len(h) > 253:
        return False
    try:
        ipaddress.ip_address(h)
        return False  # IP literal
    except ValueError:
        pass
    if "." not in h:
        return False  # single-label — would resolve to a compose service
    if h.endswith(_BLOCKED_SUFFIXES):
        return False
    return bool(_HOST_RE.match(h))


def _validate_url(url: str, allowed_hosts: list, field: str) -> Optional[str]:
    """https-only URL whose host is one of allowed_hosts. Returns error or None."""
    from urllib.parse import urlparse

    try:
        u = urlparse(url)
    except Exception:
        return f"{field}: invalid URL"
    if u.scheme != "https":
        return f"{field}: https required"
    if (u.hostname or "").lower() not in allowed_hosts:
        return f"{field}: host must be one of allowed_hosts"
    return None


def validate_platform_payload(
    platform: str,
    display_name: str,
    allowed_hosts: list,
    login_url: Optional[str] = None,
    probe_url: Optional[str] = None,
) -> Optional[str]:
    """Full payload validation. Returns an error string, or None if valid."""
    if not PLATFORM_RE.match(platform or ""):
        return "platform key must match ^[a-z0-9_-]{2,32}$"
    if not (display_name or "").strip() or len(display_name) > 100:
        return "display_name required (max 100 chars)"
    if not isinstance(allowed_hosts, list) or not allowed_hosts:
        return "allowed_hosts must be a non-empty list"
    hosts = [str(h).strip().lower() for h in allowed_hosts]
    bad = [h for h in hosts if not valid_public_host(h)]
    if bad:
        return f"allowed_hosts rejected (public FQDNs only): {', '.join(bad[:5])}"
    if login_url:
        err = _validate_url(login_url, hosts, "login_url")
        if err:
            return err
    if probe_url:
        err = _validate_url(probe_url, hosts, "probe_url")
        if err:
            return err
    return None


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


def list_platforms(enabled_only: bool = True) -> list:
    from database import get_db_cursor

    where = "WHERE enabled" if enabled_only else ""
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            f"""SELECT platform, display_name, login_url, allowed_hosts,
                       probe_url, enabled, source, created_at, updated_at
                FROM browser_platforms {where}
                ORDER BY source, platform"""
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def get_platform(platform: str) -> Optional[dict]:
    from database import get_db_cursor

    if not PLATFORM_RE.match(platform or ""):
        return None
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            """SELECT platform, display_name, login_url, allowed_hosts,
                      probe_url, enabled, source, created_at, updated_at
               FROM browser_platforms WHERE platform = %s""",
            (platform,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def add_platform(
    platform: str,
    display_name: str,
    allowed_hosts: list,
    login_url: Optional[str] = None,
    probe_url: Optional[str] = None,
) -> dict:
    """Insert a custom platform. Raises ValueError on validation failure or
    duplicate key."""
    from database import get_db_cursor

    platform = (platform or "").strip().lower()
    hosts = [str(h).strip().lower() for h in (allowed_hosts or []) if str(h).strip()]
    err = validate_platform_payload(platform, display_name, hosts, login_url, probe_url)
    if err:
        raise ValueError(err)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO browser_platforms
                   (platform, display_name, login_url, allowed_hosts, probe_url, source)
               VALUES (%s, %s, %s, %s, %s, 'custom')
               ON CONFLICT (platform) DO NOTHING
               RETURNING platform""",
            (platform, display_name.strip(), login_url, Json(hosts), probe_url),
        )
        if cur.fetchone() is None:
            raise ValueError(f"platform '{platform}' already exists")
    return {
        "platform": platform,
        "display_name": display_name.strip(),
        "login_url": login_url,
        "allowed_hosts": hosts,
        "probe_url": probe_url,
        "source": "custom",
        "enabled": True,
    }
