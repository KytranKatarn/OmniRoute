# KBS Unified Data Model — Design Spec

**Date:** 2026-04-16
**Sub-project:** #1 of the "KBS as a Salesforce-style platform" decomposition
**Status:** Draft — awaiting user review
**Project ID:** TBD (will be logged after approval)

---

## 1. Context

KBS currently has a single flat `crm_customers` table that 15 plugins reference. Most references are orphan `customer_id INT` columns with no FK constraint; only two plugins (Appointments, Invoicing) have the proper FK. There is no concept of **company** vs **person**, no way to model multiple contacts at the same company, and no extensibility for Leads or Opportunities.

The goal of this sub-project is to replace that flat model with a Salesforce-style object hierarchy that every plugin — existing and future — shares. It's the foundation every other sub-project (custom fields, shell UI v2, marketplace, workflow engine) depends on.

## 2. Goals

- A shared `accounts` + `contacts` model that works for both B2B (company with multiple contacts) and B2C (individual walk-in customer).
- Lead and Opportunity tables exist at the schema level but are tier-gated at the application level (Lead → business tier, Opportunity → enterprise tier).
- Every existing plugin table with `customer_id` gets migrated to the new linking pattern.
- Migration is one-shot per tenant with a clear rollback path.
- Design reserves room for custom fields (JSONB column per object) so that the later sub-project doesn't need another migration.

## 3. Non-Goals

- **Custom Field UI and enforcement.** The `custom_fields JSONB` column is reserved but the UI, validation, and per-tenant field catalog are a separate sub-project.
- **Workflow automation.** Leads/Opportunities don't get conversion flows in this spec.
- **Permissions model.** Tenant-level owner/admin/member stays as-is; record-level sharing is a later sub-project.
- **Reports & dashboards.** Cross-module queries are a later sub-project.
- **API layer.** REST/GraphQL API on top of the new objects is not in this spec.

## 4. Design Decisions (from brainstorm)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Object hierarchy: Account + Contact at base; Lead + Opportunity at business/enterprise tier** | Tiered visibility without branching schema. Upgrading a tenant is a permission flip, not a migration. |
| D2 | **Person Accounts for B2C** — single row serves as both Account and Contact via `type='person'` | Salesforce's chosen answer after years of pain. Single "Customers" list UX. Rollups work for both shapes. |
| D3 | **Child tables carry both `account_id` (required) and `contact_id` (optional)** | Clean rollups both directions. Matches Salesforce's pattern for Opportunities, Cases, Tasks. |
| D4 | **Big bang migration per tenant** — one SQL file, ~5 min downtime per tenant | Low real-data volume today; clean end-state; no dual-write complexity. |
| D5 | **Drop the `crm_` prefix** — tables are `accounts`, `contacts`, `leads`, `opportunities` | These are core KBS objects, not CRM-plugin-owned. |
| D6 | **Per-tenant schema stays** — tables live in each `tenant_{id}` schema | Matches current KBS architecture. |
| D7 | **INTEGER SERIAL IDs** — not UUIDs | Matches current KBS convention. No forced migration on existing plugins. |
| D8 | **`custom_fields JSONB DEFAULT '{}'`** on every core table from day 1 | Reserves space for sub-project #4 without another migration. |
| D9 | **Soft delete via `deleted_at TIMESTAMPTZ`** on all four tables | Recoverable, auditable. Hard delete requires explicit admin action. |

**Person Account invariant:** When a Person Account is created, the service layer (§8) atomically creates both the `accounts` row (`type='person'`) AND its matching primary `contacts` row. The pairing is enforced in `create_person_account()`, not by a DB trigger. Deleting a Person Account soft-deletes both rows. This keeps DB schema simple and keeps the invariant in one auditable code path.

## 5. Schema (DDL)

All four tables live in each `tenant_{id}` schema and are created by a new plugin migration: `plugins/kbs_core_objects/migrations/001_unified_objects.sql` (new plugin or bundled into `kbs_crm` — see §11).

