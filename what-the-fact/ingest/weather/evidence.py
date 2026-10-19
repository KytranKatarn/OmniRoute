"""Append-only source capture helpers for A.U.R.O.R.A. environmental feeds."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text


def capture_source_records(conn, *, dataset_key, source_url, started_at, rows):
    """Persist a retrieval and immutable source versions plus run links.

    PostgreSQL JSON recordsets keep large point feeds to a few statements per
    run. Re-fetches link to the original immutable payload version.
    """
    retrieved_at = datetime.now(timezone.utc)
    run_id = conn.execute(
        text("""
        INSERT INTO wtf.aurora_capture_run
            (dataset_key, source_url, started_at, retrieved_at,
             status, record_count)
        VALUES (:dataset_key, :source_url, :started_at, :retrieved_at,
                'complete', :count)
        RETURNING id
    """),
        {
            "dataset_key": dataset_key,
            "source_url": source_url,
            "started_at": started_at,
            "retrieved_at": retrieved_at,
            "count": len(rows),
        },
    ).scalar_one()
    if not rows:
        return {"run_id": run_id, "inserted_versions": 0}

    prepared = []
    for row in rows:
        payload_json = json.dumps(
            row["payload"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        raw_payload = row.get("raw_payload")
        digest_source = (
            raw_payload if raw_payload is not None else payload_json
        )
        prepared.append(
            {
                "dataset_key": dataset_key,
                "source_record_key": str(row["source_record_key"]),
                "source_url": row.get("source_url") or source_url,
                "payload_sha256": hashlib.sha256(
                    digest_source.encode("utf-8")
                ).hexdigest(),
                "source_observed_at": row.get("source_observed_at"),
                "source_published_at": row.get("source_published_at"),
                "first_retrieved_at": retrieved_at,
                "payload": json.loads(payload_json),
                "raw_payload": raw_payload,
            }
        )
    records_json = json.dumps(
        prepared,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    insert_result = conn.execute(
        text("""
        INSERT INTO wtf.aurora_source_version
            (dataset_key, source_record_key, source_url, payload_sha256,
             source_observed_at, source_published_at, first_retrieved_at,
             payload, raw_payload)
        SELECT x.dataset_key, x.source_record_key, x.source_url,
               x.payload_sha256, x.source_observed_at,
               x.source_published_at, x.first_retrieved_at,
               x.payload, x.raw_payload
        FROM jsonb_to_recordset(CAST(:records AS jsonb)) AS x(
            dataset_key text, source_record_key text, source_url text,
            payload_sha256 char(64), source_observed_at timestamptz,
            source_published_at timestamptz, first_retrieved_at timestamptz,
            payload jsonb, raw_payload text)
        ON CONFLICT (dataset_key, source_record_key, payload_sha256) DO NOTHING
    """),
        {"records": records_json},
    )
    conn.execute(
        text("""
        INSERT INTO wtf.aurora_capture_run_record
            (capture_run_id, source_version_id)
        SELECT :run_id, v.id
        FROM wtf.aurora_source_version v
        JOIN jsonb_to_recordset(CAST(:records AS jsonb)) AS x(
            dataset_key text, source_record_key text, payload_sha256 char(64))
          ON v.dataset_key = x.dataset_key
         AND v.source_record_key = x.source_record_key
         AND v.payload_sha256 = x.payload_sha256
        WHERE NOT EXISTS (
            SELECT 1 FROM wtf.aurora_capture_run_record prior
            WHERE prior.source_version_id = v.id
        )
        ON CONFLICT DO NOTHING
    """),
        {"run_id": run_id, "records": records_json},
    )
    return {
        "run_id": run_id,
        "inserted_versions": max(int(insert_result.rowcount or 0), 0),
    }
