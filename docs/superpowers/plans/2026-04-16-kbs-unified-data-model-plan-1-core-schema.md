# KBS Unified Data Model — Plan 1: Core Schema + Service Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the `accounts`, `contacts`, `leads`, `opportunities` tables plus a service-layer API (`core/objects.py`) into KBS. New tenants get the tables automatically. No existing plugins change yet — migration of existing tenants and plugin rewrites happen in Plans 2–4.

**Architecture:** New plugin `kbs_core_objects` owns the DDL (via its own migration). `provision_tenant_schema()` already runs every plugin's migrations — so the new plugin gets picked up automatically. A new `core/objects.py` service module is the ONLY way plugins read/write these objects (plugin code in later plans). Lead/Opportunity methods enforce tier at the service layer.

**Tech Stack:** Python 3.12, Flask, psycopg2, PostgreSQL 16, pytest.

**Repo:** `/mnt/archie_brain/kytran-business-suite` (separate repo from ARCHIE platform).

**Target branch:** `feat/kbs-unified-objects-core`

---

## File Structure

**Create:**
- `plugins/kbs_core_objects/__init__.py` — empty, plugin package marker
- `plugins/kbs_core_objects/manifest.json` — plugin metadata, no dependencies (every other plugin will later depend on this)
- `plugins/kbs_core_objects/migrations/001_unified_objects.sql` — DDL for all four tables + triggers + indexes
- `core/objects.py` — service layer (~250 lines, single file, one responsibility: CRUD for core objects)
- `tests/test_core/test_objects.py` — unit tests for service layer
- `tests/test_plugins/test_kbs_core_objects_migration.py` — tests that the plugin migration runs cleanly on a fresh tenant schema

**Modify:** None in this plan. `core/database.py` already runs every plugin's migrations via `run_plugin_migrations()` (shipped in PR #2 this session).

---

## Task 1: Create plugin skeleton

**Files:**
- Create: `plugins/kbs_core_objects/__init__.py`
- Create: `plugins/kbs_core_objects/manifest.json`

- [ ] **Step 1: Create empty package marker**

`plugins/kbs_core_objects/__init__.py`:
```python
```

(Empty file. Plugin loader reads `manifest.json`, no Python init required.)

- [ ] **Step 2: Create manifest**

`plugins/kbs_core_objects/manifest.json`:
```json
{
    "slug": "kbs_core_objects",
    "name": "Core Objects (Accounts, Contacts, Leads, Opportunities)",
    "version": "1.0.0",
    "category": "core",
    "tier_required": "free",
    "dependencies": [],
    "description": "Shared data model for Accounts, Contacts, Leads, and Opportunities. Every business plugin depends on this.",
    "routes": false
}
```

- [ ] **Step 3: Run plugin-loader validator to confirm manifest parses**

Run from the KBS repo root:
```bash
docker exec kbs_app python -c "
from core.plugin_loader import discover_manifests, validate_manifest
ms = discover_manifests('/app/plugins')
m = next(x for x in ms if x['slug'] == 'kbs_core_objects')
validate_manifest(m)
print('manifest OK:', m['slug'], m['version'])
"
```
Expected output: `manifest OK: kbs_core_objects 1.0.0`

Note: the file needs to be copied into the container since `kbs_app` doesn't bind-mount the repo. Easiest path: rebuild the container after committing (see Task 9 for rebuild step). For now, run the validator with a host mount:
```bash
docker run --rm -v /mnt/archie_brain/kytran-business-suite:/app:ro -w /app python:3.12-slim \
    sh -c "pip install -q --disable-pip-version-check && python -c \"
import sys; sys.path.insert(0, '.')
import json
with open('plugins/kbs_core_objects/manifest.json') as f: m = json.load(f)
required = {'slug','name','version','category','tier_required','dependencies'}
missing = required - set(m.keys())
assert not missing, f'missing: {missing}'
print('manifest OK:', m['slug'], m['version'])
\""
```
Expected: `manifest OK: kbs_core_objects 1.0.0`

- [ ] **Step 4: Commit**

```bash
git add plugins/kbs_core_objects/__init__.py plugins/kbs_core_objects/manifest.json
git commit -m "feat(kbs_core_objects): plugin skeleton and manifest"
```

