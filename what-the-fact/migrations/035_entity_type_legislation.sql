-- 035_entity_type_legislation.sql
-- Project #373 (Shared Entity Graph) — Link 3 (Vote).
-- Owner decision 2026-06-15: extend the canonical entity vocabulary with
-- 'legislation' so parliamentary bills/divisions become first-class nodes and
-- MP --cast_vote--> legislation edges can live in shared.entity_relationships.
-- AMENDS ADR-EG-001 (entity_type was frozen to person/organization/journalist).
-- Idempotent.
BEGIN;

ALTER TABLE shared.entities DROP CONSTRAINT IF EXISTS entities_entity_type_check;
ALTER TABLE shared.entities ADD CONSTRAINT entities_entity_type_check
    CHECK (entity_type = ANY (ARRAY['person', 'organization', 'journalist', 'legislation']));

-- Dedup intent (the dedup engine #3792 is not yet live): legislation entities must
-- NEVER fuzzy-merge — a bill is not a person/org. They resolve on exact slug only
-- (slug = 'parl-division-<id>'). The engine, when built, must restrict candidate
-- blocking to entity_type IN ('person','organization'). Recorded as canonical intent.
INSERT INTO shared.dedup_config (key, value, description)
SELECT 'legislation_fuzzy_enabled', 0,
       'legislation entities are excluded from fuzzy dedup — exact-slug match only (#373 L3)'
WHERE NOT EXISTS (SELECT 1 FROM shared.dedup_config WHERE key = 'legislation_fuzzy_enabled');

-- chain catalog: cast_vote (L3) row already exists with has_data=true; the parliament
-- reconcile (entity_graph_parliament_reconcile) makes that honest by populating the edges.

COMMIT;
