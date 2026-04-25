-- SP2: add rss_feed and bias_lean to wtf.sources
ALTER TABLE wtf.sources
    ADD COLUMN IF NOT EXISTS rss_feed  VARCHAR(512),
    ADD COLUMN IF NOT EXISTS bias_lean VARCHAR(16)
        CHECK (bias_lean IN ('left','center-left','center','center-right','right'));
