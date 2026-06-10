-- 427: allow 'sent_to_signal' on creed_marketing_assets.gen_status (#3944)
-- The CREED Command Marketing tab can hand a finished LinkedIn asset to
-- S.I.G.N.A.L.'s approval queue; the asset is marked 'sent_to_signal'.
-- Idempotent: drop+recreate the check with the extended value set.

ALTER TABLE creed_marketing_assets
    DROP CONSTRAINT IF EXISTS creed_marketing_assets_gen_status_check;

ALTER TABLE creed_marketing_assets
    ADD CONSTRAINT creed_marketing_assets_gen_status_check
    CHECK (gen_status = ANY (ARRAY['pending'::text, 'done'::text, 'error'::text, 'sent_to_signal'::text]));
