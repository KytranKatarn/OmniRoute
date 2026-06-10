-- 428: per-product C.R.E.E.D. tenant routing (#3958, spec KB #272124/#272125)
-- Each governance event routes to the tenant of the EMITTING AGENT.
-- Mapping is PER-AGENT and DATA-DRIVEN: agents.creed_tenant slug,
-- NULL = default 'kytran-empowerment' (core platform tenant).
-- Department traps (why per-agent, not per-department):
--   M.A.V.E.N. sits in News & Media but serves Media Hub  -> media-hub
--   G.A.V.E.L. sits in Legal & Regulatory but is platform -> NULL (default)
-- Idempotent: column add guarded, seeds only fill NULLs (manual edits win).

ALTER TABLE agents ADD COLUMN IF NOT EXISTS creed_tenant VARCHAR(64);

COMMENT ON COLUMN agents.creed_tenant IS
  'C.R.E.E.D. tenant slug for governance-event routing (#3958). NULL = kytran-empowerment default. Data-driven: assign as agents join products; no code change needed.';

-- what-the-fact (News & Media product agents)
UPDATE agents SET creed_tenant = 'what-the-fact'
 WHERE creed_tenant IS NULL
   AND name IN ('F.A.C.T.', 'B.I.A.S.', 'V.E.R.I.F.Y.', 'E.C.H.O.', 'I.N.K.',
                'D.R.A.F.T.', 'P.U.B.L.I.S.H.', 'A.U.R.O.R.A.', 'L.O.C.A.L.');

-- Watch products
UPDATE agents SET creed_tenant = 'gov-watch'    WHERE creed_tenant IS NULL AND name = 'P.R.O.C.U.R.E.';
UPDATE agents SET creed_tenant = 'civic-watch'  WHERE creed_tenant IS NULL AND name = 'W.A.T.C.H.';
UPDATE agents SET creed_tenant = 'market-watch' WHERE creed_tenant IS NULL AND name = 'M.A.R.K.E.T.';

-- Department-trap corrections + standalones
UPDATE agents SET creed_tenant = 'media-hub' WHERE creed_tenant IS NULL AND name = 'M.A.V.E.N.';
UPDATE agents SET creed_tenant = 'kso'       WHERE creed_tenant IS NULL AND name = 'B.A.S.E.';

-- CREED governance itself
UPDATE agents SET creed_tenant = 'creed-institute' WHERE creed_tenant IS NULL AND name = 'E.T.H.O.S.';

-- Everything else stays NULL -> kytran-empowerment (incl. G.A.V.E.L., S.C.O.U.T.,
-- S.P.E.C.T.R.A., A.R.C.H.I.E., all functional departments). legal-watch and kbs
-- have no dedicated agents yet; rows get values via data update when hired.
