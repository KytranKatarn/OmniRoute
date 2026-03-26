-- Accounting plugin tables (runs inside tenant schema)

CREATE TABLE IF NOT EXISTS chart_of_accounts (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(20)  NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    account_type VARCHAR(50)  NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    sub_type     VARCHAR(50),
    description  TEXT,
    is_active    BOOLEAN      DEFAULT true,
    parent_id    INT          REFERENCES chart_of_accounts(id),
    balance      DECIMAL(12,2) DEFAULT 0,
    created_at   TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coa_account_type ON chart_of_accounts(account_type);

CREATE TABLE IF NOT EXISTS transactions (
    id               SERIAL PRIMARY KEY,
    date             DATE         NOT NULL DEFAULT CURRENT_DATE,
    reference        VARCHAR(100),
    description      TEXT         NOT NULL,
    amount           DECIMAL(12,2) NOT NULL,
    transaction_type VARCHAR(20)  NOT NULL CHECK (transaction_type IN ('income', 'expense', 'transfer', 'journal')),
    category         VARCHAR(100),
    account_id       INT          REFERENCES chart_of_accounts(id),
    customer_id      INT,
    invoice_id       INT,
    status           VARCHAR(20)  DEFAULT 'recorded' CHECK (status IN ('recorded', 'reconciled', 'voided')),
    tags             JSONB        DEFAULT '[]',
    metadata         JSONB        DEFAULT '{}',
    created_at       TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_date             ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_account_id       ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_transaction_type ON transactions(transaction_type);

CREATE TABLE IF NOT EXISTS expenses (
    id             SERIAL PRIMARY KEY,
    date           DATE         NOT NULL DEFAULT CURRENT_DATE,
    vendor         VARCHAR(255) NOT NULL,
    description    TEXT,
    amount         DECIMAL(12,2) NOT NULL,
    category       VARCHAR(100),
    account_id     INT          REFERENCES chart_of_accounts(id),
    payment_method VARCHAR(50),
    receipt_url    TEXT,
    is_billable    BOOLEAN      DEFAULT false,
    customer_id    INT,
    status         VARCHAR(20)  DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'paid', 'voided')),
    tags           JSONB        DEFAULT '[]',
    metadata       JSONB        DEFAULT '{}',
    created_at     TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_expenses_date     ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_expenses_vendor   ON expenses(vendor);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);

CREATE TABLE IF NOT EXISTS tax_rates (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    rate        DECIMAL(5,2) NOT NULL,
    description TEXT,
    is_default  BOOLEAN      DEFAULT false,
    is_active   BOOLEAN      DEFAULT true,
    created_at  TIMESTAMP    DEFAULT NOW()
);

-- Seed default chart of accounts
INSERT INTO chart_of_accounts (code, name, account_type, sub_type) VALUES
('1000', 'Cash',                   'asset',     'current_asset'),
('1100', 'Accounts Receivable',    'asset',     'current_asset'),
('1200', 'Inventory',              'asset',     'current_asset'),
('2000', 'Accounts Payable',       'liability', 'current_liability'),
('2100', 'Credit Card',            'liability', 'current_liability'),
('3000', 'Owner Equity',           'equity',    'equity'),
('3100', 'Retained Earnings',      'equity',    'equity'),
('4000', 'Sales Revenue',          'revenue',   'income'),
('4100', 'Service Revenue',        'revenue',   'income'),
('4200', 'Other Income',           'revenue',   'income'),
('5000', 'Cost of Goods Sold',     'expense',   'cogs'),
('6000', 'Rent Expense',           'expense',   'operating'),
('6100', 'Utilities',              'expense',   'operating'),
('6200', 'Office Supplies',        'expense',   'operating'),
('6300', 'Payroll',                'expense',   'operating'),
('6400', 'Marketing',              'expense',   'operating'),
('6500', 'Insurance',              'expense',   'operating'),
('6600', 'Professional Services',  'expense',   'operating'),
('6700', 'Software & Subscriptions','expense',  'operating'),
('7000', 'Tax Expense',            'expense',   'tax')
ON CONFLICT (code) DO NOTHING;

-- Seed default tax rates
INSERT INTO tax_rates (name, rate, description, is_default) VALUES
('HST Ontario', 13.00, 'Harmonized Sales Tax - Ontario', true),
('GST',          5.00, 'Goods and Services Tax',         false),
('PST',          8.00, 'Provincial Sales Tax',           false),
('Zero Rated',   0.00, 'Zero-rated supplies',            false)
ON CONFLICT DO NOTHING;
