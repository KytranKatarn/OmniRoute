"""Backfill all heuristic bias scores with v2 scorer.

Run once: python -m ingest.backfill_bias_v2
Skips LLM-analyzed rows (analyzed_by != 'heuristic').
"""
import os
import sys
import time
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ingest.bias import score_bias

DATABASE_URL = os.environ["WTF_DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
SCHEMA = os.environ.get("WTF_SCHEMA", "wtf")
BATCH = 200


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(f"""
        SELECT a.id, a.title, a.body, bs.id AS score_id, bs.heuristic_version
        FROM {SCHEMA}.articles a
        JOIN {SCHEMA}.bias_scores bs ON bs.article_id = a.id
        WHERE bs.analyzed_by = 'heuristic'
        ORDER BY a.id
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"Found {total} heuristic-scored articles to backfill with v2.")

    updated = 0
    skipped = 0
    for i, row in enumerate(rows):
        if row["heuristic_version"] == "v3":
            skipped += 1
            continue

        result = score_bias(row["title"] or "", row["body"] or "")
        cur.execute(f"""
            UPDATE {SCHEMA}.bias_scores
            SET band = %s, score = %s, rationale = %s, heuristic_version = %s
            WHERE id = %s
        """, (result["band"], result["score"], result["rationale"],
              result["heuristic_version"], row["score_id"]))
        updated += 1

        if updated % BATCH == 0:
            conn.commit()
            pct = (i + 1) / total * 100
            print(f"  {updated} updated ({pct:.1f}%) …")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. {updated} updated, {skipped} already v2, {total} total.")


if __name__ == "__main__":
    main()
