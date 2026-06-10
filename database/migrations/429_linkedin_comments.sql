-- 429: LinkedIn comment ingestion for S.I.G.N.A.L. reply integration (#3964, read scope)
-- Stores comments scraped (READ-only) from posts we authored or commented on,
-- so the engagement monitor can surface replies needing our attention and
-- (later, WRITE scope) draft+approve+send replies. Idempotent.

CREATE TABLE IF NOT EXISTS linkedin_comments (
    id              SERIAL PRIMARY KEY,
    post_url        TEXT NOT NULL,
    post_log_id     INTEGER REFERENCES linkedin_post_log(id) ON DELETE SET NULL,
    comment_urn     TEXT,                  -- LinkedIn data-id/urn when present
    dedup_key       TEXT NOT NULL,         -- urn, or hash(author|text) fallback
    author          TEXT,
    author_headline TEXT,
    body            TEXT,
    is_reply        BOOLEAN DEFAULT FALSE, -- nested reply vs top-level comment
    commented_at    TEXT,                  -- LinkedIn's relative/absolute stamp as scraped
    account         TEXT DEFAULT 'kytran', -- which of our accounts owns the thread
    seen            BOOLEAN DEFAULT FALSE, -- surfaced to a human yet
    reply_status    TEXT DEFAULT 'none',   -- none|drafted|approved|sent|skipped (WRITE scope)
    draft_reply     TEXT,                  -- R.O.S.E.T.T.A./S.I.G.N.A.L. draft (WRITE scope)
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ DEFAULT NOW()
);

-- One row per comment per post (dedup on scrape re-runs).
CREATE UNIQUE INDEX IF NOT EXISTS uq_linkedin_comments_post_dedup
    ON linkedin_comments (post_url, dedup_key);

-- Fast "what needs attention" query.
CREATE INDEX IF NOT EXISTS idx_linkedin_comments_unseen
    ON linkedin_comments (seen, first_seen_at DESC);

COMMENT ON TABLE linkedin_comments IS
    'READ-scope comment ingestion for #3964 S.I.G.N.A.L. reply integration. '
    'Populated by services/linkedin_comment_monitor.py via the linkedin_post_comments browser skill.';
