"""
A.R.C.H.I.E. Orchestration Engine

The core brain that sits between user input and agent execution.
Composes existing systems: intent parsing, smart routing, agent delegation,
C.R.E.E.D. governance, and model execution into a single orchestrated pipeline.

Each request flows through:
1. Intent parsing (what does the user want?)
2. C.R.E.E.D. pre-check (any ethical constraints?)
3. Agent welfare check (is the selected agent healthy?)
4. Smart routing (which model tier?)
5. GPU state awareness (avoid model swap crashes)
6. Agent selection (who handles this?)
7. Execution (call the model)
8. Logging (persist thinking steps)
"""

import os
import sys
import json
import time
import uuid
import logging
import requests
from psycopg2.extras import RealDictCursor
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from db import get_db

from services.escalation_log_service import record_floor_fallback

logger = logging.getLogger(__name__)

# Ensure ai_bridge is on path
sys.path.insert(0, os.path.dirname(__file__))

from .ollama_options import build_options


def _node_url_for_orchestration(node_id: str) -> str:
    """Resolve node_id → base URL. Hub uses OLLAMA_URL env; fleet comes
    from remote_nodes via fleet_service.
    """
    if node_id in ("hub", "archie-starbase"):
        return os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL") or "http://archie_ollama:11434"
    try:
        from .fleet_service import get_node_status

        node = get_node_status(node_id)
        if node and node.get("vpn_ip"):
            return f"http://{node['vpn_ip']}:{node.get('port', 11434)}"
    except Exception:
        logger.warning("fleet_service lookup failed for %s, using OLLAMA_URL fallback", node_id)
    return os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL") or "http://archie_ollama:11434"


def _default_conversation_model():
    """Get conversation model from BridgeDispatcher (lazy, with fallback)."""
    try:
        # Relative import — the bare `from department_dispatcher import ...` NEVER
        # resolved (nothing puts services/ on sys.path), so this always fell through
        # to the hardcoded fallback (audit 2026-08-17, proposal #3381). Lazy inside
        # the function, so no circular import with the dispatcher at module load.
        from .department_dispatcher import get_dispatcher

        model = get_dispatcher().get_model_for_capability("conversation")
        return model or "dolphin3-8k:latest"
    except Exception as e:
        logger.debug("Conversation model lookup failed, using fallback: %s", e)
        return "dolphin3-8k:latest"


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))


def _push_event(event_type, agent_id=None, data=None):
    """Push activity event to the SSE queue that powers the Department HQ
    mission control /api/dispatch/stream endpoint.

    Note: the old code imported from platform_v2.tools.bridge.routes
    which NEVER existed — the bridge module was renamed department_hq
    long ago. Every call was failing silently in the except. Fixed to
    point at the real producer at fleet_helpers.push_agent_event.
    """
    try:
        from tools.department_hq.fleet_helpers import push_agent_event

        push_agent_event(event_type, agent_id, data)
    except Exception as e:
        logger.debug("SSE push skipped: %s", e)


class StepType(Enum):
    INTENT_PARSE = "intent_parse"
    ROUTE_DECISION = "route_decision"
    AGENT_SELECT = "agent_select"
    CREED_CHECK = "creed_check"
    WELFARE_CHECK = "welfare_check"
    GPU_CHECK = "gpu_check"
    EXECUTE = "execute"
    FALLBACK = "fallback"
    DECOMPOSE = "decompose"
    DELEGATE = "delegate"
    SYNTHESIZE = "synthesize"
    MEMORY_COMMAND = "memory_command"
    BRIEFING_COMMAND = "briefing_command"
    LANGUAGE_DETECT = "language_detect"
    TRANSLATE_RESPONSE = "translate_response"


@dataclass
class ThinkingStep:
    """A single step in the orchestration pipeline"""

    step_type: str
    label: str
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    success: bool = True
    agent_id: Optional[int] = None
    model_used: Optional[str] = None


@dataclass
class GovernanceEvent:
    """A C.R.E.E.D. governance event logged during orchestration"""

    event_type: str
    action: str
    outcome: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestrationResult:
    """Complete result from an orchestration request"""

    success: bool
    response: str
    thinking_steps: List[ThinkingStep] = field(default_factory=list)
    agent_used: Optional[str] = None
    agent_id: Optional[int] = None
    model_used: Optional[str] = None
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    governance_events: List[GovernanceEvent] = field(default_factory=list)
    total_duration_ms: int = 0
    error: Optional[str] = None

    def to_dict(self):
        return {
            "success": self.success,
            "response": self.response,
            "thinking_steps": [
                {
                    "step_type": s.step_type,
                    "label": s.label,
                    "data": s.data,
                    "duration_ms": s.duration_ms,
                    "success": s.success,
                    "model_used": s.model_used,
                }
                for s in self.thinking_steps
            ],
            "agent_used": self.agent_used,
            "agent_id": self.agent_id,
            "model_used": self.model_used,
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "governance_events": [
                {
                    "event_type": g.event_type,
                    "action": g.action,
                    "outcome": g.outcome,
                    "details": g.details,
                }
                for g in self.governance_events
            ],
            "total_duration_ms": self.total_duration_ms,
        }


