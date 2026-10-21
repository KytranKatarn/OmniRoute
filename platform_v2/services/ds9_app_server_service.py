"""DS9 Codex app-server connections, as the platform's DS9 tab should show them.

The DS9 gateway can drive the OpenAI Codex CLI's own `codex app-server` as the
`codex-app-server` provider (see Dev HQ #7378). That connection lives in DS9's
OWN store - table `provider_connections` in DS9's SQLite - and is created and
managed through DS9's own dashboard. The platform's DHQ "Deep Space 9 (DS9)" tab
lists the PLATFORM's `engineer_providers` table (the external AI upstreams:
cerebras, groq, openrouter, the DS9 omni* aliases, opencode_zen, ...), which
does NOT include the app-server.

The result: an operator looking at the platform's DS9 pane can see the
app-server being used in the observation-only quota card, but cannot tell WHO it
is authorized as, whether the upstream is actually reachable, which models it
offers, or toggle its routing. This module supplies that view.

TWO READ PATHS, both strictly read-only:

  * DS9's SQLite, opened `mode=ro&immutable=1` - the same approach
    omniroute_quota_service uses, and the reason is the same: DS9 owns this
    data and the platform is a reader. The platform must never WRITE to DS9's
    store, so there is no INSERT/UPDATE anywhere in this module.
  * DS9's own API, for the live health verdict. The provider test is DS9's
    code and already answers exactly the question the tab needs - is the
    upstream reachable AND is the CLI signed in - with three distinct
    diagnoses (`ok`, `app_server_login_required`, `app_server_unconfigured`).
    Re-implementing that probe here would be a second, drifting copy of it, so
    this module CALLS it and reports the verdict.

    The call is a POST (DS9's provider-test endpoint takes no body) and it is
    side-effect-free: it probes, it does not mutate the connection.

Both paths degrade independently. DS9 unreachable, or its store missing, yields
an empty-but-successful response with a reason - the DS9 tab must never break
because a gateway it merely reports on is down.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

# DS9's store, mounted READ-ONLY into the platform (docker-compose.yml:
# /home/kytran/.omniroute:/omniroute-data:ro).
DS9_DB = os.getenv("OMNIROUTE_DB_PATH", "/omniroute-data/storage.sqlite")

# The API ROOT of DS9 - no /v1 suffix. This is deliberately NOT
# OMNIROUTE_BASE_URL: that one is the *inference* base and carries a /v1
# (docker-compose.yml: http://host.docker.internal:20129/v1), which would
# produce ".../v1/api/providers/<id>/test" and 404. DS9's management API
# hangs off the root.
DS9_API_BASE_URL = os.getenv("DS9_API_BASE_URL", "http://host.docker.internal:20129").rstrip("/")

# The URL the OPERATOR's browser should open. The browser runs on the host, so
# it cannot resolve the container's host.docker.internal - it needs the host's
# own address for DS9.
DS9_DASHBOARD_URL = os.getenv("DS9_DASHBOARD_URL", "http://127.0.0.1:20129").rstrip("/")

# The provider id DS9 uses for the Codex app-server transport.
APP_SERVER_PROVIDER = "codex-app-server"

# DS9 lists the app-server's models as <alias>/<model> plus a reasoning-effort
# variant of each (-ultra/-max/-xhigh/-high/-medium/-low). The card wants the
# BASE models - those are what an operator picks - plus a count of the variants.
MODEL_VARIANT_SUFFIXES = (
    "-ultra",
    "-max",
    "-xhigh",
    "-high",
    "-medium",
    "-low",
)


def _is_variant(model_id: str) -> bool:
    return any(model_id.endswith(sfx) for sfx in MODEL_VARIANT_SUFFIXES)


# The provider-test endpoint is a POST with no body, so it is NOT a "read" by
# HTTP semantics. It is still side-effect-free (it probes), but it can take as
# long as the upstream takes to answer, so it gets a tight budget of its own -
# separate from the (fast) store read.
PROBE_TIMEOUT = float(os.getenv("DS9_APP_SERVER_PROBE_TIMEOUT", "8"))

# Do not let a huge provider list blow up the response.
MAX_MODELS = 50


def _ds9_api_key() -> str:
    return os.getenv("OMNIROUTE_API_KEY", "").strip()


def _read_connections() -> List[Dict[str, Any]]:
    """DS9's app-server connection rows, read from DS9's store. READ-ONLY.

    Returns [] (never raises) if DS9's store is missing or unreadable - the
    platform may well run where DS9 does not.
    """
    if not os.path.exists(DS9_DB):
        logger.debug("ds9_app_server: DS9 store not present at %s", DS9_DB)
        return []
    # Read WAL-correctly if we can, and fall back if we cannot.
    #
    # DS9 runs SQLite in WAL mode, so a plain \`mode=ro\` connection sees the
    # WAL and is therefore CURRENT. \`immutable=1\` (what omniroute_quota_service
    # uses) tells SQLite the file can never change, which makes it IGNORE the
    # WAL - it reads the last checkpointed snapshot instead. Measured here:
    # mode=ro saw 9356 call_logs, immutable=1 saw 9355. Prefer mode=ro, and
    # fall back to immutable=1 for a deployment where the -shm sidecar is not
    # readable (a read-only mount can make a plain WAL read fail).
    conn = None
    for uri in (
        f"file:{DS9_DB}?mode=ro",
        f"file:{DS9_DB}?mode=ro&immutable=1",
    ):
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            break
        except sqlite3.Error as exc:
            logger.debug("ds9_app_server: cannot open %s: %s", uri, exc)
            conn = None
    if conn is None:
        logger.warning("ds9_app_server: cannot open DS9 store at %s", DS9_DB)
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, provider, name, is_active, auth_type, provider_specific_data,
                   last_tested, test_status, created_at
            FROM provider_connections
            WHERE provider = ?
            ORDER BY is_active DESC, name
            """,
            (APP_SERVER_PROVIDER,),
        )
        rows = cur.fetchall()
    except sqlite3.Error as exc:
        logger.warning("ds9_app_server: cannot read DS9 connections: %s", exc)
        return []
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    out: List[Dict[str, Any]] = []
    for row in rows:
        (cid, provider, name, is_active, auth_type, psd, last_tested, test_status, created_at) = row
        out.append(
            {
                "id": cid,
                "provider": provider,
                "name": name or "Codex app-server",
                "is_active": bool(is_active),
                "auth_type": auth_type,
                "last_tested": last_tested,
                "test_status": test_status,
                "created_at": created_at,
                "provider_specific_data": _safe_json(psd),
            }
        )
    return out


