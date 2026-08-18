-- 051: indexes for /search full-text + the /activity event feed (#5720).
--
-- /search measured 45s+ per query (guaranteed edge 504): the route computed
-- to_tsvector(title||body) per-row over 107,994 articles with no index.
-- The expression GIN below serves the route's WHERE clause — the query
-- expression must stay byte-identical to this definition.
--
-- /activity measured 20-36s/view: ~40 whole-table COUNTs + a 6-branch
-- UNION ALL feed sorting ~800k rows per request. The route now caches the
-- stats bundle (5-min TTL) and pre-sorts/caps each feed branch; the ts
-- indexes below make each branch an index-ordered top-N and speed the
-- 24h-window stats.
--
-- Applied live 2026-08-18 with CREATE INDEX CONCURRENTLY (no write lock).
-- Plain form below for fresh installs. No GRANTs needed (indexes carry no
-- ACLs).

-- /search: expression FTS index (route: consumer/routes.py search()).
CREATE INDEX IF NOT EXISTS idx_articles_fts
    ON wtf.articles USING GIN (
        to_tsvector('english', COALESCE(title,'') || ' ' || COALESCE(body,''))
    );

-- /activity feed branches + 24h stats windows.
CREATE INDEX IF NOT EXISTS idx_audit_trail_event_created
    ON wtf.audit_trail (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bias_scores_computed
    ON wtf.bias_scores (computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_fact_checks_checked
    ON wtf.fact_checks (checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_story_clusters_created
    ON wtf.story_clusters (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_created
    ON wtf.summaries (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_ai_analyzed_at
    ON wtf.articles (ai_analyzed_at DESC)
    WHERE ai_analyzed_at IS NOT NULL;
