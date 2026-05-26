-- Migration 399: C.R.E.E.D. Ethics Snapshots + Governance Infrastructure
--
-- Supports:
--   #3235 — daily per-department ethics score history (trend charts, SLA baseline)
--   #3240 — welfare SLA breach/resolution event types in governance_audit_log
--
-- All DDL is idempotent.

-- ── creed_ethics_snapshots ───────────────────────────────────────────────────
-- One row per (date, department) — written nightly by Job #132.
-- Unique constraint allows ON CONFLICT upsert for safe re-runs.

CREATE TABLE IF NOT EXISTS creed_ethics_snapshots (
    id                  SERIAL PRIMARY KEY,
    snapshot_date       DATE          NOT NULL,
    department          TEXT          NOT NULL,
    score               INTEGER       NOT NULL CHECK (score BETWEEN 0 AND 100),
    grade               TEXT          NOT NULL,
    success_rate        DECIMAL(5,2)  NOT NULL DEFAULT 0,
    high_stress_agents  INTEGER       NOT NULL DEFAULT 0,
    avg_stress          DECIMAL(5,3)  NOT NULL DEFAULT 0,
    welfare_status      TEXT          NOT NULL DEFAULT 'green',
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS creed_ethics_snapshots_date_dept
    ON creed_ethics_snapshots (snapshot_date, department);

CREATE INDEX IF NOT EXISTS creed_ethics_snapshots_dept_date
    ON creed_ethics_snapshots (department, snapshot_date DESC);

-- ── governance_report_cache ──────────────────────────────────────────────────
-- Stores quarterly governance report payloads (JSON) for the API to serve.
-- Written by Job #133 on first day of each quarter.

CREATE TABLE IF NOT EXISTS creed_governance_reports (
    id           SERIAL PRIMARY KEY,
    quarter      TEXT          NOT NULL UNIQUE,   -- e.g. '2026-Q2'
    report_json  JSONB         NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Ensure governance_audit_log accepts new SLA event types (no constraint to relax,
-- just documenting the new event_type values used by Job #132):
--   welfare_sla_breach   — dept score < 70 for 2+ consecutive days
--   welfare_sla_resolved — dept score recovers to >= 70
--   creed_ethics_snapshot_done — daily snapshot completed summary
--   creed_quarterly_report — quarterly report generated
