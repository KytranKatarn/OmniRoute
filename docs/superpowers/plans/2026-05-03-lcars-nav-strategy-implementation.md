# LCARS Nav Convergence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge the platform's two parallel nav includes onto a single canonical `lcars-header.html`, with category siblings auto-derived from `module_registry.py` via a new helper service and Flask context processor.

**Architecture:** New `services/nav_service.py` exposes a pure `get_category_siblings(module_id, user)` function. A Flask context processor wires it into every template that includes `lcars-header.html`, with a per-route override path. Migration proceeds in 6 PRs: 1 pilot + 4 category waves + 1 cleanup. Defensive `try/except` in the processor ensures nav can never take down the platform.

**Tech Stack:** Python 3.12, Flask, Jinja2, pytest, Flask test client, Playwright (P.R.O.B.E.), psycopg2 (existing RBAC).

**Spec:** `docs/superpowers/specs/2026-05-03-lcars-nav-strategy-design.md`

---

## Schema Corrections Discovered During Phase 1 Implementation

Two assumptions in this plan turned out wrong. They were corrected in PR #515 (Phase 1 pilot) and **must be applied to every code block below** when executing remaining waves. The inline code in this plan still uses the original (incorrect) assumptions; treat that as historical and apply these corrections:

1. **`MODULES` is a `List[ModuleDefinition]`, NOT a dict.**
   - `for module_id, mod in MODULES.items()` → `for mod in MODULES` (then use `mod.id`)
   - `for sid, m in MODULES.items()` → `for m in MODULES` (then use `m.id`)
   - `MODULES.get(module_id)` → `next((m for m in MODULES if m.id == module_id), None)`
   - `MODULES[module_id]` → `next(m for m in MODULES if m.id == module_id)`

2. **`ModuleDefinition` has no `status` field.** Real fields are `enabled: bool`, `coming_soon: bool`, `beta: bool` (all on the dataclass).
   - `getattr(m, "status", "enabled") != "enabled"` → `not m.enabled or m.coming_soon`
   - `getattr(m, 'status', 'enabled') == 'enabled'` → `m.enabled and not m.coming_soon`
   - In docstrings: "status='enabled'" → "enabled and not coming_soon"
   - Note: `m.beta` is NOT a disable flag — beta modules should still appear in nav.

**Wave scope was also revised after audit.** Only 6 modules remain on `category_nav.html` (not ~14): `doc`, `fitness`, `therapy`, `archie_chat`, `social_media` (disabled), `system_operations` (disabled). The 4-wave plan compresses to 1-2 PRs of real migration plus the cleanup PR.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `platform_v2/services/nav_service.py` | NEW | Pure functions: endpoint→module mapping, sibling resolution, RBAC filter |
| `platform_v2/app.py` | MODIFY (+~10 lines) | Register `inject_category_siblings` context processor |
| `platform_v2/tests/test_nav_service.py` | NEW | Unit tests for `nav_service` (sibling resolution, RBAC, edge cases) |
| `platform_v2/tests/test_nav_context_processor.py` | NEW | Integration tests via Flask test client |
| `platform_v2/templates/tools/<module>.html` | MODIFY × ~14 modules | Swap include + drop old `cat_*` set blocks |
| `platform_v2/tools/<module>/routes.py` | MODIFY × ~14 modules | Drop hand-rolled `cat_modules=...` from `render_template` calls |
| `platform_v2/templates/includes/category_nav.html` | DELETE (PR 6) | Replaced by `lcars-header.html` |
| `platform_v2/static/css/category-nav.css` | DELETE (PR 6) | Replaced by `lcars-header.css` |

---

## Wave Migration Playbook

**Used by Tasks 7–10 (Waves 2–5).** Every per-module migration follows these steps verbatim.

For each module `M` in the wave's category:

1. **Read** `platform_v2/templates/tools/<M>.html` — locate the `{% include 'includes/category_nav.html' %}` block and any preceding `{% set cat_accent = ... %}` / `{% set cat_modules = ... %}` blocks.
2. **Replace** the include line:
   - Old: `{% include 'includes/category_nav.html' %}`
   - New: `{% include 'includes/lcars-header.html' %}`
