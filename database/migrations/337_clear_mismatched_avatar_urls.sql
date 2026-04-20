-- Migration 337: Clear avatar_url for 8 agents whose URL points at orphan files
-- belonging to decommissioned/renamed agents (PR #220 backfill mismatches).
--
-- Root cause: PR #220 backfilled avatar_url by best-effort filename matching from
-- the legacy roster. Several new agents (the 6 News & Media AI agents introduced
-- in 2026-04-14, plus M.A.R.K.E.T. and E.M.B.E.R.) inherited filenames from
-- now-decommissioned legacy agents — producing the "review image doesn't match
-- profile image" symptom (Roster card shows another agent's portrait).
--
-- Fix: NULL the bad references so these agents render as "missing" in the
-- Portrait Gallery, then bulk-regenerate via SDXL through P.I.X.E.L.
--
-- Idempotent: re-running is a no-op (UPDATE matches by both id AND avatar_url).

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 23  AND avatar_url = '/static/media/portraits/iris.png';     -- I.N.K.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 32  AND avatar_url = '/static/media/portraits/rune.png';     -- M.A.R.K.E.T.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 48  AND avatar_url = '/static/media/portraits/scribe.png';   -- F.A.C.T.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 49  AND avatar_url = '/static/media/portraits/razor.png';    -- B.I.A.S.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 58  AND avatar_url = '/static/media/portraits/counsel.png';  -- P.U.B.L.I.S.H.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 79  AND avatar_url = '/static/media/portraits/closer.png';   -- D.R.A.F.T.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 116 AND avatar_url = '/static/media/portraits/resolver.png'; -- V.E.R.I.F.Y.

UPDATE agents SET avatar_url = NULL, updated_at = NOW()
WHERE id = 126 AND avatar_url = '/static/media/portraits/index.png';    -- E.M.B.E.R.
