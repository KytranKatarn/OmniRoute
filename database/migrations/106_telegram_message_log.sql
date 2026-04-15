BEGIN;

-- Telegram message log — every outbound message through A.R.C.H.I.E.'s voice
CREATE TABLE IF NOT EXISTS telegram_message_log (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL DEFAULT 'info',
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    formatted_message TEXT,
    source_agent VARCHAR(100),
    source_department VARCHAR(100),
    source_module VARCHAR(100),
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'sent',  -- sent, throttled, failed, queued
    error_message TEXT,
    chat_id VARCHAR(50),
    telegram_message_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tg_log_created ON telegram_message_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tg_log_category ON telegram_message_log(category);
CREATE INDEX IF NOT EXISTS idx_tg_log_source ON telegram_message_log(source_agent);
CREATE INDEX IF NOT EXISTS idx_tg_log_status ON telegram_message_log(status);

COMMIT;
