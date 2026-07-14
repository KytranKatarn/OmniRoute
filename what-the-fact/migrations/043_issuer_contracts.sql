-- 043_issuer_contracts.sql
-- The "Contract -> Market" chain link (project #373 Link 6, Market Slice M2).
--
-- A small, refreshable rollup of federal contract awards won by each TSX-listed
-- company, mirrored FROM Gov Watch (which owns the procurement data) via
-- GET /api/internal/issuer-contract-rollup and cached here so What The Fact /
-- Market Watch can sit a listed company's federal-contract footprint beside its
-- ticker + the entity-graph market_reaction_to link (already live). The graph
-- carries the STRUCTURAL "is a federal contractor" edge; this table carries the
-- DOLLAR amount the graph lacks.
--
-- Upsert-only mirror CACHE, never the source ledger. Keyed by ticker, matching
-- securities.issuers, so consumers join with no extra normalization.

CREATE TABLE IF NOT EXISTS securities.issuer_contracts (
    ticker            text PRIMARY KEY,
    name              text,
    exchange          text,
    jv                boolean     NOT NULL DEFAULT false,
    total             bigint      NOT NULL DEFAULT 0,
    n                 integer     NOT NULL DEFAULT 0,
    by_fy             jsonb       NOT NULL DEFAULT '{}'::jsonb,
    window_start      date,
    window_end        date,
    source            text,
    refreshed_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE securities.issuer_contracts IS
    'Refreshable rollup of federal contract awards won by each TSX-listed company, '
    'mirrored from Gov Watch (CanadaBuys award notices) — the #373 Contract->Market '
    'chain link (dollar footprint). Upsert-only cache; jv=true totals are an upper '
    'bound (joint ventures the company leads). Never the source ledger.';

-- wtfuser grants (this migration is applied as archie; wtfuser gets nothing by
-- default). Upsert-only — NO DELETE on public financial records. Idempotent + guarded.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT SELECT, INSERT, UPDATE ON securities.issuer_contracts TO wtfuser;
    END IF;
END$$;