---

## Task 2: Write failing test for the plugin migration SQL

**Files:**
- Create: `tests/test_plugins/test_kbs_core_objects_migration.py`

- [ ] **Step 1: Ensure test directory exists**

```bash
mkdir -p tests/test_plugins
touch tests/test_plugins/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/test_plugins/test_kbs_core_objects_migration.py`:
```python
"""
Tests for plugins/kbs_core_objects/migrations/001_unified_objects.sql.

Each test runs the migration against a throwaway tenant_9<random> schema
on the ARCHIE dev DB, then cleans up.
"""

import os
import random

import pytest

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    set_tenant_search_path,
)


@pytest.fixture
def throwaway_tenant_id():
    tid = 90000 + random.randint(1, 9000)
    drop_tenant_schema(tid)  # in case leftover
    create_tenant_schema(tid)
    yield tid
    drop_tenant_schema(tid)


def _run_migration(tenant_id):
    migration = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "plugins", "kbs_core_objects", "migrations", "001_unified_objects.sql",
    )
    with open(migration) as f:
        sql = f.read()
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(sql)
        conn.commit()


def test_migration_creates_four_core_tables(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    schema = f"tenant_{throwaway_tenant_id}"
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
            (schema,),
        )
        tables = [r[0] for r in cur.fetchall()]
    for name in ("accounts", "contacts", "leads", "opportunities"):
        assert name in tables, f"{name} missing from {schema}: {tables}"


def test_migration_is_idempotent(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    _run_migration(throwaway_tenant_id)  # must not raise
    # Still exactly 4 rows for the tables we created
    schema = f"tenant_{throwaway_tenant_id}"
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.tables
             WHERE table_schema = %s
               AND table_name IN ('accounts','contacts','leads','opportunities')
            """,
            (schema,),
        )
        assert cur.fetchone()[0] == 4


def test_accounts_type_check_rejects_bad_value(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, throwaway_tenant_id)
        with pytest.raises(Exception):
            cur.execute(
                "INSERT INTO accounts (type, name) VALUES (%s, %s)",
                ("organisation", "Bad"),
            )


def test_contacts_require_account_id(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, throwaway_tenant_id)
        with pytest.raises(Exception):
            cur.execute(
                "INSERT INTO contacts (first_name, last_name) VALUES (%s, %s)",
                ("No", "Account"),
            )


def test_only_one_primary_contact_per_account(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, throwaway_tenant_id)
        cur.execute(
            "INSERT INTO accounts (type, name) VALUES ('company', 'Acme') RETURNING id"
        )
        acc_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO contacts (account_id, first_name, is_primary) VALUES (%s, 'Joe', TRUE)",
            (acc_id,),
        )
        with pytest.raises(Exception):
            cur.execute(
                "INSERT INTO contacts (account_id, first_name, is_primary) VALUES (%s, 'Sara', TRUE)",
                (acc_id,),
            )


def test_updated_at_trigger_fires_on_account_update(throwaway_tenant_id):
    _run_migration(throwaway_tenant_id)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, throwaway_tenant_id)
        cur.execute(
            "INSERT INTO accounts (type, name) VALUES ('company', 'Foo') RETURNING id, updated_at"
        )
        acc_id, initial_ts = cur.fetchone()
        conn.commit()

        # small sleep not needed — postgres NOW() advances per statement
        cur.execute("UPDATE accounts SET name = 'Bar' WHERE id = %s", (acc_id,))
        conn.commit()

        cur.execute("SELECT updated_at FROM accounts WHERE id = %s", (acc_id,))
        new_ts = cur.fetchone()[0]
    assert new_ts > initial_ts, "updated_at trigger did not fire"
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_plugins/test_kbs_core_objects_migration.py -x -q --no-header
```
Expected: `FAIL` — `FileNotFoundError` or similar (migration file does not yet exist).

- [ ] **Step 4: Commit**

```bash
git add tests/test_plugins/__init__.py tests/test_plugins/test_kbs_core_objects_migration.py
git commit -m "test(kbs_core_objects): migration-level tests (red)"
```

---

## Task 3: Write the migration SQL to make tests pass