class OrchestrationEngine:
    """
    ARCHIE's orchestration brain.

    Routes user requests through intent parsing, C.R.E.E.D. governance,
    smart routing, agent selection, and execution — composing
    existing subsystems rather than rewriting them.
    """

    def __init__(self):
        self._intent_parser = None
        self._smart_router = None

    def _get_intent_parser(self):
        """Lazy-load intent parser"""
        if self._intent_parser is None:
            try:
                # New location: archie_engine_staging (Task 1.5+)
                from archie_engine_staging.intent_parser import IntentParser

                self._intent_parser = IntentParser()
            except ImportError:
                try:
                    # Legacy location: archie_core (pre-migration)
                    from platform_v2.tools.archie_core.intent_parser import (
                        get_intent_parser,
                    )

                    self._intent_parser = get_intent_parser()
                except ImportError:
                    try:
                        from tools.archie_core.intent_parser import get_intent_parser

                        self._intent_parser = get_intent_parser()
                    except ImportError as e:
                        logger.warning(f"Intent parser not available: {e}")
        return self._intent_parser

    def _get_smart_router(self):
        """Lazy-load smart router"""
        if self._smart_router is None:
            try:
                from .smart_router import get_router

                self._smart_router = get_router()
            except ImportError as e:
                logger.warning(f"Smart router not available: {e}")
        return self._smart_router

    def orchestrate(
        self,
        message: str,
        user_id: int,
        conversation_id: Optional[str] = None,
        voice_mode: bool = False,
        user_context: Optional[Dict] = None,
        agent_target: Optional[str] = None,
        project_id: Optional[int] = None,
        images: Optional[List[str]] = None,
    ) -> OrchestrationResult:
        """
        Main orchestration pipeline.

        Takes a user message and routes it through the full pipeline:
        intent → C.R.E.E.D. → welfare → routing → agent → execution → logging.

        Args:
            message: The user's input text
            user_id: ID of the requesting user
            conversation_id: Optional conversation thread ID
            voice_mode: If True, responses are shorter and conversational
            user_context: Optional dict with username, preferences, etc.

        Returns:
            OrchestrationResult with response, thinking steps, and governance log
        """
        start_time = time.time()
        conversation_id = conversation_id or str(uuid.uuid4())
        session_uuid = str(uuid.uuid4())
        steps: List[ThinkingStep] = []
        governance_events: List[GovernanceEvent] = []
        selected_agent = None
        model_used = None

        # Create orchestration session in DB
        db_session_id = self._create_session(session_uuid, user_id, conversation_id)

        # Store images for _step_execute to pick up (avoid changing all call sites)
        self._images = images or []

        try:
            # --- Step 1: Parse intent ---
            intent = self._step_parse_intent(message, steps)

            # --- Step 1b: Language detection ---
            detected_lang = "en"
            user_lang_pref = "en"
            try:
                conn = get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT language, auto_detect FROM user_language_preferences WHERE user_id = %s",
                    (user_id,),
                )
                pref = cur.fetchone()
                if pref:
                    user_lang_pref = pref["language"] or "en"
                cur.close()
                conn.close()

                if pref and pref.get("auto_detect", True) and message:
                    from translation_service import detect_language

                    detected_lang = detect_language(message) or "en"
                else:
                    detected_lang = user_lang_pref

                if detected_lang != "en" or user_lang_pref != "en":
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.LANGUAGE_DETECT.value,
                            label=f"Language: {detected_lang}"
                            + (f" (pref: {user_lang_pref})" if user_lang_pref != detected_lang else ""),
                            data={
                                "detected": detected_lang,
                                "preference": user_lang_pref,
                                "auto_detect": bool(pref and pref.get("auto_detect", True)),
                            },
                            success=True,
                        )
                    )
            except Exception as e:
                logger.warning(f"Language detection failed: {e}")

            # --- Step 2: C.R.E.E.D. pre-check ---
            self._step_creed_check(intent, steps, governance_events)

            # --- Step 3: Agent welfare check ---
            # (deferred until after agent selection)

            # --- Step 4: Smart routing (model/tier selection) ---
            routing = self._step_route_decision(message, intent, steps)

            # --- Step 5: GPU state check ---
            gpu_info = self._step_gpu_check(routing, steps)

            # --- Step 6: Select agent ---
            if agent_target:
                # Department or agent targeting override
                _valid_departments = {
                    "EXECUTIVE OFFICE",
                    "OPERATIONS & INFRASTRUCTURE",
                    "LOGISTICS & SUPPLY CHAIN",
                    "FINANCE & ACCOUNTING",
                    "ENGINEERING & TECHNOLOGY",
                    "SECURITY & COMPLIANCE",
                    "RESEARCH & DEVELOPMENT",
                    "CREATIVE & DESIGN",
                    "MARKETING & COMMUNICATIONS",
                    "DOCUMENTATION & KNOWLEDGE",
                    "CUSTOMER SUCCESS & SUPPORT",
                    "HUMAN RESOURCES & CULTURE",
                    "MEDICAL & WELLNESS",
                    "LEGAL & REGULATORY",
                    "DIPLOMATIC & EXTERNAL RELATIONS",
                    "ANALYTICS & INTELLIGENCE",
                }
                if agent_target.upper() in _valid_departments:
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.AGENT_SELECT.value,
                            label="Agent Target (Department)",
                            data={"department_override": agent_target.upper()},
                        )
                    )
                else:
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.AGENT_SELECT.value,
                            label="Agent Target (Direct)",
                            data={"agent_override": agent_target},
                        )
                    )
            selected_agent = self._step_select_agent(message, intent, steps)

            # --- Step 6b: Agent welfare check (now that we have an agent) ---
            if selected_agent and selected_agent.get("agent_id"):
                welfare_ok = self._step_welfare_check(
                    selected_agent["agent_id"],
                    selected_agent.get("name", "Unknown"),
                    steps,
                    governance_events,
                )
                if not welfare_ok:
                    # Try to select an alternate agent
                    alt_agent = self._select_alternate_agent(message, intent, exclude_id=selected_agent["agent_id"])
                    if alt_agent:
                        selected_agent = alt_agent
                        steps.append(
                            ThinkingStep(
                                step_type=StepType.AGENT_SELECT.value,
                                label="Agent reassigned (welfare)",
                                data={
                                    "new_agent": alt_agent.get("name"),
                                    "reason": "previous agent stressed",
                                },
                                success=True,
                            )
                        )

            # --- Step 7: Execute ---
            model_used = self._resolve_model(routing, gpu_info, intent)
            intent_type = intent.get("type", "conversation")

            _push_event(
                "task_start",
                agent_id=selected_agent.get("agent_id") if selected_agent else None,
                data={
                    "task_type": intent_type,
                    "model": model_used,
                    "message_preview": (message[:80] if message else ""),
                },
            )

            # Memory intents bypass normal LLM execution
            if intent_type in ("memory_store", "memory_forget", "memory_list"):
                steps.append(
                    ThinkingStep(
                        step_type=StepType.MEMORY_COMMAND.value,
                        label="Memory Command",
                        data={"intent": intent_type},
                        duration_ms=0,
                        success=True,
                    )
                )
                response_text = self._handle_memory_command(intent_type, message, user_id, steps)
            elif intent_type == "media_generate":
                try:
                    from tools.media_studio.services.agent_media_service import (
                        orchestration_generate,
                    )

                    agent_name = intent.get("agent_name", "")
                    result = orchestration_generate(agent_name, intent)
                    if "error" in result:
                        response_text = f"Media generation failed: {result['error']}"
                    else:
                        response_text = (
                            f"Media generation queued for {agent_name} " f"(ID: {result.get('id', 'unknown')})"
                        )
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.EXECUTE.value,
                            label=f"Media Generate: {agent_name}",
                            data=result,
                            duration_ms=0,
                        )
                    )
                except Exception as e:
                    logger.error(f"Media generate intent failed: {e}")
                    response_text = f"Media generation error: {e}"
            # Team management intents bypass normal LLM execution
            elif intent_type in (
                "team_management",
                "department_management",
                "status_query",
                "dev_hq_status",
            ):
                response_text = self._execute_team_action(intent_type, message, user_id, intent, steps)
            elif intent.get("requires_multi_agent") and intent.get("participating_departments"):
                # Multi-agent orchestration: decompose → assign → execute → synthesize
                steps.append(
                    ThinkingStep(
                        step_type=StepType.ROUTE_DECISION.value,
                        label=f"Multi-agent mode: {len(intent['participating_departments'])} departments",
                        data={
                            "departments": intent["participating_departments"],
                            "domains": intent.get("domains_detected", []),
                        },
                        duration_ms=0,
                    )
                )

                try:
                    from multi_agent_orchestrator import MultiAgentOrchestrator

                    multi_orch = MultiAgentOrchestrator(self)
                    multi_result = multi_orch.orchestrate_multi_agent(
                        message=message,
                        intent=intent,
                        user_id=user_id,
                        session_id=db_session_id,
                    )
                    steps.extend(multi_result.thinking_steps)

                    if multi_result.response:
                        response_text = multi_result.response
                    else:
                        # Decomposition failed — fall back to single-agent
                        logger.info("Multi-agent decomposition failed, falling back to single-agent")
                        steps.append(
                            ThinkingStep(
                                step_type=StepType.FALLBACK.value,
                                label="Multi-agent fallback → single agent",
                                data={"reason": "decomposition returned no sub-tasks"},
                            )
                        )
                        response_text = self._step_execute(
                            message,
                            user_id,
                            conversation_id,
                            selected_agent,
                            model_used,
                            routing,
                            intent,
                            voice_mode,
                            user_context,
                            steps,
                        )
                except Exception as e:
                    logger.error(f"Multi-agent orchestration failed: {e}", exc_info=True)
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.FALLBACK.value,
                            label="Multi-agent error → single agent",
                            data={"error": str(e)[:200]},
                            success=False,
                        )
                    )
                    response_text = self._step_execute(
                        message,
                        user_id,
                        conversation_id,
                        selected_agent,
                        model_used,
                        routing,
                        intent,
                        voice_mode,
                        user_context,
                        steps,
                    )
            else:
                response_text = self._step_execute(
                    message,
                    user_id,
                    conversation_id,
                    selected_agent,
                    model_used,
                    routing,
                    intent,
                    voice_mode,
                    user_context,
                    steps,
                )

            # --- Step 7b: Translate response if needed ---
            try:
                response_lang = detected_lang if detected_lang != "en" else user_lang_pref
                if response_lang != "en" and response_text:
                    from translation_service import translate_text

                    t_start = time.time()
                    translated = translate_text(response_text, response_lang, "en")
                    t_ms = int((time.time() - t_start) * 1000)
                    if translated and translated != response_text:
                        response_text = translated
                        steps.append(
                            ThinkingStep(
                                step_type=StepType.TRANSLATE_RESPONSE.value,
                                label=f"Response translated to {response_lang}",
                                data={
                                    "target_language": response_lang,
                                    "original_length": len(response_text),
                                },
                                duration_ms=t_ms,
                                success=True,
                            )
                        )
            except Exception as e:
                logger.warning(f"Response translation failed: {e}")

            # --- Step 8: Log steps to DB ---
            total_ms = int((time.time() - start_time) * 1000)
            self._persist_steps(db_session_id, steps)
            self._complete_session(db_session_id, len(steps), total_ms)

            # Log governance event for the orchestration
            self._log_governance_event(
                "orchestration",
                "orchestrate_request",
                agent_id=selected_agent.get("agent_id") if selected_agent else None,
                reason=f"Orchestrated '{intent.get('type', 'unknown')}' task via {model_used}",
                outcome="success",
            )

            _push_event(
                "task_complete",
                agent_id=selected_agent.get("agent_id") if selected_agent else None,
                data={
                    "duration_ms": total_ms,
                    "success": True,
                    "model": model_used,
                    "message_preview": (message[:80] if message else ""),
                },
            )

            # Auto-extract preferences (non-blocking)
            try:
                self._auto_extract_preference(message, response_text, user_id)
            except Exception:
                pass  # Never block chat for extraction

            return OrchestrationResult(
                success=True,
                response=response_text,
                thinking_steps=steps,
                agent_used=selected_agent.get("name") if selected_agent else "ARCHIE",
                agent_id=selected_agent.get("agent_id") if selected_agent else None,
                model_used=model_used,
                conversation_id=conversation_id,
                session_id=session_uuid,
                governance_events=governance_events,
                total_duration_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.error(f"Orchestration failed: {e}", exc_info=True)
            total_ms = int((time.time() - start_time) * 1000)

            # Try to persist what we have
            try:
                self._persist_steps(db_session_id, steps)
                self._fail_session(db_session_id, str(e))
            except Exception:
                pass

            _push_event(
                "task_error",
                data={
                    "error": str(e)[:200],
                    "message_preview": (message[:80] if message else ""),
                },
            )

            return OrchestrationResult(
                success=False,
                response="",
                thinking_steps=steps,
                conversation_id=conversation_id,
                session_id=session_uuid,
                governance_events=governance_events,
                total_duration_ms=total_ms,
                error=str(e),
            )

    # =========================================================================
    # Streaming Pre-flight (Steps 1-6 only, no execution)
    # =========================================================================

    NON_STREAMABLE_INTENTS = frozenset(
        {
            "memory_store",
            "memory_forget",
            "memory_list",
            "media_generate",
            "team_management",
            "department_management",
            "status_query",
            "dev_hq_status",
        }
    )

    def orchestrate_preflight(
        self,
        message: str,
        user_id: int,
        conversation_id: str,
        user_context: Optional[Dict] = None,
        agent_target: Optional[str] = None,
    ) -> Dict:
        """
        Run orchestration steps 1-6 without executing.

        Returns a dict with resolved model, Ollama URL, messages list,
        agent info, and thinking steps — ready for the SSE streaming
        endpoint to handle step 7 (execution) itself.

        Non-streamable intents (memory commands, media gen, team mgmt)
        are flagged so the caller can fall back to full orchestrate().
        """
        start_time = time.time()
        session_uuid = str(uuid.uuid4())
        steps: List[ThinkingStep] = []
        governance_events: List[GovernanceEvent] = []
        selected_agent = None

        db_session_id = self._create_session(session_uuid, user_id, conversation_id)

        try:
            # --- Step 1: Parse intent (fast: keyword only, no LLM) ---
            t0 = time.time()
            intent = {"type": "conversation", "confidence": 0.5, "complexity": {"score": 3}}
            parser = self._get_intent_parser()
            if parser and hasattr(parser, "_quick_classify"):
                try:
                    quick = parser._quick_classify(message)
                    if quick and quick.get("type"):
                        intent = quick
                        intent.setdefault("confidence", 0.7)
                        intent.setdefault("complexity", {"score": 3})
                except Exception:
                    pass
            steps.append(
                ThinkingStep(
                    step_type=StepType.INTENT_PARSE.value,
                    label=f"Intent: {intent.get('type', 'conversation')} (fast)",
                    data={
                        "type": intent.get("type"),
                        "confidence": round(intent.get("confidence", 0.5), 2),
                        "fast_mode": True,
                    },
                    duration_ms=int((time.time() - t0) * 1000),
                )
            )
            intent_type = intent.get("type", "conversation")

            # --- Step 1b: Language detection (DB pref only, no LLM call) ---
            # Skips LLM-based detect_language() to keep preflight fast.
            # The full orchestrate() path handles LLM detection + translation.
            detected_lang = "en"
            try:
                conn = get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cur.execute(
                        "SELECT language FROM user_language_preferences WHERE user_id = %s",
                        (user_id,),
                    )
                    pref = cur.fetchone()
                    if pref and pref.get("language"):
                        detected_lang = pref["language"]
                finally:
                    cur.close()
                    conn.close()
            except Exception:
                pass

            # --- Check if streamable ---
            if intent_type in self.NON_STREAMABLE_INTENTS or intent.get("requires_multi_agent"):
                return {
                    "non_streamable": True,
                    "intent_type": intent_type,
                    "db_session_id": db_session_id,
                    "session_uuid": session_uuid,
                    "steps": steps,
                    "governance_events": governance_events,
                }

            # --- Step 2: C.R.E.E.D. pre-check ---
            creed_ok = self._step_creed_check(intent, steps, governance_events)
            if not creed_ok:
                return {
                    "error": "creed_blocked",
                    "fallback_response": "I'm unable to process that request due to governance constraints.",
                    "steps": steps,
                    "governance_events": governance_events,
                    "db_session_id": db_session_id,
                    "session_uuid": session_uuid,
                }

            # --- Step 4: Smart routing ---
            routing = self._step_route_decision(message, intent, steps)

            # --- Step 5: GPU state check ---
            gpu_info = self._step_gpu_check(routing, steps)

            # --- Step 6: Select agent ---
            if agent_target:
                # Department or agent targeting override
                _valid_departments = {
                    "EXECUTIVE OFFICE",
                    "OPERATIONS & INFRASTRUCTURE",
                    "LOGISTICS & SUPPLY CHAIN",
                    "FINANCE & ACCOUNTING",
                    "ENGINEERING & TECHNOLOGY",
                    "SECURITY & COMPLIANCE",
                    "RESEARCH & DEVELOPMENT",
                    "CREATIVE & DESIGN",
                    "MARKETING & COMMUNICATIONS",
                    "DOCUMENTATION & KNOWLEDGE",
                    "CUSTOMER SUCCESS & SUPPORT",
                    "HUMAN RESOURCES & CULTURE",
                    "MEDICAL & WELLNESS",
                    "LEGAL & REGULATORY",
                    "DIPLOMATIC & EXTERNAL RELATIONS",
                    "ANALYTICS & INTELLIGENCE",
                }
                if agent_target.upper() in _valid_departments:
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.AGENT_SELECT.value,
                            label="Agent Target (Department)",
                            data={"department_override": agent_target.upper()},
                        )
                    )
                else:
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.AGENT_SELECT.value,
                            label="Agent Target (Direct)",
                            data={"agent_override": agent_target},
                        )
                    )
            selected_agent = self._step_select_agent(message, intent, steps)

            # --- Step 6b: Welfare check ---
            if selected_agent and selected_agent.get("agent_id"):
                welfare_ok = self._step_welfare_check(
                    selected_agent["agent_id"],
                    selected_agent.get("name", "Unknown"),
                    steps,
                    governance_events,
                )
                if not welfare_ok:
                    alt_agent = self._select_alternate_agent(message, intent, exclude_id=selected_agent["agent_id"])
                    if alt_agent:
                        selected_agent = alt_agent
                        steps.append(
                            ThinkingStep(
                                step_type=StepType.AGENT_SELECT.value,
                                label="Agent reassigned (welfare)",
                                data={"new_agent": alt_agent.get("name"), "reason": "previous agent stressed"},
                                success=True,
                            )
                        )

            # --- Resolve model (uses Bridge dispatcher roster) ---
            model_used = self._resolve_model(routing, gpu_info, intent)

            # --- Resolve Ollama URL via build_options for explicit GPU placement ---
            _preflight_messages = [{"role": "user", "content": message}]
            _prompt_text = "".join(m.get("content", "") for m in _preflight_messages)
            _preflight_opts = build_options(
                model=model_used,
                target_node=None,
                prompt_tokens_hint=len(_prompt_text) // 4,
                keep_alive="5m",
            )
            node_id = _preflight_opts["target_node_id"]
            ollama_url = _node_url_for_orchestration(node_id) + "/api/chat"
            logger.info(
                "placement: node=%s model=%s placement=%s reason=%s",
                node_id,
                _preflight_opts["model"],
                _preflight_opts["placement"],
                _preflight_opts["reason"],
            )

            # --- Check provider (non-Ollama can't stream easily) ---
            provider = routing.get("provider", "ollama") if routing else "ollama"
            if provider not in ("ollama", None):
                return {
                    "non_streamable": True,
                    "intent_type": intent_type,
                    "provider": provider,
                    "db_session_id": db_session_id,
                    "session_uuid": session_uuid,
                    "steps": steps,
                    "governance_events": governance_events,
                }

            # --- Build messages list ---
            try:
                from tools.archie_core.ai_chat import ArchieAI as ArchieAI_cls
            except ImportError:
                ArchieAI_cls = None  # archie_core migrated — use fallback prompting

            system_prompt = "You are A.R.C.H.I.E., a helpful AI assistant."
            if ArchieAI_cls:
                ai = ArchieAI_cls()
                system_prompt = ai._build_system_prompt(user_context or {})

            history = self._load_conversation_history(user_id, conversation_id, user_context)

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history)
            messages.append({"role": "user", "content": message})

            # --- Push task_start event ---
            _push_event(
                "task_start",
                agent_id=selected_agent.get("agent_id") if selected_agent else None,
                data={
                    "task_type": intent_type,
                    "model": model_used,
                    "message_preview": (message[:80] if message else ""),
                    "streaming": True,
                },
            )

            preflight_ms = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "model": model_used,
                "ollama_url": ollama_url,
                "node_id": node_id,
                "messages": messages,
                "selected_agent": selected_agent,
                "agent_id": selected_agent.get("agent_id") if selected_agent else None,
                "agent_name": selected_agent.get("name") if selected_agent else "ARCHIE",
                "steps": steps,
                "governance_events": governance_events,
                "db_session_id": db_session_id,
                "session_uuid": session_uuid,
                "intent": intent,
                "routing": routing,
                "detected_lang": detected_lang,
                "preflight_ms": preflight_ms,
            }

        except Exception as e:
            logger.error(f"Orchestration preflight failed: {e}", exc_info=True)
            try:
                self._persist_steps(db_session_id, steps)
                self._fail_session(db_session_id, str(e))
            except Exception:
                pass
            return {
                "error": str(e),
                "steps": steps,
                "governance_events": governance_events,
                "db_session_id": db_session_id,
                "session_uuid": session_uuid,
            }

    # =========================================================================
    # Pipeline Steps
    # =========================================================================

    def _step_parse_intent(self, message: str, steps: List[ThinkingStep]) -> Dict:
        """Step 1: Parse the user's intent"""
        t0 = time.time()
        intent = {"type": "conversation", "confidence": 0.5, "complexity": {"score": 3}}

        parser = self._get_intent_parser()
        if parser:
            try:
                intent = parser.parse(message)
            except Exception as e:
                logger.warning(f"Intent parser error: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.INTENT_PARSE.value,
                label=f"Intent: {intent.get('type', 'unknown')}",
                data={
                    "type": intent.get("type"),
                    "confidence": round(intent.get("confidence", 0), 2),
                    "complexity_score": intent.get("complexity", {}).get("score", 3),
                    "requires_multi_agent": intent.get("requires_multi_agent", False),
                },
                duration_ms=duration,
            )
        )

        return intent

    def _step_creed_check(
        self,
        intent: Dict,
        steps: List[ThinkingStep],
        governance_events: List[GovernanceEvent],
    ) -> bool:
        """Step 2: C.R.E.E.D. ethics pre-check"""
        t0 = time.time()
        passed = True
        violations = []

        try:
            # Map intent types to actions that might have constraints
            action_map = {
                "file_operation": "destructive_action",
                "system_status": "self_modify",
            }
            action = action_map.get(intent.get("type"))

            if action:
                try:
                    from tools.creed.admin_routes import check_constraints

                    violations = check_constraints(action)
                    if violations:
                        mandatory = [v for v in violations if v.get("severity") == "mandatory"]
                        if mandatory:
                            passed = False
                except ImportError:
                    logger.debug("C.R.E.E.D. routes not available for constraint check")
        except Exception as e:
            logger.warning(f"C.R.E.E.D. check error: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.CREED_CHECK.value,
                label="C.R.E.E.D.: passed" if passed else "C.R.E.E.D.: blocked",
                data={
                    "passed": passed,
                    "violations": len(violations),
                    "details": ([v.get("constraint_name", "") for v in violations] if violations else []),
                },
                duration_ms=duration,
                success=passed,
            )
        )

        if not passed:
            governance_events.append(
                GovernanceEvent(
                    event_type="constraint_violation",
                    action=intent.get("type", "unknown"),
                    outcome="blocked",
                    details={"violations": [v.get("constraint_name") for v in violations]},
                )
            )

        return passed

    def _step_route_decision(self, message: str, intent: Dict, steps: List[ThinkingStep]) -> Optional[Dict]:
        """Step 4: Smart routing — decide which model tier to use"""
        t0 = time.time()
        routing = None

        router = self._get_smart_router()
        if router:
            try:
                # Use intent parser result if available, fall back to SmartRouter classifier
                intent_type = intent.get("type", "conversation")
                if intent_type == "conversation":
                    task_type = "conversation"
                else:
                    task_type = router.classify_task(message)
                complexity = intent.get("complexity", {}).get("score", 5)
                recommendation = router.suggest_model(task_type, complexity=complexity)
                routing = {
                    "tier": recommendation.tier,
                    "provider": recommendation.provider,
                    "model_name": recommendation.model_name,
                    "reason": recommendation.reason,
                    "task_type": task_type,
                    "should_escalate": recommendation.should_escalate,
                }
            except Exception as e:
                logger.warning(f"Smart router error: {e}")

        if routing is None:
            # Fallback: use local model
            routing = {
                "tier": "local",
                "provider": "ollama",
                "model_name": _default_conversation_model(),
                "reason": "Smart router unavailable, using default local model",
                "task_type": "conversation",
                "should_escalate": False,
            }

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.ROUTE_DECISION.value,
                label=f"Route: {routing['tier']} ({routing['model_name']})",
                data={
                    "tier": routing["tier"],
                    "model": routing["model_name"],
                    "provider": routing["provider"],
                    "task_type": routing["task_type"],
                    "reason": routing["reason"],
                },
                duration_ms=duration,
            )
        )

        return routing

    def _step_gpu_check(self, routing: Optional[Dict], steps: List[ThinkingStep]) -> Dict:
        """Step 5: Check GPU state — what model is loaded?"""
        t0 = time.time()
        gpu_info = {
            "loaded_model": None,
            "can_use_loaded": False,
            "swap_required": False,
        }

        if routing and routing.get("provider") == "ollama":
            try:
                loaded = self._get_loaded_model()
                if loaded:
                    gpu_info["loaded_model"] = loaded
                    requested = routing.get("model_name", "")
                    # Check if the loaded model matches or can handle the task
                    if loaded == requested or loaded.split(":")[0] == requested.split(":")[0]:
                        gpu_info["can_use_loaded"] = True
                    else:
                        gpu_info["swap_required"] = True
                        # Prefer using the loaded model to avoid crash
                        gpu_info["recommendation"] = "use_loaded"
            except Exception as e:
                logger.debug(f"GPU check failed: {e}")

        duration = int((time.time() - t0) * 1000)

        label = "GPU: "
        if gpu_info.get("loaded_model"):
            if gpu_info["can_use_loaded"]:
                label += f"{gpu_info['loaded_model']} (ready)"
            elif gpu_info["swap_required"]:
                label += f"{gpu_info['loaded_model']} (swap needed)"
            else:
                label += "checking"
        else:
            label += "no model loaded"

        steps.append(
            ThinkingStep(
                step_type=StepType.GPU_CHECK.value,
                label=label,
                data=gpu_info,
                duration_ms=duration,
            )
        )

        return gpu_info

    def _step_select_agent(self, message: str, intent: Dict, steps: List[ThinkingStep]) -> Optional[Dict]:
        """Step 6: Select the best agent via department, then floor fallback, then ARCHIE fallback"""
        t0 = time.time()
        agent = None
        source = "default"

        # Check for direct agent override from agent_target — honour it before any routing
        for step in steps:
            if step.data and "agent_override" in step.data:
                override_name = step.data["agent_override"]
                try:
                    _conn = get_db()
                    _cur = _conn.cursor(cursor_factory=RealDictCursor)
                    _cur.execute(
                        """
                        SELECT a.id as agent_id, a.name, a.department,
                               a.worker_type, a.model, a.tier
                        FROM agents a
                        WHERE a.name = %s AND a.status = 'active'
                        LIMIT 1
                        """,
                        (override_name,),
                    )
                    _row = _cur.fetchone()
                    _cur.close()
                    _conn.close()
                    if _row:
                        steps.append(
                            ThinkingStep(
                                step_type=StepType.AGENT_SELECT.value,
                                label="Agent Override Applied",
                                data={"agent": _row["name"], "source": "agent_target"},
                                duration_ms=int((time.time() - t0) * 1000),
                            )
                        )
                        return dict(_row)
                except Exception:
                    pass
                break  # only one override expected

        intent_type = intent.get("type", "conversation")

        # Map intent to department names
        department_map = {
            "code_task": ["Engineering & Technology"],
            "code_generation": ["Engineering & Technology"],
            "code_review": ["Engineering & Technology"],
            "team_task": ["Operations & Infrastructure", "Human Resources & Culture"],
            "team_management": ["Human Resources & Culture", "Operations & Infrastructure", "Executive Office"],
            "department_management": ["Executive Office"],
            "status_query": ["Executive Office", "Operations & Infrastructure"],
            "dev_hq_status": ["Executive Office", "Operations & Infrastructure"],
            "business_task": ["Operations & Infrastructure", "Finance & Accounting"],
            "knowledge_query": ["Documentation & Knowledge", "Research & Development"],
            "data_analysis": ["Analytics & Intelligence"],
            "creative_task": ["Creative & Design"],
            "content_creation": ["Creative & Design"],
            "system_status": ["Operations & Infrastructure", "Security & Compliance"],
            "research": ["Research & Development"],
            "security": ["Security & Compliance"],
            "operations": ["Operations & Infrastructure"],
            "logistics": ["Logistics & Supply Chain"],
            "finance": ["Finance & Accounting"],
            "hr": ["Human Resources & Culture"],
            "legal": ["Legal & Regulatory"],
            "medical": ["Medical & Wellness"],
            "diplomatic": ["Diplomatic & External Relations"],
            "marketing": ["Marketing & Communications"],
            "documentation": ["Documentation & Knowledge"],
            "customer_support": ["Customer Success & Support"],
            "conversation": ["Executive Office"],
            "general": ["Executive Office"],
        }
        preferred_departments = department_map.get(intent_type, ["Executive Office"])

        # Try 1: Find active agent in a matching department
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT a.id as agent_id, a.name, a.department, a.worker_type,
                       a.model, a.tier
                FROM agents a
                WHERE a.department = ANY(%s)
                  AND a.status = 'active'
                ORDER BY a.is_department_ai DESC, a.tier DESC
                LIMIT 1
            """,
                (preferred_departments,),
            )
            row = cur.fetchone()
            if row:
                agent = dict(row)
                source = "department"
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Department agent lookup error: {e}")

        # Try 2: Fall back to agents on the same floor, then other floors
        if not agent:
            try:
                fallback_depts = self._get_floor_fallback_departments(preferred_departments[0])
                if fallback_depts:
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    cur.execute(
                        """
                        SELECT a.id as agent_id, a.name, a.department, a.worker_type,
                               a.model, a.tier
                        FROM agents a
                        WHERE a.department = ANY(%s)
                          AND a.status = 'active'
                        ORDER BY a.is_department_ai DESC, a.tier DESC
                        LIMIT 1
                    """,
                        (fallback_depts,),
                    )
                    row = cur.fetchone()
                    if row:
                        agent = dict(row)
                        source = "floor_fallback"
                        # #6834 — PERSIST it. Until now `source` was a local variable that
                        # died at the end of this method, so dispatch_escalation_log had a
                        # single writer (the cloud path) and the misroute audit reported the
                        # CLOUD number as "floor_fallback_hits" — 1,345 against a threshold
                        # of 20, permanently, while real floor fallbacks were invisible.
                        # Best-effort by contract: record_floor_fallback never raises, so
                        # telemetry can never interrupt agent selection.
                        record_floor_fallback(
                            capability=(intent or {}).get("capability"),
                            from_department=preferred_departments[0],
                            to_department=agent.get("department"),
                            agent_id=agent.get("agent_id"),
                            module_id=(intent or {}).get("module_id"),
                        )
                    cur.close()
                    conn.close()
            except Exception as e:
                logger.warning(f"Floor fallback agent lookup error: {e}")

        # Try 3: Always fall back to ARCHIE (agent_id=2)
        if not agent or not agent.get("agent_id"):
            agent = {
                "agent_id": 2,
                "name": "ARCHIE",
                "department": "Command",
                "worker_type": "internal",
                "model": _default_conversation_model(),
                "tier": 1,
            }

        duration = int((time.time() - t0) * 1000)

        steps.append(
            ThinkingStep(
                step_type=StepType.AGENT_SELECT.value,
                label=f"Agent: {agent.get('name', 'Unknown')} ({agent.get('department', '')}) [{source}]",
                data={
                    "agent_id": agent.get("agent_id"),
                    "name": agent.get("name"),
                    "department": agent.get("department"),
                    "worker_type": agent.get("worker_type"),
                    "tier": agent.get("tier"),
                    "source": source,
                },
                duration_ms=duration,
                agent_id=agent.get("agent_id"),
            )
        )

        return agent

    def _get_floor_fallback_departments(self, target_dept: str) -> List[str]:
        """Get fallback departments ordered by floor proximity."""
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Find the floor containing the target department
            cur.execute(
                "SELECT code, departments FROM floors WHERE %s = ANY(departments)",
                (target_dept,),
            )
            row = cur.fetchone()
            if not row:
                return []
            # Same-floor departments first (excluding target)
            same_floor = [d for d in row["departments"] if d != target_dept]
            # Then departments from other floors ordered by deck number
            cur.execute(
                "SELECT departments FROM floors WHERE code != %s ORDER BY deck_number",
                (row["code"],),
            )
            other = [d for floor_row in cur.fetchall() for d in floor_row["departments"]]
            cur.close()
            return same_floor + other
        except Exception as e:
            logger.error(f"Floor fallback lookup failed: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def _step_welfare_check(
        self,
        agent_id: int,
        agent_name: str,
        steps: List[ThinkingStep],
        governance_events: List[GovernanceEvent],
    ) -> bool:
        """Step 6b: Check agent welfare before delegation"""
        t0 = time.time()
        healthy = True

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT stress_level, energy_level, current_mood
                FROM agent_emotional_state
                WHERE agent_id = %s
                ORDER BY timestamp DESC LIMIT 1
            """,
                (agent_id,),
            )
            state = cur.fetchone()
            cur.close()
            conn.close()

            if state:
                stress = float(state.get("stress_level") or 0)
                energy = float(state.get("energy_level") or 1.0)
                if stress > 0.8:
                    healthy = False
                    governance_events.append(
                        GovernanceEvent(
                            event_type="welfare_intervention",
                            action="skip_stressed_agent",
                            outcome="agent_rested",
                            details={
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "stress_level": stress,
                            },
                        )
                    )
                    _push_event(
                        "welfare_event",
                        agent_id=agent_id,
                        data={
                            "type": "welfare_intervention",
                            "action": "skip_stressed_agent",
                            "agent_name": agent_name,
                            "stress_level": stress,
                        },
                    )
                elif energy < 0.2:
                    healthy = False
                    governance_events.append(
                        GovernanceEvent(
                            event_type="welfare_intervention",
                            action="skip_exhausted_agent",
                            outcome="agent_rested",
                            details={
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "energy_level": energy,
                            },
                        )
                    )
                    _push_event(
                        "welfare_event",
                        agent_id=agent_id,
                        data={
                            "type": "welfare_intervention",
                            "action": "skip_exhausted_agent",
                            "agent_name": agent_name,
                            "energy_level": energy,
                        },
                    )
        except Exception as e:
            logger.debug(f"Welfare check error for agent {agent_id}: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.WELFARE_CHECK.value,
                label=f"Welfare: {'healthy' if healthy else 'stressed — reassigning'}",
                data={
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "healthy": healthy,
                },
                duration_ms=duration,
                success=healthy,
                agent_id=agent_id,
            )
        )

        return healthy

    def _step_execute(
        self,
        message: str,
        user_id: int,
        conversation_id: str,
        agent: Optional[Dict],
        model_name: str,
        routing: Optional[Dict],
        intent: Dict,
        voice_mode: bool,
        user_context: Optional[Dict],
        steps: List[ThinkingStep],
        project_id: Optional[int] = None,
    ) -> str:
        """Step 7: Execute the request with the selected model.

        Primary path: route through Bridge dispatcher to get agent selection,
        SmartRouter classification, knowledge augmentation (RAG), C.R.E.E.D.
        governance logging, and HR tracking. Falls back to direct Ollama if
        dispatcher is unavailable.
        """
        t0 = time.time()
        response_text = ""
        actual_model = model_name
        dispatched_via_bridge = False

        # Primary: try Bridge dispatcher for full pipeline integration.
        # Relative import now that orchestration_engine and bridge_dispatcher
        # both live in tools.department_hq.services (Project #244 Phase 2).
        try:
            from .department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            task_type = (routing or {}).get("task_type", "general")
            capability = intent.get("primary_intent", task_type)

            # Extract project_id from user_context if not explicitly provided
            if project_id is None and user_context and isinstance(user_context, dict):
                project_id = user_context.get("project_id")

            # Pass images if user attached any (vision capability — base64 strings)
            _images = getattr(self, "_images", None) or None

            result = dispatcher.request_work(
                capability=capability,
                prompt=message,
                module_id="orchestration_engine",
                user_id=user_id,
                timeout=120,
                project_id=project_id,
                prefer_agent=agent.get("name") if agent else None,
                # Chat-only model override (e.g. route C.O.D.E.X. chat to a lighter,
                # always-warm model). None for normal callers — the agent's roster
                # model (used for jobs/documentation) is unaffected.
                model_override=(user_context or {}).get("chat_model_override"),
                # Keep chat on the hub (warm, interactive-priority) instead of
                # escalating to a contended fleet node — fleet routing was adding
                # ~260s of queue wait behind WTF 7B traffic on the Starships.
                local_only=bool((user_context or {}).get("chat_model_override")),
                images=_images if _images else None,
            )
            if result.success and result.response:
                response_text = result.response
                actual_model = result.model_used or model_name
                dispatched_via_bridge = True
                logger.info(
                    f"[OrchestrationEngine] Bridge dispatch OK: " f"agent={result.agent_name} model={actual_model}"
                )
        except Exception as bridge_err:
            logger.warning(
                f"[OrchestrationEngine] Bridge dispatch failed, " f"falling back to direct execution: {bridge_err}"
            )

        # Fallback: direct execution if Bridge didn't handle it
        if not dispatched_via_bridge:
            try:
                provider = routing.get("provider", "ollama") if routing else "ollama"
                tier = routing.get("tier", "local") if routing else "local"

                if provider == "ollama" or tier == "local":
                    response_text, actual_model = self._execute_ollama(
                        message,
                        model_name,
                        user_id,
                        conversation_id,
                        voice_mode,
                        user_context,
                    )
                elif provider == "claude":
                    response_text, actual_model = self._execute_claude_proxy(message, model_name, voice_mode)
                else:
                    response_text, actual_model = self._execute_ollama(
                        message,
                        model_name,
                        user_id,
                        conversation_id,
                        voice_mode,
                        user_context,
                    )

            except Exception as e:
                logger.error(f"Execution failed: {e}")
                # Last resort: try local Ollama with default model
                try:
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.FALLBACK.value,
                            label="Fallback: retrying with local model",
                            data={"original_error": str(e)},
                        )
                    )
                    response_text, actual_model = self._execute_ollama(
                        message,
                        _default_conversation_model(),
                        user_id,
                        conversation_id,
                        voice_mode,
                        user_context,
                    )
                except Exception as e2:
                    raise RuntimeError(f"All execution paths failed: {e2}") from e

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.EXECUTE.value,
                label=f"Execute: {actual_model} ({duration}ms)",
                data={
                    "model": actual_model,
                    "response_length": len(response_text),
                    "voice_mode": voice_mode,
                    "dispatched_via_bridge": dispatched_via_bridge,
                },
                duration_ms=duration,
                model_used=actual_model,
            )
        )

        return response_text

    # =========================================================================
    # Team Management Actions (Phase 2)
    # =========================================================================

    TEAM_RESPONSE_TEMPLATES = {
        "agent_created": """I've created a new agent for you!

**{name}** — {title}
- Model: {model}
- Department: {department}
- Capabilities: {capabilities}

{first_name} is now active and ready to receive tasks.""",
        "agent_assigned": """Done! **{agent_name}** has been assigned to **{department_name}** department as {assignment_type}.""",
        "team_status": """Here's the current team status:

**Active Agents**: {active_count}
**Assigned to Departments**: {dept_count}
**Resting**: {resting_count}

{dept_summary}""",
        "agent_deactivated": """**{agent_name}** has been deactivated and moved to the lounge.
Reason: {reason}""",
        "error": """I ran into an issue: {error}

Please try again or use the Team Management module directly.""",
    }

    def _execute_team_action(
        self,
        intent_type: str,
        message: str,
        user_id: int,
        intent: Dict,
        steps: List[ThinkingStep],
    ) -> str:
        """Execute team management actions instead of normal LLM call."""
        t0 = time.time()

        try:
            if intent_type == "team_management":
                response = self._handle_team_management(message, user_id, intent, steps)
            elif intent_type == "department_management":
                response = self._handle_department_management(message, user_id, intent, steps)
            elif intent_type == "status_query":
                response = self._handle_status_query(message, user_id, intent, steps)
            elif intent_type == "dev_hq_status":
                response = self._handle_dev_hq_status(message, user_id, intent, steps)
            else:
                response = "I'm not sure how to handle that team action."

        except Exception as e:
            logger.error(f"Team action failed: {e}", exc_info=True)
            response = self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))

        duration = int((time.time() - t0) * 1000)
        steps.append(
            ThinkingStep(
                step_type=StepType.EXECUTE.value,
                label=f"Team Action: {intent_type} ({duration}ms)",
                data={
                    "action_type": intent_type,
                    "response_length": len(response),
                },
                duration_ms=duration,
            )
        )

        return response

    # =========================================================================
    # Memory Commands (Phase 7 Intelligence Layer)
    # =========================================================================

    def _handle_memory_command(self, intent_type, message, user_id, steps):
        """Handle memory store/forget/list commands."""
        import re as _re

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if intent_type == "memory_store":
                content = _re.sub(
                    r"^(remember\s+(that|this|my)|note\s+that|save\s+(this|that)\s+to\s+memory)\s*",
                    "",
                    message,
                    flags=_re.IGNORECASE,
                ).strip()
                if not content:
                    content = message
                category = "general"
                if any(
                    w in content.lower()
                    for w in [
                        "code",
                        "python",
                        "javascript",
                        "api",
                        "function",
                    ]
                ):
                    category = "technical"
                elif any(w in content.lower() for w in ["prefer", "like", "always", "never", "style"]):
                    category = "preference"
                cur.execute(
                    """
                    INSERT INTO long_term_memory
                    (user_id, memory_type, category, content,
                     importance_score, source_type, source_module)
                    VALUES (%s, 'fact', %s, %s, 0.7, 'manual', 'chat')
                    """,
                    (user_id, category, content),
                )
                conn.commit()
                response = f"Got it! I'll remember that. " f"Stored under '{category}' category."

            elif intent_type == "memory_forget":
                target = _re.sub(
                    r"^(forget\s+(about|that|my)|remove\s+memory" r"|delete\s+memory|stop\s+remembering)\s*",
                    "",
                    message,
                    flags=_re.IGNORECASE,
                ).strip()
                cur.execute(
                    """
                    UPDATE long_term_memory SET is_deleted = TRUE
                    WHERE user_id = %s AND is_deleted = FALSE
                    AND content ILIKE %s
                    """,
                    (user_id, f"%{target}%"),
                )
                affected = cur.rowcount
                conn.commit()
                if affected > 0:
                    response = f"Done. Removed {affected} memory entries " f"matching '{target}'."
                else:
                    response = f"No memories found matching '{target}'."

            elif intent_type == "memory_list":
                cur.execute(
                    """
                    SELECT category, content, importance_score, source_type
                    FROM long_term_memory
                    WHERE user_id = %s AND is_deleted = FALSE
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT 20
                    """,
                    (user_id,),
                )
                memories = cur.fetchall()
                if memories:
                    lines = []
                    current_cat = None
                    for m in memories:
                        cat = m["category"] or "general"
                        if cat != current_cat:
                            lines.append(f"\n**{cat.title()}:**")
                            current_cat = cat
                        src = " (auto)" if m["source_type"] == "auto-extracted" else ""
                        lines.append(f"- {m['content']}{src}")
                    response = "Here's what I remember about you:\n" + "\n".join(lines)
                else:
                    response = "I don't have any memories stored for you yet. " "Tell me something to remember!"

                # Also check preferences
                cur.execute(
                    """
                    SELECT preference_key, preference_value, confidence
                    FROM user_memory_preferences
                    WHERE user_id = %s AND is_active = TRUE
                    ORDER BY confidence DESC
                    """,
                    (user_id,),
                )
                prefs = cur.fetchall()
                if prefs:
                    response += "\n\n**Learned Preferences:**"
                    for p in prefs:
                        conf = int((p["confidence"] or 0) * 100)
                        response += f"\n- {p['preference_key']}: " f"{p['preference_value']} ({conf}% confident)"
            else:
                response = "I'm not sure what to do with that memory command."

            cur.close()
            conn.close()
            return response

        except Exception as e:
            logger.error("Memory command error: %s", e)
            return f"Sorry, I had trouble with that memory command: {e}"

    def _auto_extract_preference(self, message, response, user_id):
        """Lightweight preference extraction via classifier."""
        if not message or len(message) < 20:
            return
        prompt = (
            "Does this user message contain a personal preference, decision, or fact worth remembering? "
            "If yes, extract it as ONE short sentence starting with 'User prefers' or 'User decided'. "
            "If no, respond with exactly: NONE\n\n"
            "User message: " + message[:500]
        )
        try:
            from .department_dispatcher import dispatch

            result_obj = dispatch(
                capability="classify",
                prompt=prompt,
                module_id="orchestration",
                context={"task": "preference_extraction"},
            )
            if result_obj.success:
                result = (result_obj.response or "").strip()
                if result and result.upper() != "NONE" and len(result) < 200:
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO long_term_memory
                        (user_id, memory_type, category, content,
                         importance_score, source_type, source_module)
                        VALUES (%s, 'preference', 'auto-detected', %s,
                                0.5, 'auto-extracted', 'orchestration')
                    """,
                        (user_id, result),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
        except Exception as e:
            logger.debug("Auto-extraction skipped: %s", e)

    def _handle_team_management(self, message: str, user_id: int, intent: Dict, steps: List[ThinkingStep]) -> str:
        """Handle agent creation, update, and deactivation."""
        entities = intent.get("entities", {})
        action = entities.get("action", "query")
        msg_lower = message.lower()

        # Detect action if not already in entities
        if action == "query":
            if any(kw in msg_lower for kw in ["create", "new", "spawn", "hire", "recruit"]):
                action = "create"
            elif any(kw in msg_lower for kw in ["retire", "deactivate", "pause", "remove"]):
                action = "deactivate"
            elif any(kw in msg_lower for kw in ["update", "change", "modify"]):
                action = "update"

        if action == "create":
            return self._create_agent_from_chat(message, user_id, steps)
        elif action == "deactivate":
            return self._deactivate_agent_from_chat(message, user_id, steps)
        else:
            return self._describe_team(steps)

    def _create_agent_from_chat(self, message: str, user_id: int, steps: List[ThinkingStep]) -> str:
        """Create a new agent based on natural language request."""
        from param_extractor import extract_params
        from ethics_monitor import get_monitor

        # Step: Check C.R.E.E.D. governance
        monitor = get_monitor()
        archie_id = 2  # ARCHIE is the parent agent
        permission = monitor.check_agent_creation_allowed(archie_id)

        steps.append(
            ThinkingStep(
                step_type=StepType.CREED_CHECK.value,
                label=f"C.R.E.E.D.: Sub-agent creation {'allowed' if permission['allowed'] else 'blocked'}",
                data=permission,
                success=permission["allowed"],
            )
        )

        if not permission["allowed"]:
            return f"I can't create a new agent right now: {permission['reason']}"

        # Step: Extract parameters from natural language
        t0 = time.time()
        params = extract_params(message, "create_agent")
        extraction_ms = int((time.time() - t0) * 1000)

        steps.append(
            ThinkingStep(
                step_type="param_extraction",
                label=f"Extract params ({extraction_ms}ms)",
                data={"params": params},
                duration_ms=extraction_ms,
                success="error" not in params,
            )
        )

        if "error" in params:
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=params["error"])

        # Build agent creation payload
        model = params.get("model", _default_conversation_model())
        first_name = params.get("first_name", "New")
        last_name = params.get("last_name", "Agent")
        department = params.get("department", "AI Operations")
        title = params.get("title", f"{model} Specialist")
        system_prompt = params.get("system_prompt", f"You are {first_name}, an AI agent.")
        bio = params.get("bio", f"AI agent powered by {model}.")
        capabilities = params.get("capabilities", [])
        if isinstance(capabilities, list):
            capabilities_json = json.dumps(capabilities)
            capabilities_str = ", ".join(capabilities) if capabilities else "general"
        else:
            json.dumps([capabilities])
            capabilities_str = str(capabilities)

        name = f"{first_name} {last_name}".strip()

        # Create the agent in DB
        conn = get_db()
        try:
            # Single-writer path: create via agent_service for the core
            # fields then update_agent for lineage/audit extras not in the
            # create_agent signature (parent_agent_id, created_by_agent_id,
            # created_by_user_id, agent_generation). Project #241 Track C.3.
            from services import agent_service

            caps_for_service = capabilities if isinstance(capabilities, (dict, list)) else {}
            new_agent_id = agent_service.create_agent(
                name=name,
                display_name=title or name,
                department=department,
                model=model,
                system_prompt=system_prompt or "",
                temperature=0.7,
                max_tokens=4096,
                capabilities=caps_for_service,
                worker_type="ai",
            )
            agent_service.update_agent(
                new_agent_id,
                first_name=first_name,
                last_name=last_name,
                title=title,
                bio=bio,
                default_model_tier="local",
                parent_agent_id=archie_id,
                created_by_agent_id=archie_id,
                created_by_user_id=user_id,
                agent_generation=1,
            )
            new_agent = {
                "id": new_agent_id,
                "first_name": first_name,
                "last_name": last_name,
                "model": model,
                "department": department,
                "title": title,
            }

            # Log creation event via C.R.E.E.D. (uses the local conn for
            # its own audit queries; agent_service manages its own cursor).
            monitor.log_agent_creation_event(
                parent_agent_id=archie_id,
                child_agent_id=new_agent["id"],
                user_id=user_id,
                reason=f"Created via chat: {message[:200]}",
                source="chat",
                conn=conn,
            )

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Created: {name} (#{new_agent['id']})",
                    data={
                        "agent_id": new_agent["id"],
                        "name": name,
                        "model": model,
                        "department": department,
                    },
                    success=True,
                )
            )

            return self.TEAM_RESPONSE_TEMPLATES["agent_created"].format(
                name=name,
                first_name=first_name,
                title=title,
                model=model,
                department=department,
                capabilities=capabilities_str,
            )

        except Exception as e:
            conn.rollback()
            logger.error(f"Agent creation failed: {e}")
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def _deactivate_agent_from_chat(self, message: str, user_id: int, steps: List[ThinkingStep]) -> str:
        """Deactivate an agent based on natural language request."""
        from param_extractor import extract_params, resolve_agent_by_name

        params = extract_params(message, "agent_action")
        agent_name = params.get("agent_name", "")

        if not agent_name:
            return "I need to know which agent to deactivate. Could you specify the agent name?"

        conn = get_db()
        try:
            agent = resolve_agent_by_name(agent_name, conn)
            if not agent:
                return f"I couldn't find an agent matching '{agent_name}'. Check the Team Management roster."

            # Don't deactivate ARCHIE or system agents
            if agent["id"] in (1, 2):
                return f"I can't deactivate {agent['name']} — they're a core system agent."

            # Single-writer path (Project #241 Track C.3).
            from services import agent_service

            agent_service.delete_agent(agent["id"])

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Deactivated: {agent['name']} (#{agent['id']})",
                    data={"agent_id": agent["id"], "name": agent["name"]},
                    success=True,
                )
            )

            reason = params.get("reason", "Requested via chat")
            return self.TEAM_RESPONSE_TEMPLATES["agent_deactivated"].format(
                agent_name=agent["name"],
                reason=reason,
            )
        except Exception as e:
            conn.rollback()
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def _handle_department_management(self, message: str, user_id: int, intent: Dict, steps: List[ThinkingStep]) -> str:
        """Handle department assignment/unassignment."""
        from param_extractor import (
            extract_params,
            resolve_agent_by_name,
        )

        params = extract_params(message, "assign_department")
        agent_name = params.get("agent_name", "")
        department = params.get("department", "") or params.get("station_code", "")
        assignment_type = params.get("assignment_type", "primary")

        if not agent_name or not department:
            return "I need both an agent name and a department. For example: 'Assign Nova to Engineering & Technology'"

        conn = get_db()
        try:
            agent = resolve_agent_by_name(agent_name, conn)
            if not agent:
                return f"I couldn't find an agent matching '{agent_name}'."

            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Validate department exists
            cur.execute(
                "SELECT DISTINCT department FROM agents WHERE department ILIKE %s",
                (f"%{department}%",),
            )
            dept_row = cur.fetchone()
            if not dept_row:
                cur.execute("SELECT DISTINCT department FROM agents ORDER BY department")
                all_depts = [r["department"] for r in cur.fetchall()]
                return f"I couldn't find a department matching '{department}'. Available: {', '.join(all_depts)}"
            resolved_dept = dept_row["department"]

            # Check if already in that department
            if agent.get("department") == resolved_dept:
                return f"**{agent['name']}** is already in the **{resolved_dept}** department."

            # Single-writer path: update_agent auto-derives floor from
            # DEPARTMENT_FLOOR_MAP (Project #241 Track C.3).
            from services import agent_service

            try:
                agent_service.update_agent(agent["id"], department=resolved_dept)
            except ValueError as ve:
                cur.close()
                return f"Couldn't reassign: {ve}"

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Assigned: {agent['name']} → {resolved_dept}",
                    data={
                        "agent_id": agent["id"],
                        "department": resolved_dept,
                        "assignment_type": assignment_type,
                    },
                    success=True,
                )
            )

            return self.TEAM_RESPONSE_TEMPLATES["agent_assigned"].format(
                agent_name=agent["name"],
                department_name=resolved_dept,
                assignment_type=assignment_type,
            )
        except Exception as e:
            conn.rollback()
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def _handle_status_query(self, message: str, user_id: int, intent: Dict, steps: List[ThinkingStep]) -> str:
        """Handle team/department status queries."""
        entities = intent.get("entities", {})
        entities.get("subtype", "roster")

        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Active agents count
            cur.execute("SELECT COUNT(*) as count FROM agents WHERE status = 'active'")
            active_count = cur.fetchone()["count"]

            # Agents with a department assigned
            cur.execute(
                """
                SELECT COUNT(*) as count FROM agents
                WHERE status = 'active' AND department IS NOT NULL
            """
            )
            dept_count = cur.fetchone()["count"]

            # Resting agents
            cur.execute(
                """
                SELECT COUNT(*) as count FROM agent_rest_cycles
                WHERE ended_at IS NULL
            """
            )
            resting_count = cur.fetchone()["count"]

            # Department summary
            cur.execute(
                """
                SELECT department, COUNT(*) as agent_count
                FROM agents
                WHERE status = 'active' AND department IS NOT NULL
                GROUP BY department
                ORDER BY department
            """
            )
            departments = cur.fetchall()

            dept_lines = []
            for d in departments:
                count = d["agent_count"] or 0
                indicator = "●" if count > 0 else "○"
                dept_lines.append(f"  {indicator} **{d['department']}**: {count} agents")

            dept_summary = "\n".join(dept_lines) if dept_lines else "No departments configured."

            cur.close()

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Status: {active_count} active, {dept_count} in departments",
                    data={
                        "active": active_count,
                        "dept_count": dept_count,
                        "resting": resting_count,
                    },
                    success=True,
                )
            )

            return self.TEAM_RESPONSE_TEMPLATES["team_status"].format(
                active_count=active_count,
                dept_count=dept_count,
                resting_count=resting_count,
                dept_summary=dept_summary,
            )
        except Exception as e:
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def _handle_dev_hq_status(self, message: str, user_id: int, intent: Dict, steps: List[ThinkingStep]) -> str:
        """Handle project status, roadmap, and task queries from Dev HQ data."""
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get active projects ordered by priority
            cur.execute(
                """
                SELECT id, name, status, priority, description
                FROM unified_projects
                WHERE status = 'active'
                ORDER BY priority DESC, created_at DESC
                LIMIT 10
            """
            )
            projects = cur.fetchall()

            # For each project, get pending and completed task counts
            project_lines = []
            total_pending = 0
            total_completed = 0
            for proj in projects:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending') as pending,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed,
                        COUNT(*) as total
                    FROM unified_tasks
                    WHERE project_id = %s
                """,
                    (proj["id"],),
                )
                counts = cur.fetchone()
                pending = counts["pending"] or 0
                completed = counts["completed"] or 0
                total = counts["total"] or 0
                total_pending += pending
                total_completed += completed

                progress = int(completed / total * 100) if total > 0 else 0
                p = proj.get("priority", 5)
                priority_label = "Critical" if p >= 9 else "High" if p >= 7 else "Medium" if p >= 4 else "Low"

                project_lines.append(
                    f"  - **{proj['name']}** ({priority_label} priority)\n"
                    f"    Progress: {progress}% | Tasks: {completed}/{total} done, {pending} pending"
                )

            # Get recent decisions
            cur.execute(
                """
                SELECT title, status, created_at
                FROM project_decisions
                ORDER BY created_at DESC
                LIMIT 5
            """
            )
            decisions = cur.fetchall()

            decision_lines = []
            for d in decisions:
                created = d["created_at"].strftime("%b %d") if d.get("created_at") else "?"
                dstatus = d.get("status", "proposed")
                decision_lines.append(f"  - [{created}] **{d['title']}** ({dstatus})")

            cur.close()

            # Build response
            project_count = len(projects)
            projects_section = "\n".join(project_lines) if project_lines else "  No active projects."
            decisions_section = "\n".join(decision_lines) if decision_lines else "  No recent decisions."

            response = f"""Here's the current Dev HQ status:

**Active Projects**: {project_count}
**Tasks**: {total_completed} completed, {total_pending} pending

{projects_section}

**Recent Decisions**:
{decisions_section}

You can check the full details at Dev HQ: /dev-hq"""

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Dev HQ: {project_count} projects, {total_pending} pending tasks",
                    data={
                        "active_projects": project_count,
                        "total_pending": total_pending,
                        "total_completed": total_completed,
                        "recent_decisions": len(decisions),
                    },
                    success=True,
                )
            )

            return response

        except Exception as e:
            logger.error(f"Dev HQ status query failed: {e}", exc_info=True)
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def _describe_team(self, steps: List[ThinkingStep]) -> str:
        """Show a brief description of team capabilities."""
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT department, COUNT(*) as count
                FROM agents WHERE status = 'active'
                GROUP BY department ORDER BY count DESC LIMIT 10
            """
            )
            depts = cur.fetchall()
            cur.close()

            lines = [f"  - **{d['department']}**: {d['count']} agents" for d in depts]
            dept_summary = "\n".join(lines) if lines else "No departments configured."

            total = sum(d["count"] for d in depts)

            steps.append(
                ThinkingStep(
                    step_type="team_action",
                    label=f"Team overview: {total} agents",
                    data={"departments": [d["department"] for d in depts]},
                    success=True,
                )
            )

            return f"""Here's an overview of the team:

