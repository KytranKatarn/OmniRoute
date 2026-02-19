"""
Translation Service for ARCHIE Linguistics Module

Provides batch and single-string translation via Ollama LLMs,
language detection, glossary management, and translation storage.

Models used:
- qwen25-classify: fast language detection (CPU)
- qwen3-coder-cpu: batch UI string translation (CPU, 32K context)
- dolphin3-8k: single-string chat translation (GPU, 8K context)

Usage:
    from ai_bridge.translation_service import detect_language, batch_translate, translate_text

    lang = detect_language("Bonjour le monde")
    results = batch_translate([("greeting", "Hello", "nav_bar")], "fr")
    text = translate_text("Hello world", "fr")
"""

import json
import logging
import re
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("archie_platform")

# Ollama endpoint (host machine from inside Docker)
OLLAMA_URL = "http://host.docker.internal:11434"

# Languages supported by the platform
SUPPORTED_LANGUAGES = {
    "en": "English",
    "fr": "Québécois French",
}

# How many strings to translate per LLM call
BATCH_SIZE = 40


def _get_db():
    """Get a psycopg2 connection to the ARCHIE database."""
    return psycopg2.connect(
        host="archie_database",
        port=5432,
        database="archie",
        user="archie",
        password="archie",
    )


def _call_ollama(model: str, prompt: str, temperature: float = 0.3) -> str:
    """Call Ollama generate API and return the response text.

    Args:
        model: Ollama model name (e.g. 'qwen25-classify', 'qwen3-coder-cpu')
        prompt: The prompt to send
        temperature: Sampling temperature (default 0.3 for deterministic output)

    Returns:
        Generated text, or empty string on failure.
    """
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.Timeout:
        logger.error("Ollama request timed out (model=%s)", model)
        return ""
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Ollama at %s", OLLAMA_URL)
        return ""
    except Exception as e:
        logger.error("Ollama call failed (model=%s): %s", model, e)
        return ""


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Detect the language of a text string.

    Uses qwen25-classify for fast CPU-based classification.

    Args:
        text: Input text to classify.

    Returns:
        ISO 639-1 two-letter language code (e.g. 'en', 'fr').
        Defaults to 'en' if detection fails.
    """
    try:
        prompt = (
            "What language is this? Reply with ONLY the 2-letter ISO code.\n\n"
            f"{text[:500]}"
        )
        result = _call_ollama("qwen25-classify", prompt, temperature=0.1)
        # Extract just the 2-letter code from the response
        code = re.search(r"\b([a-z]{2})\b", result.lower())
        if code:
            return code.group(1)
        logger.warning("Could not parse language code from: %s", result)
        return "en"
    except Exception as e:
        logger.error("Language detection failed: %s", e)
        return "en"


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

def get_glossary(language: str) -> List[Dict]:
    """Fetch the translation glossary for a language.

    Reads from the translation_memory table, ordered by category then source_text.

    Args:
        language: ISO 639-1 code (e.g. 'fr').

    Returns:
        List of dicts with keys: source_text, translated_text, category, notes.
    """
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT source_text, translated_text, category, notes
            FROM translation_memory
            WHERE language = %s
            ORDER BY category, source_text
            """,
            (language,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.error("Failed to fetch glossary for %s: %s", language, e)
        return []


# ---------------------------------------------------------------------------
# Batch translation
# ---------------------------------------------------------------------------

def batch_translate(
    strings: List[Tuple[str, str, str]],
    language: str,
    model: str = "qwen3-coder-cpu",
) -> List[Dict]:
    """Translate a batch of UI strings.

    Args:
        strings: List of (key, english_text, context) tuples.
        language: Target language ISO code.
        model: Ollama model to use (default qwen3-coder-cpu for large context).

    Returns:
        List of dicts: {"key": str, "translation": str, "success": bool}
    """
    if not strings:
        return []

    lang_name = SUPPORTED_LANGUAGES.get(language, language)
    glossary = get_glossary(language)

    # Build glossary section for the prompt
    glossary_section = ""
    if glossary:
        glossary_lines = [
            f"  - \"{g['source_text']}\" → \"{g['translated_text']}\""
            for g in glossary
        ]
        glossary_section = (
            "GLOSSARY (use these exact translations when the term appears):\n"
            + "\n".join(glossary_lines)
            + "\n\n"
        )

    all_results = []

    # Process in batches
    for batch_start in range(0, len(strings), BATCH_SIZE):
        batch = strings[batch_start : batch_start + BATCH_SIZE]

        # Build numbered list of strings to translate
        numbered = []
        for i, (key, english_text, context) in enumerate(batch, 1):
            ctx_note = f" (context: {context})" if context else ""
            numbered.append(f'{i}. "{english_text}"{ctx_note}')

        prompt = (
            f"Translate the following UI strings from English to {lang_name}.\n"
            f"Return ONLY a JSON array with objects: "
            f'[{{"n": 1, "t": "translated"}}]\n\n'
            f"{glossary_section}"
            f"Strings to translate:\n"
            + "\n".join(numbered)
        )

        raw = _call_ollama(model, prompt, temperature=0.3)

        # Parse JSON from response
        translations = _parse_batch_response(raw, len(batch))

        for i, (key, english_text, _context) in enumerate(batch):
            if i < len(translations) and translations[i]:
                all_results.append({
                    "key": key,
                    "translation": translations[i],
                    "success": True,
                })
            else:
                logger.warning("Missing translation for key=%s in batch", key)
                all_results.append({
                    "key": key,
                    "translation": english_text,
                    "success": False,
                })

    return all_results


def _parse_batch_response(raw: str, expected: int) -> List[Optional[str]]:
    """Parse JSON array from LLM batch translation response.

    Handles markdown code fences and partial JSON.

    Returns:
        List of translated strings indexed by position (0-based).
        None entries for missing translations.
    """
    results: List[Optional[str]] = [None] * expected

    if not raw:
        return results

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        arr = json.loads(cleaned)
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict) and "n" in item and "t" in item:
                    idx = int(item["n"]) - 1  # 1-based to 0-based
                    if 0 <= idx < expected:
                        results[idx] = str(item["t"])
    except json.JSONDecodeError:
        logger.warning("Failed to parse batch translation JSON: %s", raw[:200])

    return results


