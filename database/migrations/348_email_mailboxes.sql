-- Migration 348: email_mailboxes
-- Tracks all provisioned mailboxes (AI agents + business + human)

CREATE TABLE IF NOT EXISTS email_mailboxes (
    id SERIAL PRIMARY KEY,
    address VARCHAR(200) NOT NULL UNIQUE,
    mailbox_type VARCHAR(20) NOT NULL CHECK (mailbox_type IN ('ai_agent', 'human_agent', 'business')),
    owner_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    display_name VARCHAR(200),
    provisioned BOOLEAN DEFAULT FALSE,
    provisioned_at TIMESTAMP,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed AI agent mailboxes (not yet provisioned in Stalwart)
-- Uses REPLACE(name, '.', '') to convert "F.O.R.G.E." -> "forge"
INSERT INTO email_mailboxes (address, mailbox_type, owner_agent_id, display_name)
SELECT
    LOWER(REPLACE(name, '.', '')) || '@kytranempowerment.com',
    'ai_agent',
    id,
    name
FROM agents
WHERE worker_type = 'ai'
  AND status != 'decommissioned'
ON CONFLICT (address) DO NOTHING;

-- Seed business addresses
INSERT INTO email_mailboxes (address, mailbox_type, display_name) VALUES
    ('billing@kytranempowerment.com',  'business', 'Billing'),
    ('support@kytranempowerment.com',  'business', 'Support'),
    ('info@kytranempowerment.com',     'business', 'Info'),
    ('admin@kytranempowerment.com',    'business', 'Admin'),
    ('security@kytranempowerment.com', 'business', 'Security'),
    ('no-reply@kytranempowerment.com', 'business', 'No Reply'),
    ('hello@kytranempowerment.com',    'business', 'Hello'),
    ('careers@kytranempowerment.com',  'business', 'Careers'),
    ('press@kytranempowerment.com',    'business', 'Press'),
    ('legal@kytranempowerment.com',    'business', 'Legal')
ON CONFLICT (address) DO NOTHING;
