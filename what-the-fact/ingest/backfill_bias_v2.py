"""Backfill all heuristic bias scores with v2 scorer.

Run once: python -m ingest.backfill_bias_v2
Skips LLM-analyzed rows (analyzed_by != 'heuristic').
"""

import os
import sys
import time
import psycopg2
import psycopg2.extras
from psycopg2 import sql

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ingest.bias import score_bias

SCHEMA = os.environ.get("WTF_SCHEMA", "wtf")
BATCH = 200


def main():
    database_url = os.environ["WTF_DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql.SQL("""
                SELECT a.id, a.title, a.body, bs.id AS score_id, bs.heuristic_version
                FROM {schema}.articles a
                JOIN {schema}.bias_scores bs ON bs.article_id = a.id
                WHERE bs.analyzed_by = 'heuristic'
                ORDER BY a.id
            """).format(schema=sql.Identifier(SCHEMA)))
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
                cur.execute(
                    sql.SQL("""
                    UPDATE {schema}.bias_scores
                    SET band = %s, score = %s, rationale = %s, heuristic_version = %s
                    WHERE id = %s
                """).format(schema=sql.Identifier(SCHEMA)),
                    (
                        result["band"],
                        result["score"],
                        result["rationale"],
                        result["heuristic_version"],
                        row["score_id"],
                    ),
                )
                updated += 1

                if updated % BATCH == 0:
                    conn.commit()
                    pct = (i + 1) / total * 100
                    print(f"  {updated} updated ({pct:.1f}%) …")

            conn.commit()
    finally:
        conn.close()
    print(f"\nDone. {updated} updated, {skipped} already v2, {total} total.")


if __name__ == "__main__":
    main()
