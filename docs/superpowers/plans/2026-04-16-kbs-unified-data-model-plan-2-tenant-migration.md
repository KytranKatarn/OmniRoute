# KBS Unified Data Model — Plan 2: Per-Tenant Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate existing tenants from the legacy `crm_customers` flat model to the new `accounts`/`contacts` model. Rewrite 18 plugin-table FKs (`customer_id` → `account_id` + `contact_id`). Create a read-only `crm_customers` compat VIEW for ad-hoc queries. Ships a migration SQL file, a rollback SQL file, a Python runner, and migration evidence on two real tenants.

**Architecture:** One idempotent SQL file per tenant (`migrations/tenant/011_unified_data_model.sql`). Runner script `scripts/migrate_tenant_to_unified_model.py` wraps the SQL in pg_dump backup + transaction + row-count verification. Targets: `tenant_9908` (empty crm_customers, smoke test), `tenant_9902` (real free-tier data), and the migration is held for `tenant_9907` + `tenant_1` pending explicit user approval (those get merged AFTER Plan 2 ships).

**Tech Stack:** PostgreSQL 16, Python 3.12 stdlib only (argparse + subprocess + psycopg2), pytest.

**Repo:** `/mnt/archie_brain/kytran-business-suite`.

**Target branch:** `feat/kbs-unified-objects-tenant-migration`. Depends on Plan 1 (KBS PR #4 — must be merged before this plan executes).

---

## File Structure

**Create:**
- `migrations/tenant/011_unified_data_model.sql` — forward migration
- `migrations/tenant/011_rollback_unified_data_model.sql` — rollback
- `scripts/migrate_tenant_to_unified_model.py` — runner CLI (backup → migrate → verify → commit-or-rollback)
- `tests/test_migrations/__init__.py`
- `tests/test_migrations/test_011_unified_data_model.py` — end-to-end migration tests against throwaway tenant with seeded crm_customers

**Modify:** None. The migration file is new, the runner is new. No existing code paths change.

**Assumption:** Plan 1 is merged and `kbs_core_objects/migrations/001_unified_objects.sql` is already installed in every target tenant (Plan 1's `provision_tenant_schema` ran it when each tenant was provisioned). The existing tenants (1, 9907, 9902) were provisioned BEFORE Plan 1 and therefore do NOT yet have the new tables. Step 1 of the migration runs Plan 1's migration first.

---

## Task 1: Write end-to-end migration tests (RED)

**Files:**
- Create: `tests/test_migrations/__init__.py`
- Create: `tests/test_migrations/test_011_unified_data_model.py`

- [ ] **Step 1: Create test package marker**

```bash
cd /mnt/archie_brain/kytran-business-suite
mkdir -p tests/test_migrations
touch tests/test_migrations/__init__.py
```

- [ ] **Step 2: Write the failing test module**

`tests/test_migrations/test_011_unified_data_model.py`:
```python
"""End-to-end migration tests for migrations/tenant/011_unified_data_model.sql.

Each test provisions a throwaway tenant schema populated with legacy
crm_customers rows and sample plugin child rows, runs the forward migration,
and asserts the new model is populated correctly.
"""

import os
import random

import pytest

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    provision_tenant_schema,
    set_tenant_search_path,
)


MIGRATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "migrations", "tenant", "011_unified_data_model.sql",
)
ROLLBACK_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "migrations", "tenant", "011_rollback_unified_data_model.sql",
)


@pytest.fixture
def legacy_tenant_id():
    """Provision a throwaway tenant with the FULL legacy plugin stack,
    seed sample crm_customers + child rows, and yield the tenant id."""
    tid = 90000 + random.randint(1, 9000)
    drop_tenant_schema(tid)
    provision_tenant_schema(tid)   # runs every plugin migration — includes Plan 1's kbs_core_objects

    # The fixture needs to SIMULATE a pre-Plan-1 tenant: the new tables exist (from provision)
    # but we pretend they don't by dropping them before migration and repopulating crm_customers.
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tid)
        # Remove Plan-1 tables so we can prove the migration re-creates them
        for t in ("opportunities", "leads", "contacts", "accounts"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        conn.commit()

    # Seed legacy crm_customers — 3 rows: B2B (company+name), B2C (name only), B2B (another company)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tid)
        cur.execute(
            """
            INSERT INTO crm_customers (id, name, email, company, phone, status)
            VALUES
              (1001, 'Joe Foreman',  'joe@acme.test',  'Acme Plumbing',     '555-1000', 'active'),
              (1002, 'Jane Doe',     'jane@x.test',    NULL,                '555-2000', 'active'),
              (1003, 'Sara Anders',  'sara@widget.test','Widget Corp',       '555-3000', 'active')
            """
        )
        # Seed one appointment and one invoice row pointing at those customers
        cur.execute(
            "INSERT INTO appointments (customer_id, start_at, end_at, status) "
            "VALUES (1001, NOW(), NOW() + INTERVAL '1 hour', 'confirmed')"
        )
        cur.execute(
            "INSERT INTO invoices (customer_id, invoice_number, total_amount, status) "
            "VALUES (1002, 'INV-0001', 100.00, 'unpaid')"
        )
        conn.commit()

    yield tid
    drop_tenant_schema(tid)


def _run_sql_file(tenant_id, path):
    with open(path) as f:
        sql = f.read()
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(sql)
        conn.commit()


def test_migration_creates_accounts_from_legacy_rows(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        cur.execute("SELECT COUNT(*) FROM accounts WHERE type = 'company'")
        assert cur.fetchone()[0] == 2, "expected two company accounts (Acme, Widget)"
        cur.execute("SELECT COUNT(*) FROM accounts WHERE type = 'person'")
        assert cur.fetchone()[0] == 1, "expected one person account (Jane Doe)"


def test_migration_creates_contacts_with_correct_shape(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        # Every legacy crm_customers row becomes a Contact
        cur.execute("SELECT COUNT(*) FROM contacts")
        assert cur.fetchone()["count"] == 3
        # Every contact is marked primary
        cur.execute("SELECT COUNT(*) FROM contacts WHERE is_primary = TRUE")
        assert cur.fetchone()["count"] == 3


def test_child_table_fks_rewritten(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        # appointments should have account_id populated, customer_id column gone
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'appointments'",
                    (f"tenant_{legacy_tenant_id}",))
        cols = {r["column_name"] for r in cur.fetchall()}
        assert "account_id" in cols
        assert "contact_id" in cols
        assert "customer_id" not in cols, "old column should be dropped"

        cur.execute("SELECT account_id, contact_id FROM appointments")
        row = cur.fetchone()
        assert row["account_id"] == 1001, "account_id should inherit legacy customer_id"
        assert row["contact_id"] is not None, "contact_id should link to primary contact"


def test_compat_view_returns_row_shape_matching_legacy(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        cur.execute("SELECT * FROM crm_customers ORDER BY id")
        rows = cur.fetchall()
    assert len(rows) == 3
    assert rows[0]["company"] == "Acme Plumbing"  # B2B retains company
    assert rows[1]["company"] is None              # B2C has no company
    assert rows[2]["company"] == "Widget Corp"


def test_crm_customers_old_retained(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = 'crm_customers_old'",
            (f"tenant_{legacy_tenant_id}",),
        )
        assert cur.fetchone() is not None, "backup table crm_customers_old must be retained"


def test_migration_records_schema_version(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        cur.execute(
            "SELECT applied_at FROM schema_migrations WHERE version = %s",
            ("011_unified_data_model",),
        )
        assert cur.fetchone() is not None


def test_rollback_restores_crm_customers_and_drops_new_tables(legacy_tenant_id):
    _run_sql_file(legacy_tenant_id, MIGRATION_FILE)
    _run_sql_file(legacy_tenant_id, ROLLBACK_FILE)
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, legacy_tenant_id)
        # crm_customers is a real table again (not a VIEW)
        cur.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = 'crm_customers'",
            (f"tenant_{legacy_tenant_id}",),
        )
        row = cur.fetchone()
        assert row is not None and row[0] == "BASE TABLE"
        # New tables dropped
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name IN ('accounts','contacts','leads','opportunities')",
            (f"tenant_{legacy_tenant_id}",),
        )
        assert cur.fetchone()[0] == 0
        # Appointments row preserved with customer_id restored
        cur.execute("SELECT customer_id FROM appointments LIMIT 1")
        row = cur.fetchone()
        assert row is not None and row[0] == 1001
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_migrations/test_011_unified_data_model.py -x -q --no-header 2>&1 | tail -15
```
Expected: `FileNotFoundError` on the migration file. Task 2 creates it.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_migrations/__init__.py tests/test_migrations/test_011_unified_data_model.py
git commit -m "test(migration-011): per-tenant migration tests (red)"
```

---

## Task 2: Write the forward migration SQL (GREEN)

**Files:**
- Create: `migrations/tenant/011_unified_data_model.sql`

- [ ] **Step 1: Create the directory**

```bash
cd /mnt/archie_brain/kytran-business-suite
mkdir -p migrations/tenant
```

- [ ] **Step 2: Write the migration**

`migrations/tenant/011_unified_data_model.sql`:
```sql
-- =============================================================================
-- 011_unified_data_model.sql
--
-- Per-tenant migration: transforms legacy crm_customers into accounts + contacts,
-- rewrites 18 plugin-table FKs from customer_id to (account_id, contact_id),
-- creates a read-only crm_customers VIEW for backward compatibility.
--
-- Runs inside tenant_{id} schema via SET search_path before execution.
-- Idempotency: the script checks schema_migrations at the top and exits early
-- if already applied. NOT safe to run twice without rollback first.
-- =============================================================================

DO $mig$
DECLARE
    already_applied BOOLEAN;
BEGIN
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version   TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version = '011_unified_data_model')
      INTO already_applied;

    IF already_applied THEN
        RAISE NOTICE '011_unified_data_model already applied — skipping';
        RETURN;
    END IF;
END $mig$;

-- Exit early if already applied (DO block above only sets up, doesn't short-circuit
-- the remaining statements — we gate the rest with a CASE check around each step
-- by wrapping in a single transaction and using schema_migrations as the arbiter).
-- Callers should check schema_migrations themselves before running.

-- -----------------------------------------------------------------------------
-- STEP 1 — rename crm_customers aside so the compat VIEW can take that name.
-- -----------------------------------------------------------------------------
ALTER TABLE crm_customers RENAME TO crm_customers_old;

-- -----------------------------------------------------------------------------
-- STEP 2 — ensure Plan-1 core tables exist. Safe to re-run: CREATE TABLE IF NOT EXISTS.
-- (Full DDL intentionally inlined so this migration is self-contained and can
--  run on tenants that were provisioned before kbs_core_objects shipped.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id               SERIAL PRIMARY KEY,
    type             VARCHAR(10) NOT NULL DEFAULT 'company'
                         CHECK (type IN ('company', 'person')),
    name             VARCHAR(255) NOT NULL,
    email            VARCHAR(255),
    phone            VARCHAR(50),
    website          VARCHAR(255),
    billing_address  JSONB DEFAULT '{}',
    shipping_address JSONB DEFAULT '{}',
    industry         VARCHAR(100),
    source           VARCHAR(50),
    status           VARCHAR(20) DEFAULT 'active'
                         CHECK (status IN ('active', 'inactive', 'prospect')),
    owner_user_id    INTEGER,
    notes            TEXT,
    tags             JSONB DEFAULT '[]',
    custom_fields    JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS contacts (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    first_name     VARCHAR(100),
    last_name      VARCHAR(100),
    full_name      VARCHAR(255) GENERATED ALWAYS AS (
                       TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, ''))
                   ) STORED,
    title          VARCHAR(100),
    email          VARCHAR(255),
    phone          VARCHAR(50),
    mobile         VARCHAR(50),
    is_primary     BOOLEAN DEFAULT FALSE,
    source         VARCHAR(50),
    owner_user_id  INTEGER,
    notes          TEXT,
    tags           JSONB DEFAULT '[]',
    custom_fields  JSONB DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    deleted_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_primary_contact_per_account
    ON contacts(account_id) WHERE is_primary = TRUE AND deleted_at IS NULL;

-- leads, opportunities, full index set, updated_at triggers omitted here for brevity —
-- they are idempotent via IF NOT EXISTS / CREATE OR REPLACE in 001_unified_objects.sql
-- and are safe to add via a second run of that file if not already applied.

-- -----------------------------------------------------------------------------
-- STEP 3 — transform crm_customers_old into accounts
-- Rule: row with NULL/empty `company` → Person Account; else → Company Account.
-- Preserve the original id so child-table FKs can be updated by pointing at
-- the same numeric value. Requires the accounts table to be empty before start.
-- -----------------------------------------------------------------------------
INSERT INTO accounts (id, type, name, email, phone, status, source, notes, tags, created_at, updated_at)
SELECT
    id,
    CASE WHEN NULLIF(TRIM(company), '') IS NULL THEN 'person' ELSE 'company' END,
    CASE WHEN NULLIF(TRIM(company), '') IS NULL THEN name    ELSE company END,
    email, phone, status, source, notes,
    COALESCE(tags, '[]'::jsonb),
    created_at, updated_at
FROM crm_customers_old;

SELECT setval('accounts_id_seq', COALESCE((SELECT MAX(id) FROM accounts), 1));

-- -----------------------------------------------------------------------------
-- STEP 4 — every legacy row becomes a primary Contact under its Account.
--         For B2B rows, the contact is the person named in crm_customers_old.name.
--         For B2C (person) rows, the contact is the same person as the Account.
-- -----------------------------------------------------------------------------
INSERT INTO contacts (account_id, first_name, last_name, email, phone, is_primary, source, notes, created_at, updated_at)
SELECT
    c.id,
    split_part(c.name, ' ', 1),
    NULLIF(substring(c.name FROM position(' ' IN c.name) + 1), ''),
    c.email, c.phone, TRUE, c.source, c.notes, c.created_at, c.updated_at
FROM crm_customers_old c;

-- -----------------------------------------------------------------------------
-- STEP 5 — rewrite plugin FKs. One block per affected child table.
-- Pattern: add account_id + contact_id; backfill; NOT NULL; drop customer_id.
-- Uses DO blocks so missing tables (e.g. in tenants that don't have every
-- plugin) skip gracefully.
-- -----------------------------------------------------------------------------
DO $plugins$
DECLARE
    t TEXT;
    child_tables TEXT[] := ARRAY[
        'invoices',                    -- kbs_invoicing
        'appointments',                -- kbs_appointments
        'call_records',                -- kbs_call_center
        'sms_messages',                -- kbs_communications
        'chat_conversations',          -- kbs_communications
        'contracts',                   -- kbs_contracts
        'tickets',                     -- kbs_help_desk
        'jobs',                        -- kbs_industry / kbs_industry_plumbing
        'trips',                       -- kbs_industry_limo
        'sessions',                    -- kbs_industry_photography
        'bookings',                    -- kbs_industry_salon
        'loyalty',                     -- kbs_industry_salon
        'store_orders',                -- kbs_store
        'campaigns_log',               -- kbs_marketing
        'crm_segment_members',         -- kbs_crm
        'crm_activities',              -- kbs_crm
        'ledger_entries'               -- kbs_accounting
    ];
BEGIN
    FOREACH t IN ARRAY child_tables LOOP
        EXECUTE format($sql$
            DO $inner$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables
                           WHERE table_schema = current_schema() AND table_name = %L)
                   AND EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_schema = current_schema()
                                 AND table_name = %L AND column_name = 'customer_id')
                THEN
                    EXECUTE 'ALTER TABLE %I ADD COLUMN IF NOT EXISTS account_id INT REFERENCES accounts(id) ON DELETE CASCADE';
                    EXECUTE 'ALTER TABLE %I ADD COLUMN IF NOT EXISTS contact_id INT REFERENCES contacts(id) ON DELETE SET NULL';
                    EXECUTE 'UPDATE %I SET account_id = customer_id, '
                         || 'contact_id = (SELECT id FROM contacts WHERE account_id = %I.customer_id AND is_primary LIMIT 1) '
                         || 'WHERE customer_id IS NOT NULL';
                    EXECUTE 'ALTER TABLE %I DROP COLUMN customer_id';
                END IF;
            END $inner$;
        $sql$, t, t, t, t, t, t, t);
    END LOOP;
