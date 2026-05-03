"""Centralized navigation helpers. Currently: endpoint→module resolution.
Sibling helpers land in Task 2.

Pure functions. No Flask import here so unit tests can run without app context.
"""

from __future__ import annotations

import logging
from typing import Optional

from module_registry import MODULES

# Used by get_category_siblings in Task 2.
logger = logging.getLogger(__name__)


def _build_endpoint_map() -> dict[str, str]:
    """Build endpoint-prefix → module_id map at module load.

    Each module's `blueprint_import` field is `"tools.<module>.routes:<bp_var>"`.
    Flask endpoints registered by that blueprint look like `<bp_name>.<view>`.
    The blueprint name conventionally equals the module id (verified by tests).
    """
    out: dict[str, str] = {}
    for mod in MODULES:
        # dict (not set) so future entries can map alt blueprint names → canonical module_id
        out[mod.id] = mod.id
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


def _user_can_access(user, module_id: str) -> bool:
    """RBAC check — overridden by tests via monkeypatch.

    Wrapped in try/except so an RBAC error never breaks nav rendering.
    """
    if user is None:
        return True  # Tests pass user=None to mean "no RBAC filtering"
    try:
        from rbac import can_access_module

        # Note: rbac.can_access_module takes (module_id, user) — args swapped from our signature
        return can_access_module(module_id, user)
    except Exception:  # noqa: BLE001 — fail-open: never hide a module due to RBAC error
        return True


def get_category_siblings(module_id: str, user) -> list[dict]:
    """Return sibling modules in the same category as `module_id`.

    Filters: same category, enabled=True, coming_soon=False, RBAC visible (if
    user given), self excluded. Anonymous users (is_authenticated=False) get an
    empty list — no nav strip on login pages, OAuth callbacks, etc.

    Returns: list of dicts with keys: id, label, icon, url, external, active.
    """
    try:
        # Anonymous → no shortcuts (login pages, OAuth callbacks)
        if user is not None and not getattr(user, "is_authenticated", True):
            return []

        # Find the current module's category
        current_category = None
        for m in MODULES:
            if m.id == module_id:
                current_category = m.category
                break
        if current_category is None:
            return []

        out: list[dict] = []
        for m in MODULES:
            if m.id == module_id:
                continue
            if m.category != current_category:
                continue
            if not m.enabled or m.coming_soon:
                continue
            if user is not None and not _user_can_access(user, m.id):
                continue
            external_url = getattr(m, "external_url", "") or ""
            url = external_url if external_url else m.route
            out.append(
                {
                    "id": m.id,
                    "label": m.name,
                    "icon": m.icon,
                    "url": url,
                    "external": bool(external_url),
                    "active": False,
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001 — defensive: nav must never crash
        logger.warning("get_category_siblings failed for %s: %s", module_id, exc)
        return []
