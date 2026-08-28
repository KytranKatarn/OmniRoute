"""
Error Extractor
Extracts mistakes, errors, and their solutions from conversations.

Creates knowledge entries of type: mistake_learned
"""

import re
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedError:
    """An extracted error/mistake with context and solution."""

    title: str
    error_message: str
    cause: str
    solution: str
    prevention: Optional[str]
    severity: str  # critical, high, medium, low
    language: Optional[str]
    confidence: float


class ErrorExtractor:
    """Extracts errors and mistakes from conversation transcripts."""

    # Common error patterns
    ERROR_PATTERNS = [
        # Python errors
        (r"(Traceback.*?(?=\n\n|\Z))", "python"),
        (r"(\w+Error: .+)", "python"),
        (r"(\w+Exception: .+)", "python"),
        # JavaScript/Node errors
        (r"(TypeError: .+)", "javascript"),
        (r"(ReferenceError: .+)", "javascript"),
        (r"(Uncaught .+Error.+)", "javascript"),
        # SQL errors
        (r"(ERROR:\s+.+)", "sql"),
        (r'(column ".*" (?:does not exist|already exists))', "sql"),
        (r'(relation ".*" (?:does not exist|already exists))', "sql"),
        (r"(duplicate key value violates unique constraint)", "sql"),
        # Docker errors
        (r"(docker.*error.*)", "docker"),
        (r"(container.*failed.*)", "docker"),
        # Generic errors
        (r"(FATAL:\s+.+)", "general"),
        (r"(Error:\s+.+)", "general"),
        (r"(failed to .+)", "general"),
    ]

    # Solution indicators
    SOLUTION_PATTERNS = [
        r"(?:fix|fixed|solution|resolved|solved)[:\s]+(.+?)(?:\n|$)",
        r"(?:changed|updated|modified)\s+(.+?)\s+(?:to|from)",
        r"(?:the\s+(?:fix|solution)\s+(?:is|was))[:\s]+(.+?)(?:\n|$)",
        r"(?:I|we)\s+(?:fixed|solved|resolved)\s+(?:it|this)\s+by\s+(.+?)(?:\n|$)",
    ]

    # Severity indicators
    SEVERITY_INDICATORS = {
        "critical": ["data loss", "security", "crash", "production down", "corruption"],
        "high": ["broken", "cannot", "failed", "blocking", "urgent"],
        "medium": ["error", "issue", "problem", "bug"],
        "low": ["warning", "deprecated", "minor", "cosmetic"],
    }

    def extract(self, content: str) -> List[ExtractedError]:
        """Extract all errors from conversation content."""
        errors = []
        content_lower = content.lower()

        # Find error blocks
        for pattern, lang in self.ERROR_PATTERNS:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for match in matches:
                error_text = match.group(1).strip()
                if len(error_text) < 10:  # Skip tiny matches
                    continue

                # Get surrounding context for cause/solution
                start = max(0, match.start() - 500)
                end = min(len(content), match.end() + 1000)
                context = content[start:end]

                # Extract components
                error = self._build_error(error_text, context, lang)
                if error:
                    errors.append(error)

        # Deduplicate similar errors
        return self._deduplicate(errors)

    def _build_error(self, error_text: str, context: str, language: str) -> Optional[ExtractedError]:
        """Build an ExtractedError from raw components."""
        # Generate title
        title = self._generate_title(error_text)

        # Find cause (look before the error)
        cause = self._find_cause(context, error_text)

        # Find solution (look after the error)
        solution = self._find_solution(context)

        # Determine severity
        severity = self._determine_severity(error_text + " " + context)

        # Skip if no solution found (not a complete learning)
        if not solution:
            return None

        return ExtractedError(
            title=title,
            error_message=error_text[:500],  # Truncate long tracebacks
            cause=cause,
            solution=solution,
            prevention=self._infer_prevention(cause, solution),
            severity=severity,
            language=language,
            confidence=0.8 if solution else 0.5,
        )

    def _generate_title(self, error_text: str) -> str:
        """Generate a concise title for the error."""
        # Extract the main error type/message
        error_type_match = re.search(r"(\w+(?:Error|Exception)):\s*(.+?)(?:\n|$)", error_text)
        if error_type_match:
            error_type = error_type_match.group(1)
            brief = error_type_match.group(2)[:50]
            return f"{error_type}: {brief}"

        # SQL-style error
        if "column" in error_text.lower() or "relation" in error_text.lower():
            return error_text[:60].strip()

        # Generic
        return error_text[:50].strip()

    def _find_cause(self, context: str, error_text: str) -> str:
        """Find the cause of the error from context."""
        cause_patterns = [
            r"(?:because|caused by|due to|reason)[:\s]+(.+?)(?:\n|$)",
            r"(?:the problem (?:is|was))[:\s]+(.+?)(?:\n|$)",
            r"(?:this happened because)[:\s]+(.+?)(?:\n|$)",
        ]

        for pattern in cause_patterns:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:200]

        return "Error encountered during operation"

    def _find_solution(self, context: str) -> str:
        """Find the solution from context."""
        for pattern in self.SOLUTION_PATTERNS:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                solution = match.group(1).strip()
                if len(solution) > 10:
                    return solution[:300]

        # Look for code fixes
        if "```" in context:
            # There's code after the error, likely a fix
            return "Code modification applied (see context)"

        return ""

    def _determine_severity(self, text: str) -> str:
        """Determine error severity."""
        text_lower = text.lower()

        for severity, indicators in self.SEVERITY_INDICATORS.items():
            for indicator in indicators:
                if indicator in text_lower:
                    return severity

        return "medium"

    def _infer_prevention(self, cause: str, solution: str) -> Optional[str]:
        """Infer prevention advice from cause and solution."""
        if not cause or not solution:
            return None

        # Simple heuristics
        prevention_tips = []

        if "typo" in cause.lower() or "misspell" in cause.lower():
            prevention_tips.append("Use IDE autocomplete and linting")

        if "column" in cause.lower() or "table" in cause.lower():
            prevention_tips.append("Verify database schema before queries")

        if "import" in cause.lower() or "module" in cause.lower():
            prevention_tips.append("Check import paths and module availability")

        if "permission" in cause.lower() or "access" in cause.lower():
            prevention_tips.append("Verify file/resource permissions before access")

        return "; ".join(prevention_tips) if prevention_tips else None

    def _deduplicate(self, errors: List[ExtractedError]) -> List[ExtractedError]:
        """Remove duplicate errors based on title similarity."""
        seen_titles = set()
        unique = []

        for error in errors:
            # Normalize title for comparison
            normalized = error.title.lower().strip()
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique.append(error)

        return unique
