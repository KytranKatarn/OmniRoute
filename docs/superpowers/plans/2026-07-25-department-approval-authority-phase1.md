# Department Approval Authority — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every PR requires sign-off from the department director who owns each changed path, enforced at the merge gate, surfaced in the DHQ Approvals tab.

**Architecture:** A pure path→department resolver decides which departments a PR touches. One `pr_domain_approvals` row is created per owning department when F.O.R.G.E. finishes its review. The fail-closed merge gate (`github_service._automerge_governance_ok`, live since PR #2460) gains one more required condition: every row for that PR must be `approved`. Rows are approved/rejected through the existing unified approvals surface.

**Tech Stack:** Python 3.11, Flask, psycopg2 (`RealDictCursor`), pytest, PostgreSQL 16.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-25-department-approval-authority-design.md`
- **Fail closed everywhere.** Unknown = refuse. Not knowing what a PR touches is not evidence it is safe.
- **`classify_pr_tier()` is NOT modified.** Risk tier and domain ownership are orthogonal axes.
- **Safety properties are universal; authority limits are per-actor** (established in PR #2460).
- DB access: `from database import get_db_cursor`, used as `with get_db_cursor(commit=True) as (conn, cur):`. Returns dict rows.
- Timezone: storage UTC (`TIMESTAMPTZ`), never `datetime.utcnow()`. See `.claude/rules/timezone.md`.
- Tests run in the container: `docker exec -w /app archie_platform python3 -m pytest <path> -q`. A host run needs `DB_HOST=192.168.1.200` exported and lacks `httpx`.
- Black + flake8 run as pre-commit hooks. Black reformats on the first commit attempt — re-stage and commit again.
- Branch from `main`; never commit to `main` directly.

## Out of Scope (Phase 2)

Automated director dispatch, welfare-gated wake, and COO escalation. Phase 1 creates the rows and enforces them; a human or director approves via the Approvals tab. Phase 2 automates the asking.

## File Structure

| File | Responsibility |
|---|---|
| `database/migrations/463_pr_domain_approvals.sql` | Table + indexes |
| `platform_v2/tools/repair_bay/services/pr_domain_ownership.py` | **Pure.** Path globs → owning departments. No DB, no network. |
| `platform_v2/tools/repair_bay/services/pr_domain_approvals.py` | DB + GitHub: create rows, read status, approve/reject |
| `platform_v2/tools/repair_bay/services/github_service.py` | MODIFY: gate requires all rows approved |
| `platform_v2/tools/repair_bay/services/pr_review_service.py` | MODIFY: create rows when review completes |
| `platform_v2/tools/department_hq/approvals_routes.py` | MODIFY: join into `/api/approvals/pending` + approve/reject endpoints |
| `platform_v2/tests/test_pr_domain_ownership.py` | Pure resolver tests |
| `platform_v2/tests/test_pr_domain_approvals.py` | Row creation + gate integration tests |

---

### Task 1: `pr_domain_approvals` table

**Files:**
- Create: `database/migrations/463_pr_domain_approvals.sql`

**Interfaces:**
- Consumes: nothing
- Produces: table `pr_domain_approvals` with columns `id, pr_number, repo, department, required_agent_id, deciding_agent_id, status, escalated_to, escalation_reason, matched_paths, decided_at, created_at`

- [ ] **Step 1: Write the migration**

```sql
-- 463_pr_domain_approvals.sql
--
-- Per-department sign-off on pull requests (department approval authority, Phase 1).
--
-- WHY
-- Today ONE agent reviews every change. classify_pr_tier() escalates purely by size and
-- risk, so a 50-line change to rbac.py merges on F.O.R.G.E.'s approval alone and
-- V.I.G.I.L., who owns Security & Compliance, never sees it. The organisation has
-- department heads; the merge path does not.
--
-- WHY required_agent_id AND deciding_agent_id ARE SEPARATE
-- The row must be able to say "V.I.G.I.L. was asked, A.R.C.H.I.E. decided, because
-- V.I.G.I.L. was over her token budget". Collapsing them into one column destroys
-- exactly the fact an auditor needs. Phase 2 populates the escalation columns; Phase 1
-- creates them so the schema does not churn.

CREATE TABLE IF NOT EXISTS pr_domain_approvals (
    id                SERIAL PRIMARY KEY,
    pr_number         INTEGER      NOT NULL,
    repo              TEXT         NOT NULL,
    department        TEXT         NOT NULL,
    required_agent_id INTEGER      REFERENCES agents(id),
    deciding_agent_id INTEGER      REFERENCES agents(id),
    status            TEXT         NOT NULL DEFAULT 'pending',
    escalated_to      INTEGER      REFERENCES agents(id),
    escalation_reason TEXT,
    matched_paths     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    decided_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pr_domain_approvals_status_check
        CHECK (status IN ('pending', 'approved', 'rejected', 'escalated')),
    -- An escalation without a stated reason is how "escalating is easier than asking"
    -- becomes invisible. Enforce the WHY in the schema.
    CONSTRAINT pr_domain_approvals_escalation_reason_required
        CHECK (status <> 'escalated' OR escalation_reason IS NOT NULL),
    CONSTRAINT pr_domain_approvals_unique UNIQUE (pr_number, repo, department)
);

CREATE INDEX IF NOT EXISTS idx_pr_domain_approvals_pending
    ON pr_domain_approvals (pr_number, repo) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_pr_domain_approvals_status
    ON pr_domain_approvals (status);
```

- [ ] **Step 2: Apply it**

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/463_pr_domain_approvals.sql`
Expected: `CREATE TABLE`, two `CREATE INDEX`. Re-running is a no-op (`IF NOT EXISTS`).

- [ ] **Step 3: Verify the constraint actually bites**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "INSERT INTO pr_domain_approvals (pr_number, repo, department, status)
   VALUES (1, 'x/y', 'Security & Compliance', 'escalated');"
```
Expected: `ERROR: new row ... violates check constraint "pr_domain_approvals_escalation_reason_required"`.
Then clean up: `DELETE FROM pr_domain_approvals WHERE repo='x/y';`

- [ ] **Step 4: Commit**

```bash
git add database/migrations/463_pr_domain_approvals.sql
git commit -m "feat(db): migration 463 — pr_domain_approvals table"
```

---

### Task 2: Pure path → department resolver

**Files:**
- Create: `platform_v2/tools/repair_bay/services/pr_domain_ownership.py`
- Test: `platform_v2/tests/test_pr_domain_ownership.py`

**Interfaces:**
- Consumes: nothing (pure — no DB, no network)
- Produces:
  - `OWNERSHIP_RULES: tuple[tuple[str, str], ...]` — `(regex, department)`, priority order, first match wins
  - `DEFAULT_DEPARTMENT: str = "Engineering & Technology"`
  - `resolve_owning_departments(paths: list[str]) -> dict[str, list[str]]` — department → the paths that selected it

- [ ] **Step 1: Write the failing test**

```python
"""Path -> owning department resolution (department approval authority, Phase 1).

This decides WHICH DIRECTOR IS ASKED TO APPROVE A PR, so a wrong rule does not fail
loudly — it quietly routes a decision to someone with no standing to make it. The
owner-redlined calls and the ordering traps therefore get their own pinning tests.
"""

from tools.repair_bay.services.pr_domain_ownership import (
    DEFAULT_DEPARTMENT,
    OWNERSHIP_RULES,
    resolve_owning_departments,
)

# The 17 canonical values of agents.department, read from the live table 2026-07-25.
# agents.department is constrained to exactly these, so a rule naming anything else
# resolves to a department that cannot be looked up — a silent no-approver.
CANONICAL_DEPARTMENTS = frozenset({
    "Analytics & Intelligence", "Creative & Design", "Customer Success & Support",
    "Diplomatic & External Relations", "Documentation & Knowledge",
    "Engineering & Technology", "Executive Office", "Finance & Accounting",
    "Human Resources & Culture", "Legal & Regulatory", "Logistics & Supply Chain",
    "Marketing & Communications", "Medical & Wellness", "News & Media",
    "Operations & Infrastructure", "Research & Development", "Security & Compliance",
})


class TestOwnerRedlines:
    """Calls Kytran made explicitly. Changing these needs another owner decision."""

    def test_agent_academy_is_hr_not_rnd(self):
        out = resolve_owning_departments(["platform_v2/tools/agent_academy/routes.py"])
        assert "Human Resources & Culture" in out
        assert "Research & Development" not in out

    def test_account_center_is_security_not_support(self):
        out = resolve_owning_departments(["platform_v2/tools/account_center/routes.py"])
        assert "Security & Compliance" in out
        assert "Customer Success & Support" not in out

    def test_migrations_fall_to_the_default_owner(self):
        # A migration cannot be regexed to the department owning the table; guessing
        # would be worse than Engineering. Deliberate, not an oversight.
        out = resolve_owning_departments(["database/migrations/463_whatever.sql"])
        assert list(out) == [DEFAULT_DEPARTMENT]


class TestOrderingTraps:
    """Rules are first-match-wins, so these pairs are order-dependent by construction."""

    def test_welfare_governance_beats_the_broad_welfare_rule(self):
        # C.R.E.E.D. grades the ORG on workforce treatment; K.I.N. runs the breaks.
        # Different accountability ⇒ different approver.
        out = resolve_owning_departments(
            ["platform_v2/services/welfare_governance_service.py"]
        )
        assert "Legal & Regulatory" in out
        assert "Human Resources & Culture" not in out

    def test_department_hq_splits_three_ways(self):
        # DHQ is not one domain: it holds fleet ops, the K.I.N. tab, and the dispatcher.
        out = resolve_owning_departments([
            "platform_v2/tools/department_hq/fleet_node_routes.py",
            "platform_v2/tools/department_hq/work_routes.py",
            "platform_v2/tools/department_hq/services/department_dispatcher.py",
        ])
        assert out["Operations & Infrastructure"] == [
            "platform_v2/tools/department_hq/fleet_node_routes.py"
        ]
        assert out["Human Resources & Culture"] == [
            "platform_v2/tools/department_hq/work_routes.py"
        ]
        assert out["Engineering & Technology"] == [
            "platform_v2/tools/department_hq/services/department_dispatcher.py"
        ]

    def test_first_matching_rule_wins(self):
        # rbac.py is security even though it also lives under platform_v2/.
        out = resolve_owning_departments(["platform_v2/rbac.py"])
        assert "Engineering & Technology" not in out


class TestResolution:
    def test_security_paths_route_to_vigil(self):
        out = resolve_owning_departments(["platform_v2/rbac.py"])
        assert out["Security & Compliance"] == ["platform_v2/rbac.py"]

    def test_welfare_paths_route_to_kin(self):
        out = resolve_owning_departments(["platform_v2/services/welfare_load.py"])
        assert "Human Resources & Culture" in out

    def test_multi_domain_pr_produces_one_entry_per_department(self):
        out = resolve_owning_departments(
            ["platform_v2/rbac.py", "platform_v2/services/welfare_load.py"]
        )
        assert set(out) == {"Security & Compliance", "Human Resources & Culture"}

    def test_unmatched_path_falls_back_to_default_owner(self):
        out = resolve_owning_departments(["some/unowned/thing.txt"])
        assert list(out) == [DEFAULT_DEPARTMENT]

    def test_no_path_is_ever_unowned(self):
        out = resolve_owning_departments(["a.py", "platform_v2/rbac.py", "z.md"])
        assert sum(len(v) for v in out.values()) == 3

    def test_empty_input_yields_no_departments(self):
        # The CALLER decides what an empty change list means; the resolver does not guess.
        assert resolve_owning_departments([]) == {}


class TestDepartmentNameIntegrity:
    """A typo here yields a department nobody can be looked up for — fail it at test time."""

    def test_every_rule_names_a_canonical_department(self):
        named = {dept for _, dept in OWNERSHIP_RULES}
        assert named <= CANONICAL_DEPARTMENTS, named - CANONICAL_DEPARTMENTS

    def test_default_department_is_canonical(self):
        assert DEFAULT_DEPARTMENT in CANONICAL_DEPARTMENTS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_ownership.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.repair_bay.services.pr_domain_ownership'`

- [ ] **Step 3: Write the implementation**

```python
"""Path -> owning department resolution. PURE — no DB, no network, no I/O.

The organisation has 17 departments with directors, but one agent reviews every change.
This module answers "whose area does this PR touch?" so the owning director can be
required to sign off (see the Phase 1 design spec).

Rules are ORDERED and first-match-wins per path, so a specific rule (rbac.py -> Security)
beats a broad one (platform_v2/** -> Engineering). Keep the specific rules above the
broad ones.
"""

import re
from typing import Dict, List

DEFAULT_DEPARTMENT = "Engineering & Technology"

# (regex, department). Ordered: FIRST MATCH WINS. Department strings MUST match
# agents.department exactly — it is constrained to the 17 canonical names, verified
# against the live table 2026-07-25.
#
# OWNER-REDLINED 2026-07-25. Three calls made explicitly by Kytran:
#   • Agent Academy is HR, not R&D — training is a people function.
#   • Account Center is Security, not Support — it is permissions, keys and sessions.
#   • database/migrations/ stays on the DEFAULT owner; a migration cannot be regexed
#     to the department that owns the table, and guessing would be worse than Engineering.
# Executive Office, Logistics & Supply Chain and Diplomatic & External Relations own
# NO paths by design: A.R.C.H.I.E. is the ESCALATION target, not a path owner, and the
# other two have no in-repo surface. R&D likewise owns nothing once Academy moved to HR.
OWNERSHIP_RULES = (
    # --- Security & Compliance (V.I.G.I.L., S.H.I.E.L.D.) ---
    (r"^platform_v2/rbac\.py$", "Security & Compliance"),
    (r"^platform_v2/services/auth_", "Security & Compliance"),
    (r"^platform_v2/tools/security_network/", "Security & Compliance"),
    (r"^platform_v2/tools/account_center/", "Security & Compliance"),
    (r"^secrets/", "Security & Compliance"),
    # --- Finance & Accounting (L.E.D.G.E.R., C.H.A.I.N.) ---
    (r"^platform_v2/services/stripe_service\.py$", "Finance & Accounting"),
    (r"^platform_v2/services/billing_", "Finance & Accounting"),
    (r"^platform_v2/services/subscription_service\.py$", "Finance & Accounting"),
    # --- Operations & Infrastructure (B.A.S.E., W.A.R.D.E.N., A.R.M.A.D.A.) ---
    (r"^platform_v2/tools/backup_manager/", "Operations & Infrastructure"),
    (r"^platform_v2/services/backup_", "Operations & Infrastructure"),
    (r"^scripts/backup/", "Operations & Infrastructure"),
    (r"^scripts/dr/", "Operations & Infrastructure"),
    (r"^docker-compose", "Operations & Infrastructure"),
    (r"^node_client/", "Operations & Infrastructure"),
    (r"^platform_v2/tools/department_hq/fleet_", "Operations & Infrastructure"),
    (r"^standalone/media_hub/", "Operations & Infrastructure"),  # M.A.V.E.N. is Ops
    # --- Marketing & Communications (S.I.G.N.A.L.) ---
    (r"^platform_v2/services/signal_", "Marketing & Communications"),
    (r"^website/", "Marketing & Communications"),  # 1,714 files — the public sites
    # --- Analytics & Intelligence (S.P.E.C.T.R.A., W.A.T.C.H., S.C.O.U.T.) ---
    (r"^platform_v2/services/browser_", "Analytics & Intelligence"),
    (r"^platform_v2/services/egress_", "Analytics & Intelligence"),
    (r"^archie-scraper/", "Analytics & Intelligence"),  # S.C.O.U.T.'s scraper + proxy_selector
    # --- Legal & Regulatory (G.A.V.E.L., E.T.H.O.S.) ---
    # ORDERING TRAP: welfare_governance* MUST stay above the broad welfare* rule below.
    # C.R.E.E.D. grades the ORG on how it treats the workforce; K.I.N. runs the breaks.
    # Different accountability, so different approver — and the broad rule would swallow it.
    (r"^platform_v2/services/welfare_governance", "Legal & Regulatory"),
    (r"^platform_v2/tools/creed_command/", "Legal & Regulatory"),
    # --- Human Resources & Culture (K.I.N.) ---
    (r"^platform_v2/services/welfare", "Human Resources & Culture"),
    (r"^platform_v2/services/agent_service\.py$", "Human Resources & Culture"),
    (r"^platform_v2/tools/agent_academy/", "Human Resources & Culture"),
    (r"^platform_v2/tools/department_hq/work_routes\.py$", "Human Resources & Culture"),
    # --- Medical & Wellness (V.I.T.A.L., F.A.I.T.H.) ---
    (r"^platform_v2/tools/(fitness|therapy|doc|faith)/", "Medical & Wellness"),
    # --- Creative & Design (M.U.S.E.) ---
    (r"^platform_v2/tools/media_studio/", "Creative & Design"),
    # --- News & Media (F.A.C.T.) ---
    (r"^platform_v2/tools/wtf_hub/", "News & Media"),
    (r"^what-the-fact/", "News & Media"),
    # --- Customer Success & Support (R.E.S.O.L.V.E.) ---
    (r"^platform_v2/tools/email_manager/", "Customer Success & Support"),
    # --- Documentation & Knowledge (C.O.D.E.X.) ---
    (r"^platform_v2/tools/consciousness/", "Documentation & Knowledge"),
    (r"^docs/", "Documentation & Knowledge"),
    (r"^\.claude/rules/", "Documentation & Knowledge"),
    # --- Engineering & Technology (F.O.R.G.E., P.R.O.B.E.) — also the DEFAULT ---
    (r"^ai_bridge/", "Engineering & Technology"),
    (r"^platform_v2/tools/repair_bay/", "Engineering & Technology"),
    (r"^platform_v2/tools/department_hq/services/", "Engineering & Technology"),
    (r"^platform_v2/tests/", "Engineering & Technology"),
)

_COMPILED = tuple((re.compile(pattern), dept) for pattern, dept in OWNERSHIP_RULES)


def resolve_owning_departments(paths: List[str]) -> Dict[str, List[str]]:
    """Map changed paths to the departments that own them.

    Returns ``{department: [paths that selected it]}``. Every path lands somewhere —
    unmatched paths go to ``DEFAULT_DEPARTMENT`` — so no code is unowned. An empty input
    returns ``{}``; deciding what "no changed files" means is the caller's job, not this
    function's, and the caller fails closed.
    """
    owners: Dict[str, List[str]] = {}
    for path in paths:
        if not path:
            continue
        department = DEFAULT_DEPARTMENT
        for pattern, dept in _COMPILED:
            if pattern.search(path):
                department = dept
                break
        owners.setdefault(department, []).append(path)
    return owners
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_ownership.py -q`
Expected: 14 passed

(The rules table and this test file were extracted from THIS document and executed
together on 2026-07-25 — 14 passed — so the ordering traps are known-good before
implementation starts. Re-run here anyway; a plan that has been read is not a test
that has been run.)

**Measured against all 5,610 tracked files** the same day, which is how three rules got
fixed before anyone wrote code: `website/` (1,714 files) was falling to Engineering
instead of Marketing, `what-the-fact/` to Engineering instead of News & Media, and the
`proxy_selector` rule pointed at `platform_v2/services/` when the file actually lives in
`archie-scraper/` — a rule that could never have matched anything. Resulting split:

| Files | Department |
|---:|---|
| 2,515 | Engineering & Technology (incl. the default) |
| 1,810 | Marketing & Communications |
| 509 | Documentation & Knowledge |
| 297 | News & Media |
| 229 | Operations & Infrastructure |
| 79 | Security & Compliance |
| 48 | Analytics & Intelligence |
| 38 | Creative & Design |
| 31 | Customer Success & Support |
| 24 | Medical & Wellness |
| 16 | Human Resources & Culture |
| 11 | Legal & Regulatory |
| 3 | Finance & Accounting |

Engineering still carries 45% of files, down from 85% before those fixes. That is the
honest ceiling of a path map: most of the repo IS engineering code, and F.O.R.G.E. is
the engineering director. Only `^secrets/` matches zero tracked files — deliberately, as
secrets are gitignored; the rule stands as defence-in-depth if one is ever committed.
Re-run this measurement whenever rules change — a rule matching nothing is either a typo
or a path that moved, and both are invisible without it.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_domain_ownership.py platform_v2/tests/test_pr_domain_ownership.py
git commit -m "feat(forge): pure path -> owning department resolver"
```

---

### Task 3: Create approval rows from a PR's changed files

**Files:**
- Create: `platform_v2/tools/repair_bay/services/pr_domain_approvals.py`
- Test: `platform_v2/tests/test_pr_domain_approvals.py`

**Interfaces:**
- Consumes: `resolve_owning_departments()` (Task 2); `_api_get` from `github_service`
- Produces:
  - `create_domain_approvals(pr_number: int, repo: str) -> dict` → `{"ok": bool, "departments": list[str], "error": str | None}`
  - `domain_approvals_status(pr_number: int, repo: str) -> dict` → `{"total": int, "approved": int, "pending": list[str], "rejected": list[str]}`

- [ ] **Step 1: Write the failing test**

```python
"""pr_domain_approvals — row creation and status rollup (Phase 1)."""

from unittest.mock import patch

from tools.repair_bay.services import pr_domain_approvals as pda

_REPO = "KytranKatarn/archie-platform"


def _files(*names):
    return True, [{"filename": n} for n in names]


class TestCreate:
    def test_creates_one_row_per_owning_department(self):
        with patch.object(pda, "_api_get", return_value=_files(
            "platform_v2/rbac.py", "platform_v2/services/welfare_load.py"
        )):
            with patch.object(pda, "_insert_rows", return_value=None) as ins:
                out = pda.create_domain_approvals(1, _REPO)
        assert out["ok"] is True
        assert set(out["departments"]) == {"Security & Compliance", "Human Resources & Culture"}
        assert ins.call_count == 1

    def test_fails_closed_when_changed_files_unavailable(self):
        # Not knowing what a PR touches is not evidence that it is safe.
        with patch.object(pda, "_api_get", return_value=(False, None)):
            out = pda.create_domain_approvals(1, _REPO)
        assert out["ok"] is False
        assert out["departments"] == []

    def test_fails_closed_on_empty_file_list(self):
        with patch.object(pda, "_api_get", return_value=(True, [])):
            out = pda.create_domain_approvals(1, _REPO)
        assert out["ok"] is False

    def test_fails_closed_when_github_raises(self):
        with patch.object(pda, "_api_get", side_effect=RuntimeError("boom")):
            out = pda.create_domain_approvals(1, _REPO)
        assert out["ok"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_approvals.py -q`
Expected: FAIL — `ModuleNotFoundError: ... pr_domain_approvals`

- [ ] **Step 3: Write the implementation**

```python
"""Per-department PR sign-off rows: creation and status rollup (Phase 1).

Phase 1 CREATES the rows and reports their status; the merge gate refuses until every
row is approved. Directors approve through the existing DHQ Approvals tab. Phase 2 adds
automated asking (welfare-gated wake) and COO escalation.
"""

import json
import logging
from typing import Dict, List

from database import get_db_cursor

from .github_service import _api_get
from .pr_domain_ownership import resolve_owning_departments

logger = logging.getLogger(__name__)


def _changed_paths(pr_number: int, repo: str) -> List[str]:
    """Changed file paths for a PR, or [] if they cannot be determined.

    Mirrors _automerge_paths_allowed's posture: an unavailable list is treated as
    UNKNOWN, and unknown fails closed upstream.
    """
    try:
        ok, files = _api_get(f"/repos/{repo}/pulls/{pr_number}/files", {"per_page": 100})
    except Exception as exc:  # noqa: BLE001 — fail closed on any transport error
        logger.warning("PR #%s: changed-file list unavailable (%s)", pr_number, exc)
        return []
    if not ok or not isinstance(files, list) or not files:
        logger.warning("PR #%s: changed-file list empty/unavailable", pr_number)
        return []
    return [f.get("filename", "") for f in files if f.get("filename")]


def _insert_rows(pr_number: int, repo: str, owners: Dict[str, List[str]]) -> None:
    """Insert one pending row per owning department. Idempotent per (pr, repo, dept)."""
    with get_db_cursor(commit=True) as (conn, cur):
        for department, paths in owners.items():
            cur.execute(
                """
                INSERT INTO pr_domain_approvals
                    (pr_number, repo, department, required_agent_id, matched_paths, status)
                VALUES (%s, %s, %s,
                        (SELECT id FROM agents
                          WHERE department = %s AND is_department_ai = TRUE
                            AND status = 'active' LIMIT 1),
                        %s, 'pending')
                ON CONFLICT (pr_number, repo, department) DO NOTHING
                """,
                (pr_number, repo, department, department, json.dumps(paths)),
            )


def create_domain_approvals(pr_number: int, repo: str) -> dict:
    """Create the per-department sign-off rows for a PR.

    FAILS CLOSED: if the changed-file list cannot be determined, NO rows are created and
    ok=False. The gate refuses a PR with zero rows, so an unknown change set blocks the
    merge rather than sailing through unowned.
    """
    paths = _changed_paths(pr_number, repo)
    if not paths:
        return {"ok": False, "departments": [], "error": "changed-file list unavailable"}

    owners = resolve_owning_departments(paths)
    try:
        _insert_rows(pr_number, repo, owners)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PR #%s: could not persist domain approvals: %s", pr_number, exc)
        return {"ok": False, "departments": [], "error": str(exc)[:200]}

    logger.info(
        "PR #%s: domain sign-off required from %s", pr_number, ", ".join(sorted(owners))
    )
    return {"ok": True, "departments": sorted(owners), "error": None}


def domain_approvals_status(pr_number: int, repo: str) -> dict:
    """Roll up sign-off state for a PR."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT department, status FROM pr_domain_approvals "
            "WHERE pr_number = %s AND repo = %s",
            (pr_number, repo),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {
        "total": len(rows),
        "approved": sum(1 for r in rows if r["status"] == "approved"),
        "pending": [r["department"] for r in rows if r["status"] in ("pending", "escalated")],
        "rejected": [r["department"] for r in rows if r["status"] == "rejected"],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_approvals.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_domain_approvals.py platform_v2/tests/test_pr_domain_approvals.py
git commit -m "feat(forge): create per-department PR sign-off rows, fail closed"
```

---

### Task 4: Merge gate requires every domain sign-off

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/github_service.py` (inside `_automerge_governance_ok`, after the tier check)
- Test: `platform_v2/tests/test_pr_domain_approvals.py` (append)

**Interfaces:**
- Consumes: `domain_approvals_status()` (Task 3)
- Produces: `_automerge_governance_ok` returns `(False, reason)` unless every row is `approved`

- [ ] **Step 1: Write the failing test (append to the existing file)**

```python
from tools.repair_bay.services import github_service

_APPROVED_VERDICT = "ISSUES\nNo issues found.\n\nVERDICT: APPROVE"


def _review():
    return {"pr_number": 1, "ai_summary": _APPROVED_VERDICT, "repo": _REPO}


class TestGateRequiresDomainSignoff:
    def _gate(self, status):
        m = "tools.repair_bay.services.pr_review_service"
        with patch(f"{m}.get_review", return_value=_review()):
            with patch(f"{m}.classify_pr_tier", return_value=1):
                with patch.object(github_service, "domain_approvals_status", return_value=status):
                    return github_service._automerge_governance_ok(1, repo=_REPO)

    def test_pending_domain_signoff_refuses(self):
        ok, why = self._gate({"total": 2, "approved": 1, "pending": ["Security & Compliance"], "rejected": []})
        assert ok is False
        assert "Security & Compliance" in why

    def test_all_approved_allows(self):
        ok, why = self._gate({"total": 2, "approved": 2, "pending": [], "rejected": []})
        assert ok is True, why

    def test_zero_rows_refuses(self):
        # Every PR gets at least one owner, so zero rows means they were never created.
        ok, why = self._gate({"total": 0, "approved": 0, "pending": [], "rejected": []})
        assert ok is False
        assert "no department sign-off" in why

    def test_rejection_refuses_and_says_so(self):
        ok, why = self._gate({"total": 1, "approved": 0, "pending": [], "rejected": ["Security & Compliance"]})
        assert ok is False
        assert "rejected" in why
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_approvals.py::TestGateRequiresDomainSignoff -q`
Expected: FAIL — `AttributeError: ... has no attribute 'domain_approvals_status'`

- [ ] **Step 3: Add the import and the check**

In `github_service.py`, add near the other lazy imports inside `_automerge_governance_ok`, immediately AFTER the existing tier check and BEFORE its final `return (True, ...)`:

```python
        # DOMAIN SIGN-OFF (Phase 1) — the department director owning each changed path
        # must approve. Zero rows means they were never created (every PR gets at least
        # one owner), so zero refuses: unknown ownership is not evidence of safety.
        domain = domain_approvals_status(pr_number, repo or REPO_FULL)
        if domain["total"] == 0:
            return (False, f"PR #{pr_number} has no department sign-off rows — refusing unattended merge")
        if domain["rejected"]:
            return (
                False,
                f"PR #{pr_number} rejected by {', '.join(domain['rejected'])} — "
                f"a considered rejection blocks; it does not escalate",
            )
        if domain["pending"]:
            return (
                False,
                f"PR #{pr_number} awaiting domain sign-off from {', '.join(domain['pending'])}",
            )
```

Add this import at the top of the same function, beside the existing `pr_review_service` import:

```python
        from .pr_domain_approvals import domain_approvals_status  # noqa: PLC0415
```

Then expose it at module scope so the test can patch it — add near the top of `github_service.py`, after the existing imports:

```python
def domain_approvals_status(pr_number: int, repo: str) -> dict:
    """Thin re-export so callers and tests have one patch point."""
    from .pr_domain_approvals import domain_approvals_status as _impl

    return _impl(pr_number, repo)
```

and inside `_automerge_governance_ok` call the module-level `domain_approvals_status(...)` (no local import).

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_pr_domain_approvals.py -q`
Expected: 8 passed

- [ ] **Step 5: Run the full gate suite for regressions**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_merge_governance_gate.py -q`
Expected: 20 passed. If any fail, they patch `_automerge_governance_ok`'s internals — add `domain_approvals_status` to their patches returning `{"total": 1, "approved": 1, "pending": [], "rejected": []}`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/repair_bay/services/github_service.py platform_v2/tests/test_pr_domain_approvals.py
git commit -m "feat(forge): merge gate requires every department sign-off"
```

---

### Task 5: Create rows when F.O.R.G.E. finishes its review

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_review_service.py` (in `mark_review_done`, after the review row UPDATE)

**Interfaces:**
- Consumes: `create_domain_approvals()` (Task 3)
- Produces: sign-off rows exist by the time any auto-merge is attempted

- [ ] **Step 1: Write the failing test (new file)**

Create `platform_v2/tests/test_domain_signoff_creation.py`:

```python
"""Domain sign-off rows are created when F.O.R.G.E. completes a review."""

from unittest.mock import patch

from tools.repair_bay.services import pr_review_service as prs


def test_review_completion_creates_domain_rows():
    with patch.object(prs, "create_domain_approvals", return_value={"ok": True, "departments": ["Security & Compliance"], "error": None}) as create:
        with patch.object(prs, "get_db_cursor"):
            with patch.object(prs, "_mark_review_path"):
                with patch.object(prs, "get_review", return_value={"pr_number": 9, "title": "t", "head_branch": "fix/x"}):
                    prs.mark_review_done(9, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform", auto_merge=False)
    create.assert_called_once_with(9, "KytranKatarn/archie-platform")


def test_creation_failure_does_not_raise():
    """A GitHub outage must not break review completion — the gate refuses anyway."""
    with patch.object(prs, "create_domain_approvals", side_effect=RuntimeError("boom")):
        with patch.object(prs, "get_db_cursor"):
            with patch.object(prs, "_mark_review_path"):
                with patch.object(prs, "get_review", return_value={"pr_number": 9, "title": "t", "head_branch": "fix/x"}):
                    prs.mark_review_done(9, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform", auto_merge=False)
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_domain_signoff_creation.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'create_domain_approvals'`

- [ ] **Step 3: Wire it in**

At the top of `pr_review_service.py`, beside the other imports:

```python
from .pr_domain_approvals import create_domain_approvals  # noqa: E402
```

In `mark_review_done`, immediately AFTER the `UPDATE pr_reviews` block and BEFORE `_extract_review_path`:

```python
    # Create the per-department sign-off rows now that a review exists. Best-effort: a
    # GitHub outage must not break review completion. It is safe because the merge gate
    # refuses a PR with zero rows — a failure here BLOCKS the merge, never opens it.
    try:
        create_domain_approvals(pr_number, repo or _DEFAULT_REPO)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PR #%s: domain approval creation failed: %s", pr_number, exc)
```

- [ ] **Step 4: Run to verify it passes**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/test_domain_signoff_creation.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_review_service.py platform_v2/tests/test_domain_signoff_creation.py
git commit -m "feat(forge): create domain sign-off rows on review completion"
```

---

### Task 6: Surface in the Approvals tab + approve/reject endpoints

**Files:**
- Modify: `platform_v2/tools/department_hq/approvals_routes.py`

**Interfaces:**
- Consumes: table from Task 1
- Produces: `/api/approvals/pending` includes `id="domain:<row id>"`, `category="domain_signoff"`; `POST /api/approvals/domain/<int:row_id>/approve` and `/reject`

- [ ] **Step 1: Add the union block**

In `approvals_routes.py`, after the `hiring_candidates` block (section 4), add section 5:

```python
        # 5. pr_domain_approvals — per-department PR sign-off (Phase 1)
        cur.execute(
            """SELECT pda.id, pda.pr_number, pda.repo, pda.department,
                      pda.matched_paths, pda.created_at,
                      a.display_name AS director_name,
                      pr.title AS pr_title
                 FROM pr_domain_approvals pda
                 LEFT JOIN agents a ON a.id = pda.required_agent_id
                 LEFT JOIN pr_reviews pr
                        ON pr.pr_number = pda.pr_number AND pr.repo = pda.repo
                WHERE pda.status = 'pending'
                ORDER BY pda.created_at DESC"""
        )
        for r in cur.fetchall():
            r = dict(r)
            approvals.append(
                {
                    "id": f"domain:{r['id']}",
                    "source": "domain",
                    "source_id": r["id"],
                    "category": "domain_signoff",
                    "display_name": f"PR #{r['pr_number']} — {r['department']}",
                    "action_type": "domain_signoff",
                    "reason": (
                        f"{r['department']} owns "
                        f"{len(r.get('matched_paths') or [])} changed path(s) in "
                        f"PR #{r['pr_number']}: {r.get('pr_title') or ''}"
                    ),
                    "agent_name": r.get("director_name") or "—",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "payload": {
                        "pr_number": r["pr_number"],
                        "repo": r["repo"],
                        "matched_paths": r.get("matched_paths") or [],
                    },
                }
            )
```

- [ ] **Step 2: Add the decision endpoints**

Beside the existing hire approve/reject routes:

```python
    @bp.route("/api/approvals/domain/<int:row_id>/<any(approve,reject):decision>", methods=["POST"])
    @admin_required_decorator
    def decide_domain_signoff(row_id: int, decision: str):
        """Record a department director's decision on a PR touching their domain."""
        status = "approved" if decision == "approve" else "rejected"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE pr_domain_approvals
                      SET status = %s, deciding_agent_id = COALESCE(deciding_agent_id, required_agent_id),
                          decided_at = NOW()
                    WHERE id = %s AND status IN ('pending', 'escalated')
                RETURNING pr_number, department""",
                (status, row_id),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found or already decided"}), 409
        return jsonify({"success": True, "status": status, **dict(row)})
```

- [ ] **Step 3: Verify against the live endpoint**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "INSERT INTO pr_domain_approvals (pr_number, repo, department, matched_paths)
   VALUES (99999, 'KytranKatarn/archie-platform', 'Security & Compliance', '[\"platform_v2/rbac.py\"]'::jsonb);"
docker compose restart archie_platform
```
Then in a logged-in browser console on `/tools/department-hq`:
```js
await (await fetch('/tools/department-hq/api/approvals/pending', {credentials:'same-origin'})).json()
```
Expected: an entry with `id` starting `domain:` and `category: "domain_signoff"`.
Clean up: `DELETE FROM pr_domain_approvals WHERE pr_number = 99999;`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/approvals_routes.py
git commit -m "feat(dhq): surface department sign-off in the Approvals tab"
```

---

### Task 7: Ship it

- [ ] **Step 1: Full regression run**

Run: `docker exec -w /app archie_platform python3 -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -20`
Expected: no NEW failures. Known pre-existing on `main`: `test_forge_automerge_gate` (2), `test_agent_profile_get_extended` (1), `test_approvals_multi_source` (3), plus the 5 files still failing on cross-file `sys.modules` pollution (#5192).

- [ ] **Step 2: Push and open the PR**

```bash
git push --set-upstream origin feat/department-approval-authority
gh pr create --title "feat: department approval authority — Phase 1" --body "Implements docs/superpowers/specs/2026-07-25-department-approval-authority-design.md Phase 1."
```

- [ ] **Step 3: Deploy after merge — fast-forward FIRST**

```bash
cd /mnt/archie_brain && git fetch origin && git merge --ff-only origin/main
docker compose restart archie_platform archie_scheduler
```
The containers mount the MAIN checkout. Restarting without fast-forwarding deploys nothing while looking like success.

- [ ] **Step 4: Verify live**

```bash
docker exec -i archie_platform python3 - <<'PY'
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.github_service import _automerge_governance_ok as g
print('zero-rows refuses:', g(999999)[0] is False)
PY
```
Expected: `zero-rows refuses: True`

---

## Self-Review

**Spec coverage:** two-key (Tasks 4+5) · path map (Task 2) · `pr_domain_approvals` with split required/deciding columns (Task 1) · unified approvals surface (Task 6) · rejection blocks rather than escalates (Task 4) · fail-closed throughout (Tasks 3, 4). Welfare-gated wake and COO escalation are Phase 2 — the columns exist so the schema does not churn.

**Type consistency:** `resolve_owning_departments -> Dict[str, List[str]]` consumed by `create_domain_approvals`; `domain_approvals_status -> {total, approved, pending, rejected}` consumed by the gate. Names match across tasks.

**Known risk:** Task 4 Step 5 may surface tests that patch `_automerge_governance_ok`'s internals; the mitigation is stated inline rather than discovered at run time.