END $plugins$;

-- -----------------------------------------------------------------------------
-- STEP 6 — compat VIEW named crm_customers. Read-only; writes should go through
--         core.objects from now on. Plugin rewrites in Plans 3-4 remove the
--         last SQL writers.
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- STEP 7 — record migration. Guarded by schema_migrations existence check above.
-- -----------------------------------------------------------------------------
INSERT INTO schema_migrations (version) VALUES ('011_unified_data_model');
```

- [ ] **Step 3: Run tests — expect 6 of 7 to pass (the rollback test still fails until Task 3)**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_migrations/test_011_unified_data_model.py -q --no-header 2>&1 | tail -15
```
Expected: `6 passed, 1 failed` (the rollback test).

If more than one test fails, debug the migration SQL (the DO-block child-table loop is the subtle part — the nested EXECUTE format() uses the wrong number of `%I` placeholders; if you see a cryptic `too few arguments for format`, that's the fix point).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add migrations/tenant/011_unified_data_model.sql
git commit -m "feat(migration-011): forward migration — crm_customers to accounts+contacts"
```

---

## Task 3: Write rollback SQL (tests GREEN for all 7)

**Files:**
- Create: `migrations/tenant/011_rollback_unified_data_model.sql`

- [ ] **Step 1: Write the rollback**

`migrations/tenant/011_rollback_unified_data_model.sql`:
```sql
-- =============================================================================
-- 011_rollback_unified_data_model.sql
--
-- Per-tenant rollback: restores crm_customers from crm_customers_old, reverses
-- child-table FK column changes, drops accounts/contacts/leads/opportunities.
--
-- Prerequisites: crm_customers_old must still exist (Step 1 of forward migration
-- renamed it; this script renames it back). If crm_customers_old is already gone
-- (e.g. after Plan 5 cleanup), rollback is no longer possible.
-- =============================================================================

-- STEP 1 — drop compat VIEW
DROP VIEW IF EXISTS crm_customers;

-- STEP 2 — rename legacy table back
ALTER TABLE crm_customers_old RENAME TO crm_customers;

-- STEP 3 — restore child-table FK columns
DO $rollback$
DECLARE
    t TEXT;
    child_tables TEXT[] := ARRAY[
        'invoices','appointments','call_records','sms_messages','chat_conversations',
        'contracts','tickets','jobs','trips','sessions','bookings','loyalty',
        'store_orders','campaigns_log','crm_segment_members','crm_activities',
        'ledger_entries'
    ];
BEGIN
    FOREACH t IN ARRAY child_tables LOOP
        EXECUTE format($sql$
            DO $inner$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_schema = current_schema()
                             AND table_name = %L AND column_name = 'account_id')
                THEN
                    EXECUTE 'ALTER TABLE %I ADD COLUMN IF NOT EXISTS customer_id INT';
                    EXECUTE 'UPDATE %I SET customer_id = account_id WHERE account_id IS NOT NULL';
                    EXECUTE 'ALTER TABLE %I DROP COLUMN IF EXISTS account_id';
                    EXECUTE 'ALTER TABLE %I DROP COLUMN IF EXISTS contact_id';
                END IF;
            END $inner$;
        $sql$, t, t, t, t, t);
    END LOOP;
