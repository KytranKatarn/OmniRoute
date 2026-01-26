-- ============================================================================
-- Migration 016: Invoicing Tables
-- Purpose: Subscription billing and invoice management for Business Tools
-- Created: 2026-01-17
-- ============================================================================

-- Invoice headers
CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    customer_id INTEGER REFERENCES crm_customers(id),
    order_id INTEGER, -- optional link to store orders
    subscription_id INTEGER, -- link to user_subscriptions if recurring
    status VARCHAR(50) DEFAULT 'draft', -- draft, sent, paid, overdue, cancelled, refunded
    issue_date DATE DEFAULT CURRENT_DATE,
    due_date DATE,
    subtotal DECIMAL(10,2) DEFAULT 0.00,
    tax_rate DECIMAL(5,2) DEFAULT 0.00,
    tax_amount DECIMAL(10,2) DEFAULT 0.00,
    discount_amount DECIMAL(10,2) DEFAULT 0.00,
    discount_description VARCHAR(255),
    total DECIMAL(10,2) DEFAULT 0.00,
    amount_paid DECIMAL(10,2) DEFAULT 0.00,
    balance_due DECIMAL(10,2) DEFAULT 0.00,
    currency VARCHAR(3) DEFAULT 'CAD',
    notes TEXT,
    terms TEXT,
    payment_method VARCHAR(50), -- 'stripe', 'paypal', 'manual', 'bank_transfer'
    payment_reference VARCHAR(255), -- Stripe payment intent, PayPal transaction ID, etc.
    paid_at TIMESTAMP,
    sent_at TIMESTAMP,
    viewed_at TIMESTAMP,
    recurring BOOLEAN DEFAULT FALSE,
    recurring_interval VARCHAR(20), -- 'monthly', 'yearly', 'weekly'
    next_invoice_date DATE,
    pdf_url VARCHAR(500),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Invoice line items
