-- 088_schema_migrations.sql — a ledger of which WTF migrations have been applied.
--
-- WHY: until now nothing recorded this. Migrations 001-087 were applied by piping a
-- file into psql on Citadel by hand, so the only way to answer "is 084 actually on the
-- box?" was to read the DB and look for the table/column the file creates. That is
-- guesswork dressed as bookkeeping, and it is the reason the wrong-target incident of
-- 2026-10-02 (085-087 applied to the hub) was caught by luck rather than by a check.
--
-- WHAT THIS DOES NOT DO: it does not backfill 001-087. A backfill would be a claim
-- that 87 migrations were applied, written by someone who cannot verify 87 of them.
-- Instead the '000-baseline' row below records that the pre-088 era happened and is
-- UNKNOWN, with applied_at deliberately NULL. Every migration from 088 onward logs
-- itself in the same transaction as its DDL, so "recorded" and "applied" cannot drift.
--
-- WRONG-TARGET SAFETY: the hub's archie database ALSO has a public.schema_migrations
-- (the platform's own ledger, varchar version + description + applied_at, no filename
-- column). Here CREATE TABLE IF NOT EXISTS is a no-op against that table and the
-- INSERT below then fails on the unknown 'filename' column. Under the documented
-- ON_ERROR_STOP=1 pipe that aborts the file before writing anything — so misapplying
-- this migration to the hub errors out instead of quietly filing WTF history into the
-- platform's ledger. That failure is the point; do not "fix" it by dropping filename.

CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version     varchar(50) PRIMARY KEY,
    filename    text        NOT NULL,
    description text,
    -- NULL means "applied at an unknown time": the honest encoding for the pre-088
    -- era, and the reason this column is nullable rather than NOT NULL DEFAULT now().
    applied_at  timestamptz DEFAULT now()
);

COMMENT ON TABLE public.schema_migrations IS
    'WTF migration ledger. WTF runs on Citadel''s wtf database, NOT the hub''s archie '
    'database, which has a same-named table belonging to the platform.';

-- The baseline marker. Sorts first, is obviously not a real migration, and exists so
-- that a reader of the table alone learns that 001-087 are unledgered rather than
-- absent. 'applied_at' stays NULL: nobody knows when those were applied.
INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('000-baseline',
        '001_wtf_schema.sql .. 087_election_calendar_derived.sql',
        'Applied before this ledger existed (no timestamps recorded). Spot-checked '
        'against Citadel on 2026-10-03: 085-087 confirmed live. The rest are NOT '
        'individually verified — treat as unknown, not as a record of 87 applications.',
        NULL)
ON CONFLICT (version) DO NOTHING;

-- Log this migration. ON CONFLICT DO NOTHING keeps the file re-runnable, which is the
-- property migrations/README.md documents and which 085-087 were verified against.
INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('088',
        '088_schema_migrations.sql',
        'Record which WTF migrations have been applied',
        now())
ON CONFLICT (version) DO NOTHING;