def _safe_json(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _probe(connection_id: str) -> Optional[Dict[str, Any]]:
    """Ask DS9 whether the app-server is reachable AND signed in.

    This is DS9's own provider test - it distinguishes "up but logged out"
    (app_server_login_required) from "not configured" (app_server_unconfigured)
    from "healthy" (ok). Re-implementing that logic here would give the tab a
    second, drifting copy of it.
    """
    key = _ds9_api_key()
    if not key:
        return None
    url = f"{DS9_API_BASE_URL}/api/providers/{connection_id}/test"
    body = json.dumps({}).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        logger.warning("ds9_app_server: provider test HTTP %s for %s", exc.code, connection_id)
        return {"valid": False, "error": f"DS9 provider test returned HTTP {exc.code}"}
    except (urlerror.URLError, OSError, ValueError) as exc:
        logger.warning("ds9_app_server: provider test failed for %s: %s", connection_id, exc)
        return {"valid": False, "error": f"DS9 unreachable: {exc}"}
    return payload if isinstance(payload, dict) else None


def _models() -> Dict[str, Any]:
    """The models DS9 offers for the app-server, from DS9's own /v1/models.

    DS9 lists the app-server's models as <alias>/<model> plus a reasoning-effort
    VARIANT of each (-ultra/-max/-xhigh/-high/-medium/-low). An operator picks
    a base model, so the base models are returned separately from the variant
    count rather than letting 50 reasoning variants crowd out the 7 real ones.

    Read-only, and failures degrade to an empty result.
    """
    key = _ds9_api_key()
    if not key:
        return {"models": [], "variant_count": 0}
    url = f"{DS9_API_BASE_URL}/v1/models"
    req = urlrequest.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urlrequest.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urlerror.URLError, OSError, ValueError) as exc:
        logger.warning("ds9_app_server: /v1/models failed: %s", exc)
        return {"models": [], "variant_count": 0}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {"models": [], "variant_count": 0}
    models: List[Dict[str, Any]] = []
    variant_count = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.startswith("cxa/"):
            continue
        if _is_variant(model_id):
            variant_count += 1
            continue
        models.append(
            {
                "id": model_id,
                "display_name": item.get("name") or item.get("display_name") or model_id,
            }
        )
        if len(models) >= MAX_MODELS:
            break
    return {"models": models, "variant_count": variant_count}


