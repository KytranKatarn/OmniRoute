-- Migration 180: Extend domain management for multi-domain support
-- Adds user_id, registrar, nameservers to org_domains
-- Adds domain_id FK to managed_dns_records
-- Idempotent: safe to re-run

-- 1. Add user_id to org_domains for per-user SaaS scoping
ALTER TABLE org_domains ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);

-- 2. Add registrar and nameservers fields
ALTER TABLE org_domains ADD COLUMN IF NOT EXISTS registrar VARCHAR(100);
ALTER TABLE org_domains ADD COLUMN IF NOT EXISTS nameservers TEXT[];  -- array of nameserver hostnames
ALTER TABLE org_domains ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE org_domains ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- 3. Add domain_id FK to managed_dns_records so records can link to org_domains
ALTER TABLE managed_dns_records ADD COLUMN IF NOT EXISTS domain_id INTEGER REFERENCES org_domains(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_managed_dns_records_domain_id ON managed_dns_records(domain_id);

-- 4. Add user_id index on org_domains
CREATE INDEX IF NOT EXISTS idx_org_domains_user_id ON org_domains(user_id);

-- 5. Backfill user_id=1 for existing org_domains rows (admin user)
UPDATE org_domains SET user_id = 1 WHERE user_id IS NULL;
