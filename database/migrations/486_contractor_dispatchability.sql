-- Contractor dispatchability (DS9) — separate "configured" from "may be dispatched".
--
-- WHY THIS EXISTS
-- ---------------
-- `contractor_providers.is_active` currently means two different things at once: that a
-- provider is CONFIGURED (key present, endpoint reachable) and that the platform may
-- ROUTE WORK TO IT. Those must be separable, because the standing rule is that a paid
-- provider is never auto-dispatched unless deliberately enabled — and "deliberately
-- enabled" cannot be expressed while a single boolean conflates the two.
--
-- So this adds:
--   dispatchable   may the dispatcher send work here?
--   provider_class what kind of thing is it? (governs routing eligibility)
--
-- THE DEFAULT IS THE POINT
-- -----------------------
-- `dispatchable` defaults FALSE for every pre-existing row. All 30 contractors come out of
-- this migration NOT dispatchable, so merging it cannot cause a paid provider to receive
-- traffic as a side effect. Enabling one is a separate, deliberate act — the Contracts tab
-- switch. `is_active` keeps its existing meaning, so a provider can be fully configured and
-- passing its health probe while still receiving nothing.
--
-- provider_class vocabulary, and why it is a CHECK rather than free text
-- ---------------------------------------------------------------------
--   local       mesh Ollama, owned by the bridge. NOT listed as a contractor: the bridge
--               already dispatches these (~8,100 tasks/24h across 5+ nodes). Adding them
--               here would duplicate a working system.
--   keyless     no API key required. Convenient, and frequently capability-limited —
--               pollinations is keyless and IMAGE-ONLY, which is why it cannot serve a
--               roster agent.
--   free_tier   no paid key, but the upstream imposes real limits. OmniRoute's
--               auto/coding:free currently fails because opencode-zen restricts its free
--               tier to its own client ("can only be used from within OpenCode"); the
--               unmarked auto/* ids resolve to a -free upstream and DO work. Class is
--               assigned by measurement, never by the ":free" in a model name.
--   paid        requires a paid key. Auto-dispatch refused unless `dispatchable`.
--   image_only  serves /v1/images/generations, not chat. Excluded from text dispatch.
--
-- NULL means "not yet measured". Deliberate: a probe (PR 2) assigns the real class, and
-- until then the tab shows it as unknown rather than guessing. Guessing wrong here would
-- put a paid provider into the free tier, or a keyless image provider into the roster.
--
-- Idempotent: every statement is IF NOT EXISTS / DO NOTHING, and the backfill is keyed on
-- provider_key so re-running converges rather than fighting.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Columns
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE contractor_providers
    ADD COLUMN IF NOT EXISTS dispatchable BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE contractor_providers
    ADD COLUMN IF NOT EXISTS provider_class VARCHAR(16) DEFAULT NULL;

-- The vocabulary is closed. A typo must not silently invent a class that no selector
-- handles — that is the failure mode where a provider is in a bucket nobody filters on,
-- so it is either unreachable or, worse, wrongly eligible.
ALTER TABLE contractor_providers
    DROP CONSTRAINT IF EXISTS contractor_providers_provider_class_chk;

ALTER TABLE contractor_providers
    ADD CONSTRAINT contractor_providers_provider_class_chk
    CHECK (provider_class IS NULL
           OR provider_class IN ('local','keyless','free_tier','paid','image_only'));

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Backfill what was MEASURED on 2026-10-05, not what the names imply
-- ─────────────────────────────────────────────────────────────────────────────
--
-- Only four facts were established by real requests, and they are the only ones written
-- here. Everything else stays NULL until the probe measures it.
--
-- pollinations: keyless, and its /v1/chat/completions is refused as an image-generation
--   model — the gateway answers "use POST /v1/images/generations instead".
--
-- groq / cerebras / cohere / mistral / gemini / xai: all six hold a key in
--   external_api_keys (8 of 8 rows carry a monthly_budget_usd) and serve text. They are
--   `paid`, so they stay non-dispatchable until enabled.
--
-- The three OmniRoute rows: measured, not assumed. omniroute_coding_free and
-- omniroute_best_free both returned 502 "All models failed"; omniroute_coding,
-- omniroute_coding:fast and omniroute_reasoning returned 200 and resolved to
-- opencode-zen/space-bunny-free. So the ids literally marked ":free" are the ones that
-- fail, and the unmarked ones are free. Class follows the measurement.
UPDATE contractor_providers SET provider_class = 'image_only' WHERE provider_key = 'pollinations';

UPDATE contractor_providers SET provider_class = 'paid'
 WHERE provider_key IN ('groq','cerebras','cohere','mistral','gemini','xai');

UPDATE contractor_providers SET provider_class = 'free_tier'
 WHERE provider_key IN ('omniroute','omniroute_coding_free','omniroute_best_free',
                        'omniroute_coding','omniroute_reasoning');

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Index for the selector's hot path
-- ─────────────────────────────────────────────────────────────────────────────
-- Every routing decision filters on active AND dispatchable. Without this the
-- selector scans all 30 rows and evaluates a boolean per row on the hot path.
CREATE INDEX IF NOT EXISTS idx_contractor_providers_dispatchable
    ON contractor_providers (is_active, dispatchable, provider_class);

COMMIT;
