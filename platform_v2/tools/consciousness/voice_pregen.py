"""
Voice Pre-generation Worker
Background thread-based worker for proactive word cache building.

Supports two job types:
- manual: Top N English words + custom phrases across selected emotions
- auto_conversation: Most-used words from recent ai_conversations
"""

import threading
import time
import os
from database import _get_db_password
import logging
import psycopg2

logger = logging.getLogger(__name__)

# Top 200 English words commonly used in AI assistant responses
TOP_ENGLISH_WORDS = [
    "the",
    "be",
    "to",
    "of",
    "and",
    "a",
    "in",
    "that",
    "have",
    "I",
    "it",
    "for",
    "not",
    "on",
    "with",
    "he",
    "as",
    "you",
    "do",
    "at",
    "this",
    "but",
    "his",
    "by",
    "from",
    "they",
    "we",
    "say",
    "her",
    "she",
    "or",
    "an",
    "will",
    "my",
    "one",
    "all",
    "would",
    "there",
    "their",
    "what",
    "so",
    "up",
    "out",
    "if",
    "about",
    "who",
    "get",
    "which",
    "go",
    "me",
    "when",
    "make",
    "can",
    "like",
    "time",
    "no",
    "just",
    "him",
    "know",
    "take",
    "people",
    "into",
    "year",
    "your",
    "good",
    "some",
    "could",
    "them",
    "see",
    "other",
    "than",
    "then",
    "now",
    "look",
    "only",
    "come",
    "its",
    "over",
    "think",
    "also",
    "back",
    "after",
    "use",
    "two",
    "how",
    "our",
    "work",
    "first",
    "well",
    "way",
    "even",
    "new",
    "want",
    "because",
    "any",
    "these",
    "give",
    "day",
    "most",
    "us",
    "great",
    "help",
    "need",
    "here",
    "right",
    "still",
    "find",
    "let",
    "sure",
    "happy",
    "system",
    "data",
    "file",
    "please",
    "thanks",
    "yes",
    "hello",
    "welcome",
    "sorry",
    "understand",
    "question",
    "answer",
    "information",
    "problem",
    "solution",
    "check",
    "update",
    "status",
    "error",
    "success",
    "complete",
    "running",
    "working",
    "done",
    "platform",
    "module",
    "agent",
    "task",
    "project",
    "knowledge",
    "memory",
    "process",
    "network",
    "server",
    "database",
    "service",
    "config",
    "dashboard",
    "monitor",
    "create",
    "delete",
    "edit",
    "save",
    "load",
    "search",
    "start",
    "stop",
    "restart",
    "enable",
    "disable",
    "install",
    "deploy",
    "test",
    "debug",
    "build",
    "run",
    "today",
    "available",
    "ready",
    "active",
    "online",
    "offline",
    "pending",
    "progress",
    "warning",
    "critical",
    "healthy",
    "performance",
    "security",
    "backup",
    "report",
]

# ARCHIE-specific phrases
ARCHIE_PHRASES = [
    "Hello",
    "How can I help you today",
    "Let me check that for you",
    "I understand",
    "That's a great question",
    "Here's what I found",
    "Working on it",
    "All systems operational",
    "Task completed successfully",
    "I'm A.R.C.H.I.E.",
    "Autonomous Resource and Coordination Hub",
    "Let me think about that",
    "Good morning",
    "Good afternoon",
    "Good evening",
    "Is there anything else",
    "You're welcome",
    "Of course",
]