CREATE TABLE IF NOT EXISTS invoice_items (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    description VARCHAR(500) NOT NULL,
    quantity DECIMAL(10,2) DEFAULT 1.00,
    unit_price DECIMAL(10,2) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    product_id INTEGER, -- optional link to store products
    subscription_tier VARCHAR(50), -- if this is a subscription charge
    tax_rate DECIMAL(5,2) DEFAULT 0.00,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Company invoice settings
CREATE TABLE IF NOT EXISTS invoice_settings (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200) DEFAULT 'Kytran Empowerment',
    company_address TEXT,
    company_phone VARCHAR(50),
    company_email VARCHAR(255),
    logo_url VARCHAR(500),
    default_terms TEXT DEFAULT 'Payment is due within 30 days of invoice date.',
    default_notes TEXT DEFAULT 'Thank you for your business!',
    invoice_prefix VARCHAR(20) DEFAULT 'INV-',
    next_invoice_number INTEGER DEFAULT 1001,
    default_tax_rate DECIMAL(5,2) DEFAULT 13.00, -- Ontario HST
    default_currency VARCHAR(3) DEFAULT 'CAD',
    payment_instructions TEXT,
    stripe_enabled BOOLEAN DEFAULT FALSE,
    paypal_enabled BOOLEAN DEFAULT FALSE,
    bank_details TEXT,
    footer_text TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Payment records
CREATE TABLE IF NOT EXISTS invoice_payments (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    amount DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(50),
    payment_reference VARCHAR(255),
    payment_date DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Recurring invoice schedules
CREATE TABLE IF NOT EXISTS recurring_invoices (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES crm_customers(id),
    subscription_id INTEGER,
    template_items JSONB, -- store line items as template
    interval VARCHAR(20) NOT NULL, -- 'weekly', 'monthly', 'yearly'
    next_invoice_date DATE NOT NULL,
    last_invoice_id INTEGER REFERENCES invoices(id),
    status VARCHAR(50) DEFAULT 'active', -- active, paused, cancelled
    auto_send BOOLEAN DEFAULT TRUE,
    auto_charge BOOLEAN DEFAULT FALSE,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Invoice activities (audit log)
CREATE TABLE IF NOT EXISTS invoice_activities (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    activity_type VARCHAR(50), -- 'created', 'sent', 'viewed', 'paid', 'refunded', 'updated'
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_created ON invoices(created_at);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_payments_invoice ON invoice_payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_recurring_invoices_next ON recurring_invoices(next_invoice_date, status);

-- Insert default invoice settings
INSERT INTO invoice_settings (
    company_name, company_email, company_phone, company_address,
    default_terms, invoice_prefix, default_tax_rate
) VALUES (
    'Kytran Empowerment',
    'billing@kytranempowerment.com',
    '1-800-XXX-XXXX',
    '123 Business Street\nToronto, ON M5V 1A1\nCanada',
    'Payment is due within 30 days of invoice date. Late payments may incur a 2% monthly interest charge.',
    'KE-',
    13.00
) ON CONFLICT DO NOTHING;

-- Function to generate invoice number
CREATE OR REPLACE FUNCTION generate_invoice_number()
RETURNS VARCHAR AS $$
DECLARE
    prefix VARCHAR;
    next_num INTEGER;
    result VARCHAR;
BEGIN
    SELECT invoice_prefix, next_invoice_number INTO prefix, next_num
    FROM invoice_settings LIMIT 1;

    result := prefix || LPAD(next_num::TEXT, 6, '0');

    UPDATE invoice_settings SET next_invoice_number = next_num + 1;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate invoice totals
CREATE OR REPLACE FUNCTION calculate_invoice_totals(p_invoice_id INTEGER)
RETURNS VOID AS $$
DECLARE
    v_subtotal DECIMAL(10,2);
    v_tax_rate DECIMAL(5,2);
    v_tax_amount DECIMAL(10,2);
    v_discount DECIMAL(10,2);
    v_total DECIMAL(10,2);
    v_paid DECIMAL(10,2);
BEGIN
    -- Calculate subtotal from items
    SELECT COALESCE(SUM(amount), 0) INTO v_subtotal
    FROM invoice_items WHERE invoice_id = p_invoice_id;

    -- Get invoice discount
    SELECT COALESCE(discount_amount, 0), COALESCE(tax_rate, 13) INTO v_discount, v_tax_rate
    FROM invoices WHERE id = p_invoice_id;

    -- Calculate tax and total
    v_tax_amount := (v_subtotal - v_discount) * (v_tax_rate / 100);
    v_total := v_subtotal - v_discount + v_tax_amount;

    -- Get amount paid
    SELECT COALESCE(SUM(amount), 0) INTO v_paid
    FROM invoice_payments WHERE invoice_id = p_invoice_id;

    -- Update invoice
    UPDATE invoices
    SET subtotal = v_subtotal,
        tax_amount = v_tax_amount,
        total = v_total,
        amount_paid = v_paid,
        balance_due = v_total - v_paid,
        updated_at = NOW()
    WHERE id = p_invoice_id;
END;
$$ LANGUAGE plpgsql;

-- Trigger to recalculate totals when items change
CREATE OR REPLACE FUNCTION trigger_recalculate_invoice()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM calculate_invoice_totals(OLD.invoice_id);
        RETURN OLD;
    ELSE
        PERFORM calculate_invoice_totals(NEW.invoice_id);
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_invoice_item_change ON invoice_items;
CREATE TRIGGER trigger_invoice_item_change
    AFTER INSERT OR UPDATE OR DELETE ON invoice_items
    FOR EACH ROW
    EXECUTE FUNCTION trigger_recalculate_invoice();

-- Grant permissions
GRANT ALL ON invoices TO archie;
GRANT ALL ON invoice_items TO archie;
GRANT ALL ON invoice_settings TO archie;
GRANT ALL ON invoice_payments TO archie;
GRANT ALL ON recurring_invoices TO archie;
GRANT ALL ON invoice_activities TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- Comments
COMMENT ON TABLE invoices IS 'Invoice headers with billing information';
COMMENT ON TABLE invoice_items IS 'Line items for each invoice';
COMMENT ON TABLE invoice_settings IS 'Company billing settings and branding';
COMMENT ON TABLE invoice_payments IS 'Payment records for invoices';
COMMENT ON TABLE recurring_invoices IS 'Recurring invoice schedules for subscriptions';
