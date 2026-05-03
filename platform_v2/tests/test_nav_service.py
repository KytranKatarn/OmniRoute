"""Unit tests for nav_service."""

import importlib

import pytest

from module_registry import MODULES
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


def _importable_modules_with_blueprints():
    """Yield (mod_id, module_path, bp_var) for every MODULES entry that
    declares a blueprint_import. Disabled modules (no on-disk package) are
    surfaced via the import attempt in the test itself, not pre-filtered,
    so the test logs a clear skip reason per case.
    """
    for mod in MODULES:
        bp_import = getattr(mod, "blueprint_import", None)
        if not bp_import or ":" not in bp_import:
            continue
        module_path, bp_var = bp_import.split(":", 1)
        yield mod.id, module_path, bp_var


@pytest.mark.parametrize(
    "mod_id, module_path, bp_var",
    list(_importable_modules_with_blueprints()),
    ids=lambda v: v if isinstance(v, str) else str(v),
)
def test_blueprint_name_matches_module_id(mod_id, module_path, bp_var):
    """Convention check: every MODULES entry's Flask Blueprint.name == mod.id.

    nav_service._build_endpoint_map relies on this — endpoints look like
    "<bp_name>.<view>" and we match the prefix against module_id directly.
    If a blueprint diverges (e.g. registered as 'dept_hq' while
    mod.id == 'department_hq'), resolve_module_id will silently return None
    for valid endpoints. This test catches that drift at PR time.

    Disabled modules (declared in registry but no on-disk package) skip with
    a clear reason — they don't register routes at runtime either.
    """
    try:
        m = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        pytest.skip(
            f"{mod_id}: blueprint module {module_path!r} not importable "
            f"(disabled module, no on-disk package): {exc}"
        )

    bp = getattr(m, bp_var, None)
    assert bp is not None, f"{mod_id}: blueprint variable {bp_var!r} missing in {module_path}"
    assert bp.name == mod_id, (
        f"Blueprint name convention violation: mod.id={mod_id!r} but "
        f"Blueprint.name={bp.name!r} (from {module_path}:{bp_var}). "
        f"Either rename the blueprint or add an explicit alias entry to "
        f"nav_service._build_endpoint_map."
    )


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


from dataclasses import replace as _dc_replace


def _make_stub_module(template, **overrides):
    """Build a ModuleDefinition stub by cloning an existing module with overrides.

    Uses dataclasses.replace so we don't have to enumerate the full schema.
    """
    return _dc_replace(template, **overrides)


def test_get_siblings_excludes_disabled_modules(monkeypatch):
    """Modules where enabled=False are excluded from siblings (deterministic)."""
    from module_registry import MODULES as REAL_MODULES

    template = next(m for m in REAL_MODULES if m.id == "backup_manager")
    fake_disabled = _make_stub_module(
        template,
        id="fake_disabled_test_module",
        name="Fake Disabled",
        enabled=False,
    )
    monkeypatch.setattr(nav_service, "MODULES", REAL_MODULES + [fake_disabled])

    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    sibling_ids = {s["id"] for s in siblings}
    assert "fake_disabled_test_module" not in sibling_ids


def test_get_siblings_excludes_coming_soon_modules(monkeypatch):
    """Modules where coming_soon=True are excluded from siblings (deterministic)."""
    from module_registry import MODULES as REAL_MODULES

    template = next(m for m in REAL_MODULES if m.id == "backup_manager")
    fake_coming = _make_stub_module(
        template,
        id="fake_coming_soon_test_module",
        name="Fake Coming Soon",
        coming_soon=True,
    )
    monkeypatch.setattr(nav_service, "MODULES", REAL_MODULES + [fake_coming])

    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    sibling_ids = {s["id"] for s in siblings}
    assert "fake_coming_soon_test_module" not in sibling_ids


