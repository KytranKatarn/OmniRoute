"""
Translation Service for ARCHIE Linguistics Module

All LLM calls route through BridgeDispatcher per ADR-013.
Bridge handles agent assignment, C.R.E.E.D. governance, HR labor tracking,
and dashboard AI Insights automatically.

Capabilities used:
- classify (detect_language): fast language detection via bridge
- translate: batch/single string translation via bridge

Usage:
    from ai_bridge.translation_service import detect_language, batch_translate, translate_text

    lang = detect_language("Bonjour le monde")
    results = batch_translate([("greeting", "Hello", "nav_bar")], "fr")
    text = translate_text("Hello world", "fr")
"""

import json
import os

try:
    from db import _get_db_password
except ImportError:

    def _get_db_password():
        """Fallback: read DB password from env."""
        return os.getenv("DB_PASSWORD", "")


import logging
import re
import psycopg2
import psycopg2.extras
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("archie_platform")

# Languages supported by the platform
SUPPORTED_LANGUAGES = {
    "en": "English",
    "fr": "Québécois French",
    "es": "Spanish",
    "pt": "Brazilian Portuguese",
    "de": "German",
    "zh": "Simplified Chinese (Mandarin)",
    "ar": "Arabic",
    "he": "Hebrew",
    "ai": "AI Semantic",
}

# How many strings to translate per LLM call
# Kept at 5 to stay within the translate-model batch timeout (mistral:7b / gemma3:12b)
BATCH_SIZE = 5

# Module ID for bridge tracking
MODULE_ID = "consciousness_linguistics"

# Per-language model PIN (#5626). mistral:7b garbles right-to-left scripts — it was
# shipping mixed Chinese/Russian characters into Hebrew, which is why the ar/he/de pod
# was split onto gemma3:12b in the first place (PR #1372, KB #270022).
#
# ⚠️ That pod is currently UNREACHABLE BY CAPABILITY. Agent selection matches
# `agent_skills.skill_name` EXACTLY against the dispatched capability string, and
# Amina (341) holds 'Arabic Translation' / 'Hebrew Translation' / 'German Translation'
# — never the literal 'translate'. So dispatch(capability='translate') cannot select
# her, and her task_execution_log runs stop dead on 2026-07-10. Until the skill rows
# are reconciled (filed separately), the capability resolves to R.O.S.E.T.T.A., who
# serves translate on BOTH gemma3:12b and mistral:7b — so which model an Arabic or
# Hebrew batch lands on is luck. Pinning the model makes it deterministic without
# touching the agent registry.
_MODEL_BY_LANGUAGE: Dict[str, str] = {
    "ar": "gemma3:12b",
    "he": "gemma3:12b",
    "de": "gemma3:12b",
}

# LLM placeholder words that signal the model returned a stub instead of
# translating. These are stored as failed (fall back to English) and the
# row is NOT persisted to the translations table.
_PLACEHOLDER_TRANSLATIONS: frozenset = frozenset(
    {"mock", "translated", "translation", "placeholder", "todo", "tbd", "test", "n/a", "..."}
)


