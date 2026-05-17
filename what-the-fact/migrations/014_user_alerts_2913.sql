-- 014_user_alerts_2913.sql
-- Custom alerts (#2913): topic/keyword/politician tracking with email digest.
-- Subscriber-gated; UI lives at consumer /alerts.
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS wtf.user_alerts (
    id             SERIAL PRIMARY KEY,
    user_email     VARCHAR(200) NOT NULL,
    keyword        VARCHAR(120) NOT NULL,
    -- Optional: filter to a specific source slug, bias band, or province
    source_slug    VARCHAR(80),
    bias_band      VARCHAR(20),
    province_code  VARCHAR(2),
    -- Lifecycle
    active         BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT NOW(),
    last_sent_at   TIMESTAMP,
    last_match_id  INTEGER REFERENCES wtf.articles(id) ON DELETE SET NULL,
    sent_count     INTEGER DEFAULT 0,
    -- Cardinality guards (per-user)
    CONSTRAINT user_alerts_unique_per_user UNIQUE (user_email, keyword, source_slug, bias_band, province_code)
);

CREATE INDEX IF NOT EXISTS idx_user_alerts_email_active
    ON wtf.user_alerts(user_email) WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_alerts_keyword_active
    ON wtf.user_alerts(keyword) WHERE active = TRUE;

COMMENT ON TABLE wtf.user_alerts IS
    'User-configured alert rules. Digest worker scans new articles per cycle, matches keyword (and optional bias/source/province filter), emails the user with batched matches.';

COMMENT ON COLUMN wtf.user_alerts.last_sent_at IS
    'Last successful digest send. Worker uses this as the floor when scanning for new matches — only articles ingested after this timestamp count.';

COMMENT ON COLUMN wtf.user_alerts.last_match_id IS
    'wtf.articles.id of the most recent article that matched this alert (for debug / display in management UI).';
