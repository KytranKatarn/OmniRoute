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
import requests
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# Configuration
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Ollama configuration (fallback when no Claude API key)
# Analysis model — qwen2.5-coder:7b (GPU) for knowledge extraction from
# conversations and documents.  Override via OLLAMA_ANALYSIS_MODEL env var.
def _get_analysis_model():
    return os.getenv("OLLAMA_ANALYSIS_MODEL", "qwen2.5-coder:7b")

OLLAMA_MODEL = _get_analysis_model()
# Fast model for short entries (disabled by default — model swapping crashes on small-VRAM GPUs)
# Set OLLAMA_FAST_MODEL=tinyllama:latest to enable on systems with >=16GB VRAM
OLLAMA_FAST_MODEL = os.getenv("OLLAMA_FAST_MODEL", "")

# Content limits tuned to model context windows
# qwen3-coder-cpu runs at num_ctx=32768 → ~24K tokens usable for content after prompt+output overhead
MAX_CONTENT_LENGTH = 30000  # chars for primary model
FAST_CONTENT_LENGTH = 4000  # chars for fast model (if enabled)
FAST_MODEL_THRESHOLD = 2000  # entries under this many chars use the fast model


# Determine Ollama host - prefer server with qwen model
def _find_ollama_host():
    """Find an Ollama host that has the analysis model"""
    hosts = [
        "http://host.docker.internal:11434",  # Local Ollama on ARCHIE host
    ]
    for host in hosts:
        try:
            resp = requests.get(f"{host}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(OLLAMA_MODEL in m for m in models):
                    logger.info(f"Found {OLLAMA_MODEL} at {host}")
                    return host
        except Exception:
            continue
    # Fallback to main server
    return "http://192.168.1.200:11434"


OLLAMA_HOST = _find_ollama_host()

# Choose backend: "claude" or "ollama" (auto-selects based on API key if not set)
ANALYZER_BACKEND = os.getenv("ANALYZER_BACKEND", "auto")


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
    """Analyzes content using Claude API or Ollama to extract knowledge"""

    def __init__(self, api_key: str = CLAUDE_API_KEY, backend: str = ANALYZER_BACKEND):
        self.api_key = api_key
        self._client = None
        self._fast_model_available = None  # cached availability check

        # Determine backend
        if backend == "auto":
            self.backend = "claude" if api_key else "ollama"
        else:
            self.backend = backend

        logger.info(f"Knowledge analyzer using backend: {self.backend}")

    def get_current_model(self) -> str:
        """Return the model name currently used for analysis."""
        if self.backend == "claude":
            return CLAUDE_MODEL
        return OLLAMA_MODEL

    @property
    def client(self):
        """Lazy-load anthropic client"""
        if self._client is None and self.backend == "claude":
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.error("anthropic package not installed")
                raise ImportError("pip install anthropic")
        return self._client

    def warmup(self) -> bool:
        """Warm up Ollama model to avoid cold-start crashes.

        Ollama 0.15.x has a bug where the first API call after model eviction
        crashes with 'exit status 2'. This method retries up to 3 times.
        """
        if self.backend != "ollama":
            return True
        import time

        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": "hi",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("response") is not None and "error" not in data:
                        logger.info(f"Ollama warmup succeeded on attempt {attempt + 1}")
                        return True
                    if "error" in data:
                        logger.warning(
                            f"Ollama warmup attempt {attempt + 1}: {data['error']}"
                        )
                else:
                    logger.warning(
                        f"Ollama warmup attempt {attempt + 1}: HTTP {resp.status_code}"
                    )
            except Exception as e:
                logger.warning(f"Ollama warmup attempt {attempt + 1}: {e}")
            time.sleep(3)
        logger.error("Ollama warmup failed after 3 attempts")
        return False

    def health_check(self) -> dict:
        """Check if analyzer is ready, including GPU info"""
        if self.backend == "ollama":
            try:
                resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    if any(OLLAMA_MODEL in m for m in models):
                        result = {
                            "status": "healthy",
                            "backend": "ollama",
                            "model": OLLAMA_MODEL,
                            "host": OLLAMA_HOST,
                            "fast_model": (
                                OLLAMA_FAST_MODEL
                                if self._is_fast_model_available()
                                else None
                            ),
                            "tiered": self._is_fast_model_available(),
                        }
                        # Check running models for GPU info
                        try:
                            ps_resp = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=3)
                            if ps_resp.status_code == 200:
                                running = ps_resp.json().get("models", [])
                                gpu_info = []
                                for m in running:
                                    gpu_info.append(
                                        {
                                            "name": m.get("name"),
                                            "size": m.get("size"),
                                            "processor": m.get("size_vram", 0) > 0
                                            and "GPU"
                                            or "CPU",
                                        }
                                    )
                                if gpu_info:
                                    result["running_models"] = gpu_info
                        except Exception:
                            pass
                        return result
                    return {
                        "status": "unhealthy",
                        "backend": "ollama",
                        "error": f"Model {OLLAMA_MODEL} not found",
                    }
                return {
                    "status": "unhealthy",
                    "backend": "ollama",
                    "error": "Ollama not responding",
                }
            except Exception as e:
                return {"status": "unhealthy", "backend": "ollama", "error": str(e)}

        # Claude backend
        if not self.api_key:
            return {
                "status": "unhealthy",
                "backend": "claude",
                "error": "No API key configured",
            }

        try:
            _ = self.client
            return {"status": "healthy", "backend": "claude", "model": CLAUDE_MODEL}
        except Exception as e:
            return {"status": "unhealthy", "backend": "claude", "error": str(e)}

    def _is_fast_model_available(self) -> bool:
        """Check if the fast model is configured and available.

        Disabled by default — model swapping can crash Ollama on small-VRAM GPUs (e.g. 8GB).
        Enable by setting OLLAMA_FAST_MODEL env var.
        """
        if not OLLAMA_FAST_MODEL:
            return False
        if self._fast_model_available is not None:
            return self._fast_model_available
        try:
            resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                self._fast_model_available = any(
                    OLLAMA_FAST_MODEL.split(":")[0] in m for m in models
                )
            else:
                self._fast_model_available = False
        except Exception:
            self._fast_model_available = False
        return self._fast_model_available

    def _select_model(self, content_length: int) -> tuple:
        """Select the best model based on content size.

        Returns:
            tuple: (model_name, num_ctx, max_content_chars)
        """
        if self.backend != "ollama":
            return (CLAUDE_MODEL, None, MAX_CONTENT_LENGTH)

        # Short entries → fast model (tinyllama) for speed
        if content_length <= FAST_MODEL_THRESHOLD and self._is_fast_model_available():
            logger.info(
                f"Using fast model {OLLAMA_FAST_MODEL} for {content_length} char entry"
            )
            return (OLLAMA_FAST_MODEL, 4096, FAST_CONTENT_LENGTH)

        # Everything else → primary model with expanded context
        return (OLLAMA_MODEL, 8192, MAX_CONTENT_LENGTH)

    def _call_llm(
        self,
        prompt: str,
        max_tokens: int = 4000,
        model: str = None,
        num_ctx: int = None,
    ) -> tuple:
        """
        Call LLM (Claude or Ollama) with prompt.

        Returns:
            tuple: (response_text, input_tokens, output_tokens, elapsed_ms)
        """
        if self.backend == "ollama":
            return self._call_ollama(prompt, max_tokens, model=model, num_ctx=num_ctx)
        return self._call_claude(prompt, max_tokens)

    def _call_ollama(
        self,
        prompt: str,
        max_tokens: int = 4000,
        model: str = None,
        num_ctx: int = None,
    ) -> tuple:
        """
        Call Ollama API with prompt.

        Returns:
            tuple: (response_text, input_tokens, output_tokens, elapsed_ms)
        """
        import time

        model = model or OLLAMA_MODEL
        options = {
            "num_predict": max_tokens,
            "temperature": 0.3,
        }
        if num_ctx:
            options["num_ctx"] = num_ctx

        start = time.time()
        try:
            response = requests.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options,
                },
                timeout=300,
            )
            response.raise_for_status()
            data = response.json()
            elapsed = int((time.time() - start) * 1000)

            logger.info(
                f"Ollama [{model}] prompt={data.get('prompt_eval_count', 0)} "
                f"gen={data.get('eval_count', 0)} time={elapsed}ms"
            )

            return (
                data.get("response", ""),
                data.get("prompt_eval_count", 0),
                data.get("eval_count", 0),
                elapsed,
            )
        except Exception as e:
            logger.error(f"Ollama API error ({model}): {e}")
            raise

    def _call_claude(self, prompt: str, max_tokens: int = 4000) -> tuple:
        """
        Call Claude API with prompt.

        Returns:
            tuple: (response_text, input_tokens, output_tokens, elapsed_ms)
        """
        import time

        start = time.time()
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed = int((time.time() - start) * 1000)
            return (
                response.content[0].text,
                response.usage.input_tokens,
                response.usage.output_tokens,
                elapsed,
            )
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

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

        # Select model based on content size
        orig_len = len(content)
        model, num_ctx, max_chars = self._select_model(orig_len)

        # Smart truncation to fit model context
        content = _smart_truncate(content, max_chars)

        prompt = CONVERSATION_ANALYSIS_PROMPT.format(
            content=content,
            source_type=metadata.get("source_type", "conversation_log"),
            project=metadata.get("project", "unknown"),
            date=metadata.get("date", datetime.now().isoformat()),
        )

        # Scale output budget by content size (less content = fewer cards needed)
        max_tokens = 1500 if orig_len < 3000 else 2500 if orig_len < 10000 else 4000

        try:
            response, input_tokens, output_tokens, elapsed = self._call_llm(
                prompt, max_tokens=max_tokens, model=model, num_ctx=num_ctx
            )
            data = self._parse_json_response(response)

            # Parse cards
            cards = []
            for card_data in data.get("cards", []):
                card = KnowledgeCard(
                    title=card_data.get("title", "Untitled"),
                    card_type=card_data.get("card_type", "concept"),
                    summary=card_data.get("summary", ""),
                    detailed=card_data.get("detailed", ""),
                    code_examples=card_data.get("code_examples", []),
                    topics=card_data.get("topics", []),
                    technologies=card_data.get("technologies", []),
                    difficulty=card_data.get("difficulty", "intermediate"),
                    confidence=float(card_data.get("confidence", 0.7)),
                    source_type=metadata.get("source_type", "conversation"),
                    source_ref=metadata.get("source_ref", ""),
                )
                cards.append(card)

            # Parse relationships
            relationships = []
            for rel_data in data.get("relationships", []):
                rel = ExtractedRelationship(
                    from_title=rel_data.get("from_title", ""),
                    to_title=rel_data.get("to_title", ""),
                    relationship_type=rel_data.get("relationship_type", "related_to"),
                    strength=float(rel_data.get("strength", 0.5)),
                    reasoning=rel_data.get("reasoning", ""),
                )
                relationships.append(rel)

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

        # Select model based on content size
        orig_len = len(content)
        model, num_ctx, max_chars = self._select_model(orig_len)

        # Smart truncation to fit model context
        content = _smart_truncate(content, max_chars)

        prompt = CODE_ANALYSIS_PROMPT.format(
            filename=filename, language=language, content=content
        )

        # Scale output budget by content size
        max_tokens = 1500 if orig_len < 3000 else 2500 if orig_len < 10000 else 4000

        try:
            response, input_tokens, output_tokens, elapsed = self._call_llm(
                prompt, max_tokens=max_tokens, model=model, num_ctx=num_ctx
            )
            data = self._parse_json_response(response)

            # Parse cards
            cards = []
            for card_data in data.get("cards", []):
                card = KnowledgeCard(
                    title=card_data.get("title", "Untitled"),
                    card_type=card_data.get("card_type", "pattern"),
                    summary=card_data.get("summary", ""),
                    detailed=card_data.get("detailed", ""),
                    code_examples=card_data.get("code_examples", []),
                    topics=card_data.get("topics", []),
                    technologies=card_data.get("technologies", [language]),
                    difficulty=card_data.get("difficulty", "intermediate"),
                    confidence=float(card_data.get("confidence", 0.7)),
                    source_type="github",
                    source_ref=filename,
                )
                cards.append(card)

            # Parse relationships
            relationships = []
            for rel_data in data.get("relationships", []):
                rel = ExtractedRelationship(
                    from_title=rel_data.get("from_title", ""),
                    to_title=rel_data.get("to_title", ""),
                    relationship_type=rel_data.get("relationship_type", "implements"),
                    strength=float(rel_data.get("strength", 0.5)),
                    reasoning=rel_data.get("reasoning", ""),
                )
                relationships.append(rel)

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
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Knowledge Analyzer...")
    print("-" * 40)

    # Health check
    health = analyzer_health_check()
    print(f"Health: {health}")

    if health["status"] == "healthy":
        backend = health.get("backend", "unknown")
        model = health.get("model", "unknown")
        print(f"\nAnalyzer ready using {backend} backend with {model}")
        print("To test analysis, use: analyzer.analyze_conversation(content)")
    else:
        print(f"\nAnalyzer not ready: {health.get('error', 'Unknown error')}")
        backend = health.get("backend", "auto")
        if backend == "claude":
            print("Set ANTHROPIC_API_KEY environment variable")
        else:
            print(f"Check Ollama at {OLLAMA_HOST}")
