-- Migration 048: Populate Business Hours Shifts
-- Purpose: Create 9-5 business hours shift and assign all internal agents
-- Date: 2026-01-20
-- User Requirement: 9-5 business hours only, "Reduced Staff" after hours

-- ============================================
-- STEP 1: Create Business Hours shift definition
-- ============================================

INSERT INTO shift_definitions (shift_name, shift_code, start_time, end_time, timezone, description, color, is_active)
VALUES (
    'Business Hours',
    'BH',
    '09:00:00',
    '17:00:00',
    'America/Los_Angeles',
    'Standard 9-5 business hours (Mon-Fri)',
    '#4ADE80',
    true
)
ON CONFLICT (shift_code) DO UPDATE SET
    start_time = EXCLUDED.start_time,
    end_time = EXCLUDED.end_time,
    description = EXCLUDED.description,
    updated_at = NOW();

-- ============================================
-- STEP 2: Assign all internal agents to Business Hours shift
-- For Monday through Friday (day_of_week 1-5)
-- ============================================

DO $$
DECLARE
    bh_shift_id INTEGER;
    agent_rec RECORD;
    dow INTEGER;
BEGIN
    -- Get Business Hours shift ID
    SELECT id INTO bh_shift_id FROM shift_definitions WHERE shift_code = 'BH';

    -- For each internal agent with active station assignment
    FOR agent_rec IN
        SELECT DISTINCT a.id as agent_id, sa.station_id
        FROM agents a
        JOIN station_assignments sa ON a.id = sa.agent_id
        WHERE a.worker_type = 'internal'
          AND a.status = 'active'
          AND sa.is_active = true
    LOOP
        -- Assign to each weekday (Mon=1 through Fri=5)
        FOR dow IN 1..5 LOOP
            INSERT INTO agent_shifts (
                agent_id, shift_id, station_id, day_of_week,
                effective_from, is_primary, priority, notes
            )
            VALUES (
                agent_rec.agent_id,
                bh_shift_id,
                agent_rec.station_id,
                dow,
                CURRENT_DATE,
                true,
                1,
                'Auto-assigned: 9-5 business hours coverage'
            )
            ON CONFLICT (agent_id, shift_id, day_of_week, effective_from) DO NOTHING;
        END LOOP;
    END LOOP;

    RAISE NOTICE 'Business hours shifts populated for all internal agents';
END $$;

-- ============================================
-- STEP 3: Create staffing status view
-- ============================================

CREATE OR REPLACE VIEW v_staffing_status AS
WITH current_shift AS (
    SELECT
        sd.shift_name,
        sd.start_time,
        sd.end_time,
        CURRENT_TIME BETWEEN sd.start_time AND sd.end_time AS is_active_hours,
        EXTRACT(DOW FROM CURRENT_DATE)::INTEGER AS today_dow
    FROM shift_definitions sd
    WHERE sd.shift_code = 'BH'
)
SELECT
    CASE
        WHEN cs.today_dow IN (0, 6) THEN 'Weekend - Minimal Staff'
        WHEN cs.is_active_hours THEN 'Full Staff (9-5)'
        ELSE 'Reduced Staff (After Hours)'
    END AS staffing_status,
    cs.shift_name,
    cs.start_time,
    cs.end_time,
    cs.today_dow,
    (SELECT COUNT(DISTINCT agent_id) FROM agent_shifts WHERE day_of_week = cs.today_dow) AS agents_on_shift,
    (SELECT COUNT(*) FROM agents WHERE worker_type = 'internal' AND status = 'active') AS total_internal_agents,
    CURRENT_TIME AS current_time,
    CURRENT_DATE AS current_date
FROM current_shift cs;

-- ============================================
-- STEP 4: Create helper function for API
-- ============================================

CREATE OR REPLACE FUNCTION get_staffing_status()
RETURNS JSON AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'status', staffing_status,
        'shift_name', shift_name,
        'shift_hours', start_time || ' - ' || end_time,
        'agents_on_shift', agents_on_shift,
        'total_agents', total_internal_agents,
        'current_time', to_char(current_time, 'HH24:MI'),
        'is_business_hours', staffing_status = 'Full Staff (9-5)'
    )
    INTO result
    FROM v_staffing_status;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT SELECT ON v_staffing_status TO archie;
GRANT EXECUTE ON FUNCTION get_staffing_status() TO archie;

-- Add comments
COMMENT ON VIEW v_staffing_status IS 'Real-time staffing status based on business hours (9-5)';
COMMENT ON FUNCTION get_staffing_status() IS 'Returns JSON with current staffing status for API/dashboard use';
