-- 431: per-session egress preference for the S.C.O.U.T. auth fabric (#4007).
-- A cookie session can declare which country/outpost its authenticated fetches
-- egress through. NULL / 'hub' / 'auto' = hub direct (Canada); any other value
-- is a remote_nodes.node_name. Resolution is preference-not-pin: an offline or
-- non-egress-ready node falls back to the hub at fetch time.
-- Idempotent.

ALTER TABLE browser_sessions
    ADD COLUMN IF NOT EXISTS egress_pref VARCHAR(40);

COMMENT ON COLUMN browser_sessions.egress_pref IS
    'S.C.O.U.T. egress preference (#4007): NULL/hub/auto = hub direct; else a remote_nodes.node_name. Preference-not-pin — offline/unready node falls back to hub.';
