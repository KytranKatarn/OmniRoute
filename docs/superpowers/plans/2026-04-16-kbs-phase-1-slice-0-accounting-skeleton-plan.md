# KBS Phase 1 — Slice S0: `kbs_accounting` Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `kbs_accounting` skeleton — chart-of-accounts + `post_entry()` double-entry service + minimal ledger viewer — so downstream slices (S1 crm, S2 invoicing, S3 contracts, S4 store) can emit ledger entries as they land.

**Architecture:** Plugin at `plugins/kbs_accounting/` follows the existing `kbs_crm` shape (manifest + `__init__.py` with `create_blueprint(manifest)` + `routes.py` + `service.py` + `migrations/` + `templates/` + `tests/`). Service layer owns `post_entry()` with double-entry invariant enforced (`sum(dr) == sum(cr)` per entry). Routes read entries for the UI; writes happen via `service.post_entry()` from other plugins (not via HTTP in S0). Uses `set_tenant_search_path()` per existing `core.database` pattern.

**Tech Stack:** Python 3.12, Flask, psycopg2, PostgreSQL (ARCHIE DB `archie`, `tenant_{id}` schema), Jinja2, vanilla JS (LCARS pattern), pytest, YAML for P.R.O.B.E. suite, Playwright for E2E.

**Spec:** `docs/superpowers/specs/2026-04-16-kbs-phase-1-tenant1-mvp-design.md`

---

## File Structure

### New files — KBS repo (`/mnt/archie_brain/kytran-business-suite/`)

| File | Purpose |
|------|---------|
| `plugins/kbs_accounting/manifest.json` | Plugin manifest (slug, tier, nav, permissions, emits, consumes) |
| `plugins/kbs_accounting/__init__.py` | `create_blueprint(manifest)` + event consumer registration |
| `plugins/kbs_accounting/routes.py` | `register_routes(bp)` + GET endpoints for UI |
| `plugins/kbs_accounting/service.py` | `post_entry`, `reverse_entry`, `list_entries`, `get_entry`, `get_chart_of_accounts` |
| `plugins/kbs_accounting/migrations/001_accounting_skeleton.sql` | chart_of_accounts + ledger_entries + ledger_lines tables + seed chart |
| `plugins/kbs_accounting/templates/accounting.html` | Ledger viewer page |
| `plugins/kbs_accounting/static/css/accounting.css` | LCARS tab + table styling |
| `plugins/kbs_accounting/static/js/accounting.js` | Entry detail modal (bm-overlay), data-action dispatcher |
| `plugins/kbs_accounting/static/css/.gitkeep` | Flask static-folder requires a dir |
| `plugins/kbs_accounting/static/js/.gitkeep` | same |
| `plugins/kbs_accounting/tests/__init__.py` | pytest package marker |
| `plugins/kbs_accounting/tests/test_service.py` | Unit tests: post_entry, reverse_entry, invariants, list/get |
| `plugins/kbs_accounting/tests/test_routes.py` | Integration tests: GET endpoints via Flask test client |

### New files — ARCHIE repo (`/mnt/archie_brain/`)

| File | Purpose |
|------|---------|
| `platform_v2/qa_suites/kbs-accounting.yaml` | P.R.O.B.E. suite YAML — page load + API GETs |
| `kytran-business-suite/scripts/e2e_accounting.py` | Playwright E2E happy-path script (lives in KBS repo under `scripts/`) |

### Modified files

| File | Change |
|------|--------|
| `kytran-business-suite/core/database.py` | Line 81-ish `run_plugin_migrations()` — confirm `kbs_accounting` migrations picked up. Likely no change needed (plugin loader already iterates `plugins/*/migrations/*.sql`). |

---

## Preflight

- [ ] **P0: Verify clean working tree + correct branch**

```bash
cd /mnt/archie_brain/kytran-business-suite
git status
git branch --show-current
```

Expected: clean tree. If dirty, stash or commit first. Then create the slice branch:

```bash
git checkout -b feat/slice-0-accounting-skeleton
git branch --show-current
```

Expected: `feat/slice-0-accounting-skeleton`

- [ ] **P1: Verify the spec is accessible**

```bash
ls -la /mnt/archie_brain/docs/superpowers/specs/2026-04-16-kbs-phase-1-tenant1-mvp-design.md
```

Expected: file exists, readable.

- [ ] **P2: Confirm DB access + existing test suite passes**

```bash
cd /mnt/archie_brain/kytran-business-suite
pytest tests/test_plugins/test_kbs_core_objects_migration.py -v
```

Expected: PASS. Establishes baseline; migration infra + tenant fixtures work.

- [ ] **P3: Note the push freeze**

This work lands **local only**. No `git push`. No `gh pr create`. Add a row in `~/.claude/projects/-mnt-archie-brain/memory/feedback_github-actions-minutes.md` inventory table after the final commit in this plan.

---

## Task 1: Plugin Scaffold (manifest + empty `__init__.py`)

**Files:**
- Create: `plugins/kbs_accounting/manifest.json`
- Create: `plugins/kbs_accounting/__init__.py`
- Create: `plugins/kbs_accounting/static/css/.gitkeep`
- Create: `plugins/kbs_accounting/static/js/.gitkeep`
- Create: `plugins/kbs_accounting/tests/__init__.py`

- [ ] **Step 1: Create manifest**

Write `plugins/kbs_accounting/manifest.json`:

```json
{
    "slug": "accounting",
    "name": "Accounting",
    "version": "0.1.0",
    "description": "Double-entry ledger + chart of accounts. Every money-moving event across KBS posts here.",
    "category": "finance",
    "tier_required": "business",
    "price_monthly": null,
    "icon": "book-open-check",
    "dependencies": ["kbs_core_objects"],
    "emits": ["ledger.entry_posted", "ledger.entry_reversed"],
    "consumes": [],
    "permissions": ["accounting.read", "accounting.write", "accounting.admin"],
    "nav": {"label": "Accounting", "icon": "book-open-check", "order": 60}
}
```

- [ ] **Step 2: Create minimal `__init__.py`**

Write `plugins/kbs_accounting/__init__.py`:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "accounting",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/accounting",
    )
    from plugins.kbs_accounting.routes import register_routes

    register_routes(bp)
    return bp
```

- [ ] **Step 3: Create empty static/tests scaffolding**

```bash
mkdir -p plugins/kbs_accounting/static/css plugins/kbs_accounting/static/js plugins/kbs_accounting/tests plugins/kbs_accounting/migrations plugins/kbs_accounting/templates
touch plugins/kbs_accounting/static/css/.gitkeep
touch plugins/kbs_accounting/static/js/.gitkeep
```

Write `plugins/kbs_accounting/tests/__init__.py` with an empty single line:

```python
# test package marker
```

- [ ] **Step 4: Commit scaffold**

```bash
git add plugins/kbs_accounting/manifest.json plugins/kbs_accounting/__init__.py plugins/kbs_accounting/static plugins/kbs_accounting/tests plugins/kbs_accounting/migrations plugins/kbs_accounting/templates
git commit -m "feat(kbs_accounting): scaffold plugin (S0 start)"
```

Note: the commit will fail referencing `routes.py` because `__init__.py` imports it. That's intentional — the next task creates routes.py. If the plugin loader runs at commit-time (pre-commit hook) and tries to import kbs_accounting, STOP this plan and first create an empty `routes.py` with `def register_routes(bp): pass` before committing.

---

## Task 2: Migration SQL (tables + seed chart of accounts)

**Files:**
- Create: `plugins/kbs_accounting/migrations/001_accounting_skeleton.sql`
- Test: `plugins/kbs_accounting/tests/test_migration.py`

- [ ] **Step 1: Write the failing test**

Write `plugins/kbs_accounting/tests/test_migration.py`:

```python
"""Migration test — tables + seed rows present after provisioning a fresh tenant schema."""

