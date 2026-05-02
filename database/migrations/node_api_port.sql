-- Add node_api_port to remote_nodes (default 3001 — matches node_api.py app.run port)
ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS node_api_port INTEGER NOT NULL DEFAULT 3001;

-- Reset node_skill_pushes failures so the job retries all 9 skills
-- after the port fix is deployed.
UPDATE node_skill_pushes
SET    fail_count = 0,
       last_error = NULL
WHERE  node_id = (SELECT id FROM remote_nodes WHERE node_id = 'outpost_us_001')
  AND  fail_count > 0;
