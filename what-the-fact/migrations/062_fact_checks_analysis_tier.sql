-- 062 — persist the analysis tier ON the fact_check row.
--
-- THE PROBLEM: a SYNTHESIZED verdict is indistinguishable from an adjudicated one.
--
-- ingest/tier_router._factcheck_tier1_only() says so in its own docstring:
--
--     "Tier 1 only extracted claim text — fill verdict=unverifiable + empty
--      reasoning so the row is valid but clearly marked as Tier-1-only
--      (consumer can show badge)."
--     ... "_tier_synthesized": True
--
-- The intent is right and the flag is set — but `_tier_synthesized` is NEVER
-- PERSISTED. Every writer stores claim/verdict/evidence/overall_verdict and
-- drops it, so the badge the docstring promises cannot be rendered: nothing in
-- wtf.fact_checks distinguishes "we checked and could not verify" from "the
-- gate declined to check at all".
--
-- Tier 1 is CLAIM EXTRACTION ONLY — its prompt literally reads "Extract up to 3
-- factual claims from this article. No verdict, no reasoning." When the
-- escalation gate skips tier 2, the synthesized `unverifiable` is a placeholder,
-- not a finding.
--
-- MEASURED 2026-08-31, joining fact_checks to articles.analysis_tier:
--     quick_v1              87,964  unverifiable rows   1.9% have evidence
--     quick_v1+full         25,971                      7.7%
--     quick_v1_failed+full   2,364                      9.6%
--     pending                1,347                     99.8%
--
-- ~88,000 of the 117,646 remaining `unverifiable` verdicts were NEVER
-- FACT-CHECKED. The headline "84.6% unverifiable" was never a quality signal —
-- it was mostly COVERAGE: how often the gate declined to escalate.
--
-- ⚠️ BACKFILL IS APPROXIMATE, AND DELIBERATELY SO.
-- articles.analysis_tier is the article's CURRENT tier, not necessarily the tier
-- in force when a given fact_check row was written; an article re-analysed later
-- carries the newer value. It is close in practice because every writer DELETEs
-- its own prior rows before inserting, so a row and its article usually move
-- together. It is still an INFERENCE, which is why backfilled rows are marked
-- with a `~` prefix — a reader can tell a reconstructed tier from one recorded
-- at write time. Forward writes (PR to follow) record the real value unprefixed.
--
-- ⚠️ New wtf tables/columns must GRANT to wtfuser — apps do not connect as owner.

SET lock_timeout = '3s';

-- 1. the column. ADD COLUMN with no DEFAULT is metadata-only in PG11+ — no
--    table rewrite, no long lock, safe on a table taking continuous writes.
ALTER TABLE wtf.fact_checks ADD COLUMN IF NOT EXISTS analysis_tier VARCHAR(40);

COMMENT ON COLUMN wtf.fact_checks.analysis_tier IS
  'How this verdict was produced. quick_v1 = TIER 1 ONLY: claims were extracted but NEVER verified, and overall_verdict is a SYNTHESIZED placeholder (ingest/tier_router._factcheck_tier1_only) — do NOT render it as an adjudication. quick_v1+full / quick_v1_failed+full = tier 2 actually ran. direct = DHQ job, full check with no tier gating. on_demand = Deep Dive. A leading ~ means the value was RECONSTRUCTED by migration 062 from articles.analysis_tier, not recorded at write time.';

-- 2. backfill, batched per writer (see migration 060 on FIFO lock queues).
--    ~ prefix = reconstructed, not recorded.
UPDATE wtf.fact_checks f SET analysis_tier = '~' || a.analysis_tier
  FROM wtf.articles a
 WHERE a.id = f.article_id
   AND f.analysis_tier IS NULL
   AND f.analyzed_by = 'llm_v1'
   AND a.analysis_tier IS NOT NULL;

UPDATE wtf.fact_checks f SET analysis_tier = '~' || a.analysis_tier
  FROM wtf.articles a
 WHERE a.id = f.article_id
   AND f.analysis_tier IS NULL
   AND f.analyzed_by = 'V.E.R.I.F.Y.'
   AND a.analysis_tier IS NOT NULL;

-- The DHQ jobs bypass the tier router entirely — they dispatch a full factcheck
-- directly, which is why dhq_v1 shows only 0.2% missing evidence against
-- llm_v1's 98%. 'direct' is the honest label; it is NOT tier-gated and NOT
-- synthesized, so it carries no ~ prefix ambiguity about which tier ran.
UPDATE wtf.fact_checks SET analysis_tier = '~direct'
 WHERE analysis_tier IS NULL AND analyzed_by IN ('dhq_v1', 'dhq_backlog_v1');

UPDATE wtf.fact_checks f SET analysis_tier = '~' || a.analysis_tier
  FROM wtf.articles a
 WHERE a.id = f.article_id
   AND f.analysis_tier IS NULL
   AND a.analysis_tier IS NOT NULL;   -- any remaining writer

-- 3. the query that matters: "is this verdict real?" — partial index keeps it cheap.
CREATE INDEX IF NOT EXISTS idx_fact_checks_tier_synthesized
    ON wtf.fact_checks (article_id)
 WHERE analysis_tier IN ('quick_v1', '~quick_v1');

GRANT SELECT ON wtf.fact_checks TO wtfuser;
