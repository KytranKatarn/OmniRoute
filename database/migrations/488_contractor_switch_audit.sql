-- Operator audit trail for contractor switches (DS9 PR 5)
--
-- WHY
-- ---
-- `contractor_providers` has TWO operator switches and, until now, no record of either being
-- turned. `is_active` (configured) and `dispatchable` (the dispatcher may route here) are both
-- flipped from the Contractors tab, and both write a single `updated_at`. That gives you the
-- last change and nothing else: not which switch, not what it changed from, not who.
--
-- This matters more than usual here, because `dispatchable` is a money switch. A paid provider
-- with `dispatchable=true` receives real traffic. Being unable to answer "who turned that on,
-- and was it intentional" after the fact is not an acceptable gap for that switch.
--
-- It is also a direct consequence of a bug this work already fixed. The routing toggle used to
-- write a fabricated probe observation (`probe_kind='health'`, `status='ok'`) into
-- `contractor_health` to record the decision. That was wrong: `contractor_health` is a history
-- of PROBE OBSERVATIONS, and `probe_kind` is CHECK-constrained to ('health','latency','full'),
-- so the schema already refused to express it honestly. That write was removed (#3653) rather
-- than relabelled, and this table is the honest home it needed.
--
-- DISTINCT FROM contractor_health
-- ---------------------------
--   contractor_health        what a PROBE observed. Written by a machine. Never says "ok"
--                            unless a request actually succeeded.
--   contractor_switch_audit  what an OPERATOR decided. Written by a human action.
--
-- A decision is not an observation. Keeping them apart is the entire point: one forged the
-- other's facts.
--
-- Idempotent via IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS contractor_switch_audit (
    id              BIGSERIAL PRIMARY KEY,
    provider_key    VARCHAR(50) NOT NULL,
    -- which operator switch moved. Deliberately a closed vocabulary, for the same reason
    -- contractor_health constrains its own: an unconstrained column here would eventually
    -- carry a typo and quietly become a third thing nobody queries.
    switch_name     VARCHAR(20) NOT NULL,
    from_value      BOOLEAN,
    to_value        BOOLEAN NOT NULL,
    -- Who did it. current_user.username at request time; NULL when the row was written by a
    -- non-request path (a migration or a backfill), so "nobody" is distinguishable from
    -- "somebody we failed to record".
    actor           VARCHAR(150),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contractor_switch_audit_switch_chk
        CHECK (switch_name IN ('is_active', 'dispatchable'))
);

-- The only read pattern is "what happened to THIS provider, newest first" — the row's own
-- expand panel. provider_key alone would serve that and is all that is needed; created_at is
-- carried so a future all-providers timeline does not need another index.
CREATE INDEX IF NOT EXISTS idx_contractor_switch_audit_provider
    ON contractor_switch_audit (provider_key, created_at DESC);

COMMIT;
