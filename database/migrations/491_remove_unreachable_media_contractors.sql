-- Remove the 7 media contractors the platform cannot call (DS9 PR 9)
--
-- WHY
-- ---
-- `contractor_providers` advertises nine media-only contractors. `generate_media` has adapters
-- for exactly one of them (pollinations). The other eight:
--
--   comfyui             reachable only via /api/bridge/comfyui/*, a different mechanism that
--                       does not consult contractor_providers at all. KEEP.
--   elevenlabs          no adapter, no reference anywhere in the codebase
--   fal_ai              no adapter, no reference anywhere
--   ollama_diffuser     no adapter; and the Ollama endpoint serves 40 models, none of them
--                       diffusion. It cannot produce an image today.
--   replicate           no adapter, no reference anywhere
--   replicate_audio     no adapter, no reference anywhere
--   stability_ai        no adapter, no reference anywhere
--   stability_audio     no adapter, no reference anywhere
--
-- A row an operator can see but no code path can call is a promise the platform cannot keep. The
-- Contractors tab is the operator's source of truth for what is available, and it was overstating
-- capability by 7 of 9.
--
-- Removing them also removes an accidental hazard: `replicate_audio` and `stability_audio` both
-- claimed `image_gen` alongside their audio capabilities — copy-paste in the seed data. Capability
-- lists feed the media sovereignty gate's allowlist, so those two were nominally cleared to
-- generate images they cannot generate.
--
-- NOT DELETED, DELIBERATELY
-- --------------------------
-- `comfyui` and `pollinations` stay. ComfyUI's own service is currently offline (:8188 refused),
-- but that is an availability fact, not a roster error — the bridge routes exist and return a
-- clear 503 while it is down. Deleting it would conflate "not running" with "not implemented".
--
-- GUARD
-- -----
-- The DO block refuses to run if any target has since acquired an API key or recorded real usage.
-- If someone wires an adapter and configures a provider BEFORE this migration is applied, the
-- deletion must not silently undo that work. It re-checks at apply time rather than trusting the
-- state at authoring time.
--
-- `contractor_health` rows for these providers are removed too (139 of them). They are
-- observations of providers that no longer exist, and with no FK on provider_key they would
-- otherwise linger as orphans describing a roster that is gone. The table prunes at 30 days in any
-- case, so nothing durable is lost.

DO $$
DECLARE
    targets text[] := ARRAY[
        'elevenlabs', 'fal_ai', 'ollama_diffuser', 'replicate',
        'replicate_audio', 'stability_ai', 'stability_audio'
    ];
    keyed   text[];
    used    text[];
BEGIN
    -- Refuse rather than delete if a target has become real since this was written.
    SELECT array_agg(provider) INTO keyed
      FROM external_api_keys
     WHERE provider = ANY(targets)
       AND api_key_encrypted IS NOT NULL
       AND api_key_encrypted <> '';

    IF keyed IS NOT NULL THEN
        RAISE EXCEPTION
            'aborting: media contractor removal — these now hold API keys: %. Delete them deliberately instead.',
            keyed;
    END IF;

    SELECT array_agg(DISTINCT provider) INTO used
      FROM cloud_model_usage
     WHERE provider = ANY(targets);

    IF used IS NOT NULL THEN
        RAISE EXCEPTION
            'aborting: media contractor removal — these have recorded real usage: %. Something is calling them.',
            used;
    END IF;

    DELETE FROM contractor_health   WHERE provider_key = ANY(targets);
    DELETE FROM contractor_providers WHERE provider_key = ANY(targets);

    RAISE NOTICE 'removed % media-only contractors with no dispatch path', array_length(targets, 1);
END $$;

COMMENT ON TABLE contractor_providers IS
    'Configured providers. Every row here must correspond to a code path that can actually call '
    'it: the selector for text, an adapter in generate_media for media, or a bridge route. Rows '
    'are policy, not a wish list — the dispatchable toggle refuses to enable a provider whose '
    'provider_class is NULL, so a row here is a promise the platform is expected to keep.';
