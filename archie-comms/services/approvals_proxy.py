"""Thin cockpit->platform approvals proxy (COO Cockpit Slice 1).

Mirrors conversation_service.dhq_chat_raw: GET/POST the platform's
@_require_internal_key approval endpoints with Bearer INTERNAL_API_KEY over the
internal Docker network (PLATFORM_URL=http://archie_platform:3000 — never a
public hostname). approve()/deny() are fail-CLOSED: any transport/non-ok result
returns {"ok": False, "error": ...} so the cockpit never optimistically shows an
approval as done. All approval *execution* stays on the platform; comms adds no
business logic and no new secrets.
"""

import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

# An approval id is always "<source>:<int>" (autonomy:123). Enforcing this shape
# before we interpolate it into the internal URL blocks path-traversal / SSRF to
# OTHER @_require_internal_key endpoints — a crafted or prompt-injected id like
# "../engine/telemetry" would otherwise ride the Bearer key to a different route.
_VALID_APPROVAL_ID = re.compile(r"^[a-z_]+:\d+$")


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"}


def list_pending():
    """Pending Tier-2 approvals from the platform. Read path is fail-soft:
    on any error return [] (the panel simply shows nothing, never an error card)."""
    try:
        r = requests.get(f"{_base()}/api/internal/approvals/pending", headers=_headers(), timeout=10)
        if r.status_code == 200:
            return (_json_or_empty(r) or {}).get("approvals", [])
    except Exception as exc:
        logger.warning("approvals list failed: %s", exc)
    return []


def approve(approval_id, user_id):
    return _act(approval_id, "approve", {"user_id": user_id})


def deny(approval_id, user_id, reason=""):
    return _act(approval_id, "deny", {"user_id": user_id, "reason": reason})


def _json_or_empty(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def _act(approval_id, verb, body):
    """POST the approve/deny action. Fail-CLOSED: only a 200 with ok=True is a
    success; every other outcome (non-200, ok=False, transport error) returns
    {"ok": False, "error": ...} so the row stays pending in the UI."""
    if not _VALID_APPROVAL_ID.match(str(approval_id or "")):
        logger.warning("approval %s rejected: malformed id %r", verb, approval_id)
        return {"ok": False, "error": "invalid approval id"}
    try:
        r = requests.post(
            f"{_base()}/api/internal/approvals/{approval_id}/{verb}",
            json=body,
            headers=_headers(),
            timeout=15,
        )
        data = _json_or_empty(r)
        if r.status_code == 200 and data.get("ok"):
            return data
        return {"ok": False, "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-CLOSED
        logger.warning("approval %s failed: %s", verb, exc)
        return {"ok": False, "error": str(exc)}
