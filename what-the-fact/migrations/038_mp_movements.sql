-- Migration 038: Parliamentary change-history ("movements") capture
-- Project #348 — WTF previously captured NO change history for MPs/senators:
--   the OpenParliament/senate sync was upsert-only, is_current was never set
--   false, and cabinet_role was a manual hand-seed with no source.  This table
--   is the append-only audit trail of every detected roster/role change, written
--   by ingest/parliament/{openparl,senators,cabinet}.py during the weekly sync.
-- Run: psql $WTF_DATABASE_URL < 038_mp_movements.sql   (idempotent)

CREATE TABLE IF NOT EXISTS parliament.mp_movements (
    id            BIGSERIAL PRIMARY KEY,
    subject_type  TEXT NOT NULL,             -- 'mp' | 'senator'
    subject_slug  TEXT,                      -- parliament.mps.slug / parliament.senators.slug
    subject_id    BIGINT,                    -- parliament.mps.id / parliament.senators.id (nullable)
    name          TEXT,                      -- denormalized name at time of detection
    movement_type TEXT NOT NULL,             -- appointed | departed | party_change | riding_change | cabinet_change
    before_value  JSONB,                     -- prior state (NULL for appointments)
    after_value   JSONB,                     -- new state  (NULL for pure departures if desired)
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mp_movements_detected ON parliament.mp_movements (detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_mp_movements_subject  ON parliament.mp_movements (subject_type);
CREATE INDEX IF NOT EXISTS ix_mp_movements_slug     ON parliament.mp_movements (subject_type, subject_slug);
