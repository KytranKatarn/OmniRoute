"""
Natural Language Code Generator
Converts natural language descriptions into working code

Features:
- Intent classification (create, modify, fix, explain)
- Context-aware code generation
- Multi-language support (Python, JavaScript, SQL, HTML/CSS)
- Template-based scaffolding
- Integration with knowledge base

Author: A.R.C.H.I.E.
Date: 2026-01-19
"""

import os
from database import _get_db_password
import re
from typing import Dict, List, Optional, Tuple

try:
    from tools.department_hq.services.department_dispatcher import dispatch_json as _dispatch_json

    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


class NLCodeGenerator:
    """Natural Language to Code Generator"""

    # Intent patterns for classification
    INTENT_PATTERNS = {
        "create": [
            r"create\s+(?:a\s+)?(.+)",
            r"write\s+(?:a\s+)?(.+)",
            r"make\s+(?:a\s+)?(.+)",
            r"build\s+(?:a\s+)?(.+)",
            r"generate\s+(?:a\s+)?(.+)",
            r"add\s+(?:a\s+)?(.+)",
        ],
        "modify": [
            r"modify\s+(.+)",
            r"change\s+(.+)",
            r"update\s+(.+)",
            r"edit\s+(.+)",
            r"refactor\s+(.+)",
        ],
        "fix": [
            r"fix\s+(.+)",
            r"repair\s+(.+)",
            r"debug\s+(.+)",
            r"solve\s+(.+)",
            r"correct\s+(.+)",
        ],
        "explain": [
            r"explain\s+(.+)",
            r"what\s+(?:does|is)\s+(.+)",
            r"how\s+(?:does|to)\s+(.+)",
            r"describe\s+(.+)",
        ],
        "convert": [r"convert\s+(.+)", r"translate\s+(.+)", r"transform\s+(.+)"],
    }

    # Language detection patterns
    LANGUAGE_PATTERNS = {
        "python": ["python", "flask", "django", "pandas", "numpy", "def ", "class "],
        "javascript": [
            "javascript",
            "js",
            "node",
            "react",
            "vue",
            "express",
            "function ",
        ],
        "sql": [
            "sql",
            "query",
            "select",
            "insert",
            "update",
            "delete",
            "table",
            "database",
        ],
        "html": ["html", "webpage", "page", "website", "template", "div", "form"],
        "css": ["css", "style", "styling", "layout", "flexbox", "grid"],
        "bash": ["bash", "shell", "script", "command", "terminal"],
    }

    # Code templates for common patterns
    TEMPLATES = {
        "flask_route": '''
@{blueprint}.route('/{route_path}', methods=['{method}'])
{decorator}
def {function_name}():
    """
    {description}
    """
    try:
        {body}
        return jsonify({{'success': True, 'data': result}})
    except Exception as e:
        return jsonify({{'success': False, 'error': str(e)}}), 500
''',
        "python_function": '''
def {function_name}({parameters}) -> {return_type}:
    """
    {description}

    Args:
        {args_doc}

    Returns:
        {return_doc}
    """
    {body}
''',
        "python_class": '''
class {class_name}:
    """
    {description}
    """

    def __init__(self{init_params}):
        {init_body}

    {methods}
''',
        "sql_query": """
-- {description}
{query_type} {target}
{clauses}
{conditions}
{ordering};
""",
        "html_component": """
<{tag} class="{classes}" id="{element_id}">
    {content}
</{tag}>
""",
        "javascript_function": """
/**
 * {description}
 * @param {{{param_types}}} {param_names}
 * @returns {{{return_type}}}
 */
{async_keyword}function {function_name}({parameters}) {{
    {body}
}}
""",
    }

    def __init__(self):
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            model = get_dispatcher().get_model_for_capability("code")
            self.model = model or "qwen3-coder-cpu:latest"
        except Exception:
            self.model = "qwen3-coder-cpu:latest"

    def generate(
        self,
        natural_language: str,
        context: Optional[Dict] = None,
        target_language: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict:
        """
        Generate code from natural language description

        Args:
            natural_language: User's description of what they want
            context: Optional context (existing code, file info)
            target_language: Force specific language
            file_path: Target file path for context

        Returns:
            {
                'success': bool,
                'intent': str,
                'language': str,
                'code': str,
                'explanation': str,
                'confidence': float
            }
        """
        if not AI_AVAILABLE:
            return {"success": False, "error": "AI Bridge not available"}

        # Step 1: Classify intent
        intent, intent_confidence = self._classify_intent(natural_language)

        # Step 2: Detect target language
        if not target_language:
            target_language = self._detect_language(natural_language, file_path)

        # Step 3: Extract entities and requirements
        entities = self._extract_entities(natural_language, intent)

        # Step 4: Gather context from knowledge base
        kb_context = self._get_knowledge_context(natural_language, target_language)

        # Step 5: Generate code using AI
        result = self._generate_code(natural_language, intent, target_language, entities, context, kb_context)

        if result.get("success"):
            result["intent"] = intent
            result["language"] = target_language
            result["confidence"] = intent_confidence

            # Save generation for learning
            self._save_generation(natural_language, result)

        return result

    def _classify_intent(self, text: str) -> Tuple[str, float]:
        """Classify user's intent from natural language"""
        text_lower = text.lower()

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return intent, 0.9

        # Default to 'create' with lower confidence
        return "create", 0.6

    def _detect_language(self, text: str, file_path: Optional[str] = None) -> str:
        """Detect target programming language"""

        # Check file extension first
        if file_path:
            ext = os.path.splitext(file_path)[1].lower()
            ext_map = {
                ".py": "python",
                ".js": "javascript",
                ".jsx": "javascript",
                ".ts": "typescript",
                ".tsx": "typescript",
                ".sql": "sql",
                ".html": "html",
                ".css": "css",
                ".sh": "bash",
            }
            if ext in ext_map:
                return ext_map[ext]

        # Check text for language keywords
        text_lower = text.lower()
        scores = {}

        for language, keywords in self.LANGUAGE_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[language] = score

        if scores:
            return max(scores, key=scores.get)

        # Default to Python
        return "python"

    def _extract_entities(self, text: str, intent: str) -> Dict:
        """Extract relevant entities from natural language"""
        entities = {
            "functions": [],
            "classes": [],
            "variables": [],
            "operations": [],
            "data_types": [],
        }

        # Function names (after "called", "named")
        func_match = re.search(r"(?:called|named|function)\s+(\w+)", text, re.I)
        if func_match:
            entities["functions"].append(func_match.group(1))

        # Class names
        class_match = re.search(r"class\s+(\w+)", text, re.I)
        if class_match:
            entities["classes"].append(class_match.group(1))

        # Data types
        types = ["string", "int", "float", "list", "dict", "array", "object", "boolean"]
        for t in types:
            if t in text.lower():
                entities["data_types"].append(t)

        # Operations (CRUD)
        ops = ["create", "read", "update", "delete", "get", "set", "add", "remove"]
        for op in ops:
            if op in text.lower():
                entities["operations"].append(op)

        return entities

    def _get_knowledge_context(self, query: str, language: str) -> str:
        """Get relevant context from knowledge base"""
        if not DB_AVAILABLE:
            return ""

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Search for relevant code snippets and documentation
            cur.execute(
                """
                SELECT title, content, knowledge_type
                FROM knowledge_base
                WHERE search_vector @@ plainto_tsquery('english', %s)
                  AND (
                    knowledge_type IN ('code_snippet', 'vault_note')
                    OR content ILIKE %s
                  )
                ORDER BY importance_score DESC
                LIMIT 3
            """,
                (query, f"%{language}%"),
            )

            results = cur.fetchall()
            cur.close()
            conn.close()

            if results:
                context_parts = []
                for r in results:
                    context_parts.append(f"# {r['title']}\n{r['content'][:500]}")
                return "\n\n".join(context_parts)

        except Exception as e:
            print(f"Knowledge context error: {e}")

        return ""

    def _generate_code(
        self,
        natural_language: str,
        intent: str,
        language: str,
        entities: Dict,
        user_context: Optional[Dict],
        kb_context: str,
    ) -> Dict:
        """Generate code using AI"""

        # Build prompt based on intent
        if intent == "create":
            prompt = self._build_create_prompt(natural_language, language, entities, user_context, kb_context)
        elif intent == "modify":
            prompt = self._build_modify_prompt(natural_language, language, user_context)
        elif intent == "fix":
            prompt = self._build_fix_prompt(natural_language, language, user_context)
        elif intent == "explain":
            prompt = self._build_explain_prompt(natural_language, language, user_context)
        elif intent == "convert":
            prompt = self._build_convert_prompt(natural_language, language, user_context)
        else:
            prompt = self._build_generic_prompt(natural_language, language)

        # Call AI via DHQ dispatcher (ADR-013)
        result = _dispatch_json(
            capability="code",
            prompt=prompt,
            module_id="repair_bay",
        )

        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Code generation failed"),
            }

        # Parse response
        response = result["response"]
        code, explanation = self._parse_response(response, language)

        return {
            "success": True,
            "code": code,
            "explanation": explanation,
            "raw_response": response,
        }

    def _build_create_prompt(
        self,
        nl: str,
        language: str,
        entities: Dict,
        context: Optional[Dict],
        kb_context: str,
    ) -> str:
        """Build prompt for code creation"""

        context_section = ""
        if context:
            if context.get("existing_code"):
                context_section = f"\n\nExisting code context:\n```{language}\n{context['existing_code'][:1000]}\n```"
            if context.get("file_path"):
                context_section += f"\nTarget file: {context['file_path']}"

        kb_section = ""
        if kb_context:
            kb_section = f"\n\nRelevant knowledge from codebase:\n{kb_context}"

        return f"""You are A.R.C.H.I.E., an expert {language} developer.

User Request: {nl}

Generate {language} code that fulfills this request.
{context_section}
{kb_section}

Requirements:
1. Write clean, production-ready code
2. Include appropriate error handling
3. Add docstrings/comments for documentation
4. Follow {language} best practices and conventions
5. If creating a Flask route, use jsonify for responses

Output format:
1. First, provide the code in a code block
2. Then, explain what the code does

```{language}
# Your code here
```

Explanation:
[Brief explanation of what the code does]
"""

    def _build_modify_prompt(self, nl: str, language: str, context: Optional[Dict]) -> str:
        """Build prompt for code modification"""

        existing_code = context.get("existing_code", "") if context else ""

        return f"""You are A.R.C.H.I.E., an expert {language} developer.

User Request: {nl}

Existing code to modify:
```{language}
{existing_code}
```

Modify the code according to the user's request.
Show both the OLD code section and NEW code section.

Output format:
OLD:
```{language}
[Exact section to replace]
```

NEW:
```{language}
[Modified code]
```

Explanation:
[What changed and why]
"""

    def _build_fix_prompt(self, nl: str, language: str, context: Optional[Dict]) -> str:
        """Build prompt for fixing code"""

        existing_code = context.get("existing_code", "") if context else ""
        error_msg = context.get("error", "") if context else ""

        return f"""You are A.R.C.H.I.E., an expert {language} developer and debugger.

User Request: {nl}

Code with issue:
```{language}
{existing_code}
```

{f'Error message: {error_msg}' if error_msg else ''}

Identify the bug and provide the fix.

Output format:
1. Identify the issue
2. Provide the fixed code
3. Explain the fix

Issue: [What's wrong]

Fixed code:
```{language}
[Corrected code]
```

Explanation: [Why this fix works]
"""

    def _build_explain_prompt(self, nl: str, language: str, context: Optional[Dict]) -> str:
        """Build prompt for code explanation"""

        existing_code = context.get("existing_code", "") if context else ""

        return f"""You are A.R.C.H.I.E., an expert {language} developer and teacher.

User Request: {nl}

Code to explain:
```{language}
{existing_code}
```

Provide a clear, detailed explanation of this code.

Explanation format:
1. **Overview**: What this code does overall
2. **Step by step**: Walk through the logic
3. **Key concepts**: Important patterns or techniques used
4. **Potential improvements**: Suggestions for better code
"""

    def _build_convert_prompt(self, nl: str, language: str, context: Optional[Dict]) -> str:
        """Build prompt for code conversion"""

        existing_code = context.get("existing_code", "") if context else ""
        source_lang = context.get("source_language", "unknown") if context else "unknown"

        return f"""You are A.R.C.H.I.E., an expert polyglot developer.

User Request: {nl}

Original code ({source_lang}):
```{source_lang}
{existing_code}
```

Convert this to {language}, maintaining the same functionality.

Output:
```{language}
[Converted code]
```

Notes:
[Any important differences or considerations]
"""

    def _build_generic_prompt(self, nl: str, language: str) -> str:
        """Build generic prompt"""

        return f"""You are A.R.C.H.I.E., an expert {language} developer.

User Request: {nl}

Provide helpful {language} code that addresses this request.

```{language}
# Your code here
```

Explanation:
[What the code does]
"""

    def _parse_response(self, response: str, language: str) -> Tuple[str, str]:
        """Parse AI response to extract code and explanation"""

        # Find code blocks
        code_pattern = rf"```(?:{language})?\n?(.*?)```"
        code_matches = re.findall(code_pattern, response, re.DOTALL | re.IGNORECASE)

        code = code_matches[0].strip() if code_matches else ""

        # Extract explanation (text after last code block)
        explanation = ""
        if "```" in response:
            parts = response.split("```")
            if len(parts) > 2:
                last_part = parts[-1].strip()
                # Remove common prefixes
                for prefix in ["Explanation:", "Notes:", "Summary:"]:
                    if last_part.startswith(prefix):
                        last_part = last_part[len(prefix) :].strip()
                explanation = last_part

        return code, explanation

    def _save_generation(self, prompt: str, result: Dict):
        """Save successful generation for learning"""
        if not DB_AVAILABLE:
            return

        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nl_code_generations (
                    id SERIAL PRIMARY KEY,
                    prompt TEXT,
                    intent VARCHAR(50),
                    language VARCHAR(50),
                    generated_code TEXT,
                    explanation TEXT,
                    confidence FLOAT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """
            )

            cur.execute(
                """
                INSERT INTO nl_code_generations
                (prompt, intent, language, generated_code, explanation, confidence)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    prompt,
                    result.get("intent"),
                    result.get("language"),
                    result.get("code"),
                    result.get("explanation"),
                    result.get("confidence"),
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            print(f"Save generation error: {e}")


# Convenience function
def generate_code_from_nl(
    description: str,
    context: Optional[Dict] = None,
    language: Optional[str] = None,
    file_path: Optional[str] = None,
) -> Dict:
    """
    Generate code from natural language description

    Args:
        description: Natural language description of what to create/do
        context: Optional dict with existing_code, error, etc.
        language: Force specific programming language
        file_path: Target file path for context

    Returns:
        Dict with success, code, explanation, etc.

    Example:
        result = generate_code_from_nl(
            "Create a Flask route that returns all users from the database",
            language="python"
        )
    """
    generator = NLCodeGenerator()
    return generator.generate(description, context, language, file_path)


# Quick templates
def create_flask_route(
    route_path: str,
    method: str = "GET",
    description: str = "",
    requires_auth: bool = True,
) -> str:
    """Generate a Flask route template"""

    decorator = "@login_required" if requires_auth else ""
    function_name = route_path.replace("/", "_").replace("-", "_").strip("_")
    if not function_name:
        function_name = "index"

    body = 'result = {"message": "Hello from A.R.C.H.I.E."}'

    return f'''
@bp.route('/{route_path}', methods=['{method}'])
{decorator}
def {function_name}():
    """
    {description or f'{method} /{route_path}'}
    """
    try:
        {body}
        return jsonify({{'success': True, 'data': result}})
    except Exception as e:
        return jsonify({{'success': False, 'error': str(e)}}), 500
'''


def create_python_function(
    name: str,
    params: List[str] = None,
    return_type: str = "None",
    description: str = "",
) -> str:
    """Generate a Python function template"""

    params = params or []
    param_str = ", ".join(params) if params else ""
    args_doc = "\n        ".join([f"{p}: Description" for p in params]) if params else "None"

    return f'''
def {name}({param_str}) -> {return_type}:
    """
    {description}

    Args:
        {args_doc}

    Returns:
        {return_type}: Description
    """
    # TODO: Implement
    pass
'''


if __name__ == "__main__":
    print("=" * 60)
    print("Natural Language Code Generator - Test")
    print("=" * 60)

    # Test generation
    result = generate_code_from_nl("Create a function that calculates the factorial of a number", language="python")

    print(f"\nSuccess: {result.get('success')}")
    print(f"Intent: {result.get('intent')}")
    print(f"Language: {result.get('language')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"\nGenerated Code:\n{result.get('code', 'N/A')}")
    print(f"\nExplanation:\n{result.get('explanation', 'N/A')}")
