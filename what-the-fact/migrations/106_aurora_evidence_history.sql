-- A.U.R.O.R.A. immutable retrieval history.
-- Preserve source observations and every materially different source version,
-- separately from when WTF retrieved/ingested it. Operational receipt is
-- intentionally nullable: public-feed availability does not prove receipt by
-- an agency or decision-maker.

CREATE TABLE IF NOT EXISTS wtf.aurora_capture_run (
    id              bigserial PRIMARY KEY,
    dataset_key     text NOT NULL,
    source_url      text NOT NULL,
    started_at      timestamptz NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    status          text NOT NULL CHECK (status IN ('complete', 'partial', 'failed')),
    record_count    integer NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_aurora_capture_run_dataset_time
    ON wtf.aurora_capture_run (dataset_key, retrieved_at DESC);

CREATE TABLE IF NOT EXISTS wtf.aurora_source_version (
    id                  bigserial PRIMARY KEY,
    dataset_key         text NOT NULL,
    source_record_key   text NOT NULL,
    source_url          text NOT NULL,
    payload_sha256      char(64) NOT NULL,
    source_observed_at  timestamptz,
    source_published_at timestamptz,
    operational_received_at timestamptz,
    first_retrieved_at  timestamptz NOT NULL,
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    payload             jsonb NOT NULL,
    raw_payload         text,
    UNIQUE (dataset_key, source_record_key, payload_sha256)
);
CREATE INDEX IF NOT EXISTS idx_aurora_source_version_source_time
    ON wtf.aurora_source_version (dataset_key, source_observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_aurora_source_version_first_retrieved
    ON wtf.aurora_source_version (dataset_key, first_retrieved_at DESC);

CREATE TABLE IF NOT EXISTS wtf.aurora_capture_run_record (
    capture_run_id      bigint NOT NULL REFERENCES wtf.aurora_capture_run(id),
    source_version_id   bigint NOT NULL REFERENCES wtf.aurora_source_version(id),
    PRIMARY KEY (capture_run_id, source_version_id)
);
CREATE INDEX IF NOT EXISTS idx_aurora_capture_run_record_version
    ON wtf.aurora_capture_run_record (source_version_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON wtf.aurora_capture_run,
            wtf.aurora_source_version, wtf.aurora_capture_run_record FROM wtfuser;
        GRANT SELECT, INSERT ON wtf.aurora_capture_run,
            wtf.aurora_source_version, wtf.aurora_capture_run_record TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_capture_run_id_seq,
            wtf.aurora_source_version_id_seq TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('106', '106_aurora_evidence_history.sql',
        'Append-only A.U.R.O.R.A. source retrieval and version history', now())
ON CONFLICT (version) DO NOTHING;