### 5.1 accounts

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(10) NOT NULL DEFAULT 'company'
                        CHECK (type IN ('company', 'person')),
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    phone           VARCHAR(50),
    website         VARCHAR(255),
    billing_address JSONB DEFAULT '{}',
    shipping_address JSONB DEFAULT '{}',
    industry        VARCHAR(100),
    source          VARCHAR(50),
    status          VARCHAR(20) DEFAULT 'active'
                        CHECK (status IN ('active', 'inactive', 'prospect')),
    owner_user_id   INTEGER,
    notes           TEXT,
    tags            JSONB DEFAULT '[]',
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_accounts_type_status ON accounts(type, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_accounts_owner       ON accounts(owner_user_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_accounts_email       ON accounts(LOWER(email))  WHERE deleted_at IS NULL;
CREATE INDEX idx_accounts_name_trgm   ON accounts USING gin (name gin_trgm_ops);
```

### 5.2 contacts

```sql
CREATE TABLE IF NOT EXISTS contacts (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    full_name       VARCHAR(255) GENERATED ALWAYS AS (
                        TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
                    ) STORED,
    title           VARCHAR(100),
    email           VARCHAR(255),
    phone           VARCHAR(50),
    mobile          VARCHAR(50),
    is_primary      BOOLEAN DEFAULT FALSE,
    source          VARCHAR(50),
    owner_user_id   INTEGER,
    notes           TEXT,
    tags            JSONB DEFAULT '[]',
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_contacts_account  ON contacts(account_id)        WHERE deleted_at IS NULL;
CREATE INDEX idx_contacts_email    ON contacts(LOWER(email))      WHERE deleted_at IS NULL;
CREATE INDEX idx_contacts_name_trgm ON contacts USING gin (full_name gin_trgm_ops);

-- Enforce exactly one primary contact per Account
CREATE UNIQUE INDEX uniq_primary_contact_per_account
    ON contacts(account_id) WHERE is_primary = TRUE AND deleted_at IS NULL;
```

### 5.3 leads (business+ tier)

```sql
CREATE TABLE IF NOT EXISTS leads (
    id                   SERIAL PRIMARY KEY,
    first_name           VARCHAR(100),
    last_name            VARCHAR(100),
    email                VARCHAR(255),
    phone                VARCHAR(50),
    company              VARCHAR(255),
    title                VARCHAR(100),
    source               VARCHAR(50),
    status               VARCHAR(20) DEFAULT 'new'
                            CHECK (status IN ('new', 'contacted', 'qualified', 'unqualified', 'converted')),
    assigned_user_id     INTEGER,
    converted_at         TIMESTAMPTZ,
    converted_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    converted_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    notes                TEXT,
    tags                 JSONB DEFAULT '[]',
    custom_fields        JSONB DEFAULT '{}',
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    deleted_at           TIMESTAMPTZ
);

CREATE INDEX idx_leads_status   ON leads(status)           WHERE deleted_at IS NULL;
CREATE INDEX idx_leads_assigned ON leads(assigned_user_id) WHERE deleted_at IS NULL;
```

### 5.4 opportunities (enterprise tier)

```sql
CREATE TABLE IF NOT EXISTS opportunities (
    id              SERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    name            VARCHAR(255) NOT NULL,
    amount          NUMERIC(12,2),
    currency        VARCHAR(3) DEFAULT 'CAD',
    stage           VARCHAR(30) NOT NULL DEFAULT 'prospecting'
                        CHECK (stage IN ('prospecting','qualification','proposal',
                                         'negotiation','closed_won','closed_lost')),
    probability     SMALLINT CHECK (probability BETWEEN 0 AND 100),
    close_date      DATE,
    closed_at       TIMESTAMPTZ,
    owner_user_id   INTEGER,
    source          VARCHAR(50),
    description     TEXT,
    tags            JSONB DEFAULT '[]',
    custom_fields   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_opportunities_account   ON opportunities(account_id)    WHERE deleted_at IS NULL;
CREATE INDEX idx_opportunities_stage     ON opportunities(stage)         WHERE deleted_at IS NULL;
CREATE INDEX idx_opportunities_owner     ON opportunities(owner_user_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_opportunities_close     ON opportunities(close_date)    WHERE deleted_at IS NULL AND stage NOT IN ('closed_won','closed_lost');
```

### 5.5 updated_at triggers

A shared `set_updated_at()` function updates `updated_at` on every row update for all four tables.

```sql
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_accounts_updated        BEFORE UPDATE ON accounts      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_contacts_updated        BEFORE UPDATE ON contacts      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_leads_updated           BEFORE UPDATE ON leads         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_opportunities_updated   BEFORE UPDATE ON opportunities FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### 5.6 `crm_customers` compatibility VIEW

To keep ad-hoc queries and third-party tools working during transition:

```sql
CREATE OR REPLACE VIEW crm_customers AS
SELECT
    a.id,
    COALESCE(c.full_name, a.name) AS name,
    COALESCE(c.email, a.email)   AS email,
    COALESCE(c.phone, a.phone)   AS phone,
    CASE WHEN a.type = 'company' THEN a.name ELSE NULL END AS company,
    a.status,
    a.source,
    a.notes,
    a.tags,
    jsonb_build_object('type', a.type, 'account_id', a.id, 'contact_id', c.id) AS metadata,
    a.created_at,
    a.updated_at
FROM accounts a
LEFT JOIN contacts c ON c.account_id = a.id AND c.is_primary = TRUE AND c.deleted_at IS NULL
WHERE a.deleted_at IS NULL;
```

This view is read-only. Any plugin that writes to `crm_customers` is forbidden after migration (caught by the test suite — see §9).

## 6. Plugin Impact

Every plugin table that today has `customer_id INT` gets rewritten to the new link pattern. Baseline inventory from the migration audit:

| Plugin | Tables affected (FK count) | Current column | New columns |
|--------|---------------------------|----------------|-------------|
| kbs_accounting | 2 (invoices, ledger_entries) | `customer_id INT` | `account_id INT NOT NULL`, `contact_id INT` |
| kbs_appointments | 1 (appointments) | `customer_id INT` (FK → crm_customers) | same |
| kbs_call_center | 1 (call_records) | `customer_id INTEGER` | same |
| kbs_communications | 2 (sms_messages, chat_conversations) | `customer_id INTEGER` | same |
| kbs_contracts | 1 (contracts) | `customer_id INT` | same |
| kbs_crm | 2 (crm_segment_members, crm_activities) | `customer_id NOT NULL` (FK) | `account_id NOT NULL`, `contact_id` nullable |
| kbs_help_desk | 1 (tickets) | `customer_id INTEGER` | same |
| kbs_industry | 1 (jobs) | `customer_id INTEGER` | same |
| kbs_industry_limo | 1 (trips) | `customer_id INTEGER` | same |
| kbs_industry_photography | 1 (sessions) | `customer_id INTEGER` | same |
| kbs_industry_plumbing | 1 (jobs) | `customer_id INT` | same |
| kbs_industry_salon | 2 (bookings, loyalty) | `customer_id INT` | same |
| kbs_invoicing | 1 (invoices) | `customer_id INT` (FK → crm_customers) | same |
| kbs_marketing | 1 (campaigns_log) | `customer_id INT` | same |
| kbs_store | 1 (store_orders) | `customer_id INTEGER` | same |

**Total: 18 tables across 15 plugins.**

Backfill rule: `WHERE customer_id = old_crm_customers.id` → set `account_id = new_accounts.id` and, if the old row had `company` populated, `contact_id = new_contacts.id` (the person within that company).

## 7. Migration Plan

### 7.1 Per-tenant migration script

A single SQL file, parametrized for any tenant schema: `migrations/tenant/011_unified_data_model.sql`.

```sql
SET search_path TO tenant_{id}, public;

-- Prereq: pg_trgm must be installed at the DB level (one-time, not per-tenant):
--   CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Step 1: rename crm_customers out of the way so the compat VIEW can take that name later.
ALTER TABLE crm_customers RENAME TO crm_customers_old;

-- Also rename any FK constraints that reference it by name, then keep child tables
-- referencing crm_customers_old until we rewrite them in Step 5.

-- Step 2: create new tables (§5)
\ir '../plugins/kbs_core_objects/migrations/001_unified_objects.sql'

-- Step 3: split crm_customers_old into accounts + contacts
-- Rule: company IS NULL OR company = '' → Person Account
INSERT INTO accounts (id, type, name, email, phone, status, source, notes, tags, created_at, updated_at)
SELECT
    id,
    CASE WHEN NULLIF(TRIM(company), '') IS NULL THEN 'person' ELSE 'company' END,
    CASE WHEN NULLIF(TRIM(company), '') IS NULL THEN name ELSE company END,
    email, phone, status, source, notes, tags, created_at, updated_at
FROM crm_customers_old;

-- Preserve the id sequence so child-table FKs resolve with UPDATE account_id = customer_id
SELECT setval('accounts_id_seq', (SELECT COALESCE(MAX(id), 1) FROM accounts));

-- Step 4a: create Contact rows for B2B customers (the person within the company)
INSERT INTO contacts (account_id, first_name, last_name, email, phone, is_primary, source, notes, created_at, updated_at)
SELECT
    c.id,
    split_part(c.name, ' ', 1) AS first_name,
    NULLIF(substring(c.name FROM position(' ' IN c.name) + 1), '') AS last_name,
    c.email, c.phone, TRUE, c.source, c.notes, c.created_at, c.updated_at
FROM crm_customers_old c
WHERE NULLIF(TRIM(c.company), '') IS NOT NULL;

-- Step 4b: create primary Contact rows for Person Accounts too
INSERT INTO contacts (account_id, first_name, last_name, email, phone, is_primary, source, created_at, updated_at)
SELECT
    c.id,
    split_part(c.name, ' ', 1),
    NULLIF(substring(c.name FROM position(' ' IN c.name) + 1), ''),
    c.email, c.phone, TRUE, c.source, c.created_at, c.updated_at
FROM crm_customers_old c
WHERE NULLIF(TRIM(c.company), '') IS NULL;

-- Step 5: rewrite every plugin FK (per-table block, generated from §6 inventory)
-- Example for kbs_appointments.appointments:
ALTER TABLE appointments
    ADD COLUMN account_id INT REFERENCES accounts(id) ON DELETE CASCADE,
    ADD COLUMN contact_id INT REFERENCES contacts(id) ON DELETE SET NULL;

UPDATE appointments a
   SET account_id = a.customer_id,
       contact_id = (SELECT id FROM contacts WHERE account_id = a.customer_id AND is_primary LIMIT 1)
 WHERE a.customer_id IS NOT NULL;

ALTER TABLE appointments ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE appointments DROP COLUMN customer_id;
-- ... repeat for every row in §6 ...

-- Step 6: create compat VIEW named crm_customers pointing at the new model (§5.6)

-- Step 7: record migration
INSERT INTO schema_migrations (version, applied_at) VALUES ('011_unified_data_model', NOW());
```

### 7.2 Execution order

1. Provisioning code update: `provision_tenant_schema()` runs new migration for every new tenant.
2. For each existing tenant: back up → run migration → verify row counts → commit or roll back.
3. Tenants in current DB: tenant_1 (real data), tenant_9908 (just-provisioned), tenant_9907 (business), tenant_9902 (free). Four total, sequential, with explicit approval between each.

### 7.3 Rollback

- Drop new tables; restore `crm_customers` from `crm_customers_old`.
- `crm_customers_old` is retained for 30 days post-migration. After that, an explicit cleanup migration drops it.
- Per-tenant rollback SQL is generated alongside the forward migration.

## 8. Service Layer

New module `core/objects.py` — all plugins call this, no direct SQL against `accounts`/`contacts`/`leads`/`opportunities` from plugin code.

```python
# core/objects.py
def get_account(tenant_id: int, account_id: int) -> dict | None: ...
def find_accounts(tenant_id: int, query: str, type: str | None = None, limit: int = 50) -> list[dict]: ...
def create_person_account(tenant_id: int, first_name: str, last_name: str, email: str | None = None, **kw) -> int: ...
def create_company_account(tenant_id: int, name: str, **kw) -> int: ...
def upsert_account_from_email(tenant_id: int, email: str, display_name: str) -> int: ...
def get_contact(tenant_id: int, contact_id: int) -> dict | None: ...
def list_contacts_for_account(tenant_id: int, account_id: int) -> list[dict]: ...
def soft_delete_account(tenant_id: int, account_id: int, user_id: int) -> None: ...
def get_primary_contact(tenant_id: int, account_id: int) -> dict | None: ...

# Leads (tier-gated — raise PermissionError if tenant not on business+)
def create_lead(tenant_id: int, **kw) -> int: ...
def convert_lead(tenant_id: int, lead_id: int) -> tuple[int, int]:  # → (account_id, contact_id)
    ...

# Opportunities (tier-gated — raise PermissionError if tenant not on enterprise)
def create_opportunity(tenant_id: int, account_id: int, name: str, amount: float, **kw) -> int: ...
```

Tier checks are embedded in the service methods for Lead/Opportunity calls. Plugin route decorators (`@tier_required`) are a separate layer (sub-project #3).

## 9. Testing

### 9.1 Unit / integration tests

- `tests/test_core/test_objects.py` — CRUD for each entity, primary contact uniqueness, Person Account + primary Contact creation flow.
- `tests/test_core/test_object_tier_gating.py` — free tenant calling `create_lead()` raises `PermissionError`; business tenant succeeds; enterprise-only for opportunities.

### 9.2 Migration tests

- `tests/test_migrations/test_011_unified_data_model.py` — fixture seeds `crm_customers_old` with 3 rows (B2C, B2B with company, B2B blank company), runs migration against a throwaway schema, asserts:
  - 3 accounts rows (correct types)
  - 2 contacts rows (one for B2B company contact; one auto-created for B2C person account)
  - Every plugin FK column (`appointments.account_id`, etc.) populated
  - Compat VIEW `crm_customers` returns 3 rows with matching shape

### 9.3 Smoke tests

- For each of the 15 affected plugins, one end-to-end "create record with customer" test must pass post-migration.

## 10. Rollout

1. **PR A** — add core schema + service layer + tests (no plugin changes). Deploys to dev; tenant_9908 schema re-provisioned with new tables.
2. **PR B** — per-tenant migration script + rollback; verify on tenant_9902 (free, smallest).
3. **PR C** — batch 1: kbs_crm, kbs_invoicing, kbs_appointments (the three plugins with real FK constraints) — rewrite routes to use service layer.
4. **PR D** — batch 2: all remaining plugins rewritten (12 plugins, orphan INT columns).
5. **PR E** — drop `crm_customers_old` after 30 days, remove compat VIEW, confirm no plugin still reads `crm_customers`.

## 11. Open Questions (to resolve during writing-plans)

- Should the four new tables live in a new `kbs_core_objects` plugin (separate migration dir) or be bundled into `kbs_crm`? The former gives cleaner dependency semantics; the latter preserves the manifest model already in place.
- Migration for tenant_1 (has real Kytran customer data) — does it run in the same PR as the code change, or a separate "execute migration" PR that can be approved independently?
- Index tuning: are the `gin_trgm_ops` indexes needed on day 1, or only when search UI is built?

## 12. Follow-on Work (explicitly out of scope)

- Custom Fields Engine (sub-project #4 in the master decomposition)
- Shell UI v2 — Salesforce-style list view / detail view / related lists (sub-project #2)
- Subscription tier gating — `@tier_required` decorator on plugin routes (sub-project #3 / Task #2018)
- Workflow engine (sub-project #6)
- Reports & dashboards (later phase)

---

## Appendix A — Example Queries

```sql
-- All open invoices for Acme (B2B)
SELECT i.* FROM invoices i
WHERE i.account_id = (SELECT id FROM accounts WHERE name = 'Acme Plumbing')
  AND i.status = 'unpaid';

-- All appointments Jane Doe attended (B2C — Person Account)
SELECT a.* FROM appointments a
JOIN accounts acc ON acc.id = a.account_id
WHERE acc.type = 'person' AND acc.name = 'Jane Doe';

-- Primary contact for an Account
SELECT * FROM contacts WHERE account_id = $1 AND is_primary = TRUE;
```
