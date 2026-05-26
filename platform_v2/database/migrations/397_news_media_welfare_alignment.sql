-- Migration 397: News & Media Welfare Alignment (T3167 follow-up)
--
-- 1. Upgrade V.E.R.I.F.Y.-B skills so dispatcher routes fact_check/bias_analysis to it
-- 2. Seed agent_overflow_skills bids for V.E.R.I.F.Y.-B + B.I.A.S. (enabled=false so
--    T3167 dynamic_skill_activation job auto-enables when queue depth >= HIGH_WATER=5)
-- All changes are idempotent.

-- ── V.E.R.I.F.Y.-B (id=370) skill upgrades ──────────────────────────────────

-- Raise fact_check from Lv3 → Lv4 so it scores competitively vs V.E.R.I.F.Y. (Lv5)
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES (370, 'fact_check', 4, NULL)
ON CONFLICT (agent_id, skill_name)
DO UPDATE SET proficiency_level = GREATEST(agent_skills.proficiency_level, 4),
              updated_at = NOW();

-- Add bias_analysis Lv4 (V.E.R.I.F.Y. has Lv4, B.I.A.S. has Lv5 — B.I.A.S. still wins)
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES (370, 'bias_analysis', 4, NULL)
ON CONFLICT (agent_id, skill_name)
DO UPDATE SET proficiency_level = GREATEST(agent_skills.proficiency_level, 4),
              updated_at = NOW();

-- Add classify Lv3 so V.E.R.I.F.Y.-B can absorb classify overflow
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES (370, 'classify', 3, NULL)
ON CONFLICT (agent_id, skill_name)
DO UPDATE SET proficiency_level = GREATEST(agent_skills.proficiency_level, 3),
              updated_at = NOW();

-- ── Overflow bids: V.E.R.I.F.Y.-B (id=370) ─────────────────────────────────
-- enabled=false — T3167 job auto-enables when fact_check queue depth >= 5

INSERT INTO agent_overflow_skills (agent_id, capability, bid_priority, enabled)
VALUES
    (370, 'fact_check',      8, false),
    (370, 'fact_check_backlog', 6, false),
    (370, 'bias_analysis',   7, false),
    (370, 'classify',        5, false)
ON CONFLICT (agent_id, capability)
DO UPDATE SET bid_priority = EXCLUDED.bid_priority,
              updated_at   = NOW();

-- ── Overflow bids: B.I.A.S. (id=49) ─────────────────────────────────────────
-- B.I.A.S. has bias_analysis Lv5 but may be winding_down; overflow bid lets
-- T3167 activate it when bias queue is hot and welfare gate passes.

INSERT INTO agent_overflow_skills (agent_id, capability, bid_priority, enabled)
VALUES
    (49, 'bias_analysis', 9, false),
    (49, 'bias_quick',    8, false)
ON CONFLICT (agent_id, capability)
DO UPDATE SET bid_priority = EXCLUDED.bid_priority,
              updated_at   = NOW();

-- ── Overflow bids: L.O.C.A.L. (id=361) ─────────────────────────────────────
-- L.O.C.A.L. has geo_extraction Lv5 but is winding_down; overflow bid provides
-- a T3167-managed geo overflow path when geo queue is hot.

INSERT INTO agent_overflow_skills (agent_id, capability, bid_priority, enabled)
VALUES
    (361, 'geo_extraction', 9, false),
    (361, 'geo_quick',      8, false)
ON CONFLICT (agent_id, capability)
DO UPDATE SET bid_priority = EXCLUDED.bid_priority,
              updated_at   = NOW();
