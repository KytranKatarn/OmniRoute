"""
App Builder Orchestrator - GPT-Pilot Style Agent Loop
Coordinates all agents to build applications from natural language

Purpose:
- Manage application generation workflow
- Coordinate clarification, planning, coding, testing agents
- Track progress and handle errors
- Provide real-time updates via SSE

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import sys
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum
import json
import traceback

# Add paths for imports
sys.path.insert(0, "/mnt/archie_brain/platform_v2")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from logging_config import audit_log

# ============================================================================
# ORCHESTRATOR STATES
# ============================================================================


class OrchestratorState(Enum):
    """States in the app building workflow"""

    INITIALIZING = "initializing"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    PLAN_APPROVAL = "plan_approval"
    GENERATING = "generating"
    TESTING = "testing"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRole(Enum):
    """Different agent roles in the orchestrator"""

    CLARIFICATION = "clarification"
    PLANNER = "planner"
    ARCHITECT = "architect"
    BACKEND_GENERATOR = "backend_generator"
    FRONTEND_GENERATOR = "frontend_generator"
    DATABASE_GENERATOR = "database_generator"
    TEST_GENERATOR = "test_generator"
    TEST_RUNNER = "test_runner"
    DEPLOYMENT = "deployment"


# ============================================================================
# ORCHESTRATOR EVENTS
# ============================================================================


class OrchestratorEvent:
    """Event emitted during orchestration"""

    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any],
        timestamp: Optional[datetime] = None,
    ):
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or datetime.now()

    def to_dict(self) -> Dict:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_sse(self) -> str:
        """Convert to Server-Sent Events format"""
        return f"data: {json.dumps(self.to_dict())}\n\n"


# ============================================================================
# APP BUILDER ORCHESTRATOR
# ============================================================================


class AppBuilderOrchestrator:
    """
    Main orchestrator for App Builder
    Implements GPT-Pilot style iterative development workflow
    """

    def __init__(self, project_id: int, user_id: int, db_connection=None):
        """
        Initialize orchestrator

        Args:
            project_id: Database ID of the project
            user_id: User ID creating the project
            db_connection: Database connection (optional)
        """
        self.project_id = project_id
        self.user_id = user_id
        self.db = db_connection

        # State management
        self.state = OrchestratorState.INITIALIZING
        self.current_agent: Optional[AgentRole] = None
        self.progress = 0  # 0-100%

        # Context
        self.project_data: Dict = {}
        self.clarifications: Dict[str, Any] = {}
        self.plan: Dict[str, Any] = {}
        self.generated_files: List[Dict] = []
        self.execution_log: List[Dict] = []

        # Event listeners
        self.event_listeners: List[Callable[[OrchestratorEvent], None]] = []

        # Agent instances (lazy loaded)
        self._agents: Dict[AgentRole, Any] = {}

    # ========================================================================
    # EVENT MANAGEMENT
    # ========================================================================

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit an event to all listeners"""
        event = OrchestratorEvent(event_type, data)

        # Call all listeners
        for listener in self.event_listeners:
            try:
                listener(event)
            except Exception as e:
                print(f"[Orchestrator] Event listener error: {e}")

        # Log to database
        self._log_event(event)

    def add_event_listener(self, listener: Callable[[OrchestratorEvent], None]):
        """Add an event listener"""
        self.event_listeners.append(listener)

    def _log_event(self, event: OrchestratorEvent):
        """Log event to database"""
        try:
            if self.db:
                from app import get_db

                conn = self.db or get_db()
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO app_builder_execution_logs
                    (project_id, step_name, step_type, status, output_data, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                    (
                        self.project_id,
                        event.event_type,
                        self.state.value,
                        "completed",
                        json.dumps(event.data),
                    ),
                )

                conn.commit()
                cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to log event: {e}")

    # ========================================================================
    # STATE MANAGEMENT
    # ========================================================================

    def transition_state(self, new_state: OrchestratorState):
        """Transition to a new state"""
        old_state = self.state
        self.state = new_state

        self.emit_event(
            "state_changed",
            {"from": old_state.value, "to": new_state.value, "progress": self.progress},
        )

        # Update database
        self._update_project_status(new_state.value)

    def _update_project_status(self, status: str):
        """Update project status in database"""
        try:
            if self.db:
                from app import get_db

                conn = self.db or get_db()
                cur = conn.cursor()

                cur.execute(
                    """
                    UPDATE app_builder_projects
                    SET status = %s, progress = %s, current_step = %s, updated_at = NOW()
                    WHERE id = %s
                """,
                    (
                        status,
                        self.progress,
                        self.current_agent.value if self.current_agent else None,
                        self.project_id,
                    ),
                )

                conn.commit()
                cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to update project status: {e}")

    def update_progress(self, progress: int):
        """Update progress (0-100)"""
        self.progress = max(0, min(100, progress))

        self.emit_event("progress_updated", {"progress": self.progress, "state": self.state.value})

        self._update_project_status(self.state.value)

    # ========================================================================
    # AGENT MANAGEMENT
    # ========================================================================

    def get_agent(self, role: AgentRole) -> Any:
        """Get or create an agent instance"""
        if role not in self._agents:
            self._agents[role] = self._create_agent(role)

        return self._agents[role]

    def _create_agent(self, role: AgentRole) -> Any:
        """Factory method to create agents"""
        if role == AgentRole.CLARIFICATION:
            from agents.clarification_agent import ClarificationAgent

            return ClarificationAgent(self.project_id, self.user_id)

        elif role == AgentRole.PLANNER:
            from agents.planner_agent import PlannerAgent

            return PlannerAgent(self.project_id, self.clarifications)

        elif role == AgentRole.ARCHITECT:
            from agents.architect_agent import ArchitectAgent

            return ArchitectAgent(self.project_id, self.plan)

        elif role == AgentRole.BACKEND_GENERATOR:
            from agents.backend_generator import BackendGenerator

            return BackendGenerator(self.project_id, self.plan)

        elif role == AgentRole.FRONTEND_GENERATOR:
            from agents.frontend_generator import FrontendGenerator

            return FrontendGenerator(self.project_id, self.plan)

        elif role == AgentRole.DATABASE_GENERATOR:
            from agents.database_generator import DatabaseGenerator

            return DatabaseGenerator(self.project_id, self.plan)

        elif role == AgentRole.TEST_GENERATOR:
            from agents.test_generator import TestGenerator

            return TestGenerator(self.project_id, self.generated_files)

        elif role == AgentRole.TEST_RUNNER:
            from agents.test_runner import TestRunner

            return TestRunner(self.project_id)

        elif role == AgentRole.DEPLOYMENT:
            from agents.deployment_agent import DeploymentAgent

            return DeploymentAgent(self.project_id)

        else:
            raise ValueError(f"Unknown agent role: {role}")

    # ========================================================================
    # MAIN WORKFLOW
    # ========================================================================

    async def run(self) -> Dict[str, Any]:
        """
        Main orchestrator loop
        Runs through all phases of app building

        Returns:
            Result dictionary with success status and data
        """
        try:
            # Load project data
            await self._load_project()

            # Phase 1: Clarification
            if self.state == OrchestratorState.INITIALIZING:
                await self._phase_clarification()

            # Phase 2: Planning
            if self.state == OrchestratorState.CLARIFYING:
                await self._phase_planning()

            # Phase 3: Plan Approval (wait for user)
            if self.state == OrchestratorState.PLANNING:
                self.transition_state(OrchestratorState.PLAN_APPROVAL)
                return {
                    "success": True,
                    "status": "awaiting_approval",
                    "plan": self.plan,
                }

            # Phase 4: Code Generation (only if plan approved)
            if self.state == OrchestratorState.PLAN_APPROVAL and self.project_data.get("plan_approved"):
                await self._phase_generation()

            # Phase 5: Testing
            if self.state == OrchestratorState.GENERATING:
                await self._phase_testing()

            # Phase 6: Deployment
            if self.state == OrchestratorState.TESTING and self.project_data.get("tests_passed"):
                await self._phase_deployment()

            # Mark as completed
            if self.state == OrchestratorState.DEPLOYING:
                self.transition_state(OrchestratorState.COMPLETED)
                self.update_progress(100)

            return {
                "success": True,
                "status": self.state.value,
                "project_id": self.project_id,
                "progress": self.progress,
            }

        except Exception as e:
            self.transition_state(OrchestratorState.FAILED)
            error_msg = str(e)
            error_trace = traceback.format_exc()

            self.emit_event("error", {"message": error_msg, "traceback": error_trace})

            # Log error
            if audit_log:
                audit_log(
                    "APP_BUILDER_ERROR",
                    {
                        "project_id": self.project_id,
                        "error": error_msg,
                        "state": self.state.value,
                    },
                    success=False,
                )

            return {"success": False, "status": "failed", "error": error_msg}

    # ========================================================================
    # WORKFLOW PHASES
    # ========================================================================

    async def _load_project(self):
        """Load project data from database"""
        self.emit_event("loading_project", {"project_id": self.project_id})

        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute("SELECT * FROM app_builder_projects WHERE id = %s", (self.project_id,))
            row = cur.fetchone()

            if not row:
                raise ValueError(f"Project {self.project_id} not found")

            # Convert to dict (assuming RealDictCursor or similar)
            self.project_data = dict(row) if hasattr(row, "items") else {}

            # Set initial state based on project status
            status = self.project_data.get("status", "planning")
            self.state = OrchestratorState(status)
            self.progress = self.project_data.get("progress", 0)

            cur.close()

            self.emit_event("project_loaded", {"project_id": self.project_id, "status": status})

        except Exception as e:
            raise Exception(f"Failed to load project: {e}")

    async def _phase_clarification(self):
        """Phase 1: Ask clarifying questions"""
        self.transition_state(OrchestratorState.CLARIFYING)
        self.current_agent = AgentRole.CLARIFICATION
        self.update_progress(10)

        self.emit_event("phase_started", {"phase": "clarification"})

        # Get clarification agent
        agent = self.get_agent(AgentRole.CLARIFICATION)

        # Generate clarifying questions
        questions = await agent.generate_questions(self.project_data.get("user_prompt"))

        # If no questions needed, skip to planning
        if not questions or len(questions) == 0:
            self.clarifications = {}
            return

        # Store questions in database
        await self._save_clarifications(questions, answers=None)

        # Emit questions for user to answer
        self.emit_event("clarification_questions", {"questions": questions})

        # Wait for user answers (will be provided via update_clarifications method)

    async def _phase_planning(self):
        """Phase 2: Generate detailed project plan"""
        self.transition_state(OrchestratorState.PLANNING)
        self.current_agent = AgentRole.PLANNER
        self.update_progress(30)

        self.emit_event("phase_started", {"phase": "planning"})

        # Get planner agent
        agent = self.get_agent(AgentRole.PLANNER)

        # Generate plan
        self.plan = await agent.generate_plan(self.project_data.get("user_prompt"), self.clarifications)

        # Save plan to database
        await self._save_plan(self.plan)

        self.emit_event("plan_generated", {"plan": self.plan})

    async def _phase_generation(self):
        """Phase 3: Generate code files"""
        self.transition_state(OrchestratorState.GENERATING)
        self.update_progress(50)

        self.emit_event("phase_started", {"phase": "generation"})

        # Generate backend
        self.current_agent = AgentRole.BACKEND_GENERATOR
        backend_agent = self.get_agent(AgentRole.BACKEND_GENERATOR)
        backend_files = await backend_agent.generate(self.plan)
        self.generated_files.extend(backend_files)
        self.update_progress(60)

        # Generate frontend
        self.current_agent = AgentRole.FRONTEND_GENERATOR
        frontend_agent = self.get_agent(AgentRole.FRONTEND_GENERATOR)
        frontend_files = await frontend_agent.generate(self.plan)
        self.generated_files.extend(frontend_files)
        self.update_progress(70)

        # Generate database
        self.current_agent = AgentRole.DATABASE_GENERATOR
        db_agent = self.get_agent(AgentRole.DATABASE_GENERATOR)
        db_files = await db_agent.generate(self.plan)
        self.generated_files.extend(db_files)
        self.update_progress(75)

        # Save all generated files
        await self._save_files(self.generated_files)

        self.emit_event("generation_complete", {"total_files": len(self.generated_files)})

    async def _phase_testing(self):
        """Phase 4: Generate and run tests"""
        self.transition_state(OrchestratorState.TESTING)
        self.current_agent = AgentRole.TEST_GENERATOR
        self.update_progress(80)

        self.emit_event("phase_started", {"phase": "testing"})

        # Generate tests
        test_generator = self.get_agent(AgentRole.TEST_GENERATOR)
        test_files = await test_generator.generate(self.generated_files)
        await self._save_files(test_files)

        # Run tests
        self.current_agent = AgentRole.TEST_RUNNER
        test_runner = self.get_agent(AgentRole.TEST_RUNNER)
        test_results = await test_runner.run_tests()

        # Update database with results
        await self._save_test_results(test_results)

        self.update_progress(90)

        self.emit_event("testing_complete", {"results": test_results})

    async def _phase_deployment(self):
        """Phase 5: Deploy application"""
        self.transition_state(OrchestratorState.DEPLOYING)
        self.current_agent = AgentRole.DEPLOYMENT
        self.update_progress(95)

        self.emit_event("phase_started", {"phase": "deployment"})

        # Deploy
        deployment_agent = self.get_agent(AgentRole.DEPLOYMENT)
        deployment_result = await deployment_agent.deploy()

        # Update database
        await self._save_deployment(deployment_result)

        self.emit_event("deployment_complete", {"result": deployment_result})

    # ========================================================================
    # DATABASE HELPERS
    # ========================================================================

    async def _save_clarifications(self, questions: List[Dict], answers: Optional[Dict] = None):
        """Save clarification questions and answers to database"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET clarification_questions = %s, clarification_answers = %s, updated_at = NOW()
                WHERE id = %s
            """,
                (
                    json.dumps(questions),
                    json.dumps(answers) if answers else None,
                    self.project_id,
                ),
            )

            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to save clarifications: {e}")

    async def _save_plan(self, plan: Dict):
        """Save project plan to database"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET project_plan = %s, tech_stack = %s, dependencies = %s, updated_at = NOW()
                WHERE id = %s
            """,
                (
                    json.dumps(plan),
                    json.dumps(plan.get("tech_stack", {})),
                    json.dumps(plan.get("dependencies", {})),
                    self.project_id,
                ),
            )

            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to save plan: {e}")

    async def _save_files(self, files: List[Dict]):
        """Save generated files to database"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            for file_data in files:
                cur.execute(
                    """
                    INSERT INTO app_builder_files
                    (project_id, file_path, file_name, file_type, content, generated_by, generation_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        self.project_id,
                        file_data["path"],
                        file_data["name"],
                        file_data["type"],
                        file_data["content"],
                        file_data.get("generated_by", "orchestrator"),
                        file_data.get("method", "llm"),
                    ),
                )

            # Update total files count
            cur.execute(
                """
                UPDATE app_builder_projects
                SET total_files = (SELECT COUNT(*) FROM app_builder_files WHERE project_id = %s),
                    updated_at = NOW()
                WHERE id = %s
            """,
                (self.project_id, self.project_id),
            )

            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to save files: {e}")

    async def _save_test_results(self, results: Dict):
        """Save test results to database"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET tests_generated = TRUE,
                    tests_passed = %s,
                    test_results = %s,
                    updated_at = NOW()
                WHERE id = %s
            """,
                (results.get("passed", False), json.dumps(results), self.project_id),
            )

            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to save test results: {e}")

    async def _save_deployment(self, deployment: Dict):
        """Save deployment information to database"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET deployed = TRUE,
                    deployed_at = NOW(),
                    deployment_url = %s,
                    deployment_platform = %s,
                    deployment_config = %s,
                    updated_at = NOW()
                WHERE id = %s
            """,
                (
                    deployment.get("url"),
                    deployment.get("platform"),
                    json.dumps(deployment.get("config", {})),
                    self.project_id,
                ),
            )

            conn.commit()
            cur.close()
        except Exception as e:
            print(f"[Orchestrator] Failed to save deployment: {e}")

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    async def update_clarifications(self, answers: Dict):
        """Update clarification answers (called when user responds)"""
        self.clarifications = answers
        await self._save_clarifications(self.project_data.get("clarification_questions", []), answers)

        # Continue to planning phase
        await self._phase_planning()

    async def approve_plan(self):
        """Approve the plan and continue to generation"""
        try:
            from app import get_db

            conn = self.db or get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET plan_approved = TRUE, plan_approved_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """,
                (self.project_id,),
            )

            conn.commit()
            cur.close()

            self.project_data["plan_approved"] = True

            # Continue to generation phase
            await self._phase_generation()
            await self._phase_testing()

            # Check if we should auto-deploy
            if self.project_data.get("tests_passed"):
                await self._phase_deployment()

        except Exception as e:
            print(f"[Orchestrator] Failed to approve plan: {e}")
            raise

    async def cancel(self):
        """Cancel the orchestration"""
        self.transition_state(OrchestratorState.CANCELLED)
        self.emit_event("cancelled", {"project_id": self.project_id})


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("APP BUILDER ORCHESTRATOR TEST")
    print("=" * 80)

    # Test event system
    def test_listener(event: OrchestratorEvent):
        print(f"  Event: {event.event_type} - {event.data}")

    # Create orchestrator (mock)
    orchestrator = AppBuilderOrchestrator(project_id=1, user_id=1)
    orchestrator.add_event_listener(test_listener)

    # Test state transitions
    print("\n Testing state transitions:")
    orchestrator.transition_state(OrchestratorState.CLARIFYING)
    orchestrator.update_progress(10)
    orchestrator.transition_state(OrchestratorState.PLANNING)
    orchestrator.update_progress(30)

    print("\n✅ Orchestrator test complete")
    print("=" * 80)
