-- 089_echo_phrase_counts.sql — precomputed phrase/word counts for /echo.
--
-- WHY: /echo counted 8 slogans + 6 words with full-text phrase queries over every
-- article body, on every request. Measured on Citadel 2026-10-05: ~42 s per render
-- (phrases built from common words such as "Made in Canada" cost 5-7 s EACH: a GIN
-- tsvector index stores no word positions, so every candidate's body is re-parsed to
-- check adjacency). One worker is held that long, with no rate limit on the route.
-- A single pass over the window was NOT faster (30 s), so the fix is to compute once
-- and read, not to rewrite the query.
--
-- ingest/echo/phrase_counts.py fills this table daily; /echo reads it in milliseconds.
--
-- One row per (kind, phrase, bucket). ZEROS ARE STORED EXPLICITLY: "computed, and no
-- article matched" must be distinguishable from "never computed", or an unfilled
-- table would render as a page of confident zeros. The reader (echo_data.counts_status)
-- treats any gap in the window as "not ready" rather than inventing a count.
--
--   kind='slogan' -> bucket_start is a Monday (ISO week), window 13 weeks
--   kind='word'   -> bucket_start is a calendar day,      window 30 days
--   phrase        -> the phrase exactly as passed to phraseto_tsquery (shared/echo_phrases.py)
--
-- Re-runnable: IF NOT EXISTS + ON CONFLICT DO NOTHING, like 085-088.

CREATE TABLE IF NOT EXISTS wtf.echo_phrase_counts (
    kind         text        NOT NULL CHECK (kind IN ('slogan', 'word')),
    phrase       text        NOT NULL,
    bucket_start date        NOT NULL,
    n            integer     NOT NULL CHECK (n >= 0),
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, phrase, bucket_start)
);

-- Apps do not connect as the owner. Conditional so the file still applies where the role does not exist.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON wtf.echo_phrase_counts TO wtfuser;
    END IF;
END $$;

-- Log this migration in the same transaction as its DDL (see migrations/README.md).
INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('089',
        '089_echo_phrase_counts.sql',
        'Precomputed /echo phrase and word counts (replaces ~42 s of per-request FTS)',
        now())
ON CONFLICT (version) DO NOTHING;
