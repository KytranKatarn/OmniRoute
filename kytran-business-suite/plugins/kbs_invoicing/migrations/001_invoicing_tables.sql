-- Invoicing plugin tables (runs inside tenant schema)

CREATE TABLE IF NOT EXISTS invoice_settings (
    id                  SERIAL PRIMARY KEY,
    company_name        VARCHAR(255),
    tax_rate            DECIMAL(5,2)  DEFAULT 13.00,
    invoice_prefix      VARCHAR(20)   DEFAULT 'INV',
    next_invoice_number INT           DEFAULT 1001,
    payment_instructions TEXT,
    created_at          TIMESTAMP     DEFAULT NOW()
);

-- Seed default settings row so lookups always find one
INSERT INTO invoice_settings (company_name) VALUES (NULL) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS invoices (
    id              SERIAL PRIMARY KEY,
    invoice_number  VARCHAR(50) UNIQUE NOT NULL,
    customer_id     INT REFERENCES crm_customers(id) ON DELETE SET NULL,
    status          VARCHAR(20) DEFAULT 'draft'
                        CHECK (status IN ('draft','sent','paid','overdue','void')),
    subtotal        DECIMAL(10,2) DEFAULT 0,
    tax_rate        DECIMAL(5,2)  DEFAULT 13.00,
    tax             DECIMAL(10,2) DEFAULT 0,
    total           DECIMAL(10,2) DEFAULT 0,
    amount_paid     DECIMAL(10,2) DEFAULT 0,
    balance_due     DECIMAL(10,2) DEFAULT 0,
    due_date        DATE,
    payment_method  VARCHAR(50),
    notes           TEXT,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_customer_id ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status       ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_due_date     ON invoices(due_date);

CREATE TABLE IF NOT EXISTS invoice_items (
    id          SERIAL PRIMARY KEY,
    invoice_id  INT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description VARCHAR(255) NOT NULL,
    quantity    DECIMAL(10,2) DEFAULT 1,
    unit_price  DECIMAL(10,2) NOT NULL,
    amount      DECIMAL(10,2) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoice_payments (
    id                 SERIAL PRIMARY KEY,
    invoice_id         INT NOT NULL REFERENCES invoices(id),
    amount             DECIMAL(10,2) NOT NULL,
    payment_method     VARCHAR(50),
    payment_reference  VARCHAR(255),
    payment_date       TIMESTAMP DEFAULT NOW()
);
