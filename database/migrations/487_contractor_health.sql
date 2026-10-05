-- Contractor health observations (DS9 PR 3) — what each contractor actually does.
--
-- WHY
-- ---
-- `contractor_providers.tier_position` is a hand-typed integer. It expresses a WISH about
-- which provider should be preferred, and it never changes when reality differs. Nothing
-- in the table records whether a contractor can serve at all, how fast it answers, or what
-- model it really returned — which is why `pollinations` was listed as a text provider when
-- its /v1/chat/completions is refused as an image-generation model.
--
-- This records observation, not opinion. It never dispatches, never reorders, and never
-- mutates routing: it writes one row per probe and lets the ranking read the history.
--
-- WHY THREE CADENCES IN ONE TABLE
-- -------------------------------
-- Probing is not free and the upstreams are rate-limited. `opencode-zen` already refuses
-- third-party gateways ("can only be used from within OpenCode"), so hammering it is how a
-- free tier gets withdrawn. Three cheap tiers, distinguished by `probe_kind`, share one
-- table so a single history query can answer "is it up" and "how slow is it" without
-- joining two stores:
--
--   health   every 15 min — one cheap request per contractor (does it answer at all)
--   latency  hourly       — a real completion, to get a number worth ranking on
--   full     daily        — enumerates models, so `observed_model` can be corrected
--
-- A `health` row answers "up or not"; it carries latency_ms when it happens to have one,
-- which may be NULL. Nothing depends on that column being populated — ranking treats NULL
-- as "not sampled", never as "instant".
--
-- Idempotent via IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS contractor_health (
    id              BIGSERIAL PRIMARY KEY,
    provider_key    VARCHAR(50) NOT NULL,
    -- which of the three cadences produced this row
    probe_kind      VARCHAR(10) NOT NULL DEFAULT 'health',
    -- 'ok' | 'unreachable' | 'auth_error' | 'rate_limited' | 'no_key' | 'unsupported'
    --                | 'error'
    status          VARCHAR(16) NOT NULL,
    -- Wall-clock of the probe. NULL when the request never completed.
    latency_ms      INTEGER DEFAULT NULL,
    -- What the provider ACTUALLY served, which is frequently not default_model. NULL when
    -- the probe could not reach the point of learning it.
    observed_model  TEXT DEFAULT NULL,
    -- Why: the upstream's own words. This is the field that explained the opencode-zen
    -- client-scope refusal without anyone having to guess at it again.
    detail          TEXT DEFAULT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contractor_health_kind_chk
        CHECK (probe_kind IN ('health', 'latency', 'full')),
    CONSTRAINT contractor_health_status_chk
        CHECK (status IN ('ok','unreachable','auth_error','rate_limited','no_key',
                          'unsupported','error'))
);

-- The hot query is "latest observation per provider", so that is what the index serves.
-- provider_key alone would not: it would return every historical row for one provider.
CREATE INDEX IF NOT EXISTS idx_contractor_health_latest
    ON contractor_health (provider_key, created_at DESC);

-- The full sweep filters by kind, and retention deletes by age.
CREATE INDEX IF NOT EXISTS idx_contractor_health_kind_created
    ON contractor_health (probe_kind, created_at DESC);

-- Ranking reads the most recent SUCCESSFUL latency per provider. Partial, because the
-- overwhelming majority of rows are health probes whose latency_ms is NULL.
CREATE INDEX IF NOT EXISTS idx_contractor_health_latency
    ON contractor_health (provider_key, created_at DESC)
    WHERE latency_ms IS NOT NULL;

COMMIT;
