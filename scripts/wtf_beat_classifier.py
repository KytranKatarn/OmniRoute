"""
wtf_beat_classifier.py — LLM beat classification backfill for wtf.articles.

Classifies 15 articles per dispatcher call using classify capability → I.R.I.S. / qwen25-classify.
Updates wtf.articles.beat column. Safe to re-run and to run in parallel.

Parallelism: launch multiple instances simultaneously — each atomically claims exclusive
batches via FOR UPDATE SKIP LOCKED so workers never duplicate work. The DHQ dispatcher
naturally load-balances across all fleet nodes that have qwen25-classify loaded.

Run (background, 1 worker):
  docker exec archie_platform sh -c 'setsid python3 -u /mnt/archie_brain/scripts/wtf_beat_classifier.py >> /mnt/archie_brain/scripts/beat_clf.log 2>&1 < /dev/null &'

Run (3 parallel workers, one per GPU node):
  for i in 0 1 2; do
    docker exec archie_platform sh -c "setsid python3 -u /mnt/archie_brain/scripts/wtf_beat_classifier.py --worker $i >> /mnt/archie_brain/scripts/beat_clf.log 2>&1 < /dev/null &"
  done

If a worker crashes mid-batch, reset stale claims:
  docker exec archie_database psql -U wtfuser -d wtf -c "UPDATE wtf.articles SET beat = NULL WHERE beat = '__pending__';"
"""

import argparse
import json
import logging
import sys
import time

# Script runs from /mnt/archie_brain/scripts/ — patch path before any platform imports.
# Inside archie_platform container: platform_v2/ is mounted at /app; ai_bridge at its host path.
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/app")

import psycopg2
import psycopg2.extras
from tools.department_hq.services.department_dispatcher import dispatch  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_DSN = (
    "host=archie_database port=5432 dbname=wtf "
    "user=wtfuser password=254a0029e4ef0da001800347b6c73fd1bfbd78d95a52451c8fd3822a24417662"
)
BATCH_SIZE = 15
SLEEP_BETWEEN_BATCHES = 0.5  # seconds — brief pause; fleet nodes handle concurrency

CLAIMING_SENTINEL = "__pending__"  # temporary marker while a batch is in-flight

VALID_BEATS = frozenset(
    {
        # Original 10
        "climate",
        "crime",
        "economy",
        "education",
        "foreign-policy",
        "healthcare",
        "housing",
        "immigration",
        "indigenous",
        "parliament",
        # Added — complete news outlet taxonomy
        "arts-culture",  # arts, entertainment, media industry, film, music
        "business",  # corporate news, M&A, stock markets, company earnings
        "justice",  # courts, sentencing, trials, legal proceedings (post-incident)
        "labour",  # unions, strikes, collective bargaining, workplace
        "municipal",  # city/town councils, local governance, community
        "science-tech",  # research, AI, cybersecurity, space, innovation
        "sports",  # teams, athletics, events, recreation
        "transportation",  # roads, transit, infrastructure, aviation, rail
    }
)
BEATS_LIST = ", ".join(sorted(VALID_BEATS))


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(description="WTF beat classifier backfill")
    p.add_argument(
        "--worker",
        type=int,
        default=0,
        help="Worker index (0-based) — used only in log labels. Each instance claims "
        "exclusive batches via DB locking regardless of this value.",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(worker_id: int):
    fmt = f"%(asctime)s [W{worker_id}] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("beat-classifier")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_conn():
    return psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


def count_untagged(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM wtf.articles WHERE beat IS NULL OR beat = %s",
            (CLAIMING_SENTINEL,),
        )
        return cur.fetchone()["n"]


def claim_batch(conn) -> list:
    """
    Atomically claim up to BATCH_SIZE untagged articles.

    Uses FOR UPDATE SKIP LOCKED so concurrent workers never pick the same rows.
    Sets beat = '__pending__' as a claim marker; caller must call save_beats()
    to replace with real values (or NULL on parse failure).

    Returns list of dicts: [{"id": .., "title": .., "excerpt": ..}, ...]
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH batch AS (
                SELECT id
                FROM wtf.articles
                WHERE beat IS NULL
                ORDER BY id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE wtf.articles
            SET beat = %s
            WHERE id IN (SELECT id FROM batch)
            RETURNING id, title, LEFT(body, 400) AS excerpt
            """,
            (BATCH_SIZE, CLAIMING_SENTINEL),
        )
        rows = cur.fetchall()
    conn.commit()
    return list(rows)


