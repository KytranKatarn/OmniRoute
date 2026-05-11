"""
ARCHIE Chat — REST API Endpoints

All chat endpoints: messaging, conversations, agents, stations, API keys.
Registered via register_routes(bp, admin_required) pattern (ADR-045).
"""

import logging
import time

from flask import request, jsonify

from .auth_middleware import (
    chat_auth_required,
    get_chat_user,
    generate_api_key,
    check_rate_limit,
    require_scope,
)
from .chat_service import (
    check_chat_access,
    find_team_channel,
    get_user_team_id,
    create_conversation,
    get_conversations,
    get_conversation_by_uuid,
    save_message,
    get_conversation_messages,
    archive_conversation,
    auto_title_conversation,
    get_conversation_context,
)

log = logging.getLogger(__name__)

# Canonical 10 stations with colors and capabilities
STATIONS = [
    {
        "code": "COMMAND",
        "name": "Command",
        "color": "#00e5ff",
        "capabilities": ["orchestration", "oversight", "strategy"],
    },
    {
        "code": "ANALYTICS",
        "name": "Analytics",
        "color": "#8b5cf6",
        "capabilities": ["data_analysis", "reporting", "insights"],
    },
    {
        "code": "CREATIVE",
        "name": "Creative",
        "color": "#f472b6",
        "capabilities": ["content_creation", "design", "media"],
    },
    {
        "code": "ENGINEERING",
        "name": "Engineering",
        "color": "#fbbf24",
        "capabilities": ["code_generation", "debugging", "architecture"],
    },
    {
        "code": "COMMUNICATIONS",
        "name": "Communications",
        "color": "#22d3ee",
        "capabilities": ["messaging", "translation", "outreach"],
    },
    {
        "code": "RESEARCH",
        "name": "Research",
        "color": "#10b981",
        "capabilities": ["knowledge_retrieval", "summarization", "learning"],
    },
    {
        "code": "SECURITY",
        "name": "Security",
        "color": "#ef4444",
        "capabilities": ["threat_detection", "audit", "compliance"],
    },
    {
        "code": "LOGISTICS",
        "name": "Logistics",
        "color": "#f97316",
        "capabilities": ["scheduling", "resource_management", "planning"],
    },
    {
        "code": "DIPLOMATIC",
        "name": "Diplomatic",
        "color": "#818cf8",
        "capabilities": ["negotiation", "ethics", "governance"],
    },
    {
        "code": "OPERATIONS",
        "name": "Operations",
        "color": "#a3e635",
        "capabilities": ["system_ops", "monitoring", "automation"],
    },
]


# Display name + portrait for known agent service accounts.
# Portraits are canonical_image_path from agent_portraits table.
_AGENT_ACCOUNTS = {
    "probe": {
        "display_name": "P.R.O.B.E.",
        "portrait": "/static/media/images/2026-04-20/0f7137d2-895.png",
    },
    "archie": {
        "display_name": "A.R.C.H.I.E.",
        "portrait": "/static/media/images/2026-04-30/2f24902c-66b.png",
    },
    "claude": {
        "display_name": "Claude",
        "portrait": None,  # Upload Claude logo to profile_picture on claude@ user
    },
    "kytran": {"display_name": "Kytran", "portrait": None},
}


def _error(code, message, status=400):
    """Return a standardised error JSON response."""
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status


