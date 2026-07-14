-- 044_issuer_entity_links_backfill.sql
-- #373 Contract->Market chain — link the remaining 8 TSX issuers into the entity graph.
--
-- WHY: M2 (securities.issuer_contracts) added 8 issuers AFTER the June market-watch
-- adapter run, so they never got a security-<ticker> node or a market_reaction_to edge,
-- and their federal-contract footprint never surfaced on any entity page (M3).
--
-- CURATION (hand-picked — NOT fuzzy-matched; naive matching surfaced "Ron Watkins" 266-rel
-- as a top hit for AtkinsRéalis). For each ticker we create the security node and link it
-- from the exact TSX-listed PARENT entity plus, where the parent is barely-connected, the
-- company's primary OPERATING subsidiary (each a genuine same-company entity; the security
-- node's "(TICKER)" label keeps the "publicly traded" framing honest — mirrors the live
-- Open Text / Toromont dual-links). Deliberate exclusions: Bombardier Recreational Products
-- (BRP — a separate listed company), and all JOINT-VENTURE nodes.
--
-- Idempotent: re-runnable (WHERE NOT EXISTS guards on slug and on the edge triple).
-- Target DB: hub Postgres `wtf` (shared.* graph). shared.entities INSERT is allowed
-- (trg_entities_guard fires only on DELETE/UPDATE).

BEGIN;

-- 1) security-<ticker> nodes (entity_type/roles mirror the live security-mda shape).
INSERT INTO shared.entities (entity_type, canonical_name, slug, aliases, roles, metadata, status)
SELECT 'organization',
       ic.name || ' (' || ic.ticker || ')',
       'security-' || lower(ic.ticker),
       ARRAY[ic.name, ic.ticker],
       jsonb_build_array(jsonb_build_object(
           'type','securities_issuer','source','tsx','ticker',ic.ticker,'exchange',ic.exchange)),
       '{}'::jsonb,
       'active'
FROM securities.issuer_contracts ic
WHERE ic.ticker IN ('BBD.B','CIGI','ATRL','GIB.A','WSP','SU','ACO.X','RCI.B')
  AND NOT EXISTS (SELECT 1 FROM shared.entities e2 WHERE e2.slug = 'security-' || lower(ic.ticker));

-- 2) market_reaction_to edges: curated company entity -> its security node.
INSERT INTO shared.entity_relationships
       (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
SELECT v.org_id, s.id, 'market_reaction_to', 'market-watch',
       v.org_id || '|mrt|' || v.ticker,
       jsonb_build_object('match','curated','source','issuer_crosswalk',
                          'ticker',v.ticker,'exchange','TSX','reaction','structural',
                          'backfill','issuer_contracts_2026-07')
FROM (VALUES
    (13333,  'BBD.B'),                       -- Bombardier Inc. (excl. BRP)
    (4008546,'CIGI'), (1518318,'CIGI'),      -- Colliers Int'l Group + Colliers Project Leaders Inc.
    (4008427,'ATRL'), (1459274,'ATRL'),      -- AtkinsRéalis Group + AtkinsRéalis Canada Inc.
    (4008529,'GIB.A'),(14608,  'GIB.A'),     -- CGI Inc. + CGI Information Systems & Mgmt Consultants
    (4009038,'WSP'),  (26322,  'WSP'),       -- WSP Global Inc. + WSP Canada Inc.
    (13473,  'SU'),                          -- Suncor Energy Inc.
    (216810, 'ACO.X'),                       -- ATCO Ltd.
    (192244, 'RCI.B')                        -- Rogers Communications Inc.
) AS v(org_id, ticker)
JOIN shared.entities s  ON s.slug = 'security-' || lower(v.ticker)
JOIN shared.entities o  ON o.id   = v.org_id AND o.status = 'active' AND o.merged_into IS NULL
WHERE NOT EXISTS (
    SELECT 1 FROM shared.entity_relationships r
    WHERE r.from_entity_id = v.org_id AND r.to_entity_id = s.id
      AND r.relationship_type = 'market_reaction_to');

COMMIT;
