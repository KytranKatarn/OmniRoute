"""
Knowledge Analyzer for ARCHIE Consciousness Intelligence

Uses Claude API or Ollama for deep analysis of conversations, code files, and GitHub repos.
Extracts knowledge cards, relationships, and semantic embeddings.

Supports two backends:
- Claude API (requires ANTHROPIC_API_KEY)
- Ollama (local, free - uses qwen3-coder-cpu on CPU/RAM)

Usage:
    from ai_bridge.knowledge_analyzer import get_knowledge_analyzer

    analyzer = get_knowledge_analyzer()
    result = analyzer.analyze_conversation(content, metadata)
    # result.cards contains extracted knowledge cards
    # result.relationships contains extracted relationships
"""

import os
import json
import logging
import re
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Content limits for smart truncation before sending to Bridge
MAX_CONTENT_LENGTH = 30000  # chars max for analysis prompts


@dataclass
class KnowledgeCard:
    """Extracted knowledge card from analysis"""

    title: str
    card_type: str  # 'concept', 'pattern', 'problem-solution', 'example', 'reference'
    summary: str
    detailed: str = ""
    code_examples: list = field(default_factory=list)
    topics: list = field(default_factory=list)
    technologies: list = field(default_factory=list)
    difficulty: str = "intermediate"  # 'beginner', 'intermediate', 'advanced'
    confidence: float = 0.7
    source_type: str = ""
    source_ref: str = ""


@dataclass
class ExtractedRelationship:
    """Extracted relationship between knowledge entries"""

    from_title: str
    to_title: str
    relationship_type: str  # One of 15 types
    strength: float = 0.5
    reasoning: str = ""


@dataclass
class AnalysisResult:
    """Result of knowledge analysis"""

    success: bool
    cards: list = field(default_factory=list)  # List of KnowledgeCard
    relationships: list = field(default_factory=list)  # List of ExtractedRelationship
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    processing_time_ms: int = 0


# Knowledge extraction prompt templates
CONVERSATION_ANALYSIS_PROMPT = """Analyze this conversation and extract valuable knowledge.

CONVERSATION:
{content}

CONTEXT:
- Source: {source_type}
- Project: {project}
- Date: {date}

Extract knowledge cards in this JSON format:
{{
  "cards": [
    {{
      "title": "Clear, specific title",
      "card_type": "concept|pattern|problem-solution|example|reference",
      "summary": "2-3 sentence summary",
      "detailed": "Full explanation with context",
      "code_examples": ["code snippet 1", "code snippet 2"],
      "topics": ["topic1", "topic2"],
      "technologies": ["tech1", "tech2"],
      "difficulty": "beginner|intermediate|advanced",
      "confidence": 0.0-1.0
    }}
  ],
  "relationships": [
    {{
      "from_title": "Card title or existing concept",
      "to_title": "Another card or concept",
      "relationship_type": "related_to|part_of|uses|extends|implements|solves|causes|contradicts|supersedes|prerequisite_of|alternative_to|learned_from|similar_to|example_of|applies_to",
      "strength": 0.0-1.0,
      "reasoning": "Why this relationship exists"
    }}
  ]
}}

Guidelines:
1. Extract 1-5 knowledge cards (more for longer/richer conversations)
2. Card types:
   - concept: Technical concepts explained
   - pattern: Design patterns or best practices
   - problem-solution: Bug fixes, troubleshooting, or solutions
   - example: Working code examples or demos
   - reference: API references, documentation notes
3. Include specific code examples when present
4. Set confidence based on how clearly the knowledge is stated
5. Create relationships between extracted cards and existing concepts
6. Skip small talk, greetings, or non-technical content

Return ONLY valid JSON, no markdown or explanation."""

CODE_ANALYSIS_PROMPT = """Analyze this code file and extract knowledge about its architecture and patterns.

FILE: {filename}
LANGUAGE: {language}

CODE:
{content}

Extract knowledge cards in this JSON format:
{{
  "cards": [
    {{
      "title": "Clear, specific title about this code",
      "card_type": "pattern|example|reference",
      "summary": "What this code does and why it's notable",
      "detailed": "Architecture details, design decisions",
      "code_examples": ["relevant snippet"],
      "topics": ["topic1", "topic2"],
      "technologies": ["tech1", "framework"],
      "difficulty": "beginner|intermediate|advanced",
      "confidence": 0.0-1.0
    }}
  ],
  "relationships": [
    {{
      "from_title": "This code/pattern",
      "to_title": "Related concept",
      "relationship_type": "implements|uses|extends|example_of|applies_to",
      "strength": 0.0-1.0,
      "reasoning": "Why related"
    }}
  ]
}}

Focus on:
1. Design patterns used
2. Architecture decisions
3. Notable implementations
4. API structures
5. Error handling approaches

Return ONLY valid JSON."""


