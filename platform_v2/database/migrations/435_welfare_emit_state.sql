-- 435_welfare_emit_state.sql
-- Project #379 Phase 3 — HUB→STANDALONE welfare emitter de-dupe state.
--
-- The welfare emitter (services/welfare_emit.py) pushes one C.R.E.E.D.
-- `category='welfare'` event per agent×dimension on an intraday cadence. Left
-- unguarded that is 54 agents × 4 dimensions × hourly = thousands of duplicate
-- public events/day. This table records the LAST emitted severity + timestamp
-- per (agent_id, dimension) so the emitter only fires when an agent/dimension's
-- welfare STATE CHANGES (info→warning, warning→critical, …) or when the last
-- emit aged past a heartbeat interval (so a steadily-over agent still produces a
-- periodic signal for the 30-day rolling welfare score, but not every cycle).
--
-- `dimension` also carries the two break-honor pseudo-dimensions
-- ('break_honored' / 'break_violated') so the same de-dupe applies to the
-- break-honor signal.

CREATE TABLE IF NOT EXISTS agent_welfare_emit_state (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    dimension       VARCHAR(32) NOT NULL,   -- hours|tokens|actions|stress|break_honored|break_violated
    last_severity   VARCHAR(20) NOT NULL,   -- info|warning|violation|critical
    last_event_type VARCHAR(64),            -- welfare_<dim> | welfare_break_honored | welfare_break_violated
    last_emit_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_welfare_emit_agent_dim UNIQUE (agent_id, dimension)
);

CREATE INDEX IF NOT EXISTS idx_welfare_emit_agent ON agent_welfare_emit_state(agent_id);
CREATE INDEX IF NOT EXISTS idx_welfare_emit_emit_at ON agent_welfare_emit_state(last_emit_at);
