-- Migration 394: Add owner_group columns to wtf.sources
-- The sources table already has owner_name and owner_type (added previously).
-- This migration is idempotent — safe to re-run.
-- It also backfills owner_type for sources whose owner_name is set but owner_type is NULL,
-- and adds the owner_group column as an alias key for grouping (VARCHAR 100).

-- Step 1: Ensure columns exist (idempotent)
ALTER TABLE wtf.sources ADD COLUMN IF NOT EXISTS owner_name  VARCHAR(200);
ALTER TABLE wtf.sources ADD COLUMN IF NOT EXISTS owner_type  VARCHAR(50);
ALTER TABLE wtf.sources ADD COLUMN IF NOT EXISTS owner_group VARCHAR(100);

-- Step 2: Copy owner_name → owner_group where owner_group is null
UPDATE wtf.sources
SET owner_group = owner_name
WHERE owner_name IS NOT NULL
  AND owner_group IS NULL;

-- Step 3: Backfill owner_type for known corporate groups (idempotent)
UPDATE wtf.sources SET owner_type = 'corporate'
WHERE owner_name IN (
    'Bell Media', 'Rogers Media', 'Postmedia', 'Torstar',
    'Quebecor', 'Corus Entertainment', 'Village Media',
    'Brunswick News', 'Glacier Media', 'Black Press', 'Saltwire'
)
AND (owner_type IS NULL OR owner_type = '');

UPDATE wtf.sources SET owner_type = 'public'
WHERE owner_name IN (
    'CBC/Radio-Canada', 'CBC', 'Radio-Canada',
    'TVO', 'CPAC'
)
AND (owner_type IS NULL OR owner_type = '');

UPDATE wtf.sources SET owner_type = 'non_profit'
WHERE owner_name IN (
    'Unifor Media', 'National Observer', 'The Tyee',
    'Broadbent Institute', 'PressProgress', 'CanadaLand',
    'Aboriginal Multi-Media Society', 'APTN (Indigenous-owned)'
)
AND (owner_type IS NULL OR owner_type = '');

-- Step 4: Index for fast grouping queries on the CRTC ownership panel
CREATE INDEX IF NOT EXISTS idx_sources_owner_group ON wtf.sources (owner_group);
CREATE INDEX IF NOT EXISTS idx_sources_owner_name  ON wtf.sources (owner_name);
