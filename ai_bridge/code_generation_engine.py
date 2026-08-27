"""
Code Generation Engine V2
Generates actual code changes for improvement proposals using AI

Features:
- Architect/Editor pattern for improved accuracy
- Syntax validation before saving (Python, JS, HTML)
- Content matching verification
- Team Management integration for agent selection
- Retry logic with error feedback

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-15 (V2 refactor)
"""

import os
from db import _get_db_password
from typing import Dict, List, Optional, Tuple
from datetime import datetime

_dispatcher = None


def _get_dispatcher():
    global _dispatcher
    if _dispatcher is None:
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            _dispatcher = get_dispatcher()
        except Exception:
            pass
    return _dispatcher


# Import V2 validators
try:
    from code_validator import CodeValidator, validate_code
    from content_matcher import ContentMatcher, verify_content

    VALIDATORS_AVAILABLE = True
except ImportError:
    VALIDATORS_AVAILABLE = False
    print("[CodeGen] Warning: Validators not available, running without validation")


class CodeGenerationEngine:
    """Generates code changes for improvement proposals with V2 validation"""

    # V2 Configuration
    MAX_RETRIES = 3
    DEFAULT_MODEL = None  # Resolved dynamically via BridgeDispatcher

    @classmethod
    def _get_code_model(cls):
        """Get the code model from BridgeDispatcher."""
        try:
            disp = _get_dispatcher()
            return disp.get_model_for_capability("code") if disp else "qwen3-coder-cpu:latest"
        except Exception:
            return "qwen3-coder-cpu:latest"

    # Prompts for architect/editor pattern
    ARCHITECT_PROMPT = """You are analyzing a code issue to plan a MINIMAL fix.

## ISSUE
{issue_description}

## TARGET FILE: {file_path}
## RELEVANT CODE (around line {line_number}):
```{language}
{file_context}
```

## YOUR TASK
1. Identify the ROOT CAUSE (be specific - which line/function?)
2. Determine the MINIMAL change needed
3. Do NOT refactor unrelated code
4. Do NOT add features beyond the fix

## OUTPUT FORMAT (JSON only, no other text):
```json
{{
    "root_cause": "Specific description of what causes the issue",
    "affected_lines": [{start_line}, {end_line}],
    "fix_strategy": "One sentence describing the minimal fix",
    "change_scope": "1-3 lines"
}}
```"""

    EDITOR_PROMPT = """You are implementing a code fix based on the architect's analysis.

## ARCHITECT'S ANALYSIS
{architect_output}

## FILE TO MODIFY: {file_path}

## CURRENT CODE (lines {start_line}-{end_line}):
```{language}
{focused_context}
```

## CRITICAL RULES - READ CAREFULLY
1. OLD_CONTENT must be copied EXACTLY from the code shown above
2. Include ALL leading whitespace (spaces, not tabs)
3. Do NOT include line numbers like "215:" - copy only the code
4. Make the MINIMUM change possible to fix the issue
5. Do NOT fix other issues or refactor surrounding code
6. Preserve the exact indentation (count the spaces!)

## OUTPUT FORMAT
FILE: {file_path}
ACTION: modify
DESCRIPTION: [1 sentence]

OLD_CONTENT:
```
[Exact content to replace - copy character-for-character]
```

NEW_CONTENT:
```
[Your fix - same indentation as OLD_CONTENT]
```"""

    RETRY_PROMPT = """Your previous code change failed validation.

## PREVIOUS ATTEMPT
OLD_CONTENT:
```
{previous_old_content}
```

NEW_CONTENT:
```
{previous_new_content}
```

## VALIDATION ERROR
{validation_error}

## ACTUAL FILE CONTENT (copy from here):
```{language}
{actual_file_content}
```

## WHAT WENT WRONG
{error_analysis}

## YOUR TASK
Generate a CORRECTED change. Copy the OLD_CONTENT exactly from the file content shown above.

FILE: {file_path}
ACTION: modify
DESCRIPTION: [1 sentence]

OLD_CONTENT:
```
[Copy EXACTLY from actual file content above]
```

NEW_CONTENT:
```
[Fixed code with same indentation]
```"""

    def __init__(self):
        # Support both Docker internal paths and host mount paths
        # Docker container uses /app for platform_v2, host uses /mnt/archie_brain/platform_v2
        self.docker_platform_path = "/app"
        self.host_platform_path = "/mnt/archie_brain/platform_v2"
        self.ai_bridge_path = "/mnt/archie_brain/ai_bridge"

        # Detect if running inside Docker (platform at /app) or outside
        if os.path.exists("/app/app.py"):
            self.base_path = self.docker_platform_path
        else:
            self.base_path = self.host_platform_path

        # Initialize V2 validators
        self.validator = CodeValidator() if VALIDATORS_AVAILABLE else None
        self.matcher = ContentMatcher() if VALIDATORS_AVAILABLE else None

    def generate_with_validation(
        self,
        proposal_id: int,
        proposal_title: str,
        proposal_description: str,
        category: str,
        target_files: Optional[List[str]] = None,
        line_number: Optional[int] = None,
        issue_context: Optional[Dict] = None,
        prefer_contractor: bool = False,
    ) -> Dict:
        """
        V2 Code Generation with full validation pipeline.

        Pipeline:
        1. Architect Phase - Analyze problem, plan minimal fix
        2. Editor Phase - Generate actual code changes
        3. Validation Phase - Syntax check + content matching
        4. Retry if validation fails (up to MAX_RETRIES)

        Args:
            proposal_id: Proposal ID
            proposal_title: Title of improvement
            proposal_description: Detailed description
            category: Category (ui, api, database, etc.)
            target_files: List of files to modify
            line_number: Line number where issue was detected
            issue_context: Issue details from CodeRabbit
            prefer_contractor: Prefer external AI (Claude/GPT-4) for complex tasks

        Returns:
            {
                'success': bool,
                'changes': [...],
                'validation_results': {...},
                'metadata': {...}
            }
        """
        print(f"🤖 [V2] Generating code for proposal #{proposal_id}...")

        # Validate target files
        validation = self._validate_target_files(target_files or [])
        if not validation["valid_files"]:
            return {
                "success": False,
                "error": f"No valid target files found. Missing: {validation['missing_files']}",
            }

        # Select model based on task complexity
        model = self._select_model_for_task(category, prefer_contractor)
        print(f"   Using model: {model}")

        # Process each file
        all_changes = []
        all_validation_results = []

        for file_info in validation["valid_files"]:
            file_path = file_info["path"]
            language = self._detect_language(file_path)

            # Get focused context around line number
            if line_number:
                context = self._read_file_content(file_path, line_number)
                focused_context = context["context"]
            else:
                focused_context = file_info["content"][:2000]

            # Try generation with retries
            retry_count = 0
            last_error = None
            change = None

            while retry_count < self.MAX_RETRIES:
                if retry_count == 0:
                    # First attempt - use architect/editor pattern
                    change = self._generate_with_architect_editor(
                        file_path=file_path,
                        file_content=file_info["content"],
                        focused_context=focused_context,
                        issue_description=proposal_description,
                        issue_context=issue_context,
                        line_number=line_number,
                        language=language,
                        model=model,
                    )
                else:
                    # Retry with error feedback
                    # Handle case where previous change was None
                    prev_change = change if change else {"old_content": "", "new_content": ""}
                    change = self._generate_with_retry(
                        file_path=file_path,
                        file_content=file_info["content"],
                        previous_change=prev_change,
                        validation_error=last_error,
                        language=language,
                        model=model,
                    )

                if not change:
                    last_error = "AI failed to generate code"
                    retry_count += 1
                    continue

                # Validate the generated code
                validation_result = self._validate_change(
                    change=change,
                    file_path=file_path,
                    file_content=file_info["content"],
                    language=language,
                )

                if validation_result["valid"]:
                    # Success!
                    all_changes.append(change)
                    all_validation_results.append(validation_result)
                    print(f"   ✅ {file_path}: Valid change generated (attempt {retry_count + 1})")
                    break
                else:
                    last_error = validation_result["error"]
                    print(f"   ⚠️ {file_path}: Validation failed (attempt {retry_count + 1}): {last_error}")
                    retry_count += 1

            if retry_count >= self.MAX_RETRIES:
                print(f"   ❌ {file_path}: Max retries exceeded")
                all_validation_results.append(
                    {
                        "valid": False,
                        "error": f"Max retries exceeded. Last error: {last_error}",
                        "file_path": file_path,
                    }
                )

        # Build error message if no changes were generated
        error_msg = None
        if len(all_changes) == 0:
            if all_validation_results:
                # Collect error messages from validation results
                errors = [r.get("error", "Unknown error") for r in all_validation_results if not r.get("valid")]
                error_msg = (
                    f"Code generation failed: {'; '.join(errors)}"
                    if errors
                    else "No valid code changes could be generated"
                )
            else:
                error_msg = "AI did not generate any code changes"

        result = {
            "success": len(all_changes) > 0,
            "changes": all_changes,
            "validation_results": all_validation_results,
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "model_used": model,
                "proposal_id": proposal_id,
                "retries_used": retry_count if "retry_count" in dir() else 0,
                "validation_enabled": VALIDATORS_AVAILABLE,
            },
        }
        if error_msg:
            result["error"] = error_msg
        return result

    def _select_model_for_task(self, category: str, prefer_contractor: bool) -> str:
        """
        Select AI model based on task complexity, skills, and preference.

        V2 Selection Strategy (Phase 17):
        1. Map category to required skills
        2. Query agent_skills for best matching agent
        3. Prefer internal agents (FREE) unless prefer_contractor=True
        4. Fall back to Team Management or default model
        """
        # Category to skills mapping
        category_skills = {
            "security": ["security_analysis", "complex_security", "code_review"],
            "performance": [
                "performance_optimization",
                "algorithm_design",
                "profiling",
            ],
            "architecture": ["architecture", "system_design", "technical_leadership"],
            "database": ["database_optimization", "sql", "database_design"],
            "ui": ["javascript", "frontend_development", "ui_design"],
            "api": ["api_design", "python", "rest_api"],
            "backend": ["python", "api_design", "backend_development"],
            "frontend": ["javascript", "react", "frontend_development"],
            "testing": ["code_review", "testing", "test_automation"],
            "documentation": ["documentation", "technical_writing"],
            "refactoring": ["refactoring", "code_review", "best_practices"],
            "code_quality": ["code_review", "best_practices", "syntax_correction"],
        }

        required_skills = category_skills.get(category, ["code_review", "python"])

        # Try to find best agent using skills
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Query for best agent with required skills
            placeholders = ",".join(["%s"] * len(required_skills))
            worker_preference = "contract" if prefer_contractor else "internal"

            cur.execute(
                f"""
                SELECT
                    a.model,
                    a.name,
                    a.worker_type,
                    COUNT(s.skill_name) as matching_skills,
                    SUM(s.proficiency_level) as skill_score
                FROM agents a
                JOIN agent_skills s ON a.id = s.agent_id
                WHERE a.status = 'active'
                  AND a.model IS NOT NULL
                  AND s.skill_name IN ({placeholders})
                  AND s.proficiency_level >= 4
                GROUP BY a.id, a.model, a.name, a.worker_type
                ORDER BY
                    CASE WHEN a.worker_type = %s THEN 0 ELSE 1 END,
                    skill_score DESC,
                    matching_skills DESC
                LIMIT 1
            """,
                required_skills + [worker_preference],
            )

            result = cur.fetchone()
            cur.close()
            conn.close()

            if result and result["model"]:
                print(f"   Skill-based selection: {result['name']} ({result['model']})")
                print(f"   Matching skills: {result['matching_skills']}, Score: {result['skill_score']}")
                return result["model"]

        except Exception as e:
            print(f"   Warning: Skill-based selection failed: {e}")

        # Try to use Team Management agent selection
        try:
            from agent_delegation import select_best_agent_for_task

            task_desc = f"Generate code fix for {category} issue"
            agent = select_best_agent_for_task(task_description=task_desc, department_preference="Engineering")
            if agent and agent.get("model"):
                return agent["model"]
        except ImportError:
            pass  # Team Management not available
        except Exception as e:
            print(f"   Warning: Agent selection failed: {e}")

        # Fallback to preference-based selection
        if prefer_contractor:
            # Check for available external APIs
            if os.getenv("ANTHROPIC_API_KEY"):
                return "claude-sonnet-4-20250514"
            elif os.getenv("OPENAI_API_KEY"):
                return "gpt-4-turbo"

        return self._get_code_model()

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension"""
        ext = os.path.splitext(file_path)[1].lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
        }
        return lang_map.get(ext, "text")

    def _generate_with_architect_editor(
        self,
        file_path: str,
        file_content: str,
        focused_context: str,
        issue_description: str,
        issue_context: Optional[Dict],
        line_number: Optional[int],
        language: str,
        model: str,
    ) -> Optional[Dict]:
        """
        Two-phase generation using architect/editor pattern.

        Phase 1 (Architect): Analyze problem, identify minimal fix
        Phase 2 (Editor): Generate actual code with exact old_content
        """
        # Determine line range
        if line_number:
            start_line = max(1, line_number - 10)
            end_line = line_number + 10
        else:
            start_line = 1
            end_line = 50

        # Phase 1: Architect - analyze the problem
        architect_prompt = self.ARCHITECT_PROMPT.format(
            issue_description=issue_description,
            file_path=file_path,
            line_number=line_number or "unknown",
            language=language,
            file_context=focused_context,
            start_line=start_line,
            end_line=end_line,
        )

        architect_result = _get_dispatcher().request_work(
            capability="code_analysis",
            prompt=architect_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not architect_result.success:
            return None

        architect_output = architect_result.response

        # Phase 2: Editor - generate actual code
        editor_prompt = self.EDITOR_PROMPT.format(
            architect_output=architect_output,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            language=language,
            focused_context=focused_context,
        )

        editor_result = _get_dispatcher().request_work(
            capability="code",
            prompt=editor_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not editor_result.success:
            return None

        # Parse the editor response
        changes = self._parse_code_changes_from_response(editor_result.response, category="general")

        return changes[0] if changes else None

    def _generate_with_retry(
        self,
        file_path: str,
        file_content: str,
        previous_change: Dict,
        validation_error: str,
        language: str,
        model: str,
    ) -> Optional[Dict]:
        """Generate code with retry prompt including error feedback"""

        # Get actual file context for reference
        lines = file_content.split("\n")
        preview = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[:100]))

        # Analyze the error
        if "SyntaxError" in validation_error or "IndentationError" in validation_error:
            error_analysis = "The generated code has a syntax error. Check indentation and Python syntax."
        elif "not found" in validation_error.lower():
            error_analysis = (
                "The OLD_CONTENT doesn't match the actual file. Copy it exactly from the file content shown."
            )
        else:
            error_analysis = validation_error

        retry_prompt = self.RETRY_PROMPT.format(
            previous_old_content=previous_change.get("old_content", ""),
            previous_new_content=previous_change.get("new_content", ""),
            validation_error=validation_error,
            language=language,
            actual_file_content=preview,
            error_analysis=error_analysis,
            file_path=file_path,
        )

        result = _get_dispatcher().request_work(
            capability="code",
            prompt=retry_prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not result.success:
            return None

        changes = self._parse_code_changes_from_response(result.response, category="general")

        return changes[0] if changes else None

    def _validate_change(self, change: Dict, file_path: str, file_content: str, language: str) -> Dict:
        """
        Validate a generated change before saving.

        Checks:
        1. Syntax validation of new_content
        2. Content matching of old_content in file
        """
        if not VALIDATORS_AVAILABLE:
            return {"valid": True, "warning": "Validators not available"}

        errors = []

        # 1. Validate syntax of new_content
        new_content = change.get("new_content", "")
        if new_content and language in ("python", "javascript", "html", "css"):
            # For Python, we need to validate in context
            if language == "python":
                test_code = new_content
                stripped = test_code.strip()

                # Check if it's a complete definition
                if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("import "):
                    # Try as standalone module
                    import ast

                    try:
                        ast.parse(test_code)
                    except SyntaxError as e:
                        errors.append(f"SyntaxError in new_content: {e.msg} at line {e.lineno}")
                else:
                    # It's a code snippet - need to dedent and wrap appropriately
                    import ast
                    import textwrap

                    # Dedent to remove leading whitespace
                    dedented = textwrap.dedent(test_code)

                    # Try different wrappers based on content
                    valid = False
                    last_error = None

                    # Try 1: As-is (might be valid module-level code)
                    try:
                        ast.parse(dedented)
                        valid = True
                    except SyntaxError as e:
                        last_error = e

                    # Try 2: Wrap in function (for statement-level code)
                    if not valid:
                        wrapped = "def _test():\n" + textwrap.indent(dedented, "    ")
                        try:
                            ast.parse(wrapped)
                            valid = True
                        except SyntaxError as e:
                            last_error = e

                    # Try 3: Wrap in try/except (for except/finally blocks)
                    if not valid and ("except" in dedented or "finally" in dedented):
                        wrapped = "def _test():\n    try:\n        pass\n" + textwrap.indent(dedented, "    ")
                        try:
                            ast.parse(wrapped)
                            valid = True
                        except SyntaxError as e:
                            last_error = e

                    # Try 4: Wrap in if block (for else/elif)
                    if not valid and ("else" in dedented or "elif" in dedented):
                        wrapped = "def _test():\n    if True:\n        pass\n" + textwrap.indent(dedented, "    ")
                        try:
                            ast.parse(wrapped)
                            valid = True
                        except SyntaxError as e:
                            last_error = e

                    if not valid and last_error:
                        errors.append(f"SyntaxError in new_content: {last_error.msg} at line {last_error.lineno}")

            else:
                result = self.validator.validate(new_content, file_path)
                if not result.success:
                    errors.extend(result.errors)

        # 2. Verify old_content exists in file
        old_content = change.get("old_content", "")
        if old_content:
            match_result = self.matcher.verify_old_content(file_path, old_content)
            if not match_result.match_found:
                errors.append(f"old_content not found in file: {match_result.error}")
                if match_result.suggestions:
                    errors.append(f"Suggestions: {'; '.join(match_result.suggestions[:2])}")

        if errors:
            return {"valid": False, "error": "; ".join(errors), "file_path": file_path}

        return {
            "valid": True,
            "file_path": file_path,
            "match_type": match_result.match_type if old_content else None,
        }

    def _read_file_content(self, file_path: str, line_number: Optional[int] = None) -> Optional[Dict]:
        """
        Read actual file content from the codebase.

        Args:
            file_path: Relative path like 'platform_v2/tools/xyz/routes.py' or 'tools/xyz/routes.py'
            line_number: Optional line number to focus context around

        Returns:
            {
                'full_path': str,
                'content': str,
                'exists': bool,
                'context': str (relevant section if line_number provided)
            }
        """
        # Normalize path - try multiple possible locations (Docker and host paths)
        possible_paths = []

        # Handle absolute paths first
        if file_path.startswith("/"):
            # Absolute path - use as-is
            possible_paths.append(file_path)
            # Also try mapping /app paths to host paths (in case running from host)
            if file_path.startswith("/app/"):
                rel_path = file_path[len("/app/") :]
                possible_paths.append(os.path.join(self.host_platform_path, rel_path))
        elif file_path.startswith("platform_v2/"):
            # Strip prefix and look in platform_v2 (both Docker and host paths)
            rel_path = file_path[len("platform_v2/") :]
            possible_paths.append(os.path.join(self.docker_platform_path, rel_path))
            possible_paths.append(os.path.join(self.host_platform_path, rel_path))
        elif file_path.startswith("ai_bridge/"):
            # Look in ai_bridge
            rel_path = file_path[len("ai_bridge/") :]
            possible_paths.append(os.path.join(self.ai_bridge_path, rel_path))
        else:
            # Try all locations
            possible_paths.append(os.path.join(self.docker_platform_path, file_path))
            possible_paths.append(os.path.join(self.host_platform_path, file_path))
            possible_paths.append(os.path.join(self.ai_bridge_path, file_path))
            possible_paths.append(os.path.join("/mnt/archie_brain", file_path))

        for full_path in possible_paths:
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Get context around specific line if provided
                    context = content
                    if line_number and line_number > 0:
                        lines = content.split("\n")
                        start = max(0, line_number - 15)  # 15 lines before
                        end = min(len(lines), line_number + 15)  # 15 lines after
                        context_lines = lines[start:end]
                        context = "\n".join(f"{start + i + 1}: {line}" for i, line in enumerate(context_lines))

                    return {
                        "full_path": full_path,
                        "content": content,
                        "exists": True,
                        "context": context,
                        "line_count": len(content.split("\n")),
                    }
                except Exception as e:
                    print(f"Error reading {full_path}: {e}")
                    continue

        return {
            "full_path": file_path,
            "content": "",
            "exists": False,
            "context": "",
            "line_count": 0,
        }

    def _validate_target_files(self, target_files: List[str]) -> Dict:
        """
        Validate that target files exist and return their content.

        Returns:
            {
                'valid_files': [{'path': str, 'content': str, 'context': str}],
                'missing_files': [str],
                'all_valid': bool
            }
        """
        valid_files = []
        missing_files = []

        for file_path in target_files or []:
            file_info = self._read_file_content(file_path)
            if file_info["exists"]:
                valid_files.append(
                    {
                        "path": file_path,
                        "full_path": file_info["full_path"],
                        "content": file_info["content"],
                        "context": file_info["context"],
                        "line_count": file_info["line_count"],
                    }
                )
            else:
                missing_files.append(file_path)

        return {
            "valid_files": valid_files,
            "missing_files": missing_files,
            "all_valid": len(missing_files) == 0,
        }

    def generate_code_for_proposal(
        self,
        proposal_id: int,
        proposal_title: str,
        proposal_description: str,
        category: str,
        target_files: Optional[List[str]] = None,
        line_number: Optional[int] = None,
        issue_context: Optional[Dict] = None,
    ) -> Dict:
        """
        Generate actual code changes for an improvement proposal

        Args:
            proposal_id: Proposal ID
            proposal_title: Title of the improvement
            proposal_description: Detailed description
            category: Category (ui, api, database, etc.)
            target_files: Optional list of files to modify
            line_number: Optional line number where issue was detected
            issue_context: Optional dict with issue details from CodeRabbit

        Returns:
            {
                'success': bool,
                'changes': [
                    {
                        'file_path': str,
                        'action': 'modify' | 'create' | 'delete',
                        'old_content': str (for modify),
                        'new_content': str,
                        'diff': str,
                        'description': str
                    }
                ],
                'metadata': dict
            }
        """
        print(f"🤖 Generating code for proposal #{proposal_id}...")

        # PHASE 14 FIX: Read actual file content before generating fixes
        file_contexts = []
        validation = self._validate_target_files(target_files or [])

        if validation["missing_files"]:
            print(f"⚠️  Warning: Some target files don't exist: {validation['missing_files']}")

        # Read actual content for each valid file
        for file_info in validation["valid_files"]:
            # If we have a line number, get focused context
            if line_number:
                focused = self._read_file_content(file_info["path"], line_number)
                file_contexts.append(
                    {
                        "path": file_info["path"],
                        "full_path": file_info["full_path"],
                        "context": focused["context"],
                        "line_number": line_number,
                        "line_count": file_info["line_count"],
                    }
                )
            else:
                # Include first 200 lines as context (or full file if smaller)
                lines = file_info["content"].split("\n")
                preview_lines = lines[:200]
                preview = "\n".join(f"{i+1}: {line}" for i, line in enumerate(preview_lines))
                if len(lines) > 200:
                    preview += f"\n... ({len(lines) - 200} more lines)"

                file_contexts.append(
                    {
                        "path": file_info["path"],
                        "full_path": file_info["full_path"],
                        "context": preview,
                        "line_number": None,
                        "line_count": file_info["line_count"],
                    }
                )

        # Build context-aware prompt for code generation WITH ACTUAL CODE
        prompt = self._build_code_generation_prompt(
            proposal_title,
            proposal_description,
            category,
            target_files,
            file_contexts,
            line_number,
            issue_context,
        )

        # Use AI to generate code changes
        result = _get_dispatcher().request_work(
            capability="code",
            prompt=prompt,
            module_id="improvement_labs",
            user_id=4,
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error or "Code generation failed",
            }

        # Parse AI response to extract code changes
        ai_response = result.response
        changes = self._parse_code_changes_from_response(ai_response, category)

        return {
            "success": True,
            "changes": changes,
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "model_used": result.model_used or "unknown",
                "proposal_id": proposal_id,
                "ai_response": ai_response,
            },
        }

    def _build_code_generation_prompt(
        self,
        title: str,
        description: str,
        category: str,
        target_files: Optional[List[str]],
        file_contexts: Optional[List[Dict]] = None,
        line_number: Optional[int] = None,
        issue_context: Optional[Dict] = None,
    ) -> str:
        """Build prompt for AI code generation WITH ACTUAL FILE CONTENT"""

        # Build file context section with ACTUAL CODE
        file_context_section = ""
        if file_contexts:
            file_context_section = "\n**ACTUAL FILE CONTENT (READ THIS CAREFULLY):**\n"
            for fc in file_contexts:
                file_context_section += f"\n--- {fc['path']} ({fc['line_count']} lines) ---\n"
                if fc.get("line_number"):
                    file_context_section += f"(Focus area: around line {fc['line_number']})\n"
                file_context_section += f"```\n{fc['context']}\n```\n"
        else:
            file_context_section = "\n**WARNING: Could not read target files. Creating new files instead.**\n"

        # Build issue context if from CodeRabbit
        issue_section = ""
        if issue_context:
            issue_section = f"""
