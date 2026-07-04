"""
A.R.C.H.I.E. Auto-Tagging Engine
Automatically analyzes conversations and generates relevant tags for knowledge storage

Hybrid: fast regex pre-filter + optional LLM enrichment via qwen25-classify.
"""

import os
import re
import json
import logging
from typing import List, Dict, Set, Optional

logger = logging.getLogger(__name__)

LLM_TAGGING_ENABLED = os.getenv("LLM_TAGGING_ENABLED", "true").lower() == "true"

# Knowledge domains and their keywords
KNOWLEDGE_DOMAINS = {
    "python": {
        "keywords": [
            "python",
            "def ",
            "class ",
            "import ",
            "pip",
            "django",
            "flask",
            "fastapi",
            "numpy",
            "pandas",
        ],
        "patterns": [r"\bdef\s+\w+", r"\bclass\s+\w+", r"\.py\b", r"import\s+\w+"],
    },
    "javascript": {
        "keywords": [
            "javascript",
            "js",
            "node",
            "npm",
            "react",
            "vue",
            "angular",
            "function ",
            "const ",
            "let ",
            "var ",
        ],
        "patterns": [r"function\s+\w+", r"const\s+\w+", r"\.js\b", r"=>"],
    },
    "database": {
        "keywords": [
            "sql",
            "database",
            "postgres",
            "mysql",
            "mongodb",
            "query",
            "table",
            "select",
            "insert",
            "update",
            "delete",
        ],
        "patterns": [
            r"\bSELECT\b",
            r"\bINSERT\b",
            r"\bUPDATE\b",
            r"\bCREATE TABLE\b",
            r"\.sql\b",
        ],
    },
    "api": {
        "keywords": [
            "api",
            "endpoint",
            "rest",
            "graphql",
            "json",
            "request",
            "response",
            "get",
            "post",
            "put",
            "delete",
        ],
        "patterns": [r"/api/", r"@app\.route", r"@api_bp\.route", r"HTTP", r"REST"],
    },
    "frontend": {
        "keywords": [
            "html",
            "css",
            "template",
            "ui",
            "interface",
            "button",
            "form",
            "style",
            "component",
        ],
        "patterns": [r"<\w+>", r"\.html\b", r"\.css\b", r"class=", r"id="],
    },
    "docker": {
        "keywords": [
            "docker",
            "container",
            "dockerfile",
            "compose",
            "image",
            "volume",
            "network",
        ],
        "patterns": [r"docker-compose", r"FROM\s+\w+", r"RUN\s+", r"COPY\s+"],
    },
    "deployment": {
        "keywords": [
            "deploy",
            "production",
            "staging",
            "environment",
            "server",
            "cloud",
            "aws",
            "heroku",
            "netlify",
        ],
        "patterns": [r"\.env\b", r"config", r"production", r"staging"],
    },
    "security": {
        "keywords": [
            "security",
            "auth",
            "authentication",
            "authorization",
            "password",
            "token",
            "jwt",
            "encryption",
            "ssl",
            "https",
        ],
        "patterns": [r"password", r"token", r"auth", r"secure", r"encrypt"],
    },
    "testing": {
        "keywords": [
            "test",
            "pytest",
            "unittest",
            "jest",
            "mocha",
            "assert",
            "mock",
            "fixture",
        ],
        "patterns": [r"def test_", r"test\(", r"assert\s+", r"\.test\."],
    },
    "git": {
        "keywords": [
            "git",
            "commit",
            "branch",
            "merge",
            "pull",
            "push",
            "clone",
            "repository",
            "github",
        ],
        "patterns": [r"git\s+", r"\.git/", r"commit", r"branch"],
    },
    "performance": {
        "keywords": [
            "performance",
            "optimization",
            "cache",
            "speed",
            "memory",
            "cpu",
            "efficient",
            "fast",
            "slow",
        ],
        "patterns": [r"optimize", r"performance", r"cache", r"memory"],
    },
    "error-handling": {
        "keywords": [
            "error",
            "exception",
            "try",
            "catch",
            "except",
            "finally",
            "raise",
            "throw",
        ],
        "patterns": [
            r"try:",
            r"except\s+\w+:",
            r"raise\s+",
            r"Error\b",
            r"Exception\b",
        ],
    },
    "ai-ml": {
        "keywords": [
            "ai",
            "ml",
            "machine learning",
            "neural",
            "model",
            "training",
            "llm",
            "ollama",
            "openai",
            "claude",
            "gpt",
        ],
        "patterns": [r"\bollama\b", r"\bllm\b", r"\bgpt\b", r"\bclaude\b", r"model\."],
    },
    "consciousness": {
        "keywords": [
            "memory",
            "consciousness",
            "awareness",
            "knowledge",
            "learning",
            "archie",
            "brain",
        ],
        "patterns": [r"long_term_memory", r"consciousness", r"knowledge", r"learn"],
    },
    "backup": {
        "keywords": ["backup", "restore", "recovery", "snapshot", "archive"],
        "patterns": [r"backup", r"restore", r"\.sql\b", r"pg_dump"],
    },
}


