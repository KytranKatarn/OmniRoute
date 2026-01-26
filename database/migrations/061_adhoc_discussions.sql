-- Migration 061: Multi-Agent Ad-hoc Discussions
-- Date: 2026-01-21
-- Purpose: Support ad-hoc discussions not linked to improvement proposals (Phase 63)

-- Add discussion_type column to agent_discussions if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_discussions' AND column_name = 'discussion_type'
    ) THEN
        ALTER TABLE agent_discussions ADD COLUMN discussion_type VARCHAR(50) DEFAULT 'proposal';
    END IF;
END $$;

-- Add user_id column to track who initiated discussion (for ad-hoc)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_discussions' AND column_name = 'initiated_by_user'
    ) THEN
        ALTER TABLE agent_discussions ADD COLUMN initiated_by_user INTEGER REFERENCES users(id);
    END IF;
END $$;

-- Index for finding user's discussions
CREATE INDEX IF NOT EXISTS idx_agent_discussions_user ON agent_discussions(initiated_by_user);
CREATE INDEX IF NOT EXISTS idx_agent_discussions_type ON agent_discussions(discussion_type);

-- Make proposal_id nullable (was required before, now optional for ad-hoc)
ALTER TABLE agent_discussions ALTER COLUMN proposal_id DROP NOT NULL;

-- Update existing discussions to have type 'proposal'
UPDATE agent_discussions
SET discussion_type = 'proposal'
WHERE discussion_type IS NULL AND proposal_id IS NOT NULL;

-- Update ad-hoc discussions (no proposal_id)
UPDATE agent_discussions
SET discussion_type = 'adhoc'
WHERE discussion_type IS NULL AND proposal_id IS NULL;

-- View for active discussions (proposal and ad-hoc)
CREATE OR REPLACE VIEW v_active_discussions AS
SELECT
    ad.id,
    ad.discussion_type,
    ad.proposal_id,
    ad.topic,
    ad.description,
    ad.status,
    ad.consensus_reached,
    ad.consensus_score,
    ad.started_at,
    ad.metadata,
    ad.initiated_by_user,
    u.email as initiated_by_email,
    a.name as facilitator_name,
    COUNT(DISTINCT adm.agent_id) as participant_count,
    COUNT(adm.id) as message_count,
    MAX(adm.created_at) as last_activity
FROM agent_discussions ad
LEFT JOIN users u ON ad.initiated_by_user = u.id
LEFT JOIN agents a ON ad.facilitator_id = a.id
LEFT JOIN agent_discussion_messages adm ON ad.id = adm.discussion_id
WHERE ad.status = 'active'
GROUP BY ad.id, ad.discussion_type, ad.proposal_id, ad.topic, ad.description,
         ad.status, ad.consensus_reached, ad.consensus_score, ad.started_at,
         ad.metadata, ad.initiated_by_user, u.email, a.name;

COMMENT ON VIEW v_active_discussions IS 'Active multi-agent discussions (Phase 63)';

-- View: Discussion summary with participants
CREATE OR REPLACE VIEW v_discussion_participants AS
SELECT
    ad.id as discussion_id,
    ad.topic,
    ad.discussion_type,
    ad.status,
    array_agg(DISTINCT a.name) as participants,
    array_agg(DISTINCT a.department) as departments,
    COUNT(DISTINCT adm.agent_id) as agent_count,
    COUNT(adm.id) as message_count,
    AVG(adm.confidence_score) as avg_confidence
FROM agent_discussions ad
LEFT JOIN agent_discussion_messages adm ON ad.id = adm.discussion_id
LEFT JOIN agents a ON adm.agent_id = a.id
GROUP BY ad.id, ad.topic, ad.discussion_type, ad.status;

COMMENT ON VIEW v_discussion_participants IS 'Discussion participants summary (Phase 63)';

-- Function: Start ad-hoc discussion
CREATE OR REPLACE FUNCTION start_adhoc_discussion(
    p_topic VARCHAR(255),
    p_user_id INTEGER,
    p_facilitator_id INTEGER DEFAULT NULL,
    p_stations TEXT[] DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_discussion_id INTEGER;
    v_facilitator INTEGER;
BEGIN
    -- Use ARCHIE as default facilitator
    IF p_facilitator_id IS NULL THEN
        SELECT id INTO v_facilitator FROM agents WHERE name = 'A.R.C.H.I.E.' LIMIT 1;
    ELSE
        v_facilitator := p_facilitator_id;
    END IF;

    INSERT INTO agent_discussions (
        discussion_type,
        topic,
        description,
        facilitator_id,
        status,
        initiated_by_user,
        metadata,
        started_at
    ) VALUES (
        'adhoc',
        p_topic,
        'Ad-hoc multi-agent discussion: ' || p_topic,
        v_facilitator,
        'active',
        p_user_id,
        jsonb_build_object('stations', COALESCE(p_stations, ARRAY[]::TEXT[])),
        NOW()
    )
    RETURNING id INTO v_discussion_id;

    RETURN v_discussion_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION start_adhoc_discussion IS 'Start a new ad-hoc multi-agent discussion (Phase 63)';

-- Function: Get discussion analytics
CREATE OR REPLACE FUNCTION get_discussion_analytics(p_days INTEGER DEFAULT 30)
RETURNS TABLE (
    total_discussions BIGINT,
    adhoc_discussions BIGINT,
    proposal_discussions BIGINT,
    avg_participants NUMERIC,
    avg_messages NUMERIC,
    avg_consensus_score NUMERIC,
    completed_with_consensus BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::BIGINT as total_discussions,
        COUNT(*) FILTER (WHERE discussion_type = 'adhoc')::BIGINT as adhoc_discussions,
        COUNT(*) FILTER (WHERE discussion_type = 'proposal')::BIGINT as proposal_discussions,
        ROUND(AVG((SELECT COUNT(DISTINCT agent_id) FROM agent_discussion_messages WHERE discussion_id = ad.id))::NUMERIC, 1) as avg_participants,
        ROUND(AVG((SELECT COUNT(*) FROM agent_discussion_messages WHERE discussion_id = ad.id))::NUMERIC, 1) as avg_messages,
        ROUND(AVG(CASE WHEN consensus_score IS NOT NULL THEN consensus_score ELSE 0 END)::NUMERIC, 2) as avg_consensus_score,
        COUNT(*) FILTER (WHERE consensus_reached = TRUE)::BIGINT as completed_with_consensus
    FROM agent_discussions ad
    WHERE started_at > NOW() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_discussion_analytics IS 'Get discussion analytics for dashboard (Phase 63)';

SELECT 'Migration 061 completed - Ad-hoc discussions enabled (Phase 63)' as status;