**Total Active Agents**: {total}

**By Department**:
{dept_summary}

You can ask me to:
- Create a new agent ("Create a Python code reviewer")
- Assign agents to departments ("Put Nova in Engineering & Technology")
- Check department status ("Who's on duty?")
- Deactivate agents ("Retire the test agent")"""
        except Exception as e:
            return self.TEAM_RESPONSE_TEMPLATES["error"].format(error=str(e))
        finally:
            conn.close()

    def orchestrate_joint(
        self,
        topic: str,
        user_id: int,
        max_turns: int = 10,
    ) -> Dict:
        """
        Orchestrate a joint ARCHIE + Claude collaboration that produces work products.

        This is a higher-level orchestration that:
        1. Creates a collaboration session
        2. Runs the joint collaboration (plan → delegate → execute → synthesize)
        3. Logs governance events for the entire session
        4. Returns session info + work products

        Args:
            topic: What to collaborate on
            user_id: ID of the requesting user
            max_turns: Maximum collaboration turns

        Returns:
            Dict with session_id, status, work_products[], thinking_steps[]
        """
        start_time = time.time()
        steps: List[ThinkingStep] = []
        governance_events: List[GovernanceEvent] = []

        # Step 1: C.R.E.E.D. check for joint work
        intent = {"type": "collaboration", "complexity": {"score": 7}}
        self._step_creed_check(intent, steps, governance_events)

        # Step 2: Log that we're starting a joint collaboration
        self._log_governance_event(
            "orchestration",
            "start_joint_collaboration",
            reason=f"Joint collaboration on: {topic[:100]}",
            outcome="initiated",
        )

        steps.append(
            ThinkingStep(
                step_type="joint_init",
                label=f"Joint collaboration: {topic[:60]}",
                data={"topic": topic, "max_turns": max_turns},
            )
        )

        try:
            # Step 3: Create and run joint session via collaboration engine
            import asyncio

            sys.path.insert(
                0,
                os.path.join(
                    os.path.dirname(__file__),
                    "..",
                    "platform_v2",
                    "tools",
                    "consciousness",
                ),
            )
            from collaboration_engine import get_collaboration_engine

            engine = get_collaboration_engine()
            session = engine.start_session(topic, max_turns=max_turns, user_id=user_id)

            steps.append(
                ThinkingStep(
                    step_type="joint_session",
                    label=f"Session created: {session.id[:8]}...",
                    data={"session_id": session.id},
                )
            )

            # Run the joint collaboration asynchronously
            loop = asyncio.new_event_loop()
            try:
                completed_session = loop.run_until_complete(engine.run_joint_collaboration(session.id))
            finally:
                loop.close()

            # Gather work products
            work_products = engine.get_work_products(session.id)

            total_ms = int((time.time() - start_time) * 1000)
            steps.append(
                ThinkingStep(
                    step_type=StepType.EXECUTE.value,
                    label=f"Joint work complete ({len(work_products)} products, {total_ms}ms)",
                    data={
                        "products_count": len(work_products),
                        "session_status": completed_session.status.value,
                        "turns_used": completed_session.current_turn,
                    },
                    duration_ms=total_ms,
                )
            )

            self._log_governance_event(
                "orchestration",
                "complete_joint_collaboration",
                reason=f"Joint collaboration completed: {len(work_products)} work products",
                outcome="success",
            )

            return {
                "success": True,
                "session_id": session.id,
                "status": completed_session.status.value,
                "topic": topic,
                "turns_used": completed_session.current_turn,
                "work_products": work_products,
                "thinking_steps": [
                    {
                        "step_type": s.step_type,
                        "label": s.label,
                        "data": s.data,
                        "duration_ms": s.duration_ms,
                        "success": s.success,
                    }
                    for s in steps
                ],
                "governance_events": [
                    {
                        "event_type": g.event_type,
                        "action": g.action,
                        "outcome": g.outcome,
                    }
                    for g in governance_events
                ],
                "total_duration_ms": int((time.time() - start_time) * 1000),
            }

        except Exception as e:
            logger.error(f"Joint orchestration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "thinking_steps": [{"step_type": s.step_type, "label": s.label, "data": s.data} for s in steps],
                "total_duration_ms": int((time.time() - start_time) * 1000),
            }

    # =========================================================================
    # Execution Backends
    # =========================================================================

    def _execute_ollama(
        self,
        message: str,
        model_name: str,
        user_id: int,
        conversation_id: str,
        voice_mode: bool,
        user_context: Optional[Dict],
    ) -> tuple:
        """Execute via local Ollama (dolphin3 or whatever is loaded)"""
        try:
            # Use ArchieAI for personality-enriched responses
            try:
                from tools.archie_core.ai_chat import ArchieAI
            except ImportError:
                ArchieAI = None  # archie_core migrated — use fallback prompting

            if ArchieAI is None:
                raise ImportError("Could not find ai_chat module")

            ai = ArchieAI()
            context = user_context or {}
            if voice_mode:
                context["voice_mode"] = True

            # Load conversation history
            history = self._load_conversation_history(user_id, conversation_id, user_context)

            result = ai.chat(message, context, history)
            if result.get("success"):
                return result["response"], result.get("model", model_name)
            else:
                raise RuntimeError(result.get("error", "ArchieAI chat failed"))
        except ImportError:
            # Fall back to direct Ollama call
            from archie_bridge import call_ollama

            system_prompt = "You are A.R.C.H.I.E., a helpful AI assistant."
            if voice_mode:
                system_prompt += " Keep responses concise and conversational. No markdown."

            result = call_ollama(message, model=model_name, system_prompt=system_prompt)
            if result.get("success"):
                return result["response"], result.get("model", model_name)
            else:
                raise RuntimeError(result.get("error", "Ollama call failed"))

    def _execute_claude_proxy(self, message: str, model_name: str, voice_mode: bool) -> tuple:
        """Execute via Claude CLI proxy (port 7682, Max subscription)"""
        proxy_url = os.getenv("CLAUDE_PROXY_URL", "http://host.docker.internal:7682")

        system_prompt = None
        if voice_mode:
            system_prompt = "Keep responses concise and conversational. No markdown formatting."

        payload = {
            "message": message,
            "system_prompt": system_prompt,
        }

        # NOTE: proxy_url is the Claude CLI proxy (CLAUDE_PROXY_URL, port 7682),
        # not a direct Ollama endpoint. build_options() does not apply here —
        # this uses a different payload shape (message/system_prompt, not
        # messages/options) and routes to Claude via the Max subscription proxy.
        # The proxy runs the Claude CLI with permissions skipped on the host, so every
        # POST carries the CLAUDE_PROXY_TOKEN shared secret (scripts/claude_proxy.py).
        # Read at call time so a restart is all a rotated secret needs.
        headers = {"Content-Type": "application/json"}
        proxy_token = os.getenv("CLAUDE_PROXY_TOKEN", "").strip()
        if proxy_token:
            headers["X-Claude-Proxy-Token"] = proxy_token

        resp = requests.post(
            f"{proxy_url}/api/chat",
            json=payload,
            headers=headers,
            timeout=130,
        )

        if resp.status_code == 200:
            data = resp.json()
            return data.get("response", ""), f"claude-proxy ({model_name})"
        else:
            raise RuntimeError(f"Claude proxy returned {resp.status_code}: {resp.text[:200]}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_loaded_model(self) -> Optional[str]:
        """Check which Ollama model is currently loaded in GPU memory (local instance)"""
        try:
            local_host = os.getenv("OLLAMA_LOCAL_HOST", "host.docker.internal")
            local_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
            resp = requests.get(f"http://{local_host}:{local_port}/api/ps", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    return models[0].get("name")
        except Exception as e:
            logger.debug(f"Could not check loaded model: {e}")
        return None

    def _resolve_model(self, routing: Optional[Dict], gpu_info: Dict, intent: Optional[Dict] = None) -> str:
        """Resolve final model name, preferring loaded model to avoid swaps"""
        conv_model = _default_conversation_model()
        if routing is None:
            return conv_model

        requested = routing.get("model_name", conv_model)

        # If provider is not ollama, use the requested model as-is
        if routing.get("provider") != "ollama":
            return requested

        # Conversation MUST use the designated conversation model — it follows
        # personality system prompts faithfully.
        intent_type = intent.get("type", "") if intent else ""
        if intent_type in (
            "conversation",
            "team_management",
            "department_management",
            "status_query",
            "dev_hq_status",
        ):
            return conv_model

        # Models that cannot be used for chat/generation (embedding-only)
        non_chat_models = {"arctic-embed-cpu"}

        loaded = gpu_info.get("loaded_model")

        # Never substitute an embedding model for a chat request
        if loaded and loaded in non_chat_models:
            return requested

        # If GPU check says we can use the loaded model, use it
        if gpu_info.get("can_use_loaded") and loaded:
            return loaded

        # If a swap would be required and the loaded model can handle it, prefer loaded
        if gpu_info.get("swap_required") and loaded:
            return loaded

        return requested

    def _select_alternate_agent(self, message: str, intent: Dict, exclude_id: int) -> Optional[Dict]:
        """Select an alternative agent when the primary is stressed"""
        try:
            from agent_delegation import select_best_agent_for_task

            agent = select_best_agent_for_task(message)
            if agent and agent.get("agent_id") != exclude_id:
                return agent
        except Exception:
            pass
        return None

    def _load_conversation_history(
        self, user_id: int, conversation_id: str, user_context: Optional[Dict] = None
    ) -> list:
        """Load recent conversation history for context.

        Checks user_context['conversation_history'] first (from chat module),
        then falls back to ai_conversations table (legacy).
        """
        # Prefer chat module history (already formatted as role/content dicts)
        if user_context and user_context.get("conversation_history"):
            return user_context["conversation_history"]

        # Fallback: legacy ai_conversations table
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT message, response FROM ai_conversations
                WHERE user_id = %s AND conversation_id = %s
                ORDER BY created_at DESC LIMIT 10
            """,
                (user_id, conversation_id),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            history = []
            for row in reversed(rows):
                history.append({"role": "user", "content": row["message"]})
                if row.get("response"):
                    history.append({"role": "assistant", "content": row["response"]})
            return history
        except Exception:
            return []

    # =========================================================================
    # Database Operations
    # =========================================================================

    def _create_session(self, session_uuid: str, user_id: int, conversation_id: str) -> Optional[int]:
        """Create orchestration session in DB"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO orchestration_sessions (session_id, user_id, conversation_id)
                VALUES (%s, %s, %s)
                RETURNING id
            """,
                (session_uuid, user_id, conversation_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"Failed to create orchestration session: {e}")
            return None

    def _persist_steps(self, session_id: Optional[int], steps: List[ThinkingStep]):
        """Persist thinking steps to DB"""
        if not session_id or not steps:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            for i, step in enumerate(steps):
                cur.execute(
                    """
                    INSERT INTO orchestration_steps
                    (session_id, step_order, step_type, step_data, agent_id, model_used, duration_ms, success)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        session_id,
                        i + 1,
                        step.step_type,
                        json.dumps(step.data),
                        step.agent_id,
                        step.model_used,
                        step.duration_ms,
                        step.success,
                    ),
                )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to persist orchestration steps: {e}")

    def _complete_session(self, session_id: Optional[int], total_steps: int, total_ms: int):
        """Mark session as completed"""
        if not session_id:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE orchestration_sessions
                SET status = 'completed', total_steps = %s, total_duration_ms = %s,
                    completed_at = NOW()
                WHERE id = %s
            """,
                (total_steps, total_ms, session_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to complete orchestration session: {e}")

    def _fail_session(self, session_id: Optional[int], error: str):
        """Mark session as failed"""
        if not session_id:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE orchestration_sessions
                SET status = 'failed', metadata = jsonb_set(
                    COALESCE(metadata, '{}'), '{error}', %s::jsonb
                ), completed_at = NOW()
                WHERE id = %s
            """,
                (json.dumps(error), session_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to mark orchestration session as failed: {e}")

    def _log_governance_event(
        self,
        event_type: str,
        action: str,
        agent_id: int = None,
        reason: str = None,
        outcome: str = "success",
    ):
        """Log to governance_audit_log"""
        try:
            from tools.creed.admin_routes import log_governance_event

            log_governance_event(
                event_type=event_type,
                category="orchestration",
                action=action,
                agent_id=agent_id,
                reason=reason,
                outcome=outcome,
            )
        except Exception as e:
            logger.debug(f"Failed to log governance event: {e}")


# =========================================================================
# Singleton
# =========================================================================

_engine_instance = None


def get_orchestration_engine() -> OrchestrationEngine:
    """Get singleton orchestration engine instance"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OrchestrationEngine()
    return _engine_instance
