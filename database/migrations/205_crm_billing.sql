-- CRM ↔ Billing customer linking
CREATE TABLE IF NOT EXISTS crm_billing_link (
    id SERIAL PRIMARY KEY,
    crm_customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
    billing_customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
    linked_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(crm_customer_id),
    UNIQUE(billing_customer_id)
);
CREATE INDEX IF NOT EXISTS idx_crm_billing_crm ON crm_billing_link(crm_customer_id);
CREATE INDEX IF NOT EXISTS idx_crm_billing_billing ON crm_billing_link(billing_customer_id);
