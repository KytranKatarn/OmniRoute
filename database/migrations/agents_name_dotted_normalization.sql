-- #2164 Phase 2: normalize agents.name to dotted acronym form.
-- Prep work in Phase 1 (PR #193) updated all hardcoded plain-form
-- caller strings to dotted — the agent_service cache rebuilds with
-- dotted keys on platform restart, matching what callers now pass.
--
-- Scope: AI agents only (worker_type='ai'), non-decommissioned,
-- whose display_name is already in dotted form (contains '.'),
-- and whose name is NOT already in dotted form (excludes M.A.V.E.N.,
-- P.R.O.B.E., W.A.T.C.H. which are already correct).

UPDATE agents
SET name = display_name,
    updated_at = NOW()
WHERE worker_type = 'ai'
  AND shift_state != 'decommissioned'
  AND name != display_name
  AND display_name LIKE '%.%'
  AND name NOT LIKE '%.%';
