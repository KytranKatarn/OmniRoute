-- ============================================================================
-- Migration 017: Scheduler Tables
-- Purpose: Calendar events, subscriptions, tasks for Business Tools
-- Created: 2026-01-17
-- ============================================================================

-- Calendar events
CREATE TABLE IF NOT EXISTS calendar_events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    event_type VARCHAR(50) DEFAULT 'general', -- 'meeting', 'call', 'reminder', 'subscription', 'task', 'general'
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    all_day BOOLEAN DEFAULT FALSE,
    location VARCHAR(255),
    video_link VARCHAR(500),

    -- Recurrence
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule VARCHAR(255), -- RRULE format (e.g., 'FREQ=WEEKLY;BYDAY=MO,WE,FR')
    recurrence_end DATE,
    parent_event_id INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE,

    -- Associations
    customer_id INTEGER, -- Link to CRM customer
    user_id INTEGER REFERENCES users(id),
    assigned_to INTEGER REFERENCES users(id),

    -- Status
    status VARCHAR(50) DEFAULT 'scheduled', -- 'scheduled', 'completed', 'cancelled', 'rescheduled'
    color VARCHAR(20) DEFAULT '#3b82f6',

    -- Reminders (stored as JSON array of minutes before)
    reminders JSONB DEFAULT '[30, 1440]', -- 30 min and 24 hours before
    reminder_sent BOOLEAN DEFAULT FALSE,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Subscription schedules (tracking renewals)
