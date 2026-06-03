-- ui_qa_queue: host-side Playwright UI-test runner queue (#371, 2026-06-03)
-- The archie_platform container has NO chromium; Playwright lives on the HOST.
-- So delegate_task(capability='run_qa_suite', args={'module': '<m>'}) ENQUEUES a
-- row here (in-container), and the host cron runner scripts/run_ui_qa_queue.py
-- drains it, runs `pytest qa/tests/modules/<m>.py` on the host, records pass/fail,
-- and posts the result back to the originating unified_tasks row (work_notes).
CREATE TABLE IF NOT EXISTS ui_qa_queue (
    id           SERIAL PRIMARY KEY,
    module       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    requested_by TEXT,
    task_id      INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    passed       INTEGER,
    failed       INTEGER,
    summary      TEXT
);

CREATE INDEX IF NOT EXISTS idx_ui_qa_queue_pending
    ON ui_qa_queue (id) WHERE status IN ('queued', 'running');