def analyze_content(text: str) -> Dict[str, any]:
    """
    Analyze text content and extract tags

    Returns:
        {
            'tags': List[str],  # Identified tags
            'confidence': Dict[str, float],  # Confidence score per tag
            'keywords': List[str],  # Key terms found
            'code_detected': bool,  # Whether code was detected
            'languages': List[str],  # Programming languages detected
        }
    """
    text_lower = text.lower()

    # Track matches
    domain_scores = {}
    detected_languages = set()
    keywords_found = set()

    # Analyze each domain
    for domain, config in KNOWLEDGE_DOMAINS.items():
        score = 0

        # Check keywords
        for keyword in config["keywords"]:
            if keyword.lower() in text_lower:
                score += 1
                keywords_found.add(keyword)

        # Check patterns
        for pattern in config["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                score += 2  # Patterns are stronger signals

        if score > 0:
            domain_scores[domain] = score

    # Detect programming languages
    if any(kw in text_lower for kw in ["python", "def ", ".py"]):
        detected_languages.add("python")
    if any(kw in text_lower for kw in ["javascript", "node", ".js"]):
        detected_languages.add("javascript")
    if any(kw in text_lower for kw in ["sql", "database", "select"]):
        detected_languages.add("sql")

    # Determine final tags (domains with score >= 2)
    tags = [domain for domain, score in domain_scores.items() if score >= 2]

    # Add top languages
    tags.extend(detected_languages)

    # Detect code blocks
    code_detected = bool(re.search(r"```[\s\S]*```", text) or re.search(r"def \w+|class \w+|function \w+", text))

    # Calculate confidence scores
    confidence = {}
    max_score = max(domain_scores.values()) if domain_scores else 1
    for domain, score in domain_scores.items():
        confidence[domain] = min(score / max_score, 1.0)

    return {
        "tags": list(set(tags)),  # Remove duplicates
        "confidence": confidence,
        "keywords": list(keywords_found),
        "code_detected": code_detected,
        "languages": list(detected_languages),
        "domain_scores": domain_scores,
    }


def _llm_enrich_tags(text: str, regex_tags: List[str]) -> List[str]:
    """
    Use qwen25-classify to discover tags that regex missed.
    Returns enriched tag list or original tags on failure.
    """
    if not LLM_TAGGING_ENABLED:
        return regex_tags

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        domains = ", ".join(KNOWLEDGE_DOMAINS.keys())
        prompt = (
            f"Classify this text into relevant knowledge domains. "
            f"Available domains: {domains}, plus any other relevant tags.\n"
            f"Already detected: {', '.join(regex_tags) if regex_tags else 'none'}\n"
            f"Add any domains the text relates to that are missing.\n\n"
            f"Text: {text[:800]}\n\n"
            f'Respond with JSON only: {{"tags": ["tag1", "tag2"]}}'
        )

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            "classify",
            prompt,
            "auto_tagger",
            json_mode=True,
            timeout=10,
            prefer_agent="I.R.I.S.",
        )

        if result.success:
            data = json.loads(result.response)
            llm_tags = data.get("tags", [])
            if isinstance(llm_tags, list):
                combined = list(set(regex_tags + [t.lower().strip() for t in llm_tags if isinstance(t, str)]))
                return combined

    except Exception as e:
        logger.debug(f"LLM tag enrichment failed, using regex only: {e}")

    return regex_tags


