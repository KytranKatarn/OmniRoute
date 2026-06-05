-- 419: widen agent_rotation_log.reason from VARCHAR(50) to VARCHAR(255).
-- The 50-char limit silently broke EVERY shift-state transition whose reason text
-- exceeded 50 chars — most visibly A.R.C.H.I.E.'s 12h COO mandatory-rest enforcement
-- ("A.R.C.H.I.E. COO: 12h welfare threshold — C.R.E.E.D. mandatory rest" = 67 chars),
-- which crashed with "value too long for type character varying(50)" so no agent was
-- ever actually rested at the 12h C.R.E.E.D. threshold. KB #270619.
-- Idempotent: widening is always safe to re-run.
ALTER TABLE agent_rotation_log ALTER COLUMN reason TYPE VARCHAR(255);