**Files:**
- Create: `plugins/kbs_core_objects/migrations/001_unified_objects.sql`

- [ ] **Step 1: Create migrations directory**

```bash
mkdir -p plugins/kbs_core_objects/migrations
```

- [ ] **Step 2: Write the migration SQL**

`plugins/kbs_core_objects/migrations/001_unified_objects.sql`:
```sql
-- KBS Unified Data Model — core tables (Accounts, Contacts, Leads, Opportunities)
-- Runs inside a tenant_{id} schema via set_tenant_search_path() before execution.

-- Prereq: pg_trgm must be installed at the DB level (one-time, not per-tenant).
-- Host ops runs: CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- accounts
-- =============================================================================
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

CREATE INDEX IF NOT EXISTS idx_accounts_type_status ON accounts(type, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_accounts_owner       ON accounts(owner_user_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_accounts_email       ON accounts(LOWER(email))  WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_accounts_name_trgm   ON accounts USING gin (name gin_trgm_ops);

-- =============================================================================
-- contacts
-- =============================================================================
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

CREATE INDEX IF NOT EXISTS idx_contacts_account    ON contacts(account_id)   WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_email      ON contacts(LOWER(email)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_name_trgm  ON contacts USING gin (full_name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_primary_contact_per_account
    ON contacts(account_id) WHERE is_primary = TRUE AND deleted_at IS NULL;

-- =============================================================================
-- leads  (visible to business+ tier — enforced at the service layer)
-- =============================================================================
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

CREATE INDEX IF NOT EXISTS idx_leads_status   ON leads(status)           WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_leads_assigned ON leads(assigned_user_id) WHERE deleted_at IS NULL;

-- =============================================================================
-- opportunities  (enterprise tier — enforced at the service layer)
-- =============================================================================
CREATE TABLE IF NOT EXISTS opportunities (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id     INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    name           VARCHAR(255) NOT NULL,
    amount         NUMERIC(12,2),
    currency       VARCHAR(3) DEFAULT 'CAD',
    stage          VARCHAR(30) NOT NULL DEFAULT 'prospecting'
                       CHECK (stage IN ('prospecting','qualification','proposal',
                                        'negotiation','closed_won','closed_lost')),
    probability    SMALLINT CHECK (probability BETWEEN 0 AND 100),
    close_date     DATE,
    closed_at      TIMESTAMPTZ,
    owner_user_id  INTEGER,
    source         VARCHAR(50),
    description    TEXT,
    tags           JSONB DEFAULT '[]',
    custom_fields  JSONB DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    deleted_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_opportunities_account ON opportunities(account_id)    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_opportunities_stage   ON opportunities(stage)         WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_opportunities_owner   ON opportunities(owner_user_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_opportunities_close   ON opportunities(close_date)
    WHERE deleted_at IS NULL AND stage NOT IN ('closed_won','closed_lost');

-- =============================================================================
-- shared updated_at trigger
-- =============================================================================
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_accounts_updated      ON accounts;
DROP TRIGGER IF EXISTS trg_contacts_updated      ON contacts;
DROP TRIGGER IF EXISTS trg_leads_updated         ON leads;
DROP TRIGGER IF EXISTS trg_opportunities_updated ON opportunities;

CREATE TRIGGER trg_accounts_updated      BEFORE UPDATE ON accounts      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_contacts_updated      BEFORE UPDATE ON contacts      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_leads_updated         BEFORE UPDATE ON leads         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_opportunities_updated BEFORE UPDATE ON opportunities FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

- [ ] **Step 3: Install pg_trgm extension (one-time, per-DB operation)**

```bash
docker exec archie_database psql -U archie -d archie -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```
Expected: `CREATE EXTENSION` (or `NOTICE: extension "pg_trgm" already exists`).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_plugins/test_kbs_core_objects_migration.py -x -q --no-header
```
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add plugins/kbs_core_objects/migrations/001_unified_objects.sql
git commit -m "feat(kbs_core_objects): unified data model migration SQL

