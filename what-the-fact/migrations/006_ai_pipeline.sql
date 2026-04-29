-- 006_ai_pipeline.sql — WTF 2.0 AI pipeline columns + geo_reports

ALTER TABLE wtf.articles
    ADD COLUMN IF NOT EXISTS province_code VARCHAR(2),
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS lat DECIMAL(9,6),
    ADD COLUMN IF NOT EXISTS lng DECIMAL(9,6),
    ADD COLUMN IF NOT EXISTS geo_scope VARCHAR(20) DEFAULT 'national' NOT NULL,
    ADD COLUMN IF NOT EXISTS ai_analyzed BOOLEAN DEFAULT FALSE NOT NULL,
    ADD COLUMN IF NOT EXISTS ai_analyzed_at TIMESTAMP;

ALTER TABLE wtf.bias_scores
    ADD COLUMN IF NOT EXISTS analyzed_by VARCHAR(20) DEFAULT 'heuristic',
    ADD COLUMN IF NOT EXISTS trigger_phrases JSONB,
    ADD COLUMN IF NOT EXISTS confidence DECIMAL(4,3);

ALTER TABLE wtf.fact_checks
    ADD COLUMN IF NOT EXISTS analyzed_by VARCHAR(20) DEFAULT 'heuristic',
    ADD COLUMN IF NOT EXISTS claims JSONB,
    ADD COLUMN IF NOT EXISTS overall_verdict VARCHAR(50) CHECK (overall_verdict IN ('verified', 'mostly_true', 'mixed', 'disputed', 'unverifiable', NULL));

CREATE TABLE IF NOT EXISTS wtf.geo_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    province_coverage JSONB,
    outlet_province_matrix JSONB,
    news_deserts JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_province ON wtf.articles(province_code);
CREATE INDEX IF NOT EXISTS idx_articles_ai_pending ON wtf.articles(id) WHERE ai_analyzed = FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_reports_date ON wtf.geo_reports(report_date);
