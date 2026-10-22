-- Per-agent portrait history (Media Studio review 2026-10-21, task #7429).
-- Every approve (and every revert) records what the agent's canonical portrait + avatar WERE, so a wrong approval
-- can be undone in one click. Before this, recovering the 7 portraits replaced on 2026-10-21 needed git history of
-- the generated website data. Idempotent. ON DELETE CASCADE: history is meaningless without the agent.
CREATE TABLE IF NOT EXISTS agent_portrait_history (
    id                          SERIAL PRIMARY KEY,
    agent_id                    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    action                      VARCHAR(20) NOT NULL DEFAULT 'approve',   -- approve | revert
    prev_canonical_image_path   TEXT,
    prev_avatar_url             TEXT,
    prev_media_id               INTEGER,
    new_canonical_image_path    TEXT,
    new_media_id                INTEGER,
    actor                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_portrait_history_agent
    ON agent_portrait_history (agent_id, created_at DESC, id DESC);