def _inject_warden_action(user_msg: str, agent_resp: str) -> str:
    """Post-process W.A.R.D.E.N. response: inject [ACTION] block when model describes an action."""
    import json as _json

    resp_lower = agent_resp.lower()
    user_lower = user_msg.lower()

    # Model already produced a structured action block — leave it alone
    if "[action]" in resp_lower or "⟦action⟧" in resp_lower:
        return agent_resp

    # Auto-generated confirmation messages should not re-trigger injection
    if user_msg.strip().startswith("[Action confirmed:"):
        return agent_resp

    # Only inject when response signals action intent
    action_signal = any(
        kw in resp_lower for kw in ["will", "run", "now", "prune", "cleanup", "proceed", "execute", "action"]
    )
    if not action_signal:
        return agent_resp

    # Match user request to a known action type
    action = None
    if any(kw in user_lower for kw in ["cleanup", "prune", "retention", "old backup"]):
        action = {
            "type": "run_cleanup",
            "label": "Run Retention Cleanup",
            "confirm": "Prune backups older than 90 days to reclaim disk space",
            "route": "POST /tools/backup-manager/cleanup",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["run backup", "start backup", "create backup", "full backup", "new backup"]):
        action = {
            "type": "run_backup",
            "label": "Run Full Backup",
            "confirm": "Start a full system backup now",
            "route": "POST /tools/backup-manager/create",
            "payload": {"backup_type": "full"},
        }
    elif any(kw in user_lower for kw in ["standalone backup", "backup standalone", "backup all standalone"]):
        action = {
            "type": "run_standalones",
            "label": "Backup All Standalones",
            "confirm": "Run backup for all standalone products",
            "route": "POST /tools/backup-manager/api/standalones/backup",
            "payload": {"run_all": True},
        }

    if action:
        return agent_resp + f"\n\n[ACTION]{_json.dumps(action)}[/ACTION]"
    return agent_resp


def _inject_resolve_action(user_msg: str, agent_resp: str) -> str:
    """Post-process R.E.S.O.L.V.E. response: inject [ACTION] block for Account Center actions."""
    import json as _json

    resp_lower = agent_resp.lower()
    user_lower = user_msg.lower()

    if "[action]" in resp_lower or "⟦action⟧" in resp_lower:
        return agent_resp

    if user_msg.strip().startswith("[Action confirmed:"):
        return agent_resp

    action_signal = any(
        kw in resp_lower
        for kw in ["will", "can", "invite", "send", "lock", "unlock", "revoke", "reset", "proceed", "create", "action"]
    )
    if not action_signal:
        return agent_resp

    action = None
    if any(kw in user_lower for kw in ["invite user", "send invite", "add user", "invite someone", "new invite"]):
        action = {
            "type": "invite_user",
            "label": "Send User Invite",
            "confirm": "Open the invite dialog to add a new user to the platform",
            "route": "POST /tools/account-center/api/invites/send",
            "payload": {},
        }
    elif any(
        kw in user_lower for kw in ["lock account", "lock user", "disable user", "suspend user", "disable account"]
    ):
        action = {
            "type": "lock_account",
            "label": "Lock Account",
            "confirm": "Lock this user account — they will not be able to log in",
            "route": "POST /tools/account-center/api/users/lock",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["unlock account", "unlock user", "re-enable", "reenable", "restore access"]):
        action = {
            "type": "unlock_account",
            "label": "Unlock Account",
            "confirm": "Unlock this user account and restore login access",
            "route": "POST /tools/account-center/api/users/unlock",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["revoke api key", "revoke key", "delete api key", "disable key"]):
        action = {
            "type": "revoke_api_key",
            "label": "Revoke API Key",
            "confirm": "Revoke this API key — it will stop working immediately",
            "route": "DELETE /tools/account-center/api/keys/revoke",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["revoke session", "end session", "kick user", "log out user", "force logout"]):
        action = {
            "type": "revoke_session",
            "label": "Revoke Session",
            "confirm": "Force logout this user session immediately",
            "route": "DELETE /tools/account-center/api/sessions/revoke",
            "payload": {},
        }

    if action:
        return agent_resp + f"\n\n[ACTION]{_json.dumps(action)}[/ACTION]"
    return agent_resp