# ---------------------------------------------------------------------------
# Single-string translation (for chat / real-time use)
# ---------------------------------------------------------------------------

def translate_text(
    text: str,
    target_language: str,
    source_language: str = "en",
    model: str = "dolphin3-8k",
) -> str:
    """Translate a single text string.

    Intended for chat / real-time translation, uses the faster GPU model.

    Args:
        text: Source text to translate.
        target_language: Target ISO language code.
        source_language: Source ISO language code (default 'en').
        model: Ollama model to use.

    Returns:
        Translated text, or original text on failure.
    """
    try:
        src_name = SUPPORTED_LANGUAGES.get(source_language, source_language)
        tgt_name = SUPPORTED_LANGUAGES.get(target_language, target_language)

        prompt = (
            f"Translate the following text from {src_name} to {tgt_name}. "
            f"Return ONLY the translated text, nothing else.\n\n"
            f"{text}"
        )

        result = _call_ollama(model, prompt, temperature=0.3)
        if result:
            return result
        logger.warning("Empty translation result, returning original text")
        return text
    except Exception as e:
        logger.error("Translation failed: %s", e)
        return text


# ---------------------------------------------------------------------------
# Translation storage
# ---------------------------------------------------------------------------

def store_translations(
    results: List[Dict],
    language: str,
    model: str,
) -> Dict[str, int]:
    """Upsert translation results into the translations table.

    Uses ON CONFLICT (key, language) to update existing entries.

    Args:
        results: List of {"key": str, "translation": str, "success": bool}.
        language: Target language code.
        model: Model used for translation.

    Returns:
        Dict with counts: {"inserted": N, "updated": N, "failed": N}
    """
    counts = {"inserted": 0, "updated": 0, "failed": 0}

    if not results:
        return counts

    try:
        conn = _get_db()
        cur = conn.cursor()

        for item in results:
            if not item.get("success", False):
                counts["failed"] += 1
                continue

            try:
                cur.execute(
                    """
                    INSERT INTO translations (key, language, translation, model_used, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW())
                    ON CONFLICT (key, language) DO UPDATE SET
                        translation = EXCLUDED.translation,
                        model_used = EXCLUDED.model_used,
                        updated_at = NOW()
                    RETURNING (xmax = 0) AS is_insert
                    """,
                    (item["key"], language, item["translation"], model),
                )
                row = cur.fetchone()
                if row and row[0]:
                    counts["inserted"] += 1
                else:
                    counts["updated"] += 1
            except Exception as e:
                logger.error("Failed to store translation key=%s: %s", item.get("key"), e)
                conn.rollback()
                counts["failed"] += 1

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("store_translations DB error: %s", e)

    return counts


# ---------------------------------------------------------------------------
# Translation retrieval
# ---------------------------------------------------------------------------

def get_translations(language: str) -> Dict[str, str]:
    """Get all approved translations for a language.

    Args:
        language: ISO language code.

    Returns:
        Dict mapping translation key to translated text.
    """
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT key, translation
            FROM translations
            WHERE language = %s AND status = 'approved'
            ORDER BY key
            """,
            (language,),
        )
        result = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        conn.close()
        return result
    except Exception as e:
        logger.error("get_translations failed for %s: %s", language, e)
        return {}


def get_translation_stats(language: str) -> Dict[str, int]:
    """Get translation statistics for a language.

    Args:
        language: ISO language code.

    Returns:
        Dict with keys: total, approved, pending, rejected, human_edited.
    """
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                COUNT(*) FILTER (WHERE human_edited = TRUE) AS human_edited
            FROM translations
            WHERE language = %s
            """,
            (language,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return {
                "total": row[0],
                "approved": row[1],
                "pending": row[2],
                "rejected": row[3],
                "human_edited": row[4],
            }
        return {"total": 0, "approved": 0, "pending": 0, "rejected": 0, "human_edited": 0}
    except Exception as e:
        logger.error("get_translation_stats failed for %s: %s", language, e)
        return {"total": 0, "approved": 0, "pending": 0, "rejected": 0, "human_edited": 0}
