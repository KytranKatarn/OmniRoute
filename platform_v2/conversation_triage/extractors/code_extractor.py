"""
Code Extractor
Extracts reusable code snippets, patterns, and functions from conversations.

Creates knowledge entries of type: code_snippet
"""

import re
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedCode:
    """An extracted code snippet with context."""

    title: str
    code: str
    language: str
    purpose: str
    context: str
    file_path: Optional[str]
    confidence: float


class CodeExtractor:
    """Extracts code snippets from conversation transcripts."""

    # Language detection patterns for fenced code blocks
    LANGUAGE_ALIASES = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "sh": "bash",
        "shell": "bash",
        "yml": "yaml",
        "psql": "sql",
        "postgres": "sql",
        "dockerfile": "docker",
    }

    # Minimum lines for a "useful" snippet
    MIN_LINES = 3

    # Maximum lines to extract
    MAX_LINES = 100

    # Pattern for fenced code blocks
    CODE_BLOCK_PATTERN = r"```(\w*)\n(.*?)```"

    # Pattern for file paths often preceding code
    FILE_PATH_PATTERN = r'(?:File|Path|In|Edit):\s*[`"]?([^\s`"]+\.\w+)[`"]?'

    def extract(self, content: str) -> List[ExtractedCode]:
        """Extract all code snippets from conversation content."""
        snippets = []

        # Find all fenced code blocks
        matches = re.finditer(self.CODE_BLOCK_PATTERN, content, re.DOTALL)

        for match in matches:
            lang_hint = match.group(1).lower()
            code = match.group(2).strip()

            # Skip very short snippets
            lines = code.split("\n")
            if len(lines) < self.MIN_LINES:
                continue

            # Skip very long snippets (likely full files)
            if len(lines) > self.MAX_LINES:
                code = "\n".join(lines[: self.MAX_LINES]) + "\n# ... (truncated)"

            # Normalize language
            language = self.LANGUAGE_ALIASES.get(lang_hint, lang_hint) or self._detect_language(code)

            # Get surrounding context
            start = max(0, match.start() - 300)
            context = content[start : match.start()].strip()

            # Look for file path
            file_path = self._find_file_path(context)

            # Generate title and purpose
            title, purpose = self._analyze_code(code, language, context)

            snippets.append(
                ExtractedCode(
                    title=title,
                    code=code,
                    language=language,
                    purpose=purpose,
                    context=context[-200:] if len(context) > 200 else context,
                    file_path=file_path,
                    confidence=0.85,
                )
            )

        # Deduplicate similar snippets
        return self._deduplicate(snippets)

    def _detect_language(self, code: str) -> str:
        """Detect language from code content."""
        # Python indicators
        if re.search(
            r"\bdef\s+\w+\s*\(|^\s*import\s+\w+|^\s*from\s+\w+\s+import",
            code,
            re.MULTILINE,
        ):
            return "python"

        # JavaScript/TypeScript indicators
        if re.search(r"\bfunction\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|\basync\s+function", code):
            return "javascript"

        # SQL indicators
        if re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\b", code, re.IGNORECASE):
            return "sql"

        # HTML indicators
        if re.search(r"<(?:div|span|html|body|head|script)", code, re.IGNORECASE):
            return "html"

        # CSS indicators
        if re.search(r"[\w-]+\s*:\s*[\w#%-]+;", code):
            return "css"

        # Bash indicators
        if re.search(r"^\s*(?:#!/|docker|apt|pip|npm)\s", code, re.MULTILINE):
            return "bash"

        return "unknown"

    def _find_file_path(self, context: str) -> Optional[str]:
        """Find file path from context."""
        match = re.search(self.FILE_PATH_PATTERN, context, re.IGNORECASE)
        if match:
            return match.group(1)

        # Look for common path patterns
        path_match = re.search(r"(/[\w/]+\.\w+|[\w/]+/[\w.]+\.(?:py|js|ts|sql|html))", context)
        if path_match:
            return path_match.group(1)

        return None

    def _analyze_code(self, code: str, language: str, context: str) -> tuple:
        """Analyze code to generate title and purpose."""
        # Extract function/class names
        if language == "python":
            func_match = re.search(r"def\s+(\w+)\s*\(", code)
            class_match = re.search(r"class\s+(\w+)", code)
            if func_match:
                name = func_match.group(1)
                return f"Python function: {name}", f"Function {name} implementation"
            if class_match:
                name = class_match.group(1)
                return f"Python class: {name}", f"Class {name} implementation"

        elif language in ("javascript", "typescript"):
            func_match = re.search(r"(?:function|const|let)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|[=(])", code)
            if func_match:
                name = func_match.group(1)
                return f"JS function: {name}", f"Function {name} implementation"

        elif language == "sql":
            if "CREATE TABLE" in code.upper():
                table_match = re.search(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                    code,
                    re.IGNORECASE,
                )
                if table_match:
                    return (
                        f"SQL: Create table {table_match.group(1)}",
                        "Table creation script",
                    )
            if "CREATE FUNCTION" in code.upper():
                return "SQL: Stored function", "PostgreSQL function definition"
            return "SQL Query", "Database query/migration"

        # Generic analysis based on context
        context_lower = context.lower()
        if "fix" in context_lower or "solution" in context_lower:
            return f"{language.title()} fix", "Bug fix code snippet"
        if "example" in context_lower:
            return f"{language.title()} example", "Example code snippet"
        if "template" in context_lower:
            return f"{language.title()} template", "Code template"

        return f"{language.title()} snippet", f"Code snippet in {language}"

    def _deduplicate(self, snippets: List[ExtractedCode]) -> List[ExtractedCode]:
        """Remove duplicate code snippets."""
        seen_hashes = set()
        unique = []

        for snippet in snippets:
            # Hash based on first 200 chars of code (normalized)
            code_hash = hash(snippet.code[:200].replace(" ", "").replace("\n", ""))
            if code_hash not in seen_hashes:
                seen_hashes.add(code_hash)
                unique.append(snippet)

        return unique