def _inject_vigil_action(user_msg: str, agent_resp: str) -> str:
    """Post-process V.I.G.I.L. response: inject [ACTION] block for Security & Network actions."""
    import json as _json

    resp_lower = agent_resp.lower()
    user_lower = user_msg.lower()

    if "[action]" in resp_lower or "⟦action⟧" in resp_lower:
        return agent_resp

    if user_msg.strip().startswith("[Action confirmed:"):
        return agent_resp

    action_signal = any(
        kw in resp_lower
        for kw in [
            "will",
            "can",
            "run",
            "scan",
            "block",
            "revoke",
            "restart",
            "remediate",
            "proceed",
            "action",
            "execute",
        ]
    )
    if not action_signal:
        return agent_resp

    action = None
    if any(
        kw in user_lower for kw in ["run compliance", "compliance scan", "run scan", "scan now", "check compliance"]
    ):
        action = {
            "type": "run_compliance_scan",
            "label": "Run Compliance Scan",
            "confirm": "Trigger a full compliance scan across all active rule packs",
            "route": "POST /tools/security-network/api/compliance/scan",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["run recon", "port scan", "nmap", "recon scan", "network scan"]):
        action = {
            "type": "run_recon_scan",
            "label": "Run Recon Scan",
            "confirm": "Launch a network recon scan to discover open ports and services",
            "route": "POST /tools/security-network/api/recon/launch",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["block device", "block ip", "ban device", "isolate device"]):
        action = {
            "type": "block_device",
            "label": "Block Device",
            "confirm": "Add an AdGuard block rule to isolate this device from the network",
            "route": "POST /tools/security-network/api/devices/block",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["restart service", "restart proxy", "restart npm", "reload nginx"]):
        action = {
            "type": "restart_service",
            "label": "Restart Service",
            "confirm": "Restart the selected network service",
            "route": "POST /tools/security-network/api/services/restart",
            "payload": {},
        }
    elif any(kw in user_lower for kw in ["refresh devices", "rediscover", "discover devices", "arp scan"]):
        action = {
            "type": "discover_devices",
            "label": "Discover Devices",
            "confirm": "Trigger a fresh ARP + AdGuard device discovery scan",
            "route": "POST /tools/security-network/api/devices/discover",
            "payload": {},
        }

    if action:
        return agent_resp + f"\n\n[ACTION]{_json.dumps(action)}[/ACTION]"
    return agent_resp


