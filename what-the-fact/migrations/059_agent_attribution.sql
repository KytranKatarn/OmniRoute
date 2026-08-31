-- 059 — record WHICH AGENT produced a fact-check / bias score.
--
-- WHY A NEW COLUMN RATHER THAN REUSING AN EXISTING ONE
-- Both candidates are already carrying other meanings, and overloading either
-- one breaks something that works:
--
--   analyzed_by  is a dedup SELECTOR. platform_v2/tools/department_hq/jobs.py
--                :4516 runs `DELETE FROM wtf.fact_checks WHERE article_id = %s
--                AND analyzed_by = 'dhq_v1'` before re-inserting, and :4570
--                filters on it too. Put an agent name there and the DELETE stops
--                matching -> duplicate fact-checks.
--
--   checker      is already three things at once. Measured over 30 days:
--                fact_v1 76,837 · GoogleFCT:none 28,949 · V.E.R.I.F.Y. 11,028 ·
--                heuristic-v1 4,686 · GoogleFCT:Snopes / AFP / Washington Post…
--                The GoogleFCT:* rows are EXTERNAL PARTNER fact-checks — real
--                third-party sources, not agents. Folding agents in here would
--                erase the partner distinction the column exists to record.
--
-- SEMANTICS OF THIS COLUMN
-- agent_name is the A.R.C.H.I.E. agent that actually performed the work, as
-- reported by the dispatcher. NULL means NOT RECORDED — it does not mean
-- "V.E.R.I.F.Y.", and nothing should default it to a name.
--
-- Historical rows stay NULL on purpose. The dispatcher's choice was discarded at
-- write time, so it cannot be recovered from this database; /activity renders
-- those as "pipeline — agent not recorded" rather than guessing. Inferring a
-- name from task_execution_log timestamps would put a fabricated attribution on
-- a public transparency page, which is worse than admitting the gap.
--
-- Context: over 7 days V.E.R.I.F.Y. performed only 19% of fact_checks —
-- P.R.O.O.F., E.C.H.O., V.E.T., A.X.I.O.M., C.O.N.D.U.I.T., T.A.L.O.N. and
-- R.A.N.G.E.R. did the rest, and every one was published as "V.E.R.I.F.Y."

-- ⚠️ LOCK GUARD — DO NOT REMOVE.
-- wtf.fact_checks is written continuously by the live pipeline (measured ~31
-- rows / 10 min, plus a DELETE-then-reinsert per article). ALTER TABLE needs
-- ACCESS EXCLUSIVE, and a Postgres lock queue is FIFO: an ALTER that has to WAIT
-- puts itself at the head of the queue and every subsequent reader and writer
-- stacks up behind it. Running this without a timeout blocked the ingest
-- pipeline for over two minutes on 2026-08-31 before it was cancelled.
--
-- With lock_timeout the ALTER fails fast instead of building a queue. Re-run the
-- file until it succeeds — every statement is IF NOT EXISTS / idempotent.
SET lock_timeout = '3s';

ALTER TABLE wtf.fact_checks  ADD COLUMN IF NOT EXISTS agent_name TEXT;
ALTER TABLE wtf.bias_scores  ADD COLUMN IF NOT EXISTS agent_name TEXT;

COMMENT ON COLUMN wtf.fact_checks.agent_name IS
  'A.R.C.H.I.E. agent that performed this check, per the dispatcher. NULL = not recorded (do not default to a name). Distinct from checker (pipeline version / external partner) and analyzed_by (dedup selector).';
COMMENT ON COLUMN wtf.bias_scores.agent_name IS
  'A.R.C.H.I.E. agent that produced this score, per the dispatcher. NULL = not recorded (do not default to a name).';

-- Partial indexes: /activity groups by agent over a recent window, and the vast
-- majority of existing rows are NULL, so indexing only the attributed ones keeps
-- these small while they backfill naturally with new work.
CREATE INDEX IF NOT EXISTS idx_fact_checks_agent_checked
  ON wtf.fact_checks (agent_name, checked_at DESC) WHERE agent_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bias_scores_agent_computed
  ON wtf.bias_scores (agent_name, computed_at DESC) WHERE agent_name IS NOT NULL;

-- wtfuser is the app role; new wtf tables/columns must be granted to it or the
-- app reads fail while the owner's psql session works fine (migration 047).
GRANT SELECT, INSERT, UPDATE ON wtf.fact_checks TO wtfuser;
GRANT SELECT, INSERT, UPDATE ON wtf.bias_scores TO wtfuser;
