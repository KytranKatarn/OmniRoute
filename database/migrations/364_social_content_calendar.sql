-- Migration 364: Agent Social Presence Engine Phase 2
-- Creates social_content_calendar (weekly slots) and agent_social_voice (extended voice settings)
-- Seeds 3 default weekly slots: Mon=Live the Dream, Wed=Wellness, Fri=Build & Innovate

CREATE TABLE IF NOT EXISTS social_content_calendar (
    id SERIAL PRIMARY KEY,
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    slot_order SMALLINT DEFAULT 0,
    theme_id INTEGER REFERENCES social_content_themes(id),
    featured_agent_id INTEGER REFERENCES agents(id),
    auto_generate BOOLEAN DEFAULT false,
    time_of_day TIME DEFAULT '09:00:00',
    platform VARCHAR(50) DEFAULT 'linkedin',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (day_of_week, slot_order)
);

CREATE TABLE IF NOT EXISTS agent_social_voice (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER UNIQUE REFERENCES agents(id),
    post_frequency_per_week SMALLINT DEFAULT 2,
    sample_phrases TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scc_day ON social_content_calendar(day_of_week);
CREATE INDEX IF NOT EXISTS idx_asv_agent ON agent_social_voice(agent_id);

-- Seed 3 default weekly slots
INSERT INTO social_content_calendar (day_of_week, slot_order, theme_id, featured_agent_id, auto_generate, time_of_day)
VALUES
  (0, 0, (SELECT id FROM social_content_themes WHERE slug='live-dream'),       (SELECT id FROM agents WHERE name='S.I.G.N.A.L.' LIMIT 1), false, '09:00:00'),
  (2, 0, (SELECT id FROM social_content_themes WHERE slug='wellness-healing'), (SELECT id FROM agents WHERE name='V.I.T.A.L.' LIMIT 1),   false, '10:00:00'),
  (4, 0, (SELECT id FROM social_content_themes WHERE slug='build-innovate'),   (SELECT id FROM agents WHERE name='F.O.R.G.E.' LIMIT 1),   false, '09:00:00')
ON CONFLICT (day_of_week, slot_order) DO NOTHING;