def test_get_siblings_returns_required_fields():
    """Each sibling has id, label, icon, url, external."""
    siblings = nav_service.get_category_siblings("backup_manager", user=None)
    assert len(siblings) > 0
    for s in siblings:
        assert set(s.keys()) >= {"id", "label", "icon", "url", "external", "active"}
        assert isinstance(s["external"], bool)


# ---------------------------------------------------------------------------
# Task 3 — RBAC + anonymous + external_url
# ---------------------------------------------------------------------------


class FakeUser:
    """Stub matching the bits of flask_login.current_user that we use.

    Production passes `current_user` from flask_login. Tests use this to avoid
    needing a real Flask app context.
    """

    def __init__(self, username, is_authenticated=True, allowed_modules=None):
        self.username = username
        self.is_authenticated = is_authenticated
        self._allowed = allowed_modules or set()

    def can_access(self, module_id: str) -> bool:
        return module_id in self._allowed


def test_anonymous_user_returns_empty():
    """Unauthenticated user → empty siblings (no nav strip on login/OAuth pages)."""
    user = FakeUser("anon", is_authenticated=False)
    assert nav_service.get_category_siblings("backup_manager", user) == []


def test_authenticated_user_with_no_rbac_filter_sees_all_siblings(monkeypatch):
    """Authenticated user with permissive RBAC sees all enabled siblings in category."""
    user = FakeUser("admin", is_authenticated=True)
    # Force _user_can_access to allow everything
    monkeypatch.setattr(nav_service, "_user_can_access", lambda u, mid: True)
    siblings = nav_service.get_category_siblings("backup_manager", user)
    assert len(siblings) > 0
    sibling_ids = {s["id"] for s in siblings}
    assert "security_network" in sibling_ids


def test_rbac_filters_unauthorized_siblings(monkeypatch):
    """User without RBAC for a sibling module sees it filtered out."""
    user = FakeUser("limited", is_authenticated=True, allowed_modules={"backup_manager", "security_network"})
    monkeypatch.setattr(
        nav_service,
        "_user_can_access",
        lambda u, mid: u.can_access(mid),
    )
    siblings = nav_service.get_category_siblings("backup_manager", user)
    sibling_ids = {s["id"] for s in siblings}
    # security_network is allowed; account_center is in ADMIN_OPERATIONS but user lacks access
    assert "security_network" in sibling_ids
    assert "account_center" not in sibling_ids


def test_external_url_module_marked_external():
    """Modules with external_url set carry external=True and url=external_url."""
    from module_registry import MODULES

    external_mods = [m for m in MODULES if getattr(m, "external_url", "") and m.enabled]
    if not external_mods:
        pytest.skip("no external_url module in registry")
    target = external_mods[0]
    target_cat_member = next(
        (m for m in MODULES if m.category == target.category and m.id != target.id and m.enabled and not m.coming_soon),
        None,
    )
    if target_cat_member is None:
        pytest.skip("no enabled sibling for external module to test from")

    siblings = nav_service.get_category_siblings(target_cat_member.id, user=None)
    match = next((s for s in siblings if s["id"] == target.id), None)
    # user=None bypasses RBAC, so the target MUST appear (no defensive skip)
    assert match is not None, f"external module {target.id} should appear in siblings"
    assert match["external"] is True
    assert match["url"].startswith("http")


def test_rbac_exception_falls_open(monkeypatch):
    """If rbac.can_access_module raises, _user_can_access returns True (fail-open).

    Nav strip must never break the page — even on RBAC system errors.
    """

    def boom(module_id, user):
        raise RuntimeError("rbac broke")

    monkeypatch.setattr("rbac.can_access_module", boom)
    user = FakeUser("u", is_authenticated=True)
    # Should NOT raise; should return siblings (fail-open via _user_can_access)
    siblings = nav_service.get_category_siblings("backup_manager", user)
    assert isinstance(siblings, list)
    # Fail-open means the user sees siblings as if RBAC weren't filtering
    assert len(siblings) > 0
