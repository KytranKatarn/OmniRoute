-- Add web_ui_ports JSONB column to docker_stacks
-- Stores array of web UI port definitions per stack
-- Example: [{"port": 3000, "label": "Platform", "path": "/"}]

ALTER TABLE docker_stacks ADD COLUMN IF NOT EXISTS web_ui_ports JSONB DEFAULT '[]'::jsonb;
COMMENT ON COLUMN docker_stacks.web_ui_ports IS 'JSON array of web UI ports, e.g. [{"port":3000,"label":"Platform","path":"/"}]';

-- Seed A.R.C.H.I.E. system stack web UI ports
UPDATE docker_stacks SET web_ui_ports = '[{"port": 3000, "label": "Platform", "path": "/"}]'::jsonb WHERE name = 'archie';
