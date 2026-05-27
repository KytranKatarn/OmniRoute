"""
A2A Protocol Support (T1715) — Agent-to-Agent interoperability.

Implements the Google A2A protocol v0.2 spec:
  GET  /.well-known/agent.json         — Agent Card discovery (no auth)
  POST /api/a2a/tasks/send             — Submit task (synchronous dispatch)
  GET  /api/a2a/tasks/<task_id>        — Task status + artifacts
  POST /api/a2a/tasks/<task_id>/cancel — Cancel task
  GET  /api/a2a/docs                   — Implementation overview

Auth: X-A2A-API-Key header — validated against api_keys table.
Required permissions: 'admin' or 'chat' in the permissions JSONB array.

Dispatch: all task execution routes through DHQ department_dispatcher
(skill-based routing, 11-tier GPU-aware escalation, welfare gating).

Spec reference: https://google.github.io/A2A/specification
Implementation phase: 1 (synchronous dispatch; async + SSE = Phase 2)
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ── Blueprints ────────────────────────────────────────────────────────────────

# Blueprint 1 — .well-known (no URL prefix — must be at app root)
a2a_wellknown_bp = Blueprint("a2a_wellknown", __name__)

# Blueprint 2 — task management API
a2a_tasks_bp = Blueprint("a2a_tasks", __name__, url_prefix="/api/a2a")

# ── A2A Agent Card (spec §3.1) ────────────────────────────────────────────────

_AGENT_CARD = {
    "name": "A.R.C.H.I.E.",
    "description": (
        "Autonomous Resource & Cognitive Hyperintelligence Engine — "
        "a multi-agent AI platform with 34 specialist agents across 17 departments. "
        "Capabilities include code review, research, documentation, analytics, "
        "creative generation, security audits, and Canadian civic intelligence analysis."
    ),
    "url": "https://platform.kytranempowerment.com",
    "version": "5.33.0",
    "documentationUrl": "https://platform.kytranempowerment.com/api/a2a/docs",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "authentication": {
        "schemes": ["ApiKey"],
        "credentials": {
            "ApiKey": {
                "in": "header",
                "name": "X-A2A-API-Key",
                "description": ("API key with 'chat' or 'admin' permission. " "Managed in Account Center → API Keys."),
            }
        },
    },
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["text"],
    "skills": [
        {
            "id": "code_review",
            "name": "Code Review",
            "description": "Review code for bugs, security vulnerabilities, and quality issues",
            "tags": ["engineering", "security"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "research",
            "name": "Research",
            "description": "Investigate topics, synthesise findings, produce structured reports",
            "tags": ["research", "knowledge"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "documentation",
            "name": "Documentation",
            "description": "Write technical documentation, API references, and README files",
            "tags": ["knowledge", "writing"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "analyze",
            "name": "Analysis",
            "description": "Analyse data, patterns, and produce structured insights",
            "tags": ["analytics"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "summarize",
            "name": "Summarisation",
            "description": "Summarise long texts, documents, and datasets",
            "tags": ["knowledge"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "security",
            "name": "Security Audit",
            "description": "Security review, compliance checking, vulnerability assessment",
            "tags": ["security", "compliance"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "creative",
            "name": "Creative Writing",
            "description": "Generate creative content, marketing copy, and narrative",
            "tags": ["creative"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "general",
            "name": "General",
            "description": "General-purpose AI assistance routed to the best available agent",
            "tags": ["general"],
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
    ],
}

# Allowed capability strings — prevents capability injection
_VALID_CAPABILITIES = frozenset(
    {
        "code_review",
        "research",
        "documentation",
        "analyze",
        "summarize",
        "security",
        "creative",
        "general",
        "debug",
        "classify",
        "translate",
        "embedding",
    }
)

# A2A state ← bridge_jobs status
_STATUS_MAP = {
    "pending": "submitted",
    "running": "working",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "canceled",
    "pending_approval": "working",
}


# ── Auth ──────────────────────────────────────────────────────────────────────


def _validate_a2a_key(raw_key: str) -> bool:
    """Validate X-A2A-API-Key against api_keys (must have admin or chat permission)."""
    if not raw_key:
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id FROM api_keys
                WHERE key_hash = %s
                  AND is_active = TRUE
                  AND (permissions @> '["admin"]'::jsonb
                       OR permissions @> '["chat"]'::jsonb)
                LIMIT 1
                """,
                (key_hash,),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.warning("A2A key validation error: %s", e)
        return False


