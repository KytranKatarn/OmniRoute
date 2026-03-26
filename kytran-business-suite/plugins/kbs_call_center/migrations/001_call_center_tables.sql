-- Call Center plugin tables — run inside tenant schema (no tenant_id column needed).
-- All statements are idempotent.

CREATE TABLE IF NOT EXISTS call_phone_numbers (
    id          SERIAL PRIMARY KEY,
    number      VARCHAR(20) NOT NULL,
    provider    VARCHAR(50) CHECK (provider IN ('twilio', 'telnyx', 'telus', 'other')),
    label       VARCHAR(100),
    is_active   BOOLEAN DEFAULT TRUE,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS call_records (
    id               SERIAL PRIMARY KEY,
    phone_number_id  INTEGER REFERENCES call_phone_numbers(id) ON DELETE SET NULL,
    customer_id      INTEGER,
    direction        VARCHAR(10) CHECK (direction IN ('inbound', 'outbound')),
    status           VARCHAR(20) DEFAULT 'initiated'
                         CHECK (status IN ('initiated', 'ringing', 'in_progress', 'completed', 'missed', 'failed')),
    duration_seconds INTEGER DEFAULT 0,
    recording_url    TEXT,
    transcript       TEXT,
    notes            TEXT,
    metadata         JSONB DEFAULT '{}',
    started_at       TIMESTAMP DEFAULT NOW(),
    ended_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS call_escalations (
    id           SERIAL PRIMARY KEY,
    call_id      INTEGER NOT NULL REFERENCES call_records(id) ON DELETE CASCADE,
    reason       VARCHAR(255),
    priority     VARCHAR(20) DEFAULT 'normal'
                     CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    status       VARCHAR(20) DEFAULT 'pending'
                     CHECK (status IN ('pending', 'assigned', 'resolved')),
    assigned_to  VARCHAR(255),
    resolved_at  TIMESTAMP,
    notes        TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_call_records_customer_id  ON call_records (customer_id);
CREATE INDEX IF NOT EXISTS idx_call_records_status       ON call_records (status);
CREATE INDEX IF NOT EXISTS idx_call_records_started_at   ON call_records (started_at);
CREATE INDEX IF NOT EXISTS idx_call_escalations_status   ON call_escalations (status);
