-- ============================================================================
-- Migration 018: Analytics Tables
-- Purpose: Unified metrics and dashboards for Business Tools
-- Created: 2026-01-17
-- ============================================================================

-- Daily analytics snapshots
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    snapshot_type VARCHAR(50) NOT NULL, -- 'daily', 'weekly', 'monthly'

    -- Revenue metrics
    revenue_total DECIMAL(12,2) DEFAULT 0,
    revenue_subscriptions DECIMAL(12,2) DEFAULT 0,
    revenue_orders DECIMAL(12,2) DEFAULT 0,
    revenue_invoices DECIMAL(12,2) DEFAULT 0,

    -- Customer metrics
    customers_total INTEGER DEFAULT 0,
    customers_new INTEGER DEFAULT 0,
    customers_active INTEGER DEFAULT 0,
    customers_churned INTEGER DEFAULT 0,

    -- Subscription metrics
    subscriptions_total INTEGER DEFAULT 0,
    subscriptions_new INTEGER DEFAULT 0,
    subscriptions_cancelled INTEGER DEFAULT 0,
    mrr DECIMAL(12,2) DEFAULT 0, -- Monthly Recurring Revenue
    arr DECIMAL(12,2) DEFAULT 0, -- Annual Recurring Revenue

    -- Order metrics
    orders_total INTEGER DEFAULT 0,
    orders_completed INTEGER DEFAULT 0,
    orders_cancelled INTEGER DEFAULT 0,
    avg_order_value DECIMAL(10,2) DEFAULT 0,

    -- Invoice metrics
    invoices_total INTEGER DEFAULT 0,
    invoices_sent INTEGER DEFAULT 0,
    invoices_paid INTEGER DEFAULT 0,
    invoices_overdue INTEGER DEFAULT 0,
    invoices_amount_due DECIMAL(12,2) DEFAULT 0,

    -- Email metrics
    emails_sent INTEGER DEFAULT 0,
    emails_opened INTEGER DEFAULT 0,
    emails_clicked INTEGER DEFAULT 0,
    email_open_rate DECIMAL(5,2) DEFAULT 0,

    -- Call Center metrics
    calls_total INTEGER DEFAULT 0,
    calls_answered INTEGER DEFAULT 0,
    calls_missed INTEGER DEFAULT 0,
    avg_call_duration INTEGER DEFAULT 0, -- seconds
    call_satisfaction DECIMAL(3,2) DEFAULT 0,

    -- Website metrics
    page_views INTEGER DEFAULT 0,
    unique_visitors INTEGER DEFAULT 0,

    -- Store metrics
    store_visits INTEGER DEFAULT 0,
    store_conversions INTEGER DEFAULT 0,
    conversion_rate DECIMAL(5,2) DEFAULT 0,

    -- Raw data for drill-down
    raw_data JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(snapshot_date, snapshot_type)
);

