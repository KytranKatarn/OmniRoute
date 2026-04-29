-- 007_score_flags.sql — WTF 2.0 Radical Transparency: user error-flagging

CREATE TABLE IF NOT EXISTS wtf.score_flags (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES wtf.articles(id) ON DELETE CASCADE,
    user_ip VARCHAR(45) NOT NULL,
    flag_type VARCHAR(50) NOT NULL CHECK (flag_type IN ('bias_wrong', 'fact_wrong', 'geo_wrong', 'other')),
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_score_flags_article ON wtf.score_flags(article_id);
CREATE INDEX IF NOT EXISTS idx_score_flags_created ON wtf.score_flags(created_at DESC);