Creates accounts, contacts, leads, opportunities with full index coverage,
updated_at triggers, and tier-agnostic schema (gating enforced at service layer)."
```

---

## Task 4: Write failing tests for `core/objects.py` service — Account CRUD

**Files:**
- Create: `tests/test_core/test_objects.py`

- [ ] **Step 1: Write the failing test module**

`tests/test_core/test_objects.py`:
```python
"""Tests for core.objects service layer."""

import random

import pytest

from core import objects
from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    set_tenant_search_path,
)

# Load migration SQL once per module
import os
MIGRATION_SQL = open(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "plugins", "kbs_core_objects", "migrations", "001_unified_objects.sql",
    )
).read()


@pytest.fixture
def tenant_id():
    tid = 90000 + random.randint(1, 9000)
    drop_tenant_schema(tid)
    create_tenant_schema(tid)
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tid)
        cur.execute(MIGRATION_SQL)
        conn.commit()
    # Seed a tenant row with tier='free' so tier checks resolve
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "INSERT INTO tenants (id, name, slug, tier) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET tier = EXCLUDED.tier",
            (tid, f"test-{tid}", f"test-{tid}", "free"),
        )
        conn.commit()
    yield tid
    with get_db_cursor() as (conn, cur):
        cur.execute("DELETE FROM tenants WHERE id = %s", (tid,))
        conn.commit()
    drop_tenant_schema(tid)


def test_create_company_account_returns_id(tenant_id):
    acc_id = objects.create_company_account(tenant_id, name="Acme Plumbing", phone="555-0100")
    assert isinstance(acc_id, int) and acc_id > 0


def test_get_account_returns_dict_with_expected_fields(tenant_id):
    acc_id = objects.create_company_account(tenant_id, name="Acme", email="x@y.com")
    acc = objects.get_account(tenant_id, acc_id)
    assert acc is not None
    assert acc["id"] == acc_id
    assert acc["type"] == "company"
    assert acc["name"] == "Acme"
    assert acc["email"] == "x@y.com"


def test_get_account_soft_deleted_returns_none(tenant_id):
    acc_id = objects.create_company_account(tenant_id, name="Gone")
    objects.soft_delete_account(tenant_id, acc_id, user_id=1)
    assert objects.get_account(tenant_id, acc_id) is None


def test_create_person_account_also_creates_primary_contact(tenant_id):
    acc_id = objects.create_person_account(
        tenant_id, first_name="Jane", last_name="Doe", email="jane@x.com"
    )
    acc = objects.get_account(tenant_id, acc_id)
    assert acc["type"] == "person"
    assert acc["name"] == "Jane Doe"

    contact = objects.get_primary_contact(tenant_id, acc_id)
    assert contact is not None
    assert contact["first_name"] == "Jane"
    assert contact["last_name"] == "Doe"
    assert contact["is_primary"] is True


def test_find_accounts_filters_by_type(tenant_id):
    objects.create_company_account(tenant_id, name="Acme Co")
    objects.create_person_account(tenant_id, first_name="Jane", last_name="Doe")
    people = objects.find_accounts(tenant_id, query="", type="person")
    assert len(people) == 1 and people[0]["name"] == "Jane Doe"
    companies = objects.find_accounts(tenant_id, query="", type="company")
    assert len(companies) == 1 and companies[0]["name"] == "Acme Co"


# --- Lead tier gating ---
def test_free_tenant_cannot_create_lead(tenant_id):
    with pytest.raises(PermissionError):
        objects.create_lead(tenant_id, first_name="Bob", email="bob@x.com")


def test_business_tenant_can_create_lead(tenant_id):
    # bump tier to business
    with get_db_cursor() as (conn, cur):
        cur.execute("UPDATE tenants SET tier = 'business' WHERE id = %s", (tenant_id,))
        conn.commit()
    lead_id = objects.create_lead(tenant_id, first_name="Bob", email="bob@x.com")
    assert lead_id > 0


# --- Opportunity tier gating ---
def test_business_tenant_cannot_create_opportunity(tenant_id):
    with get_db_cursor() as (conn, cur):
        cur.execute("UPDATE tenants SET tier = 'business' WHERE id = %s", (tenant_id,))
        conn.commit()
    acc_id = objects.create_company_account(tenant_id, name="Acme")
    with pytest.raises(PermissionError):
        objects.create_opportunity(tenant_id, account_id=acc_id, name="Deal", amount=1000)