def save_beats(conn, updates: list):
    """
    updates: [(beat_or_None, article_id), ...]
    Replaces the __pending__ marker with the real beat (or NULL if unparseable).
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE wtf.articles SET beat = %s WHERE id = %s",
            updates,
            page_size=50,
        )
    conn.commit()


def cleanup_stale_claims(conn, log):
    """Reset any __pending__ rows left by a previous crashed worker."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wtf.articles SET beat = NULL WHERE beat = %s RETURNING id",
            (CLAIMING_SENTINEL,),
        )
        stale = cur.rowcount
    conn.commit()
    if stale:
        log.warning("Cleaned up %d stale __pending__ claims from previous run", stale)


# ---------------------------------------------------------------------------
# LLM classification via DHQ dispatcher
# ---------------------------------------------------------------------------


def classify_batch(articles: list, log) -> list:
    """Returns list of beat strings (or None) same length as articles."""
    lines = []
    for i, a in enumerate(articles, 1):
        title = (a["title"] or "").strip()
        excerpt = (a["excerpt"] or "").strip().replace("\n", " ")[:300]
        lines.append(f"{i}. {title} | {excerpt}")

    n = len(articles)
    prompt = (
        f"Classify these {n} Canadian news articles into beats.\n"
        f"Valid beats: {BEATS_LIST}\n"
        f'Use "none" if no beat fits.\n\n'
        "Articles:\n"
        + "\n".join(lines)
        + f"\n\nReturn ONLY a JSON array of {n} strings, one per article, same order:\n"
        '["beat_or_none", ...]'
    )

    try:
        result = dispatch(
            capability="classify",
            prompt=prompt,
            module_id="wtf_beat_backfill",
            json_mode=True,
        )
    except Exception as exc:
        log.warning("Dispatcher error: %s — marking batch None", exc)
        return [None] * n

    if not result.success:
        log.warning("Dispatch failed: %s — marking batch None", result.error)
        return [None] * n

    raw = (result.response or "").strip()

    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(raw[start : end + 1])
            except Exception:
                pass

    if not isinstance(parsed, list):
        log.warning("Unparseable response (id=%d): %s", articles[0]["id"], raw[:120])
        return [None] * n

    beats = []
    for item in parsed:
        if isinstance(item, str):
            b = item.strip().lower()
            beats.append(b if b in VALID_BEATS else None)
        else:
            beats.append(None)

    # Pad/trim to match batch length
    while len(beats) < n:
        beats.append(None)
    return beats[:n]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()
    log = setup_logging(args.worker)

    conn = get_conn()

    # Clean up any stale claims from a previously crashed worker
    cleanup_stale_claims(conn, log)

    total = count_untagged(conn)
    log.info("Beat classifier starting — %d unclassified articles to process", total)

    processed = 0
    tagged = 0
    t0 = time.time()

    while True:
        batch = claim_batch(conn)
        if not batch:
            log.info("No more untagged articles — worker done.")
            break

        beats = classify_batch(batch, log)
        updates = [(beat, row["id"]) for row, beat in zip(batch, beats)]
        save_beats(conn, updates)

        processed += len(batch)
        tagged += sum(1 for b in beats if b)

        # Progress every ~150 articles
        if processed % 150 < BATCH_SIZE or processed >= total:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = total - processed
            eta_m = remaining / rate / 60 if rate > 0 else 0
            pct = processed / total * 100 if total else 0
            log.info(
                "[%d/%d | %.0f%%] %d beats assigned | %.1f art/s | ETA ~%.0fm",
                processed,
                total,
                pct,
                tagged,
                rate,
                eta_m,
            )

        time.sleep(SLEEP_BETWEEN_BATCHES)

    elapsed = time.time() - t0
    log.info(
        "Done — %d articles processed in %.0fs | %d beats assigned | %d unmatched (NULL)",
        processed,
        elapsed,
        tagged,
        processed - tagged,
    )
    conn.close()


if __name__ == "__main__":
    main()