def _validate_a2a_admin_key(raw_key: str) -> bool:
    """Validate X-A2A-API-Key — admin permission required.

    Used by tasks/get and tasks/cancel to prevent IDOR (any authenticated key
    reading another key's task results).  Phase 2 will replace this with
    per-key ownership filtering once tasks are persisted to bridge_jobs.
    """
    if not raw_key:
        return False
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id FROM api_keys
                WHERE key_hash = %s
                  AND is_active = TRUE
                  AND permissions @> '["admin"]'::jsonb
                LIMIT 1
                """,
                (key_hash,),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.warning("A2A admin key validation error: %s", e)
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────


def _a2a_task(
    task_id: str,
    state: str,
    message: str | None = None,
    artifacts: list | None = None,
) -> dict:
    """Return a conformant A2A Task object (spec §4.2)."""
    status: dict = {
        "state": state,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if message:
        status["message"] = {"role": "agent", "parts": [{"text": message}]}
    return {
        "id": task_id,
        "status": status,
        "artifacts": artifacts or [],
        "metadata": {},
    }


def _parse_message(body: dict) -> tuple[str, str]:
    """Extract (prompt_text, capability) from an A2A request body."""
    parts = (body.get("message") or {}).get("parts") or []
    text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p).strip()
    metadata = body.get("metadata") or {}
    capability = metadata.get("capability") or metadata.get("skill_id") or "general"
    if capability not in _VALID_CAPABILITIES:
        capability = "general"
    return text, capability


# ── Well-known endpoint ───────────────────────────────────────────────────────


@a2a_wellknown_bp.route("/.well-known/agent.json")
def agent_card():
    """A2A Agent Card — standard discovery endpoint (no auth required, spec §3.1)."""
    resp = jsonify(_AGENT_CARD)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ── Task endpoints ────────────────────────────────────────────────────────────


@a2a_tasks_bp.route("/tasks/send", methods=["POST"])
def tasks_send():
    """
    A2A tasks/send — receive and synchronously dispatch a task (spec §4.1).

    Phase 1 implementation: tasks execute synchronously and return
    state=completed (or failed) in a single HTTP response.  Async dispatch
    with bridge_jobs persistence is deferred to Phase 2.

    Body (A2A Message):
        {
          "id": "<optional client task id>",
          "sessionId": "<optional session>",
          "message": {
            "role": "user",
            "parts": [{"text": "..."}]
          },
          "metadata": {
            "capability": "code_review"   // optional routing hint
          }
        }
    """
    api_key = request.headers.get("X-A2A-API-Key", "")
    if not _validate_a2a_key(api_key):
        return (
            jsonify(
                {
                    "error": {
                        "code": -32001,
                        "message": "Unauthorized — invalid or missing X-A2A-API-Key",
                    }
                }
            ),
            401,
        )

    body = request.get_json(silent=True) or {}
    task_id = body.get("id") or str(uuid.uuid4())
    prompt, capability = _parse_message(body)

    if not prompt:
        return (
            jsonify(
                {
                    "error": {
                        "code": -32602,
                        "message": "No text content found in message.parts",
                    }
                }
            ),
            400,
        )

    # Dispatch through DHQ — welfare-gated, skill-routed, cost-tracked
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability=capability,
            prompt=prompt,
            context={
                "source": "a2a",
                "task_id": task_id,
                "session_id": body.get("sessionId"),
                "protocol": "a2a_v0.2",
            },
        )
    except Exception as exc:
        logger.error("A2A dispatch error task=%s: %s", task_id, exc)
        return (
            jsonify(_a2a_task(task_id, "failed", message=f"Dispatch error: {exc}")),
            500,
        )

    if result.success:
        artifacts = [
            {
                "name": "response",
                "mimeType": "text/plain",
                "parts": [{"text": result.response}],
                "metadata": {
                    "agent": result.agent,
                    "tier": result.tier,
                    "cost_usd": result.cost_usd,
                    "capability": capability,
                },
            }
        ]
        return jsonify(_a2a_task(task_id, "completed", artifacts=artifacts))

    return (
        jsonify(
            _a2a_task(
                task_id,
                "failed",
                message=result.error or "Dispatch returned no response",
            )
        ),
        500,
    )


@a2a_tasks_bp.route("/tasks/<task_id>", methods=["GET"])
def tasks_get(task_id: str):
    """
    A2A tasks/get — retrieve task status (spec §4.3).

    Phase 1: looks up bridge_jobs rows tagged module_source='a2a'
    via metadata JSONB.  Returns 404 for unknown task IDs.
    """
    api_key = request.headers.get("X-A2A-API-Key", "")
    if not _validate_a2a_admin_key(api_key):
        # Admin scope required — prevents IDOR (any chat key reading another key's tasks).
        # Phase 2 will replace this with per-key ownership filtering once tasks are
        # persisted to bridge_jobs with metadata.a2a_owner_key_id.
        return (
            jsonify({"error": {"code": -32001, "message": "Unauthorized — admin scope required for task lookup"}}),
            401,
        )

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT status, description, agent_name, error_message
                FROM bridge_jobs
                WHERE module_source = 'a2a'
                  AND metadata @> %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                # json.dumps ensures task_id cannot inject additional JSON structure.
                (json.dumps({"a2a_task_id": task_id}),),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.warning("A2A tasks/get DB error: %s", exc)
        row = None

    if not row:
        return (
            jsonify({"error": {"code": -32001, "message": f"Task {task_id!r} not found"}}),
            404,
        )

    state = _STATUS_MAP.get(row["status"], "working")
    artifacts = []
    if state == "completed" and row.get("description"):
        artifacts = [
            {
                "name": "response",
                "mimeType": "text/plain",
                "parts": [{"text": row["description"]}],
                "metadata": {"agent": row.get("agent_name")},
            }
        ]

    err_msg = row.get("error_message") if state == "failed" else None
    return jsonify(_a2a_task(task_id, state, message=err_msg, artifacts=artifacts))


@a2a_tasks_bp.route("/tasks/<task_id>/cancel", methods=["POST"])
def tasks_cancel(task_id: str):
    """
    A2A tasks/cancel — cancel a pending task (spec §4.4).

    Phase 1: synchronous dispatch means tasks complete before cancel can
    arrive.  Returns state=canceled immediately; Phase 2 will add real
    cancellation against bridge_jobs.
    """
    api_key = request.headers.get("X-A2A-API-Key", "")
    if not _validate_a2a_admin_key(api_key):
        # Admin scope required — same IDOR risk as tasks_get (Phase 2 will add ownership).
        return (
            jsonify({"error": {"code": -32001, "message": "Unauthorized — admin scope required for task cancel"}}),
            401,
        )

    return jsonify(_a2a_task(task_id, "canceled"))


@a2a_tasks_bp.route("/docs", methods=["GET"])
def a2a_docs():
    """A2A implementation reference — no auth required."""
    return jsonify(
        {
            "protocol": "A2A (Agent-to-Agent)",
            "spec_version": "0.2",
            "spec_url": "https://google.github.io/A2A/specification",
            "platform": "A.R.C.H.I.E. v5.33.0",
            "implementation_phase": 1,
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/.well-known/agent.json",
                    "auth": "none",
                    "description": "Agent Card discovery",
                },
                {
                    "method": "POST",
                    "path": "/api/a2a/tasks/send",
                    "auth": "X-A2A-API-Key",
                    "description": "Submit task (synchronous dispatch)",
                },
                {
                    "method": "GET",
                    "path": "/api/a2a/tasks/<id>",
                    "auth": "X-A2A-API-Key",
                    "description": "Task status + artifacts",
                },
                {
                    "method": "POST",
                    "path": "/api/a2a/tasks/<id>/cancel",
                    "auth": "X-A2A-API-Key",
                    "description": "Cancel task",
                },
            ],
            "authentication": {
                "header": "X-A2A-API-Key",
                "validation": "SHA-256 hash against api_keys table",
                "required_permission": "admin OR chat",
                "management": "Account Center → API Keys",
            },
            "dispatch": (
                "All tasks route through the DHQ department_dispatcher. "
                "Skill-based routing with 11-tier GPU-aware escalation, "
                "K.I.N. welfare gating, and cost tracking."
            ),
            "available_skills": [s["id"] for s in _AGENT_CARD["skills"]],
            "capability_hint": (
                "Set metadata.capability to a skill ID to route to the right agent. "
                "Defaults to 'general' if omitted or unrecognised."
            ),
            "phase_2_roadmap": [
                "Async task dispatch with bridge_jobs persistence",
                "SSE streaming (spec §5)",
                "Push notification webhooks (spec §6)",
                "OAuth 2.0 authentication",
                "Multi-turn task sessions",
                "input-required state for clarification loops",
            ],
        }
    )
