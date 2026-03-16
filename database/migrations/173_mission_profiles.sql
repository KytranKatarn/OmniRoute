-- Migration 173: Mission Profiles
-- Reconfigurable station routing profiles for Bridge dispatcher
-- Project #146 / Task #953

-- ============================================================================
-- Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS mission_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    color VARCHAR(7) NOT NULL,
    icon VARCHAR(50),
    job_routing_overrides JSONB DEFAULT '{}',
    station_priorities JSONB DEFAULT '{}',
    agent_config JSONB DEFAULT '{}',
    loop_job_config JSONB DEFAULT '{}',
    event_triggers JSONB DEFAULT '[]',
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mission_schedules (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER REFERENCES mission_profiles(id) ON DELETE CASCADE,
    cron_expression VARCHAR(100) NOT NULL,
    duration_minutes INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- Seed 6 profiles
-- ============================================================================

INSERT INTO mission_profiles (name, display_name, description, color, icon, job_routing_overrides, station_priorities, agent_config, loop_job_config, event_triggers, is_default) VALUES

-- 1. Standard Operations (DEFAULT)
(
    'standard_operations',
    'Standard Operations',
    'Default balanced routing across all stations with normal IAAE governance and standard warmup priority',
    '#00d4ff',
    'activity',
    '{}'::jsonb,
    '{"COMMAND": 1.0, "ANALYTICS": 1.0, "CREATIVE": 1.0, "ENGINEERING": 1.0, "COMMUNICATIONS": 1.0, "RESEARCH": 1.0, "SECURITY": 1.0, "LOGISTICS": 1.0, "DIPLOMATIC": 1.0, "OPERATIONS": 1.0}'::jsonb,
    '{"warmup_priority": [], "rest_threshold": 0.7, "skip_rest": false}'::jsonb,
    '{}'::jsonb,
    '[]'::jsonb,
    TRUE
),

-- 2. Security Audit
(
    'security_audit',
    'Security Audit',
    'Enhanced security scanning and monitoring. Reroutes code analysis and testing to SECURITY station, deprioritizes creative work',
    '#EF4444',
    'shield-alert',
    '{"code_analysis": "SECURITY", "testing": "SECURITY", "vulnerability_scan": "SECURITY"}'::jsonb,
    '{"SECURITY": 2.0, "OPERATIONS": 1.5, "COMMAND": 1.0, "ANALYTICS": 1.0, "ENGINEERING": 0.8, "RESEARCH": 0.8, "COMMUNICATIONS": 0.5, "CREATIVE": 0.5, "LOGISTICS": 0.5, "DIPLOMATIC": 0.5}'::jsonb,
    '{"warmup_priority": ["llama3.1:8b", "smollm2:1.7b"], "rest_threshold": 0.3, "skip_rest": false}'::jsonb,
    '{"agent_network_discovery": {"interval": 120}, "agent_ssh_monitor": {"interval": 120}, "agent_security_scan": {"interval": 300}}'::jsonb,
    '[{"condition": "fail2ban_bans_gt_5", "cooldown_min": 30}, {"condition": "ssh_brute_force", "cooldown_min": 15}]'::jsonb,
    FALSE
),

-- 3. Feature Sprint
(
    'feature_sprint',
    'Feature Sprint',
    'Development-focused routing. Prioritizes ENGINEERING and ANALYTICS, auto-triggers code scans, low-risk proposals auto-approve',
    '#32CD32',
    'rocket',
    '{"code_review": "ENGINEERING", "testing": "ENGINEERING", "documentation": "ENGINEERING"}'::jsonb,
    '{"ENGINEERING": 2.0, "ANALYTICS": 1.5, "COMMAND": 1.0, "OPERATIONS": 1.0, "RESEARCH": 1.0, "SECURITY": 0.8, "COMMUNICATIONS": 0.5, "CREATIVE": 0.5, "LOGISTICS": 0.5, "DIPLOMATIC": 0.5}'::jsonb,
    '{"warmup_priority": ["qwen3-coder-cpu", "qwen2.5-coder:7b", "llama3.2:3b"], "rest_threshold": 0.5, "skip_rest": false}'::jsonb,
    '{"agent_code_scan": {"interval": 600}, "agent_improvement_scan": {"interval": 1800}}'::jsonb,
    '[]'::jsonb,
    FALSE
),

-- 4. Content Push
(
    'content_push',
    'Content Push',
    'Creative content generation focus. Prioritizes CREATIVE and COMMUNICATIONS stations, warms image generation models',
    '#FF69B4',
    'palette',
    '{"content_generation": "CREATIVE", "translation": "COMMUNICATIONS", "social_media": "COMMUNICATIONS"}'::jsonb,
    '{"CREATIVE": 2.0, "COMMUNICATIONS": 1.5, "COMMAND": 1.0, "DIPLOMATIC": 1.0, "ANALYTICS": 0.8, "RESEARCH": 0.8, "ENGINEERING": 0.5, "SECURITY": 0.5, "OPERATIONS": 0.5, "LOGISTICS": 0.5}'::jsonb,
    '{"warmup_priority": ["aya:8b", "llama3.2:3b"], "rest_threshold": 0.6, "skip_rest": false}'::jsonb,
    '{"agent_content_schedule": {"interval": 900}}'::jsonb,
    '[]'::jsonb,
    FALSE
),

-- 5. Maintenance
(
    'maintenance',
    'Maintenance',
    'System maintenance mode. Reduced job intervals, aggressive agent rest, only critical jobs processed',
    '#F59E0B',
    'wrench',
    '{"backup": "OPERATIONS", "cleanup": "OPERATIONS", "optimization": "OPERATIONS"}'::jsonb,
    '{"OPERATIONS": 1.5, "ENGINEERING": 1.5, "COMMAND": 1.0, "SECURITY": 1.0, "ANALYTICS": 0.5, "CREATIVE": 0.3, "COMMUNICATIONS": 0.3, "RESEARCH": 0.3, "LOGISTICS": 0.3, "DIPLOMATIC": 0.3}'::jsonb,
    '{"warmup_priority": [], "rest_threshold": 0.9, "skip_rest": false}'::jsonb,
    '{"agent_improvement_scan": {"interval": 7200}, "agent_knowledge_analysis": {"interval": 7200}, "agent_network_discovery": {"interval": 3600}}'::jsonb,
    '[]'::jsonb,
    FALSE
),

-- 6. Emergency Response
(
    'emergency_response',
    'Emergency Response',
    'All-hands emergency mode. All agents wake from barracks, max throughput, skip IAAE rest, Telegram on all alerts, cloud auto-approved',
    '#DC2626',
    'siren',
    '{}'::jsonb,
    '{"COMMAND": 2.0, "SECURITY": 2.0, "OPERATIONS": 2.0, "ENGINEERING": 1.5, "ANALYTICS": 1.5, "COMMUNICATIONS": 1.5, "RESEARCH": 1.0, "CREATIVE": 1.0, "LOGISTICS": 1.0, "DIPLOMATIC": 1.0}'::jsonb,
    '{"warmup_priority": ["llama3.1:8b", "smollm2:1.7b", "qwen3-coder-cpu"], "rest_threshold": 0.0, "skip_rest": true}'::jsonb,
    '{"agent_security_scan": {"interval": 60}, "agent_network_discovery": {"interval": 60}, "agent_ssh_monitor": {"interval": 60}}'::jsonb,
    '[{"condition": "critical_alerts_gt_3", "cooldown_min": 10}, {"condition": "fail2ban_bans_gt_10", "cooldown_min": 5}]'::jsonb,
    FALSE
)

ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    color = EXCLUDED.color,
    icon = EXCLUDED.icon,
    job_routing_overrides = EXCLUDED.job_routing_overrides,
    station_priorities = EXCLUDED.station_priorities,
    agent_config = EXCLUDED.agent_config,
    loop_job_config = EXCLUDED.loop_job_config,
    event_triggers = EXCLUDED.event_triggers,
    is_default = EXCLUDED.is_default,
    updated_at = NOW();

-- ============================================================================
-- Default schedule: maintenance on Sundays at 2 AM for 2 hours
-- ============================================================================

INSERT INTO mission_schedules (profile_id, cron_expression, duration_minutes, is_active)
SELECT id, '0 2 * * 0', 120, TRUE
FROM mission_profiles
WHERE name = 'maintenance'
ON CONFLICT DO NOTHING;