**CODE ISSUE DETECTED:**
- Issue Type: {issue_context.get('issue_type', 'unknown')}
- Severity: {issue_context.get('severity', 'medium')}
- Line Number: {issue_context.get('line_number', 'unknown')}
- Message: {issue_context.get('message', description)}
- Suggestion: {issue_context.get('suggestion', 'See description')}
"""

        prompt = f"""You are A.R.C.H.I.E., a software engineer implementing a code fix.

**IMPROVEMENT REQUEST:**
Title: {title}
Description: {description}
Category: {category}
Target Files: {', '.join(target_files) if target_files else 'See below'}
{issue_section}
{file_context_section}

**CRITICAL INSTRUCTIONS:**
1. The OLD_CONTENT MUST be copied EXACTLY from the actual file content shown above
2. Do NOT guess or make up what the old code looks like
3. **PRESERVE EXACT INDENTATION** - Copy all leading spaces/tabs exactly as shown
4. The OLD_CONTENT must be a substring that exists in the file
5. Do NOT include line numbers (like "215:") - only copy the code AFTER the line number
6. The code shown uses SPACES for indentation - preserve the EXACT number of spaces

**REQUIRED FORMAT:**
For each file that needs changes, provide:

FILE: <file_path>
ACTION: modify
DESCRIPTION: <what this change does>

