"""
Insight Extractor
Extracts architecture decisions, insights, and learnings from conversations.

Creates knowledge entries of type: vault_note, improvement
"""

import re
import logging
from typing import List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedInsight:
    """An extracted insight or decision."""

    title: str
    content: str
    insight_type: str  # decision, insight, todo, learning
    category: str
    related_files: List[str]
    confidence: float


class InsightExtractor:
    """Extracts insights and decisions from conversation transcripts."""

    # Decision indicators
    DECISION_PATTERNS = [
        r"(?:we(?:'ll| will| should)|let's|decided to|going to)\s+(.+?)(?:\.|$)",
        r"(?:the (?:plan|approach|solution) is to)\s+(.+?)(?:\.|$)",
        r"(?:instead of .+?, we'll)\s+(.+?)(?:\.|$)",
    ]

    # Insight/learning indicators
    INSIGHT_PATTERNS = [
        r"(?:learned that|discovered that|realized that|turns out)\s+(.+?)(?:\.|$)",
        r"(?:key (?:insight|learning|takeaway)[:\s]+)(.+?)(?:\.|$)",
        r"(?:important[:\s]+)(.+?)(?:\.|$)",
        r"(?:note[:\s]+)(.+?)(?:\.|$)",
    ]

    # Todo/action indicators
    TODO_PATTERNS = [
        r"(?:TODO|FIXME|NOTE)[:\s]+(.+?)(?:\n|$)",
        r"(?:need to|should|must)\s+(.+?)(?:\.|$)",
        r"(?:next steps?[:\s]+)(.+?)(?:\n|$)",
    ]

    # Category detection
    CATEGORY_KEYWORDS = {
        "architecture": ["architecture", "design", "pattern", "structure", "refactor"],
        "database": ["database", "sql", "table", "migration", "schema"],
        "api": ["api", "endpoint", "route", "request", "response"],
        "performance": ["performance", "optimize", "speed", "cache", "slow"],
        "security": ["security", "auth", "permission", "token", "password"],
        "ui": ["ui", "template", "frontend", "css", "button", "form"],
        "testing": ["test", "coverage", "mock", "fixture"],
        "deployment": ["deploy", "docker", "production", "release"],
        "workflow": ["workflow", "process", "pipeline", "hook"],
    }

    def extract(self, content: str) -> List[ExtractedInsight]:
        """Extract all insights from conversation content."""
        insights = []

        # Extract decisions
        insights.extend(self._extract_pattern_type(content, self.DECISION_PATTERNS, "decision"))

        # Extract learnings
        insights.extend(self._extract_pattern_type(content, self.INSIGHT_PATTERNS, "learning"))

        # Extract TODOs
        insights.extend(self._extract_pattern_type(content, self.TODO_PATTERNS, "todo"))

        # Extract summary sections
        insights.extend(self._extract_summaries(content))

        # Deduplicate
        return self._deduplicate(insights)

    def _extract_pattern_type(self, content: str, patterns: List[str], insight_type: str) -> List[ExtractedInsight]:
        """Extract insights matching specific patterns."""
        insights = []

        for pattern in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                extracted = match.group(1).strip()
                if len(extracted) < 15:  # Skip very short matches
                    continue
                if len(extracted) > 500:  # Truncate very long matches
                    extracted = extracted[:500] + "..."

                # Get context for category detection
                start = max(0, match.start() - 200)
                end = min(len(content), match.end() + 200)
                context = content[start:end]

                # Detect category
                category = self._detect_category(context)

                # Find related files
                related_files = self._find_related_files(context)

                # Generate title
                title = self._generate_title(extracted, insight_type)

                insights.append(
                    ExtractedInsight(
                        title=title,
                        content=extracted,
                        insight_type=insight_type,
                        category=category,
                        related_files=related_files,
                        confidence=0.75,
                    )
                )

        return insights

    def _extract_summaries(self, content: str) -> List[ExtractedInsight]:
        """Extract summary sections that often contain valuable insights."""
        insights = []

        # Look for summary headers
        summary_pattern = (
            r"(?:#{1,3}\s*)?(?:Summary|Key (?:Points|Takeaways)|Conclusion)[:\s]*\n(.+?)(?=\n#{1,3}|\n\n\n|\Z)"
        )
        matches = re.finditer(summary_pattern, content, re.IGNORECASE | re.DOTALL)

        for match in matches:
            summary_text = match.group(1).strip()
            if len(summary_text) < 30:
                continue

            # Parse bullet points if present
            bullets = re.findall(r"[-*]\s+(.+)", summary_text)
            if bullets:
                for bullet in bullets[:5]:  # Max 5 bullets
                    if len(bullet) > 15:
                        insights.append(
                            ExtractedInsight(
                                title=f"Learning: {bullet[:50]}",
                                content=bullet,
                                insight_type="learning",
                                category=self._detect_category(bullet),
                                related_files=self._find_related_files(content),
                                confidence=0.8,
                            )
                        )
            else:
                # Single summary block
                insights.append(
                    ExtractedInsight(
                        title="Session Summary",
                        content=summary_text[:500],
                        insight_type="learning",
                        category=self._detect_category(summary_text),
                        related_files=self._find_related_files(content),
                        confidence=0.85,
                    )
                )

        return insights

    def _detect_category(self, text: str) -> str:
        """Detect the category based on keywords."""
        text_lower = text.lower()
        scores = {}

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[category] = score

        if scores:
            return max(scores, key=scores.get)
        return "general"

    def _find_related_files(self, text: str) -> List[str]:
        """Find file paths mentioned in text."""
        # Match common file patterns
        patterns = [
            r"/[\w/.-]+\.\w+",  # Absolute paths
            r"[\w/]+/[\w.-]+\.(?:py|js|ts|html|sql|md)",  # Relative paths
            r"`([^`]+\.(?:py|js|ts|html|sql|md))`",  # Backtick-wrapped
        ]

        files = set()
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                files.add(match)

        return list(files)[:10]  # Max 10 files

    def _generate_title(self, content: str, insight_type: str) -> str:
        """Generate a title for the insight."""
        # Extract first meaningful phrase
        words = content.split()[:8]
        base = " ".join(words)
        if len(content) > len(base):
            base += "..."

        type_labels = {
            "decision": "Decision",
            "learning": "Learned",
            "todo": "TODO",
            "insight": "Insight",
        }
        prefix = type_labels.get(insight_type, "Note")

        return f"{prefix}: {base}"

    def _deduplicate(self, insights: List[ExtractedInsight]) -> List[ExtractedInsight]:
        """Remove duplicate insights."""
        seen = set()
        unique = []

        for insight in insights:
            # Normalize for comparison
            key = insight.content[:100].lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(insight)

        return unique
