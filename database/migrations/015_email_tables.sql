-- ============================================================================
-- Migration 015: Email Manager Tables
-- Purpose: Email templates, sending, and tracking for Business Tools
-- Created: 2026-01-17
-- ============================================================================

-- Email templates
CREATE TABLE IF NOT EXISTS email_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    body_html TEXT,
    body_text TEXT,
    template_type VARCHAR(50) DEFAULT 'custom', -- 'invoice', 'order_confirm', 'shipping', 'renewal', 'welcome', 'custom'
    variables JSONB DEFAULT '{}', -- available template variables
    is_active BOOLEAN DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Email send logs
CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES email_templates(id),
    recipient VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(255),
    subject VARCHAR(255) NOT NULL,
    body_preview TEXT, -- first 500 chars
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'sent', 'failed', 'bounced', 'opened', 'clicked'
    error_message TEXT,
    metadata JSONB DEFAULT '{}', -- additional data like customer_id, invoice_id, etc.
    sent_at TIMESTAMP,
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- SMTP settings
CREATE TABLE IF NOT EXISTS email_settings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) DEFAULT 'Default',
    smtp_host VARCHAR(255),
    smtp_port INTEGER DEFAULT 587,
    smtp_user VARCHAR(255),
    smtp_password_encrypted TEXT,
    encryption VARCHAR(20) DEFAULT 'tls', -- 'none', 'ssl', 'tls'
    from_email VARCHAR(255),
    from_name VARCHAR(255),
    reply_to VARCHAR(255),
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    test_result VARCHAR(50), -- 'success', 'failed', null
    test_message TEXT,
    tested_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Email queue (for bulk/scheduled sending)
CREATE TABLE IF NOT EXISTS email_queue (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES email_templates(id),
    recipient VARCHAR(255) NOT NULL,
    recipient_name VARCHAR(255),
    subject VARCHAR(255),
    body_html TEXT,
    variables JSONB DEFAULT '{}', -- merged variables
    scheduled_for TIMESTAMP DEFAULT NOW(),
    priority INTEGER DEFAULT 5, -- 1-10, lower = higher priority
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'processing', 'sent', 'failed'
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Email campaigns (for bulk sends)
CREATE TABLE IF NOT EXISTS email_campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    template_id INTEGER REFERENCES email_templates(id),
    segment_id INTEGER REFERENCES crm_segments(id),
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'scheduled', 'sending', 'sent', 'cancelled'
    scheduled_for TIMESTAMP,
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    opened_count INTEGER DEFAULT 0,
    clicked_count INTEGER DEFAULT 0,
    bounced_count INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_templates_type ON email_templates(template_type);
CREATE INDEX IF NOT EXISTS idx_email_templates_active ON email_templates(is_active);
CREATE INDEX IF NOT EXISTS idx_email_logs_recipient ON email_logs(recipient);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);
CREATE INDEX IF NOT EXISTS idx_email_logs_created ON email_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_email_logs_template ON email_logs(template_id);
CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_queue(status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_email_queue_priority ON email_queue(priority, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_email_campaigns_status ON email_campaigns(status);

-- Insert default templates
INSERT INTO email_templates (name, subject, body_html, body_text, template_type, variables) VALUES
    ('Welcome Email', 'Welcome to Kytran Empowerment!',
     '<h1>Welcome, {{first_name}}!</h1><p>Thank you for joining Kytran Empowerment. We''re excited to have you!</p><p>Best regards,<br>The Kytran Empowerment Team</p>',
     'Welcome, {{first_name}}!\n\nThank you for joining Kytran Empowerment. We''re excited to have you!\n\nBest regards,\nThe Kytran Empowerment Team',
     'welcome',
     '{"first_name": "Customer first name", "email": "Customer email"}'),

    ('Order Confirmation', 'Order Confirmed - #{{order_id}}',
     '<h1>Thank you for your order!</h1><p>Hi {{first_name}},</p><p>Your order #{{order_id}} has been confirmed and is being processed.</p><p><strong>Order Total:</strong> ${{total}}</p><p>We''ll send you a shipping confirmation once your order ships.</p>',
     'Thank you for your order!\n\nHi {{first_name}},\n\nYour order #{{order_id}} has been confirmed and is being processed.\n\nOrder Total: ${{total}}\n\nWe''ll send you a shipping confirmation once your order ships.',
     'order_confirm',
     '{"first_name": "Customer first name", "order_id": "Order number", "total": "Order total"}'),

    ('Invoice', 'Invoice #{{invoice_number}} from Kytran Empowerment',
     '<h1>Invoice #{{invoice_number}}</h1><p>Hi {{first_name}},</p><p>Please find your invoice attached.</p><p><strong>Amount Due:</strong> ${{total}}<br><strong>Due Date:</strong> {{due_date}}</p><p>Thank you for your business!</p>',
     'Invoice #{{invoice_number}}\n\nHi {{first_name}},\n\nPlease find your invoice attached.\n\nAmount Due: ${{total}}\nDue Date: {{due_date}}\n\nThank you for your business!',
     'invoice',
     '{"first_name": "Customer first name", "invoice_number": "Invoice number", "total": "Invoice total", "due_date": "Payment due date"}'),

    ('Subscription Renewal', 'Your subscription is renewing soon',
     '<h1>Subscription Renewal Reminder</h1><p>Hi {{first_name}},</p><p>Your {{tier}} subscription will renew on {{renewal_date}}.</p><p><strong>Amount:</strong> ${{amount}}</p><p>No action is required. Your subscription will automatically renew.</p>',
     'Subscription Renewal Reminder\n\nHi {{first_name}},\n\nYour {{tier}} subscription will renew on {{renewal_date}}.\n\nAmount: ${{amount}}\n\nNo action is required. Your subscription will automatically renew.',
     'renewal',
     '{"first_name": "Customer first name", "tier": "Subscription tier", "renewal_date": "Renewal date", "amount": "Renewal amount"}'),

    ('Password Reset', 'Reset your password',
     '<h1>Password Reset Request</h1><p>Hi {{first_name}},</p><p>Click the link below to reset your password:</p><p><a href="{{reset_link}}">Reset Password</a></p><p>This link expires in 24 hours.</p><p>If you didn''t request this, please ignore this email.</p>',
     'Password Reset Request\n\nHi {{first_name}},\n\nClick the link below to reset your password:\n\n{{reset_link}}\n\nThis link expires in 24 hours.\n\nIf you didn''t request this, please ignore this email.',
     'custom',
     '{"first_name": "Customer first name", "reset_link": "Password reset URL"}')
ON CONFLICT DO NOTHING;

-- Insert default email settings (placeholder)
INSERT INTO email_settings (name, smtp_host, smtp_port, from_email, from_name, is_default) VALUES
    ('Default SMTP', 'smtp.example.com', 587, 'noreply@kytranempowerment.com', 'Kytran Empowerment', true)
ON CONFLICT DO NOTHING;

-- Grant permissions
GRANT ALL ON email_templates TO archie;
GRANT ALL ON email_logs TO archie;
GRANT ALL ON email_settings TO archie;
GRANT ALL ON email_queue TO archie;
GRANT ALL ON email_campaigns TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Add comments
COMMENT ON TABLE email_templates IS 'Reusable email templates with variable substitution';
COMMENT ON TABLE email_logs IS 'Log of all sent emails with tracking';
COMMENT ON TABLE email_settings IS 'SMTP configuration for sending emails';
COMMENT ON TABLE email_queue IS 'Queue for scheduled/bulk email sending';
COMMENT ON TABLE email_campaigns IS 'Bulk email campaigns to segments';