def _smart_truncate(content: str, max_chars: int) -> str:
    """Intelligently truncate content preserving the most valuable parts.

    For conversations: keeps beginning (topic setup) and end (solutions/conclusions).
    For code: keeps beginning (imports, class defs) and end (key implementations).
    """
    if len(content) <= max_chars:
        return content

    # Reserve 30% for the beginning, 50% for the end, 20% for the separator
    head_budget = int(max_chars * 0.30)
    tail_budget = int(max_chars * 0.50)

    head = content[:head_budget]
    tail = content[-tail_budget:]

    # Try to cut at paragraph/line boundaries for cleaner breaks
    last_newline = head.rfind("\n")
    if last_newline > head_budget * 0.7:
        head = head[:last_newline]

    first_newline = tail.find("\n")
    if first_newline > 0 and first_newline < tail_budget * 0.3:
        tail = tail[first_newline + 1 :]

    skipped = len(content) - len(head) - len(tail)
    return head + f"\n\n[... {skipped:,} chars skipped ...]\n\n" + tail


class KnowledgeAnalyzer:
    """Analyzes content via Bridge dispatcher to extract knowledge.

    All LLM inference routes through Bridge (ADR-013) for model management,
    VRAM handling, agent assignment, and escalation.
    """

    def __init__(self):
        logger.info("Knowledge analyzer using Bridge dispatcher")

    def get_current_model(self) -> str:
        """Return the model name — managed by Bridge dispatcher."""
        return "bridge-managed"

    def warmup(self) -> bool:
        """No-op — Bridge dispatcher handles model loading and warmup."""
        return True

    def health_check(self) -> dict:
        """Check if analyzer is ready via Bridge dispatcher."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            if dispatcher:
                return {
                    "status": "healthy",
                    "backend": "bridge",
                    "model": "managed by Bridge dispatcher",
                }
            return {"status": "unhealthy", "backend": "bridge", "error": "No dispatcher"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "bridge", "error": str(e)}

    def _parse_cards(self, data, source_type, source_ref, default_type="concept", default_techs=None):
        """Parse knowledge cards from LLM JSON response."""
        cards = []
        for cd in data.get("cards", []):
            cards.append(
                KnowledgeCard(
                    title=cd.get("title", "Untitled"),
                    card_type=cd.get("card_type", default_type),
                    summary=cd.get("summary", ""),
                    detailed=cd.get("detailed", ""),
                    code_examples=cd.get("code_examples", []),
                    topics=cd.get("topics", []),
                    technologies=cd.get("technologies", default_techs or []),
                    difficulty=cd.get("difficulty", "intermediate"),
                    confidence=float(cd.get("confidence", 0.7)),
                    source_type=source_type,
                    source_ref=source_ref,
                )
            )
        return cards

    def _parse_relationships(self, data, default_rel="related_to"):
        """Parse relationships from LLM JSON response."""
        rels = []
        for rd in data.get("relationships", []):
            rels.append(
                ExtractedRelationship(
                    from_title=rd.get("from_title", ""),
                    to_title=rd.get("to_title", ""),
                    relationship_type=rd.get("relationship_type", default_rel),
                    strength=float(rd.get("strength", 0.5)),
                    reasoning=rd.get("reasoning", ""),
                )
            )
        return rels

    def _call_llm(
        self,
        prompt: str,
        max_tokens: int = 4000,
        model: str = None,
        num_ctx: int = None,
        job_id: int = None,
        local_only: bool = False,
    ) -> tuple:
        """
        Call LLM via Bridge dispatcher (ADR-013).

        All inference routes through Bridge for model management, VRAM
        handling, agent assignment, and escalation.

        Args:
            job_id: Bridge job ID — when set, the assigned batch agent
                    is excluded from the busy-agents check so it can
                    handle every item in the batch.

        Returns:
            tuple: (response_text, input_tokens, output_tokens, elapsed_ms)
        """
        import time
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        start = time.time()
        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            "knowledge_analysis",
            prompt,
            "consciousness",
            json_mode=True,
            # #4343 P1b: the consciousness analysis loop is background batch — low priority
            # so it yields the interactive reserved fleet stream + sorts behind interactive work.
            priority="low",
            # timeout defaults to 300 but dispatcher overrides to 600 for
            # knowledge_analysis via CAPABILITY_TIMEOUTS (task #2130).
            job_id=job_id,
            local_only=local_only,
        )
        elapsed = int((time.time() - start) * 1000)

        if result.success:
            logger.info(
                f"Bridge [{result.model_used}] "
                f"prompt={result.prompt_tokens} "
                f"gen={result.completion_tokens} time={elapsed}ms"
            )
            return (
                result.response,
                result.prompt_tokens,
                result.completion_tokens,
                elapsed,
            )
        else:
            error_msg = getattr(result, "error", "Bridge dispatch failed")
            logger.error(f"Bridge dispatch failed: {error_msg}")
            raise RuntimeError(f"Bridge dispatch failed: {error_msg}")

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from Claude response, handling markdown code blocks"""
        # Remove markdown code blocks if present
        response = response.strip()
        if response.startswith("```"):
            # Find the content between code fences
            lines = response.split("\n")
            content_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    content_lines.append(line)
            response = "\n".join(content_lines)

        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return {"cards": [], "relationships": []}

    def analyze_conversation(
        self,
        content: str,
        metadata: Optional[dict] = None,
        job_id: int = None,
        local_only: bool = False,
    ) -> AnalysisResult:
        """
        Analyze a conversation and extract knowledge.

        Args:
            content: Conversation text
            metadata: Optional metadata (source_type, project, date)

        Returns:
            AnalysisResult with extracted cards and relationships
        """
        if not content or len(content.strip()) < 100:
            return AnalysisResult(success=False, error="Content too short for analysis")

        metadata = metadata or {}

        # Smart truncation to fit model context
        orig_len = len(content)
        content = _smart_truncate(content, MAX_CONTENT_LENGTH)

        prompt = CONVERSATION_ANALYSIS_PROMPT.format(
            content=content,
            source_type=metadata.get("source_type", "conversation_log"),
            project=metadata.get("project", "unknown"),
            date=metadata.get("date", datetime.now().isoformat()),
        )

        try:
            response, input_tokens, output_tokens, elapsed = self._call_llm(
                prompt, job_id=job_id, local_only=local_only
            )
            data = self._parse_json_response(response)
            cards = self._parse_cards(data, metadata.get("source_type", "conversation"), metadata.get("source_ref", ""))
            relationships = self._parse_relationships(data)

            return AnalysisResult(
                success=True,
                cards=cards,
                relationships=relationships,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                processing_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return AnalysisResult(success=False, error=str(e))

    def analyze_code_file(
        self,
        content: str,
        filename: str,
        language: Optional[str] = None,
        job_id: int = None,
        local_only: bool = False,
    ) -> AnalysisResult:
        """
        Analyze a code file and extract patterns and knowledge.

        Args:
            content: Code file content
            filename: Name of the file
            language: Programming language (auto-detected if not provided)

        Returns:
            AnalysisResult with extracted cards and relationships
        """
        if not content or len(content.strip()) < 50:
            return AnalysisResult(success=False, error="Code too short for analysis")

        # Auto-detect language from extension
        if not language:
            ext = os.path.splitext(filename)[1].lower()
            language_map = {
                ".py": "Python",
                ".js": "JavaScript",
                ".ts": "TypeScript",
                ".go": "Go",
                ".rs": "Rust",
                ".java": "Java",
                ".sql": "SQL",
                ".sh": "Bash",
                ".yml": "YAML",
                ".yaml": "YAML",
                ".html": "HTML",
                ".css": "CSS",
            }
            language = language_map.get(ext, "Unknown")

        # Smart truncation to fit model context
        content = _smart_truncate(content, MAX_CONTENT_LENGTH)

        prompt = CODE_ANALYSIS_PROMPT.format(filename=filename, language=language, content=content)

        try:
            response, input_tokens, output_tokens, elapsed = self._call_llm(
                prompt, job_id=job_id, local_only=local_only
            )
            data = self._parse_json_response(response)
            cards = self._parse_cards(data, "github", filename, default_type="pattern", default_techs=[language])
            relationships = self._parse_relationships(data, default_rel="implements")

            return AnalysisResult(
                success=True,
                cards=cards,
                relationships=relationships,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                processing_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return AnalysisResult(success=False, error=str(e))


# Singleton instance
_analyzer: Optional[KnowledgeAnalyzer] = None


def get_knowledge_analyzer() -> KnowledgeAnalyzer:
    """Get or create singleton analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = KnowledgeAnalyzer()
    return _analyzer


def analyzer_health_check() -> dict:
    """Convenience function for health check"""
    analyzer = get_knowledge_analyzer()
    return analyzer.health_check()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing Knowledge Analyzer...")
    health = analyzer_health_check()
    print(f"Health: {health}")
