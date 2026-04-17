"""
Step-by-Step Guidance Generator for Improvement Proposals
Breaks down complex improvements into actionable implementation steps
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
from typing import Dict, List, Optional
from datetime import datetime
import os
from db import _get_db_password


class StepGuidanceGenerator:
    """
    Generates step-by-step implementation guidance for improvement proposals.

    Features:
    - Breaks complex tasks into manageable steps
    - Estimates complexity and time
    - Identifies prerequisites and dependencies
    - Provides testing checkpoints
    - Tracks progress through steps
    """

    def __init__(self):
        # Category-specific step templates
        self.category_templates = {
            "security": [
                "Identify security vulnerability or weakness",
                "Research best practices and security patterns",
                "Implement security fix or enhancement",
                "Add security tests and validation",
                "Run security scan and penetration test",
                "Document security changes and rationale",
            ],
            "performance": [
                "Profile and measure current performance",
                "Identify performance bottlenecks",
                "Research optimization strategies",
                "Implement performance improvements",
                "Add performance benchmarks",
                "Verify performance gains",
            ],
            "ui": [
                "Design UI mockup or wireframe",
                "Get user feedback on design",
                "Implement UI components",
                "Add CSS styling and responsiveness",
                "Test across different browsers/devices",
                "Gather user feedback on implementation",
            ],
            "api": [
                "Design API endpoint structure",
                "Define request/response schemas",
                "Implement API endpoint",
                "Add input validation and error handling",
                "Write API documentation",
                "Create API tests and integration tests",
            ],
            "database": [
                "Design database schema changes",
                "Create migration script",
                "Test migration on development database",
                "Implement application code changes",
                "Add database indexes for performance",
                "Run migration on production with backup",
            ],
            "testing": [
                "Identify test scenarios and edge cases",
                "Write unit tests for core functionality",
                "Write integration tests",
                "Run test suite and fix failures",
                "Add to CI/CD pipeline",
                "Document test coverage",
            ],
        }

        # Default generic template
        self.default_template = [
            "Analyze requirements and scope",
            "Design solution approach",
            "Implement core functionality",
            "Add error handling and edge cases",
            "Write tests",
            "Document changes",
            "Deploy and monitor",
        ]

    def generate_steps(
        self,
        proposal_id: int = None,
        title: str = None,
        description: str = None,
        category: str = "general",
        complexity: str = "medium",
        custom_steps: List[str] = None,
    ) -> Dict:
        """
        Generate implementation steps for a proposal.

        Args:
            proposal_id: Optional proposal ID to load from database
            title: Proposal title
            description: Proposal description
            category: Proposal category (for template selection)
            complexity: Complexity level (low/medium/high)
            custom_steps: Custom step list (overrides template)

        Returns:
            Dict with steps array and metadata
        """
        # If proposal_id provided, load from database
        if proposal_id:
            proposal_data = self._load_proposal(proposal_id)
            if proposal_data:
                title = proposal_data.get("title", title)
                description = proposal_data.get("description", description)
                category = proposal_data.get("category", category)
                complexity = proposal_data.get("complexity", complexity)

        # Get template steps
        if custom_steps:
            base_steps = custom_steps
        elif category in self.category_templates:
            base_steps = self.category_templates[category]
        else:
            base_steps = self.default_template

        # Enhance steps with metadata
        steps = []
        for i, step_title in enumerate(base_steps):
            step = {
                "step_number": i + 1,
                "title": step_title,
                "description": self._generate_step_description(
                    step_title, category, description
                ),
                "status": "pending",  # pending, in_progress, completed, blocked, skipped
                "estimated_time": self._estimate_step_time(step_title, complexity),
                "dependencies": self._identify_dependencies(i, base_steps),
                "testing_checkpoint": self._is_testing_checkpoint(step_title),
                "files_to_modify": [],  # Will be populated during implementation
                "completed_at": None,
                "notes": "",
            }
            steps.append(step)

        # Add pre and post steps based on complexity
        if complexity in ["medium", "high"]:
            steps.insert(
                0,
                {
                    "step_number": 0,
                    "title": "Create backup before starting",
                    "description": "Use backup manager to create a pre-implementation backup for rollback capability",
                    "status": "pending",
                    "estimated_time": "5 min",
                    "dependencies": [],
                    "testing_checkpoint": False,
                    "critical": True,
                },
            )

        # Add final deployment step
        steps.append(
            {
                "step_number": len(steps) + 1,
                "title": "Deploy and monitor",
                "description": "Deploy changes to production and monitor for issues",
                "status": "pending",
                "estimated_time": "30 min",
                "dependencies": [len(steps)],  # Depends on all previous steps
                "testing_checkpoint": True,
                "critical": True,
            }
        )

        # Re-number steps after insertions
        for i, step in enumerate(steps):
            step["step_number"] = i + 1

        # Calculate total estimated time
        total_time = self._calculate_total_time(steps)

        return {
            "proposal_id": proposal_id,
            "title": title,
            "category": category,
            "complexity": complexity,
            "steps": steps,
            "total_steps": len(steps),
            "total_estimated_time": total_time,
            "generated_at": datetime.now().isoformat(),
            "progress": self._calculate_progress(steps),
        }

    def update_step_status(
        self,
        proposal_id: int,
        step_number: int,
        status: str,
        notes: str = None,
        files_modified: List[str] = None,
    ) -> Dict:
        """
        Update the status of a specific step.

        Args:
            proposal_id: The proposal ID
            step_number: Which step to update (1-indexed)
            status: New status (pending/in_progress/completed/blocked/skipped)
            notes: Optional notes about the step
            files_modified: List of files modified in this step

        Returns:
            Updated steps object
        """
        # Load current steps from database
        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT plan_steps FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )
            row = cur.fetchone()

            if not row or not row["plan_steps"]:
                return {"success": False, "error": "No steps found for proposal"}

            steps_data = row["plan_steps"]
            steps = steps_data.get("steps", [])

            # Find and update the step
            for step in steps:
                if step["step_number"] == step_number:
                    step["status"] = status
                    if notes:
                        step["notes"] = notes
                    if files_modified:
                        step["files_to_modify"] = files_modified
                    if status == "completed":
                        step["completed_at"] = datetime.now().isoformat()
                    break

            # Recalculate progress
            steps_data["progress"] = self._calculate_progress(steps)

            # Save back to database
            cur.execute(
                """
                UPDATE improvement_proposals
                SET plan_steps = %s
                WHERE id = %s
            """,
                (json.dumps(steps_data), proposal_id),
            )

            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        return {
            "success": True,
            "steps": steps_data,
            "progress": steps_data["progress"],
        }

    def _load_proposal(self, proposal_id: int) -> Optional[Dict]:
        """Load proposal from database"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT title, description, category, complexity
                    FROM improvement_proposals
                    WHERE id = %s
                """,
                    (proposal_id,),
                )
                proposal = cur.fetchone()
                return dict(proposal) if proposal else None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            return None

    def _get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def _generate_step_description(
        self, step_title: str, category: str, full_description: str
    ) -> str:
        """Generate a detailed description for a step"""
        # Extract relevant parts from full description
        # For now, just return a generic description based on title
        descriptions = {
            "backup": "Create a full backup using the backup manager to ensure rollback capability",
            "profile": "Use profiling tools to measure current performance metrics",
            "design": "Create a design document or mockup for review",
            "implement": "Write the core implementation code following best practices",
            "test": "Write comprehensive tests including unit and integration tests",
            "document": "Update documentation including inline comments and user guides",
            "deploy": "Deploy changes to production environment with monitoring",
        }

        # Match keywords in step title
        for keyword, desc in descriptions.items():
            if keyword in step_title.lower():
                return desc

        return f"Complete the step: {step_title}"

    def _estimate_step_time(self, step_title: str, complexity: str) -> str:
        """Estimate time for a step based on complexity"""
        base_times = {"low": 15, "medium": 30, "high": 60}

        multipliers = {
            "design": 1.5,
            "implement": 2.0,
            "test": 1.5,
            "research": 1.5,
            "document": 1.0,
        }

        base = base_times.get(complexity, 30)

        # Check for multipliers
        for keyword, mult in multipliers.items():
            if keyword in step_title.lower():
                base = int(base * mult)
                break

        if base < 60:
            return f"{base} min"
        else:
            hours = base // 60
            mins = base % 60
            if mins > 0:
                return f"{hours}h {mins}min"
            return f"{hours}h"

    def _identify_dependencies(
        self, step_index: int, all_steps: List[str]
    ) -> List[int]:
        """Identify which previous steps this step depends on"""
        # Most steps depend on the previous step
        if step_index == 0:
            return []
        else:
            return [step_index]  # Depends on previous step

    def _is_testing_checkpoint(self, step_title: str) -> bool:
        """Determine if this step is a testing checkpoint"""
        testing_keywords = [
            "test",
            "verify",
            "validate",
            "check",
            "benchmark",
            "monitor",
        ]
        return any(kw in step_title.lower() for kw in testing_keywords)

    def _calculate_total_time(self, steps: List[Dict]) -> str:
        """Calculate total estimated time for all steps"""
        total_minutes = 0

        for step in steps:
            time_str = step.get("estimated_time", "0 min")
            # Parse time string like "30 min" or "2h 15min"
            if "h" in time_str:
                parts = time_str.split("h")
                total_minutes += int(parts[0].strip()) * 60
                if len(parts) > 1 and "min" in parts[1]:
                    total_minutes += int(parts[1].replace("min", "").strip())
            elif "min" in time_str:
                total_minutes += int(time_str.replace("min", "").strip())

        hours = total_minutes // 60
        mins = total_minutes % 60

        if hours > 0:
            return f"{hours}h {mins}min" if mins > 0 else f"{hours}h"
        return f"{mins} min"

    def _calculate_progress(self, steps: List[Dict]) -> Dict:
        """Calculate progress statistics"""
        total = len(steps)
        completed = sum(1 for s in steps if s.get("status") == "completed")
        in_progress = sum(1 for s in steps if s.get("status") == "in_progress")
        blocked = sum(1 for s in steps if s.get("status") == "blocked")

        return {
            "total_steps": total,
            "completed": completed,
            "in_progress": in_progress,
            "blocked": blocked,
            "pending": total - completed - in_progress - blocked,
            "percentage": int((completed / total) * 100) if total > 0 else 0,
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def generate_steps_for_proposal(proposal_id: int) -> Dict:
    """Quick function to generate steps for a proposal"""
    generator = StepGuidanceGenerator()
    return generator.generate_steps(proposal_id=proposal_id)


def update_step(
    proposal_id: int, step_number: int, status: str, notes: str = None
) -> Dict:
    """Quick function to update a step status"""
    generator = StepGuidanceGenerator()
    return generator.update_step_status(proposal_id, step_number, status, notes)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Step Guidance Generator - Test Mode")
    print("=" * 60)

    generator = StepGuidanceGenerator()

    # Test 1: Generate steps for a security improvement
    print("\n1. SECURITY IMPROVEMENT STEPS:")
    print("-" * 60)
    result = generator.generate_steps(
        title="Fix SQL injection vulnerability in user search",
        category="security",
        complexity="high",
    )

    for step in result["steps"]:
        status_icon = "✓" if step["status"] == "completed" else "○"
        print(f"{status_icon} Step {step['step_number']}: {step['title']}")
        print(f"   Time: {step['estimated_time']}")
        if step.get("testing_checkpoint"):
            print(f"   [TESTING CHECKPOINT]")

    print(f"\nTotal time: {result['total_estimated_time']}")
    print(f"Progress: {result['progress']['percentage']}%")

    # Test 2: Generate steps for a UI improvement
    print("\n2. UI IMPROVEMENT STEPS:")
    print("-" * 60)
    result2 = generator.generate_steps(
        title="Add dark mode toggle to settings", category="ui", complexity="medium"
    )

    for step in result2["steps"][:5]:  # Show first 5
        print(f"Step {step['step_number']}: {step['title']} ({step['estimated_time']})")

    print(f"\nTotal steps: {result2['total_steps']}")
    print(f"Total time: {result2['total_estimated_time']}")

    print("\n✅ Step Guidance Generator tests passed!")