# The health probe's conditions. These are the states an operator can act on,
# and each needs a DIFFERENT action, which is why they are not collapsed into
# a single "up/down".
APP_SERVER_CONDITIONS = (
    "healthy",  # reachable and signed in
    "disabled",  # the operator turned the connection off on purpose
    "down",  # the sidecar is not answering its readiness probe
    "not_ready",  # the sidecar answered but reports itself not ready
    "signed_out",  # the sidecar is up but the Codex CLI is not signed in
    "not_configured",  # the adapter has no URL/token for this connection
    "turn_failed",  # the sidecar accepted the request but the turn failed
    "unreachable",  # DS9 could not be reached, so the state is UNKNOWN
    "absent",  # DS9 reports no app-server connection at all
)

# DS9's own diagnosis codes for this provider, mapped to the condition each
# one means. DS9 probes the sidecar's /readyz and its account/read, so its
# verdict already distinguishes "the sidecar is down" from "DS9 is down" — the
# two need different actions, so they must not be collapsed.
#
#   app_server_unreachable    -> the sidecar's /readyz could not be fetched
#   app_server_not_ready      -> the sidecar answered, but is not ready
#   app_server_login_required -> reachable, but the Codex CLI is signed out
#   app_server_unconfigured   -> the adapter has no URL/token
#   app_server_turn_failed    -> the sidecar ran a turn and it failed
#
# Source: src/app/api/providers/[id]/test/codexAppServerHealth.ts
_DIAGNOSIS_CONDITIONS = {
    "app_server_unreachable": "down",
    "app_server_not_ready": "not_ready",
    "app_server_login_required": "signed_out",
    "app_server_unconfigured": "not_configured",
    "app_server_turn_failed": "turn_failed",
}

_CONDITION_DETAIL = {
    "down": (
        "The Codex app-server sidecar is NOT answering its readiness probe "
        "(app_server_unreachable). The unit is ds9-codex-appserver.service — "
        "check it with: systemctl status ds9-codex-appserver.service"
    ),
    "not_ready": ("The Codex app-server sidecar answered but reports itself NOT READY " "(app_server_not_ready)."),
    "signed_out": (
        "The Codex app-server is up but the Codex CLI is NOT SIGNED IN "
        "(app_server_login_required). It needs the owner to sign in again — the "
        "isolated login lives in the sidecar's own CODEX_HOME, not the owner's."
    ),
    "not_configured": (
        "The Codex app-server is not configured (app_server_unconfigured) — the "
        "adapter has no URL/token for the connection."
    ),
    "turn_failed": ("The Codex app-server ran a turn and it FAILED (app_server_turn_failed)."),
    "unreachable": ("DS9 could not be reached, so the Codex app-server's state is UNKNOWN " "(not healthy)."),
}