def auto_warmup_cache(synthesizer=None, db_conn_func=None):
    """Pre-cache common ARCHIE phrases on startup using Kokoro engine.

    Runs in a background daemon thread. Waits for Kokoro pipeline to load
    before synthesizing. Skips phrases already in cache.

    Args:
        synthesizer: VoiceSynthesizer instance (lazy-loaded if None)
        db_conn_func: Callable returning a DB connection (uses get_db if None)
    """
    import hashlib

    def _warmup():
        try:
            time.sleep(15)  # Wait for Kokoro pipeline to load first

            if synthesizer is None:
                try:
                    import sys

                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
                    from ai_bridge.voice_synthesis import get_voice_synthesizer

                    synth = get_voice_synthesizer()
                except ImportError:
                    logger.warning("[VoiceWarmup] Could not import voice synthesizer")
                    return
            else:
                synth = synthesizer

            conn_func = db_conn_func or get_db
            conn = None
            cur = None
            conn = conn_func()
            cur = conn.cursor()

            cached = 0
            skipped = 0
            for phrase in ARCHIE_PHRASES:
                # Build the same cache key the synthesizer uses (kokoro, en, neutral, af_heart)
                normalized = phrase.lower().strip()
                content = f"kokoro|en|agent:2|{normalized}|neutral"
                text_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

                cur.execute(
                    "SELECT 1 FROM voice_word_cache WHERE text_hash = %s",
                    (text_hash,),
                )
                if cur.fetchone():
                    skipped += 1
                    continue

                try:
                    # Use agent synthesis (ARCHIE = agent_id 2) for consistent cache keys
                    result = synth.synthesize_for_agent(phrase, agent_id=2, emotion="neutral")
                    if result.get("success"):
                        cached += 1
                    time.sleep(0.05)  # Throttle
                except Exception as e:
                    logger.debug(f"[VoiceWarmup] Skipped '{phrase}': {e}")

            # Lock warmup entries for immutability (reuse existing conn)
            if cached > 0:
                cur.execute(
                    """
                    UPDATE voice_word_cache
                    SET is_locked = TRUE, locked_at = NOW()
                    WHERE agent_id = 2 AND engine = 'kokoro' AND is_locked = FALSE
                """
                )
                conn.commit()

            logger.info(f"[VoiceWarmup] Done: {cached} new, {skipped} already cached")
        except Exception as e:
            logger.error(f"[VoiceWarmup] Failed: {e}")
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    t = threading.Thread(target=_warmup, daemon=True, name="voice-warmup-cache")
    t.start()


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def get_cached_words(emotion: str, agent_id=None):
    """Get set of already-cached word hashes for an emotion"""
    try:
        conn = get_db()
        cur = conn.cursor()
        if agent_id:
            cur.execute(
                """
                SELECT text_hash FROM voice_word_cache
                WHERE emotion_context = %s AND (agent_id = %s OR agent_id IS NULL)
                AND text_hash IS NOT NULL
            """,
                (emotion, agent_id),
            )
        else:
            cur.execute(
                """
                SELECT text_hash FROM voice_word_cache
                WHERE emotion_context = %s AND text_hash IS NOT NULL
            """,
                (emotion,),
            )
        hashes = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()
        return hashes
    except Exception as e:
        logger.error(f"[VoicePregen] Cache check error: {e}")
        return set()


def get_conversation_words(days: int = 30, limit: int = 200):
    """Get most-used words from recent conversations"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT response FROM ai_conversations
            WHERE created_at > NOW() - (%s * INTERVAL '1 day')
            AND response IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
        """,
            (days,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Count word frequency
        word_freq = {}
        import re

        for (response,) in rows:
            words = re.findall(r"\b[a-zA-Z]{2,}\b", response.lower())
            for w in words:
                word_freq[w] = word_freq.get(w, 0) + 1

        # Sort by frequency, return top N
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:limit]]
    except Exception as e:
        logger.error(f"[VoicePregen] Conversation words error: {e}")
        return []


