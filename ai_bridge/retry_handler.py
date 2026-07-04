"""
Test Retry Handler for A.R.C.H.I.E. Improvements Lab
Handles the test-fail-retry loop with automatic contractor escalation

Workflow:
1. Tests fail → retry with same agent (up to 3 times)
2. Agent receives failure context for smarter regeneration
3. After 3 failures → escalate to external contractor
4. Contractor proposes fix → human reviews via chat
5. Human decides: apply fix | try another contractor | investigate manually

Author: A.R.C.H.I.E.
Date: 2026-01-14
"""

import os
from db import _get_db_password
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    logger.error("psycopg2 not available")
    psycopg2 = None


class TestRetryHandler:
    """
    Manages test failure retries and contractor escalation.

    Constants:
        MAX_RETRIES: Maximum retry attempts before escalation (3)

    Escalation Flow:
        retry 1 → retry 2 → retry 3 → contractor consultation → human review
    """

    MAX_RETRIES = 3

    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": _get_db_password(),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def handle_test_failure(self, proposal_id: int, test_results: Dict, sandbox_id: int = None) -> Dict:
        """
        Handle a test failure - decide whether to retry or escalate.

        Args:
            proposal_id: ID of the failing proposal
            test_results: Test execution results with details
            sandbox_id: Optional sandbox instance ID

        Returns:
            {
                'action': 'retry' | 'escalate' | 'error',
                'retry_count': int,
                'message': str,
                ...
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get current proposal state
            cur.execute(
                """
                SELECT
                    ip.*,
                    a.name as assigned_agent_name,
                    a.model as assigned_agent_model
                FROM improvement_proposals ip
                LEFT JOIN agents a ON ip.assigned_agent_id = a.id
                WHERE ip.id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                return {
                    "action": "error",
                    "error": f"Proposal #{proposal_id} not found",
                }

            current_retry_count = proposal.get("test_retry_count", 0) or 0

            # Build failure context
            failure_context = self._build_failure_context(
                test_results, proposal.get("test_failure_context"), current_retry_count
            )

            if current_retry_count < self.MAX_RETRIES:
                # Retry with same agent
                return self._trigger_retry(
                    cur,
                    conn,
                    proposal_id,
                    proposal,
                    failure_context,
                    current_retry_count + 1,
                )
            else:
                # Max retries exhausted - escalate to contractor
                return self._escalate_to_contractor(cur, conn, proposal_id, proposal, failure_context)

        except Exception as e:
            conn.rollback()
            logger.error(f"Error handling test failure for proposal {proposal_id}: {e}")
            return {"action": "error", "error": str(e)}
        finally:
            cur.close()
            conn.close()

    def _build_failure_context(self, current_results: Dict, previous_context: Dict, retry_count: int) -> Dict:
        """
        Build comprehensive failure context for agent retry.

        Accumulates:
        - Current test failures (error messages, stack traces)
        - Previous retry attempts and their failures
        - Pattern analysis (recurring failures)
        """
        if previous_context is None:
            previous_context = {"attempts": []}

        if isinstance(previous_context, str):
            try:
                previous_context = json.loads(previous_context)
            except Exception:
                previous_context = {"attempts": []}

        # Extract failure details from current results
        failed_tests = []
        error_messages = []

        if "suite_results" in current_results:
            for suite in current_results.get("suite_results", []):
                if not suite.get("passed", True):
                    failed_tests.append(
                        {
                            "name": suite.get("name", "Unknown"),
                            "error": suite.get("error", ""),
                            "output": suite.get("output", "")[:500],  # Truncate
                        }
                    )
                    if suite.get("error"):
                        error_messages.append(suite["error"])

        # Build new context
        new_attempt = {
            "attempt_number": retry_count + 1,
            "timestamp": datetime.now().isoformat(),
            "failed_tests": failed_tests,
            "error_summary": error_messages[:5],  # Top 5 errors
            "overall_status": current_results.get("overall_status", "failed"),
            "passed_count": current_results.get("summary", {}).get("passed", 0),
            "failed_count": current_results.get("summary", {}).get("failed", 0),
        }

        attempts = previous_context.get("attempts", [])
        attempts.append(new_attempt)

        # Analyze patterns
        patterns = self._analyze_failure_patterns(attempts)

        return {
            "attempts": attempts,
            "total_retries": len(attempts),
            "patterns": patterns,
            "last_failure": new_attempt,
            "recurring_errors": self._find_recurring_errors(attempts),
        }

    def _analyze_failure_patterns(self, attempts: List[Dict]) -> Dict:
        """Analyze failure patterns across retry attempts."""
        if len(attempts) < 2:
            return {"pattern_detected": False}

        # Count test names that fail repeatedly
        test_failure_counts = {}
        for attempt in attempts:
            for test in attempt.get("failed_tests", []):
                name = test.get("name", "Unknown")
                test_failure_counts[name] = test_failure_counts.get(name, 0) + 1

        # Find tests that fail every time
        always_failing = [name for name, count in test_failure_counts.items() if count == len(attempts)]

        return {
            "pattern_detected": len(always_failing) > 0,
            "always_failing_tests": always_failing,
            "test_failure_frequency": test_failure_counts,
        }

    def _find_recurring_errors(self, attempts: List[Dict]) -> List[str]:
        """Find error messages that appear in multiple attempts."""
        error_counts = {}
        for attempt in attempts:
            for error in attempt.get("error_summary", []):
                # Normalize error (first 100 chars)
                normalized = error[:100] if error else ""
                if normalized:
                    error_counts[normalized] = error_counts.get(normalized, 0) + 1

        # Return errors appearing more than once
        return [err for err, count in error_counts.items() if count > 1]

    def _trigger_retry(
        self,
        cur,
        conn,
        proposal_id: int,
        proposal: Dict,
        failure_context: Dict,
        new_retry_count: int,
    ) -> Dict:
        """
        Trigger a retry with the same agent.

        Updates:
        - test_retry_count
        - test_failure_context
        - status back to code_generating
        """
        # Update proposal
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                test_retry_count = %s,
                test_failure_context = %s,
                status = 'code_generating',
                last_retry_at = NOW()
            WHERE id = %s
        """,
            (new_retry_count, json.dumps(failure_context), proposal_id),
        )

        # Log retry event
        self._log_chat_message(
            cur,
            proposal_id,
            sender_type="system",
            content=f"Test retry #{new_retry_count} initiated. Previous failures: {len(failure_context.get('recurring_errors', []))} recurring errors detected.",
            message_type="action",
        )

        conn.commit()

        logger.info(f"Proposal #{proposal_id}: Triggered retry {new_retry_count}/{self.MAX_RETRIES}")

        return {
            "action": "retry",
            "retry_count": new_retry_count,
            "max_retries": self.MAX_RETRIES,
            "message": f"Retry {new_retry_count}/{self.MAX_RETRIES} initiated",
            "failure_context": failure_context,
            "agent_id": proposal.get("assigned_agent_id"),
            "agent_name": proposal.get("assigned_agent_name"),
        }

    def _escalate_to_contractor(self, cur, conn, proposal_id: int, proposal: Dict, failure_context: Dict) -> Dict:
        """
        Escalate to external contractor after max retries.

        Selects contractor based on:
        1. Category matching (security → Claude, etc.)
        2. Availability
        3. Round-robin if multiple available
        """
        # Select appropriate contractor
        contractor = self._select_contractor(cur, proposal.get("category"))

        if not contractor:
            # No contractor available - escalate to human only
            cur.execute(
                """
                UPDATE improvement_proposals
                SET
                    escalation_status = 'human_only',
                    escalated_at = NOW(),
                    test_failure_context = %s
                WHERE id = %s
            """,
                (json.dumps(failure_context), proposal_id),
            )

            self._log_chat_message(
                cur,
                proposal_id,
                sender_type="system",
                content="No contractors available. Escalated to human-only investigation.",
                message_type="action",
            )

            conn.commit()

            return {
                "action": "human_only",
                "message": "No contractors available - requires human investigation",
                "failure_context": failure_context,
            }

        # Update proposal for contractor consultation
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                escalation_status = 'contractor_consulting',
                contractor_agent_id = %s,
                escalated_at = NOW(),
                test_failure_context = %s,
                status = 'escalated'
            WHERE id = %s
        """,
            (contractor["id"], json.dumps(failure_context), proposal_id),
        )

        # Create contractor consultation record
        consultation_id = self._create_consultation(cur, proposal_id, contractor["id"], proposal, failure_context)

        # Log to chat
        self._log_chat_message(
            cur,
            proposal_id,
            sender_type="system",
            content=f"Escalated to contractor: {contractor['name']} ({contractor['api_provider']}). Awaiting proposal.",
            message_type="action",
        )

        conn.commit()

        logger.info(f"Proposal #{proposal_id}: Escalated to contractor {contractor['name']}")

        return {
            "action": "escalate",
            "contractor_id": contractor["id"],
            "contractor_name": contractor["name"],
            "contractor_provider": contractor["api_provider"],
            "consultation_id": consultation_id,
            "message": f"Escalated to {contractor['name']} for consultation",
            "failure_context": failure_context,
        }

    def _select_contractor(self, cur, category: str) -> Optional[Dict]:
        """
        Select appropriate contractor for the proposal category.

        Selection criteria:
        1. Match category to contractor specialty if possible
        2. Check availability (not currently consulting)
        3. Round-robin among available contractors
        """
        # Category to provider mapping (preferred)
        category_preferences = {
            "security": "anthropic",  # Claude for security
            "database": "openai",  # GPT for database
            "performance": "google",  # Gemini for analysis
            "api": "anthropic",
            "ui": "openai",
        }

        preferred_provider = category_preferences.get(category)

        # Try preferred provider first
        if preferred_provider:
            cur.execute(
                """
                SELECT id, name, api_provider, model, personality_prompt
                FROM agents
                WHERE worker_type = 'contract'
                AND api_provider = %s
                AND status = 'active'
                AND api_enabled = TRUE
                LIMIT 1
            """,
                (preferred_provider,),
            )

            contractor = cur.fetchone()
            if contractor:
                return dict(contractor)

        # Fallback: any available contractor
        cur.execute(
            """
            SELECT id, name, api_provider, model, personality_prompt
            FROM agents
            WHERE worker_type = 'contract'
            AND status = 'active'
            AND api_enabled = TRUE
            ORDER BY last_used ASC NULLS FIRST
            LIMIT 1
        """
        )

        contractor = cur.fetchone()
        return dict(contractor) if contractor else None

    def _create_consultation(
        self,
        cur,
        proposal_id: int,
        contractor_id: int,
        proposal: Dict,
        failure_context: Dict,
    ) -> int:
        """Create a contractor consultation record."""
        # Build prompt for contractor
        prompt = self._build_contractor_prompt(proposal, failure_context)

        cur.execute(
            """
            INSERT INTO contractor_consultations
            (proposal_id, contractor_id, request_prompt, consultation_status)
            VALUES (%s, %s, %s, 'pending')
            RETURNING id
        """,
            (proposal_id, contractor_id, prompt),
        )

        result = cur.fetchone()
        return result["id"] if result else 0

    def _build_contractor_prompt(self, proposal: Dict, failure_context: Dict) -> str:
        """Build the prompt to send to contractor."""
        attempts = failure_context.get("attempts", [])
        recurring_errors = failure_context.get("recurring_errors", [])

        # Handle None values properly (get returns None if key exists but value is None)
        title = proposal.get("title") or "Unknown"
        category = proposal.get("category") or "General"
        description = proposal.get("description") or "No description"
        code_changes = proposal.get("code_changes") or "No code changes recorded"

        prompt = f"""You are a senior contractor reviewing a failed improvement proposal.

## PROPOSAL
**Title**: {title}
**Category**: {category}
**Description**: {description}

## ORIGINAL CODE CHANGES
```
{code_changes[:2000]}
```

## TEST FAILURES
This proposal has failed {len(attempts)} times.

### Recurring Errors
{chr(10).join(f'- {err}' for err in recurring_errors[:5]) if recurring_errors else 'No recurring patterns detected'}

### Last Failure Details
"""

        if attempts:
            last = attempts[-1]
            prompt += f"""
- Failed Tests: {last.get('failed_count', 0)}
- Passed Tests: {last.get('passed_count', 0)}

**Error Details:**
"""
            for test in last.get("failed_tests", [])[:3]:
                test_name = test.get("name") or "Unknown"
                test_error = (test.get("error") or "Unknown error")[:300]
                prompt += f"""
Test: {test_name}
Error: {test_error}
"""

        prompt += """
## YOUR TASK
1. Analyze why the internal team's approach failed
2. Propose a NEW approach to fix this issue
3. Provide complete, working code
4. Explain what the previous attempts missed

Focus on what the internal team overlooked. Be specific and provide implementation-ready code.
"""

        return prompt

    def _log_chat_message(
        self,
        cur,
        proposal_id: int,
        sender_type: str,
        content: str,
        message_type: str = "text",
        sender_id: int = None,
        sender_name: str = None,
    ):
        """Log a message to proposal chat."""
        try:
            cur.execute(
                """
                INSERT INTO proposal_chat_messages
                (proposal_id, sender_type, sender_id, sender_name, content, message_type)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    proposal_id,
                    sender_type,
                    sender_id,
                    sender_name or sender_type.title(),
                    content,
                    message_type,
                ),
            )
        except Exception as e:
            logger.warning(f"Could not log chat message: {e}")

    def get_retry_status(self, proposal_id: int) -> Dict:
        """
        Get current retry status for a proposal.

        Returns:
            {
                'proposal_id': int,
                'retry_count': int,
                'max_retries': int,
                'escalation_status': str,
                'contractor': {...} or None,
                'failure_context': {...}
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT
                    ip.id,
                    ip.title,
                    ip.test_retry_count,
                    ip.test_failure_context,
                    ip.escalation_status,
                    ip.contractor_agent_id,
                    ip.escalated_at,
                    a.name as contractor_name,
                    a.api_provider as contractor_provider
                FROM improvement_proposals ip
                LEFT JOIN agents a ON ip.contractor_agent_id = a.id
                WHERE ip.id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                return {"error": "Proposal not found"}

            return {
                "proposal_id": proposal["id"],
                "title": proposal["title"],
                "retry_count": proposal["test_retry_count"] or 0,
                "max_retries": self.MAX_RETRIES,
                "retries_remaining": self.MAX_RETRIES - (proposal["test_retry_count"] or 0),
                "escalation_status": proposal["escalation_status"] or "none",
                "escalated_at": (proposal["escalated_at"].isoformat() if proposal["escalated_at"] else None),
                "contractor": (
                    {
                        "id": proposal["contractor_agent_id"],
                        "name": proposal["contractor_name"],
                        "provider": proposal["contractor_provider"],
                    }
                    if proposal["contractor_agent_id"]
                    else None
                ),
                "failure_context": proposal["test_failure_context"],
            }

        finally:
            cur.close()
            conn.close()

    def reset_retries(self, proposal_id: int) -> Dict:
        """Reset retry count for a proposal (admin action)."""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                UPDATE improvement_proposals
                SET
                    test_retry_count = 0,
                    test_failure_context = NULL,
                    escalation_status = 'none',
                    contractor_agent_id = NULL,
                    contractor_proposal = NULL,
                    escalated_at = NULL
                WHERE id = %s
                RETURNING id
            """,
                (proposal_id,),
            )

            result = cur.fetchone()
            conn.commit()

            if result:
                logger.info(f"Reset retries for proposal #{proposal_id}")
                return {"success": True, "message": "Retries reset"}
            return {"success": False, "error": "Proposal not found"}

        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()


# Singleton instance
_handler_instance = None


def get_retry_handler() -> TestRetryHandler:
    """Get singleton TestRetryHandler instance"""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = TestRetryHandler()
    return _handler_instance


# Convenience functions
def handle_test_failure(proposal_id: int, test_results: Dict) -> Dict:
    """Handle test failure for a proposal"""
    return get_retry_handler().handle_test_failure(proposal_id, test_results)


def get_retry_status(proposal_id: int) -> Dict:
    """Get retry status for a proposal"""
    return get_retry_handler().get_retry_status(proposal_id)


def reset_proposal_retries(proposal_id: int) -> Dict:
    """Reset retries for a proposal"""
    return get_retry_handler().reset_retries(proposal_id)


# CLI testing
if __name__ == "__main__":
    print("Test Retry Handler - Diagnostic Mode")
    print("=" * 60)

    handler = get_retry_handler()

    # Test database connection
    try:
        conn = handler.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) as count FROM improvement_proposals")
        count = cur.fetchone()["count"]
        print(f"✅ Database connected. {count} proposals found.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Database error: {e}")

    print("\nTest Retry Handler ready for use.")
    print(f"Max retries before escalation: {TestRetryHandler.MAX_RETRIES}")
