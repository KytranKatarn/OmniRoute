-- SP2 #1875: rolling aggregate outlet bias scores
CREATE TABLE IF NOT EXISTS wtf.outlet_bias_scores (
    id              SERIAL PRIMARY KEY,
    source_id       INTEGER      NOT NULL UNIQUE REFERENCES wtf.sources(id),
    article_count   INTEGER      NOT NULL DEFAULT 0,
    avg_score       REAL         NOT NULL DEFAULT 0.0,
    band            VARCHAR(16)  NOT NULL DEFAULT 'center',
    window_days     INTEGER      NOT NULL DEFAULT 30,
    computed_at     TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT outlet_bias_band_check CHECK (
        band IN ('left','center-left','center','center-right','right')
    )
);
