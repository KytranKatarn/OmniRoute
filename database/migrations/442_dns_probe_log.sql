-- 442_dns_probe_log.sql — External-DNS resolution monitor (Task #4571)
-- Captures the recurring OAuth/platform.claude.com DNS failure live: one row per
-- ~2-min probe cycle. classification = healthy | adguard_fail | network_fail |
-- control_only_fail. Idempotent.

CREATE TABLE IF NOT EXISTS dns_probe_log (
    id             BIGSERIAL PRIMARY KEY,
    probed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    classification TEXT NOT NULL,   -- healthy | adguard_fail | network_fail | control_only_fail
    severity       TEXT NOT NULL,   -- info | warning | error
    results        JSONB,           -- per-name {name, adguard:{ok,rcode,rcode_name,ip,ms}, control:{...}, status}
    ip_forward     INT,             -- best-effort container-view snapshot, nullable
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_dns_probe_log_probed_at ON dns_probe_log (probed_at DESC);
CREATE INDEX IF NOT EXISTS idx_dns_probe_log_severity  ON dns_probe_log (severity, probed_at DESC);