def test_enterprise_tenant_can_create_opportunity(tenant_id):
    with get_db_cursor() as (conn, cur):
        cur.execute("UPDATE tenants SET tier = 'enterprise' WHERE id = %s", (tenant_id,))
        conn.commit()
    acc_id = objects.create_company_account(tenant_id, name="Acme")
    opp_id = objects.create_opportunity(tenant_id, account_id=acc_id, name="Deal", amount=1000)
    assert opp_id > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_core/test_objects.py -x -q --no-header
```
Expected: `ModuleNotFoundError: No module named 'core.objects'`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_core/test_objects.py
git commit -m "test(core.objects): service layer tests (red)"
```

---

## Task 5: Implement `core/objects.py` Account CRUD

**Files:**
- Create: `core/objects.py`

- [ ] **Step 1: Write the module**

`core/objects.py`:
```python
"""Service layer for KBS unified data model — Accounts, Contacts, Leads, Opportunities.

All plugins MUST go through this module. Direct SQL against the core tables
from plugin code is forbidden (caught in tests in Plans 3-4).

Tier gating is enforced here for Lead (business+) and Opportunity (enterprise)
operations. Account and Contact are free-tier.
"""

from typing import Any

from psycopg2.extras import Json, RealDictCursor

from core.database import get_db_cursor, set_tenant_search_path


LEAD_MIN_TIER = ("business", "enterprise")
OPPORTUNITY_MIN_TIER = ("enterprise",)


def _get_tenant_tier(tenant_id: int) -> str:
    """Read tenants.tier from the public schema — never cached; single call per op."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT tier FROM tenants WHERE id = %s", (tenant_id,))
        row = cur.fetchone()
    if not row:
        raise LookupError(f"tenant {tenant_id} not found")
    return row[0]


def _require_tier(tenant_id: int, allowed: tuple[str, ...]) -> None:
    tier = _get_tenant_tier(tenant_id)
    if tier not in allowed:
        raise PermissionError(
            f"tenant {tenant_id} tier={tier!r} not allowed here (need one of {allowed})"
        )


def _with_tenant(cur, tenant_id: int) -> None:
    set_tenant_search_path(cur, tenant_id)


# =============================================================================
# Accounts
# =============================================================================

def create_company_account(
    tenant_id: int,
    name: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    industry: str | None = None,
    owner_user_id: int | None = None,
    **extra: Any,
) -> int:
    """Create a type='company' Account. Returns new id."""
    return _insert_account(
        tenant_id,
        type_="company",
        name=name,
        email=email,
        phone=phone,
        website=website,
        industry=industry,
        owner_user_id=owner_user_id,
        **extra,
    )


def create_person_account(
    tenant_id: int,
    first_name: str,
    last_name: str | None = None,
    *,
    email: str | None = None,
    phone: str | None = None,
    owner_user_id: int | None = None,
    **extra: Any,
) -> int:
    """Create a type='person' Account AND its primary Contact atomically.
    Returns the Account id.
    """
    full_name = " ".join(filter(None, [first_name, last_name])).strip()
    with get_db_cursor() as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO accounts (type, name, email, phone, owner_user_id)
            VALUES ('person', %s, %s, %s, %s)
            RETURNING id
            """,
            (full_name, email, phone, owner_user_id),
        )
        acc_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO contacts
                (account_id, first_name, last_name, email, phone, is_primary)
            VALUES (%s, %s, %s, %s, %s, TRUE)
            """,
            (acc_id, first_name, last_name, email, phone),
        )
        conn.commit()
    return acc_id


def _insert_account(tenant_id: int, *, type_: str, **fields: Any) -> int:
    cols = ["type"]
    vals = [type_]
    for k, v in fields.items():
        if v is None:
            continue
        cols.append(k)
        vals.append(Json(v) if isinstance(v, (dict, list)) else v)
    placeholders = ", ".join(["%s"] * len(vals))
    col_sql = ", ".join(cols)
    with get_db_cursor() as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            f"INSERT INTO accounts ({col_sql}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        acc_id = cur.fetchone()[0]
        conn.commit()
    return acc_id


def get_account(tenant_id: int, account_id: int) -> dict | None:
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            "SELECT * FROM accounts WHERE id = %s AND deleted_at IS NULL",
            (account_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def soft_delete_account(tenant_id: int, account_id: int, user_id: int) -> None:
    with get_db_cursor() as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            "UPDATE accounts SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL",
            (account_id,),
        )
        conn.commit()


def find_accounts(
    tenant_id: int,
    query: str = "",
    type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    sql = "SELECT * FROM accounts WHERE deleted_at IS NULL"
    params: list[Any] = []
    if query:
        sql += " AND name ILIKE %s"
        params.append(f"%{query}%")
    if type:
        sql += " AND type = %s"
        params.append(type)
    sql += " ORDER BY name LIMIT %s"
    params.append(limit)
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# =============================================================================
# Contacts
# =============================================================================

def get_primary_contact(tenant_id: int, account_id: int) -> dict | None:
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            """
            SELECT * FROM contacts
             WHERE account_id = %s AND is_primary = TRUE AND deleted_at IS NULL
             LIMIT 1
            """,
            (account_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


# =============================================================================
# Leads (business+)
# =============================================================================

def create_lead(
    tenant_id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    *,
    email: str | None = None,
    phone: str | None = None,
    company: str | None = None,
    source: str | None = None,
    **extra: Any,
) -> int:
    _require_tier(tenant_id, LEAD_MIN_TIER)
    with get_db_cursor() as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO leads (first_name, last_name, email, phone, company, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (first_name, last_name, email, phone, company, source),
        )
        lead_id = cur.fetchone()[0]
        conn.commit()
    return lead_id


# =============================================================================
# Opportunities (enterprise)
# =============================================================================

def create_opportunity(
    tenant_id: int,
    account_id: int,
    name: str,
    amount: float | None = None,
    *,
    contact_id: int | None = None,
    stage: str = "prospecting",
    probability: int | None = None,
    close_date: str | None = None,
    owner_user_id: int | None = None,
    **extra: Any,
) -> int:
    _require_tier(tenant_id, OPPORTUNITY_MIN_TIER)
    with get_db_cursor() as (conn, cur):
        _with_tenant(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO opportunities
                (account_id, contact_id, name, amount, stage, probability, close_date, owner_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (account_id, contact_id, name, amount, stage, probability, close_date, owner_user_id),
        )
        opp_id = cur.fetchone()[0]
        conn.commit()
    return opp_id
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
PASS=$(grep -E "^DB_PASSWORD=" /mnt/archie_brain/.env | head -1 | cut -d= -f2)
DB_PASSWORD="$PASS" KBS_DB_PASSWORD="$PASS" python3 -m pytest tests/test_core/test_objects.py -x -q --no-header
```
Expected: `9 passed`.

