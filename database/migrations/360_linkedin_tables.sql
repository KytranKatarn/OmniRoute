-- Migration 360: LinkedIn automation tables
-- Part of S.I.G.N.A.L. LinkedIn brain feature

-- Track all posts made by the browser agent
CREATE TABLE IF NOT EXISTS linkedin_post_log (
    id                  SERIAL PRIMARY KEY,
    content             TEXT NOT NULL,
    hashtags            TEXT[] DEFAULT '{}',
    post_type           VARCHAR(50) DEFAULT 'personal', -- personal, company
    company_slug        VARCHAR(100),
    post_url            TEXT,
    image_path          TEXT,
    agent_id            INT REFERENCES agents(id) ON DELETE SET NULL,
    approval_id         INT,                             -- autonomy_approval_queue.id
    status              VARCHAR(50) DEFAULT 'posted',   -- posted, failed, draft
    impressions         INT,
    reactions           INT,
    comments            INT,
    shares              INT,
    analytics_fetched_at TIMESTAMPTZ,
    posted_at           TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_linkedin_post_log_posted ON linkedin_post_log (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_linkedin_post_log_status  ON linkedin_post_log (status);

-- Hashtag performance tracking for S.I.G.N.A.L. rotation
CREATE TABLE IF NOT EXISTS linkedin_hashtag_stats (
    id               SERIAL PRIMARY KEY,
    hashtag          VARCHAR(100) UNIQUE NOT NULL,
    usage_count      INT DEFAULT 0,
    last_used        TIMESTAMPTZ,
    avg_engagement   DECIMAL(8,2) DEFAULT 0,
    total_impressions BIGINT DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Seed default hashtag pool for Kytran Empowerment / A.R.C.H.I.E.
INSERT INTO linkedin_hashtag_stats (hashtag) VALUES
    ('AI'), ('ArtificialIntelligence'), ('MachineLearning'), ('Automation'),
    ('BuildingInPublic'), ('IndieHacker'), ('Montreal'), ('Canada'),
    ('GovTech'), ('Procurement'), ('Compliance'), ('AIEthics'),
    ('SaaS'), ('TechStartup'), ('Entrepreneur'), ('Leadership'),
    ('ARCHIE'), ('KytranEmpowerment'), ('CREED'), ('GovWatch')
ON CONFLICT (hashtag) DO NOTHING;

-- Connection outreach queue for Gov Watch targets
CREATE TABLE IF NOT EXISTS linkedin_outreach_queue (
    id              SERIAL PRIMARY KEY,
    profile_url     TEXT UNIQUE NOT NULL,
    name            VARCHAR(200),
    company         VARCHAR(200),
    title           VARCHAR(200),
    location        VARCHAR(200),
    status          VARCHAR(50) DEFAULT 'pending',
    -- pending → connect_requested → connected → message_sent → replied → converted
    connect_note    TEXT,
    follow_up_msg   TEXT,
    source          VARCHAR(100) DEFAULT 'manual', -- gov_watch, linkedin_search, manual
    connected_at    TIMESTAMPTZ,
    messaged_at     TIMESTAMPTZ,
    replied_at      TIMESTAMPTZ,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_linkedin_outreach_status   ON linkedin_outreach_queue (status);
CREATE INDEX IF NOT EXISTS idx_linkedin_outreach_source   ON linkedin_outreach_queue (source);
CREATE INDEX IF NOT EXISTS idx_linkedin_outreach_created  ON linkedin_outreach_queue (created_at DESC);