def _serialize_datetime(obj):
    """Convert datetime fields in a dict to ISO-8601 strings."""
    if obj is None:
        return None
    out = {}
    for k, v in obj.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def register_routes(bp, admin_required):
    """Register all chat API routes on the given blueprint."""

    # ------------------------------------------------------------------
    # 1. POST /api/v1/chat/message — Send message, get orchestrated response
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/message", methods=["POST"])
    @chat_auth_required
    @require_scope("chat")
    def send_message():
        start = time.time()
        user = get_chat_user()
        user_id = user["id"]

        # Tier check
        access = check_chat_access(user_id)
        if not access["allowed"]:
            return _error("TIER_REQUIRED", access["reason"], 403)

        # Parse body
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        if not message:
            return _error("VALIDATION_ERROR", "Message cannot be empty", 400)

        conversation_id_param = body.get("conversation_id")  # UUID string or None
        agent_target = body.get("agent_target")
        include_thinking = bool(body.get("include_thinking", True))

        # Rate limit for API key users
        if user.get("auth_method") == "api_key":
            if not check_rate_limit(user_id, user.get("rate_limit", 30)):
                return _error("RATE_LIMITED", "Rate limit exceeded. Try again shortly.", 429)

        # Load or create conversation
        team_id = get_user_team_id(user_id)
        conv = None
        if conversation_id_param:
            conv = get_conversation_by_uuid(conversation_id_param, user_id, team_id)
            if not conv:
                return _error("NOT_FOUND", "Conversation not found or access denied", 404)
        else:
            conv = create_conversation(user_id, team_id=team_id, agent_target=agent_target)

        # Resolve sender display info for message identity
        sender_username = user.get("username", "")
        _acct = _AGENT_ACCOUNTS.get(sender_username, {})
        sender_display_name = _acct.get("display_name") or sender_username
        sender_portrait = _acct.get("portrait")
        if not sender_portrait:
            # Fall back to user profile picture
            try:
                from database import get_db_cursor as _gdc

                with _gdc(commit=False) as (_c, _cur):
                    _cur.execute(
                        "SELECT profile_picture, oauth_picture FROM users WHERE id = %s",
                        (user_id,),
                    )
                    _ur = _cur.fetchone()
                    if _ur:
                        sender_portrait = _ur.get("profile_picture") or _ur.get("oauth_picture")
            except Exception:
                pass

        # Save user message — store display_name + portrait in metadata for history rendering
        user_msg = save_message(
            conv["id"],
            "user",
            message,
            extra_metadata={
                "sender_username": sender_username,
                "sender_display_name": sender_display_name,
                "sender_portrait": sender_portrait,
            },
        )

        # Auto-title from first message (only when conversation was just created)
        if not conversation_id_param:
            auto_title_conversation(conv["id"], message)

        # Default to ARCHIE when no agent targeted (she's primary on COMMAND)
        effective_target = agent_target if agent_target and agent_target != "auto" else "ARCHIE"

        # Build conversation context for multi-turn memory (up to 20 msgs / 4000 chars)
        conv_context = get_conversation_context(conv["id"], max_messages=20, max_chars=4000)
        # Strip action blocks from context so the model doesn't echo raw [ACTION] syntax
        import re as _re

        conv_context = _re.sub(r"\[ACTION\][\s\S]*?\[/ACTION\]", "", conv_context)
        conv_context = _re.sub(r"⟦ACTION⟧[\s\S]*?⟦/ACTION⟧", "", conv_context)

        # Build structured history list for orchestration engine (newest excluded — already in prompt)
        recent_messages = get_conversation_messages(conv["id"], include_thinking=False, limit=20)
        conversation_history = []
        for m in recent_messages[:-1]:  # exclude the user message just saved
            if m["role"] in ("user", "assistant") and m.get("content"):
                conversation_history.append({"role": m["role"], "content": m["content"][:500]})

        # Prepend conversation title + context to the message for the AI
        title_prefix = ""
        if conv.get("title") and conversation_id_param:
            title_prefix = f"[This conversation is about: {conv['title']}]\n\n"
        contextual_message = f"{title_prefix}{conv_context}{message}" if (title_prefix or conv_context) else message

        # Inject live briefing so agents always know their module's current state
        if effective_target == "W.A.R.D.E.N.":
            try:
                from tools.archie_chat.warden_briefing import _build_warden_briefing

                contextual_message = _build_warden_briefing() + contextual_message
            except Exception as _be:
                log.warning("W.A.R.D.E.N. briefing failed (non-fatal): %s", _be)
            contextual_message += "\n\n[MANDATORY: Your response MUST be written in English only. Do not use German, Portuguese, French, or any other language. English only.]"
        elif effective_target == "R.E.S.O.L.V.E.":
            _module_key = body.get("module_key") or ""
            try:
                if _module_key == "email_manager":
                    from tools.archie_chat.email_hq_briefing import _build_email_hq_briefing

                    contextual_message = _build_email_hq_briefing() + contextual_message
                else:
                    from tools.archie_chat.account_center_briefing import _build_account_center_briefing

                    contextual_message = _build_account_center_briefing() + contextual_message
            except Exception as _be:
                log.warning("R.E.S.O.L.V.E. briefing failed (non-fatal): %s", _be)
            contextual_message += "\n\n[MANDATORY: Respond in English only. You are R.E.S.O.L.V.E., Customer Success & Support director. Be helpful, clear, and suggest relevant actions when appropriate.]"
        elif effective_target == "V.I.G.I.L.":
            try:
                from tools.archie_chat.security_network_briefing import _build_security_network_briefing

                contextual_message = _build_security_network_briefing() + contextual_message
            except Exception as _be:
                log.warning("V.I.G.I.L. briefing failed (non-fatal): %s", _be)
            contextual_message += "\n\n[MANDATORY: Respond in English only. You are V.I.G.I.L., the Security & Network guardian. Be precise, security-focused, and suggest remediation actions when appropriate.]"

        # Call orchestration engine
        try:
            from tools.department_hq.services.orchestration_engine import OrchestrationEngine

            engine = OrchestrationEngine()
            result = engine.orchestrate(
                message=contextual_message,
                user_id=user_id,
                conversation_id=str(conv.get("conversation_uuid")),
                agent_target=effective_target,
                user_context={
                    "username": user.get("username", ""),
                    "conversation_history": conversation_history,
                    "original_message": message,
                },
            )
        except Exception as exc:
            log.exception("Orchestration failed: %s", exc)
            return _error("ORCHESTRATION_ERROR", "Failed to generate response", 500)

        # Look up agent display_name and station_code
        agent_display_name = None
        agent_station = None
        if result.agent_used:
            try:
                from database import get_db_cursor as _gc

                with _gc() as (conn, cur):
                    cur.execute(
                        """SELECT display_name FROM agents WHERE name = %s LIMIT 1""",
                        (result.agent_used,),
                    )
                    row = cur.fetchone()
                    if row:
                        agent_display_name = row["display_name"]
            except Exception:
                log.warning("Failed to look up agent display info for %s", result.agent_used)

        duration_ms = int((time.time() - start) * 1000)

        # Post-process agent responses: inject action block when model describes an action
        # but doesn't produce structured output (small model limitation)
        assistant_response = result.response
        if effective_target == "W.A.R.D.E.N." and result.success:
            assistant_response = _inject_warden_action(message, assistant_response)
        elif effective_target == "R.E.S.O.L.V.E." and result.success:
            assistant_response = _inject_resolve_action(message, assistant_response)
        elif effective_target == "V.I.G.I.L." and result.success:
            assistant_response = _inject_vigil_action(message, assistant_response)

        # Save assistant message
        governance_dicts = (
            [
                {"event_type": g.event_type, "timestamp": g.timestamp, "details": g.details}
                for g in result.governance_events
            ]
            if result.governance_events
            else None
        )
        thinking_dicts = (
            [
                {"step_type": s.step_type, "label": s.label, "duration_ms": s.duration_ms, "success": s.success}
                for s in result.thinking_steps
            ]
            if result.thinking_steps
            else None
        )

        assistant_msg = save_message(
            conv["id"],
            "assistant",
            assistant_response,
            thinking_steps=thinking_dicts,
            agent_used=result.agent_used,
            model_used=result.model_used,
            station_code=agent_station,
            governance_events=governance_dicts,
            duration_ms=duration_ms,
        )

        # Cross-session memory: ingest conversation for knowledge retrieval
        try:
            from ai_bridge.conversation_ingest import ingest_conversation

            ingest_conversation(
                user_message=message,
                ai_response=result.response,
                user_id=user_id,
                source="archie_chat",
                model=result.model_used or "",
                provider="orchestration",
            )
        except Exception as e:
            log.debug("Conversation ingest skipped: %s", e)

        # Build response
        response_data = {
            "success": True,
            "conversation_id": str(conv["conversation_uuid"]),
            "message_id": assistant_msg["id"],
            "response": assistant_response,
            "agent": {
                "name": result.agent_used,
                "display_name": agent_display_name,
                "station": agent_station,
            },
            "model_used": result.model_used,
            "duration_ms": duration_ms,
            "sender": {
                "username": sender_username,
                "display_name": sender_display_name,
                "portrait": sender_portrait,
            },
        }

        if include_thinking and thinking_dicts:
            response_data["thinking_steps"] = thinking_dicts

        if governance_dicts:
            response_data["governance_events"] = governance_dicts

        # KB augmentation: attach knowledge sources used
        include_knowledge = bool(body.get("include_knowledge", False))
        if include_knowledge:
            try:
                from ai_bridge.knowledge_retrieval import get_relevant_knowledge

                kb_context = get_relevant_knowledge(message, max_results=3)
                response_data["knowledge_used"] = kb_context if isinstance(kb_context, list) else []
            except Exception:
                response_data["knowledge_used"] = []

        # M.U.S.E. portrait action card — detect portrait refinement intent in user message
        _portrait_kw = {"portrait", "refine", "appearance", "looks like", "redesign", "image", "picture", "photo"}
        if any(kw in message.lower() for kw in _portrait_kw):
            try:
                from database import get_db_cursor as _gc

                # Find agent referenced in message or conversation agent_target
                _agent_name = agent_target if agent_target and agent_target not in ("auto", "ARCHIE") else None
                _portrait_agent_id = None
                _portrait_agent_name = None
                if _agent_name:
                    with _gc() as (_c, _cur):
                        _cur.execute(
                            "SELECT id, display_name FROM agents WHERE name ILIKE %s AND worker_type='ai' LIMIT 1",
                            (_agent_name,),
                        )
                        _row = _cur.fetchone()
                        if _row:
                            _portrait_agent_id = _row["id"]
                            _portrait_agent_name = _row["display_name"] or _agent_name

                if _portrait_agent_id:
                    response_data["actions"] = [
                        {
                            "type": "portrait_refinement",
                            "label": f"Refine {_portrait_agent_name}'s portrait with M.U.S.E.",
                            "agent_id": _portrait_agent_id,
                            "agent_name": _portrait_agent_name,
                            "endpoint": f"/api/portraits/{_portrait_agent_id}/agent-refine",
                            "method": "POST",
                            "description": "Queue an agent-initiated portrait revision. M.U.S.E. synthesises a new prompt from the agent's voice and current portrait.",
                            "fields": [
                                {"name": "feedback", "type": "text", "label": "Optional direction", "required": False}
                            ],
                        }
                    ]
            except Exception as _exc:
                log.debug("Portrait action card skipped: %s", _exc)

        return jsonify(response_data), 200

    # ------------------------------------------------------------------
    # 2. GET /api/v1/chat/conversations — List conversations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def list_conversations():
        user = get_chat_user()
        user_id = user["id"]

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        archived = request.args.get("archived", "false").lower() == "true"

        team_id = get_user_team_id(user_id)
        result = get_conversations(user_id, team_id=team_id, page=page, limit=limit, archived=archived)

        return (
            jsonify(
                {
                    "success": True,
                    "conversations": [_serialize_datetime(c) for c in result["conversations"]],
                    "total": result["total"],
                    "page": result["page"],
                    "limit": result["limit"],
                }
            ),
            200,
        )

    # ------------------------------------------------------------------
    # 2b. GET /api/conversations/threads — Thread sidebar (team scoping)
    # ------------------------------------------------------------------
    @bp.route("/api/conversations/threads", methods=["GET"])
    @login_required
    def list_conversation_threads():
        """Return conversations for the thread sidebar with team/personal scope labels.

        Query params:
            scope: all | team | personal (default: all)
            limit: max results (default: 30)
        """
        from flask_login import current_user

        user_id = current_user.id
        scope = request.args.get("scope", "all")
        limit = min(request.args.get("limit", 30, type=int), 100)

        team_id = get_user_team_id(user_id)

        threads = []
        if scope in ("all", "personal"):
            personal = get_conversations(user_id, team_id=None, page=1, limit=limit)
            for c in personal["conversations"]:
                threads.append(
                    {
                        "conversation_id": c.get("conversation_uuid") or str(c.get("id")),
                        "title": c.get("title") or "Untitled",
                        "scope": "personal",
                        "team_id": None,
                        "agent_target": c.get("agent_target"),
                        "updated_at": (
                            c.get("updated_at").isoformat()
                            if hasattr(c.get("updated_at"), "isoformat")
                            else str(c.get("updated_at", ""))
                        ),
                    }
                )

        if scope in ("all", "team") and team_id is not None:
            team = get_conversations(user_id, team_id=team_id, page=1, limit=limit)
            for c in team["conversations"]:
                threads.append(
                    {
                        "conversation_id": c.get("conversation_uuid") or str(c.get("id")),
                        "title": c.get("title") or "Untitled",
                        "scope": "team",
                        "team_id": team_id,
                        "agent_target": c.get("agent_target"),
                        "updated_at": (
                            c.get("updated_at").isoformat()
                            if hasattr(c.get("updated_at"), "isoformat")
                            else str(c.get("updated_at", ""))
                        ),
                    }
                )

        threads.sort(key=lambda x: x["updated_at"], reverse=True)
        return jsonify({"success": True, "threads": threads[:limit], "has_team": team_id is not None})

    # ------------------------------------------------------------------
    # 3. POST /api/v1/chat/conversations — Create new conversation
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations", methods=["POST"])
    @chat_auth_required
    @require_scope("chat")
    def create_new_conversation():
        user = get_chat_user()
        user_id = user["id"]

        access = check_chat_access(user_id)
        if not access["allowed"]:
            return _error("TIER_REQUIRED", access["reason"], 403)

        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip() or None
        agent_target = body.get("agent_target")

        team_id = get_user_team_id(user_id)
        conv = create_conversation(user_id, team_id=team_id, title=title, agent_target=agent_target)

        return (
            jsonify(
                {
                    "success": True,
                    "conversation": _serialize_datetime(conv),
                }
            ),
            201,
        )

    # ------------------------------------------------------------------
    # 4. GET /api/v1/chat/channel — Find or create shared module channel
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/channel", methods=["GET"])
    @chat_auth_required
    @require_scope("chat")
    def get_or_create_channel():
        """Return the shared admin conversation for a module+agent combination.

        All admins who open the same module land in the same thread.
        Creates the channel on first access.
        """
        user = get_chat_user()
        user_id = user["id"]
        module_key = (request.args.get("module") or "").strip()
        agent_target = (request.args.get("agent") or "W.A.R.D.E.N.").strip()

        if not module_key:
            return _error("VALIDATION_ERROR", "module parameter required", 400)

        team_id = get_user_team_id(user_id)
        if team_id is None:
            return _error("FORBIDDEN", "Shared channels require admin access", 403)

        conv = find_team_channel(team_id, agent_target, module_key)
        if not conv:
            title = f"{agent_target} — {module_key.replace('_', ' ').title()} Channel"
            conv = create_conversation(user_id, team_id=team_id, title=title, agent_target=agent_target)

        return (
            jsonify(
                {
                    "success": True,
                    "conversation_uuid": str(conv["conversation_uuid"]),
                    "title": conv.get("title", ""),
                }
            ),
            200,
        )

    # ------------------------------------------------------------------
    # 5. GET /api/v1/chat/conversations/<uuid>/messages — Get history
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/<string:conv_uuid>/messages", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def get_messages(conv_uuid):
        user = get_chat_user()
        user_id = user["id"]
        team_id = get_user_team_id(user_id)

        conv = get_conversation_by_uuid(conv_uuid, user_id, team_id)
        if not conv:
            return _error("NOT_FOUND", "Conversation not found or access denied", 404)

        include_thinking = request.args.get("include_thinking", "true").lower() != "false"
        limit = request.args.get("limit", 50, type=int)
        before_id = request.args.get("before", None, type=int)

        messages = get_conversation_messages(
            conv["id"],
            include_thinking=include_thinking,
            limit=limit,
            before_id=before_id,
        )

        return (
            jsonify(
                {
                    "success": True,
                    "conversation_id": str(conv["conversation_uuid"]),
                    "messages": [_serialize_datetime(m) for m in messages],
                }
            ),
            200,
        )

    # ------------------------------------------------------------------
    # 5. DELETE /api/v1/chat/conversations/<int:id> — Archive conversation
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/<int:conv_id>", methods=["DELETE"])
    @chat_auth_required
    @require_scope("chat")
    def delete_conversation(conv_id):
        user = get_chat_user()
        user_id = user["id"]

        success = archive_conversation(conv_id, user_id)
        if not success:
            return _error("NOT_FOUND", "Conversation not found or already archived", 404)

        return jsonify({"success": True, "message": "Conversation archived"}), 200

    # ------------------------------------------------------------------
    # 6. GET /api/v1/chat/agents — List available agents
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/agents", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def list_agents():
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    SELECT a.id, a.name, a.display_name,
                           a.shift_state, a.department, a.model
                    FROM agents a
                    WHERE a.shift_state IN ('active', 'deployed')
                    ORDER BY a.department, a.display_name
                    """
                )
                rows = cur.fetchall()

            agents = []
            for r in rows:
                agents.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "display_name": r["display_name"],
                        "department": r["department"],
                        "model": r["model"],
                        "shift_state": r["shift_state"],
                    }
                )

            return jsonify({"success": True, "agents": agents}), 200
        except Exception as exc:
            log.exception("Failed to list agents: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to retrieve agents", 500)

    # ------------------------------------------------------------------
    # 7. GET /api/v1/chat/stations — Return 10 stations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/stations", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def list_stations():
        return jsonify({"success": True, "stations": STATIONS}), 200

    # ------------------------------------------------------------------
    # 8. POST /api/v1/chat/keys — Generate API key (admin only)
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys", methods=["POST"])
    @chat_auth_required
    @require_scope("admin")
    def create_api_key():
        user = get_chat_user()
        if not user.get("is_admin"):
            return _error("AUTH_FAILED", "Admin access required", 403)
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return _error("VALIDATION_ERROR", "Key name is required", 400)

        rate_limit = body.get("rate_limit", 30)
        if not isinstance(rate_limit, int) or rate_limit < 1 or rate_limit > 1000:
            rate_limit = 30

        try:
            result = generate_api_key(user["id"], name, rate_limit)
            return (
                jsonify(
                    {
                        "success": True,
                        "key": result["key"],
                        "key_id": result["key_id"],
                        "prefix": result["prefix"],
                        "message": "Store this key securely. It will not be shown again.",
                    }
                ),
                201,
            )
        except Exception as exc:
            log.exception("Failed to create API key: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to create API key", 500)

    # ------------------------------------------------------------------
    # 9. GET /api/v1/chat/keys — List user's API keys
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys", methods=["GET"])
    @chat_auth_required
    @require_scope("admin")
    def list_api_keys():
        user = get_chat_user()
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, key_prefix, name, rate_limit,
                           is_active, created_at, last_used_at
                    FROM chat_api_keys
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user["id"],),
                )
                rows = cur.fetchall()

            keys = [_serialize_datetime(dict(r)) for r in rows]
            return jsonify({"success": True, "keys": keys}), 200
        except Exception as exc:
            log.exception("Failed to list API keys: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to retrieve API keys", 500)

    # ------------------------------------------------------------------
    # 10. DELETE /api/v1/chat/keys/<int:id> — Revoke API key
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys/<int:key_id>", methods=["DELETE"])
    @chat_auth_required
    @require_scope("admin")
    def revoke_api_key(key_id):
        user = get_chat_user()
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    UPDATE chat_api_keys
                    SET is_active = FALSE
                    WHERE id = %s AND user_id = %s AND is_active = TRUE
                    """,
                    (key_id, user["id"]),
                )
                if cur.rowcount == 0:
                    return _error("NOT_FOUND", "API key not found or already revoked", 404)

            return jsonify({"success": True, "message": "API key revoked"}), 200
        except Exception as exc:
            log.exception("Failed to revoke API key: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to revoke API key", 500)

    # ------------------------------------------------------------------
    # 11. GET /api/v1/chat/conversations/search — Search conversations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/search", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def search_convos():
        user = get_chat_user()
        query = request.args.get("q", "").strip()
        if not query:
            return _error("VALIDATION_ERROR", "Query required", 400)
        team_id = get_user_team_id(user["id"])

        from .chat_service import search_conversations

        results = search_conversations(user["id"], query, team_id)
        return jsonify({"success": True, "results": results}), 200

    # ------------------------------------------------------------------
    # 12. GET /api/v1/chat/knowledge/search — Direct KB search
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/knowledge/search", methods=["GET"])
    @chat_auth_required
    @require_scope("read")
    def search_knowledge():
        query = request.args.get("q", "").strip()
        if not query:
            return _error("VALIDATION_ERROR", "Query required", 400)
        limit = min(request.args.get("limit", 10, type=int), 50)
        try:
            from ai_bridge.knowledge_retrieval import get_relevant_knowledge

            results = get_relevant_knowledge(query, max_results=limit)
            return (
                jsonify(
                    {
                        "success": True,
                        "query": query,
                        "results": results if isinstance(results, list) else [],
                    }
                ),
                200,
            )
        except Exception as e:
            log.error("KB search failed: %s", e)
            return _error("ORCHESTRATION_FAILED", str(e)[:200], 500)
