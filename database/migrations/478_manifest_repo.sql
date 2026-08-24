-- A manifest entry is a (repo, PR) pair. Without this, _pr_on_open_window
-- matches on PR number alone and a window for one repo authorises another.
-- No backfill: maintenance_window_items has 0 rows (measured 2026-08-23), so
-- there is no legacy ref format to preserve. NULL stays meaningful — it means
-- "names no repo", and the matcher refuses it rather than assuming a default.
ALTER TABLE maintenance_window_items
    ADD COLUMN IF NOT EXISTS repo VARCHAR(200);

COMMENT ON COLUMN maintenance_window_items.repo IS
    'owner/name of the repo this manifest entry authorises. NULL authorises nothing.';

CREATE INDEX IF NOT EXISTS idx_mwi_window_repo_ref
    ON maintenance_window_items (window_id, repo, ref);
