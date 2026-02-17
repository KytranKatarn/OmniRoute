"""
A.R.C.H.I.E. Multi-Agent Orchestrator

When the intent parser detects requires_multi_agent=True, this module
decomposes the task into sub-tasks, assigns each to the best agent
from the indicated stations, executes them (serializing Ollama calls,
parallelizing Claude proxy calls), and synthesizes results.

Pipeline: decompose → assign → execute → synthesize
"""

import os
import sys
import json
import time
import logging
import asyncio
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))


@dataclass
class SubTask:
    index: int
    description: str
    domain: str
    station: str
    assigned_agent: Optional[Dict] = None
    response: Optional[str] = None
    model_used: Optional[str] = None
    duration_ms: int = 0
    status: str = "pending"


@dataclass
class MultiAgentResult:
    response: str
    sub_tasks: List[SubTask]
    thinking_steps: list = field(default_factory=list)
    total_duration_ms: int = 0
    agents_used: List[str] = field(default_factory=list)


class MultiAgentOrchestrator:
    """
    Decomposes multi-domain tasks into sub-tasks, assigns agents,
    executes with GPU-safe scheduling, and synthesizes results.
    """

    def __init__(self, orchestration_engine):
        """
        Args:
            orchestration_engine: Reference to OrchestrationEngine instance
                for reusing _execute_ollama, _execute_claude_proxy, etc.
        """
        self.engine = orchestration_engine

    def orchestrate_multi_agent(
        self,
        message: str,
        intent: Dict,
        user_id: int,
        session_id: Optional[int],
    ) -> MultiAgentResult:
        """
        Main multi-agent pipeline (synchronous wrapper).

        Args:
            message: Original user message
            intent: Parsed intent dict (with participating_stations, domains_detected)
            user_id: Requesting user ID
            session_id: DB session ID for persisting delegation_tasks

        Returns:
            MultiAgentResult with synthesized response and per-sub-task details
        """
        from orchestration_engine import ThinkingStep, StepType

        start_time = time.time()
        thinking_steps = []
        stations = intent.get("participating_stations", [])
        domains = intent.get("domains_detected", [])

        # Step 1: Decompose
        sub_tasks = self._decompose_task(message, stations, domains, thinking_steps)
        if not sub_tasks:
            # Decomposition failed — caller should fall back to single-agent
            return MultiAgentResult(
                response="",
                sub_tasks=[],
                thinking_steps=thinking_steps,
                total_duration_ms=int((time.time() - start_time) * 1000),
            )

        # Step 2: Assign agents
        self._assign_agents(sub_tasks, thinking_steps)

        # Step 3: Execute sub-tasks (GPU-safe)
        self._execute_subtasks(sub_tasks, message, user_id, session_id, thinking_steps)

        # Step 4: Synthesize
        final_response = self._synthesize_results(message, sub_tasks, thinking_steps)

        total_ms = int((time.time() - start_time) * 1000)
        agents_used = list(
            set(
                st.assigned_agent.get("name", "Unknown")
                for st in sub_tasks
                if st.assigned_agent
            )
        )

        return MultiAgentResult(
            response=final_response,
            sub_tasks=sub_tasks,
            thinking_steps=thinking_steps,
            total_duration_ms=total_ms,
            agents_used=agents_used,
        )

    # =========================================================================
    # Step 1: Decompose
    # =========================================================================

    def _decompose_task(
        self,
        message: str,
        stations: List[str],
        domains: List[str],
        thinking_steps: list,
    ) -> List[SubTask]:
        """Decompose the user's message into 2-4 sub-tasks using Claude proxy."""
        from orchestration_engine import ThinkingStep, StepType

        t0 = time.time()

        # Domain-to-station mapping (mirrors intent_parser)
        domain_to_station = {
            "security": "SECURITY",
            "performance": "ENGINEERING",
            "architecture": "ENGINEERING",
            "code": "ENGINEERING",
            "testing": "QA",
            "operations": "OPERATIONS",
            "business": "OPERATIONS",
            "creative": "CREATIVE",
        }

        system_prompt = (
            "You are a task decomposition engine. Given a user request that spans "
            "multiple domains, break it into 2-4 independent sub-tasks.\n\n"
            "For each sub-task, specify:\n"
            "- description: what needs to be done\n"
            "- required_domain: one of: security, engineering, qa, operations, creative\n\n"
            f"The user's request involves these domains: {', '.join(domains)}.\n"
            f"Available stations: {', '.join(stations)}.\n\n"
            "Return ONLY a JSON array, no other text. Example:\n"
            '[{"description": "Review code for SQL injection vulnerabilities", "required_domain": "security"}, '
            '{"description": "Optimize database query performance", "required_domain": "engineering"}]'
        )

        try:
            proxy_url = os.getenv(
                "CLAUDE_PROXY_URL", "http://host.docker.internal:7682"
            )
            resp = requests.post(
                f"{proxy_url}/api/chat",
                json={
                    "message": f"Decompose this request into sub-tasks:\n\n{message}",
                    "system_prompt": system_prompt,
                },
                timeout=60,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"Claude proxy returned {resp.status_code}")

            raw_response = resp.json().get("response", "")

            # Parse JSON from response (handle markdown code blocks)
            json_text = raw_response.strip()
            if "```" in json_text:
                # Extract from code block
                start = json_text.find("[")
                end = json_text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_text = json_text[start:end]
            elif not json_text.startswith("["):
                start = json_text.find("[")
                end = json_text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_text = json_text[start:end]

            tasks_data = json.loads(json_text)

            # Map domain names to station codes
            domain_map = {
                "security": "SECURITY",
                "engineering": "ENGINEERING",
                "qa": "QA",
                "operations": "OPERATIONS",
                "creative": "CREATIVE",
            }

            sub_tasks = []
            for i, task in enumerate(tasks_data[:4]):  # Max 4 sub-tasks
                domain = task.get("required_domain", "engineering").lower()
                station = domain_map.get(domain, "ENGINEERING")
                sub_tasks.append(
                    SubTask(
                        index=i,
                        description=task.get("description", f"Sub-task {i+1}"),
                        domain=domain,
                        station=station,
                    )
                )

            duration = int((time.time() - t0) * 1000)
            thinking_steps.append(
                ThinkingStep(
                    step_type=StepType.DECOMPOSE.value,
                    label=f"Decomposed into {len(sub_tasks)} sub-tasks",
                    data={
                        "sub_task_count": len(sub_tasks),
                        "sub_tasks": [
                            {
                                "description": st.description[:80],
                                "domain": st.domain,
                                "station": st.station,
                            }
                            for st in sub_tasks
                        ],
                    },
                    duration_ms=duration,
                )
            )

            return sub_tasks

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            duration = int((time.time() - t0) * 1000)
            logger.warning(f"Decomposition JSON parse failed: {e}")
            thinking_steps.append(
                ThinkingStep(
                    step_type=StepType.DECOMPOSE.value,
                    label="Decomposition failed (bad JSON)",
                    data={"error": str(e)},
                    duration_ms=duration,
                    success=False,
                )
            )
            return []

        except Exception as e:
            duration = int((time.time() - t0) * 1000)
            logger.warning(f"Decomposition failed: {e}")
            thinking_steps.append(
                ThinkingStep(
                    step_type=StepType.DECOMPOSE.value,
                    label=f"Decomposition failed: {str(e)[:60]}",
                    data={"error": str(e)},
                    duration_ms=duration,
                    success=False,
                )
            )
            return []

    # =========================================================================
    # Step 2: Assign Agents
    # =========================================================================

    def _assign_agents(
        self,
        sub_tasks: List[SubTask],
        thinking_steps: list,
    ):
        """Assign the best agent to each sub-task based on station/department."""
        from orchestration_engine import ThinkingStep, StepType

        t0 = time.time()

        # Station-to-department mapping for agent_delegation
        station_to_dept = {
            "SECURITY": "Security",
            "ENGINEERING": "Engineering",
            "QA": "Quality Assurance",
            "OPERATIONS": "Operations",
            "CREATIVE": "Creative",
            "COMMAND": "Command",
        }

        try:
            from agent_delegation import select_best_agent_for_task
        except ImportError:
            logger.warning("agent_delegation not available for multi-agent assignment")
            # Fall back: assign ARCHIE to all sub-tasks
            archie = {
                "id": 2,
                "name": "ARCHIE",
                "department": "Command",
                "worker_type": "internal",
                "model": "dolphin3-8k:latest",
                "tier": 1,
            }
            for st in sub_tasks:
                st.assigned_agent = archie
            thinking_steps.append(
                ThinkingStep(
                    step_type=StepType.DELEGATE.value,
                    label="Delegation: all tasks → ARCHIE (fallback)",
                    data={"reason": "agent_delegation module not available"},
                    duration_ms=int((time.time() - t0) * 1000),
                )
            )
            return

        assignments = []
        for st in sub_tasks:
            dept = station_to_dept.get(st.station, "Engineering")
            agent = select_best_agent_for_task(
                st.description, department_preference=dept
            )

            if agent and agent.get("id"):
                st.assigned_agent = {
                    "id": agent.get("id"),
                    "agent_id": agent.get("id"),
                    "name": agent.get("name", "Unknown"),
                    "department": agent.get("department", dept),
                    "worker_type": agent.get("worker_type", "internal"),
                    "model": agent.get("model", "dolphin3-8k:latest"),
                    "tier": agent.get("tier", 1),
                }
            else:
                # Fallback to ARCHIE
                st.assigned_agent = {
                    "id": 2,
                    "agent_id": 2,
                    "name": "ARCHIE",
                    "department": "Command",
                    "worker_type": "internal",
                    "model": "dolphin3-8k:latest",
                    "tier": 1,
                }

            assignments.append(
                {
                    "sub_task": st.description[:60],
                    "agent": st.assigned_agent["name"],
                    "station": st.station,
                }
            )

        duration = int((time.time() - t0) * 1000)
        thinking_steps.append(
            ThinkingStep(
                step_type=StepType.DELEGATE.value,
                label=f"Delegated {len(sub_tasks)} sub-tasks to {len(set(a['agent'] for a in assignments))} agents",
                data={"assignments": assignments},
                duration_ms=duration,
            )
        )

    # =========================================================================
    # Step 3: Execute Sub-Tasks
    # =========================================================================

    def _execute_subtasks(
        self,
        sub_tasks: List[SubTask],
        original_message: str,
        user_id: int,
        session_id: Optional[int],
        thinking_steps: list,
    ):
        """
        Execute all sub-tasks with GPU-safe scheduling.
        - Ollama tasks run sequentially (avoid model swap crashes on M4000)
        - Claude proxy tasks can run concurrently
        """
        from orchestration_engine import ThinkingStep, StepType

        # Classify sub-tasks by execution backend
        ollama_tasks = []
        claude_tasks = []

        for st in sub_tasks:
            if not st.assigned_agent:
                continue
            model = st.assigned_agent.get("model", "dolphin3-8k:latest")
            worker_type = st.assigned_agent.get("worker_type", "internal")

            # Internal agents use Ollama, contract agents use Claude proxy
            if worker_type == "internal":
                ollama_tasks.append(st)
            else:
                claude_tasks.append(st)

        # Execute Ollama tasks sequentially (GPU-safe)
        for st in ollama_tasks:
            self._execute_single_subtask(
                st, original_message, user_id, session_id, thinking_steps
            )

        # Execute Claude proxy tasks (could be parallel, but keeping simple with sequential
        # since Claude proxy is single-connection anyway)
        for st in claude_tasks:
            self._execute_single_subtask(
                st, original_message, user_id, session_id, thinking_steps
            )

    def _execute_single_subtask(
        self,
        sub_task: SubTask,
        original_message: str,
        user_id: int,
        session_id: Optional[int],
        thinking_steps: list,
    ):
        """Execute a single sub-task and record results."""
        from orchestration_engine import ThinkingStep, StepType, get_db

        t0 = time.time()
        agent = sub_task.assigned_agent or {}
        model = agent.get("model", "dolphin3-8k:latest")
        worker_type = agent.get("worker_type", "internal")
        agent_name = agent.get("name", "Unknown")

        prompt = (
            f"You are handling a specific aspect of a larger request.\n\n"
            f"Original user request: {original_message}\n\n"
            f"Your specific sub-task: {sub_task.description}\n\n"
            f"Focus only on your assigned sub-task. Be thorough but concise."
        )

        try:
            sub_task.status = "running"

            if worker_type == "internal":
                # Use Ollama via the engine's execution method
                response_text, actual_model = self.engine._execute_ollama(
                    prompt, model, user_id, "", False, None
                )
            else:
                # Use Claude proxy
                response_text, actual_model = self.engine._execute_claude_proxy(
                    prompt, model, False
                )

            sub_task.response = response_text
            sub_task.model_used = actual_model
            sub_task.status = "completed"

        except Exception as e:
            logger.error(f"Sub-task {sub_task.index} execution failed: {e}")
            sub_task.response = f"Error: {str(e)}"
            sub_task.model_used = model
            sub_task.status = "failed"

        sub_task.duration_ms = int((time.time() - t0) * 1000)

        # Persist to delegation_tasks table
        if session_id:
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO delegation_tasks
                    (session_id, parent_message, sub_task_index, sub_task_description,
                     assigned_agent_id, assigned_station, model_used, status,
                     response, duration_ms, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            CASE WHEN %s IN ('completed', 'failed') THEN NOW() ELSE NULL END)
                """,
                    (
                        session_id,
                        original_message[:500],
                        sub_task.index,
                        sub_task.description[:500],
                        agent.get("id"),
                        sub_task.station,
                        sub_task.model_used,
                        sub_task.status,
                        sub_task.response[:5000] if sub_task.response else None,
                        sub_task.duration_ms,
                        sub_task.status,
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to persist delegation task: {e}")

        # Record thinking step
        thinking_steps.append(
            ThinkingStep(
                step_type=StepType.EXECUTE.value,
                label=f"Sub-task {sub_task.index + 1}: {agent_name} ({sub_task.station}) [{sub_task.duration_ms}ms]",
                data={
                    "sub_task_index": sub_task.index,
                    "sub_task": sub_task.description[:80],
                    "agent": agent_name,
                    "station": sub_task.station,
                    "model": sub_task.model_used,
                    "status": sub_task.status,
                    "response_length": (
                        len(sub_task.response) if sub_task.response else 0
                    ),
                },
                duration_ms=sub_task.duration_ms,
                success=sub_task.status == "completed",
                agent_id=agent.get("id"),
                model_used=sub_task.model_used,
            )
        )

    # =========================================================================
    # Step 4: Synthesize
    # =========================================================================

    def _synthesize_results(
        self,
        original_message: str,
        sub_tasks: List[SubTask],
        thinking_steps: list,
    ) -> str:
        """Synthesize sub-task results into a unified response."""
        from orchestration_engine import ThinkingStep, StepType

        t0 = time.time()

        # Collect results
        completed = [st for st in sub_tasks if st.status == "completed"]
        failed = [st for st in sub_tasks if st.status == "failed"]

        if not completed:
            # All sub-tasks failed
            duration = int((time.time() - t0) * 1000)
            thinking_steps.append(
                ThinkingStep(
                    step_type=StepType.SYNTHESIZE.value,
                    label="Synthesis: all sub-tasks failed",
                    data={"completed": 0, "failed": len(failed)},
                    duration_ms=duration,
                    success=False,
                )
            )
            return "I attempted to break this into sub-tasks, but all of them encountered errors. Please try a simpler request or rephrase."

        # Build synthesis prompt
        results_text = []
        for st in sub_tasks:
            status_label = "COMPLETED" if st.status == "completed" else "FAILED"
            agent_name = (
                st.assigned_agent.get("name", "Unknown")
                if st.assigned_agent
                else "Unknown"
            )
            results_text.append(
                f"--- Sub-task {st.index + 1} ({st.domain}, {agent_name}) [{status_label}] ---\n"
                f"Task: {st.description}\n"
                f"Response: {st.response or 'No response'}\n"
            )

        synthesis_prompt = (
            f"You are synthesizing results from multiple AI agents who each handled "
            f"a different aspect of the user's request.\n\n"
            f"Original request: {original_message}\n\n"
            f"Sub-task results:\n{''.join(results_text)}\n\n"
            f"Provide a unified, coherent response that integrates all sub-task results. "
            f"Do not mention that multiple agents were involved — present it as one seamless answer. "
            f"If any sub-tasks failed, note what couldn't be addressed."
        )

        try:
            proxy_url = os.getenv(
                "CLAUDE_PROXY_URL", "http://host.docker.internal:7682"
            )
            resp = requests.post(
                f"{proxy_url}/api/chat",
                json={
                    "message": synthesis_prompt,
                    "system_prompt": "You are a synthesis engine. Combine multiple sub-task results into a single coherent response.",
                },
                timeout=90,
            )

            if resp.status_code == 200:
                final_response = resp.json().get("response", "")
            else:
                raise RuntimeError(f"Claude proxy returned {resp.status_code}")

        except Exception as e:
            logger.warning(
                f"Synthesis via Claude proxy failed: {e}, falling back to concatenation"
            )
            # Fallback: concatenate responses with headers
            parts = []
            for st in completed:
                parts.append(f"**{st.domain.title()}**:\n{st.response}\n")
            if failed:
                parts.append(
                    f"\n*Note: {len(failed)} sub-task(s) could not be completed.*"
                )
            final_response = "\n".join(parts)

        duration = int((time.time() - t0) * 1000)
        thinking_steps.append(
            ThinkingStep(
                step_type=StepType.SYNTHESIZE.value,
                label=f"Synthesized {len(completed)}/{len(sub_tasks)} results ({duration}ms)",
                data={
                    "completed_count": len(completed),
                    "failed_count": len(failed),
                    "response_length": len(final_response),
                },
                duration_ms=duration,
            )
        )

        return final_response
