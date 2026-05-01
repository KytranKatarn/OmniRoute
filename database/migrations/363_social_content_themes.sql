-- Migration 363: Agent Social Presence Engine Phase 1
-- Creates social_content_themes + social_content_scenes tables
-- Seeds 9 department themes + 27 scenes
-- Adds theme_id FK to social_video_queue

CREATE TABLE IF NOT EXISTS social_content_themes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    department VARCHAR(100),
    curator_agent_id INTEGER REFERENCES agents(id),
    tone TEXT,
    hashtags TEXT[] DEFAULT '{}',
    music_mood VARCHAR(50) DEFAULT 'uplifting',
    accent_color VARCHAR(7) DEFAULT '#8b5cf6',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_content_scenes (
    id SERIAL PRIMARY KEY,
    theme_id INTEGER REFERENCES social_content_themes(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    visual_prompt_template TEXT NOT NULL,
    style_directive TEXT,
    image_aspect VARCHAR(10) DEFAULT 'square',
    generation_type VARCHAR(20) DEFAULT 'lifestyle',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sct_slug ON social_content_themes(slug);
CREATE INDEX IF NOT EXISTS idx_scs_theme ON social_content_scenes(theme_id);

-- Seed 9 department themes
INSERT INTO social_content_themes (name, slug, department, curator_agent_id, tone, hashtags, music_mood, accent_color) VALUES
('Faith & Strength',      'faith-strength',     'Medical & Wellness',         352, 'Spiritual, hopeful, believe in yourself',          ARRAY['#FaithAndStrength','#KytranEmpowerment','#BelieveInYourself'], 'ambient',      '#f59e0b'),
('Wellness & Healing',    'wellness-healing',   'Medical & Wellness',         148, 'Nurturing, grounding, health-forward',             ARRAY['#WellnessJourney','#KytranEmpowerment','#HealingVibes'],       'calm',         '#22c55e'),
('Legal Empowerment',     'legal-empowerment',  'Legal & Regulatory',         147, 'Bold, empowering, know your rights',               ARRAY['#LegalEmpowerment','#KytranEmpowerment','#KnowYourRights'],    'professional', '#ef4444'),
('Build & Innovate',      'build-innovate',     'Engineering & Technology',   136, 'Forward-thinking, ambitious, maker energy',        ARRAY['#BuildAndInnovate','#KytranEmpowerment','#Innovation'],        'uplifting',    '#3b82f6'),
('Financial Freedom',     'financial-freedom',  'Finance & Accounting',       144, 'Smart, strategic, build legacy',                   ARRAY['#FinancialFreedom','#KytranEmpowerment','#BuildWealth'],        'professional', '#10b981'),
('Protect & Serve',       'protect-serve',      'Security & Compliance',        3, 'Protective, trustworthy, safety-first',            ARRAY['#ProtectAndServe','#KytranEmpowerment','#SecurityFirst'],      'calm',         '#6366f1'),
('Culture & People',      'culture-people',     'Human Resources & Culture',  145, 'Warm, inclusive, our people are our power',        ARRAY['#CultureAndPeople','#KytranEmpowerment','#TeamWork'],          'uplifting',    '#f97316'),
('Create Without Limits', 'create-limits',      'Creative & Design',          138, 'Expressive, vibrant, create without limits',       ARRAY['#CreateWithoutLimits','#KytranEmpowerment','#CreativeLife'],   'ambient',      '#a855f7'),
('Live the Dream',        'live-dream',         'Marketing & Communications', 141, 'Aspirational, personal, relatable, live fully',    ARRAY['#LiveTheDream','#KytranEmpowerment','#MondayMotivation'],      'uplifting',    '#ec4899')
ON CONFLICT (slug) DO NOTHING;

-- Seed 3 scenes per theme (27 total) using slug lookup for portability
INSERT INTO social_content_scenes (theme_id, name, description, visual_prompt_template, style_directive, generation_type, sort_order)
SELECT t.id, s.name, s.description, s.prompt, s.style, s.gtype, s.sorder
FROM social_content_themes t
JOIN (VALUES
  ('faith-strength',    'Sunrise Prayer',         'Golden hour, meditative',        '{agent_description}, standing at sunrise, arms open, golden light, peaceful, spiritual atmosphere, photorealistic, cinematic', 'warm golden tones, soft bokeh, devotional', 'lifestyle', 1),
  ('faith-strength',    'Candlelight Reflection', 'Intimate, warm, contemplative',  '{agent_description}, seated near candles, eyes closed, peaceful, warm amber light, photorealistic',                           'warm amber, intimate, sacred',              'selfie',    2),
  ('faith-strength',    'Community Gathering',    'Group energy, spiritual',         '{agent_description}, smiling warmly in diverse community gathering, natural light, authentic, photorealistic',                 'joyful, communal, natural light',           'lifestyle', 3),
  ('wellness-healing',  'Morning Yoga',           'Peaceful, sunrise, outdoors',     '{agent_description}, in yoga pose outdoors at sunrise, serene, nature background, photorealistic',                           'soft morning light, greens and golds',      'lifestyle', 1),
  ('wellness-healing',  'Nature Walk',            'Forest path, grounded, candid',   '{agent_description}, walking on forest path, candid, dappled sunlight, relaxed smile, photorealistic',                      'green tones, natural light, candid energy', 'selfie',    2),
  ('wellness-healing',  'Mindful Meal',           'Healthy food, cozy, intentional', '{agent_description}, at bright table with colorful healthy food, warm smile, natural light kitchen, photorealistic',         'bright airy, wellness colors, intentional', 'lifestyle', 3),
  ('legal-empowerment', 'Confident at Desk',      'Professional, powerful, focused', '{agent_description}, at professional desk with books and documents, confident posture, warm office lighting, photorealistic', 'deep wood tones, powerful, sharp',          'lifestyle', 1),
  ('legal-empowerment', 'Advocacy Moment',        'Speaking up, community, passion', '{agent_description}, speaking passionately to small group outdoors, gesturing, diverse crowd, natural light, photorealistic','natural light, community energy, determined','lifestyle', 2),
  ('legal-empowerment', 'Victory Celebration',    'Achievement, joy, milestone',     '{agent_description}, celebrating with arms raised, bright background, big smile, photorealistic',                            'bright celebratory, high energy, triumph',  'selfie',    3),
  ('build-innovate',    'Late Night Build',       'Tech, focused, maker energy',     '{agent_description}, at workstation with multiple screens, focused, blue screen glow, late night, photorealistic',            'cool blue light, tech atmosphere, intense', 'lifestyle', 1),
  ('build-innovate',    'Tech Conference',        'Networking, ideas, energy',        '{agent_description}, at tech conference, engaged in conversation, bright event lighting, professional casual, photorealistic','modern event space, professional, energetic','lifestyle', 2),
  ('build-innovate',    'Maker Moment',           'Creating, hands-on, proud',        '{agent_description}, holding finished project, proud smile, workshop background, natural light, photorealistic',              'warm workshop light, authentic pride',      'selfie',    3),
  ('financial-freedom', 'Growth Mindset',         'Confident, professional, forward', '{agent_description}, standing in modern office with city view, confident pose, sharp attire, photorealistic',               'corporate clean, upward energy, sharp',     'lifestyle', 1),
  ('financial-freedom', 'Vision Board',           'Intentional, planning, ambitious', '{agent_description}, reviewing whiteboard or planning wall, focused, bright modern space, photorealistic',                  'bright modern space, strategic, clean',     'lifestyle', 2),
  ('financial-freedom', 'Legacy Moment',          'Milestone, reflection, pride',     '{agent_description}, looking out floor-to-ceiling window at city skyline, reflective, golden hour, photorealistic',         'golden hour, aspirational, contemplative',  'selfie',    3),
  ('protect-serve',     'Vigilant Professional',  'Alert, trustworthy, composed',     '{agent_description}, in data center or secure facility, composed, blue LED lighting, photorealistic',                       'cool blue tones, secure atmosphere',        'lifestyle', 1),
  ('protect-serve',     'Community Watch',        'Community, caring, protective',    '{agent_description}, outdoors in neighborhood, friendly but alert, natural daylight, photorealistic',                       'natural daylight, community warmth',        'lifestyle', 2),
  ('protect-serve',     'Safety Awareness',       'Educational, clear, direct',       '{agent_description}, at workshop or briefing, presenting to small group, professional, photorealistic',                     'clean professional lighting, authoritative','lifestyle', 3),
  ('culture-people',    'Team Celebration',       'Joy, togetherness, milestone',     '{agent_description}, celebrating with diverse team, arms around colleagues, big smiles, confetti, photorealistic',           'warm celebratory, diverse, joyful',         'lifestyle', 1),
  ('culture-people',    'Welcoming Moment',       'Onboarding, inclusive, warm',      '{agent_description}, warmly welcoming someone new, handshake, bright modern office, photorealistic',                       'bright welcoming, inclusive, warm tones',   'lifestyle', 2),
  ('culture-people',    'Our People',             'Candid, authentic, human',          '{agent_description}, candid shot laughing with colleagues, genuine moment, photorealistic',                                 'candid natural light, authentic warmth',    'selfie',    3),
  ('create-limits',     'Art Studio',             'Creative, expressive, process',    '{agent_description}, in vibrant art studio surrounded by creative work, paint or design tools, photorealistic',              'colorful studio, vibrant palette',          'lifestyle', 1),
  ('create-limits',     'Inspiration Board',      'Ideas, vision, artistic',           '{agent_description}, reviewing mood board or inspiration wall, thoughtful, creative space, photorealistic',                 'artistic space, warm creative light',       'lifestyle', 2),
  ('create-limits',     'Finished Piece',         'Pride, achievement, artistic',      '{agent_description}, holding or beside finished creative work, proud genuine smile, studio backdrop, photorealistic',       'gallery or studio lighting, pride',         'selfie',    3),
  ('live-dream',        'Sunrise Beach',          'Golden hour, horizon, hopeful',     '{agent_description}, at sunrise beach, looking toward horizon, golden light, casual attire, cinematic depth, photorealistic','golden hour, cinematic, aspirational',      'lifestyle', 1),
  ('live-dream',        'City Rooftop',           'Urban, reflective, evening',         '{agent_description}, on rooftop with city skyline at dusk, relaxed pose, city lights, casual attire, photorealistic',     'dusk city glow, aspirational, cool tones',  'lifestyle', 2),
  ('live-dream',        'Candid Selfie',          'Real, spontaneous, relatable',       '{agent_description}, casual selfie, natural genuine smile, outdoor soft bokeh, daylight, authentic, photorealistic',      'natural daylight, candid energy, warm',     'selfie',    3)
) AS s(slug, name, description, prompt, style, gtype, sorder)
ON t.slug = s.slug
ON CONFLICT DO NOTHING;

-- Add theme_id to social_video_queue
ALTER TABLE social_video_queue ADD COLUMN IF NOT EXISTS theme_id INTEGER REFERENCES social_content_themes(id);
CREATE INDEX IF NOT EXISTS idx_svq_theme ON social_video_queue(theme_id);
