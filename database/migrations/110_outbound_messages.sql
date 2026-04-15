BEGIN;

CREATE TABLE IF NOT EXISTS outbound_messages (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    source_agent VARCHAR(100),
    source_department VARCHAR(100),
    source_module VARCHAR(100),
    channel VARCHAR(20) DEFAULT 'telegram',
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    result JSONB
);

CREATE INDEX IF NOT EXISTS idx_outbound_pending
    ON outbound_messages(status) WHERE status = 'pending';

COMMIT;
