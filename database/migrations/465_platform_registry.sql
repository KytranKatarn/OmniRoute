-- 465_platform_registry.sql — Living Platform Registry, Phase 1 (task #5230)
--
-- WHY THIS TABLE EXISTS
-- .claude/rules/module-capability-index.md is 314 hand-typed lines that a new
-- session reads FIRST and then acts on. A hand-maintained index does not merely
-- age — it ASSERTS FALSE THINGS:
--   * `backups` and `backup_locks` documented as tables; neither exists. The
--     integrity check queried `FROM backups`, threw every run, swallowed it, and
--     left backups UNMONITORED WHILE APPEARING MONITORED.
--   * media_studio / game_studio / media_hub listed as Codex-writable when they
--     never were — a real widening of an automated agent's write access.
--   * auth_events documented as existing when it does not (#5174).
-- Each of those was believed because it was written down.
--
-- PRINCIPLE: anything an agent reads to make a decision must be DERIVED from a
-- live source, or must DECLARE its own staleness. This table is the derived
-- half; `notes` is the human half that survives regeneration.

CREATE TABLE IF NOT EXISTS platform_registry_module (
    module_id            TEXT PRIMARY KEY,

    -- ---- collected from module_registry.py / rbac.py (authoritative, overwritten every run)
    name                 TEXT        NOT NULL,
    description          TEXT,
    category             TEXT        NOT NULL,
    route                TEXT,
    blueprint_import     TEXT,
    external_url         TEXT,
    required_permissions JSONB       NOT NULL DEFAULT '[]'::jsonb,
    minimum_role         TEXT,
    minimum_tier         TEXT,
    enabled              BOOLEAN     NOT NULL DEFAULT TRUE,
    beta                 BOOLEAN     NOT NULL DEFAULT FALSE,
    coming_soon          BOOLEAN     NOT NULL DEFAULT FALSE,
    version              TEXT,
    tags                 JSONB       NOT NULL DEFAULT '[]'::jsonb,
    show_on_dashboard    BOOLEAN,

    -- ---- human-owned. NEVER written by the collector.
    -- The hand-written rationale in the index ("SABnzbd set_config is
    -- unreliable — edit sabnzbd.ini directly") is the genuinely valuable part
    -- and cannot be derived. It lives here so regeneration cannot destroy it —
    -- otherwise the first regen silently deletes years of hard-won gotchas and
    -- everyone goes back to hand-editing the markdown.
    notes                TEXT,

    -- ---- lifecycle. A DISAPPEARANCE IS THE MOST INTERESTING EVENT, so it is
    -- recorded, never deleted. reconcile() flips status to 'absent' and freezes
    -- last_seen_at; the row and its notes stay. Deleting would erase exactly the
    -- evidence that something vanished — the phantom-table failure in reverse.
    status               TEXT        NOT NULL DEFAULT 'present'
                                     CHECK (status IN ('present', 'absent')),
    first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prm_category ON platform_registry_module (category);
CREATE INDEX IF NOT EXISTS idx_prm_status   ON platform_registry_module (status);

COMMENT ON TABLE  platform_registry_module IS
    'Derived registry of platform modules (task #5230). Collected from module_registry.py; '
    'the generated capability index renders FROM this table. Rows are never deleted — a '
    'vanished module becomes status=absent so the disappearance is visible.';
COMMENT ON COLUMN platform_registry_module.notes IS
    'Human-owned rationale/gotchas. The collector MUST NOT overwrite this column.';
COMMENT ON COLUMN platform_registry_module.status IS
    'present | absent. absent = collected before, not seen in the latest run. Never deleted.';