- [ ] **Step 3: Commit**

```bash
git add core/objects.py
git commit -m "feat(core.objects): service layer for Accounts, Contacts, Leads, Opportunities

- create_company_account / create_person_account (atomic with primary Contact)
- get_account / find_accounts / soft_delete_account
- get_primary_contact
- create_lead (business+) / create_opportunity (enterprise) — tier-gated at service layer"
```

---

## Task 6: Verify new tenant provisioning includes the new tables

**Files:**
- No code changes — this task proves the earlier PR #2 wiring still works end-to-end after adding `kbs_core_objects`.

- [ ] **Step 1: Drop a throwaway test tenant schema if it exists**

```bash
docker exec archie_database psql -U archie -d archie -c "DROP SCHEMA IF EXISTS tenant_90001 CASCADE;"
```

- [ ] **Step 2: Rebuild kbs_app so it picks up the new plugin**

```bash
cd /mnt/archie_brain/kytran-business-suite
docker rm -f kbs_app kbs_worker
docker compose -f docker-compose.yml -f docker-compose.hub.yml up -d --no-deps --build kytran-business-suite kbs-worker
sleep 6
docker ps --filter name=kbs_app --format '{{.Names}} {{.Status}}'
```
Expected: `kbs_app Up N seconds`.

- [ ] **Step 3: Provision a throwaway tenant via the real code path**

