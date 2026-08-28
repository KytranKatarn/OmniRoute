"""
Sandbox AI Integration
Integrates sandbox testing with AI Bridge for intelligent analysis and learning.

Features:
- Analyze test failures using AI
- Suggest fixes based on error patterns
- Store learnings in knowledge_base (mistake_learned type)
- Query existing knowledge for similar issues
"""

import os
from database import _get_db_password
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Database connection
def get_db():
    """Get database connection"""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


class SandboxAIIntegration:
    """AI-powered sandbox analysis and learning system"""

    def __init__(self):
        pass

    def analyze_test_failure(
        self,
        module_id: str,
        test_name: str,
        error_output: str,
        file_path: Optional[str] = None,
        code_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a test failure using AI and return analysis with suggestions.

        Args:
            module_id: The sandbox module that failed
            test_name: Name of the failed test
            error_output: The error message/stack trace
            file_path: Optional file path where error occurred
            code_context: Optional code snippet around the error

        Returns:
            Analysis dict with root_cause, suggested_fix, similar_issues
        """
        logger.info(f"Analyzing test failure in {module_id}: {test_name}")

        # First, check knowledge_base for similar issues
        similar_issues = self._find_similar_issues(error_output, module_id)

        # If we have a strong match, return that
        if similar_issues and similar_issues[0].get("similarity_score", 0) > 0.8:
            logger.info("Found highly similar issue in knowledge base")
            return {
                "success": True,
                "source": "knowledge_base",
                "similar_issue": similar_issues[0],
                "root_cause": similar_issues[0].get("content", ""),
                "suggested_fix": similar_issues[0].get("metadata", {}).get("solution", ""),
                "confidence": "high",
            }

        # Otherwise, use AI to analyze
        ai_analysis = self._ai_analyze_error(
            module_id=module_id,
            test_name=test_name,
            error_output=error_output,
            file_path=file_path,
            code_context=code_context,
            similar_issues=similar_issues,
        )

        return {
            "success": True,
            "source": "ai_analysis",
            "root_cause": ai_analysis.get("root_cause", "Unknown"),
            "suggested_fix": ai_analysis.get("suggested_fix", ""),
            "explanation": ai_analysis.get("explanation", ""),
            "similar_issues": similar_issues[:3] if similar_issues else [],
            "confidence": ai_analysis.get("confidence", "medium"),
        }

    def _find_similar_issues(self, error_output: str, module_id: str) -> List[Dict]:
        """Search knowledge_base for similar errors"""
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Search for mistake_learned entries with similar content
            # Use simple text matching for now
            search_terms = self._extract_search_terms(error_output)

            cur.execute(
                """
                SELECT id, title, content, knowledge_type, importance_score, tags, memory_metadata
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                  AND (
                      content ILIKE ANY(%s)
                      OR title ILIKE ANY(%s)
                      OR %s = ANY(tags)
                  )
                ORDER BY importance_score DESC
                LIMIT 5
            """,
                (
                    [f"%{term}%" for term in search_terms],
                    [f"%{term}%" for term in search_terms],
                    module_id,
                ),
            )

            results = cur.fetchall()

            # Add similarity scores (basic for now)
            for result in results:
                result["similarity_score"] = self._calculate_similarity(error_output, result.get("content", ""))

            # Sort by similarity
            results.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)

            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"Error searching knowledge_base: {e}")
            return []
        finally:
            cur.close()
            conn.close()

    def _extract_search_terms(self, error_output: str) -> List[str]:
        """Extract key search terms from error output"""
        # Common error patterns to look for
        import re

        terms = []

        # Extract error types (e.g., TypeError, ValueError)
        error_types = re.findall(r"(\w+Error|\w+Exception)", error_output)
        terms.extend(error_types[:3])

        # Extract function names
        functions = re.findall(r"in (\w+)\s*\(", error_output)
        terms.extend(functions[:3])

        # Extract file names
        files = re.findall(r"(\w+\.py)", error_output)
        terms.extend(files[:2])

        # Remove duplicates
        return list(set(terms))

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple text similarity score"""
        if not text1 or not text2:
            return 0.0

        # Simple word overlap similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _ai_analyze_error(
        self,
        module_id: str,
        test_name: str,
        error_output: str,
        file_path: Optional[str],
        code_context: Optional[str],
        similar_issues: List[Dict],
    ) -> Dict[str, Any]:
        """Use AI to analyze the error"""
        try:
            # Build context from similar issues
            context_text = ""
            if similar_issues:
                context_text = "\n\nSimilar past issues:\n"
                for issue in similar_issues[:2]:
                    context_text += f"- {issue.get('title', 'Unknown')}: {issue.get('content', '')[:200]}...\n"

            prompt = f"""Analyze this test failure and provide a solution.

Module: {module_id}
Test: {test_name}
File: {file_path or 'Unknown'}

Error Output:
{error_output[:2000]}

{f'Code Context: {code_context[:1000]}' if code_context else ''}
{context_text}

Provide your analysis in the following format:
ROOT CAUSE: [One sentence describing the root cause]
SUGGESTED FIX: [Specific code changes or actions to fix the issue]
EXPLANATION: [Brief explanation of why this fix works]
CONFIDENCE: [high/medium/low]
"""

            from tools.department_hq.services.department_dispatcher import dispatch_json

            result = dispatch_json(
                capability="debug",
                prompt=prompt,
                module_id="repair_bay",
            )
            response = result.get("response", "") if isinstance(result, dict) else str(result)

            # Parse the response
            return self._parse_ai_response(response)

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {
                "root_cause": "Unable to determine (AI analysis failed)",
                "suggested_fix": "Manual review required",
                "explanation": str(e),
                "confidence": "low",
            }

    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """Parse structured AI response"""
        result = {
            "root_cause": "",
            "suggested_fix": "",
            "explanation": "",
            "confidence": "medium",
        }

        lines = response.split("\n")
        current_field = None

        for line in lines:
            line_upper = line.upper().strip()
            if line_upper.startswith("ROOT CAUSE:"):
                current_field = "root_cause"
                result["root_cause"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_upper.startswith("SUGGESTED FIX:"):
                current_field = "suggested_fix"
                result["suggested_fix"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_upper.startswith("EXPLANATION:"):
                current_field = "explanation"
                result["explanation"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif line_upper.startswith("CONFIDENCE:"):
                conf = line.split(":", 1)[1].strip().lower() if ":" in line else "medium"
                result["confidence"] = conf if conf in ["high", "medium", "low"] else "medium"
            elif current_field and line.strip():
                result[current_field] += " " + line.strip()

        return result

    def record_learning(
        self,
        module_id: str,
        error_type: str,
        error_message: str,
        solution: str,
        success: bool,
        file_path: Optional[str] = None,
        proposal_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Record a learning from sandbox testing to knowledge_base.

        Args:
            module_id: The sandbox module
            error_type: Type of error (test_failure, deployment_failure, etc.)
            error_message: The error that occurred
            solution: The fix that was applied
            success: Whether the fix was successful
            file_path: Optional file path involved
            proposal_id: Optional linked proposal ID

        Returns:
            Result dict with created knowledge entry
        """
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Create knowledge entry
            title = f"[{module_id}] {error_type}: {error_message[:50]}"
            content = f"""## Error Analysis

**Module:** {module_id}
**Error Type:** {error_type}
**File:** {file_path or 'N/A'}

### Error Message
{error_message}

### Solution Applied
{solution}

### Outcome
{'Successfully fixed' if success else 'Fix unsuccessful - needs further investigation'}
"""

            metadata = {
                "module_id": module_id,
                "error_type": error_type,
                "solution": solution,
                "success": success,
                "file_path": file_path,
                "proposal_id": proposal_id,
                "recorded_at": datetime.now().isoformat(),
            }

            # Higher importance for unsuccessful fixes (need attention)
            importance = 0.95 if not success else 0.7

            cur.execute(
                """
                INSERT INTO knowledge_base
                (title, content, knowledge_type, importance_score, tags, memory_metadata, source_type, created_at)
                VALUES (%s, %s, 'mistake_learned', %s, %s, %s, 'sandbox', NOW())
                RETURNING id, title, knowledge_type, importance_score
            """,
                (
                    title,
                    content,
                    importance,
                    [module_id, error_type, "sandbox", "auto-learned"],
                    json.dumps(metadata),
                ),
            )

            entry = cur.fetchone()
            conn.commit()

            logger.info(f"Recorded learning: {entry['title']}")

            return {"success": True, "entry": dict(entry)}

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record learning: {e}")
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()

    def get_module_learnings(self, module_id: str, limit: int = 10) -> List[Dict]:
        """Get all learnings for a specific module"""
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT id, title, content, importance_score, tags, memory_metadata, created_at
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                  AND %s = ANY(tags)
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (module_id, limit),
            )

            results = cur.fetchall()
            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"Error fetching learnings: {e}")
            return []
        finally:
            cur.close()
            conn.close()

    def suggest_from_learnings(self, module_id: str, context: str) -> Optional[Dict]:
        """
        Check if there's a relevant learning that might help with current task.

        Args:
            module_id: The module being worked on
            context: Description of current task/issue

        Returns:
            Most relevant learning entry or None
        """
        learnings = self.get_module_learnings(module_id, limit=20)

        if not learnings:
            return None

        # Find most relevant
        best_match = None
        best_score = 0

        for learning in learnings:
            score = self._calculate_similarity(context, learning.get("content", ""))
            if score > best_score:
                best_score = score
                best_match = learning

        if best_score > 0.3:  # Threshold for relevance
            return {"learning": best_match, "relevance_score": best_score}

        return None


# CLI Testing
if __name__ == "__main__":
    integration = SandboxAIIntegration()

    # Test finding similar issues
    print("Testing similar issue search...")
    similar = integration._find_similar_issues("TypeError: cannot unpack non-iterable NoneType object", "platform")
    print(f"Found {len(similar)} similar issues")

    # Test recording a learning
    print("\nTesting learning record...")
    result = integration.record_learning(
        module_id="test",
        error_type="test_failure",
        error_message="Test error for validation",
        solution="This is a test solution",
        success=True,
    )
    print(f"Record result: {result}")

    print("\nSandbox AI Integration ready!")
