"""
Conversation Classifier
Stage 1 of the Triage Pipeline

Classifies raw conversations by:
- Topic detection (what was discussed)
- Phase detection (planning, coding, debugging, reviewing, deploying)
- Urgency scoring (errors = high, chat = low)
"""

import re
import logging
from typing import List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Classification:
    """Result of classifying a conversation."""

    primary_topic: str
    phase: str  # planning, coding, debugging, reviewing, deploying, discussing
    urgency_score: float  # 0.0 to 1.0
    tags: List[str]
    confidence: float


class ConversationClassifier:
    """Classifies conversations for triage routing."""

    # Phase detection patterns
    PHASE_PATTERNS = {
        "debugging": [
            r"error[:\s]",
            r"exception",
            r"traceback",
            r"failed",
            r"fix",
            r"bug",
            r"broken",
            r"crash",
            r"issue",
            r"problem",
            r"doesn\'t work",
        ],
        "coding": [
            r"implement",
            r"create\s+\w+\s+function",
            r"add\s+\w+\s+method",
            r"write\s+code",
            r"code\s+snippet",
            r"```\w+",
            r"def\s+\w+",
            r"function\s+\w+",
        ],
        "planning": [
            r"how\s+should",
            r"what\s+approach",
            r"design",
            r"architecture",
            r"strategy",
            r"plan",
            r"roadmap",
            r"phase\s+\d+",
        ],
        "reviewing": [
            r"review",
            r"check",
            r"verify",
            r"test",
            r"looks\s+good",
            r"lgtm",
            r"approve",
            r"merge",
        ],
        "deploying": [
            r"deploy",
            r"release",
            r"production",
            r"docker",
            r"restart",
            r"migration",
            r"rollout",
            r"push\s+to",
        ],
    }

    # Topic detection patterns
    TOPIC_PATTERNS = {
        "database": [r"sql", r"postgres", r"migration", r"table", r"column", r"query"],
        "api": [r"endpoint", r"route", r"api", r"request", r"response", r"rest"],
        "frontend": [r"template", r"html", r"css", r"javascript", r"ui", r"button"],
        "authentication": [r"auth", r"login", r"password", r"token", r"permission"],
        "docker": [r"docker", r"container", r"compose", r"image"],
        "testing": [r"test", r"pytest", r"unittest", r"coverage"],
        "documentation": [r"docs", r"readme", r"documentation", r"comment"],
        "configuration": [r"config", r"settings", r"environment", r"env"],
        "ai_bridge": [r"ollama", r"model", r"prompt", r"ai_bridge", r"agent"],
        "knowledge_base": [r"knowledge", r"memory", r"learning", r"consciousness"],
    }

    # Urgency indicators
    URGENCY_HIGH = [
        r"critical",
        r"urgent",
        r"broken",
        r"crash",
        r"down",
        r"emergency",
        r"production\s+error",
        r"data\s+loss",
        r"security",
    ]
    URGENCY_MEDIUM = [r"error", r"bug", r"fix", r"issue", r"problem", r"failed"]

    def classify(self, content: str) -> Classification:
        """Classify a conversation transcript."""
        content_lower = content.lower()

        # Detect phase
        phase, phase_confidence = self._detect_phase(content_lower)

        # Detect primary topic
        topic, topic_tags = self._detect_topic(content_lower)

        # Calculate urgency
        urgency = self._calculate_urgency(content_lower, phase)

        # Overall confidence
        confidence = (phase_confidence + 0.7) / 2  # Base 0.7 for topic detection

        return Classification(
            primary_topic=topic,
            phase=phase,
            urgency_score=urgency,
            tags=topic_tags,
            confidence=confidence,
        )

    def _detect_phase(self, content: str) -> Tuple[str, float]:
        """Detect the conversation phase."""
        scores = {}

        for phase, patterns in self.PHASE_PATTERNS.items():
            count = 0
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                count += len(matches)
            scores[phase] = count

        if not scores or max(scores.values()) == 0:
            return "discussing", 0.5

        best_phase = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[best_phase] / total if total > 0 else 0.5

        return best_phase, min(confidence, 0.95)

    def _detect_topic(self, content: str) -> Tuple[str, List[str]]:
        """Detect the primary topic and related tags."""
        scores = {}

        for topic, patterns in self.TOPIC_PATTERNS.items():
            count = 0
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                count += len(matches)
            if count > 0:
                scores[topic] = count

        if not scores:
            return "general", []

        # Sort by score descending
        sorted_topics = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_topics[0][0]
        tags = [t[0] for t in sorted_topics[:5]]  # Top 5 as tags

        return primary, tags

    def _calculate_urgency(self, content: str, phase: str) -> float:
        """Calculate urgency score (0.0 to 1.0)."""
        base_urgency = {
            "debugging": 0.7,
            "deploying": 0.6,
            "coding": 0.5,
            "reviewing": 0.4,
            "planning": 0.3,
            "discussing": 0.2,
        }.get(phase, 0.5)

        # Check for high urgency indicators
        for pattern in self.URGENCY_HIGH:
            if re.search(pattern, content, re.IGNORECASE):
                return min(base_urgency + 0.3, 1.0)

        # Check for medium urgency indicators
        for pattern in self.URGENCY_MEDIUM:
            if re.search(pattern, content, re.IGNORECASE):
                return min(base_urgency + 0.1, 0.9)

        return base_urgency

    def extract_summary(self, content: str, max_length: int = 200) -> str:
        """Extract a brief summary from the conversation."""
        # Find user messages
        user_pattern = r"(?:Human|User):\s*(.+?)(?=(?:Assistant|Human|User):|$)"
        matches = re.findall(user_pattern, content, re.IGNORECASE | re.DOTALL)

        if matches:
            # Take first substantive user message
            for match in matches:
                cleaned = match.strip()[:max_length]
                if len(cleaned) > 20:
                    return cleaned + "..." if len(match) > max_length else cleaned

        # Fallback: first N characters
        return content[:max_length].strip() + "..."