import pytest

from core.database import get_db_cursor, provision_tenant_schema, set_tenant_search_path


TEST_TENANT_ID = 99910  # dedicated to this test file; safe to drop


@pytest.fixture(scope="module", autouse=True)
def provisioned_tenant():
    # Provision + teardown via raw SQL DROP
    provision_tenant_schema(TEST_TENANT_ID)
    yield
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(f"DROP SCHEMA IF EXISTS tenant_{TEST_TENANT_ID} CASCADE")


def _q(sql: str, *params):
    with get_db_cursor(commit=False) as (_, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute(sql, params)
        return cur.fetchall()


def test_chart_of_accounts_table_exists():
    rows = _q(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = 'chart_of_accounts'",
        f"tenant_{TEST_TENANT_ID}",
    )
    assert len(rows) == 1


def test_ledger_entries_table_exists():
    rows = _q(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = 'ledger_entries'",
        f"tenant_{TEST_TENANT_ID}",
    )
    assert len(rows) == 1


def test_ledger_lines_table_exists():
    rows = _q(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = 'ledger_lines'",
        f"tenant_{TEST_TENANT_ID}",
    )
    assert len(rows) == 1


def test_chart_of_accounts_has_standard_seed():
    """After provisioning, the chart should include at least one account per top-level class."""
    rows = _q(
        "SELECT code, name, class FROM chart_of_accounts ORDER BY code"
    )
    codes = {r[0] for r in rows}
    assert {"1010_cash", "1210_accounts_receivable", "2110_accounts_payable",
            "3010_owner_equity", "4010_revenue", "5010_cost_of_goods_sold"}.issubset(codes), (
        f"Seed chart missing required accounts; got {sorted(codes)}"
    )


def test_ledger_lines_has_fk_to_entries():
    rows = _q(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema = %s AND table_name = 'ledger_lines' AND constraint_type = 'FOREIGN KEY'",
        f"tenant_{TEST_TENANT_ID}",
    )
    assert len(rows) >= 1, "ledger_lines should have a FK to ledger_entries"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/archie_brain/kytran-business-suite
pytest plugins/kbs_accounting/tests/test_migration.py -v
```

Expected: all 5 tests FAIL or ERROR (tables/seed don't exist yet).

- [ ] **Step 3: Write the migration SQL**

Write `plugins/kbs_accounting/migrations/001_accounting_skeleton.sql`:

```sql
-- KBS Accounting — skeleton tables (chart_of_accounts, ledger_entries, ledger_lines)
-- Runs inside a tenant_{id} schema via set_tenant_search_path() before execution.

-- =============================================================================
-- chart_of_accounts
-- =============================================================================
CREATE TABLE IF NOT EXISTS chart_of_accounts (
    code          VARCHAR(32) PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    class         VARCHAR(16) NOT NULL CHECK (class IN ('asset','liability','equity','revenue','expense')),
    parent_code   VARCHAR(32) REFERENCES chart_of_accounts(code),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    description   TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coa_class ON chart_of_accounts(class) WHERE is_active;

-- =============================================================================
-- ledger_entries (the "journal entry" — a logical grouping of balanced lines)
-- =============================================================================
CREATE TABLE IF NOT EXISTS ledger_entries (
    id                  SERIAL PRIMARY KEY,
    entry_date          DATE NOT NULL,
    description         TEXT NOT NULL,
    source_plugin       VARCHAR(64) NOT NULL,
    source_entity_type  VARCHAR(64) NOT NULL,
    source_entity_id    INTEGER NOT NULL,
    metadata            JSONB DEFAULT '{}',
    reversed_by_id      INTEGER REFERENCES ledger_entries(id),
    reverses_id         INTEGER REFERENCES ledger_entries(id),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by_user_id  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entries_date          ON ledger_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_entries_source        ON ledger_entries(source_plugin, source_entity_type, source_entity_id);
CREATE INDEX IF NOT EXISTS idx_entries_reverse_chain ON ledger_entries(reverses_id) WHERE reverses_id IS NOT NULL;

-- =============================================================================
-- ledger_lines (the individual Dr/Cr lines per entry; sum(dr) must equal sum(cr))
-- =============================================================================
CREATE TABLE IF NOT EXISTS ledger_lines (
    id          SERIAL PRIMARY KEY,
    entry_id    INTEGER NOT NULL REFERENCES ledger_entries(id) ON DELETE CASCADE,
    account     VARCHAR(32) NOT NULL REFERENCES chart_of_accounts(code),
    dr          NUMERIC(14,2) NOT NULL DEFAULT 0,
    cr          NUMERIC(14,2) NOT NULL DEFAULT 0,
    memo        TEXT,
    line_order  INTEGER NOT NULL DEFAULT 0,
    CHECK (dr >= 0 AND cr >= 0),
    CHECK (NOT (dr > 0 AND cr > 0))
);

CREATE INDEX IF NOT EXISTS idx_lines_entry   ON ledger_lines(entry_id);
CREATE INDEX IF NOT EXISTS idx_lines_account ON ledger_lines(account);

-- =============================================================================
-- Seed the standard chart of accounts (idempotent)
-- =============================================================================
INSERT INTO chart_of_accounts (code, name, class, description) VALUES
    -- 1xxx Assets
    ('1010_cash',                  'Cash',                  'asset',     'Operating bank account'),
    ('1020_stripe_balance',        'Stripe Balance',        'asset',     'Funds in Stripe awaiting payout'),
    ('1210_accounts_receivable',   'Accounts Receivable',   'asset',     'Invoices sent but not yet paid'),
    ('1400_inventory',             'Inventory',             'asset',     'Stock on hand'),
    -- 2xxx Liabilities
    ('2110_accounts_payable',      'Accounts Payable',      'liability', 'Bills owed to vendors'),
    ('2210_sales_tax_payable',     'Sales Tax Payable',     'liability', 'Tax collected pending remittance'),
    -- 3xxx Equity
    ('3010_owner_equity',          'Owner Equity',          'equity',    'Capital contributed by owner'),
    ('3020_retained_earnings',     'Retained Earnings',     'equity',    'Accumulated net income'),
    -- 4xxx Revenue
    ('4010_revenue',               'Revenue',               'revenue',   'Income from sales + services'),
    ('4020_refunds_and_returns',   'Refunds and Returns',   'revenue',   'Contra-revenue for refunded sales'),
    -- 5xxx Expenses
    ('5010_cost_of_goods_sold',    'Cost of Goods Sold',    'expense',   'Direct cost of sold goods'),
    ('5100_operating_expenses',    'Operating Expenses',    'expense',   'General opex'),
    ('5200_payment_processing',    'Payment Processing',    'expense',   'Stripe/processor fees')
ON CONFLICT (code) DO NOTHING;
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest plugins/kbs_accounting/tests/test_migration.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/kbs_accounting/migrations/001_accounting_skeleton.sql plugins/kbs_accounting/tests/test_migration.py
git commit -m "feat(kbs_accounting): skeleton migration — chart of accounts + ledger tables + seed"
```

---

## Task 3: Service — `post_entry()` core

**Files:**
- Create: `plugins/kbs_accounting/service.py`
- Test: `plugins/kbs_accounting/tests/test_service.py`

- [ ] **Step 1: Write the failing test for post_entry happy-path**

Write `plugins/kbs_accounting/tests/test_service.py`:

```python
"""Unit tests for kbs_accounting.service — 100% coverage target (money code)."""

from datetime import date
from decimal import Decimal

import pytest

from core.database import get_db_cursor, provision_tenant_schema, set_tenant_search_path


TEST_TENANT_ID = 99911  # dedicated to service tests


@pytest.fixture(scope="module", autouse=True)
def provisioned_tenant():
    provision_tenant_schema(TEST_TENANT_ID)
    yield
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(f"DROP SCHEMA IF EXISTS tenant_{TEST_TENANT_ID} CASCADE")


@pytest.fixture()
def clean_ledger():
    """Wipe ledger between tests so each test is hermetic."""
    with get_db_cursor(commit=True) as (_, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute("TRUNCATE ledger_lines, ledger_entries RESTART IDENTITY CASCADE")
    yield


def test_post_entry_happy_path(clean_ledger):
    from plugins.kbs_accounting.service import post_entry, get_entry

    entry_id = post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Test invoice paid",
        source_plugin="kbs_invoicing",
        source_entity_type="invoice",
        source_entity_id=42,
        lines=[
            {"account": "1010_cash", "dr": Decimal("100.00"), "cr": Decimal("0")},
            {"account": "1210_accounts_receivable", "dr": Decimal("0"), "cr": Decimal("100.00")},
        ],
        metadata={"stripe_charge_id": "ch_test_123"},
    )
    assert isinstance(entry_id, int) and entry_id > 0

    entry = get_entry(TEST_TENANT_ID, entry_id)
    assert entry["description"] == "Test invoice paid"
    assert entry["source_plugin"] == "kbs_invoicing"
    assert entry["source_entity_id"] == 42
    assert entry["metadata"]["stripe_charge_id"] == "ch_test_123"
    assert len(entry["lines"]) == 2
    assert sum(Decimal(str(line["dr"])) for line in entry["lines"]) == Decimal("100.00")
    assert sum(Decimal(str(line["cr"])) for line in entry["lines"]) == Decimal("100.00")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest plugins/kbs_accounting/tests/test_service.py::test_post_entry_happy_path -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'plugins.kbs_accounting.service'`.

- [ ] **Step 3: Write minimal service implementation**

Write `plugins/kbs_accounting/service.py`:

```python
"""Service layer for kbs_accounting — double-entry ledger.

Every money-moving event across KBS calls `post_entry()`. Lines are validated
for the double-entry invariant (sum(dr) == sum(cr)). Entries are tied back to
their source plugin + entity for audit.

All functions take `tenant_id` as the first argument (spec §Tenant context).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path


@dataclass(frozen=True)
class _Line:
    account: str
    dr: Decimal
    cr: Decimal


def _coerce_lines(raw: Iterable[dict]) -> list[_Line]:
    out: list[_Line] = []
    for row in raw:
        dr = Decimal(str(row.get("dr", 0) or 0))
        cr = Decimal(str(row.get("cr", 0) or 0))
        if dr < 0 or cr < 0:
            raise ValueError(f"dr/cr must be non-negative, got dr={dr} cr={cr}")
        if dr > 0 and cr > 0:
            raise ValueError("a single line cannot have both dr and cr non-zero")
        out.append(_Line(account=row["account"], dr=dr, cr=cr))
    return out


def _validate_balanced(lines: list[_Line]) -> None:
    if len(lines) < 2:
        raise ValueError("ledger entry must have at least 2 lines")
    dr_total = sum((l.dr for l in lines), Decimal("0"))
    cr_total = sum((l.cr for l in lines), Decimal("0"))
    if dr_total != cr_total:
        raise ValueError(
            f"unbalanced entry: sum(dr)={dr_total} != sum(cr)={cr_total}"
        )
    if dr_total == 0:
        raise ValueError("entry must have non-zero totals")


def post_entry(
    tenant_id: int,
    entry_date: date,
    description: str,
    source_plugin: str,
    source_entity_type: str,
    source_entity_id: int,
    lines: list[dict],
    metadata: dict | None = None,
    created_by_user_id: int | None = None,
) -> int:
    """Post a balanced ledger entry. Returns the new entry_id.

    Atomic: entry + all lines commit together or not at all.
    """
    coerced = _coerce_lines(lines)
    _validate_balanced(coerced)

    with get_db_cursor(commit=True) as (_, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO ledger_entries
              (entry_date, description, source_plugin, source_entity_type,
               source_entity_id, metadata, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (entry_date, description, source_plugin, source_entity_type,
             source_entity_id, Json(metadata or {}), created_by_user_id),
        )
        entry_id = cur.fetchone()[0]

        for order, line in enumerate(coerced):
            cur.execute(
                """
                INSERT INTO ledger_lines (entry_id, account, dr, cr, line_order)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (entry_id, line.account, line.dr, line.cr, order),
            )
    return entry_id


def get_entry(tenant_id: int, entry_id: int) -> dict[str, Any]:
    """Fetch a single entry with its lines."""
    with get_db_cursor(commit=False) as (_, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            SELECT id, entry_date, description, source_plugin, source_entity_type,
                   source_entity_id, metadata, reverses_id, reversed_by_id, created_at
            FROM ledger_entries WHERE id = %s
            """,
            (entry_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"entry {entry_id} not found in tenant {tenant_id}")
        entry = {
            "id": row[0],
            "entry_date": row[1].isoformat() if row[1] else None,
            "description": row[2],
            "source_plugin": row[3],
            "source_entity_type": row[4],
            "source_entity_id": row[5],
            "metadata": row[6] or {},
            "reverses_id": row[7],
            "reversed_by_id": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
        }
        cur.execute(
            """
            SELECT id, account, dr, cr, memo, line_order
            FROM ledger_lines WHERE entry_id = %s ORDER BY line_order, id
            """,
            (entry_id,),
        )
        entry["lines"] = [
            {
                "id": lr[0],
                "account": lr[1],
                "dr": str(lr[2]),
                "cr": str(lr[3]),
                "memo": lr[4],
                "line_order": lr[5],
            }
            for lr in cur.fetchall()
        ]
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest plugins/kbs_accounting/tests/test_service.py::test_post_entry_happy_path -v
```

Expected: PASS.

- [ ] **Step 5: Add failing tests for invariant violations**

Append to `plugins/kbs_accounting/tests/test_service.py`:

```python
def test_post_entry_unbalanced_raises(clean_ledger):
    from plugins.kbs_accounting.service import post_entry

    with pytest.raises(ValueError, match="unbalanced"):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, 16),
            description="bad entry",
            source_plugin="test",
            source_entity_type="test",
            source_entity_id=1,
            lines=[
                {"account": "1010_cash", "dr": "100.00", "cr": "0"},
                {"account": "1210_accounts_receivable", "dr": "0", "cr": "99.00"},
            ],
        )


def test_post_entry_single_line_raises(clean_ledger):
    from plugins.kbs_accounting.service import post_entry

    with pytest.raises(ValueError, match="at least 2 lines"):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, 16),
            description="bad",
            source_plugin="test",
            source_entity_type="test",
            source_entity_id=1,
            lines=[{"account": "1010_cash", "dr": "100.00", "cr": "0"}],
        )


def test_post_entry_both_dr_and_cr_on_line_raises(clean_ledger):
    from plugins.kbs_accounting.service import post_entry

    with pytest.raises(ValueError, match="both dr and cr"):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, 16),
            description="bad",
            source_plugin="test",
            source_entity_type="test",
            source_entity_id=1,
            lines=[
                {"account": "1010_cash", "dr": "100.00", "cr": "50.00"},
                {"account": "4010_revenue", "dr": "0", "cr": "50.00"},
            ],
        )


def test_post_entry_zero_totals_raises(clean_ledger):
    from plugins.kbs_accounting.service import post_entry

    with pytest.raises(ValueError, match="non-zero"):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, 16),
            description="zero",
            source_plugin="test",
            source_entity_type="test",
            source_entity_id=1,
            lines=[
                {"account": "1010_cash", "dr": "0", "cr": "0"},
                {"account": "4010_revenue", "dr": "0", "cr": "0"},
            ],
        )


def test_post_entry_rollback_on_bad_account(clean_ledger):
    """If a line references a non-existent account, the whole entry must roll back."""
    from plugins.kbs_accounting.service import post_entry

    with pytest.raises(Exception):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, 16),
            description="bad fk",
            source_plugin="test",
            source_entity_type="test",
            source_entity_id=1,
            lines=[
                {"account": "9999_nonexistent", "dr": "100.00", "cr": "0"},
                {"account": "4010_revenue", "dr": "0", "cr": "100.00"},
            ],
        )

    # Verify no entry and no lines leaked
    with get_db_cursor(commit=False) as (_, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute("SELECT COUNT(*) FROM ledger_entries")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM ledger_lines")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 6: Run all service tests**

```bash
pytest plugins/kbs_accounting/tests/test_service.py -v
```

Expected: all 5 tests PASS. If rollback test fails, the psycopg2 transaction scope in `get_db_cursor(commit=True)` may be committing per-statement; fix by wrapping the `for` loop inside a savepoint or converting the helper to a single BEGIN/COMMIT scope.

- [ ] **Step 7: Commit**

```bash
git add plugins/kbs_accounting/service.py plugins/kbs_accounting/tests/test_service.py
git commit -m "feat(kbs_accounting): post_entry with double-entry invariant + rollback-safety tests"
```

---

## Task 4: Service — `reverse_entry()`

**Files:**
- Modify: `plugins/kbs_accounting/service.py` (add `reverse_entry`)
- Modify: `plugins/kbs_accounting/tests/test_service.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `plugins/kbs_accounting/tests/test_service.py`:

```python
def test_reverse_entry_creates_mirror(clean_ledger):
    from plugins.kbs_accounting.service import post_entry, reverse_entry, get_entry

    original_id = post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Original",
        source_plugin="test",
        source_entity_type="invoice",
        source_entity_id=7,
        lines=[
            {"account": "1010_cash", "dr": "50.00", "cr": "0"},
            {"account": "4010_revenue", "dr": "0", "cr": "50.00"},
        ],
    )

    reversal_id = reverse_entry(TEST_TENANT_ID, original_id, reason="refund")

    # Mirror has the same totals, swapped dr/cr
    reversal = get_entry(TEST_TENANT_ID, reversal_id)
    assert reversal["reverses_id"] == original_id
    assert reversal["description"].lower().startswith("reversal")
    assert "refund" in reversal["description"].lower()
    assert len(reversal["lines"]) == 2
    # line 1: was cash dr 50 → now cash cr 50
    by_account = {l["account"]: l for l in reversal["lines"]}
    assert by_account["1010_cash"]["dr"] == "0.00"
    assert by_account["1010_cash"]["cr"] == "50.00"
    assert by_account["4010_revenue"]["dr"] == "50.00"
    assert by_account["4010_revenue"]["cr"] == "0.00"

    # Original is now marked as reversed
    original_after = get_entry(TEST_TENANT_ID, original_id)
    assert original_after["reversed_by_id"] == reversal_id


def test_reverse_entry_twice_raises(clean_ledger):
    from plugins.kbs_accounting.service import post_entry, reverse_entry

    entry_id = post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Original",
        source_plugin="test",
        source_entity_type="invoice",
        source_entity_id=8,
        lines=[
            {"account": "1010_cash", "dr": "25.00", "cr": "0"},
            {"account": "4010_revenue", "dr": "0", "cr": "25.00"},
        ],
    )
    reverse_entry(TEST_TENANT_ID, entry_id, reason="first")
    with pytest.raises(ValueError, match="already reversed"):
        reverse_entry(TEST_TENANT_ID, entry_id, reason="second")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugins/kbs_accounting/tests/test_service.py::test_reverse_entry_creates_mirror plugins/kbs_accounting/tests/test_service.py::test_reverse_entry_twice_raises -v
```

Expected: FAIL (`reverse_entry` not defined).

- [ ] **Step 3: Implement `reverse_entry`**

Append to `plugins/kbs_accounting/service.py`:

```python
def reverse_entry(tenant_id: int, entry_id: int, reason: str) -> int:
    """Create a mirror entry that reverses the original. Returns the new entry_id.

    The original entry's `reversed_by_id` is set to the new entry's id so reversals
    are idempotent and traceable.
    """
    original = get_entry(tenant_id, entry_id)
    if original["reversed_by_id"] is not None:
        raise ValueError(f"entry {entry_id} already reversed by {original['reversed_by_id']}")

    # Swap dr/cr on each line
    mirror_lines = [
        {"account": l["account"], "dr": l["cr"], "cr": l["dr"]}
        for l in original["lines"]
    ]

    with get_db_cursor(commit=True) as (_, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO ledger_entries
              (entry_date, description, source_plugin, source_entity_type,
               source_entity_id, metadata, reverses_id)
            VALUES (CURRENT_DATE, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                f"Reversal of entry {entry_id}: {reason}",
                original["source_plugin"],
                original["source_entity_type"],
                original["source_entity_id"],
                Json({"reverses_entry_id": entry_id, "reason": reason}),
                entry_id,
            ),
        )
        reversal_id = cur.fetchone()[0]
        for order, line in enumerate(mirror_lines):
            cur.execute(
                """
                INSERT INTO ledger_lines (entry_id, account, dr, cr, line_order)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (reversal_id, line["account"], line["dr"], line["cr"], order),
            )
        cur.execute(
            "UPDATE ledger_entries SET reversed_by_id = %s WHERE id = %s",
            (reversal_id, entry_id),
        )
    return reversal_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugins/kbs_accounting/tests/test_service.py -v
```

Expected: all service tests PASS (7 total so far).

- [ ] **Step 5: Commit**

```bash
git add plugins/kbs_accounting/service.py plugins/kbs_accounting/tests/test_service.py
git commit -m "feat(kbs_accounting): reverse_entry — mirror lines + idempotent reversal chain"
```

---

## Task 5: Service — `list_entries`, `get_chart_of_accounts`

**Files:**
- Modify: `plugins/kbs_accounting/service.py`
- Modify: `plugins/kbs_accounting/tests/test_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `plugins/kbs_accounting/tests/test_service.py`:

```python
def test_list_entries_returns_most_recent_first(clean_ledger):
    from plugins.kbs_accounting.service import post_entry, list_entries

    for i in range(3):
        post_entry(
            tenant_id=TEST_TENANT_ID,
            entry_date=date(2026, 4, i + 1),
            description=f"Entry {i}",
            source_plugin="test",
            source_entity_type="invoice",
            source_entity_id=i,
            lines=[
                {"account": "1010_cash", "dr": "10.00", "cr": "0"},
                {"account": "4010_revenue", "dr": "0", "cr": "10.00"},
            ],
        )

    rows = list_entries(TEST_TENANT_ID)
    assert len(rows) == 3
    # Default sort: most recent entry_date + id first
    assert rows[0]["description"] == "Entry 2"
    assert rows[-1]["description"] == "Entry 0"


def test_list_entries_filter_by_source(clean_ledger):
    from plugins.kbs_accounting.service import post_entry, list_entries

    post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Invoice entry",
        source_plugin="kbs_invoicing",
        source_entity_type="invoice",
        source_entity_id=1,
        lines=[
            {"account": "1010_cash", "dr": "10.00", "cr": "0"},
            {"account": "4010_revenue", "dr": "0", "cr": "10.00"},
        ],
    )
    post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Order entry",
        source_plugin="kbs_store",
        source_entity_type="order",
        source_entity_id=1,
        lines=[
            {"account": "1010_cash", "dr": "20.00", "cr": "0"},
            {"account": "4010_revenue", "dr": "0", "cr": "20.00"},
        ],
    )

    invoicing = list_entries(TEST_TENANT_ID, source_plugin="kbs_invoicing")
    store = list_entries(TEST_TENANT_ID, source_plugin="kbs_store")
    assert len(invoicing) == 1
    assert invoicing[0]["source_plugin"] == "kbs_invoicing"
    assert len(store) == 1
    assert store[0]["source_plugin"] == "kbs_store"


def test_get_chart_of_accounts_returns_seed(clean_ledger):
    from plugins.kbs_accounting.service import get_chart_of_accounts

    accounts = get_chart_of_accounts(TEST_TENANT_ID)
    codes = {a["code"] for a in accounts}
    assert "1010_cash" in codes
    assert "4010_revenue" in codes
    # class field present
    assert all("class" in a for a in accounts)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugins/kbs_accounting/tests/test_service.py::test_list_entries_returns_most_recent_first plugins/kbs_accounting/tests/test_service.py::test_list_entries_filter_by_source plugins/kbs_accounting/tests/test_service.py::test_get_chart_of_accounts_returns_seed -v
```

Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement `list_entries` and `get_chart_of_accounts`**

Append to `plugins/kbs_accounting/service.py`:

```python
def list_entries(
    tenant_id: int,
    source_plugin: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List entries (newest first). Optional filter by source_plugin.

    Returns entry headers only (no lines) — use get_entry() for details.
    """
    sql = """
        SELECT id, entry_date, description, source_plugin, source_entity_type,
               source_entity_id, reverses_id, reversed_by_id, created_at
        FROM ledger_entries
    """
    params: list[Any] = []
    if source_plugin:
        sql += " WHERE source_plugin = %s"
        params.append(source_plugin)
    sql += " ORDER BY entry_date DESC, id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db_cursor(commit=False) as (_, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(sql, params)
        return [
            {
                "id": r[0],
                "entry_date": r[1].isoformat() if r[1] else None,
                "description": r[2],
                "source_plugin": r[3],
                "source_entity_type": r[4],
                "source_entity_id": r[5],
                "reverses_id": r[6],
                "reversed_by_id": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
            }
            for r in cur.fetchall()
        ]


def get_chart_of_accounts(tenant_id: int, active_only: bool = True) -> list[dict[str, Any]]:
    """Return the chart of accounts for a tenant."""
    sql = "SELECT code, name, class, parent_code, is_active, description FROM chart_of_accounts"
    if active_only:
        sql += " WHERE is_active = TRUE"
    sql += " ORDER BY code"
    with get_db_cursor(commit=False) as (_, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(sql)
        return [
            {
                "code": r[0],
                "name": r[1],
                "class": r[2],
                "parent_code": r[3],
                "is_active": r[4],
                "description": r[5],
            }
            for r in cur.fetchall()
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugins/kbs_accounting/tests/test_service.py -v
```

Expected: all 10 service tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/kbs_accounting/service.py plugins/kbs_accounting/tests/test_service.py
git commit -m "feat(kbs_accounting): list_entries + get_chart_of_accounts"
```

---

## Task 6: Routes scaffold + GET endpoints

**Files:**
- Create: `plugins/kbs_accounting/routes.py`
- Test: `plugins/kbs_accounting/tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Write `plugins/kbs_accounting/tests/test_routes.py`:

```python
"""Integration tests for kbs_accounting HTTP routes."""

from datetime import date

import pytest

from core.database import get_db_cursor, provision_tenant_schema, set_tenant_search_path


TEST_TENANT_ID = 99912


@pytest.fixture(scope="module", autouse=True)
def provisioned_tenant():
    provision_tenant_schema(TEST_TENANT_ID)
    yield
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(f"DROP SCHEMA IF EXISTS tenant_{TEST_TENANT_ID} CASCADE")


@pytest.fixture()
def seeded_entry():
    from plugins.kbs_accounting.service import post_entry

    with get_db_cursor(commit=True) as (_, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute("TRUNCATE ledger_lines, ledger_entries RESTART IDENTITY CASCADE")

    entry_id = post_entry(
        tenant_id=TEST_TENANT_ID,
        entry_date=date(2026, 4, 16),
        description="Route test entry",
        source_plugin="test",
        source_entity_type="invoice",
        source_entity_id=1,
        lines=[
            {"account": "1010_cash", "dr": "10.00", "cr": "0"},
            {"account": "4010_revenue", "dr": "0", "cr": "10.00"},
        ],
    )
    return entry_id


def _auth(client, tenant_id=TEST_TENANT_ID):
    """Force-login as a tenant admin for the duration of the request.
    Uses the test-only header supported by the auth middleware — see core/auth.py
    for the header name. If the helper doesn't exist yet, use session.patch fixture.
    """
    with client.session_transaction() as s:
        s["_user_id"] = "1"
        s["tenant_id"] = tenant_id
        s["role"] = "admin"


def test_get_accounting_index_loads(client, seeded_entry):
    _auth(client)
    resp = client.get("/accounting/")
    assert resp.status_code in (200, 302)


def test_get_api_entries_returns_list(client, seeded_entry):
    _auth(client)
    resp = client.get("/accounting/api/entries")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "entries" in data
    assert len(data["entries"]) == 1
    assert data["entries"][0]["description"] == "Route test entry"


def test_get_api_entry_detail_returns_lines(client, seeded_entry):
    _auth(client)
    resp = client.get(f"/accounting/api/entries/{seeded_entry}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["entry"]["id"] == seeded_entry
    assert len(data["entry"]["lines"]) == 2


def test_get_api_chart_of_accounts_returns_seed(client, seeded_entry):
    _auth(client)
    resp = client.get("/accounting/api/chart-of-accounts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(a["code"] == "1010_cash" for a in data["accounts"])
    assert any(a["code"] == "4010_revenue" for a in data["accounts"])


def test_get_api_entry_not_found_returns_404(client, seeded_entry):
    _auth(client)
    resp = client.get("/accounting/api/entries/999999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest plugins/kbs_accounting/tests/test_routes.py -v
```

Expected: FAIL with 404s (blueprint not registered yet) or import errors.

- [ ] **Step 3: Implement routes**

Write `plugins/kbs_accounting/routes.py`:

```python
"""HTTP routes for kbs_accounting — thin wrappers over service.py.

All routes are tenant-scoped via the session's `tenant_id` and gated behind
`@login_required`. Tier gating is handled by the manifest's `tier_required="business"`
and the marketplace's sidebar hiding (no-op for tenant_1 which is always Enterprise).
"""

from flask import jsonify, render_template, session
from flask_login import login_required

from plugins.kbs_accounting import service


def _current_tenant_id() -> int:
    tid = session.get("tenant_id")
    if not tid:
        raise PermissionError("no tenant in session")
    return int(tid)


def register_routes(bp):
    @bp.route("/")
    @login_required
    def index():
        return render_template("accounting.html")

    @bp.route("/api/entries")
    @login_required
    def api_list_entries():
        from flask import request

        source = request.args.get("source_plugin")
        limit = min(int(request.args.get("limit", 50)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
        entries = service.list_entries(
            _current_tenant_id(), source_plugin=source, limit=limit, offset=offset
        )
        return jsonify({"entries": entries, "limit": limit, "offset": offset})

    @bp.route("/api/entries/<int:entry_id>")
    @login_required
    def api_get_entry(entry_id):
        try:
            entry = service.get_entry(_current_tenant_id(), entry_id)
        except LookupError:
            return jsonify({"error": "not found"}), 404
        return jsonify({"entry": entry})

    @bp.route("/api/chart-of-accounts")
    @login_required
    def api_chart_of_accounts():
        accounts = service.get_chart_of_accounts(_current_tenant_id())
        return jsonify({"accounts": accounts})
```

Also create a minimal `plugins/kbs_accounting/templates/accounting.html` so the index route renders:

```html
{% extends "base.html" %}
{% block title %}Accounting{% endblock %}
{% block content %}
<div class="kbs-page">
  <div class="kbs-page-header">
    <h1>Accounting</h1>
    <p class="muted">Double-entry ledger. Every money-moving event posts here.</p>
  </div>
  <div id="accounting-root" data-plugin="kbs_accounting"></div>
</div>
<link rel="stylesheet" href="/static/accounting/css/accounting.css">
<script src="/static/accounting/js/accounting.js" defer></script>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest plugins/kbs_accounting/tests/test_routes.py -v
```

Expected: all 5 tests PASS. If auth fixture doesn't work, read `core/auth.py` to find the test-mode bypass — many Flask-Login setups accept `TESTING=True` + session priming; others need an explicit `test_client_auth` helper. Adjust `_auth()` in the test file to match.

- [ ] **Step 5: Commit**

```bash
git add plugins/kbs_accounting/routes.py plugins/kbs_accounting/templates/accounting.html plugins/kbs_accounting/tests/test_routes.py
git commit -m "feat(kbs_accounting): GET routes — index + list + detail + chart-of-accounts"
```

---

## Task 7: Ledger Viewer UI (CSS + JS)

**Files:**
- Create: `plugins/kbs_accounting/static/css/accounting.css`
- Create: `plugins/kbs_accounting/static/js/accounting.js`

- [ ] **Step 1: Write CSS**

Write `plugins/kbs_accounting/static/css/accounting.css`:

```css
/* kbs_accounting — ledger viewer styles */

#accounting-root { padding: 16px 0; }

.acc-toolbar {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  margin-bottom: 14px;
  color: var(--archie-text-muted, #94a3b8);
  font-size: 0.85rem;
}
.acc-toolbar select,
.acc-toolbar button {
  padding: 6px 10px;
  background: rgba(139,92,246,0.12);
  border: 1px solid var(--archie-palette-purple-600, #7c3aed);
  border-radius: 4px;
  color: #e5e7eb;
  font-size: 0.8rem;
}

.acc-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.acc-table th,
.acc-table td { padding: 8px 10px; text-align: left; }
.acc-table thead tr {
  border-bottom: 1px solid rgba(255,255,255,0.12);
}
.acc-table tbody tr {
  border-bottom: 1px solid rgba(255,255,255,0.05);
  cursor: pointer;
}
.acc-table tbody tr:hover {
  background: rgba(139,92,246,0.06);
}
.acc-table .acc-money { font-family: 'IBM Plex Mono', monospace; text-align: right; }
.acc-entry-reversed { color: var(--archie-palette-red-500, #ef4444); font-style: italic; }

.acc-empty {
  padding: 40px; text-align: center; color: var(--archie-text-muted, #94a3b8);
}
```

- [ ] **Step 2: Write JS (DOM-construction, no innerHTML interpolation)**

Write `plugins/kbs_accounting/static/js/accounting.js`:

```javascript
/* kbs_accounting — ledger viewer */
(function () {
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
        var v = attrs[k];
        if (k === 'style') el.style.cssText = v;
        else if (k === 'className') el.className = v;
        else if (v != null) el.setAttribute(k, v);
      }
    }
    (children || []).forEach(function (c) {
      if (c == null || c === false) return;
      if (typeof c === 'string' || typeof c === 'number') {
        el.appendChild(document.createTextNode(String(c)));
      } else el.appendChild(c);
    });
    return el;
  }

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  async function api(path) {
    var res = await fetch('/accounting' + path);
    if (!res.ok) throw new Error('api ' + path + ' returned ' + res.status);
    return res.json();
  }

  async function loadEntries() {
    var root = document.getElementById('accounting-root');
    clear(root);

    var toolbar = h('div', { className: 'acc-toolbar' }, [
      h('span', null, ['Source:']),
      h('select', { id: 'acc-source', 'data-action': 'change-source' }, [
        h('option', { value: '' }, ['All']),
        h('option', { value: 'kbs_invoicing' }, ['Invoicing']),
        h('option', { value: 'kbs_store' }, ['Store']),
        h('option', { value: 'kbs_contracts' }, ['Contracts']),
      ]),
      h('button', { 'data-action': 'refresh' }, ['Refresh']),
    ]);
    root.appendChild(toolbar);

    var tableWrap = h('div', { id: 'acc-entries' });
    root.appendChild(tableWrap);

    await renderEntries();
  }

  async function renderEntries(sourceFilter) {
    var tableWrap = document.getElementById('acc-entries');
    clear(tableWrap);
    var path = '/api/entries' + (sourceFilter ? '?source_plugin=' + encodeURIComponent(sourceFilter) : '');
    var data;
    try { data = await api(path); }
    catch (err) {
      tableWrap.appendChild(h('div', { className: 'acc-empty' }, ['Error: ' + err.message]));
      return;
    }
    if (!data.entries.length) {
      tableWrap.appendChild(h('div', { className: 'acc-empty' }, ['No ledger entries yet.']));
      return;
    }
    var headers = ['Date', 'Description', 'Source', 'Entity', 'Status'];
    var thead = h('thead', null, [
      h('tr', null, headers.map(function (x) { return h('th', null, [x]); })),
    ]);
    var tbody = h('tbody');
    data.entries.forEach(function (e) {
      var row = h('tr', { 'data-action': 'open-entry', 'data-arg': String(e.id) }, [
        h('td', null, [e.entry_date || '']),
        h('td', null, [e.description || '']),
        h('td', null, [e.source_plugin || '']),
        h('td', null, [e.source_entity_type + ' #' + e.source_entity_id]),
        h('td', { className: e.reversed_by_id ? 'acc-entry-reversed' : '' },
          [e.reversed_by_id ? 'Reversed' : (e.reverses_id ? 'Reversal' : 'Posted')]),
      ]);
      tbody.appendChild(row);
    });
    tableWrap.appendChild(h('table', { className: 'acc-table' }, [thead, tbody]));
  }

  async function openEntryDetail(entryId) {
    var data;
    try { data = await api('/api/entries/' + entryId); }
    catch (err) { alert('Error: ' + err.message); return; }
    var entry = data.entry;
    // bm-overlay modal — DOM-construction, no innerHTML
    var existing = document.getElementById('acc-entry-modal');
    if (existing) existing.remove();
    var overlay = h('div', {
      id: 'acc-entry-modal', className: 'bm-overlay active',
      style: '--bm-accent:#7c3aed;--bm-accent-rgb:124,58,237;',
      'data-action': 'close-modal-on-backdrop',
    });
    var shell = h('div', { className: 'bm-shell', style: 'max-width:620px;' });
    var frame = h('div', { className: 'bm-frame' }, [
      h('div', { className: 'bm-frame-elbow-top' }),
      h('div', { className: 'bm-frame-seg' }),
      h('div', { className: 'bm-frame-seg dim' }),
      h('div', { className: 'bm-frame-light on' }),
      h('div', { className: 'bm-frame-fill' }),
      h('div', { className: 'bm-frame-elbow-bottom' }),
    ]);
    var body = h('div', { className: 'bm-body' }, [
      h('p', null, [entry.description || '']),
      h('p', { className: 'muted' }, [
        entry.source_plugin + ' ' + entry.source_entity_type + ' #' + entry.source_entity_id +
        ' on ' + (entry.entry_date || ''),
      ]),
      h('table', { className: 'acc-table' }, [
        h('thead', null, [
          h('tr', null, ['Account', 'Dr', 'Cr'].map(function (x) { return h('th', null, [x]); })),
        ]),
        h('tbody', null, entry.lines.map(function (l) {
          return h('tr', null, [
            h('td', null, [l.account]),
            h('td', { className: 'acc-money' }, [l.dr]),
            h('td', { className: 'acc-money' }, [l.cr]),
          ]);
        })),
      ]),
    ]);
    var content = h('div', { className: 'bm-content' }, [
      h('div', { className: 'bm-header' }, [
        h('span', { className: 'bm-header-title' }, ['ENTRY #' + entry.id]),
        h('div', { className: 'bm-header-strip' }, [
          h('button', { className: 'bm-close', 'data-action': 'close-modal', 'aria-label': 'Close' }, ['×']),
        ]),
      ]),
      body,
    ]);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);
  }

  function closeModal() {
    var existing = document.getElementById('acc-entry-modal');
    if (existing) existing.remove();
  }

  // Click dispatcher — data-action pattern
  document.addEventListener('click', function (e) {
    var t = e.target.closest && e.target.closest('[data-action]');
    if (!t) return;
    var action = t.dataset.action;
    if (action === 'refresh') {
      var sel = document.getElementById('acc-source');
      renderEntries(sel ? sel.value : '');
    } else if (action === 'open-entry') {
      openEntryDetail(t.dataset.arg);
    } else if (action === 'close-modal') {
      closeModal();
    } else if (action === 'close-modal-on-backdrop') {
      if (e.target === t) closeModal();
    }
  });
  document.addEventListener('change', function (e) {
    var t = e.target.closest && e.target.closest('[data-action="change-source"]');
    if (!t) return;
    renderEntries(t.value);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadEntries);
  } else {
    loadEntries();
  }
})();
```

- [ ] **Step 3: Restart the KBS app to pick up static files**

```bash
docker compose -f /mnt/archie_brain/kytran-business-suite/docker-compose.hub.yml restart kbs_app 2>&1 | tail -3
sleep 6
curl -s -o /dev/null -w "health=%{http_code}\n" http://192.168.1.200:8091/health
```

Expected: `health=200`.

- [ ] **Step 4: Commit**

```bash
git add plugins/kbs_accounting/static/css/accounting.css plugins/kbs_accounting/static/js/accounting.js plugins/kbs_accounting/templates/accounting.html
git commit -m "feat(kbs_accounting): ledger viewer UI — list + entry detail modal (bm-overlay)"
```

---

## Task 8: P.R.O.B.E. suite YAML

**Files:**
- Create (in **ARCHIE repo**): `platform_v2/qa_suites/kbs-accounting.yaml`

- [ ] **Step 1: Write the suite YAML**

Write `/mnt/archie_brain/platform_v2/qa_suites/kbs-accounting.yaml`:

```yaml
suite:
  name: "Finance — KBS Accounting"
  description: "Critical paths for kbs_accounting skeleton: page load, list entries, entry detail, chart of accounts"
  base_url: "http://192.168.1.200:8091"
  auth:
    username: "${KBS_TEST_USERNAME}"
    password: "${KBS_TEST_PASSWORD}"

tests:
  - name: "acc-page-loads"
    type: api
    method: GET
    path: /accounting/
    expect:
      status: [200, 302]

  - name: "acc-entries-list"
    type: api
    method: GET
    path: /accounting/api/entries
    expect:
      status: [200, 302]

  - name: "acc-entries-list-filtered"
    type: api
    method: GET
    path: /accounting/api/entries?source_plugin=kbs_invoicing
    expect:
      status: [200, 302]

  - name: "acc-chart-of-accounts"
    type: api
    method: GET
    path: /accounting/api/chart-of-accounts
    expect:
      status: [200, 302]
```

- [ ] **Step 2: Register the suite into the DB**

From the ARCHIE repo, run:

```bash
cd /mnt/archie_brain
docker exec archie_platform python3 -c "
import yaml, sys, traceback
sys.path.insert(0, '/app')
try:
    from psycopg2.extras import Json
    from database import get_db_cursor
    with open('/app/qa_suites/kbs-accounting.yaml') as f:
        spec = yaml.safe_load(f)
    s = spec.get('suite', {})
    name = s.get('name'); desc = s.get('description',''); target = s.get('base_url','http://192.168.1.200:8091')
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute('SELECT id FROM qa_test_suites WHERE name = %s', (name,))
        row = cur.fetchone()
        if row:
            cur.execute('UPDATE qa_test_suites SET description=%s, target_url=%s, spec=%s, is_active=true, updated_at=NOW() WHERE id=%s RETURNING id', (desc, target, Json(spec), row['id']))
            print('UPDATED id=', cur.fetchone()['id'])
        else:
            cur.execute(\"INSERT INTO qa_test_suites (name, description, target_url, spec, suite_type) VALUES (%s,%s,%s,%s,'internal') RETURNING id\", (name, desc, target, Json(spec)))
            print('INSERTED id=', cur.fetchone()['id'])
except Exception:
    traceback.print_exc()
"
```

Expected: `INSERTED id=<N>` (or UPDATED if re-running).

- [ ] **Step 3: Run the suite once to baseline**

Use the MCP tool (from a Claude session) or the platform UI:

```
mcp__archie__run_qa_suite(suite_id=<N>, triggered_by='post-S0-deploy')
```

Expected: ≥ 3/4 pass. `acc-page-loads` may 302 when not authed — that's fine. Record the run_id.

- [ ] **Step 4: Commit (ARCHIE repo)**

```bash
cd /mnt/archie_brain
git add platform_v2/qa_suites/kbs-accounting.yaml
git commit -m "feat(probe): add KBS accounting P.R.O.B.E. suite"
```

---

## Task 9: Playwright E2E happy-path

**Files:**
- Create: `kytran-business-suite/scripts/e2e_accounting.py`

- [ ] **Step 1: Write the E2E script**

Write `kytran-business-suite/scripts/e2e_accounting.py`:

```python
"""Playwright E2E for kbs_accounting — ledger viewer happy-path.

Pre-req: KBS running at http://192.168.1.200:8091, test tenant_1 exists with
at least one seeded ledger entry (created via pytest fixture or API).
"""

import os
import sys
from playwright.sync_api import sync_playwright


BASE = os.getenv("KBS_BASE", "http://192.168.1.200:8091")
USER = os.getenv("KBS_TEST_USERNAME", "admin@kytranempowerment.com")
PASS = os.getenv("KBS_TEST_PASSWORD", "KytranBiz2026!")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Login
        page.goto(f"{BASE}/auth/login")
        page.fill('input[name="email"]', USER)
        page.fill('input[name="password"]', PASS)
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/**", timeout=5000)

        # Nav to Accounting
        page.goto(f"{BASE}/accounting/")
        page.wait_for_selector('#accounting-root', timeout=5000)

        # Expect at least the toolbar + entries table or empty-state
        toolbar = page.query_selector('.acc-toolbar')
        assert toolbar is not None, "toolbar missing"
        print("[acc-e2e] toolbar present")

        # Click first row (if any) and expect modal
        first_row = page.query_selector('.acc-table tbody tr')
        if first_row:
            first_row.click()
            page.wait_for_selector('#acc-entry-modal', timeout=2000)
            assert page.query_selector('#acc-entry-modal .bm-body table'), "modal missing lines"
            print("[acc-e2e] entry detail modal renders with lines")
            # Close modal
            page.click('.bm-close')
            page.wait_for_selector('#acc-entry-modal', state='detached', timeout=2000)
            print("[acc-e2e] modal closes")
        else:
            print("[acc-e2e] no entries yet; empty state renders (OK)")
            assert page.query_selector('.acc-empty'), "empty state missing"

        browser.close()
    print("[acc-e2e] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Seed at least one entry via pytest (run test_service.py) or direct service call**

Run from the KBS repo:

```bash
cd /mnt/archie_brain/kytran-business-suite
python3 -c "
import sys; sys.path.insert(0, '.')
from datetime import date
from plugins.kbs_accounting.service import post_entry
entry_id = post_entry(
    tenant_id=1, entry_date=date.today(),
    description='E2E seed', source_plugin='test', source_entity_type='manual',
    source_entity_id=1,
    lines=[{'account':'1010_cash','dr':'100.00','cr':'0'},
           {'account':'4010_revenue','dr':'0','cr':'100.00'}],
)
print('seeded entry id=', entry_id)
"
```

Expected: `seeded entry id=<N>` with N > 0. (If tenant_1 isn't provisioned yet for kbs_accounting, first run `provision_tenant_schema(1)` — that's idempotent.)

- [ ] **Step 3: Run the E2E**

```bash
python3 scripts/e2e_accounting.py
```

Expected: `[acc-e2e] PASS`.

- [ ] **Step 4: Commit**

```bash
git add scripts/e2e_accounting.py
git commit -m "feat(kbs_accounting): playwright E2E happy-path"
```

---

## Task 10: Manual acceptance walkthrough

- [ ] **Step 1: Walk the flow in a real browser as Kytran admin**

1. Open `http://192.168.1.200:8091/accounting/` in Chromium via Playwright MCP OR the user opens it directly if reachable over their network.
2. Confirm the ledger viewer renders: header, toolbar, table (or empty state).
3. If any entries exist, click one — confirm the bm-overlay modal appears with full line detail.
4. Click Refresh — confirm the list reloads.
5. Filter by source plugin — confirm the list updates.

- [ ] **Step 2: Capture screenshot**

Use Playwright MCP:

```
mcp__plugin_playwright_playwright__browser_take_screenshot(filename="kbs-accounting-ledger.png", fullPage=true)
```

Save the path for the PR body.

- [ ] **Step 3: Final commit — slice marker**

```bash
cd /mnt/archie_brain/kytran-business-suite
git commit --allow-empty -m "chore(kbs_accounting): S0 skeleton slice complete — ready for downstream slices (S1+)

All tasks from the Slice S0 plan shipped locally:
- plugin scaffold + manifest
- migration: chart_of_accounts + ledger_entries + ledger_lines + seed chart
- service: post_entry (double-entry invariant), reverse_entry, list_entries,
  get_entry, get_chart_of_accounts
- routes: /accounting/, /api/entries, /api/entries/<id>, /api/chart-of-accounts
- UI: ledger viewer table + entry detail bm-overlay modal (DOM construction,
  no innerHTML interpolation)
- P.R.O.B.E. suite registered in ARCHIE repo
- Playwright E2E happy-path green
- Manual acceptance walkthrough complete; screenshot in PR

LOCAL COMMIT ONLY — push on 2026-05-01 per GitHub Actions minutes freeze.
Register branch in Repair Bay's Pending Push Queue panel."
```

- [ ] **Step 4: Register in the push-queue inventory (ARCHIE memory)**

Append a row to the inventory table in `~/.claude/projects/-mnt-archie-brain/memory/feedback_github-actions-minutes.md`:

```
| `feat/slice-0-accounting-skeleton` (in kytran-business-suite) | <latest-sha> | 🟡 not pushed | KBS Phase 1 Slice S0 — kbs_accounting skeleton (chart of accounts + double-entry post_entry() + ledger viewer + P.R.O.B.E. suite + E2E) | Hold until 2026-05-01 |
```

- [ ] **Step 5: Close out Dev HQ tasks**

From the ARCHIE MCP:

```
mcp__archie__complete_task(task_id=<S0-task-id>, notes="Slice S0 shipped locally on branch feat/slice-0-accounting-skeleton in KBS repo. See plan docs/superpowers/plans/2026-04-16-kbs-phase-1-slice-0-accounting-skeleton-plan.md for file list. Branch held for May 1 push per freeze.")

mcp__archie__log_decision(
    title="KBS Accounting — double-entry + post_entry hook pattern",
    decision="kbs_accounting exposes post_entry(tenant_id, entry_date, description, source_plugin, source_entity_type, source_entity_id, lines, metadata) with sum(dr)==sum(cr) invariant enforced in service. Other plugins call this (never direct SQL) for every money-moving event. Reversals via reverse_entry() create mirror entries + set reversed_by_id on original.",
    context="First slice of KBS Phase 1. Foundation for S1 CRM (no money), S2 Invoicing (invoice.paid → post_entry), S3 Contracts, S4 Store (order.paid → post_entry), future reporting (S6 full accounting).",
    alternatives="Single-entry ledger (rejected — real accounting needs double-entry). Per-plugin ledger tables (rejected — one unified post_entry() enforces consistency). Defer until S6 full accounting (rejected — retrofitting hooks later = 4x the work).",
    consequences="Every future slice that moves money MUST call post_entry(). Direct INSERTs into ledger_entries or ledger_lines from non-kbs_accounting code = review-blocker. Reconciliation reports (S6) are a pure aggregation over the existing tables; no data model change.",
    project_id=269,
)
```

---

## Self-Review Checklist (run before claiming S0 done)

- [ ] Every task's commit landed; `git log --oneline | head -15` shows 10+ commits on `feat/slice-0-accounting-skeleton`.
- [ ] `pytest plugins/kbs_accounting/tests/ -v` — all 3 test files green, 12+ tests pass.
- [ ] `coverage run -m pytest plugins/kbs_accounting && coverage report -m | grep service` — ≥ 95% coverage on `service.py`.
- [ ] P.R.O.B.E. run 4/4 (or 3/4 with auth redirect noted).
- [ ] Playwright E2E prints `[acc-e2e] PASS`.
- [ ] Screenshot of working ledger viewer attached to the PR body draft in `~/tmp/kbs-accounting-pr-body.md`.
- [ ] No `TODO` / `FIXME` / placeholder values in any committed file (`git grep -E 'TODO|FIXME|XXX' plugins/kbs_accounting/`).
- [ ] No direct SQL to `ledger_entries` / `ledger_lines` outside `service.py` (`git grep -E 'FROM ledger_(entries|lines)' plugins/` — should match only service.py).
- [ ] Inventory row in `feedback_github-actions-minutes.md` updated.

---

## Handoff to S1

Once S0 is green, the next slice is **S1: `kbs_crm` rewrite to `core.objects`**. Invoke `writing-plans` again with the S1 scope from the parent spec. S1 depends on:
- S0's `post_entry` is exported and importable (no CRM-side money events yet, but the import is expected in Phase 1 even if it's only used in tests for shape assertions).
- `kbs_core_objects` accounts/contacts/leads/opportunities tables exist in tenant_1 (already shipped Plan 1).
