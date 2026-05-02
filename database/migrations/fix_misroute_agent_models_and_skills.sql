-- Fix misroute audit: 3 high-failure agent/capability pairs
-- 2026-05-02 — PR #475
--
-- 1. S.C.R.O.L.L. (id=332) had knowledge_analysis Lv1 with gemma2-cpu:latest
--    → 600s timeouts. Remove the skill so S.P.E.C.T.R.A. (Lv5, mistral:7b)
--    wins instead. S.C.R.O.L.L.'s strength is research/text_analysis, not
--    knowledge analysis.
--
-- 2. L.O.C.A.L. (id=361) uses llama3.2:3b for geo_extraction → 22% silent
--    failures (empty responses). Upgrade to mistral:7b for reliable
--    structured JSON extraction.
--
-- 3. R.E.S.O.L.V.E. (id=142) uses qwen2.5:1.5b for conversation → 42%
--    timeout failures at 90s under Ollama queue load. Upgrade to qwen2.5:7b
--    for more reliable responses. conversation/chat now also mapped to
--    Customer Success & Support in CAPABILITY_DEPARTMENT_MAP.

DELETE FROM agent_skills
WHERE agent_id = 332 AND skill_name = 'knowledge_analysis';

UPDATE agents SET model = 'mistral:7b'   WHERE id = 361; -- L.O.C.A.L.
UPDATE agents SET model = 'qwen2.5:7b'  WHERE id = 142; -- R.E.S.O.L.V.E.
