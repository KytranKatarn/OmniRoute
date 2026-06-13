-- 433_shift_state_history.sql — audit log of agent shift-state transitions + formalize
-- the fleet hardware-rest window. Foundation for the K.I.N. Shift-Calendar subtab
-- (reactive state-timeline: agents are wake-on-demand, so "on shift" = active/deployed
-- state minus rest cycles minus the hardware-rest window). Idempotent.
--
-- Apply:  docker exec -i archie_database psql -U archie -d archie < 433_shift_state_history.sql

CREATE TABLE IF NOT EXISTS shift_state_history (
    id         SERIAL PRIMARY KEY,
    agent_id   INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    from_state TEXT,
    to_state   TEXT NOT NULL,
    reason     TEXT,
    changed_by TEXT,
    changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssh_agent_time ON shift_state_history (agent_id, changed_at DESC);

-- Formalize the fleet hardware-rest window (advisory; the calendar overlays it as the
-- only true "schedule"). 8PM–6AM ET. Not dispatcher-enforced (owner decision 2026-06-13).
INSERT INTO system_config (key, value, description)
VALUES ('welfare:hardware_rest_window',
        '{"start_hour":20,"end_hour":6,"tz":"America/Toronto","enabled":true}',
        'Fleet-global hardware rest window (advisory) for the K.I.N. shift calendar.')
ON CONFLICT (key) DO NOTHING;
