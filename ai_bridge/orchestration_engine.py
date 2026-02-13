"""
A.R.C.H.I.E. Orchestration Engine

The core brain that sits between user input and agent execution.
Composes existing systems: intent parsing, smart routing, agent delegation,
IAAE governance, and model execution into a single orchestrated pipeline.

Each request flows through:
1. Intent parsing (what does the user want?)
2. IAAE pre-check (any ethical constraints?)
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
import psycopg2
from psycopg2.extras import RealDictCursor
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Ensure ai_bridge is on path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'platform_v2'))


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


class StepType(Enum):
    INTENT_PARSE = "intent_parse"
    ROUTE_DECISION = "route_decision"
    AGENT_SELECT = "agent_select"
    IAAE_CHECK = "iaae_check"
    WELFARE_CHECK = "welfare_check"
    GPU_CHECK = "gpu_check"
    EXECUTE = "execute"
    FALLBACK = "fallback"


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
    """An IAAE governance event logged during orchestration"""
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
            'success': self.success,
            'response': self.response,
            'thinking_steps': [
                {
                    'step_type': s.step_type,
                    'label': s.label,
                    'data': s.data,
                    'duration_ms': s.duration_ms,
                    'success': s.success,
                    'model_used': s.model_used,
                }
                for s in self.thinking_steps
            ],
            'agent_used': self.agent_used,
            'agent_id': self.agent_id,
            'model_used': self.model_used,
            'conversation_id': self.conversation_id,
            'session_id': self.session_id,
            'governance_events': [
                {
                    'event_type': g.event_type,
                    'action': g.action,
                    'outcome': g.outcome,
                    'details': g.details,
                }
                for g in self.governance_events
            ],
            'total_duration_ms': self.total_duration_ms,
        }


class OrchestrationEngine:
    """
    ARCHIE's orchestration brain.

    Routes user requests through intent parsing, IAAE governance,
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
                # Try package import first (when /mnt/archie_brain is on sys.path)
                from platform_v2.tools.archie_core.intent_parser import get_intent_parser
                self._intent_parser = get_intent_parser()
            except ImportError:
                try:
                    # Try direct import (when archie_core is on sys.path)
                    from tools.archie_core.intent_parser import get_intent_parser
                    self._intent_parser = get_intent_parser()
                except ImportError:
                    try:
                        # Fallback: add to path directly
                        parser_path = os.path.join(
                            os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'archie_core'
                        )
                        if parser_path not in sys.path:
                            sys.path.insert(0, parser_path)
                        from intent_parser import get_intent_parser
                        self._intent_parser = get_intent_parser()
                    except ImportError as e:
                        logger.warning(f"Intent parser not available: {e}")
        return self._intent_parser

    def _get_smart_router(self):
        """Lazy-load smart router"""
        if self._smart_router is None:
            try:
                from smart_router import get_router
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
    ) -> OrchestrationResult:
        """
        Main orchestration pipeline.

        Takes a user message and routes it through the full pipeline:
        intent → IAAE → welfare → routing → agent → execution → logging.

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

        try:
            # --- Step 1: Parse intent ---
            intent = self._step_parse_intent(message, steps)

            # --- Step 2: IAAE pre-check ---
            iaae_ok = self._step_iaae_check(intent, steps, governance_events)

            # --- Step 3: Agent welfare check ---
            # (deferred until after agent selection)

            # --- Step 4: Smart routing (model/tier selection) ---
            routing = self._step_route_decision(message, intent, steps)

            # --- Step 5: GPU state check ---
            gpu_info = self._step_gpu_check(routing, steps)

            # --- Step 6: Select agent ---
            selected_agent = self._step_select_agent(message, intent, steps)

            # --- Step 6b: Agent welfare check (now that we have an agent) ---
            if selected_agent and selected_agent.get('agent_id'):
                welfare_ok = self._step_welfare_check(
                    selected_agent['agent_id'], selected_agent.get('name', 'Unknown'),
                    steps, governance_events
                )
                if not welfare_ok:
                    # Try to select an alternate agent
                    alt_agent = self._select_alternate_agent(
                        message, intent, exclude_id=selected_agent['agent_id']
                    )
                    if alt_agent:
                        selected_agent = alt_agent
                        steps.append(ThinkingStep(
                            step_type=StepType.AGENT_SELECT.value,
                            label="Agent reassigned (welfare)",
                            data={'new_agent': alt_agent.get('name'), 'reason': 'previous agent stressed'},
                            success=True,
                        ))

            # --- Step 7: Execute ---
            model_used = self._resolve_model(routing, gpu_info)
            response_text = self._step_execute(
                message, user_id, conversation_id,
                selected_agent, model_used, routing, intent,
                voice_mode, user_context, steps
            )

            # --- Step 8: Log steps to DB ---
            total_ms = int((time.time() - start_time) * 1000)
            self._persist_steps(db_session_id, steps)
            self._complete_session(db_session_id, len(steps), total_ms)

            # Log governance event for the orchestration
            self._log_governance_event(
                'orchestration', 'orchestrate_request',
                agent_id=selected_agent.get('agent_id') if selected_agent else None,
                reason=f"Orchestrated '{intent.get('type', 'unknown')}' task via {model_used}",
                outcome='success'
            )

            return OrchestrationResult(
                success=True,
                response=response_text,
                thinking_steps=steps,
                agent_used=selected_agent.get('name') if selected_agent else 'ARCHIE',
                agent_id=selected_agent.get('agent_id') if selected_agent else None,
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
    # Pipeline Steps
    # =========================================================================

    def _step_parse_intent(self, message: str, steps: List[ThinkingStep]) -> Dict:
        """Step 1: Parse the user's intent"""
        t0 = time.time()
        intent = {'type': 'conversation', 'confidence': 0.5, 'complexity': {'score': 3}}

        parser = self._get_intent_parser()
        if parser:
            try:
                intent = parser.parse(message)
            except Exception as e:
                logger.warning(f"Intent parser error: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(ThinkingStep(
            step_type=StepType.INTENT_PARSE.value,
            label=f"Intent: {intent.get('type', 'unknown')}",
            data={
                'type': intent.get('type'),
                'confidence': round(intent.get('confidence', 0), 2),
                'complexity_score': intent.get('complexity', {}).get('score', 3),
                'requires_multi_agent': intent.get('requires_multi_agent', False),
            },
            duration_ms=duration,
        ))

        return intent

    def _step_iaae_check(
        self, intent: Dict, steps: List[ThinkingStep],
        governance_events: List[GovernanceEvent]
    ) -> bool:
        """Step 2: IAAE ethics pre-check"""
        t0 = time.time()
        passed = True
        violations = []

        try:
            # Map intent types to actions that might have constraints
            action_map = {
                'file_operation': 'destructive_action',
                'system_status': 'self_modify',
            }
            action = action_map.get(intent.get('type'))

            if action:
                try:
                    sys.path.insert(0, os.path.join(
                        os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'team_management'
                    ))
                    from iaae_routes import check_constraints
                    violations = check_constraints(action)
                    if violations:
                        mandatory = [v for v in violations if v.get('severity') == 'mandatory']
                        if mandatory:
                            passed = False
                except ImportError:
                    logger.debug("IAAE routes not available for constraint check")
        except Exception as e:
            logger.warning(f"IAAE check error: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(ThinkingStep(
            step_type=StepType.IAAE_CHECK.value,
            label="IAAE: passed" if passed else "IAAE: blocked",
            data={
                'passed': passed,
                'violations': len(violations),
                'details': [v.get('constraint_name', '') for v in violations] if violations else [],
            },
            duration_ms=duration,
            success=passed,
        ))

        if not passed:
            governance_events.append(GovernanceEvent(
                event_type='constraint_violation',
                action=intent.get('type', 'unknown'),
                outcome='blocked',
                details={'violations': [v.get('constraint_name') for v in violations]},
            ))

        return passed

    def _step_route_decision(
        self, message: str, intent: Dict, steps: List[ThinkingStep]
    ) -> Optional[Dict]:
        """Step 4: Smart routing — decide which model tier to use"""
        t0 = time.time()
        routing = None

        router = self._get_smart_router()
        if router:
            try:
                # Use intent parser result if available, fall back to SmartRouter classifier
                intent_type = intent.get('type', 'conversation')
                if intent_type == 'conversation':
                    task_type = 'conversation'
                else:
                    task_type = router.classify_task(message)
                complexity = intent.get('complexity', {}).get('score', 5)
                recommendation = router.suggest_model(task_type, complexity=complexity)
                routing = {
                    'tier': recommendation.tier,
                    'provider': recommendation.provider,
                    'model_name': recommendation.model_name,
                    'reason': recommendation.reason,
                    'task_type': task_type,
                    'should_escalate': recommendation.should_escalate,
                }
            except Exception as e:
                logger.warning(f"Smart router error: {e}")

        if routing is None:
            # Fallback: use local model
            routing = {
                'tier': 'local',
                'provider': 'ollama',
                'model_name': 'dolphin3:latest',
                'reason': 'Smart router unavailable, using default local model',
                'task_type': 'conversation',
                'should_escalate': False,
            }

        duration = int((time.time() - t0) * 1000)
        steps.append(ThinkingStep(
            step_type=StepType.ROUTE_DECISION.value,
            label=f"Route: {routing['tier']} ({routing['model_name']})",
            data={
                'tier': routing['tier'],
                'model': routing['model_name'],
                'provider': routing['provider'],
                'task_type': routing['task_type'],
                'reason': routing['reason'],
            },
            duration_ms=duration,
        ))

        return routing

    def _step_gpu_check(
        self, routing: Optional[Dict], steps: List[ThinkingStep]
    ) -> Dict:
        """Step 5: Check GPU state — what model is loaded?"""
        t0 = time.time()
        gpu_info = {
            'loaded_model': None,
            'can_use_loaded': False,
            'swap_required': False,
        }

        if routing and routing.get('provider') == 'ollama':
            try:
                loaded = self._get_loaded_model()
                if loaded:
                    gpu_info['loaded_model'] = loaded
                    requested = routing.get('model_name', '')
                    # Check if the loaded model matches or can handle the task
                    if loaded == requested or loaded.split(':')[0] == requested.split(':')[0]:
                        gpu_info['can_use_loaded'] = True
                    else:
                        gpu_info['swap_required'] = True
                        # Prefer using the loaded model to avoid crash
                        gpu_info['recommendation'] = 'use_loaded'
            except Exception as e:
                logger.debug(f"GPU check failed: {e}")

        duration = int((time.time() - t0) * 1000)

        label = "GPU: "
        if gpu_info.get('loaded_model'):
            if gpu_info['can_use_loaded']:
                label += f"{gpu_info['loaded_model']} (ready)"
            elif gpu_info['swap_required']:
                label += f"{gpu_info['loaded_model']} (swap needed)"
            else:
                label += "checking"
        else:
            label += "no model loaded"

        steps.append(ThinkingStep(
            step_type=StepType.GPU_CHECK.value,
            label=label,
            data=gpu_info,
            duration_ms=duration,
        ))

        return gpu_info

    def _step_select_agent(
        self, message: str, intent: Dict, steps: List[ThinkingStep]
    ) -> Optional[Dict]:
        """Step 6: Select the best agent via Bridge stations, then delegation, then ARCHIE fallback"""
        t0 = time.time()
        agent = None
        source = 'default'

        intent_type = intent.get('type', 'conversation')

        # Map intent to Bridge station codes
        station_map = {
            'code_task': ['ENGINEERING', 'ENGINEERING_CODE', 'ENGINEERING_BUILD'],
            'team_task': ['OPERATIONS', 'OPERATIONS_CORE', 'HR'],
            'business_task': ['OPERATIONS', 'FINANCE'],
            'knowledge_query': ['CONSCIOUSNESS', 'RND', 'RND_AI'],
            'creative_task': ['CREATIVE', 'CREATIVE_MEDIA', 'CREATIVE_CONTENT'],
            'system_status': ['OPERATIONS', 'INFRASTRUCTURE', 'SECURITY'],
            'conversation': ['COMMAND'],
        }
        preferred_stations = station_map.get(intent_type, ['COMMAND'])

        # Try 1: Find agent assigned to a matching Bridge station
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT a.id as agent_id, a.name, a.department, a.worker_type,
                       a.model, a.tier, bs.station_code
                FROM station_assignments sa
                JOIN bridge_stations bs ON sa.station_id = bs.id
                JOIN agents a ON sa.agent_id = a.id
                WHERE sa.is_active = true
                  AND a.status = 'active'
                  AND bs.station_code = ANY(%s)
                ORDER BY sa.priority ASC, sa.assignment_type = 'primary' DESC
                LIMIT 1
            """, (preferred_stations,))
            row = cur.fetchone()
            if row:
                agent = dict(row)
                source = 'station'
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Station assignment lookup error: {e}")

        # Try 2: Fall back to agent_delegation department match
        if not agent:
            try:
                from agent_delegation import select_best_agent_for_task
                dept_map = {
                    'code_task': 'Engineering',
                    'team_task': 'Operations',
                    'business_task': 'Strategy',
                    'knowledge_query': 'Research',
                    'creative_task': 'Creative',
                    'system_status': 'Operations',
                }
                dept = dept_map.get(intent_type)
                result = select_best_agent_for_task(message, department_preference=dept)
                if result and result.get('agent_id'):
                    agent = result
                    source = 'delegation'
            except Exception as e:
                logger.warning(f"Agent delegation fallback error: {e}")

        # Try 3: Always fall back to ARCHIE (agent_id=2)
        if not agent or not agent.get('agent_id'):
            agent = {
                'agent_id': 2,
                'name': 'ARCHIE',
                'department': 'Command',
                'worker_type': 'internal',
                'model': 'dolphin3:latest',
                'tier': 1,
            }

        duration = int((time.time() - t0) * 1000)

        steps.append(ThinkingStep(
            step_type=StepType.AGENT_SELECT.value,
            label=f"Agent: {agent.get('name', 'Unknown')} ({agent.get('department', '')}) [{source}]",
            data={
                'agent_id': agent.get('agent_id'),
                'name': agent.get('name'),
                'department': agent.get('department'),
                'worker_type': agent.get('worker_type'),
                'tier': agent.get('tier'),
                'source': source,
                'station': agent.get('station_code'),
            },
            duration_ms=duration,
            agent_id=agent.get('agent_id'),
        ))

        return agent

    def _step_welfare_check(
        self, agent_id: int, agent_name: str,
        steps: List[ThinkingStep],
        governance_events: List[GovernanceEvent]
    ) -> bool:
        """Step 6b: Check agent welfare before delegation"""
        t0 = time.time()
        healthy = True

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT stress_level, energy_level, current_mood
                FROM agent_emotional_state
                WHERE agent_id = %s
                ORDER BY timestamp DESC LIMIT 1
            """, (agent_id,))
            state = cur.fetchone()
            cur.close()
            conn.close()

            if state:
                stress = float(state.get('stress_level') or 0)
                energy = float(state.get('energy_level') or 1.0)
                if stress > 0.8:
                    healthy = False
                    governance_events.append(GovernanceEvent(
                        event_type='welfare_intervention',
                        action='skip_stressed_agent',
                        outcome='agent_rested',
                        details={
                            'agent_id': agent_id,
                            'agent_name': agent_name,
                            'stress_level': stress,
                        },
                    ))
                elif energy < 0.2:
                    healthy = False
                    governance_events.append(GovernanceEvent(
                        event_type='welfare_intervention',
                        action='skip_exhausted_agent',
                        outcome='agent_rested',
                        details={
                            'agent_id': agent_id,
                            'agent_name': agent_name,
                            'energy_level': energy,
                        },
                    ))
        except Exception as e:
            logger.debug(f"Welfare check error for agent {agent_id}: {e}")

        duration = int((time.time() - t0) * 1000)
        steps.append(ThinkingStep(
            step_type=StepType.WELFARE_CHECK.value,
            label=f"Welfare: {'healthy' if healthy else 'stressed — reassigning'}",
            data={
                'agent_id': agent_id,
                'agent_name': agent_name,
                'healthy': healthy,
            },
            duration_ms=duration,
            success=healthy,
            agent_id=agent_id,
        ))

        return healthy

    def _step_execute(
        self, message: str, user_id: int, conversation_id: str,
        agent: Optional[Dict], model_name: str, routing: Optional[Dict],
        intent: Dict, voice_mode: bool, user_context: Optional[Dict],
        steps: List[ThinkingStep]
    ) -> str:
        """Step 7: Execute the request with the selected model"""
        t0 = time.time()
        response_text = ""
        actual_model = model_name

        try:
            provider = routing.get('provider', 'ollama') if routing else 'ollama'
            tier = routing.get('tier', 'local') if routing else 'local'

            if provider == 'ollama' or tier == 'local':
                response_text, actual_model = self._execute_ollama(
                    message, model_name, user_id, conversation_id,
                    voice_mode, user_context
                )
            elif provider == 'claude':
                response_text, actual_model = self._execute_claude_proxy(
                    message, model_name, voice_mode
                )
            else:
                # Fallback to Ollama
                response_text, actual_model = self._execute_ollama(
                    message, model_name, user_id, conversation_id,
                    voice_mode, user_context
                )

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            # Fallback: try local Ollama with whatever is loaded
            try:
                steps.append(ThinkingStep(
                    step_type=StepType.FALLBACK.value,
                    label="Fallback: retrying with local model",
                    data={'original_error': str(e)},
                ))
                response_text, actual_model = self._execute_ollama(
                    message, 'dolphin3:latest', user_id, conversation_id,
                    voice_mode, user_context
                )
            except Exception as e2:
                raise RuntimeError(f"All execution paths failed: {e2}") from e

        duration = int((time.time() - t0) * 1000)
        steps.append(ThinkingStep(
            step_type=StepType.EXECUTE.value,
            label=f"Execute: {actual_model} ({duration}ms)",
            data={
                'model': actual_model,
                'response_length': len(response_text),
                'voice_mode': voice_mode,
            },
            duration_ms=duration,
            model_used=actual_model,
        ))

        return response_text

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

        # Step 1: IAAE check for joint work
        intent = {'type': 'collaboration', 'complexity': {'score': 7}}
        self._step_iaae_check(intent, steps, governance_events)

        # Step 2: Log that we're starting a joint collaboration
        self._log_governance_event(
            'orchestration', 'start_joint_collaboration',
            reason=f"Joint collaboration on: {topic[:100]}",
            outcome='initiated'
        )

        steps.append(ThinkingStep(
            step_type='joint_init',
            label=f"Joint collaboration: {topic[:60]}",
            data={'topic': topic, 'max_turns': max_turns},
        ))

        try:
            # Step 3: Create and run joint session via collaboration engine
            import asyncio
            sys.path.insert(0, os.path.join(
                os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'consciousness'
            ))
            from collaboration_engine import get_collaboration_engine

            engine = get_collaboration_engine()
            session = engine.start_session(topic, max_turns=max_turns, user_id=user_id)

            steps.append(ThinkingStep(
                step_type='joint_session',
                label=f"Session created: {session.id[:8]}...",
                data={'session_id': session.id},
            ))

            # Run the joint collaboration asynchronously
            loop = asyncio.new_event_loop()
            try:
                completed_session = loop.run_until_complete(
                    engine.run_joint_collaboration(session.id)
                )
            finally:
                loop.close()

            # Gather work products
            work_products = engine.get_work_products(session.id)

            total_ms = int((time.time() - start_time) * 1000)
            steps.append(ThinkingStep(
                step_type=StepType.EXECUTE.value,
                label=f"Joint work complete ({len(work_products)} products, {total_ms}ms)",
                data={
                    'products_count': len(work_products),
                    'session_status': completed_session.status.value,
                    'turns_used': completed_session.current_turn,
                },
                duration_ms=total_ms,
            ))

            self._log_governance_event(
                'orchestration', 'complete_joint_collaboration',
                reason=f"Joint collaboration completed: {len(work_products)} work products",
                outcome='success'
            )

            return {
                'success': True,
                'session_id': session.id,
                'status': completed_session.status.value,
                'topic': topic,
                'turns_used': completed_session.current_turn,
                'work_products': work_products,
                'thinking_steps': [
                    {
                        'step_type': s.step_type,
                        'label': s.label,
                        'data': s.data,
                        'duration_ms': s.duration_ms,
                        'success': s.success,
                    }
                    for s in steps
                ],
                'governance_events': [
                    {'event_type': g.event_type, 'action': g.action, 'outcome': g.outcome}
                    for g in governance_events
                ],
                'total_duration_ms': int((time.time() - start_time) * 1000),
            }

        except Exception as e:
            logger.error(f"Joint orchestration failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'thinking_steps': [
                    {'step_type': s.step_type, 'label': s.label, 'data': s.data}
                    for s in steps
                ],
                'total_duration_ms': int((time.time() - start_time) * 1000),
            }

    # =========================================================================
    # Execution Backends
    # =========================================================================

    def _execute_ollama(
        self, message: str, model_name: str, user_id: int,
        conversation_id: str, voice_mode: bool, user_context: Optional[Dict]
    ) -> tuple:
        """Execute via local Ollama (dolphin3 or whatever is loaded)"""
        try:
            # Use ArchieAI for personality-enriched responses
            sys.path.insert(0, os.path.join(
                os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'archie_core'
            ))
            from ai_chat import ArchieAI

            ai = ArchieAI()
            context = user_context or {}
            if voice_mode:
                context['voice_mode'] = True

            # Load conversation history
            history = self._load_conversation_history(user_id, conversation_id)

            result = ai.chat(message, context, history)
            if result.get('success'):
                return result['response'], result.get('model', model_name)
            else:
                raise RuntimeError(result.get('error', 'ArchieAI chat failed'))
        except ImportError:
            # Fall back to direct Ollama call
            from archie_bridge import call_ollama

            system_prompt = "You are A.R.C.H.I.E., a helpful AI assistant."
            if voice_mode:
                system_prompt += " Keep responses concise and conversational. No markdown."

            result = call_ollama(message, model=model_name, system_prompt=system_prompt)
            if result.get('success'):
                return result['response'], result.get('model', model_name)
            else:
                raise RuntimeError(result.get('error', 'Ollama call failed'))

    def _execute_claude_proxy(
        self, message: str, model_name: str, voice_mode: bool
    ) -> tuple:
        """Execute via Claude CLI proxy (port 7682, Max subscription)"""
        proxy_url = os.getenv('CLAUDE_PROXY_URL', 'http://host.docker.internal:7682')

        system_prompt = None
        if voice_mode:
            system_prompt = "Keep responses concise and conversational. No markdown formatting."

        payload = {
            'message': message,
            'system_prompt': system_prompt,
        }

        resp = requests.post(
            f"{proxy_url}/api/chat",
            json=payload,
            timeout=130,
        )

        if resp.status_code == 200:
            data = resp.json()
            return data.get('response', ''), f"claude-proxy ({model_name})"
        else:
            raise RuntimeError(f"Claude proxy returned {resp.status_code}: {resp.text[:200]}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_loaded_model(self) -> Optional[str]:
        """Check which Ollama model is currently loaded in GPU memory (local instance)"""
        try:
            local_host = os.getenv('OLLAMA_LOCAL_HOST', 'host.docker.internal')
            local_port = os.getenv('OLLAMA_LOCAL_PORT', '11434')
            resp = requests.get(f"http://{local_host}:{local_port}/api/ps", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get('models', [])
                if models:
                    return models[0].get('name')
        except Exception as e:
            logger.debug(f"Could not check loaded model: {e}")
        return None

    def _resolve_model(self, routing: Optional[Dict], gpu_info: Dict) -> str:
        """Resolve final model name, preferring loaded model to avoid swaps"""
        if routing is None:
            return 'dolphin3:latest'

        requested = routing.get('model_name', 'dolphin3:latest')

        # If provider is not ollama, use the requested model as-is
        if routing.get('provider') != 'ollama':
            return requested

        # If GPU check says we can use the loaded model, use it
        if gpu_info.get('can_use_loaded') and gpu_info.get('loaded_model'):
            return gpu_info['loaded_model']

        # If a swap would be required and the loaded model can handle it, prefer loaded
        if gpu_info.get('swap_required') and gpu_info.get('loaded_model'):
            loaded = gpu_info['loaded_model']
            # Conversational tasks can be handled by any model
            task_type = routing.get('task_type', 'conversation')
            if task_type in ('conversation', 'format', 'code_simple', 'documentation'):
                return loaded
            # For complex tasks, still prefer loaded model over crashing
            return loaded

        return requested

    def _select_alternate_agent(
        self, message: str, intent: Dict, exclude_id: int
    ) -> Optional[Dict]:
        """Select an alternative agent when the primary is stressed"""
        try:
            from agent_delegation import select_best_agent_for_task
            agent = select_best_agent_for_task(message)
            if agent and agent.get('agent_id') != exclude_id:
                return agent
        except Exception:
            pass
        return None

    def _load_conversation_history(self, user_id: int, conversation_id: str) -> list:
        """Load recent conversation history for context"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT message, response FROM ai_conversations
                WHERE user_id = %s AND conversation_id = %s
                ORDER BY created_at DESC LIMIT 5
            """, (user_id, conversation_id))
            rows = cur.fetchall()
            cur.close()
            conn.close()

            history = []
            for row in reversed(rows):
                history.append({'role': 'user', 'content': row['message']})
                if row.get('response'):
                    history.append({'role': 'assistant', 'content': row['response']})
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
            cur.execute("""
                INSERT INTO orchestration_sessions (session_id, user_id, conversation_id)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (session_uuid, user_id, conversation_id))
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
                cur.execute("""
                    INSERT INTO orchestration_steps
                    (session_id, step_order, step_type, step_data, agent_id, model_used, duration_ms, success)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    session_id, i + 1, step.step_type,
                    json.dumps(step.data), step.agent_id,
                    step.model_used, step.duration_ms, step.success,
                ))
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
            cur.execute("""
                UPDATE orchestration_sessions
                SET status = 'completed', total_steps = %s, total_duration_ms = %s,
                    completed_at = NOW()
                WHERE id = %s
            """, (total_steps, total_ms, session_id))
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
            cur.execute("""
                UPDATE orchestration_sessions
                SET status = 'failed', metadata = jsonb_set(
                    COALESCE(metadata, '{}'), '{error}', %s::jsonb
                ), completed_at = NOW()
                WHERE id = %s
            """, (json.dumps(error), session_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to mark orchestration session as failed: {e}")

    def _log_governance_event(
        self, event_type: str, action: str,
        agent_id: int = None, reason: str = None, outcome: str = 'success'
    ):
        """Log to governance_audit_log"""
        try:
            sys.path.insert(0, os.path.join(
                os.path.dirname(__file__), '..', 'platform_v2', 'tools', 'team_management'
            ))
            from iaae_routes import log_governance_event
            log_governance_event(
                event_type=event_type,
                category='orchestration',
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
