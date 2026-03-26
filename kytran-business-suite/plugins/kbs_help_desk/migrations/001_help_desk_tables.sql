-- Help Desk plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS support_tickets (
    id              SERIAL PRIMARY KEY,
    ticket_number   VARCHAR(20) UNIQUE NOT NULL,
    customer_id     INTEGER,
    subject         VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(20) DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'waiting', 'resolved', 'closed')),
    priority        VARCHAR(20) DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    category        VARCHAR(100),
    assigned_to     VARCHAR(255),
    tags            JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    resolved_at     TIMESTAMP,
    closed_at       TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_comments (
    id          SERIAL PRIMARY KEY,
    ticket_id   INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    author      VARCHAR(255) NOT NULL,
    content     TEXT NOT NULL,
    is_internal BOOLEAN DEFAULT FALSE,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sla_policies (
    id                   SERIAL PRIMARY KEY,
    name                 VARCHAR(255) NOT NULL,
    priority             VARCHAR(20) NOT NULL,
    first_response_hours INTEGER DEFAULT 24,
    resolution_hours     INTEGER DEFAULT 72,
    is_active            BOOLEAN DEFAULT TRUE,
    created_at           TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_support_tickets_customer_id ON support_tickets (customer_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status      ON support_tickets (status);
CREATE INDEX IF NOT EXISTS idx_support_tickets_priority    ON support_tickets (priority);
CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at  ON support_tickets (created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket_id   ON ticket_comments (ticket_id);
