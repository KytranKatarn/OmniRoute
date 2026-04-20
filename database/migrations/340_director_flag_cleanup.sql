-- Migration 340: Cleanup `agents.is_department_ai` drift.
--
-- Canonical rule: 17 departments × 1 director each. Prior session drift left
-- 22 agents flagged as director across 5 departments with duplicate flags.
-- Keeping user-chosen canon:
--   · Analytics & Intelligence        → S.P.E.C.T.R.A. (demote M.A.R.K.E.T.)
--   · Documentation & Knowledge       → C.O.D.E.X.    (demote E.M.B.E.R.)
--   · Legal & Regulatory              → G.A.V.E.L.    (demote E.T.H.O.S.)
--   · Operations & Infrastructure     → B.A.S.E.      (demote A.R.M.A.D.A.)
--   · Security & Compliance           → V.I.G.I.L.    (demote S.H.I.E.L.D.)
--   · Engineering & Technology        → F.O.R.G.E.    (per user decision 2026-04-20)
--   · News & Media                    → F.A.C.T.      (per user decision 2026-04-20)
--
-- All 3 public/internal surfaces (DHQ Org Chart, DHQ Roster, public
-- /directory.html, public /ai-directors.html) read `agents.is_department_ai`
-- — this migration aligns all of them in one shot.
--
-- Related: agent_service.get_org_chart() patched in same PR to never silently
-- drop a staff member when flag drift is present (defense in depth).
--
-- Idempotent: UPDATE targets are by specific id.

UPDATE agents SET is_department_ai = false, updated_at = NOW()
WHERE id = 32;    -- M.A.R.K.E.T. — Analytics & Intelligence specialist

UPDATE agents SET is_department_ai = false, updated_at = NOW()
WHERE id = 126;   -- E.M.B.E.R. — Documentation & Knowledge specialist

UPDATE agents SET is_department_ai = false, updated_at = NOW()
WHERE id = 336;   -- E.T.H.O.S. — Legal & Regulatory specialist (C.R.E.E.D. adjacent)

UPDATE agents SET is_department_ai = false, updated_at = NOW()
WHERE id = 337;   -- A.R.M.A.D.A. — Operations & Infrastructure specialist (fleet)

UPDATE agents SET is_department_ai = false, updated_at = NOW()
WHERE id = 150;   -- S.H.I.E.L.D. — Security & Compliance specialist

-- Post-migration sanity (should print exactly 17):
-- SELECT COUNT(*) FROM agents WHERE is_department_ai = true AND status = 'active';