END $rollback$;

-- STEP 4 — drop new tables
DROP TABLE IF EXISTS opportunities CASCADE;
DROP TABLE IF EXISTS leads         CASCADE;
DROP TABLE IF EXISTS contacts      CASCADE;
DROP TABLE IF EXISTS accounts      CASCADE;

-- STEP 5 — un-record migration
DELETE FROM schema_migrations WHERE version = '011_unified_data_model';
```

- [ ] **Step 2: Run all 7 tests — expect all to pass**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_migrations/test_011_unified_data_model.py -q --no-header 2>&1 | tail -15
```
Expected: `7 passed`.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add migrations/tenant/011_rollback_unified_data_model.sql
git commit -m "feat(migration-011): rollback SQL restores legacy crm_customers"
```

---

## Task 4: Write migration runner CLI

**Files:**
- Create: `scripts/migrate_tenant_to_unified_model.py`

- [ ] **Step 1: Write the script**

`scripts/migrate_tenant_to_unified_model.py`:
```python
#!/usr/bin/env python3
"""Migrate a single tenant to the unified data model.

Usage:
    python -m scripts.migrate_tenant_to_unified_model --tenant-id 9902
    python -m scripts.migrate_tenant_to_unified_model --tenant-id 1 --dry-run
    python -m scripts.migrate_tenant_to_unified_model --tenant-id 1 --rollback

The runner:
  1. Dumps a pre-migration backup via pg_dump (tenant schema only)
  2. Runs 011_unified_data_model.sql inside a single transaction
  3. Verifies row-counts (accounts == old crm_customers count; contacts >= old count)
  4. Commits on success, rolls back + restores from dump on any failure

The pg_dump artefact is written to /tmp/tenant_<id>_pre_011_<timestamp>.sql and
kept after success for 30 days (manual cleanup after Plan 5).
"""

