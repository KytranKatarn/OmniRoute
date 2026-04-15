-- ============================================================
-- LLM Ecosystem Redesign — AI Agent Roster Restructure
-- Decision #441
-- ============================================================

BEGIN;

-- 1. Reinstate A.R.C.H.I.E. — COO, dolphin3-8k, uncensored
UPDATE agents SET
    shift_state = 'active',
    model = 'dolphin3-8k:latest',
    title = 'Chief Operations Officer & Platform Director'
WHERE id = 2 AND name = 'ARCHIE';

-- 2. Reinstate F.O.R.G.E. — Senior Engineer
UPDATE agents SET
    shift_state = 'active',
    title = 'Senior Engineer & Self-Healing Pipeline'
WHERE id = 136 AND name = 'FORGE';

-- 3. Reassign models — purpose-matched per department capability
-- Engineering gets best coder
UPDATE agents SET model = 'deepseek-coder-v2:16b' WHERE id = 340 AND name = 'P.R.O.B.E.';

-- Security & HR get real reasoning (gemma3:12b)
UPDATE agents SET model = 'gemma3:12b' WHERE id = 3 AND name = 'VIGIL';
UPDATE agents SET model = 'gemma3:12b' WHERE id = 145 AND name = 'KIN';

-- Research & Legal get strong reasoning (phi4:14b)
UPDATE agents SET model = 'phi4:14b' WHERE id = 140 AND name = 'DARWIN';
UPDATE agents SET model = 'phi4:14b' WHERE id = 147 AND name = 'GAVEL';

-- News & Media — fact-checking needs reasoning, creative needs uncensored
UPDATE agents SET model = 'gemma3:12b' WHERE id = 48 AND name = 'fact';
UPDATE agents SET model = 'dolphin3:latest' WHERE id = 23 AND name = 'ink';

-- Fix ghost models (qwen2.5:7b not on disk)
UPDATE agents SET model = 'gemma2:9b' WHERE id = 332 AND name = 'scroll';
UPDATE agents SET model = 'llama3.2:3b' WHERE id = 331 AND name = 'heritage';

-- Vision specialist gets proper vision model
UPDATE agents SET model = 'qwen2.5vl:7b' WHERE id = 334 AND name = 'visage';

-- 4. Convert 5 acronym internals to worker_type='ai'
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 32 AND name = 'MARKET';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 126 AND name = 'EMBER';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 150 AND name = 'SHIELD';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 336 AND name = 'ethos';
UPDATE agents SET worker_type = 'ai', is_department_ai = true WHERE id = 337 AND name = 'ARMADA';

-- Assign models to newly converted AI agents
UPDATE agents SET model = 'mistral:7b' WHERE id = 32 AND name = 'MARKET';
UPDATE agents SET model = 'llama3.2:3b' WHERE id = 126 AND name = 'EMBER';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 150 AND name = 'SHIELD';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 336 AND name = 'ethos';
UPDATE agents SET model = 'gemma2:9b' WHERE id = 337 AND name = 'ARMADA';

-- 5. Set News & Media floor to CREATIVE
UPDATE agents SET floor = 'CREATIVE' WHERE department = 'News & Media' AND floor IS DISTINCT FROM 'CREATIVE';

COMMIT;
