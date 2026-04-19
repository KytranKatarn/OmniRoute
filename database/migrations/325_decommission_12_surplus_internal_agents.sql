-- ============================================================
-- Decommission 12 Human-Named Surplus Internal Agents
-- Project #261 task #1928 (session 2026-04-19, user-approved)
--
-- Keeps (5 dispatcher-referenced + 1 translator):
--   CodeSmith  (id=4)   Engineering default        — platform_v2/tools/department_hq/services/department_dispatcher.py:213
--   Architect  (id=5)   schema_design/api/arch      — department_dispatcher.py:214-216
--   Nexus      (id=9)   embedding/vision/knowledge  — department_dispatcher.py:228-230
--   Scholar    (id=11)  R&D default                 — department_dispatcher.py:236
--   Pixel      (id=13)  image_generation owner      — media_studio/edit_service.py + benchmark_service.py:519
--   ROSETTA    (id=134) Arabic+French translation   — reactivated in migration 324
--
-- Why: these 12 agents have 0 code references, 0 dispatched events in 30 days,
-- and are fully covered by the 34-agent AI acronym roster. Soft-decommission
-- only (shift_state='decommissioned') — skills/portraits/history preserved,
-- FK rows intact, fully reversible with a single UPDATE.
--
-- Rollback:
--   UPDATE agents SET shift_state='active' WHERE id IN
--     (24,26,28,33,34,40,41,46,55,56,93,107);
-- ============================================================

BEGIN;

UPDATE agents
SET shift_state = 'decommissioned',
    updated_at  = NOW()
WHERE id IN (
     24,  -- Juno     (Thandi Mbeki)       Infrastructure Engineer
     26,  -- Luna     (Fatima Al-Rashid)   Senior Diplomatic Advisor
     28,  -- Nova     (Isabella Fernandez) Creative Director
     33,  -- Sage     (Haruto Takahashi)   People & Culture Lead
     34,  -- Thorn    (Rowan McAllister)   Penetration Tester & Red Team Lead
     40,  -- Value    (Yuki Nakamura)      Financial Analyst
     41,  -- Tempo    (Leila Abadi)        Senior Copywriter
     46,  -- Scout    (Olumide Adeyemi)    Senior Data Scientist
     55,  -- Envoy    (Kwame Asante)       Client Success Manager
     56,  -- Dispatch (Carmen Reyes)       Logistics Coordinator
     93,  -- Zenith   (Priya Sharma)       Medical Director
    107   -- Crucible (Kenji Yamamoto)     Legal Counsel
)
AND shift_state != 'decommissioned';

-- Close any open rotation_log entries for these agents
UPDATE agent_rotation_log
SET ended_at = NOW()
WHERE agent_id IN (24,26,28,33,34,40,41,46,55,56,93,107)
  AND ended_at IS NULL;

-- Orphan-check: Envoy (55) reports to Luna (26). Luna is also decommissioned here,
-- so Envoy gets decommissioned at the same time — no dangling active subordinate.
-- (Other subordinates listed for Luna are Embassy/Liaison/Hearth, all already decommissioned.)

COMMIT;

-- Verification (run after migration):
-- SELECT id, name, shift_state, updated_at
-- FROM agents
-- WHERE id IN (24,26,28,33,34,40,41,46,55,56,93,107)
-- ORDER BY id;
-- Expected: all 12 rows with shift_state='decommissioned'.
