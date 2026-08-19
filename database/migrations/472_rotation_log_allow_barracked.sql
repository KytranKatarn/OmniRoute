-- 472: agent_rotation_log must be able to record a BENCH (#5829)
--
-- WHY: `agent_rotation_log.valid_shift_state` allowed only
--   active | winding_down | cooldown | off_duty
-- so 'barracked' — the bench — was UNRECORDABLE. Consequences, all measured
-- 2026-08-19:
--   * agent_service.transition_shift_state() carries a ROTATION_LOG_STATES
--     tuple that silently SKIPS logging for a barracked transition;
--   * agent_service.reactivate_agent() therefore had to use a raw UPDATE;
--   * so EVERY bench in the platform's history left no trace at all.
-- Four agents (P.U.B.L.I.S.H. 582 runs/24h, C.O.D.E.X. 173, G.A.V.E.L. 59,
-- P.R.O.B.E. 41) sat 'barracked' while actively working, excluded from
-- skill-based selection but still served by pinned paths. With no rotation
-- row and no open rest cycle there was NO WAY to tell a deliberate bench from
-- an accident — the audit trail could not represent the state.
--
-- 'decommissioned' is deliberately NOT added: it is a terminal lifecycle
-- state, not a shift rotation, and reactivate_agent() already reports it via
-- its own return value.
--
-- Idempotent + reversible (see the DOWN note at the bottom).

-- Live table: the platform writes rotations continuously, and ALTER TABLE needs
-- ACCESS EXCLUSIVE. Fail FAST rather than queue behind writers and block them —
-- a migration that waits on a lock is a migration that takes the app down with it.
SET lock_timeout = '5s';
SET statement_timeout = '30s';

BEGIN;
ALTER TABLE agent_rotation_log DROP CONSTRAINT IF EXISTS valid_shift_state;

ALTER TABLE agent_rotation_log
    ADD CONSTRAINT valid_shift_state
    CHECK (shift_state IN ('active', 'winding_down', 'cooldown', 'off_duty', 'barracked'));
COMMIT;

COMMENT ON CONSTRAINT valid_shift_state ON agent_rotation_log IS
    'Shift states recordable as a rotation. barracked added 2026-08-19 (#5829) — '
    'a bench with no audit row is indistinguishable from an accident.';

-- DOWN (manual, only if no barracked rows exist):
--   DELETE FROM agent_rotation_log WHERE shift_state = 'barracked';
--   ALTER TABLE agent_rotation_log DROP CONSTRAINT valid_shift_state;
--   ALTER TABLE agent_rotation_log ADD CONSTRAINT valid_shift_state
--     CHECK (shift_state IN ('active','winding_down','cooldown','off_duty'));