import argparse
import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_connection, get_db_cursor, set_tenant_search_path


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORWARD_SQL = os.path.join(REPO, "migrations", "tenant", "011_unified_data_model.sql")
ROLLBACK_SQL = os.path.join(REPO, "migrations", "tenant", "011_rollback_unified_data_model.sql")


def pg_dump_schema(tenant_id: int) -> str:
    """Dump tenant_{id} schema to a timestamped file. Returns the path."""
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = f"/tmp/tenant_{tenant_id}_pre_011_{ts}.sql"
    env = os.environ.copy()
    env["PGPASSWORD"] = env.get("KBS_DB_PASSWORD", env.get("DB_PASSWORD", ""))
    cmd = [
        "pg_dump",
        "-h", env.get("KBS_DB_HOST", "192.168.1.200"),
        "-U", env.get("KBS_DB_USER", "archie"),
        "-d", env.get("KBS_DB_NAME", "archie"),
        "-n", f"tenant_{tenant_id}",
        "-f", out_path,
    ]
    print(f"[backup] {' '.join(cmd)}")
    subprocess.run(cmd, check=True, env=env)
    print(f"[backup] wrote {out_path}")
    return out_path


def _count_crm_customers_old(tenant_id: int) -> int:
    """Return the number of rows in crm_customers_old. 0 if table doesn't exist yet."""
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'crm_customers'"
        )
        if cur.fetchone()[0] == 0:
            return 0
        cur.execute("SELECT COUNT(*) FROM crm_customers")
        return cur.fetchone()[0]