def _classify_verdict(verdict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn DS9's provider-test verdict into a state the platform can act on.

    ONE classifier, used by BOTH the tab card and the health monitor, so the
    two can never disagree about what state the app-server is in.

    Returns {state, code, message, latency_ms}:
      state     "authenticated" | "down" | "not_ready" | "signed_out" |
                "not_configured" | "turn_failed" | "unknown"
      code      DS9's own diagnosis code, or None
      message   DS9's own message, or None
    """
    out = {
        "state": "unknown",
        "code": None,
        "message": None,
        "latency_ms": None,
    }
    if verdict is None:
        # DS9 itself could not be reached — UNKNOWN, never "healthy".
        return out
    out["latency_ms"] = verdict.get("latencyMs")
    diagnosis = verdict.get("diagnosis") or {}
    if isinstance(diagnosis, dict):
        out["code"] = diagnosis.get("code")
        out["message"] = diagnosis.get("message")
    if verdict.get("valid"):
        out["state"] = "authenticated"
    elif out["code"] in _DIAGNOSIS_CONDITIONS:
        out["state"] = _DIAGNOSIS_CONDITIONS[out["code"]]
    return out


def get_app_server_status() -> Dict[str, Any]:
    """The DS9 tab's view of the Codex app-server connections.

    Shape (stable for the tab):
      {
        "success": bool,
        "connections": [ { id, name, provider, is_active, auth_state, health,
                           models, last_tested, ... } ],
        "reason": str | None     # why it is empty, when it is
      }

    `auth_state` is one of:
      "authenticated"  - DS9's provider test says valid
      "signed_out"     - upstream is up but the Codex CLI is not signed in
      "not_configured" - the adapter has no URL/token for this connection
      "unknown"        - DS9 could not be reached, or has no verdict
    """
    connections = _read_connections()
    if not connections:
        return {
            "success": True,
            "connections": [],
            "reason": "DS9 reports no Codex app-server connection.",
        }

    models = _models()
    base_models = models.get("models") or []
    variant_count = models.get("variant_count") or 0
    out: List[Dict[str, Any]] = []
    for conn in connections:
        verdict = _probe(conn["id"])
        classified = _classify_verdict(verdict)
        auth_state = classified["state"]
        health: Dict[str, Any] = {}
        if verdict is not None:
            health = {
                "valid": bool(verdict.get("valid")),
                "latency_ms": classified["latency_ms"],
                "tested_at": verdict.get("testedAt"),
            }
            if verdict.get("error"):
                health["error"] = verdict.get("error")
            if classified["code"]:
                health["diagnosis_code"] = classified["code"]
        out.append(
            {
                "id": conn["id"],
                "name": conn["name"],
                "provider": conn["provider"],
                "is_active": conn["is_active"],
                "auth_state": auth_state,
                "health": health,
                "models": base_models,
                "variant_count": variant_count,
                "last_tested": conn["last_tested"],
                "created_at": conn["created_at"],
                "dashboard_url": f"{DS9_DASHBOARD_URL}/dashboard/providers/{conn['provider']}",
            }
        )
    return {"success": True, "connections": out, "reason": None}


def get_app_server_health() -> Dict[str, Any]:
    """Is the Codex app-server sidecar alive and signed in?

    The LEAN version of get_app_server_status(): the same two read paths, but
    WITHOUT the model list. A health probe must not depend on /v1/models —
    that is a catalogue read, it is slow, and it is not what "is the sidecar
    alive" means.

    Returns:
      {
        "condition": one of APP_SERVER_CONDITIONS,
        "detail": str,           # human-readable, safe to put in an alert
        "checked_at": str,       # ISO timestamp of the probe
        "connections": [ {id, name, is_active, auth_state, latency_ms,
                          diagnosis_code} ],
      }

    Never raises. "unreachable" is deliberately NOT "healthy": an unknown state
    must never read as a working one. And "unreachable" means DS9 could not be
    reached — a DOWN SIDECAR is a different condition ("down"), because the
    operator's next action is different.
    """
    connections = _read_connections()
    if not connections:
        return {
            "condition": "absent",
            "detail": "DS9 reports no Codex app-server connection.",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "connections": [],
        }

    entries: List[Dict[str, Any]] = []
    for conn in connections:
        verdict = _probe(conn["id"])
        classified = _classify_verdict(verdict)
        entries.append(
            {
                "id": conn["id"],
                "name": conn["name"],
                "is_active": conn["is_active"],
                "auth_state": classified["state"],
                "latency_ms": classified["latency_ms"],
                "diagnosis_code": classified["code"],
                "diagnosis_message": classified["message"],
            }
        )

    # An INACTIVE connection is a deliberate operator choice, not a fault. It
    # must never raise an alarm — paging on something someone turned off is
    # how an alert channel gets muted.
    active = [e for e in entries if e["is_active"]]
    if not active:
        return {
            "condition": "disabled",
            "detail": (
                "The Codex app-server connection is present but DISABLED "
                "(is_active=0). That is a deliberate setting, not a fault."
            ),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "connections": entries,
        }

    worst = "healthy"
    for entry in active:
        state = entry["auth_state"]
        if state == "unknown":
            worst = "unreachable"
            break
        if state != "authenticated":
            worst = state
    if worst == "healthy":
        detail = (
            f"{len(active)} Codex app-server connection(s) reachable and signed in "
            f"({', '.join(str(e['name']) for e in active)})."
        )
    else:
        detail = _CONDITION_DETAIL.get(worst, f"The Codex app-server is {worst}.")
        # DS9's own message names the exact URL and error; keep it — it is the
        # difference between "look at the sidecar" and "look at the network".
        messages = [str(e.get("diagnosis_message")) for e in active if e.get("diagnosis_message")]
        if messages:
            detail = f"{detail} DS9 says: {messages[0]}"
    return {
        "condition": worst,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "connections": entries,
    }