```bash
docker exec kbs_app python -c "
from core.database import provision_tenant_schema, get_db_cursor
provision_tenant_schema(90001)
with get_db_cursor(commit=False) as (conn, cur):
    cur.execute(\"\"\"SELECT COUNT(*) FROM information_schema.tables
                     WHERE table_schema='tenant_90001'
                       AND table_name IN ('accounts','contacts','leads','opportunities')\"\"\")
    print('core tables present:', cur.fetchone()[0])
"
```
Expected: `core tables present: 4`.

- [ ] **Step 4: Clean up the throwaway tenant**

```bash
docker exec archie_database psql -U archie -d archie -c "DROP SCHEMA IF EXISTS tenant_90001 CASCADE;"
```

- [ ] **Step 5: Commit (nothing to add — if nothing changed, skip this step)**

No commit needed if the verification passes; the Plan 1 scope is already in the tree.

---

## Task 7: Open PR

**Files:**
- None — this is a meta-task.

- [ ] **Step 1: Push the branch**

```bash
cd /mnt/archie_brain/kytran-business-suite
git push -u origin feat/kbs-unified-objects-core
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(kbs_core_objects): unified data model core schema + service layer" --body "$(cat <<'EOF'
## Summary
- Introduces \`accounts\`, \`contacts\`, \`leads\`, \`opportunities\` as shared core tables in every \`tenant_{id}\` schema.
- New plugin \`kbs_core_objects\` owns the migration. \`provision_tenant_schema()\` picks it up automatically.
- New \`core/objects.py\` service layer — tier-gated for Leads (business+) and Opportunities (enterprise).
- **No existing plugin changes in this PR** — migration of existing tenants and plugin rewrites land in Plans 2–4.

## Spec
\`docs/superpowers/specs/2026-04-16-kbs-unified-data-model-design.md\`

## Test plan
- [x] 6 migration-level tests pass (tables created, idempotent, CHECK constraints, primary-contact uniqueness, updated_at trigger)
- [x] 9 service-layer tests pass (CRUD, Person Account atomic creation, Lead/Opp tier gating)
- [x] End-to-end: throwaway tenant_90001 provisioned via \`provision_tenant_schema\`, all 4 core tables present
- [ ] After merge: verify tenant_9908 (or a fresh SSO signup) has the 4 new tables

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
Expected: a GitHub URL printed.

- [ ] **Step 3: Record the decision in Dev HQ**

Use `mcp__archie__log_decision` with:
- title: `KBS unified data model — Plan 1 shipped (core schema + service layer)`
- decision: brief note that PR X landed
- project_id: 269
- task_id: (relevant KBS overhaul task)

---

## Self-Review Notes

1. **Spec coverage** — every section of the spec that applies to Plan 1 has a task:
   - §5 DDL → Task 3
   - §5.5 triggers → Task 3 (tested in Task 2)
   - §8 service layer → Task 4 (tests) + Task 5 (impl)
   - §9.1 unit tests → Task 4
   - §9.2 migration tests → Task 2
   - §10 PR A → whole plan
   - §5.6 compat VIEW, §7 per-tenant migration, §6 plugin impact → **Plan 2/3/4** (explicitly out of scope for Plan 1)

2. **Placeholder scan** — no TBDs, no "similar to Task N"; every step has the literal code/command needed.

3. **Type consistency** — `create_company_account` signature in Task 5 matches invocations in Task 4 tests. `create_person_account` returns `int` (Account id) in both places. `get_primary_contact` returns `dict | None` in both. `create_lead` / `create_opportunity` raise `PermissionError` exactly — the tests assert the same exception type.

---

## What Plan 2 will cover

- Per-tenant migration script (`migrations/tenant/011_unified_data_model.sql`)
- Rollback script
- Migration runner CLI (`scripts/migrate_tenant_to_unified_model.py`)
- Compat VIEW `crm_customers`
- Verification on tenant_9902 (smallest, free tier)

Plan 3 will rewrite kbs_crm / kbs_invoicing / kbs_appointments to use the service layer.
Plan 4 will rewrite the remaining 12 plugins.
Plan 5 drops `crm_customers_old` after the 30-day compat window.
