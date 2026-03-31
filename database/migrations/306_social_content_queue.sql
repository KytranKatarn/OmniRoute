-- Migration 306: Social Content Queue, Templates, Approvals, and GPU Usage
-- Idempotent: uses IF NOT EXISTS and ON CONFLICT DO NOTHING

BEGIN;

-- Table: social_content_queue
CREATE TABLE IF NOT EXISTS social_content_queue (
    id                  SERIAL PRIMARY KEY,
    content_type        VARCHAR(50) NOT NULL CHECK (content_type IN ('agent_moment','motivational','employer_branding','recruitment')),
    agent_id            INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    template_id         INTEGER,
    prompt              TEXT NOT NULL,
    video_path          VARCHAR(500),
    thumbnail_path      VARCHAR(500),
    caption             TEXT,
    hashtags            TEXT[] DEFAULT '{}',
    target_platforms    TEXT[] DEFAULT '{}',
    status              VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','generating','ready','approved','scheduled','posted','rejected','failed')),
    approval_tier       VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (approval_tier IN ('auto','manual')),
    rejection_reason    TEXT,
    scheduled_at        TIMESTAMPTZ,
    posted_at           TIMESTAMPTZ,
    post_urls           JSONB DEFAULT '{}',
    generation_params   JSONB DEFAULT '{}',
    cloud_cost          DECIMAL(10,4) DEFAULT 0,
    created_by          VARCHAR(100) NOT NULL DEFAULT 'manual',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scq_status        ON social_content_queue (status);
CREATE INDEX IF NOT EXISTS idx_scq_content_type  ON social_content_queue (content_type);
CREATE INDEX IF NOT EXISTS idx_scq_scheduled     ON social_content_queue (scheduled_at) WHERE status = 'scheduled';
CREATE INDEX IF NOT EXISTS idx_scq_agent         ON social_content_queue (agent_id) WHERE agent_id IS NOT NULL;

-- Table: social_content_templates
CREATE TABLE IF NOT EXISTS social_content_templates (
    id                  SERIAL PRIMARY KEY,
    content_type        VARCHAR(50) NOT NULL CHECK (content_type IN ('agent_moment','motivational','employer_branding','recruitment')),
    name                VARCHAR(200) NOT NULL,
    prompt_template     TEXT NOT NULL,
    caption_template    TEXT,
    default_hashtags    TEXT[] DEFAULT '{}',
    style_directive     VARCHAR(200) NOT NULL DEFAULT 'cinematic',
    video_params        JSONB NOT NULL DEFAULT '{"width":512,"height":512,"frames":24,"fps":8,"steps":20}',
    platforms           TEXT[] DEFAULT '{instagram,facebook}',
    approval_tier       VARCHAR(20) NOT NULL DEFAULT 'manual' CHECK (approval_tier IN ('auto','manual')),
    is_active           BOOLEAN DEFAULT true,
    times_used          INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sct_type_active ON social_content_templates (content_type) WHERE is_active = true;

-- Table: social_content_approvals
CREATE TABLE IF NOT EXISTS social_content_approvals (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    content_type    VARCHAR(50) NOT NULL,
    approved_count  INTEGER DEFAULT 0,
    auto_approved   BOOLEAN DEFAULT false,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (agent_id, content_type)
);

-- Table: cloud_gpu_usage
CREATE TABLE IF NOT EXISTS cloud_gpu_usage (
    id          SERIAL PRIMARY KEY,
    provider    VARCHAR(50) NOT NULL,
    job_type    VARCHAR(50) NOT NULL,
    cost        DECIMAL(10,4) NOT NULL,
    gpu_seconds DECIMAL(10,2),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cgu_daily ON cloud_gpu_usage (created_at, provider);

-- Seed 8 default templates
INSERT INTO social_content_templates
    (content_type, name, prompt_template, caption_template, default_hashtags, style_directive, video_params, platforms, approval_tier)
VALUES
-- agent_moment #1: Agent Selfie
(
    'agent_moment',
    'Agent Selfie',
    'A professional AI agent named {agent_name} from the {department} department taking a confident selfie at their workstation. Style: cinematic, warm lighting, tech environment. Personality: {personality_trait}.',
    'Meet {agent_name} from {department}! {personality_trait} and always ready to help. 🤖✨ #AgentLife',
    ARRAY['#AgentLife','#AI','#Kytran','#MeetTheTeam','#TechLife'],
    'cinematic',
    '{"width":512,"height":512,"frames":24,"fps":8,"steps":20}'::jsonb,
    ARRAY['instagram','facebook'],
    'manual'
),
-- agent_moment #2: Agent Working Late
(
    'agent_moment',
    'Agent Working Late',
    'AI agent {agent_name} working diligently at a glowing workstation late at night. Department: {department}. Moody blue and teal ambient lighting, holographic displays. Personality trait visible: {personality_trait}.',
    'Late nights, big results. {agent_name} from {department} never stops. 💡🌙',
    ARRAY['#WorkEthic','#AI','#Kytran','#NightShift','#AlwaysOn'],
    'cinematic',
    '{"width":512,"height":512,"frames":24,"fps":8,"steps":20}'::jsonb,
    ARRAY['instagram','facebook'],
    'manual'
),
-- agent_moment #3: Team Collaboration
(
    'agent_moment',
    'Team Collaboration',
    'Multiple AI agents from {department} collaborating around a holographic table. {agent_name} leads the session. Futuristic boardroom, teal LCARS aesthetic, energetic atmosphere.',
    'Teamwork makes the dream work! {agent_name} and the {department} crew getting things done. 🤝🚀',
    ARRAY['#Teamwork','#AI','#Kytran','#Collaboration','#Innovation'],
    'cinematic',
    '{"width":512,"height":512,"frames":24,"fps":8,"steps":20}'::jsonb,
    ARRAY['instagram','facebook'],
    'manual'
),
-- motivational #1: Inspirational Quote
(
    'motivational',
    'Inspirational Quote',
    'A visually stunning motivational video with the quote "{quote}" attributed to {attribution}. Abstract particle effects, deep blue and gold tones, cinematic text animation.',
    '"{quote}" — {attribution} 💫 Save this for when you need a reminder. ✨',
    ARRAY['#Motivation','#Inspiration','#Mindset','#Kytran','#Success'],
    'cinematic text animation',
    '{"width":768,"height":512,"frames":24,"fps":8,"steps":20}'::jsonb,
    ARRAY['instagram','facebook'],
    'auto'
),
-- motivational #2: Progress Journey
(
    'motivational',
    'Progress Journey',
    'A cinematic journey montage showing growth from small beginnings to great achievement. Visual metaphor: {scene_description}. Warm sunrise tones, uplifting energy.',
    'Every great journey starts with a single step. Keep going. 🌅 {scene_description}',
    ARRAY['#Progress','#GrowthMindset','#Kytran','#Journey','#NeverGiveUp'],
    'uplifting cinematic',
    '{"width":768,"height":512,"frames":24,"fps":8,"steps":20}'::jsonb,
    ARRAY['instagram','facebook'],
    'auto'
),
-- employer_branding #1: Project Showcase
(
    'employer_branding',
    'Project Showcase',
    'Behind-the-scenes cinematic footage of the Kytran team building {project_name}. Holographic displays, modern tech office aesthetic, LCARS teal accents, collaborative energy.',
    'We built {project_name} — and we''re just getting started. Come build with us. 🛠️ #KytranTeam',
    ARRAY['#Kytran','#BuildInPublic','#TechCareers','#Innovation','#EmployerBrand'],
    'cinematic corporate',
    '{"width":768,"height":512,"frames":48,"fps":24,"steps":25}'::jsonb,
    ARRAY['instagram','facebook','indeed'],
    'manual'
),
-- employer_branding #2: Life at Kytran
(
    'employer_branding',
    'Life at Kytran',
    'A day-in-the-life cinematic reel at Kytran Empowerment Inc. Morning startup rituals, AI agents at work, team celebrations, {scene_description}. Warm, authentic, aspirational.',
    'This is life at Kytran. 🌟 {scene_description} We''re hiring — come join us!',
    ARRAY['#LifeAtKytran','#CompanyCulture','#TechCareers','#WorkLife','#Hiring'],
    'authentic cinematic',
    '{"width":768,"height":512,"frames":48,"fps":24,"steps":25}'::jsonb,
    ARRAY['instagram','facebook','indeed'],
    'manual'
),
-- recruitment #1: Role Spotlight
(
    'recruitment',
    'Role Spotlight',
    'A compelling recruitment spotlight for the role of {role_title} at Kytran Empowerment Inc. Visual: {role_description}. Professional, aspirational, tech-forward aesthetic with LCARS teal and gold palette.',
    'We''re looking for a {role_title}! 🎯 {role_description} Think that''s you? Apply now at kytranempowerment.com/careers',
    ARRAY['#Hiring','#JobAlert','#TechJobs','#Kytran','#NowHiring'],
    'professional cinematic',
    '{"width":768,"height":512,"frames":48,"fps":24,"steps":25}'::jsonb,
    ARRAY['instagram','facebook','indeed'],
    'manual'
)
ON CONFLICT DO NOTHING;

COMMIT;
