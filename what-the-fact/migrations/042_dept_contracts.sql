-- 042_dept_contracts.sql
-- The "Contract" chain link (project #373: Money -> MP -> ... -> Contract).
--
-- A small, refreshable rollup of federal contract awards by the canonical
-- department a minister leads, mirrored FROM Gov Watch (the owner of the
-- procurement data) via GET /api/internal/dept-contract-rollup and cached here
-- so the WTF cost pages + civic-watch can sit a minister's office cost beside
-- the federal contract volume their portfolio oversees. Portfolio-level and
-- approximate; the honesty caveats live with the source (Gov Watch) and the
-- display layer. This is an upsert-only mirror CACHE, never the source ledger.
--
-- Keyed by canonical department name == parliament.minister_travel.owner_org's
-- English half, so the cost model joins with no extra normalization.

CREATE TABLE IF NOT EXISTS parliament.dept_contracts (
    canonical_dept    text PRIMARY KEY,
    total             bigint      NOT NULL DEFAULT 0,
    n                 integer     NOT NULL DEFAULT 0,
    by_fy             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    central_purchaser boolean     NOT NULL DEFAULT false,
    window_start      date,
    window_end        date,
    source            text,
    refreshed_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE parliament.dept_contracts IS
    'Refreshable rollup of federal contract awards by canonical minister-portfolio '
    'department, mirrored from Gov Watch (CanadaBuys award notices) — the #373 '
    'Contract chain link. Upsert-only cache; never the source ledger.';

-- wtfuser grants (this migration is applied as archie; wtfuser gets nothing by
-- default). Upsert-only — NO DELETE on public financial records. Idempotent + guarded.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE ON parliament.dept_contracts TO wtfuser;
    END IF;
END$$;
