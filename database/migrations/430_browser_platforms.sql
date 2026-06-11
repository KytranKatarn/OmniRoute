-- 430: browser_platforms — data-driven platform registry for the S.C.O.U.T.
-- auth fabric (#4006, phase 2a of #3708). Replaces the hardcoded platform
-- dicts in archie-browser/login_app.py + session_routes._SUPPORTED_PLATFORMS
-- as the source of truth for which sites the login sidecar / cookie import /
-- health probe may touch. platform matches browser_sessions.platform
-- (VARCHAR(50), no FK — sessions for custom platforms are valid).
-- Idempotent.

CREATE TABLE IF NOT EXISTS browser_platforms (
    platform      VARCHAR(50) PRIMARY KEY,
    display_name  VARCHAR(100) NOT NULL,
    -- NULL login_url = cookie-import only (no interactive login capture)
    login_url     TEXT,
    allowed_hosts JSONB NOT NULL DEFAULT '[]',
    -- NULL probe_url = no generic health probe (opt-in per platform)
    probe_url     TEXT,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    source        VARCHAR(20) NOT NULL DEFAULT 'custom'
                  CHECK (source IN ('seed', 'custom')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seeds mirror archie-browser/login_app.py (_ALLOWED_LOGIN_HOSTS /
-- _DEFAULT_LOGIN_URL) + session_routes._SUPPORTED_PLATFORMS. probe_url left
-- NULL: linkedin is probed via its READ skill (WARM_SKILLS), the rest stay
-- unprobed until deliberately opted in.
INSERT INTO browser_platforms (platform, display_name, login_url, allowed_hosts, source) VALUES
  ('linkedin', 'LinkedIn', 'https://www.linkedin.com/login',
   '["www.linkedin.com", "linkedin.com"]', 'seed'),
  ('x', 'X (Twitter)', 'https://x.com/i/flow/login',
   '["x.com", "www.x.com", "twitter.com", "www.twitter.com"]', 'seed'),
  ('claude', 'Claude', 'https://claude.ai/login',
   '["claude.ai", "www.claude.ai"]', 'seed'),
  ('deepseek', 'DeepSeek', 'https://chat.deepseek.com/sign_in',
   '["chat.deepseek.com", "www.deepseek.com"]', 'seed'),
  ('twitter', 'Twitter (legacy cookie import)', NULL,
   '["twitter.com", "www.twitter.com"]', 'seed'),
  ('facebook', 'Facebook', NULL,
   '["facebook.com", "www.facebook.com"]', 'seed'),
  ('openai', 'OpenAI', NULL,
   '["chat.openai.com", "chatgpt.com", "platform.openai.com"]', 'seed')
ON CONFLICT (platform) DO NOTHING;
