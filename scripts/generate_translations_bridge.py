#!/usr/bin/env python3
"""
Generate translations for all non-EN languages via the Bridge.

Per ADR-013: ALL LLM calls route through BridgeDispatcher.
This ensures agent assignment, IAAE governance, HR tracking,
and dashboard AI Insights.

Usage (inside Docker):
    python3 /mnt/archie_brain/scripts/generate_translations_bridge.py
"""

import sys
import os
import time

# Ensure ai_bridge modules are importable
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain")

from ai_bridge.translation_service import (
    batch_translate,
    store_translations,
    SUPPORTED_LANGUAGES,
    BATCH_SIZE,
)

# DB access
import psycopg2
import psycopg2.extras


def get_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def get_english_keys():
    """Fetch all English translation keys."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, text FROM translations WHERE language = 'en' ORDER BY key")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def main():
    languages = [lang for lang in SUPPORTED_LANGUAGES if lang != "en"]
    en_keys = get_english_keys()
    total_keys = len(en_keys)

    print(f"=== Bridge Translation Generator ===")
    print(f"Languages: {', '.join(languages)}")
    print(f"Keys per language: {total_keys}")
    print(f"Batches per language: {(total_keys + BATCH_SIZE - 1) // BATCH_SIZE}")
    print(f"Total batches: {len(languages) * ((total_keys + BATCH_SIZE - 1) // BATCH_SIZE)}")
    print()

    # Build strings list: (key, english_text, context)
    strings = [(key, text, "") for key, text in en_keys]

    overall_start = time.time()

    for lang in languages:
        lang_name = SUPPORTED_LANGUAGES[lang]
        print(f"\n=== {lang_name} ({lang}) ===")
        lang_start = time.time()

        # Check if already has translations
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM translations WHERE language = %s", (lang,))
        existing = cur.fetchone()[0]
        cur.close()
        conn.close()

        if existing >= total_keys:
            print(f"  Already has {existing} translations, skipping.")
            continue
        elif existing > 0:
            print(f"  Has {existing}/{total_keys} translations, generating remaining...")

        print(f"  Translating {total_keys} keys via bridge...")

        # batch_translate routes through bridge dispatcher
        results = batch_translate(strings, lang)

        success_count = sum(1 for r in results if r.get("success"))
        fail_count = sum(1 for r in results if not r.get("success"))

        # Store results
        # Get the model used from the last bridge execution log
        model_used = "bridge-routed"
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT model_used FROM task_execution_log
                WHERE module_source = 'consciousness_linguistics'
                  AND capability = 'translate'
                ORDER BY created_at DESC LIMIT 1
            """
            )
            row = cur.fetchone()
            if row:
                model_used = row[0]
            cur.close()
            conn.close()
        except Exception:
            pass

        counts = store_translations(results, lang, model_used)
        lang_elapsed = time.time() - lang_start

        print(f"  Done: {success_count} translated, {fail_count} failed")
        print(f"  Stored: {counts['inserted']} new, {counts['updated']} updated, {counts['failed']} failed")
        print(f"  Time: {lang_elapsed:.0f}s ({lang_elapsed/60:.1f}m)")
        sys.stdout.flush()

    overall_elapsed = time.time() - overall_start
    print(f"\n=== Complete ===")
    print(f"Total time: {overall_elapsed:.0f}s ({overall_elapsed/60:.1f}m)")

    # Final stats
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT language, COUNT(*) as count,
               COUNT(*) FILTER (WHERE source = 'ai_generated') as ai,
               COUNT(*) FILTER (WHERE status = 'pending_review') as pending
        FROM translations
        GROUP BY language
        ORDER BY language
    """
    )
    print("\nFinal translation counts:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} total ({row[2]} AI, {row[3]} pending)")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
