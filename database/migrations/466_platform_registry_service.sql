-- 466_platform_registry_service.sql — Living Platform Registry, Phase 2 (task #5230)
--
-- WHY
-- .claude/rules/operational-state.md carries a hand-typed table of ~28 services
-- (port / subdomain / container / host). It is the same failure class as the
-- module index: it drifts, and agents act on it. It already needed manual
-- corrections for NPM (decommissioned), the CORS proxy (stopped), and the hub's
-- stale public IP — each discovered by someone tripping over it.
--
-- Two live sources, deliberately kept distinct because they answer different
-- questions and fail differently:
--
--   * DOCKER      — what is actually running on the hub, right now.
--   * PROVENANCE  — for the 9 image-baked products, does the RUNNING image match
--                   the source it claims? Reuses scripts/deploy_drift_check.py
--                   check_products(), which is already the provenance SSOT
--                   (daily deploy_drift_monitor job + the F.O.R.G.E. Dockerfile
--                   guard + the Repair Bay tab all read it). Building a second
--                   drift checker here would create exactly the divergence this
--                   registry exists to eliminate.
--
-- FAIL-OPEN IS INHERITED, NOT REINVENTED. check_products() reports 'fail_open'
-- when a product is unreachable or has no resolvable expected SHA — that is NOT
-- drift, and must never be rendered as one. An unreachable product is an
-- unknown, and an unknown reported as a fault is how alert fatigue starts.

CREATE TABLE IF NOT EXISTS platform_registry_service (
    service_key       TEXT PRIMARY KEY,   -- container name, or product key for remote products

    -- ---- classification
    kind              TEXT        NOT NULL DEFAULT 'container'
                                  CHECK (kind IN ('container', 'product')),
    host              TEXT,               -- 'hub' | mesh IP for remote products

    -- ---- collected from the docker daemon (hub only)
    container_name    TEXT,
    image             TEXT,
    container_state   TEXT,               -- running | exited | created | ...
    restart_policy    TEXT,
    compose_project   TEXT,
    compose_service   TEXT,
    ports             JSONB       NOT NULL DEFAULT '[]'::jsonb,
    started_at        TIMESTAMPTZ,

    -- ---- collected from check_products() (products only; NULL for plain containers)
    version_url       TEXT,
    baked_sha         TEXT,
    expected_sha      TEXT,
    drift_status      TEXT        CHECK (drift_status IN ('in_sync', 'drift', 'fail_open')),
    provenance_at     TIMESTAMPTZ,        -- when drift was last MEASURED, not when the row was touched

    -- ---- human-owned. The collector must never write this (same rule as modules).
    notes             TEXT,

    -- ---- lifecycle. Never deleted; a vanished service is the interesting event.
    status            TEXT        NOT NULL DEFAULT 'present'
                                  CHECK (status IN ('present', 'absent')),
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prs_status ON platform_registry_service (status);
CREATE INDEX IF NOT EXISTS idx_prs_kind   ON platform_registry_service (kind);
CREATE INDEX IF NOT EXISTS idx_prs_drift  ON platform_registry_service (drift_status)
    WHERE drift_status IS NOT NULL;

COMMENT ON TABLE platform_registry_service IS
    'Derived registry of running services (task #5230 phase 2). Docker daemon + '
    'deploy_drift_check.check_products(). Rows are never deleted — a vanished '
    'service becomes status=absent so the disappearance stays visible.';
COMMENT ON COLUMN platform_registry_service.drift_status IS
    'From check_products(). fail_open = unreachable or no resolvable expected SHA. '
    'That is an UNKNOWN, never a fault — do not render it as drift.';
COMMENT ON COLUMN platform_registry_service.provenance_at IS
    'When drift was last MEASURED. Distinct from collected_at: a cheap container-only '
    'collection leaves this untouched, so a stale provenance reading cannot masquerade '
    'as a fresh one.';
COMMENT ON COLUMN platform_registry_service.notes IS
    'Human-owned. The collector MUST NOT overwrite this column.';
