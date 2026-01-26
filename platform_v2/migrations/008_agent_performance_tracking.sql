-- ============================================================================
-- Migration 008: Agent Performance Tracking
-- Date: 2026-01-01
-- Purpose: Track individual agent performance, implement grading, and enable learning
-- ============================================================================

-- Table: Agent Performance Logs
-- Tracks every action/task performed by agents
CREATE TABLE IF NOT EXISTS agent_performance_logs (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    action_type VARCHAR(50),  -- 'evaluation', 'discussion', 'test', 'deployment', 'code_review'
    proposal_id INTEGER REFERENCES improvement_proposals(id) ON DELETE SET NULL,
    discussion_id INTEGER REFERENCES agent_discussions(id) ON DELETE SET NULL,
    task_description TEXT,
    outcome VARCHAR(30),  -- 'success', 'failure', 'partial', 'error'
    duration_seconds INTEGER,
    quality_score DECIMAL(3,2),  -- 0.00 to 1.00 (how good was the work)
    accuracy_score DECIMAL(3,2),  -- 0.00 to 1.00 (how accurate was the evaluation)
    timeliness_score DECIMAL(3,2),  -- 0.00 to 1.00 (completed on time?)
    complexity_level VARCHAR(30),  -- 'simple', 'moderate', 'complex', 'expert'
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table: Agent Performance Metrics
-- Aggregated metrics per agent (updated periodically)
CREATE TABLE IF NOT EXISTS agent_performance_metrics (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE UNIQUE,

    -- Overall Performance
    overall_grade VARCHAR(3),  -- 'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D', 'F'
    overall_score DECIMAL(5,2),  -- 0.00 to 100.00
    performance_trend VARCHAR(20),  -- 'improving', 'stable', 'declining'

    -- Activity Metrics
    total_tasks_completed INTEGER DEFAULT 0,
    total_tasks_failed INTEGER DEFAULT 0,
    tasks_last_30_days INTEGER DEFAULT 0,
    avg_task_duration_seconds INTEGER,

    -- Quality Metrics
    avg_quality_score DECIMAL(3,2),
    avg_accuracy_score DECIMAL(3,2),
    avg_timeliness_score DECIMAL(3,2),

    -- Evaluation Metrics
    evaluations_given INTEGER DEFAULT 0,
    evaluations_agreed_with_consensus INTEGER DEFAULT 0,  -- How often agent agreed with majority
    consensus_agreement_rate DECIMAL(3,2),  -- Percentage

    -- Proposal Success Metrics
    proposals_approved INTEGER DEFAULT 0,
    proposals_rejected INTEGER DEFAULT 0,
    proposals_implemented_successfully INTEGER DEFAULT 0,
    proposals_failed_in_production INTEGER DEFAULT 0,
    success_rate DECIMAL(3,2),

    -- Learning Metrics
    proficiency_level VARCHAR(30),  -- 'novice', 'intermediate', 'advanced', 'expert', 'master'
    learning_velocity DECIMAL(3,2),  -- Rate of improvement (0.00 to 1.00)
    specialization_areas TEXT[],  -- Array of categories agent excels in

    -- Timestamps
    last_updated TIMESTAMP DEFAULT NOW(),
    last_task_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table: Agent Skill Proficiency History
-- Tracks how agent skills improve over time
CREATE TABLE IF NOT EXISTS agent_skill_proficiency_history (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    skill_name VARCHAR(100),
    old_proficiency_level DECIMAL(3,2),
    new_proficiency_level DECIMAL(3,2),
    change_reason VARCHAR(255),
    evidence TEXT,  -- What evidence led to this change
    updated_by VARCHAR(50),  -- 'system', 'admin', 'learning_engine'
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Table: Agent Learning Insights
-- Stores insights learned from successes and failures
CREATE TABLE IF NOT EXISTS agent_learning_insights (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    insight_type VARCHAR(50),  -- 'success_pattern', 'failure_pattern', 'improvement_area', 'strength'
    category VARCHAR(50),  -- Proposal category this applies to
    insight_text TEXT,
    confidence DECIMAL(3,2),  -- How confident we are in this insight
    occurrences INTEGER DEFAULT 1,  -- How many times we've seen this pattern
    first_observed TIMESTAMP DEFAULT NOW(),
    last_observed TIMESTAMP DEFAULT NOW(),
    actionable BOOLEAN DEFAULT TRUE,
    metadata JSONB
);

-- Table: Agent Peer Comparisons
-- Compare agents against their peers
CREATE TABLE IF NOT EXISTS agent_peer_comparisons (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    peer_group VARCHAR(50),  -- 'same_department', 'same_tier', 'same_worker_type', 'all_agents'
    metric_name VARCHAR(50),  -- 'overall_score', 'success_rate', 'quality_score', etc.
    agent_value DECIMAL(5,2),
    peer_average DECIMAL(5,2),
    peer_median DECIMAL(5,2),
    percentile DECIMAL(3,2),  -- Agent's percentile rank (0.00 to 1.00)
    calculated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_perf_logs_agent ON agent_performance_logs(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_perf_logs_proposal ON agent_performance_logs(proposal_id);
CREATE INDEX IF NOT EXISTS idx_perf_logs_outcome ON agent_performance_logs(outcome, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_perf_metrics_agent ON agent_performance_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_perf_metrics_grade ON agent_performance_metrics(overall_grade, overall_score DESC);
CREATE INDEX IF NOT EXISTS idx_skill_history_agent ON agent_skill_proficiency_history(agent_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_insights_agent ON agent_learning_insights(agent_id, insight_type);
CREATE INDEX IF NOT EXISTS idx_peer_comparisons_agent ON agent_peer_comparisons(agent_id, calculated_at DESC);

-- Add new columns to agents table for quick performance reference
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS current_grade VARCHAR(3),  -- Quick reference to latest grade
ADD COLUMN IF NOT EXISTS performance_score DECIMAL(5,2),  -- 0.00 to 100.00
ADD COLUMN IF NOT EXISTS total_tasks_completed INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS success_rate DECIMAL(3,2),
ADD COLUMN IF NOT EXISTS last_performance_update TIMESTAMP;

-- View: Agent Performance Leaderboard
CREATE OR REPLACE VIEW agent_performance_leaderboard AS
SELECT
    a.id as agent_id,
    COALESCE(a.first_name || ' ' || a.last_name, a.name) as agent_name,
    a.department,
    a.tier,
    a.worker_type,
    a.current_grade,
    a.performance_score,
    a.total_tasks_completed,
    a.success_rate,
    apm.overall_score,
    apm.performance_trend,
    apm.proficiency_level,
    apm.avg_quality_score,
    apm.consensus_agreement_rate,
    RANK() OVER (ORDER BY a.performance_score DESC NULLS LAST) as overall_rank,
    RANK() OVER (PARTITION BY a.department ORDER BY a.performance_score DESC NULLS LAST) as department_rank
FROM agents a
LEFT JOIN agent_performance_metrics apm ON a.id = apm.agent_id
WHERE a.status = 'active'
ORDER BY a.performance_score DESC NULLS LAST;

-- View: Agent Performance Summary
CREATE OR REPLACE VIEW agent_performance_summary AS
SELECT
    apm.agent_id,
    COALESCE(a.first_name || ' ' || a.last_name, a.name) as agent_name,
    a.department,
    apm.overall_grade,
    apm.overall_score,
    apm.performance_trend,
    apm.total_tasks_completed,
    apm.tasks_last_30_days,
    apm.success_rate,
    apm.avg_quality_score,
    apm.consensus_agreement_rate,
    apm.proficiency_level,
    apm.specialization_areas,
    apm.last_task_at,
    (
        SELECT COUNT(*)
        FROM agent_learning_insights ali
        WHERE ali.agent_id = apm.agent_id
        AND ali.actionable = TRUE
    ) as actionable_insights_count
FROM agent_performance_metrics apm
JOIN agents a ON apm.agent_id = a.id
WHERE a.status = 'active';

-- Function: Calculate Agent Grade from Score
CREATE OR REPLACE FUNCTION calculate_agent_grade(score DECIMAL) RETURNS VARCHAR AS $$
BEGIN
    RETURN CASE
        WHEN score >= 97 THEN 'A+'
        WHEN score >= 93 THEN 'A'
        WHEN score >= 90 THEN 'A-'
        WHEN score >= 87 THEN 'B+'
        WHEN score >= 83 THEN 'B'
        WHEN score >= 80 THEN 'B-'
        WHEN score >= 77 THEN 'C+'
        WHEN score >= 73 THEN 'C'
        WHEN score >= 70 THEN 'C-'
        WHEN score >= 60 THEN 'D'
        ELSE 'F'
    END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Insert initial metrics for existing agents
INSERT INTO agent_performance_metrics (agent_id, overall_grade, overall_score, proficiency_level)
SELECT
    id,
    'C',  -- Default grade
    75.0,  -- Default score
    'intermediate'  -- Default proficiency
FROM agents
WHERE status = 'active'
ON CONFLICT (agent_id) DO NOTHING;

-- Update agents table with initial performance data
UPDATE agents a
SET
    current_grade = 'C',
    performance_score = 75.0,
    total_tasks_completed = 0,
    success_rate = 0.0
WHERE a.status = 'active' AND a.current_grade IS NULL;

-- Comments for documentation
COMMENT ON TABLE agent_performance_logs IS 'Tracks every action/task performed by agents';
COMMENT ON TABLE agent_performance_metrics IS 'Aggregated performance metrics per agent';
COMMENT ON TABLE agent_skill_proficiency_history IS 'Tracks how agent skills improve over time';
COMMENT ON TABLE agent_learning_insights IS 'Stores insights learned from successes and failures';
COMMENT ON TABLE agent_peer_comparisons IS 'Compare agents against their peers';
COMMENT ON VIEW agent_performance_leaderboard IS 'Shows agent rankings by performance';
COMMENT ON VIEW agent_performance_summary IS 'Comprehensive view of agent performance';
COMMENT ON FUNCTION calculate_agent_grade IS 'Converts numeric score to letter grade (A+ to F)';

-- Trigger: Auto-update agent grade when metrics change
CREATE OR REPLACE FUNCTION update_agent_grade() RETURNS TRIGGER AS $$
BEGIN
    UPDATE agents
    SET
        current_grade = calculate_agent_grade(NEW.overall_score),
        performance_score = NEW.overall_score,
        total_tasks_completed = NEW.total_tasks_completed,
        success_rate = NEW.success_rate,
        last_performance_update = NOW()
    WHERE id = NEW.agent_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_agent_grade
AFTER INSERT OR UPDATE ON agent_performance_metrics
FOR EACH ROW
EXECUTE FUNCTION update_agent_grade();