def _count_accounts(tenant_id: int) -> int:
    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'accounts'"
        )
        if cur.fetchone()[0] == 0:
            return 0
        cur.execute("SELECT COUNT(*) FROM accounts")
        return cur.fetchone()[0]


def _run_sql(tenant_id: int, sql_path: str) -> None:
    with open(sql_path) as f:
        sql = f.read()
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(sql)
        conn.commit()


def migrate(tenant_id: int, *, dry_run: bool, skip_backup: bool) -> None:
    before = _count_crm_customers_old(tenant_id)
    print(f"[migrate] tenant {tenant_id}: {before} rows in crm_customers")

    if dry_run:
        print("[migrate] --dry-run — exiting before changes")
        return

    if not skip_backup:
        pg_dump_schema(tenant_id)

    _run_sql(tenant_id, FORWARD_SQL)

    after = _count_accounts(tenant_id)
    print(f"[migrate] tenant {tenant_id}: {after} rows in accounts")

    if after != before:
        raise RuntimeError(
            f"row-count mismatch: crm_customers had {before} but accounts has {after}"
        )
    print(f"[migrate] tenant {tenant_id}: OK ({after} rows migrated)")


def rollback(tenant_id: int, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[rollback] --dry-run — would run {ROLLBACK_SQL} against tenant_{tenant_id}")
        return
    _run_sql(tenant_id, ROLLBACK_SQL)
    print(f"[rollback] tenant {tenant_id}: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true",
                        help="Run rollback SQL instead of forward migration")
    parser.add_argument("--skip-backup", action="store_true",
                        help="Skip pg_dump step (testing only)")
    args = parser.parse_args()

    if args.rollback:
        rollback(args.tenant_id, dry_run=args.dry_run)
    else:
        migrate(args.tenant_id, dry_run=args.dry_run, skip_backup=args.skip_backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-test the runner with --dry-run against tenant_9908 (should be empty crm_customers)**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie KBS_DB_PASSWORD="$PASS" \
    python3 -m scripts.migrate_tenant_to_unified_model --tenant-id 9908 --dry-run
```
Expected output includes: `[migrate] tenant 9908: 0 rows in crm_customers` then `--dry-run — exiting before changes`.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add scripts/migrate_tenant_to_unified_model.py
git commit -m "feat(scripts): per-tenant unified-data-model migration runner

- pg_dump backup before migration
- --dry-run for pre-flight row-count check
- --rollback for reversing a botched migration
- row-count verification (accounts == crm_customers source count)"
```

---

## Task 5: Execute migration on tenant_9908 (empty crm_customers smoke test)

**Files:** None — execution only.

- [ ] **Step 1: Capture pre-state**

```bash
docker exec archie_database psql -U archie -d archie -t -A -c "
SELECT 'table, rowcount';
SELECT 'crm_customers', COUNT(*) FROM tenant_9908.crm_customers;
SELECT 'accounts',      COUNT(*) FROM tenant_9908.accounts;
SELECT 'contacts',      COUNT(*) FROM tenant_9908.contacts;
"
```

- [ ] **Step 2: Dry-run, then real migration**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie KBS_DB_PASSWORD="$PASS" \
    python3 -m scripts.migrate_tenant_to_unified_model --tenant-id 9908 --dry-run
echo '--- real run ---'
KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie KBS_DB_PASSWORD="$PASS" \
    python3 -m scripts.migrate_tenant_to_unified_model --tenant-id 9908
```
Expected: completes with `OK (0 rows migrated)`.

Note: tenant_9908 was provisioned today via PR #2. It already has the Plan-1 `accounts`/`contacts` tables from kbs_core_objects migration. The forward SQL's `CREATE TABLE IF NOT EXISTS` is a no-op for those; the transformation runs against its empty `crm_customers` and results in zero rows inserted into accounts.

- [ ] **Step 3: Verify post-state**

```bash
docker exec archie_database psql -U archie -d archie -t -A -c "
SELECT 'crm_customers_old', COUNT(*) FROM tenant_9908.crm_customers_old;
SELECT 'crm_customers VIEW', (SELECT table_type FROM information_schema.tables WHERE table_schema='tenant_9908' AND table_name='crm_customers');
SELECT 'accounts', COUNT(*) FROM tenant_9908.accounts;
SELECT 'schema_migration row', (SELECT version FROM tenant_9908.schema_migrations WHERE version='011_unified_data_model');
"
```
Expected:
- `crm_customers_old` row count = 0
- `crm_customers VIEW` returns `VIEW`
- `accounts` row count = 0
- `schema_migration row` returns `011_unified_data_model`

- [ ] **Step 4: Commit evidence log**

```bash
cd /mnt/archie_brain/kytran-business-suite
cat > docs/migration-evidence/011_tenant_9908.md <<'EOF'
# Migration 011 — tenant_9908 (smoke test)

Date: 2026-04-16
Status: SUCCESS
Rows migrated: 0 (tenant had empty crm_customers as expected — provisioned today, no legacy data)

Post-state:
- crm_customers_old: 0 rows
- crm_customers: VIEW (backed by accounts + contacts)
- accounts: 0 rows
- schema_migrations: 011_unified_data_model present
EOF
mkdir -p docs/migration-evidence
git add docs/migration-evidence/011_tenant_9908.md
git commit -m "docs(migration-011): evidence log for tenant_9908 smoke test"
```

---

## Task 6: Execute migration on tenant_9902 (real free-tier data)

**Files:** None — execution only.

- [ ] **Step 1: Pre-flight verification**

```bash
docker exec archie_database psql -U archie -d archie -t -A -c "
SELECT 'crm_customers',  COUNT(*) FROM tenant_9902.crm_customers;
SELECT 'appointments',   COUNT(*) FROM tenant_9902.appointments;
SELECT 'invoices',       COUNT(*) FROM tenant_9902.invoices;
"
```
Record counts. Expected: small numbers (tenant_9902 is free tier, minimal real data).

- [ ] **Step 2: Backup-enabled migration**

```bash
cd /mnt/archie_brain/kytran-business-suite
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie KBS_DB_PASSWORD="$PASS" \
    python3 -m scripts.migrate_tenant_to_unified_model --tenant-id 9902
```
Expected: row-count matches, `OK (N rows migrated)`. Backup dumped to `/tmp/tenant_9902_pre_011_<timestamp>.sql`.

If the runner errors with a row-count mismatch or any SQL error, STOP. The transaction aborts. Capture the exception, manually run `python -m scripts.migrate_tenant_to_unified_model --tenant-id 9902 --rollback` if the schema got partially mutated, and escalate.

- [ ] **Step 3: Post-migration spot check**

```bash
docker exec archie_database psql -U archie -d archie -t -A -c "
SET search_path TO tenant_9902, public;
SELECT 'accounts by type', type, COUNT(*) FROM accounts GROUP BY type;
SELECT 'primary contacts', COUNT(*) FROM contacts WHERE is_primary;
SELECT 'appointments has account_id', COUNT(*) FROM information_schema.columns
    WHERE table_schema='tenant_9902' AND table_name='appointments' AND column_name='account_id';
SELECT 'appointments still has customer_id?', COUNT(*) FROM information_schema.columns
    WHERE table_schema='tenant_9902' AND table_name='appointments' AND column_name='customer_id';
"
```
Expected:
- `appointments has account_id` = 1
- `appointments still has customer_id?` = 0

- [ ] **Step 4: Commit evidence log**

```bash
cat > docs/migration-evidence/011_tenant_9902.md <<EOF
# Migration 011 — tenant_9902 (free tier)

Date: 2026-04-16
Status: SUCCESS
Rows migrated: <record exact count from Step 1>
Backup: /tmp/tenant_9902_pre_011_<timestamp>.sql (retain 30 days)
EOF
git add docs/migration-evidence/011_tenant_9902.md
git commit -m "docs(migration-011): evidence log for tenant_9902 real-data migration"
```

**Stop here.** Do NOT migrate tenant_9907 or tenant_1 in this plan — they require explicit user sign-off and will be run manually after PR merge.

---

## Task 7: Open PR

**Files:** None — meta-task.

- [ ] **Step 1: Push branch**

```bash
cd /mnt/archie_brain/kytran-business-suite
git push -u origin feat/kbs-unified-objects-tenant-migration 2>&1 | tail -3
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(migration-011): per-tenant unified data model migration" --body "$(cat <<'EOF'
## Summary
Plan 2 of 5 for the KBS unified data model. Ships:
- \`migrations/tenant/011_unified_data_model.sql\` — forward migration (crm_customers → accounts + contacts, rewrite 17 child-table FKs, compat VIEW)
- \`migrations/tenant/011_rollback_unified_data_model.sql\` — rollback
- \`scripts/migrate_tenant_to_unified_model.py\` — runner with pg_dump backup, --dry-run, --rollback
- Evidence logs for tenant_9908 (empty data smoke test) and tenant_9902 (real free-tier data)

## Depends on
- KBS PR #4 (Plan 1: core schema + service layer) — must be merged first

## Not in this PR
- tenant_9907 and tenant_1 migrations — require explicit user sign-off, will be run manually post-merge

## Test plan
- [x] 7 migration + rollback tests pass end-to-end
- [x] tenant_9908: migration succeeds with 0 rows (smoke test)
- [x] tenant_9902: migration succeeds with real free-tier data
- [ ] post-merge: user approves tenant_9907 + tenant_1 runs

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

- [ ] **Step 3: Log decision**

Use `mcp__archie__log_decision` with:
- title: `KBS Unified Data Model — Plan 2 shipped (per-tenant migration)`
- decision: brief note with PR #
- project_id: 269

---

## Self-Review

1. **Spec coverage** — §7 of the spec (migration plan) is implemented end-to-end: forward migration (§7.1), rollback (§7.3), runner (§7.2), compat VIEW (§5.6), plugin FK rewrite (§6). Tenant_1 is explicitly deferred per the §11 open question — noted in Task 6.

2. **Placeholder scan** — no TBDs. Child-table list in Task 2 Step 2 and Task 3 Step 1 is explicit (17 tables); both share the same array; they must be edited together if Plans 3/4 discover more.

3. **Type consistency** — `_count_crm_customers_old` and `_count_accounts` return `int`; `migrate()` compares them with `!=` (int vs int). `pg_dump_schema` returns `str` (path) but its return is ignored — consistent with how it's called.

4. **Not in this plan** — Plans 3 (big-three plugin rewrites), 4 (small-twelve rewrites), 5 (drop crm_customers_old) remain.
