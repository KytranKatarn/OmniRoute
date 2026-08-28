"""
Mistake Detector - Automatic Error Learning System
Detects repeated errors and creates mistake_learned entries to prevent repetition

Part of Phase 4: Mistake Learning & Prevention
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import logging
import re
import json
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


class MistakeDetector:
    """
    Detects repeated errors and creates mistake_learned entries

    Automatically learns from errors to prevent repetition
    """

    # Common error patterns to detect
    COMMON_PATTERNS = {
        "database_column_missing": {
            "pattern": r'column ["\']([^"\']+)["\'] does not exist',
            "category": "database_schema",
            "severity": "high",
            "solution_template": 'Check the database schema and add missing column "{match}" via migration.',
            "prevention": "Always run migrations before deploying code changes",
            "tags": ["database", "schema", "migration", "postgresql"],
        },
        "database_table_missing": {
            "pattern": r'relation ["\']([^"\']+)["\'] does not exist',
            "category": "database_schema",
            "severity": "high",
            "solution_template": 'Table "{match}" does not exist. Create it via migration or check table name spelling.',
            "prevention": "Verify table names match database schema",
            "tags": ["database", "schema", "migration", "postgresql"],
        },
        "circular_import": {
            "pattern": r"ImportError.*circular import",
            "category": "python_imports",
            "severity": "high",
            "solution_template": "Refactor to avoid circular dependency. Move shared code to a separate module or use lazy imports.",
            "prevention": "Keep module dependencies unidirectional",
            "tags": ["python", "imports", "circular-dependency", "refactoring"],
        },
        "module_not_found": {
            "pattern": r'ModuleNotFoundError: No module named ["\']([^"\']+)["\']',
            "category": "python_imports",
            "severity": "high",
            "solution_template": 'Module "{match}" not installed. Run: pip install {match}',
            "prevention": "Keep requirements.txt updated",
            "tags": ["python", "imports", "dependencies", "pip"],
        },
        "jinja2_syntax_error": {
            "pattern": r"TemplateSyntaxError.*unexpected",
            "category": "template_syntax",
            "severity": "medium",
            "solution_template": "Use Jinja2 syntax: {{ }} for variables, {% %} for statements. Do NOT use ${{}}",
            "prevention": "Follow Jinja2 syntax guidelines",
            "tags": ["jinja2", "templates", "syntax", "flask"],
        },
        "template_not_found": {
            "pattern": r"TemplateNotFound: (.+)",
            "category": "flask_templates",
            "severity": "medium",
            "solution_template": 'Template "{match}" not found. Ensure template path includes correct directory (e.g., tools/template.html)',
            "prevention": "Verify template paths relative to templates/ directory",
            "tags": ["jinja2", "templates", "flask", "paths"],
        },
        "werkzeug_routing_error": {
            "pattern": r'BuildError.*Could not build url for endpoint ["\']([^"\']+)["\']',
            "category": "flask_routing",
            "severity": "medium",
            "solution_template": 'Route endpoint "{match}" does not exist. Check blueprint registration and route definitions.',
            "prevention": "Ensure all blueprints are registered in app.py",
            "tags": ["flask", "routing", "blueprints", "urls"],
        },
        "attribute_error": {
            "pattern": r'AttributeError.*object has no attribute ["\']([^"\']+)["\']',
            "category": "python_attributes",
            "severity": "medium",
            "solution_template": 'Attribute "{match}" does not exist on object. Check spelling or add the attribute.',
            "prevention": "Verify object attributes before accessing",
            "tags": ["python", "attributes", "objects"],
        },
        "key_error": {
            "pattern": r'KeyError: ["\']([^"\']+)["\']',
            "category": "python_dictionaries",
            "severity": "low",
            "solution_template": 'Key "{match}" not found in dictionary. Use .get() or check if key exists first.',
            "prevention": "Use dict.get(key, default) instead of dict[key]",
            "tags": ["python", "dictionaries", "keys"],
        },
        "index_error": {
            "pattern": r"IndexError: list index out of range",
            "category": "python_lists",
            "severity": "low",
            "solution_template": "List index out of range. Check list length before accessing.",
            "prevention": "Verify list length with len() or use try/except",
            "tags": ["python", "lists", "indexing"],
        },
        "type_error": {
            "pattern": r"TypeError: (.+)",
            "category": "python_types",
            "severity": "medium",
            "solution_template": "Type error: {match}. Check data types being used.",
            "prevention": "Verify data types match expected parameters",
            "tags": ["python", "types", "casting"],
        },
        "value_error": {
            "pattern": r"ValueError: (.+)",
            "category": "python_values",
            "severity": "low",
            "solution_template": "Value error: {match}. Check input values.",
            "prevention": "Validate input values before processing",
            "tags": ["python", "values", "validation"],
        },
        "connection_error": {
            "pattern": r"(ConnectionRefusedError|ConnectionError|Timeout)",
            "category": "network_connectivity",
            "severity": "high",
            "solution_template": "Connection error. Check if service is running and network is accessible.",
            "prevention": "Ensure services are running and ports are open",
            "tags": ["network", "connectivity", "services"],
        },
        "permission_denied": {
            "pattern": r"PermissionError.*Permission denied",
            "category": "file_permissions",
            "severity": "medium",
            "solution_template": "Permission denied. Check file/directory permissions or run with appropriate privileges.",
            "prevention": "Set correct file permissions (chmod)",
            "tags": ["permissions", "filesystem", "security"],
        },
    }

    def __init__(self):
        """Initialize mistake detector"""
        self.db = None

    def detect_and_learn(self, error_message: str, context: Dict) -> Optional[Dict]:
        """
        Detect if this is a known error pattern and learn from it

        Args:
            error_message: The error message string
            context: Context dict with route, method, user_id, etc.

        Returns:
            Dict with existing mistake if already learned, or None if new
        """
        for mistake_type, config in self.COMMON_PATTERNS.items():
            match = re.search(config["pattern"], error_message, re.IGNORECASE)

            if match:
                # Extract matched groups (like column name, module name, etc.)
                matched_value = match.group(1) if match.groups() else None

                # Check if we already learned this specific mistake
                existing = self.check_if_learned(mistake_type, matched_value, error_message)

                if existing:
                    # We already know about this mistake!
                    logger.warning(f"[Mistake Detector] ⚠️ REPEATED MISTAKE DETECTED: {mistake_type}")
                    print(f"[Mistake Detector] 📚 Known solution: {existing.get('content', '')[:200]}")
                    return existing

                # New mistake - learn it!
                print(f"[Mistake Detector] 🆕 New mistake detected: {mistake_type}")
                learned = self.create_mistake_entry(
                    mistake_type=mistake_type,
                    error_message=error_message,
                    matched_value=matched_value,
                    context=context,
                    config=config,
                )

                if learned:
                    print(f"[Mistake Detector] ✅ Learned new mistake (ID: {learned.get('id')})")
                    return learned

        return None

    def check_if_learned(self, mistake_type: str, matched_value: Optional[str], error_message: str) -> Optional[Dict]:
        """
        Check if we already learned this specific mistake

        Args:
            mistake_type: Type of mistake (e.g., 'database_column_missing')
            matched_value: Specific value (e.g., column name)
            error_message: Full error message

        Returns:
            Existing mistake dict if found, None otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Search for existing mistake by type and content similarity
            cur.execute(
                """
                SELECT *
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                  AND category = %s
                  AND (
                    content ILIKE %s
                    OR (%s IS NOT NULL AND content ILIKE %s)
                  )
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (
                    self.COMMON_PATTERNS[mistake_type]["category"],
                    f"%{mistake_type}%",
                    matched_value,
                    f"%{matched_value}%" if matched_value else None,
                ),
            )

            result = cur.fetchone()
            cur.close()
            conn.close()

            return dict(result) if result else None

        except Exception as e:
            print(f"[Mistake Detector] Error checking if learned: {e}")
            return None

    def create_mistake_entry(
        self,
        mistake_type: str,
        error_message: str,
        matched_value: Optional[str],
        context: Dict,
        config: Dict,
    ) -> Optional[Dict]:
        """
        Create a new mistake_learned entry in knowledge_base

        Args:
            mistake_type: Type of mistake
            error_message: Full error message
            matched_value: Extracted value from regex match
            context: Error context (route, method, user, etc.)
            config: Pattern configuration

        Returns:
            Created mistake dict with id, or None if failed
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Generate title
            title = f"Common Error: {mistake_type.replace('_', ' ').title()}"
            if matched_value:
                title = f"{title} - {matched_value}"

            # Generate solution from template
            solution = config["solution_template"]
            if matched_value and "{match}" in solution:
                solution = solution.format(match=matched_value)

            # Build content in markdown format
            content = f"# {title}\n\n"
            content += f"## Error Message\n```\n{error_message[:500]}\n```\n\n"
            content += f"## Solution\n{solution}\n\n"
            content += f"## Prevention\n{config['prevention']}\n\n"
            content += f"## Severity\n{config['severity']}\n\n"
            content += f"## Context\n"
            content += json.dumps(
                {
                    "route": context.get("route"),
                    "method": context.get("method"),
                    "detected_at": datetime.now().isoformat(),
                    "matched_value": matched_value,
                },
                indent=2,
            )

            # Insert into knowledge_base
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    source_type,
                    source_id,
                    memory_metadata,
                    created_at,
                    updated_at
                ) VALUES (
                    'mistake_learned',
                    %s,
                    %s,
                    %s,
                    %s,
                    0.95,
                    'mistake_detector',
                    %s,
                    %s,
                    NOW(),
                    NOW()
                )
                RETURNING id, title, content, category, tags
            """,
                (
                    title,
                    content,
                    config["category"],
                    config["tags"],
                    mistake_type,
                    json.dumps(
                        {
                            "pattern": config["pattern"],
                            "severity": config["severity"],
                            "detected_at": datetime.now().isoformat(),
                            "context": context,
                        }
                    ),
                ),
            )

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            return dict(result) if result else None

        except Exception as e:
            print(f"[Mistake Detector] Error creating mistake entry: {e}")
            import traceback

            traceback.print_exc()
            return None

    def get_solution_for_error(self, error_message: str) -> Optional[str]:
        """
        Get known solution for an error message if available

        Args:
            error_message: The error message

        Returns:
            Solution string if found, None otherwise
        """
        for mistake_type, config in self.COMMON_PATTERNS.items():
            match = re.search(config["pattern"], error_message, re.IGNORECASE)

            if match:
                matched_value = match.group(1) if match.groups() else None

                # Check if we learned this before
                existing = self.check_if_learned(mistake_type, matched_value, error_message)

                if existing:
                    # Extract solution from content
                    content = existing.get("content", "")
                    solution_match = re.search(r"## Solution\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
                    if solution_match:
                        return solution_match.group(1).strip()

        return None

    def get_all_mistakes(self, limit: int = 50) -> List[Dict]:
        """
        Get all learned mistakes

        Args:
            limit: Maximum number to return

        Returns:
            List of mistake dicts
        """
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    id,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    created_at,
                    updated_at
                FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                  AND source_type = 'mistake_detector'
                ORDER BY importance_score DESC, created_at DESC
                LIMIT %s
            """,
                (limit,),
            )

            results = cur.fetchall()
            cur.close()
            conn.close()

            return [dict(r) for r in results]

        except Exception as e:
            print(f"[Mistake Detector] Error getting all mistakes: {e}")
            return []


