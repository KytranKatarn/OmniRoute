-- Contract test for the ADR-EG-001 amendment (2026-06-25): entity-graph ingest
-- now accepts per-entity `metadata` (merged) + `external_ids` (sedar_issuer key).
--
-- Runs entirely in a rolled-back txn against the LIVE `wtf` schema — proves the
-- exact ON CONFLICT clauses shipped in consumer/entity_graph_routes.py without
-- persisting anything (shared.entities is immutable; DELETE is trigger-blocked).
--
-- Run:  docker exec -i archie_database psql -U archie -d wtf -tA -v ON_ERROR_STOP=1 \
--         -f consumer/tests/test_entity_graph_metadata.sql | grep -E 'PASS|FAIL'
-- Expect: T1..T5 all PASS.

BEGIN;

-- T1: metadata shallow-merges across upserts (naics_* accrete, no clobber).
INSERT INTO shared.entities (entity_type,canonical_name,slug,aliases,roles,metadata)
VALUES ('organization','ZZ SliceA Test Co','zz-slicea-eg001','{}'::text[],'[]'::jsonb,'{"a":1}'::jsonb)
ON CONFLICT (slug) DO UPDATE SET metadata=COALESCE(shared.entities.metadata,'{}'::jsonb)||COALESCE(EXCLUDED.metadata,'{}'::jsonb), updated_at=NOW();
INSERT INTO shared.entities (entity_type,canonical_name,slug,aliases,roles,metadata)
VALUES ('organization','ZZ SliceA Test Co','zz-slicea-eg001','{}'::text[],'[]'::jsonb,'{"b":2,"naics_code":"522111","naics_sector":"52","naics_source":"tmx_derived"}'::jsonb)
ON CONFLICT (slug) DO UPDATE SET metadata=COALESCE(shared.entities.metadata,'{}'::jsonb)||COALESCE(EXCLUDED.metadata,'{}'::jsonb), updated_at=NOW();
SELECT 'T1 metadata_merge: '||CASE WHEN metadata @> '{"a":1,"b":2,"naics_sector":"52","naics_code":"522111"}'::jsonb THEN 'PASS' ELSE 'FAIL '||metadata::text END FROM shared.entities WHERE slug='zz-slicea-eg001';

-- T2: a caller that OMITS metadata sends '{}' (column is NOT NULL; the route never
--     sends NULL) → existing keys are preserved (backward-compatible no-op merge).
INSERT INTO shared.entities (entity_type,canonical_name,slug,aliases,roles,metadata)
VALUES ('organization','ZZ SliceA Test Co','zz-slicea-eg001','{}'::text[],'[]'::jsonb,'{}'::jsonb)
ON CONFLICT (slug) DO UPDATE SET metadata=COALESCE(shared.entities.metadata,'{}'::jsonb)||COALESCE(EXCLUDED.metadata,'{}'::jsonb), updated_at=NOW();
SELECT 'T2 no_clobber_on_empty: '||CASE WHEN metadata @> '{"a":1,"naics_sector":"52"}'::jsonb THEN 'PASS' ELSE 'FAIL '||metadata::text END FROM shared.entities WHERE slug='zz-slicea-eg001';

-- T3: external id written.
INSERT INTO shared.entity_external_ids (entity_id,key_type,key_value,source_product)
SELECT id,'sedar_issuer','TEST-EG001-999','market-watch' FROM shared.entities WHERE slug='zz-slicea-eg001'
ON CONFLICT (key_type,key_value) DO UPDATE SET entity_id=EXCLUDED.entity_id, source_product=COALESCE(EXCLUDED.source_product, shared.entity_external_ids.source_product);
SELECT 'T3 extid_write: '||CASE WHEN count(*)=1 THEN 'PASS' ELSE 'FAIL '||count(*)::text END FROM shared.entity_external_ids WHERE key_type='sedar_issuer' AND key_value='TEST-EG001-999';

-- T4: ON CONFLICT (key_type,key_value) re-points entity_id (one issuer# -> one entity).
INSERT INTO shared.entities (entity_type,canonical_name,slug,aliases,roles,metadata)
VALUES ('organization','ZZ SliceA Test Co2','zz-slicea2-eg001','{}'::text[],'[]'::jsonb,'{}'::jsonb) ON CONFLICT (slug) DO NOTHING;
INSERT INTO shared.entity_external_ids (entity_id,key_type,key_value,source_product)
SELECT id,'sedar_issuer','TEST-EG001-999','market-watch' FROM shared.entities WHERE slug='zz-slicea2-eg001'
ON CONFLICT (key_type,key_value) DO UPDATE SET entity_id=EXCLUDED.entity_id;
SELECT 'T4 extid_repoint: '||CASE WHEN (SELECT entity_id FROM shared.entity_external_ids WHERE key_type='sedar_issuer' AND key_value='TEST-EG001-999')=(SELECT id FROM shared.entities WHERE slug='zz-slicea2-eg001') THEN 'PASS' ELSE 'FAIL' END;

ROLLBACK;

-- T5: prove the rollback left nothing behind.
SELECT 'T5 rollback_clean: '||CASE WHEN NOT EXISTS(SELECT 1 FROM shared.entities WHERE slug LIKE 'zz-slicea%eg001') THEN 'PASS' ELSE 'FAIL' END;
