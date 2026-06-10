"""AI incident filing — platform side (task #3263).

``file_ai_incident()`` is the single entry point for recording an AI incident
(error, near-miss, unexpected behaviour). It:

  1. writes an internal ``governance_audit_log`` event (event_type=
     ``ai_incident_reported``),
  2. files the incident to the C.R.E.E.D. public disclosure log
     (``creed:8086`` ``POST /api/v1/incidents``) — disclosure is gated by the
     ``disclose`` flag, so filing alone never auto-publishes,
  3. Telegram-alerts the owner for ``high``/``critical`` severity.

Every step is best-effort and isolated — a failure in one never blocks the
others or raises to the caller (incident recording must not itself cause an
incident).
"""

import json
import logging
import os
import urllib.request
import uuid

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Hub-local C.R.E.E.D. (same host); mirrors the env used by dept_hq/jobs.py.
_CREED_URL = os.getenv("CREED_API_URL", "http://192.168.1.200:8086")

SEVERITIES = {"low", "medium", "high", "critical"}


def file_ai_incident(
    severity,
    title,
    description="",
    affected_agents=None,
    root_cause="",
    resolution="",
    status="investigating",
    lessons_learned="",
    disclose=False,
):
    """Record an AI incident. Returns {incident_ref, audit_logged, creed_filed}.

    Never raises — incident recording must not cause a new incident.
    """
    severity = (severity or "").strip().lower()
    if severity not in SEVERITIES:
        severity = "medium"
    incident_ref = "INC-" + uuid.uuid4().hex[:8]
    affected = (
        affected_agents
        if isinstance(affected_agents, str)
        else ", ".join(str(a) for a in (affected_agents or []))
    )

    audit_logged = False
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                  (event_type, event_category, action, reason, timestamp)
                VALUES ('ai_incident_reported', 'accountability',
                        'incident_filed', %s, NOW())
                """,
                (f"[{severity}] {title} ({incident_ref})"[:500],),
            )
        audit_logged = True
    except Exception as e:
        logger.error("file_ai_incident: governance_audit_log write failed: %s", e)

    creed_filed = False
    try:
        payload = json.dumps(
            {
                "incident_ref": incident_ref,
                "severity": severity,
                "title": title,
                "description": description,
                "affected_agents": affected,
                "root_cause": root_cause,
                "resolution": resolution,
                "status": status,
                "lessons_learned": lessons_learned,
                "disclosed": bool(disclose),
            }
        ).encode()
        _headers = {"Content-Type": "application/json"}
        # #3958: route the incident to the tenant of the first affected agent
        # (falls back inside creed_emit: default tenant -> legacy key).
        try:
            from services.creed_emit import auth_header_for_agent

            _first_agent = None
            if affected_agents:
                _first_agent = (
                    str(affected_agents).split(",")[0].strip()
                    if isinstance(affected_agents, str)
                    else str(list(affected_agents)[0])
                )
            _headers.update(auth_header_for_agent(agent_name=_first_agent))
        except Exception:
            _creed_key = os.getenv("CREED_INGEST_KEY", "")
            if _creed_key:
                _headers["Authorization"] = f"Bearer {_creed_key}"
        req = urllib.request.Request(
            f"{_CREED_URL}/api/v1/incidents",
            data=payload,
            headers=_headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            creed_filed = r.status in (200, 201)
    except Exception as e:
        logger.error("file_ai_incident: C.R.E.E.D. filing failed: %s", e)

    if severity in ("high", "critical"):
        try:
            from services import telegram_service

            telegram_service.send_security(
                f"AI incident — {severity.upper()}",
                f"{incident_ref}: {title}. {description[:300]}"
                + ("" if creed_filed else " (C.R.E.E.D. filing FAILED — check logs)"),
            )
        except Exception as e:
            logger.warning("file_ai_incident: Telegram alert failed: %s", e)

    return {
        "incident_ref": incident_ref,
        "audit_logged": audit_logged,
        "creed_filed": creed_filed,
    }
