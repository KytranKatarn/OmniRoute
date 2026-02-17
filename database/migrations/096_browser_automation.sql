-- ============================================================================
-- Migration 096: Browser Automation
-- Purpose: Playwright-based web automation with domain approval
-- Created: 2026-02-17
-- ============================================================================

-- Browser automation tasks
CREATE TABLE IF NOT EXISTS browser_tasks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    task_type VARCHAR(50) NOT NULL DEFAULT 'screenshot', -- 'scrape', 'form_fill', 'monitor', 'screenshot', 'custom'
    url VARCHAR(2000) NOT NULL,
    instructions TEXT,                       -- natural language or Playwright script
    script TEXT,                             -- generated Playwright code
    schedule_cron VARCHAR(100),              -- optional cron for recurring tasks
    status VARCHAR(50) DEFAULT 'pending',    -- 'pending', 'running', 'completed', 'failed', 'paused', 'awaiting_approval'
    priority INTEGER DEFAULT 5,
    max_retries INTEGER DEFAULT 3,
    retry_count INTEGER DEFAULT 0,
    timeout_seconds INTEGER DEFAULT 60,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    error_message TEXT,
    created_by INTEGER REFERENCES users(id),
    approval_id INTEGER REFERENCES autonomy_approval_queue(id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Approved domains for browser automation
CREATE TABLE IF NOT EXISTS browser_approved_domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(500) NOT NULL UNIQUE,     -- e.g. 'github.com'
    approved_by INTEGER REFERENCES users(id),
    auto_approved BOOLEAN DEFAULT FALSE,     -- internal domains
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Task execution results
CREATE TABLE IF NOT EXISTS browser_task_results (
    id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES browser_tasks(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'success', -- 'success', 'failed', 'partial'
    screenshot_path VARCHAR(500),            -- path to captured screenshot
    scraped_data JSONB,                      -- extracted data
    page_title VARCHAR(1000),
    page_url VARCHAR(2000),                  -- final URL (after redirects)
    duration_ms INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_browser_tasks_status ON browser_tasks(status);
CREATE INDEX IF NOT EXISTS idx_browser_tasks_type ON browser_tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_browser_tasks_next_run ON browser_tasks(next_run_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_browser_tasks_schedule ON browser_tasks(schedule_cron) WHERE schedule_cron IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_browser_domains_domain ON browser_approved_domains(domain);
CREATE INDEX IF NOT EXISTS idx_browser_results_task ON browser_task_results(task_id, created_at);

-- Pre-approve internal domains
INSERT INTO browser_approved_domains (domain, auto_approved, notes) VALUES
    ('192.168.1.200', TRUE, 'Local ARCHIE host'),
    ('localhost', TRUE, 'Localhost'),
    ('archie_platform', TRUE, 'Docker internal')
ON CONFLICT (domain) DO NOTHING;

-- Grant permissions
GRANT ALL ON browser_tasks TO archie;
GRANT ALL ON browser_approved_domains TO archie;
GRANT ALL ON browser_task_results TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE browser_tasks IS 'Playwright-based browser automation tasks';
COMMENT ON TABLE browser_approved_domains IS 'Approved domains for automated browsing';
COMMENT ON TABLE browser_task_results IS 'Results from browser task executions';
