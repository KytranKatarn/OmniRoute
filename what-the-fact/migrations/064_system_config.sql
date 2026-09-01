-- 064_system_config.sql
-- The weekly digest worker (ingest/weekly_digest_worker.py) reads/writes an
-- unqualified `system_config` for its once-per-week dedup stamp
-- (`wtf_weekly_digest_last_sent`). That table never existed in the wtf
-- database — it exists only in the platform `archie` DB — so every Monday
-- cycle raised inside _already_sent_this_week() before a single mail was
-- built, and run.py swallowed it as "weekly_digest crashed" in container
-- logs that are wiped on each rebuild. The digest has never sent.
--
-- Unqualified name resolves to public via the default search_path, so the
-- table is created in public, matching the worker as written.

CREATE TABLE IF NOT EXISTS public.system_config (
    config_key   TEXT PRIMARY KEY,
    config_value TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Apps connect as wtfuser, never the owner (migration 047 lesson).
GRANT SELECT, INSERT, UPDATE ON public.system_config TO wtfuser;

-- Deliberately NO seed row: an absent stamp reads as "never sent", which is
-- true, and lets the next Monday cycle send without manual intervention.
