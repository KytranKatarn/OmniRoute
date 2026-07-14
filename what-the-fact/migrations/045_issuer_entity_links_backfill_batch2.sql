-- 045_issuer_entity_links_backfill_batch2.sql
-- #373 Contract->Market — link the 4 NEW TSX issuers added to the Gov Watch ISSUER_CROSSWALK
-- (2026-07): BCE, SLF, CGY, CPX. Same curated parent+operating pattern as 044. Idempotent.
--
-- CURATION (hand-verified, exact-string — never fuzzy):
--   BCE  -> BCE Inc. (parent) + Bell Canada (primary operating). Excludes "Bell Textron" (Textron).
--   SLF  -> Sun Life Financial Inc. (parent) + Sun Life Assurance Company of Canada (operating).
--   CGY  -> Calian Group Ltd (parent) + CALIAN LTD (operating). EXCLUDES "Scalian inc." (1550938) —
--           a DIFFERENT company that merely contains the substring "calian" — and non-Calian-led JVs.
--   CPX  -> Capital Power Corporation (parent) + Capital Power (operating).
--
-- Idempotent (WHERE NOT EXISTS on slug + edge triple). shared.entities INSERT is allowed
-- (trg_entities_guard fires only on DELETE/UPDATE). Target: hub Postgres `wtf` (shared.* graph).

BEGIN;

-- 1) security-<ticker> nodes (mirror the live security-mda shape).
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
WHERE ic.ticker IN ('BCE','SLF','CGY','CPX')
  AND NOT EXISTS (SELECT 1 FROM shared.entities e2 WHERE e2.slug = 'security-' || lower(ic.ticker));

-- 2) curated parent + primary-operating market_reaction_to edges.
INSERT INTO shared.entity_relationships
       (from_entity_id, to_entity_id, relationship_type, source_product, source_id, metadata)
SELECT v.org_id, s.id, 'market_reaction_to', 'market-watch',
       v.org_id || '|mrt|' || v.ticker,
       jsonb_build_object('match','curated','source','issuer_crosswalk',
                          'ticker',v.ticker,'exchange','TSX','reaction','structural',
                          'backfill','issuer_contracts_2026-07')
FROM (VALUES
    (237359,  'BCE'), (13737,   'BCE'),   -- BCE Inc. (parent) + Bell Canada (operating)
    (194632,  'SLF'), (1465132, 'SLF'),   -- Sun Life Financial Inc. + Sun Life Assurance Company of Canada
    (1459975, 'CGY'), (14135,   'CGY'),   -- Calian Group Ltd + CALIAN LTD (NOT "Scalian inc." 1550938)
    (193701,  'CPX'), (1466415, 'CPX')    -- Capital Power Corporation + Capital Power
) AS v(org_id, ticker)
JOIN shared.entities s ON s.slug = 'security-' || lower(v.ticker)
JOIN shared.entities o ON o.id = v.org_id AND o.status = 'active' AND o.merged_into IS NULL
WHERE NOT EXISTS (
    SELECT 1 FROM shared.entity_relationships r
    WHERE r.from_entity_id = v.org_id AND r.to_entity_id = s.id
      AND r.relationship_type = 'market_reaction_to');

COMMIT;
