-- 050: indexes for the /news route rewrite (#5719).
--
-- Measured 2026-08-18 (EXPLAIN ANALYZE on the live hub wtf DB): the /news
-- rows query alone cost 14.6s cold — the newest-per-cluster correlated
-- subquery executed 107,885 times, wtf.fact_checks (357k rows) had NO
-- article_id index (~500ms hash build per hit + duplicate page rows for
-- the 86k articles with >1 non-GoogleFCT check), and JIT added 3.5s.
-- Together with the query rewrite in consumer/routes.py news() and
-- SET LOCAL jit=off, cold render drops ~8.3s -> ~0.4s.
--
-- Applied live 2026-08-18 with CREATE INDEX CONCURRENTLY (no write lock).
-- Plain form below for fresh installs. No GRANTs needed (indexes carry no
-- ACLs; tables owned by wtfuser).

-- Kills the per-hit hash build of 260k fact_checks rows; enables the
-- per-article LATERAL probe. Also benefits article pages.
CREATE INDEX IF NOT EXISTS idx_fact_checks_article
    ON wtf.fact_checks (article_id);

-- Newest-per-cluster becomes a single index descent (max cluster 1,231
-- rows was previously sorted per probe). Replaces ix_articles_cluster.
CREATE INDEX IF NOT EXISTS idx_articles_cluster_published
    ON wtf.articles (cluster_id, published_at DESC)
    WHERE cluster_id IS NOT NULL;

-- Q1 source_count 48h window: 72ms seq scan (105,935 rows removed) -> ~3ms.
CREATE INDEX IF NOT EXISTS idx_articles_ingested_at
    ON wtf.articles (ingested_at);

-- Redundant once the composite above exists (same partial predicate,
-- leading column identical).
DROP INDEX IF EXISTS wtf.ix_articles_cluster;