def update_job_progress(job_id: int, completed: int, failed: int = 0, status: str = None, error: str = None):
    """Update pre-gen job progress in DB"""
    try:
        conn = get_db()
        cur = conn.cursor()
        if status:
            cur.execute(
                """
                UPDATE voice_pregen_jobs
                SET completed_words = %s, failed_words = %s, status = %s,
                    error_message = %s,
                    completed_at = CASE WHEN %s IN ('completed', 'failed') THEN NOW() ELSE completed_at END
                WHERE id = %s
            """,
                (completed, failed, status, error, status, job_id),
            )
        else:
            cur.execute(
                """
                UPDATE voice_pregen_jobs
                SET completed_words = %s, failed_words = %s
                WHERE id = %s
            """,
                (completed, failed, job_id),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[VoicePregen] Progress update error: {e}")


def run_pregen_job(
    job_id: int,
    words: list,
    emotions: list,
    agent_id: int = None,
    quality: str = "high",
    engine: str = "kokoro",
    language: str = "en",
):
    """
    Background worker function for pre-generation.
    Runs in a daemon thread.
    Uses 'high' quality by default since pre-gen is not time-sensitive.
    """
    import hashlib
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer, KokoroEngine
    except ImportError:
        update_job_progress(job_id, 0, 0, "failed", "Cannot import voice synthesizer")
        return

    synthesizer = get_voice_synthesizer()

    # Mark job as running
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE voice_pregen_jobs
            SET status = 'running', started_at = NOW(), total_words = %s
            WHERE id = %s
        """,
            (len(words) * len(emotions), job_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[VoicePregen] Job start error: {e}")
        return

    completed = 0
    failed = 0

    # Default voice for cache key generation
    default_voice = KokoroEngine.DEFAULT_VOICE if engine == "kokoro" else "Ana Florence"

    # Kokoro is English-only; auto-route non-English to XTTS v2
    effective_engine = engine
    if language != "en" and engine == "kokoro":
        effective_engine = "xtts_v2"

    for emotion in emotions:
        cached_hashes = get_cached_words(emotion, agent_id)

        for word in words:
            # Generate hash matching the engine+language-scoped cache key format
            if agent_id:
                content = f"{effective_engine}|{language}|agent:{agent_id}|{word}|{emotion}"
            else:
                eff_voice = KokoroEngine.DEFAULT_VOICE if effective_engine == "kokoro" else "Ana Florence"
                content = f"{effective_engine}|{language}|{word}|{emotion}|{eff_voice}"
            word_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

            if word_hash in cached_hashes:
                completed += 1
                if completed % 10 == 0:
                    update_job_progress(job_id, completed, failed)
                continue

            # Synthesize with engine, quality, and language
            try:
                if agent_id:
                    result = synthesizer.synthesize_for_agent(
                        word, agent_id, emotion, quality=quality, language=language
                    )
                else:
                    result = synthesizer.synthesize(
                        word,
                        emotion,
                        quality=quality,
                        engine=effective_engine,
                        language=language,
                    )

                if result.get("success"):
                    completed += 1
                else:
                    failed += 1
                    logger.warning(f"[VoicePregen] Failed: {word}/{emotion}: {result.get('error')}")
            except Exception as e:
                failed += 1
                logger.error(f"[VoicePregen] Error synthesizing '{word}': {e}")

            # Update progress every 5 words
            if (completed + failed) % 5 == 0:
                update_job_progress(job_id, completed, failed)

            # Small delay to avoid overloading TTS
            # Kokoro is much faster than XTTS, so needs less throttling
            time.sleep(0.02 if engine == "kokoro" else 0.1)

    # Lock all generated entries to prevent overwrites
    try:
        conn = get_db()
        cur = conn.cursor()
        if agent_id:
            cur.execute(
                """
                UPDATE voice_word_cache
                SET is_locked = TRUE,
                    locked_at = NOW(),
                    locked_with_params = (
                        SELECT jsonb_build_object(
                            'speaker', avp.speaker,
                            'speed', avp.speed,
                            'pitch_shift', avp.pitch_shift,
                            'warmth', avp.warmth,
                            'engine', avp.engine,
                            'voice_blend', avp.voice_blend
                        )
                        FROM agent_voice_profiles avp
                        WHERE avp.agent_id = %s AND avp.engine = %s AND avp.language = %s
                        LIMIT 1
                    )
                WHERE agent_id = %s AND engine = %s AND language = %s
                AND is_locked = FALSE
            """,
                (agent_id, effective_engine, language, agent_id, effective_engine, language),
            )
        else:
            cur.execute(
                """
                UPDATE voice_word_cache
                SET is_locked = TRUE, locked_at = NOW()
                WHERE agent_id IS NULL AND engine = %s AND language = %s
                AND is_locked = FALSE
            """,
                (effective_engine, language),
            )
        locked = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[VoicePregen] Locked {locked} cache entries for immutability")
    except Exception as e:
        logger.error(f"[VoicePregen] Lock error: {e}")

    # Final update
    update_job_progress(job_id, completed, failed, "completed")
    logger.info(f"[VoicePregen] Job {job_id} completed ({engine}): {completed} done, {failed} failed")


def start_pregen_job(
    job_type: str,
    word_count: int = 100,
    emotions: list = None,
    agent_id: int = None,
    custom_phrases: list = None,
    quality: str = "high",
    engine: str = "kokoro",
    language: str = "en",
) -> int:
    """
    Start a pre-generation job. Returns job ID.

    Args:
        job_type: 'manual' or 'auto_conversation'
        word_count: Number of top words to pre-generate (max 500)
        emotions: List of emotions to generate for
        agent_id: Optional agent ID for agent-specific caching
        custom_phrases: Optional additional phrases to include
        quality: Quality preset ('standard' or 'high', default 'high')
        engine: TTS engine ('kokoro' or 'xtts_v2', default 'kokoro')
        language: Language code ('en', 'fr', etc., default 'en')

    Returns:
        Job ID
    """
    if emotions is None:
        emotions = ["neutral"]

    word_count = min(word_count, 500)

    # Build word list based on job type
    if job_type == "manual":
        words = TOP_ENGLISH_WORDS[:word_count]
        if custom_phrases:
            words.extend(custom_phrases[:50])
        words.extend(ARCHIE_PHRASES)
    elif job_type == "auto_conversation":
        words = get_conversation_words(days=30, limit=word_count)
        if not words:
            words = TOP_ENGLISH_WORDS[:50]
    else:
        words = TOP_ENGLISH_WORDS[:word_count]

    # Deduplicate
    seen = set()
    unique_words = []
    for w in words:
        wl = w.lower().strip()
        if wl and wl not in seen:
            seen.add(wl)
            unique_words.append(w)
    words = unique_words

    # Create job record
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO voice_pregen_jobs (agent_id, status, job_type, total_words, engine, language)
            VALUES (%s, 'pending', %s, %s, %s, %s)
            RETURNING id
        """,
            (agent_id, job_type, len(words) * len(emotions), engine, language),
        )
        job_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[VoicePregen] Job creation error: {e}")
        raise

    # Start background thread
    thread = threading.Thread(
        target=run_pregen_job,
        args=(job_id, words, emotions, agent_id, quality, engine, language),
        daemon=True,
        name=f"voice-pregen-{job_id}",
    )
    thread.start()

    return job_id