3. **Update** the parameter set block:
   - Keep: `cat_accent`, `cat_accent_rgb`, `cat_label`
   - Add: `cat_accent_dark` (if not already set, copy from `cat_accent_light`), `module_title` (the module's display name from registry), `module_back_url` (default `/dashboard`)
   - **Remove**: `cat_modules` (now derived from registry by context processor)
   - **Remove**: `cat_icon` (now read from registry inside helper)
4. **Read** `platform_v2/tools/<M>/routes.py` — find any `render_template(...)` call passing `cat_modules=...`.
5. **Remove** `cat_modules=...` kwargs from those calls. Leave any `header_tabs=...` or `header_shortcuts=...` (per-module override path stays intact).
6. **Run** `docker exec archie_platform pytest platform_v2/tests/test_nav_context_processor.py::test_module_<M>_renders -v` — must PASS (we add this test in Task 6 for the pilot, then add one row per module in each wave's first step).
7. **Visual verify** via Playwright:
   - `mcp__plugin_playwright_playwright__browser_navigate` to `https://platform.kytranempowerment.com/tools/<M-route>`
   - `browser_take_screenshot` — save as `verify/wave<N>-<M>-dark.png`
   - Toggle light mode (click theme icon), screenshot as `verify/wave<N>-<M>-light.png`
   - Inspect both: nav strip renders, sibling pills present, no console 404s
8. **Run** `mcp__archie__run_qa_suite` for the module — must be green.

After all modules in the wave are migrated:

9. `git add` the touched files, commit with message `feat(nav): migrate <category> to lcars-header.html`
10. `git push -u origin feat/nav-converge-<category>`
11. `gh pr create` with title `feat(nav): converge <category> on lcars-header.html` and body listing the migrated modules + screenshot evidence + scan results
12. Wait for user review/approval, self-merge, **soak 24h** before next wave

---

## Phase 1 — Pilot (PR 1)

### Task 1: Build endpoint-to-module-id map

**Files:**
- Create: `platform_v2/services/nav_service.py`
- Test: `platform_v2/tests/test_nav_service.py`

- [ ] **Step 1: Write the failing test**

Create `platform_v2/tests/test_nav_service.py`:

```python
"""Unit tests for nav_service."""
import pytest
from services import nav_service


def test_endpoint_to_module_map_built_at_import():
    """ENDPOINT_TO_MODULE is populated from MODULES at module load."""
    assert isinstance(nav_service.ENDPOINT_TO_MODULE, dict)
    assert len(nav_service.ENDPOINT_TO_MODULE) > 0


def test_endpoint_to_module_resolves_known_module():
    """Known endpoint resolves to its module id."""
    # backup_manager blueprint registers 'backup_manager.*' endpoints
    assert nav_service.resolve_module_id("backup_manager.index") == "backup_manager"
    assert nav_service.resolve_module_id("backup_manager.backup_list") == "backup_manager"


def test_endpoint_to_module_unknown_returns_none():
    """Unknown endpoint returns None — caller treats as 'no shortcuts'."""
    assert nav_service.resolve_module_id("nonexistent.endpoint") is None
    assert nav_service.resolve_module_id("") is None
    assert nav_service.resolve_module_id(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py::test_endpoint_to_module_map_built_at_import -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.nav_service'`

- [ ] **Step 3: Write minimal implementation**

Create `platform_v2/services/nav_service.py`:

```python
"""Centralized navigation helpers — sibling resolution from module_registry.

Pure functions. No Flask import here so unit tests can run without app context.
"""
from __future__ import annotations

import logging
from typing import Optional

from module_registry import MODULES

logger = logging.getLogger(__name__)


def _build_endpoint_map() -> dict[str, str]:
    """Build endpoint-prefix → module_id map at module load.

    Each module's `blueprint_import` field is `"tools.<module>.routes:<bp_var>"`.
    Flask endpoints registered by that blueprint look like `<bp_name>.<view>`.
    The blueprint name conventionally equals the module id (verified by tests).
    """
    out: dict[str, str] = {}
    for module_id, mod in MODULES.items():
        # Map module_id directly — matches blueprint name convention
        out[module_id] = module_id
    return out


ENDPOINT_TO_MODULE: dict[str, str] = _build_endpoint_map()


def resolve_module_id(endpoint: Optional[str]) -> Optional[str]:
    """Return module_id for a Flask request.endpoint, or None if unknown.

    Endpoint format is "<blueprint>.<view>"; we match on the blueprint prefix.
    """
    if not endpoint:
        return None
    bp_prefix = endpoint.split(".", 1)[0]
    return ENDPOINT_TO_MODULE.get(bp_prefix)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/nav_service.py platform_v2/tests/test_nav_service.py
git commit -m "feat(nav): endpoint→module resolver scaffolding"
```

---

### Task 2: Implement `get_category_siblings()` core

**Files:**
- Modify: `platform_v2/services/nav_service.py`
- Test: `platform_v2/tests/test_nav_service.py`

- [ ] **Step 1: Write the failing test**

Append to `platform_v2/tests/test_nav_service.py`:

```python
def test_get_siblings_same_category_excludes_self():
    """Returns sibling modules in the same category, excluding the current module."""
    # backup_manager is in ADMIN_OPERATIONS along with security_network, account_center, etc.
    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    sibling_ids = {s["id"] for s in siblings}
    assert "backup_manager" not in sibling_ids
    assert "security_network" in sibling_ids


def test_get_siblings_returns_empty_for_unknown_module():
    """Unknown module → empty list, never raises."""
    assert nav_service.get_category_siblings("nonexistent_module", user=None) == []


def test_get_siblings_skips_disabled_modules():
    """Modules where status='disabled' do not appear in siblings."""
    # system_operations is disabled per registry
    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    sibling_ids = {s["id"] for s in siblings}
    assert "system_operations" not in sibling_ids


def test_get_siblings_returns_required_fields():
    """Each sibling has id, label, icon, url, external."""
    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    assert len(siblings) > 0
    for s in siblings:
        assert set(s.keys()) >= {"id", "label", "icon", "url", "external"}
        assert isinstance(s["external"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py -v`
Expected: 4 new tests FAIL with `AttributeError: module 'services.nav_service' has no attribute 'get_category_siblings'`.

- [ ] **Step 3: Implement get_category_siblings**

Append to `platform_v2/services/nav_service.py`:

```python
def get_category_siblings(module_id: str, user) -> list[dict]:
    """Return sibling modules in the same category as `module_id`.

    Filters: same category, status='enabled', RBAC visible (if user given), self excluded.

    Returns: list of dicts with keys: id, label, icon, url, external, active.
    """
    try:
        current = MODULES.get(module_id)
        if current is None:
            return []

        out: list[dict] = []
        for sid, m in MODULES.items():
            if sid == module_id:
                continue
            if m.category != current.category:
                continue
            if getattr(m, "status", "enabled") != "enabled":
                continue
            external_url = getattr(m, "external_url", "") or ""
            url = external_url if external_url else m.route
            out.append({
                "id": sid,
                "label": m.name,
                "icon": m.icon,
                "url": url,
                "external": bool(external_url),
                "active": False,
            })
        return out
    except Exception as exc:  # noqa: BLE001 — defensive: nav must never crash
        logger.warning("get_category_siblings failed for %s: %s", module_id, exc)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/nav_service.py platform_v2/tests/test_nav_service.py
git commit -m "feat(nav): core get_category_siblings with self-exclusion + disabled filter"
```

---

### Task 3: Add RBAC filter + external URL handling + override-no-op

**Files:**
- Modify: `platform_v2/services/nav_service.py`
- Test: `platform_v2/tests/test_nav_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_nav_service.py`:

```python
class FakeUser:
    def __init__(self, username, is_authenticated=True, allowed_modules=None):
        self.username = username
        self.is_authenticated = is_authenticated
        self._allowed = allowed_modules or set()

    def can_access_module(self, module_id):
        return module_id in self._allowed


def test_anonymous_user_returns_empty():
    """Unauthenticated user → empty siblings (no nav strip)."""
    user = FakeUser("anon", is_authenticated=False)
    assert nav_service.get_category_siblings("backup_manager", user) == []


def test_rbac_filters_unauthorized_siblings(monkeypatch):
    """User without RBAC for a sibling module sees it filtered out."""
    user = FakeUser("limited", allowed_modules={"backup_manager", "security_network"})
    monkeypatch.setattr(nav_service, "_user_can_access", lambda u, mid: u.can_access_module(mid))
    siblings = nav_service.get_category_siblings("backup_manager", user)
    sibling_ids = {s["id"] for s in siblings}
    # account_center is in ADMIN_OPERATIONS but user lacks access
    assert "security_network" in sibling_ids
    assert "account_center" not in sibling_ids


def test_external_url_module_marked_external():
    """Modules with external_url set carry external=True and url=external_url."""
    # Find any module with external_url in MODULES (Media Outreach products)
    from module_registry import MODULES
    external_mods = [mid for mid, m in MODULES.items() if getattr(m, "external_url", "")]
    assert external_mods, "test fixture: at least one external_url module must exist"
    target = external_mods[0]
    target_cat_member = next(
        (mid for mid, m in MODULES.items()
         if m.category == MODULES[target].category and mid != target),
        None,
    )
    if target_cat_member is None:
        pytest.skip("no sibling for external module in registry")
    siblings = nav_service.get_category_siblings(target_cat_member, user=None)
    match = next((s for s in siblings if s["id"] == target), None)
    assert match is not None
    assert match["external"] is True
    assert match["url"].startswith("http")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py -v`
Expected: 3 new tests FAIL (anonymous and RBAC have no implementation; external test may pass already).

- [ ] **Step 3: Add RBAC + auth handling**

Modify `platform_v2/services/nav_service.py` — replace the body of `get_category_siblings`:

```python
def _user_can_access(user, module_id: str) -> bool:
    """Default RBAC check — overridden by tests via monkeypatch.

    In production, integrates with rbac.user_has_module_access(user, module_id).
    """
    if user is None:
        return True  # Tests pass user=None to mean "no RBAC filtering"
    try:
        from rbac import user_has_module_access
        return user_has_module_access(user, module_id)
    except Exception:
        return True  # Fail-open: never hide a module due to RBAC import error


def get_category_siblings(module_id: str, user) -> list[dict]:
    """Return sibling modules in the same category as `module_id`.

    Filters: same category, status='enabled', RBAC visible (if user authenticated),
    self excluded. Anonymous users (is_authenticated=False) get an empty list.

    Returns: list of dicts with keys: id, label, icon, url, external, active.
    """
    try:
        # Anonymous → no shortcuts (login pages, OAuth callbacks)
        if user is not None and not getattr(user, "is_authenticated", True):
            return []

        current = MODULES.get(module_id)
        if current is None:
            return []

        out: list[dict] = []
        for sid, m in MODULES.items():
            if sid == module_id:
                continue
            if m.category != current.category:
                continue
            if getattr(m, "status", "enabled") != "enabled":
                continue
            if user is not None and not _user_can_access(user, sid):
                continue
            external_url = getattr(m, "external_url", "") or ""
            url = external_url if external_url else m.route
            out.append({
                "id": sid,
                "label": m.name,
                "icon": m.icon,
                "url": url,
                "external": bool(external_url),
                "active": False,
            })
        return out
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning("get_category_siblings failed for %s: %s", module_id, exc)
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_service.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/nav_service.py platform_v2/tests/test_nav_service.py
git commit -m "feat(nav): RBAC filtering + anonymous + external_url handling"
```

---

### Task 4: Build Flask context processor with override + memoization

**Files:**
- Modify: `platform_v2/app.py`
- Create: `platform_v2/tests/test_nav_context_processor.py`

- [ ] **Step 1: Write the failing integration test**

Create `platform_v2/tests/test_nav_context_processor.py`:

```python
"""Integration tests for inject_category_siblings context processor."""
from unittest.mock import patch

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def test_processor_injects_shortcuts_on_module_page(app, client, login_admin):
    """A request to a tool route receives header_shortcuts in template context."""
    captured = {}

    def fake_render(template_name, **ctx):
        captured.update(ctx)
        return "ok"

    with patch("flask.render_template", side_effect=fake_render):
        resp = client.get("/tools/backup-manager")
    assert resp.status_code == 200
    assert "header_shortcuts" in captured
    assert isinstance(captured["header_shortcuts"], list)


def test_processor_respects_route_override(app, client, login_admin):
    """If a route already provides header_shortcuts, processor does not overwrite."""
    sentinel = [{"id": "x", "label": "X", "icon": "x", "url": "/x", "external": False}]
    captured = {}

    def fake_render(template_name, **ctx):
        captured.update(ctx)
        return "ok"

    # Simulate a route that hands its own list
    with patch("flask.render_template", side_effect=fake_render):
        with app.test_request_context("/tools/backup-manager"):
            from flask import g
            g.header_shortcuts_override = sentinel
            resp = client.get("/tools/backup-manager")
    # When override sentinel is present, processor must respect it
    # (test runs again without override — second call should auto-fill)
    assert "header_shortcuts" in captured


def test_processor_never_raises(app):
    """Even with broken module registry, processor returns empty list, not error."""
    from services import nav_service
    with patch.object(nav_service, "get_category_siblings", side_effect=RuntimeError("boom")):
        with app.test_request_context("/tools/backup-manager"):
            from app import inject_category_siblings
            ctx = inject_category_siblings()
            assert ctx == {"header_shortcuts": []}


def test_processor_anonymous_returns_empty(app, client):
    """Unauthenticated request → empty shortcuts."""
    captured = {}

    def fake_render(template_name, **ctx):
        captured.update(ctx)
        return "ok"

    with patch("flask.render_template", side_effect=fake_render):
        resp = client.get("/login")
    if "header_shortcuts" in captured:
        assert captured["header_shortcuts"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_context_processor.py -v`
Expected: tests FAIL with `ImportError: cannot import name 'inject_category_siblings' from 'app'`.

- [ ] **Step 3: Implement context processor in app.py**

Open `platform_v2/app.py` and add (near the top of the function-level definitions, after blueprint registrations):

```python
from flask import g, request

from services import nav_service


@app.context_processor
def inject_category_siblings():
    """Auto-populate `header_shortcuts` for any template that includes lcars-header.html.

    Per-request memoized via flask.g. If the route already set
    g.header_shortcuts_override, the override wins. Defensive: never raises.
    """
    try:
        # Per-request memoization
        if hasattr(g, "_nav_shortcuts_cached"):
            return {"header_shortcuts": g._nav_shortcuts_cached}

        # Per-route override path
        override = getattr(g, "header_shortcuts_override", None)
        if override is not None:
            g._nav_shortcuts_cached = override
            return {"header_shortcuts": override}

        # Resolve current module from request endpoint
        endpoint = getattr(request, "endpoint", None)
        module_id = nav_service.resolve_module_id(endpoint)
        if module_id is None:
            g._nav_shortcuts_cached = []
            return {"header_shortcuts": []}

        from flask_login import current_user
        shortcuts = nav_service.get_category_siblings(module_id, current_user)
        g._nav_shortcuts_cached = shortcuts
        return {"header_shortcuts": shortcuts}
    except Exception as exc:  # noqa: BLE001 — defensive
        import logging
        logging.getLogger(__name__).warning(
            "inject_category_siblings failed: %s", exc
        )
        return {"header_shortcuts": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_context_processor.py -v`
Expected: 4 passed (or document any conftest fixtures needed for `login_admin`).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/app.py platform_v2/tests/test_nav_context_processor.py
git commit -m "feat(nav): inject_category_siblings context processor with override + memoization"
```

---

### Task 5: Migrate `backup_manager` template + route (pilot module)

**Files:**
- Modify: `platform_v2/templates/tools/backup_manager.html`
- Modify: `platform_v2/tools/backup_manager/routes.py`

- [ ] **Step 1: Read current state**

Run: `grep -n "category_nav.html\|cat_modules\|cat_accent" platform_v2/templates/tools/backup_manager.html`

Note the line numbers and the `{% set cat_* %}` blocks. Note any `cat_modules=[...]` in `routes.py`:
`grep -n "cat_modules" platform_v2/tools/backup_manager/routes.py`

- [ ] **Step 2: Update the template**

Edit `platform_v2/templates/tools/backup_manager.html`. Replace the include block. Old looks like:

```jinja
{% set cat_accent = '#FFAA00' %}
{% set cat_accent_rgb = '255,170,0' %}
{% set cat_label = 'ADMIN OPS' %}
{% set cat_icon = 'shield-check' %}
{% set cat_modules = [...] %}
{% include 'includes/category_nav.html' %}
```

New:

```jinja
{% set cat_accent = '#FFAA00' %}
{% set cat_accent_rgb = '255,170,0' %}
{% set cat_accent_dark = '#cc8800' %}
{% set cat_label = 'ADMIN OPS' %}
{% set module_title = 'BACKUP MANAGER' %}
{% set module_back_url = '/dashboard' %}
{% include 'includes/lcars-header.html' %}
```

(Note: `cat_icon` and `cat_modules` are removed — both now derived by the helper.)

- [ ] **Step 3: Update the route**

Edit `platform_v2/tools/backup_manager/routes.py`. Find every `render_template(...)` call that passes `cat_modules=`:

```python
# Old
return render_template(
    "tools/backup_manager.html",
    cat_modules=[
        {"label": "Security", "icon": "shield", "url": "/tools/security-network"},
        ...
    ],
    other_kwarg=...,
)

# New
return render_template(
    "tools/backup_manager.html",
    other_kwarg=...,
)
```

Remove only `cat_modules=...` — keep all other kwargs.

- [ ] **Step 4: Add a regression test for the route render**

Append to `platform_v2/tests/test_nav_context_processor.py`:

```python
def test_module_backup_manager_renders(client, login_admin):
    """Pilot module loads with new include + helper-injected shortcuts."""
    resp = client.get("/tools/backup-manager")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "lcars-header" in body
    assert "category_nav" not in body  # Old include is gone from this page
```

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_context_processor.py::test_module_backup_manager_renders -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/backup_manager.html \
        platform_v2/tools/backup_manager/routes.py \
        platform_v2/tests/test_nav_context_processor.py
git commit -m "feat(nav): migrate backup_manager to lcars-header.html (pilot)"
```

---

### Task 6: Visual verify pilot + open PR 1

**Files:**
- None (verification only)

- [ ] **Step 1: Deploy locally**

Run: `docker compose restart archie_platform`
Wait ~10s for boot.

- [ ] **Step 2: Playwright dark-mode screenshot**

```
mcp__plugin_playwright_playwright__browser_navigate
  url: https://platform.kytranempowerment.com/tools/backup-manager
mcp__plugin_playwright_playwright__browser_take_screenshot
  filename: verify/pr1-pilot-dark.png
```

Inspect: nav strip renders, sibling pills present (Security, Account Center, etc.), no console 404s.

- [ ] **Step 3: Playwright light-mode screenshot**

```
mcp__plugin_playwright_playwright__browser_click  selector: "[onclick*='toggleTheme']"
mcp__plugin_playwright_playwright__browser_take_screenshot
  filename: verify/pr1-pilot-light.png
```

Inspect light-mode rendering.

- [ ] **Step 4: Run module-scoped P.R.O.B.E. scan**

Run via MCP: `mcp__archie__run_qa_suite` for the `backup_manager` module — must be green.

- [ ] **Step 5: Push branch and open PR**

```bash
git push -u origin feat/nav-converge-pilot
gh pr create --title "feat(nav): pilot — converge backup_manager on lcars-header.html" --body "$(cat <<'EOF'
## Summary

Pilot PR for the LCARS nav convergence (Project #212, Task #1652). Implements:

- New `services/nav_service.py` — pure helper for sibling resolution, RBAC-aware
- New `inject_category_siblings()` Flask context processor in `app.py` — defensive, memoized, override-aware
- Migrates `backup_manager` (1 module) as the pilot
- Test coverage: `test_nav_service.py` (10 tests), `test_nav_context_processor.py` (5 tests)

## Verification

- Unit + integration tests green: `docker exec archie_platform pytest platform_v2/tests/test_nav_*.py -v`
- Dark-mode screenshot: `verify/pr1-pilot-dark.png`
- Light-mode screenshot: `verify/pr1-pilot-light.png`
- P.R.O.B.E. backup_manager suite: green

## Spec

`docs/superpowers/specs/2026-05-03-lcars-nav-strategy-design.md` (PR #514)

## Test plan

- [x] Unit tests pass
- [x] Integration tests pass
- [x] Visual verification (dark + light)
- [x] P.R.O.B.E. green
- [ ] User reviews and approves
- [ ] Self-merge after approval, soak 24h before Wave 2

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Wait for review, self-merge, soak**

Per `feedback_pr-management.md`: pause until user reviews. After approval, run `gh pr merge --squash --delete-branch`. Soak 24h before kicking off Wave 2.

---

## Phase 2 — Wave 2: Admin Ops (PR 2)

### Task 7: Migrate Admin Ops category

**Files:**
- Modify: every template + route in `ADMIN_OPERATIONS` category except `backup_manager` (already done)

- [ ] **Step 1: Enumerate the category from registry**

Run inside Docker:

```bash
docker exec archie_platform python3 -c "
from module_registry import MODULES, ModuleCategory
for mid, m in MODULES.items():
    if m.category == ModuleCategory.ADMIN_OPERATIONS and getattr(m, 'status', 'enabled') == 'enabled' and mid != 'backup_manager':
        print(mid, '->', m.route)
"
```

Record the list (typically: `security_network`, `account_center`, `saas_manager`).

- [ ] **Step 2: Create the wave branch**

```bash
git checkout main && git pull
git checkout -b feat/nav-converge-admin-ops
```

- [ ] **Step 3: Migrate each module per the Wave Migration Playbook above**

For each module in the enumerated list, follow Playbook steps 1–8. Then add a per-module render test to `platform_v2/tests/test_nav_context_processor.py`:

```python
def test_module_<M>_renders(client, login_admin):
    resp = client.get("<M-route>")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "lcars-header" in body
    assert "category_nav" not in body
```

- [ ] **Step 4: Run all nav tests**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_*.py -v`
Expected: all PASS, including new per-module render tests.

- [ ] **Step 5: Visual verification**

For each migrated module, capture dark + light Playwright screenshots:
- `verify/pr2-<M>-dark.png`
- `verify/pr2-<M>-light.png`

Inspect each pair: nav strip renders, sibling pills point to the right modules, no console 404s.

- [ ] **Step 6: Run P.R.O.B.E. for each migrated module**

Run via MCP `mcp__archie__run_qa_suite` for each module — must be green.

- [ ] **Step 7: Commit, push, open PR**

```bash
git add platform_v2/templates/tools/ platform_v2/tools/ platform_v2/tests/
git commit -m "feat(nav): converge ADMIN_OPERATIONS on lcars-header.html"
git push -u origin feat/nav-converge-admin-ops
gh pr create --title "feat(nav): converge Admin Ops on lcars-header.html (Wave 2)" --body "<!-- list migrated modules + screenshots + scan results -->"
```

- [ ] **Step 8: Wait for review, self-merge, soak**

Soak 24h after merge before Wave 3.

---

## Phase 3 — Wave 3: SaaS Services (PR 3)

### Task 8: Migrate SAAS_SERVICES category

**Files:**
- Modify: every enabled template + route in `SAAS_SERVICES` category

- [ ] **Step 1: Enumerate the category**

Run inside Docker:

```bash
docker exec archie_platform python3 -c "
from module_registry import MODULES, ModuleCategory
for mid, m in MODULES.items():
    if m.category == ModuleCategory.SAAS_SERVICES and getattr(m, 'status', 'enabled') == 'enabled':
        print(mid, '->', m.route)
"
```

Record the list. Note: `kytran_business_suite` may have `external_url` set — it migrates the same way (the helper handles `external` flag automatically).

- [ ] **Step 2: Create wave branch**

```bash
git checkout main && git pull
git checkout -b feat/nav-converge-saas
```

- [ ] **Step 3: Migrate each module per the Wave Migration Playbook**

Same as Task 7 Step 3, plus per-module render tests in `test_nav_context_processor.py`.

- [ ] **Step 4: Run all nav tests**

Run: `docker exec archie_platform pytest platform_v2/tests/test_nav_*.py -v`
Expected: all PASS.

- [ ] **Step 5: Visual verification**

Dark + light Playwright screenshots per module: `verify/pr3-<M>-{dark,light}.png`.

- [ ] **Step 6: P.R.O.B.E. green per module**

Run `mcp__archie__run_qa_suite` for each.

- [ ] **Step 7: Commit, push, open PR**

```bash
git add platform_v2/templates/tools/ platform_v2/tools/ platform_v2/tests/
git commit -m "feat(nav): converge SAAS_SERVICES on lcars-header.html"
git push -u origin feat/nav-converge-saas
gh pr create --title "feat(nav): converge SaaS Services on lcars-header.html (Wave 3)" --body "<!-- list migrated modules + screenshots + scan results -->"
```

- [ ] **Step 8: Wait for review, self-merge, soak**

Soak 24h before Wave 4.

---

## Phase 4 — Wave 4: Applications & Concepts (PR 4)

### Task 9: Migrate APPLICATIONS_CONCEPTS category

**Files:**
- Modify: every enabled template + route in `APPLICATIONS_CONCEPTS` category

- [ ] **Step 1: Enumerate the category**

```bash
docker exec archie_platform python3 -c "
from module_registry import MODULES, ModuleCategory
for mid, m in MODULES.items():
    if m.category == ModuleCategory.APPLICATIONS_CONCEPTS and getattr(m, 'status', 'enabled') == 'enabled':
        print(mid, '->', m.route)
"
```

Typical: `media_hub`, `family_tree`, `fitness`, `therapy`, `doc`.

- [ ] **Step 2: Create wave branch**

```bash
git checkout main && git pull
git checkout -b feat/nav-converge-applications
```

- [ ] **Step 3: Migrate each module per Wave Migration Playbook**

- [ ] **Step 4: Run all nav tests** — must pass.

- [ ] **Step 5: Dark + light screenshots** — `verify/pr4-<M>-{dark,light}.png`.

- [ ] **Step 6: P.R.O.B.E. green per module.**

- [ ] **Step 7: Commit, push, open PR**

```bash
git add platform_v2/templates/tools/ platform_v2/tools/ platform_v2/tests/
git commit -m "feat(nav): converge APPLICATIONS_CONCEPTS on lcars-header.html"
git push -u origin feat/nav-converge-applications
gh pr create --title "feat(nav): converge Applications on lcars-header.html (Wave 4)" --body "<!-- list + screenshots + scans -->"
```

- [ ] **Step 8: Wait for review, self-merge, soak 24h**

---

## Phase 5 — Wave 5: Creative + Crypto (PR 5)

### Task 10: Migrate CREATIVE_STUDIOS + CRYPTO categories

**Files:**
- Modify: every enabled template + route in `CREATIVE_STUDIOS` and `CRYPTO` categories

- [ ] **Step 1: Enumerate both categories**

```bash
docker exec archie_platform python3 -c "
from module_registry import MODULES, ModuleCategory
targets = (ModuleCategory.CREATIVE_STUDIOS, ModuleCategory.CRYPTO)
for mid, m in MODULES.items():
    if m.category in targets and getattr(m, 'status', 'enabled') == 'enabled':
        print(m.category.value, mid, '->', m.route)
"
```

Typical: `media_studio`, `game_studio`, `archie_pool`, `pool_management`.

- [ ] **Step 2: Create wave branch**

```bash
git checkout main && git pull
git checkout -b feat/nav-converge-creative-crypto
```

- [ ] **Step 3: Migrate each module per Wave Migration Playbook**

- [ ] **Step 4: Run all nav tests** — must pass.

- [ ] **Step 5: Dark + light screenshots** — `verify/pr5-<M>-{dark,light}.png`.

- [ ] **Step 6: P.R.O.B.E. green per module.**

Note: `media_studio` is large — pay extra attention to the queue panel (Decision #440 + PR #464 area) doesn't break.

- [ ] **Step 7: Commit, push, open PR**

```bash
git add platform_v2/templates/tools/ platform_v2/tools/ platform_v2/tests/
git commit -m "feat(nav): converge CREATIVE_STUDIOS + CRYPTO on lcars-header.html"
git push -u origin feat/nav-converge-creative-crypto
gh pr create --title "feat(nav): converge Creative + Crypto on lcars-header.html (Wave 5)" --body "<!-- list + screenshots + scans -->"
```

- [ ] **Step 8: Wait for review, self-merge, SOAK 48h before Wave 6**

48h soak before cleanup PR — cleanup is the riskiest step.

---

## Phase 6 — Cleanup (PR 6)

### Task 11: Delete legacy nav files + bump static asset version

**Files:**
- Delete: `platform_v2/templates/includes/category_nav.html`
- Delete: `platform_v2/static/css/category-nav.css`
- Modify: `platform_v2/app.py` (bump static asset version)

- [ ] **Step 1: Verify no remaining references**

Run:

```bash
grep -rn "category_nav.html" platform_v2/templates/ platform_v2/tools/
grep -rnE "\.cn-|\.nav-modules|\.nav-category-label" platform_v2/static/css/
```

Expected output: empty (no matches in either grep). If any matches remain, abort and fix the source — the cleanup PR may not orphan working modules.

- [ ] **Step 2: Create cleanup branch**

```bash
git checkout main && git pull
git checkout -b chore/nav-cleanup
```

- [ ] **Step 3: Delete the files**

```bash
git rm platform_v2/templates/includes/category_nav.html
git rm platform_v2/static/css/category-nav.css
```

- [ ] **Step 4: Bump static asset cache-bust version**

Find the asset version constant in `platform_v2/app.py` (search for `STATIC_VERSION` or similar). Increment it. Example:

```python
# Before
STATIC_VERSION = "5.32.0"

# After
STATIC_VERSION = "5.33.0"  # nav cleanup, force browser cache refresh
```

- [ ] **Step 5: Run full test suite**

Run: `docker exec archie_platform pytest platform_v2/tests/ -v`
Expected: all green.

- [ ] **Step 6: Smoke test every category in browser**

Spot-check one module per category via Playwright (dark + light) to confirm nothing broke from the file deletion.

- [ ] **Step 7: Commit, push, open PR**

```bash
git add platform_v2/app.py platform_v2/templates/includes/category_nav.html platform_v2/static/css/category-nav.css
git commit -m "chore(nav): delete category_nav.html + category-nav.css; bump static version"
git push -u origin chore/nav-cleanup
gh pr create --title "chore(nav): cleanup — delete legacy nav files (Wave 6 — final)" --body "$(cat <<'EOF'
## Summary

Final wave of LCARS nav convergence. All modules migrated to `lcars-header.html` across PRs 1–5. This PR removes the deprecated files and bumps the static asset version to bust browser caches.

## Verification

- `grep -r 'category_nav.html' platform_v2/` → 0 matches
- `grep -rE '\.cn-|\.nav-modules|\.nav-category-label' platform_v2/static/css/` → 0 matches
- Full test suite green
- Smoke test: one module per category (dark + light) — all clean

## Closes

- Decision #398 (UI nav blocker) — RESOLVED
- Project #212 — 100% complete
- Task #1652 — DONE

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 8: Wait for review, self-merge**

After merge, no further wave — convergence is complete.

---

## Phase 7 — Closeout

### Task 12: Resolve Decision #398, log followups, update Project #212

**Files:**
- None (MCP calls only)

- [ ] **Step 1: Log resolution decision**

Call `mcp__archie__log_decision` with:
- decision: "LCARS nav convergence complete — single canonical include lcars-header.html, sibling shortcuts auto-derived from module_registry"
- context: "Project #212 reaches 100%. Decision #398 resolved. PRs 514 (spec) + pilot + 4 wave PRs + cleanup PR all merged. Spec at docs/superpowers/specs/2026-05-03-lcars-nav-strategy-design.md."
- project_id: 212

- [ ] **Step 2: Update Project #212**

Call `mcp__archie__update_project_status` to mark Project #212 as completed.

- [ ] **Step 3: Mark Task #1652 complete**

Call `mcp__archie__complete_task` with id 1652 and notes referencing the cleanup PR merge.

- [ ] **Step 4: Create followup tasks**

Call `mcp__archie__create_task` for:
1. "Translate shortcut labels via i18n_prefix" — Project #290
2. "Audit per-module shortcut overrides — confirm none need custom lists" — Project #212 (or close as out-of-scope if not needed)

- [ ] **Step 5: Store learning in KB**

Call `mcp__archie__store_memory` with knowledge_type='vault_note', tags including 'lcars', 'nav', 'convergence', summarizing the migration approach for future reference.

---

## Self-Review Checklist (run before handoff)

- [ ] Spec coverage: every section of `2026-05-03-lcars-nav-strategy-design.md` maps to a task above
- [ ] Placeholder scan: zero `TBD`/`TODO`/`add appropriate ...` strings
- [ ] Type consistency: `get_category_siblings` signature matches across Tasks 2, 3, 4 — `(module_id: str, user) -> list[dict]`
- [ ] Sibling dict keys consistent: `id, label, icon, url, external, active` everywhere
- [ ] Wave PR title pattern consistent: `feat(nav): converge <CATEGORY> on lcars-header.html (Wave N)`
- [ ] Cleanup PR title pattern: `chore(nav): cleanup — delete legacy nav files (Wave 6 — final)`
- [ ] Branch naming consistent: `feat/nav-converge-<category>` for waves, `chore/nav-cleanup` for PR 6

---

## Total Effort Estimate

| Phase | Tasks | Approx. Sessions |
|---|---|---|
| Phase 1 (Pilot) | 6 | 1 session (~2 hours) |
| Phase 2 (Admin Ops) | 1 | 0.5 session (~1 hour) |
| Phase 3 (SaaS) | 1 | 1–1.5 sessions (~9 modules) |
| Phase 4 (Apps) | 1 | 1 session (~5 modules) |
| Phase 5 (Creative + Crypto) | 1 | 0.5–1 session (~4 modules) |
| Phase 6 (Cleanup) | 1 | 0.5 session |
| Phase 7 (Closeout) | 1 | 0.25 session |
| **Total** | **12 tasks** | **~5–6 sessions across ~2 weeks (with soak periods)** |
