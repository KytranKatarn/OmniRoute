-- Correct the cost class of the two OmniRoute rows that are not free (DS9 PR 10)
--
-- WHY
-- ---
-- Five contractor rows point at the same OmniRoute gateway (`http://omniroute:20128/v1`) with
-- different `auto/*` routing aliases. A verification pass on 2026-10-06 established:
--
--   * the gateway is UP — GET /v1/models returns HTTP 200 and 540 models
--   * every alias these rows configure EXISTS: auto/best-free, auto/coding, auto/coding:free,
--     auto/reasoning
--   * `auto/*` are DYNAMIC routers, so a failure is a statement about the upstream model the
--     alias happened to select, not about the row's configuration
--
-- So nothing here is stale config and nothing should be retired. Retiring a row whose alias is
-- valid, because the model behind it is unavailable this afternoon, is the same category error as
--     deleting a provider because it is not working right now.
--
-- Per-row reality:
--
--   omniroute_coding        auto/coding       -> 402 "This model requires an opencode API key"
--   omniroute_coding_free   auto/coding:free  -> 402 "This model requires an opencode API key"
--   omniroute_best_free     auto/best-free    -> 400 "Model is unavailable"  (upstream withdrawn)
--   omniroute_reasoning     auto/reasoning    -> 400 "Model is unavailable"  (upstream withdrawn)
--   omniroute               (client-restricted) -> 403 free tier only usable inside OpenCode
--
-- Only the first two change. Both were labelled `free_tier` while their own gateway response says
-- a paid OpenCode key is required — a row named "free" that answers 402 for payment, on the tab
-- operators use to judge cost. `omniroute_coding_free` is the sharpest: the alias literally says
-- `:free`.
--
-- WHY THIS IS A MIGRATION AND NOT A PROBE
-- --------------------------------------
-- `classify_provider_class` never assigns `paid`, on purpose. Its docstring records that it used
-- to end in `return "paid" if is_cloud_proxy else "free_tier"`, which asserted cost from a flag
-- that says how a provider is REACHED rather than what it COSTS. A probe can observe a 402 but
-- cannot prove the price behind it, so `paid` is operator-assigned. This file is that assignment,
-- recorded so it survives a fresh database and so the evidence travels with the change.
--
-- The three untouched rows keep `free_tier` deliberately:
--   * `omniroute` is genuinely free — it is client-restricted, which is a different failure
--   * `best_free` and `reasoning` fail on upstream availability, not on cost; `free_tier` is an
--     unproven claim rather than a known-false one, and the rows may resolve again at any time.
--
-- GUARD
-- -----
-- Only `free_tier` is rewritten. If someone has already corrected a row by hand, this leaves it
-- alone rather than stomping their judgement, and a re-application is a no-op.

DO $$
DECLARE
    targets text[] := ARRAY['omniroute_coding', 'omniroute_coding_free'];
    updated int;
BEGIN
    UPDATE contractor_providers
       SET provider_class = 'paid'
     WHERE provider_key = ANY(targets)
       AND provider_class = 'free_tier';

    GET DIAGNOSTICS updated = ROW_COUNT;

    IF updated > 0 THEN
        RAISE NOTICE 'reclassified % OmniRoute row(s) free_tier -> paid (gateway answers 402: a paid OpenCode key is required)', updated;
    ELSE
        RAISE NOTICE 'no rows needed reclassifying — already correct, or corrected by hand';
    END IF;
END $$;

COMMENT ON COLUMN contractor_providers.provider_class IS
    'Cost class. local | keyless | free_tier | paid | image_only. Assigned by an operator, never '
    'inferred by the health probe: classify_provider_class deliberately cannot return paid, '
    'because a probe can observe a 402 but cannot prove the price behind it. NULL means '
    'unmeasured, and the dispatchable toggle refuses to enable an unmeasured provider (HTTP 409) '
    'precisely because an unknown cost is not a licence to spend.';