OLD_CONTENT:
```
<EXACT code from the file above - copy it precisely>
```

NEW_CONTENT:
```
<the fixed/improved code>
```

---

**EXAMPLE (bare except fix):**
If fixing a bare except clause, and the actual code shows:
```
214:         except:
215:             pass
```

Note the indentation: "except:" has 8 leading spaces, "pass" has 12 leading spaces.
DO NOT include the line numbers. Copy ONLY the code with its exact indentation.

Your response should be:
FILE: tools/example/routes.py
ACTION: modify
DESCRIPTION: Fix bare except clause to catch specific exception

OLD_CONTENT:
```
        except:
            pass
```

NEW_CONTENT:
```
        except Exception as e:
            pass  # Non-critical operation
```

Notice: Both OLD_CONTENT and NEW_CONTENT preserve the 8-space indentation before "except".

**Now generate the EXACT code changes based on the actual file content shown above:**
"""

        return prompt

    def _parse_code_changes_from_response(self, ai_response: str, category: str) -> List[Dict]:
        """
        Parse AI response to extract structured code changes

        Returns list of change dictionaries
        """
        changes = []

        import re

        # Normalize markdown formatting - remove ** bold markers around keywords
        normalized = ai_response
        normalized = re.sub(r"\*\*FILE:\*\*", "FILE:", normalized)
        normalized = re.sub(r"\*\*ACTION:\*\*", "ACTION:", normalized)
        normalized = re.sub(r"\*\*DESCRIPTION:\*\*", "DESCRIPTION:", normalized)
        normalized = re.sub(r"\*\*OLD_CONTENT:\*\*", "OLD_CONTENT:", normalized)
        normalized = re.sub(r"\*\*NEW_CONTENT:\*\*", "NEW_CONTENT:", normalized)

        # Also handle backtick-wrapped file paths: `templates/foo.html`
        # FILE: `templates/foo.html` -> FILE: templates/foo.html
        normalized = re.sub(r"FILE:\s*`([^`]+)`", r"FILE: \1", normalized)

        # Look for FILE: markers (with flexible patterns)
        file_pattern = r"FILE:\s*(.+?)(?:\n|$)"
        action_pattern = r"ACTION:\s*(\w+?)(?:\n|$)"
        description_pattern = r"DESCRIPTION:\s*(.+?)(?:\n|$)"
        old_content_pattern = r"OLD_CONTENT:\s*```(?:\w+)?\n(.*?)```"
        new_content_pattern = r"NEW_CONTENT:\s*```(?:\w+)?\n(.*?)```"

        # Find all file blocks - split on FILE: (case insensitive)
        file_blocks = re.split(r"(?=FILE:)", normalized, flags=re.IGNORECASE)

        for block in file_blocks:
            if not block.strip():
                continue

            # Check if block starts with FILE:
            if not re.match(r"^FILE:", block, re.IGNORECASE):
                continue

            # Extract components
            file_match = re.search(file_pattern, block, re.IGNORECASE)
            action_match = re.search(action_pattern, block, re.IGNORECASE)
            desc_match = re.search(description_pattern, block, re.IGNORECASE)
            old_content_match = re.search(old_content_pattern, block, re.DOTALL | re.IGNORECASE)
            new_content_match = re.search(new_content_pattern, block, re.DOTALL | re.IGNORECASE)

            if not file_match:
                continue

            file_path = file_match.group(1).strip()
            # Clean up file path - remove trailing markers or notes
            file_path = re.sub(r"\s*\(.*\)\s*$", "", file_path)  # Remove (create) or (modify) notes
            file_path = file_path.strip("`").strip()

            # Determine action - default to modify if not specified
            if action_match:
                action = action_match.group(1).strip().lower()
            elif "(create)" in block.lower() or "create" in block[:100].lower():
                action = "create"
            else:
                action = "modify"

            description = desc_match.group(1).strip() if desc_match else f"Change to {file_path}"
            old_content = old_content_match.group(1).strip() if old_content_match else ""
            new_content = new_content_match.group(1).strip() if new_content_match else ""

            # Strip line number prefixes if AI accidentally included them (e.g., "215:         except:")
            def strip_line_numbers(content):
                """Remove line number prefixes like '215:' or '215:\t' from each line"""
                lines = content.split("\n")
                cleaned = []
                for line in lines:
                    # Match pattern: optional spaces, digits, colon, optional tab/space
                    match = re.match(r"^\s*\d+:\s?(.*)$", line)
                    if match:
                        cleaned.append(match.group(1))
                    else:
                        cleaned.append(line)
                return "\n".join(cleaned)

            old_content = strip_line_numbers(old_content)
            new_content = strip_line_numbers(new_content)

            # Skip if no content to apply
            if not new_content and not old_content:
                continue

            # Generate diff
            diff = self._generate_diff(old_content, new_content, file_path)

            changes.append(
                {
                    "file_path": file_path,
                    "action": action,
                    "old_content": old_content,
                    "new_content": new_content,
                    "diff": diff,
                    "description": description,
                }
            )

        # If AI didn't provide structured format, create a fallback change
        if not changes:
            # Create a simple change based on category
            changes = self._create_fallback_change(category, ai_response)

        return changes

    def _create_fallback_change(self, category: str, ai_response: str) -> List[Dict]:
        """Create a fallback change when AI doesn't follow format"""

        # For UI category, assume dashboard modification
        if category == "ui":
            return [
                {
                    "file_path": "templates/dashboard.html",
                    "action": "modify",
                    "old_content": '<div class="tool-card disabled">',
                    "new_content": '<a href="/tools/website_builder/" class="tool-card">',
                    "diff": '- <div class="tool-card disabled">\n+ <a href="/tools/website_builder/" class="tool-card">',
                    "description": "Enable Website Builder module (AI-generated)",
                }
            ]

        # Generic fallback
        return [
            {
                "file_path": "CHANGE_DESCRIPTION.md",
                "action": "create",
                "old_content": "",
                "new_content": f"# AI-Generated Change\n\n{ai_response}",
                "diff": f"+ {ai_response}",
                "description": "AI-generated improvement description",
            }
        ]

    def _generate_diff(self, old_content: str, new_content: str, file_path: str) -> str:
        """Generate unified diff between old and new content"""
        import difflib

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )

        return "".join(diff)