def generate_tags_from_conversation(user_message: str, ai_response: str, use_llm: bool = True) -> List[str]:
    """
    Generate tags from a complete conversation (user message + AI response).
    Hybrid approach: regex pre-filter + optional LLM enrichment.

    Args:
        user_message: User's message text
        ai_response: AI's response text
        use_llm: Whether to use LLM for tag enrichment (default True)

    Returns:
        List of relevant tags
    """
    # Analyze both messages with regex
    combined_text = f"{user_message}\n\n{ai_response}"
    analysis = analyze_content(combined_text)

    tags = analysis["tags"]

    # Add context-based tags
    if "how" in user_message.lower() or "explain" in user_message.lower():
        tags.append("explanation")

    if "error" in combined_text.lower() or "fix" in combined_text.lower():
        tags.append("troubleshooting")

    if "implement" in user_message.lower() or "create" in user_message.lower():
        tags.append("implementation")

    if "optimize" in combined_text.lower() or "improve" in combined_text.lower():
        tags.append("optimization")

    tags = list(set(tags))

    # Enrich with LLM if enabled
    if use_llm:
        tags = _llm_enrich_tags(combined_text, tags)

    return tags


def extract_code_snippets(text: str) -> List[Dict[str, str]]:
    """
    Extract code snippets from text

    Returns:
        List of {'language': str, 'code': str}
    """
    snippets = []

    # Extract fenced code blocks
    pattern = r"```(\w+)?\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)

    for lang, code in matches:
        snippets.append({"language": lang or "unknown", "code": code.strip()})

    return snippets


def summarize_conversation(user_message: str, ai_response: str, max_length: int = 200) -> str:
    """
    Generate a brief summary of the conversation

    Returns:
        Summary string
    """
    # Extract first sentence of user message
    user_summary = user_message.split(".")[0][:100]

    # Extract key points from AI response
    ai_sentences = ai_response.split(".")
    ai_summary = ai_sentences[0][:100] if ai_sentences else ""

    summary = f"Q: {user_summary}... A: {ai_summary}..."

    return summary[:max_length]


def should_store_knowledge(user_message: str, ai_response: str) -> bool:
    """
    Determine if this conversation contains valuable knowledge worth storing

    Returns:
        bool
    """
    # Don't store if too short
    if len(user_message) < 10 or len(ai_response) < 20:
        return False

    # Don't store simple greetings
    greetings = ["hello", "hi", "hey", "thanks", "thank you"]
    if user_message.lower().strip() in greetings:
        return False

    # Store if it contains code, technical terms, or explanations
    combined = f"{user_message} {ai_response}".lower()

    valuable_indicators = [
        "how to",
        "why",
        "what is",
        "explain",
        "implement",
        "function",
        "class",
        "method",
        "code",
        "error",
        "fix",
        "solve",
        "create",
        "build",
        "database",
    ]

    return any(indicator in combined for indicator in valuable_indicators)


# Example usage
if __name__ == "__main__":
    test_conversation = """
    User: How do I create a database backup in PostgreSQL?

    AI: To create a database backup in PostgreSQL, you can use pg_dump:

    ```bash
    pg_dump -U username -d database_name > backup.sql
    ```

    This creates a full SQL dump of your database.
    """

    analysis = analyze_content(test_conversation)
    print("Analysis:", analysis)

    tags = generate_tags_from_conversation(
        "How do I create a database backup in PostgreSQL?",
        "To create a database backup... use pg_dump...",
    )
    print("Tags:", tags)