# Singleton instance
_detector = None


def get_mistake_detector() -> MistakeDetector:
    """Get singleton MistakeDetector instance"""
    global _detector
    if _detector is None:
        _detector = MistakeDetector()
    return _detector


# Test function
if __name__ == "__main__":
    print("Testing Mistake Detector...")
    print("=" * 60)

    detector = MistakeDetector()

    # Test 1: Database column missing
    print("\nTest 1: Database Column Missing Error")
    error1 = 'psycopg2.errors.UndefinedColumn: column "weighted_score" does not exist'
    context1 = {"route": "/api/search", "method": "POST", "user_id": 1}

    result1 = detector.detect_and_learn(error1, context1)
    if result1:
        print(f"✅ Detected and learned: {result1['title']}")
    else:
        print("❌ Not detected")

    # Test 2: Template not found
    print("\nTest 2: Template Not Found Error")
    error2 = "jinja2.exceptions.TemplateNotFound: admin_brain.html"
    context2 = {"route": "/admin/brain", "method": "GET", "user_id": 1}

    result2 = detector.detect_and_learn(error2, context2)
    if result2:
        print(f"✅ Detected: {result2['title']}")
    else:
        print("❌ Not detected")

    # Test 3: Circular import
    print("\nTest 3: Circular Import Error")
    error3 = "ImportError: cannot import name X from Y (circular import)"
    context3 = {"route": "module_load", "method": "import", "user_id": None}

    result3 = detector.detect_and_learn(error3, context3)
    if result3:
        print(f"✅ Detected: {result3['title']}")
    else:
        print("❌ Not detected")

    # Show all learned mistakes
    print("\n" + "=" * 60)
    print("All Learned Mistakes:")
    mistakes = detector.get_all_mistakes()
    print(f"Total: {len(mistakes)} mistakes")
    for m in mistakes:
        print(f"  - {m['title']} (Category: {m['category']}, Severity in content)")