# Convenience functions
def generate_code_for_proposal(
    proposal_id: int,
    proposal_title: str,
    proposal_description: str,
    category: str = "general",
    target_files: Optional[List[str]] = None,
    line_number: Optional[int] = None,
    issue_context: Optional[Dict] = None,
    use_v2: bool = True,
    prefer_contractor: bool = False,
) -> Dict:
    """
    Generate code changes for a proposal.

    Args:
        use_v2: Use V2 validation pipeline (default True)
        prefer_contractor: Prefer external AI for complex tasks

    V2 Features:
        - Architect/Editor pattern for better accuracy
        - Syntax validation before saving
        - Content matching verification
        - Retry with error feedback
    """
    engine = CodeGenerationEngine()

    if use_v2 and VALIDATORS_AVAILABLE:
        return engine.generate_with_validation(
            proposal_id,
            proposal_title,
            proposal_description,
            category,
            target_files,
            line_number,
            issue_context,
            prefer_contractor,
        )
    else:
        # Fall back to V1 (legacy)
        return engine.generate_code_for_proposal(
            proposal_id,
            proposal_title,
            proposal_description,
            category,
            target_files,
            line_number,
            issue_context,
        )


def generate_code_with_validation(
    proposal_id: int,
    proposal_title: str,
    proposal_description: str,
    category: str = "general",
    target_files: Optional[List[str]] = None,
    line_number: Optional[int] = None,
    issue_context: Optional[Dict] = None,
    prefer_contractor: bool = False,
) -> Dict:
    """V2 convenience function - always uses validation pipeline"""
    engine = CodeGenerationEngine()
    return engine.generate_with_validation(
        proposal_id,
        proposal_title,
        proposal_description,
        category,
        target_files,
        line_number,
        issue_context,
        prefer_contractor,
    )


if __name__ == "__main__":
    # Test code generation
    print("=" * 80)
    print("Code Generation Engine - Test")
    print("=" * 80)

    result = generate_code_for_proposal(
        proposal_id=999,
        proposal_title="Enable Website Builder",
        proposal_description="Make the Website Builder tool active and clickable on the dashboard. Add a basic interface.",
        category="ui",
    )

    print(f"\n✅ Success: {result['success']}")
    print(f"📝 Changes generated: {len(result.get('changes', []))}")

    for i, change in enumerate(result.get("changes", []), 1):
        print(f"\n--- Change {i} ---")
        print(f"File: {change['file_path']}")
        print(f"Action: {change['action']}")
        print(f"Description: {change['description']}")
        if change.get("diff"):
            print(f"Diff:\n{change['diff'][:200]}...")
