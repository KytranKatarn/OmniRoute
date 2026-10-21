-- Per-node GPU lease (#7401). An image session on a fleet node (Media Studio) holds a lease for as long as
-- its SDXL checkpoint is resident; the LLM dispatcher skips leased nodes when dispatch:gpu_lease:enabled.
-- Idempotent. Acquisition always records the row (visibility); enforcement is a separate, default-OFF flag.
CREATE TABLE IF NOT EXISTS node_gpu_leases (
    node_name    TEXT PRIMARY KEY,
    holder       TEXT NOT NULL,
    holder_kind  TEXT NOT NULL DEFAULT 'image',
    acquired_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