-- Custom dashboards
CREATE TABLE IF NOT EXISTS analytics_dashboards (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    is_default BOOLEAN DEFAULT FALSE,
    layout JSONB DEFAULT '[]', -- Widget positions and sizes
    filters JSONB DEFAULT '{}', -- Default filters
    refresh_interval INTEGER DEFAULT 300, -- seconds
    user_id INTEGER REFERENCES users(id),
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Dashboard widgets
CREATE TABLE IF NOT EXISTS analytics_widgets (
    id SERIAL PRIMARY KEY,
    dashboard_id INTEGER REFERENCES analytics_dashboards(id) ON DELETE CASCADE,
    widget_type VARCHAR(50) NOT NULL, -- 'metric', 'chart', 'table', 'list'
    title VARCHAR(200),
    data_source VARCHAR(100), -- 'revenue', 'customers', 'subscriptions', 'orders', etc.
    chart_type VARCHAR(50), -- 'line', 'bar', 'pie', 'donut', 'area'
    config JSONB DEFAULT '{}', -- Widget-specific configuration
    position_x INTEGER DEFAULT 0,
    position_y INTEGER DEFAULT 0,
    width INTEGER DEFAULT 4,
    height INTEGER DEFAULT 2,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Saved reports
CREATE TABLE IF NOT EXISTS analytics_reports (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    report_type VARCHAR(50), -- 'revenue', 'customers', 'subscriptions', 'calls', 'custom'
    date_range VARCHAR(50), -- 'today', 'week', 'month', 'quarter', 'year', 'custom'
    start_date DATE,
    end_date DATE,
    filters JSONB DEFAULT '{}',
    columns JSONB DEFAULT '[]',
    group_by VARCHAR(50),
    is_scheduled BOOLEAN DEFAULT FALSE,
    schedule_cron VARCHAR(100),
    email_recipients TEXT[], -- array of emails
    last_run_at TIMESTAMP,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Metric definitions (for custom metrics)
CREATE TABLE IF NOT EXISTS analytics_metrics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    description TEXT,
    category VARCHAR(50), -- 'revenue', 'customers', 'performance', 'engagement'
    data_type VARCHAR(50) DEFAULT 'number', -- 'number', 'currency', 'percentage', 'duration'
    calculation_sql TEXT, -- SQL to calculate the metric
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Goals/Targets
CREATE TABLE IF NOT EXISTS analytics_goals (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    metric_name VARCHAR(100) NOT NULL, -- links to analytics_metrics.name or builtin
    target_value DECIMAL(15,2) NOT NULL,
    current_value DECIMAL(15,2) DEFAULT 0,
    period VARCHAR(50) NOT NULL, -- 'daily', 'weekly', 'monthly', 'quarterly', 'yearly'
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(50) DEFAULT 'in_progress', -- 'in_progress', 'achieved', 'missed'
    progress_percentage DECIMAL(5,2) DEFAULT 0,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_date ON analytics_snapshots(snapshot_date, snapshot_type);
CREATE INDEX IF NOT EXISTS idx_analytics_dashboards_user ON analytics_dashboards(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_widgets_dashboard ON analytics_widgets(dashboard_id);
CREATE INDEX IF NOT EXISTS idx_analytics_reports_user ON analytics_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_goals_period ON analytics_goals(period, start_date, end_date);

-- Insert default metrics
INSERT INTO analytics_metrics (name, display_name, description, category, data_type) VALUES
    ('total_revenue', 'Total Revenue', 'Sum of all revenue from orders, subscriptions, and invoices', 'revenue', 'currency'),
    ('mrr', 'Monthly Recurring Revenue', 'Total monthly revenue from active subscriptions', 'revenue', 'currency'),
    ('arr', 'Annual Recurring Revenue', 'MRR multiplied by 12', 'revenue', 'currency'),
    ('avg_order_value', 'Average Order Value', 'Average value of completed orders', 'revenue', 'currency'),
    ('total_customers', 'Total Customers', 'Total number of customers in CRM', 'customers', 'number'),
    ('new_customers', 'New Customers', 'Customers added in the period', 'customers', 'number'),
    ('churn_rate', 'Churn Rate', 'Percentage of customers lost', 'customers', 'percentage'),
    ('email_open_rate', 'Email Open Rate', 'Percentage of emails opened', 'engagement', 'percentage'),
    ('call_satisfaction', 'Call Satisfaction', 'Average satisfaction score from calls', 'performance', 'number'),
    ('conversion_rate', 'Conversion Rate', 'Percentage of visits that convert to orders', 'performance', 'percentage')
ON CONFLICT (name) DO NOTHING;

-- Insert default dashboard
INSERT INTO analytics_dashboards (name, description, is_default, is_public, layout) VALUES
    ('Business Overview', 'Main dashboard with key business metrics', true, true, '[
        {"widget": "revenue_total", "x": 0, "y": 0, "w": 3, "h": 1},
        {"widget": "customers_total", "x": 3, "y": 0, "w": 3, "h": 1},
        {"widget": "subscriptions_active", "x": 6, "y": 0, "w": 3, "h": 1},
        {"widget": "orders_today", "x": 9, "y": 0, "w": 3, "h": 1},
        {"widget": "revenue_chart", "x": 0, "y": 1, "w": 8, "h": 3},
        {"widget": "top_customers", "x": 8, "y": 1, "w": 4, "h": 3}
    ]'::jsonb)
ON CONFLICT DO NOTHING;

-- Function to generate daily snapshot
CREATE OR REPLACE FUNCTION generate_daily_snapshot(p_date DATE DEFAULT CURRENT_DATE)
RETURNS INTEGER AS $$
DECLARE
    v_snapshot_id INTEGER;
BEGIN
    -- Delete existing snapshot for this date
    DELETE FROM analytics_snapshots WHERE snapshot_date = p_date AND snapshot_type = 'daily';

    -- Create new snapshot
    INSERT INTO analytics_snapshots (
        snapshot_date, snapshot_type,
        revenue_total, revenue_subscriptions, revenue_orders, revenue_invoices,
        customers_total, customers_new, customers_active,
        subscriptions_total, subscriptions_new, subscriptions_cancelled, mrr,
        orders_total, orders_completed, avg_order_value,
        invoices_total, invoices_sent, invoices_paid, invoices_overdue,
        emails_sent, emails_opened, email_open_rate,
        calls_total, calls_answered
    )
    SELECT
        p_date,
        'daily',
        -- Revenue (from invoices paid today)
        COALESCE((SELECT SUM(total) FROM invoices WHERE paid_at::DATE = p_date), 0),
        COALESCE((SELECT SUM(amount) FROM subscription_schedules WHERE last_billed_date = p_date), 0),
        0, -- orders placeholder
        COALESCE((SELECT SUM(total) FROM invoices WHERE paid_at::DATE = p_date), 0),
        -- Customers
        COALESCE((SELECT COUNT(*) FROM crm_customers), 0),
        COALESCE((SELECT COUNT(*) FROM crm_customers WHERE created_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM crm_customers WHERE last_activity >= p_date - INTERVAL '30 days'), 0),
        -- Subscriptions
        COALESCE((SELECT COUNT(*) FROM subscription_schedules WHERE status = 'active'), 0),
        COALESCE((SELECT COUNT(*) FROM subscription_schedules WHERE created_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM subscription_schedules WHERE status = 'cancelled' AND updated_at::DATE = p_date), 0),
        COALESCE((SELECT SUM(amount) FROM subscription_schedules WHERE status = 'active' AND billing_cycle = 'monthly'), 0),
        -- Orders placeholder
        0, 0, 0,
        -- Invoices
        COALESCE((SELECT COUNT(*) FROM invoices WHERE created_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM invoices WHERE sent_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM invoices WHERE paid_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM invoices WHERE status = 'overdue'), 0),
        -- Emails
        COALESCE((SELECT COUNT(*) FROM email_logs WHERE sent_at::DATE = p_date), 0),
        COALESCE((SELECT COUNT(*) FROM email_logs WHERE opened_at::DATE = p_date), 0),
        COALESCE(
            (SELECT ROUND(COUNT(*) FILTER (WHERE opened_at IS NOT NULL)::DECIMAL / NULLIF(COUNT(*), 0) * 100, 2)
             FROM email_logs WHERE sent_at::DATE = p_date), 0
        ),
        -- Calls placeholder
        0, 0
    RETURNING id INTO v_snapshot_id;

    -- Update ARR
    UPDATE analytics_snapshots
    SET arr = mrr * 12
    WHERE id = v_snapshot_id;

    RETURN v_snapshot_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get metric value
CREATE OR REPLACE FUNCTION get_metric_value(p_metric VARCHAR, p_date_from DATE DEFAULT NULL, p_date_to DATE DEFAULT NULL)
RETURNS DECIMAL AS $$
DECLARE
    v_result DECIMAL;
    v_from DATE := COALESCE(p_date_from, CURRENT_DATE - INTERVAL '30 days');
    v_to DATE := COALESCE(p_date_to, CURRENT_DATE);
BEGIN
    CASE p_metric
        WHEN 'total_revenue' THEN
            SELECT COALESCE(SUM(revenue_total), 0) INTO v_result
            FROM analytics_snapshots
            WHERE snapshot_date BETWEEN v_from AND v_to AND snapshot_type = 'daily';
        WHEN 'mrr' THEN
            SELECT COALESCE(mrr, 0) INTO v_result
            FROM analytics_snapshots
            WHERE snapshot_date = v_to AND snapshot_type = 'daily'
            ORDER BY snapshot_date DESC LIMIT 1;
        WHEN 'arr' THEN
            SELECT COALESCE(arr, 0) INTO v_result
            FROM analytics_snapshots
            WHERE snapshot_date = v_to AND snapshot_type = 'daily'
            ORDER BY snapshot_date DESC LIMIT 1;
        WHEN 'total_customers' THEN
            SELECT COUNT(*) INTO v_result FROM crm_customers;
        WHEN 'new_customers' THEN
            SELECT COUNT(*) INTO v_result
            FROM crm_customers WHERE created_at::DATE BETWEEN v_from AND v_to;
        WHEN 'active_subscriptions' THEN
            SELECT COUNT(*) INTO v_result
            FROM subscription_schedules WHERE status = 'active';
        ELSE
            v_result := 0;
    END CASE;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON analytics_snapshots TO archie;
GRANT ALL ON analytics_dashboards TO archie;
GRANT ALL ON analytics_widgets TO archie;
GRANT ALL ON analytics_reports TO archie;
GRANT ALL ON analytics_metrics TO archie;
GRANT ALL ON analytics_goals TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE analytics_snapshots IS 'Daily/weekly/monthly aggregated metrics';
COMMENT ON TABLE analytics_dashboards IS 'Custom dashboard configurations';
COMMENT ON TABLE analytics_widgets IS 'Widgets within dashboards';
COMMENT ON TABLE analytics_reports IS 'Saved and scheduled reports';
COMMENT ON TABLE analytics_metrics IS 'Metric definitions for custom analytics';
COMMENT ON TABLE analytics_goals IS 'Business goals and targets';