def _get_db():
    """Get a psycopg2 connection to the ARCHIE database."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _dispatch(
    capability: str,
    prompt: str,
    system_prompt: str = None,
    timeout: int = 300,
    job_id: int = None,
    local_only: bool = False,
    prefer_agent: str = None,
) -> str:
    """Route an LLM call through the BridgeDispatcher (ADR-013).

    All LLM work goes through the bridge so that:
    - Agent assignment is tracked (e.g. Amara at Consciousness)
    - C.R.E.E.D. governance is enforced
    - HR labor tracking records the work
    - Dashboard AI Insights reflect the activity
    - Escalation triggers automatically on failures

    Args:
        capability: Bridge capability key ('classify', 'translate', etc.)
        prompt: The prompt to send.
        system_prompt: Optional system prompt override.
        timeout: HTTP timeout in seconds (default 300, translation uses 600).
        job_id: Optional bridge job ID to link this execution to.

    Returns:
        Generated text, or empty string on failure.
    """
    try:
        if capability == "detect_language":
            from services.coordinator_lane import coordinator_dispatch

            result = coordinator_dispatch(
                capability,
                prompt,
                module_id=MODULE_ID,
                timeout_s=10,
            )
            if result.success:
                return result.response
            logger.error("Bridge dispatch failed (capability=%s): %s", capability, result.error)
            return ""

        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability=capability,
            prompt=prompt,
            module_id=MODULE_ID,
            system_prompt=system_prompt,
            timeout=timeout,
            job_id=job_id,
            local_only=local_only,
            prefer_agent=prefer_agent,
        )
        if result.success:
            return result.response
        logger.error("Bridge dispatch failed (capability=%s): %s", capability, result.error)
        return ""
    except Exception as e:
        logger.error("Bridge dispatch error (capability=%s): %s", capability, e)
        return ""


def _queued_dispatch_text(**kwargs) -> Optional[str]:
    """Lazy shim over services.cluster_dispatch.queued_dispatch_text (#5626).

    Imported lazily, not at module scope: this module is loaded from BOTH the web app
    (`/app` already on sys.path) and the scheduler sidecar / bare `python3 -c` runs,
    where `services.*` is not importable until cluster_dispatch's own
    `_ensure_import_paths()` has run (KB #272154). A module-level import would make
    translation_service unimportable in the very contexts the drip producer runs in.

    Returns None if the helper itself cannot be loaded, so the caller falls through to
    its existing "no translation this batch" path rather than raising mid-drain.
    """
    try:
        from services.cluster_dispatch import queued_dispatch_text
    except ImportError:
        try:
            import sys

            if "/app" not in sys.path:
                sys.path.insert(0, "/app")
            from services.cluster_dispatch import queued_dispatch_text
        except Exception as exc:  # pragma: no cover - environment-dependent
            logger.error("[Linguistics] queued_dispatch_text unavailable: %s", exc)
            return None
    return queued_dispatch_text(**kwargs)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_language(text: str) -> str:
    """Detect the language of a text string.

    Routes through bridge with 'detect_language' capability.

    Args:
        text: Input text to classify.

    Returns:
        ISO 639-1 two-letter language code (e.g. 'en', 'fr').
        Defaults to 'en' if detection fails.
    """
    try:
        prompt = "What language is this? Reply with ONLY the 2-letter ISO code.\n\n" f"{text[:500]}"
        result = _dispatch("detect_language", prompt)
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
        List of dicts with keys: source_text, translated_text, category.
    """
    try:
        conn = _get_db()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """
                SELECT source_text, translated_text, category
                FROM translation_memory
                WHERE language = %s
                ORDER BY category, source_text
                """,
                (language,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            return rows
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.error("Failed to fetch glossary for %s: %s", language, e)
        return []


# ---------------------------------------------------------------------------
# Batch translation
# ---------------------------------------------------------------------------


def batch_translate(
    strings: List[Tuple[str, str, str]],
    language: str,
    parent_job_id: int = None,
    batch_offset: int = 0,
    model: str = None,
    source_label: str = "platform",
) -> List[Dict]:
    """Translate a batch of UI strings via the bridge.

    Each batch is stored to DB immediately after translation for crash
    resilience — if the job dies mid-run, all completed batches are preserved.

    Args:
        strings: List of (key, english_text, context) tuples.
        language: Target language ISO code.
        parent_job_id: If provided, update this job's progress instead of
                       creating a new sub-job. batch_offset is the number
                       of batches already completed in prior languages.
        model: generated_by LABEL for the stored rows (default None → generic).
                       Inference is routed by the 'translate' capability
                       (mistral:7b / gemma3:12b), NOT this label.

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
        glossary_lines = [f"  - \"{g['source_text']}\" \u2192 \"{g['translated_text']}\"" for g in glossary]
        glossary_section = (
            "GLOSSARY (use these exact translations when the term appears):\n" + "\n".join(glossary_lines) + "\n\n"
        )

    all_results = []
    total_batches = (len(strings) + BATCH_SIZE - 1) // BATCH_SIZE

    # If no parent job, create a standalone job for this batch operation
    job_id = parent_job_id
    dispatcher = None
    standalone = job_id is None
    if standalone:
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            job_id = dispatcher.create_job(
                job_type="batch_translate",
                module_source=MODULE_ID,
                description=f"Translate {len(strings)} keys to {lang_name}",
                total_steps=total_batches,
                capability="translate",
                metadata={
                    "language": language,
                    "lang_name": lang_name,
                    "total_strings": len(strings),
                    "batch_size": BATCH_SIZE,
                },
            )
        except Exception as e:
            logger.warning("[Linguistics] Could not create bridge job: %s", e)
    else:
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
        except Exception:
            pass

    total_ok = 0
    total_fail = 0

    # Process in batches — store each batch immediately for crash resilience
    for batch_start in range(0, len(strings), BATCH_SIZE):
        batch_num = batch_start // BATCH_SIZE + 1
        batch = strings[batch_start : batch_start + BATCH_SIZE]

        # Build numbered list of strings to translate
        numbered = []
        for i, (key, english_text, context) in enumerate(batch, 1):
            ctx_note = f" (context: {context})" if context else ""
            numbered.append(f'{i}. "{english_text}"{ctx_note}')

        prompt = (
            f"Translate the following UI strings from English to {lang_name}.\n"
            f"Return ONLY a JSON array. Each object has 'n' (the string number) "
            f"and 't' (the actual {lang_name} translation — not a placeholder).\n"
            f'Example format: [{{"n": 1, "t": "<{lang_name} translation>"}}, {{"n": 2, "t": "<{lang_name} translation>"}}]\n\n'
            f"{glossary_section}"
            f"Strings to translate:\n" + "\n".join(numbered)
        )

        logger.info(
            "[Linguistics] %s batch %d/%d (%d strings)",
            language,
            batch_num,
            total_batches,
            len(batch),
        )
        # #5626 — QUEUE-AWARE. `_dispatch` returns "" whenever request_work reports
        # queued=True (cold model / busy agent), which is not a failure: the work IS
        # accepted and model_dispatch_worker writes a result nobody was reading. Every
        # such batch was silently discarded and its keys stayed missing forever, so the
        # backlog could never drain on a contended cluster (KB #276153).
        # queued_dispatch_text runs inline when warm and otherwise polls
        # dispatch_pending_queue for the worker's result. NEVER use dispatch_json here.
        raw = (
            _queued_dispatch_text(
                capability="translate",
                prompt=prompt,
                module_id=MODULE_ID,
                local_only=True,
                poll_timeout_s=600,
                job_id=job_id,
                prefer_agent="C.O.D.E.X.",
                model_override=_MODEL_BY_LANGUAGE.get(language),
            )
            or ""
        )

        # Parse JSON from response
        translations = _parse_batch_response(raw, len(batch))

        batch_results = []
        batch_ok = 0
        for i, (key, english_text, _context) in enumerate(batch):
            t = translations[i] if i < len(translations) else None
            is_placeholder = t and t.strip().lower() in _PLACEHOLDER_TRANSLATIONS
            if t and not is_placeholder:
                batch_results.append(
                    {
                        "key": key,
                        "translation": t,
                        "success": True,
                    }
                )
                batch_ok += 1
            else:
                if is_placeholder:
                    logger.warning(
                        "Placeholder translation '%s' rejected for key=%s lang=%s",
                        t,
                        key,
                        language,
                    )
                else:
                    logger.warning("Missing translation for key=%s in batch", key)
                batch_results.append(
                    {
                        "key": key,
                        "translation": english_text,
                        "success": False,
                    }
                )

        # Store this batch to DB immediately — no progress lost on crash
        if batch_ok > 0:
            try:
                batch_stats = store_translations(batch_results, language, model or "codex", source_label)
                total_ok += batch_stats.get("inserted", 0) + batch_stats.get("updated", 0)
                total_fail += batch_stats.get("failed", 0)
            except Exception as e:
                logger.error("[Linguistics] %s batch %d store failed: %s", language, batch_num, e)
                total_fail += batch_ok
        else:
            total_fail += len(batch)

        all_results.extend(batch_results)

        logger.info(
            "[Linguistics] %s batch %d/%d done: %d/%d ok (stored)",
            language,
            batch_num,
            total_batches,
            batch_ok,
            len(batch),
        )

        # Update job progress
        if job_id and dispatcher:
            try:
                dispatcher.update_job_progress(
                    job_id=job_id,
                    completed_steps=batch_offset + batch_num,
                    failed_steps=0,
                    metadata_update={
                        "language": language,
                        "lang_name": lang_name,
                        "strings_ok": total_ok,
                        "strings_failed": total_fail,
                        "last_batch": batch_num,
                    },
                )
            except Exception:
                pass

    # Only complete if this is a standalone job (not part of a parent)
    if standalone and job_id and dispatcher:
        try:
            dispatcher.complete_job(job_id)
        except Exception:
            pass

    return all_results


def _parse_batch_response(raw: str, expected: int) -> List[Optional[str]]:
    """Parse JSON array from LLM batch translation response.

    Handles markdown code fences, preamble text before JSON, and partial JSON.
    The LLM may return commentary before/after the actual JSON array.

    Returns:
        List of translated strings indexed by position (0-based).
        None entries for missing translations.
    """
    results: List[Optional[str]] = [None] * expected

    if not raw:
        return results

    cleaned = raw.strip()

    # Strategy 1: Extract JSON from markdown code fences anywhere in response
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        # Strategy 2: Find the first '[' and last ']' to extract JSON array
        first_bracket = cleaned.find("[")
        last_bracket = cleaned.rfind("]")
        if first_bracket != -1 and last_bracket > first_bracket:
            cleaned = cleaned[first_bracket : last_bracket + 1]

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
) -> str:
    """Translate a single text string via the bridge.

    Intended for chat / real-time translation.

    Args:
        text: Source text to translate.
        target_language: Target ISO language code.
        source_language: Source ISO language code (default 'en').

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

        result = _dispatch("translate", prompt)
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
    source_label: str = "platform",
) -> Dict[str, int]:
    """Upsert translation results into the translations table.

    Uses ON CONFLICT (source_label, key, language) so the same key can exist
    across different products/sites without collision.

    Args:
        results: List of {"key": str, "translation": str, "success": bool}.
        language: Target language code.
        model: Model used for translation.
        source_label: Product/site label (e.g. "platform", "website_creed").

    Returns:
        Dict with counts: {"inserted": N, "updated": N, "failed": N}
    """
    counts = {"inserted": 0, "updated": 0, "failed": 0}

    if not results:
        return counts

    try:
        conn = _get_db()
        try:
            cur = conn.cursor()

            for item in results:
                if not item.get("success", False):
                    counts["failed"] += 1
                    continue

                try:
                    cur.execute(
                        """
                        INSERT INTO translations (source_label, key, language, text,
                                                  generated_by, source, status,
                                                  created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, 'ai_generated', 'approved',
                                NOW(), NOW())
                        ON CONFLICT (source_label, key, language) DO UPDATE SET
                            text = EXCLUDED.text,
                            generated_by = EXCLUDED.generated_by,
                            status = 'approved',
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS is_insert
                        """,
                        (source_label, item["key"], language, item["translation"], model),
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
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
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
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT key, text
                FROM translations
                WHERE language = %s AND status = 'approved'
                ORDER BY key
                """,
                (language,),
            )
            result = {row[0]: row[1] for row in cur.fetchall()}
            return result
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
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
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE source = 'human_edited') AS human_edited
                FROM translations
                WHERE language = %s
                """,
                (language,),
            )
            row = cur.fetchone()

            if row:
                return {
                    "total": row[0],
                    "approved": row[1],
                    "pending": row[2],
                    "rejected": row[3],
                    "human_edited": row[4],
                }
            return {"total": 0, "approved": 0, "pending": 0, "rejected": 0, "human_edited": 0}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.error("get_translation_stats failed for %s: %s", language, e)
        return {"total": 0, "approved": 0, "pending": 0, "rejected": 0, "human_edited": 0}