CREATE TABLE IF NOT EXISTS subscription_schedules (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER,
    customer_id INTEGER,
    user_id INTEGER REFERENCES users(id),

    -- Schedule info
    tier VARCHAR(50), -- 'free', 'pro', 'business', 'enterprise'
    billing_cycle VARCHAR(20) DEFAULT 'monthly', -- 'monthly', 'yearly'
    amount DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'CAD',

    -- Dates
    start_date DATE NOT NULL,
    next_billing_date DATE,
    last_billed_date DATE,
    end_date DATE, -- null for active subscriptions

    -- Status
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'cancelled', 'paused', 'expired', 'trial'
    auto_renew BOOLEAN DEFAULT TRUE,

    -- Payment
    payment_method VARCHAR(50), -- 'stripe', 'paypal', 'manual'
    stripe_subscription_id VARCHAR(255),

    -- History
    billing_history JSONB DEFAULT '[]',

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scheduled tasks (future automated actions)
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    task_type VARCHAR(50) NOT NULL, -- 'email', 'invoice', 'reminder', 'webhook', 'callback', 'follow_up'

    -- Schedule
    scheduled_for TIMESTAMP NOT NULL,
    executed_at TIMESTAMP,

    -- Recurrence
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule VARCHAR(255),
    next_run TIMESTAMP,

    -- Target
    target_type VARCHAR(50), -- 'customer', 'invoice', 'subscription', 'user'
    target_id INTEGER,

    -- Action details
    action_config JSONB DEFAULT '{}', -- task-specific config

    -- Status
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed', 'cancelled'
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    error_message TEXT,
    result JSONB,

    -- Priority
    priority INTEGER DEFAULT 5, -- 1-10, lower = higher priority

    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Reminders
CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    reminder_type VARCHAR(50) DEFAULT 'general', -- 'general', 'follow_up', 'payment', 'renewal', 'appointment'

    -- When
    remind_at TIMESTAMP NOT NULL,

    -- Who
    user_id INTEGER REFERENCES users(id),
    customer_id INTEGER,

    -- What
    related_type VARCHAR(50), -- 'event', 'invoice', 'subscription', 'task', 'customer'
    related_id INTEGER,

    -- Status
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'sent', 'dismissed', 'snoozed'
    snoozed_until TIMESTAMP,

    -- Notification
    notification_channels JSONB DEFAULT '["in_app"]', -- 'in_app', 'email', 'sms'
    sent_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Availability/Working hours
CREATE TABLE IF NOT EXISTS user_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    day_of_week INTEGER NOT NULL, -- 0=Sunday, 1=Monday, etc.
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'America/Toronto',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Time blocks (blocked time, vacations, etc.)
CREATE TABLE IF NOT EXISTS time_blocks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    block_type VARCHAR(50) DEFAULT 'busy', -- 'busy', 'vacation', 'out_of_office', 'focus_time'
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_customer ON calendar_events(customer_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_type ON calendar_events(event_type);
CREATE INDEX IF NOT EXISTS idx_calendar_events_status ON calendar_events(status);
CREATE INDEX IF NOT EXISTS idx_subscription_schedules_next ON subscription_schedules(next_billing_date, status);
CREATE INDEX IF NOT EXISTS idx_subscription_schedules_customer ON subscription_schedules(customer_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_scheduled ON scheduled_tasks(scheduled_for, status);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_type ON scheduled_tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_reminders_remind ON reminders(remind_at, status);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_user_availability_user ON user_availability(user_id);
CREATE INDEX IF NOT EXISTS idx_time_blocks_user ON time_blocks(user_id, start_time);

-- Insert default availability (Mon-Fri 9am-5pm)
INSERT INTO user_availability (user_id, day_of_week, start_time, end_time, is_available)
SELECT u.id, dow.day, '09:00:00', '17:00:00', dow.day BETWEEN 1 AND 5
FROM users u
CROSS JOIN (VALUES (0), (1), (2), (3), (4), (5), (6)) AS dow(day)
WHERE u.id = 1
ON CONFLICT DO NOTHING;

-- Function to get upcoming reminders
CREATE OR REPLACE FUNCTION get_due_reminders(p_user_id INTEGER DEFAULT NULL)
RETURNS TABLE (
    id INTEGER,
    title VARCHAR,
    message TEXT,
    reminder_type VARCHAR,
    remind_at TIMESTAMP,
    user_id INTEGER,
    customer_id INTEGER,
    related_type VARCHAR,
    related_id INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT r.id, r.title, r.message, r.reminder_type, r.remind_at,
           r.user_id, r.customer_id, r.related_type, r.related_id
    FROM reminders r
    WHERE r.status = 'pending'
      AND r.remind_at <= NOW()
      AND (p_user_id IS NULL OR r.user_id = p_user_id)
    ORDER BY r.remind_at;
END;
$$ LANGUAGE plpgsql;

-- Function to process due scheduled tasks
CREATE OR REPLACE FUNCTION get_due_scheduled_tasks()
RETURNS TABLE (
    id INTEGER,
    name VARCHAR,
    task_type VARCHAR,
    target_type VARCHAR,
    target_id INTEGER,
    action_config JSONB,
    attempts INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT t.id, t.name, t.task_type, t.target_type, t.target_id, t.action_config, t.attempts
    FROM scheduled_tasks t
    WHERE t.status = 'pending'
      AND t.scheduled_for <= NOW()
      AND t.attempts < t.max_attempts
    ORDER BY t.priority, t.scheduled_for;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update subscription next billing date
CREATE OR REPLACE FUNCTION calculate_next_billing_date()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.billing_cycle = 'monthly' THEN
        NEW.next_billing_date := COALESCE(NEW.last_billed_date, NEW.start_date) + INTERVAL '1 month';
    ELSIF NEW.billing_cycle = 'yearly' THEN
        NEW.next_billing_date := COALESCE(NEW.last_billed_date, NEW.start_date) + INTERVAL '1 year';
    ELSIF NEW.billing_cycle = 'weekly' THEN
        NEW.next_billing_date := COALESCE(NEW.last_billed_date, NEW.start_date) + INTERVAL '1 week';
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_calculate_billing ON subscription_schedules;
CREATE TRIGGER trigger_calculate_billing
    BEFORE INSERT OR UPDATE OF last_billed_date, billing_cycle ON subscription_schedules
    FOR EACH ROW
    EXECUTE FUNCTION calculate_next_billing_date();

-- Grant permissions
GRANT ALL ON calendar_events TO archie;
GRANT ALL ON subscription_schedules TO archie;
GRANT ALL ON scheduled_tasks TO archie;
GRANT ALL ON reminders TO archie;
GRANT ALL ON user_availability TO archie;
GRANT ALL ON time_blocks TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE calendar_events IS 'Calendar events with recurrence support';
COMMENT ON TABLE subscription_schedules IS 'Subscription renewal tracking';
COMMENT ON TABLE scheduled_tasks IS 'Future automated tasks queue';
COMMENT ON TABLE reminders IS 'User and customer reminders';
COMMENT ON TABLE user_availability IS 'User working hours by day';
COMMENT ON TABLE time_blocks IS 'Blocked time periods (vacation, busy, etc.)';
