-- 135: Link remote_nodes to user accounts for Starship Command
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_remote_nodes_user_id ON remote_nodes(user_id);
