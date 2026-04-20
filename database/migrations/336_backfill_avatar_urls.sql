-- Migration 336: backfill avatar_url for 18 active agents (Project #262 Phase 3a)
--
-- Context: the Roster + Org Chart audit (PR #219) surfaced that 26 active
-- agents had avatar_url = NULL even though matching portrait files already
-- exist on disk in platform_v2/static/media/portraits/. This migration
-- links the 18 clean matches. The remaining 8 need actual generation
-- (Phase 3b): P.I.X.E.L. + R.O.S.E.T.T.A. (AI-style regen — existing files
-- are the old human faces), 4 new humans (Lucia, Maya, Lillian, Josée),
-- plus W.A.T.C.H. and E.T.H.O.S. (AI directors with no existing file).
--
-- Filename convention: lowercase(name with dots stripped).png.

BEGIN;

UPDATE agents SET avatar_url = '/static/media/portraits/scroll.png',   updated_at = now() WHERE id = 332;
UPDATE agents SET avatar_url = '/static/media/portraits/forge.png',    updated_at = now() WHERE id = 136;
UPDATE agents SET avatar_url = '/static/media/portraits/signal.png',   updated_at = now() WHERE id = 141;
UPDATE agents SET avatar_url = '/static/media/portraits/darwin.png',   updated_at = now() WHERE id = 140;
UPDATE agents SET avatar_url = '/static/media/portraits/gavel.png',    updated_at = now() WHERE id = 147;
UPDATE agents SET avatar_url = '/static/media/portraits/muse.png',     updated_at = now() WHERE id = 138;
UPDATE agents SET avatar_url = '/static/media/portraits/resolve.png',  updated_at = now() WHERE id = 142;
UPDATE agents SET avatar_url = '/static/media/portraits/spectra.png',  updated_at = now() WHERE id = 137;
UPDATE agents SET avatar_url = '/static/media/portraits/accord.png',   updated_at = now() WHERE id = 149;
UPDATE agents SET avatar_url = '/static/media/portraits/kin.png',      updated_at = now() WHERE id = 145;
UPDATE agents SET avatar_url = '/static/media/portraits/base.png',     updated_at = now() WHERE id = 139;
UPDATE agents SET avatar_url = '/static/media/portraits/shield.png',   updated_at = now() WHERE id = 150;
UPDATE agents SET avatar_url = '/static/media/portraits/armada.png',   updated_at = now() WHERE id = 337;
UPDATE agents SET avatar_url = '/static/media/portraits/codex.png',    updated_at = now() WHERE id = 146;
UPDATE agents SET avatar_url = '/static/media/portraits/vital.png',    updated_at = now() WHERE id = 148;
UPDATE agents SET avatar_url = '/static/media/portraits/heritage.png', updated_at = now() WHERE id = 331;
UPDATE agents SET avatar_url = '/static/media/portraits/ledger.png',   updated_at = now() WHERE id = 144;
UPDATE agents SET avatar_url = '/static/media/portraits/cargo.png',    updated_at = now() WHERE id = 143;

-- Assertion: 18 rows now have avatar_url set among the targeted IDs
DO $$
DECLARE cnt int;
BEGIN
    SELECT COUNT(*) INTO cnt FROM agents
     WHERE id IN (332,136,141,140,147,138,142,137,149,145,139,150,337,146,148,331,144,143)
       AND avatar_url IS NOT NULL;
    ASSERT cnt = 18, format('Expected 18 avatar_url backfills, got %s', cnt);
END $$;

COMMIT;
