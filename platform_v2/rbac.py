"""
Role-Based Access Control (RBAC) System
Enforces permission-based access control across the ARCHIE Platform

Purpose:
- Define role hierarchy (PUBLIC → USER → PREMIUM → ADMIN → SUPER_ADMIN)
- Map permissions to roles
- Provide decorators for route protection
- Check user permissions programmatically

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

from enum import Enum
from typing import List, Set
from functools import wraps

try:
    from flask import abort, redirect, url_for, request
    from flask_login import current_user

    FLASK_AVAILABLE = True
except ImportError:
    # Allow running without Flask for testing
    FLASK_AVAILABLE = False
    current_user = None

    def abort(code):
        raise PermissionError(f"Access denied (HTTP {code})")


class Role(Enum):
    """User roles with numeric hierarchy"""

    PUBLIC = 0  # Not logged in
    USER = 10  # Basic authenticated user
    PREMIUM = 20  # Paid subscriber
    ADMIN = 90  # Administrator
    SUPER_ADMIN = 100  # System owner


class Permission(Enum):
    """
    System permissions - functional capabilities, not module-specific.

    Module access is controlled via module_registry.py where modules specify
    their required permissions. These permissions are generic and can be
    reused across multiple modules.

    Module Consolidation (2026-02-03):
    - media_hub uses: No special permissions (USER access)
    - project_manager uses: ADMIN_PROJECTS permission
    - automations uses: AUTOMATION_* permissions
    - sandbox_manager uses: ADMIN_SANDBOX, ADMIN_TESTING permissions
    - bridge uses: ADMIN_FINE_TUNING, ADMIN_IDE permissions
    - team_management uses: ADMIN_USERS permission
    - crm uses: ANALYTICS_VIEW permission
    """

    # Public (no login required)
    PUBLIC_VIEW = "public:view"

    # User permissions
    USER_CHAT = "archie:chat"
    CODE_EDITOR_READ = "code_editor:read"
    CODE_EDITOR_WRITE = "code_editor:write"
    USER_SETTINGS = "user:settings"
    READ_OWN = "read:own"
    WRITE_OWN = "write:own"
    AUTOMATION_CREATE = "automation:create"
    AUTOMATION_MANAGE = "automation:manage"
    TASK_PLANNER_SCHEDULE = "task_planner:schedule"
    TASK_PLANNER_CALENDAR = "task_planner:calendar"
    GOOGLE_EMAIL = "google:email"
    GOOGLE_CONTACTS = "google:contacts"
    GOOGLE_CALENDAR = "google:calendar"

    # Premium permissions
    APP_BUILDER_CREATE = "app_builder:create"
    APP_BUILDER_DEPLOY = "app_builder:deploy"
    APP_BUILDER_UNLIMITED = "app_builder:unlimited"
    SOCIAL_MEDIA_CREATE = "social_media:create"
    SOCIAL_MEDIA_SCHEDULE = "social_media:schedule"
    MEDIA_STUDIO_GENERATE = "media_studio:generate"
    MEDIA_STUDIO_MANAGE = "media_studio:manage"
    # DEPRECATED 2026-02-03: Not needed
    # FIGMA_IMPORT = "figma:import"
    ANALYTICS_VIEW = "analytics:view"

    # Admin permissions
    ADMIN_ACCESS = "admin:access"
    ADMIN_AGENTS = "admin:agents"
    ADMIN_IMPROVEMENTS = "admin:improvements"
    ADMIN_DEV_PIPELINE = "admin:repair_bay"
    ADMIN_USERS = "admin:users"
    ADMIN_BACKUPS = "admin:backups"
    ADMIN_LOGS = "admin:logs"
    ADMIN_SANDBOX = "admin:sandbox"
    ADMIN_FINE_TUNING = "admin:fine_tuning"
    ADMIN_IDE = "admin:ide"
    ADMIN_TESTING = "admin:testing"
    ADMIN_PROJECTS = "admin:projects"  # Phase 65: Unified Project Management
    READ_ALL = "read:all"
    WRITE_ALL = "write:all"

    # Autonomy permissions
    AUTONOMY_MANAGE = "autonomy:manage"

    # Super Admin permissions
    ADMIN_MINING = "admin:mining"
    ADMIN_SYSTEM = "admin:system"
    ADMIN_SAAS = "admin:saas"
    ADMIN_SECURITY = "admin:security"
    SUPER_ADMIN_ALL = "superadmin:all"


# ============================================================================
# ROLE PERMISSION MAPPINGS
# ============================================================================

ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.PUBLIC: {
        Permission.PUBLIC_VIEW,
    },
    Role.USER: {
        # Inherit PUBLIC
        Permission.PUBLIC_VIEW,
        # USER specific
        Permission.CODE_EDITOR_READ,
        Permission.CODE_EDITOR_WRITE,
        Permission.USER_SETTINGS,
        Permission.READ_OWN,
        Permission.WRITE_OWN,
        # App Builder (limited: 1 project/month for FREE users)
        Permission.APP_BUILDER_CREATE,
        # Automations: admin-only (N8N global proxy, not multi-tenant yet)
        # Task Planner (basic scheduling)
        Permission.TASK_PLANNER_SCHEDULE,
        Permission.TASK_PLANNER_CALENDAR,
        # Google Workspace integration
        Permission.GOOGLE_EMAIL,
        Permission.GOOGLE_CONTACTS,
        Permission.GOOGLE_CALENDAR,
    },
    Role.PREMIUM: {
        # Inherit USER
        Permission.PUBLIC_VIEW,
        Permission.CODE_EDITOR_READ,
        Permission.CODE_EDITOR_WRITE,
        Permission.USER_SETTINGS,
        Permission.READ_OWN,
        Permission.WRITE_OWN,
        Permission.APP_BUILDER_CREATE,
        Permission.TASK_PLANNER_SCHEDULE,
        Permission.TASK_PLANNER_CALENDAR,
        Permission.GOOGLE_EMAIL,
        Permission.GOOGLE_CONTACTS,
        Permission.GOOGLE_CALENDAR,
        # PREMIUM specific
        Permission.APP_BUILDER_DEPLOY,
        Permission.APP_BUILDER_UNLIMITED,  # Unlimited projects
        Permission.SOCIAL_MEDIA_CREATE,
        Permission.SOCIAL_MEDIA_SCHEDULE,
        Permission.MEDIA_STUDIO_GENERATE,
        Permission.MEDIA_STUDIO_MANAGE,
        # DEPRECATED 2026-02-03: Not needed
        # Permission.FIGMA_IMPORT,
        Permission.ANALYTICS_VIEW,
    },
    Role.ADMIN: {
        # Inherit PREMIUM
        Permission.PUBLIC_VIEW,
        Permission.USER_CHAT,
        Permission.CODE_EDITOR_READ,
        Permission.CODE_EDITOR_WRITE,
        Permission.USER_SETTINGS,
        Permission.READ_OWN,
        Permission.WRITE_OWN,
        Permission.APP_BUILDER_CREATE,
        Permission.APP_BUILDER_DEPLOY,
        Permission.APP_BUILDER_UNLIMITED,
        Permission.SOCIAL_MEDIA_CREATE,
        Permission.SOCIAL_MEDIA_SCHEDULE,
        Permission.MEDIA_STUDIO_GENERATE,
        Permission.MEDIA_STUDIO_MANAGE,
        # DEPRECATED 2026-02-03: Not needed
        # Permission.FIGMA_IMPORT,
        Permission.ANALYTICS_VIEW,
        Permission.AUTOMATION_CREATE,
        Permission.AUTOMATION_MANAGE,
        Permission.TASK_PLANNER_SCHEDULE,
        Permission.TASK_PLANNER_CALENDAR,
        Permission.GOOGLE_EMAIL,
        Permission.GOOGLE_CONTACTS,
        Permission.GOOGLE_CALENDAR,
        # ADMIN specific
        Permission.ADMIN_ACCESS,
        Permission.ADMIN_AGENTS,
        Permission.ADMIN_IMPROVEMENTS,
        Permission.ADMIN_USERS,
        Permission.ADMIN_BACKUPS,
        Permission.ADMIN_LOGS,
        Permission.ADMIN_SANDBOX,
        Permission.ADMIN_FINE_TUNING,
        Permission.ADMIN_IDE,
        Permission.ADMIN_TESTING,
        Permission.ADMIN_PROJECTS,  # Phase 65: Unified Project Management
        Permission.ADMIN_SYSTEM,  # Phase 78: System Operations access
        Permission.ADMIN_SAAS,  # SaaS Manager access
        Permission.AUTONOMY_MANAGE,  # Project Autonomy: Agent Loop
        Permission.READ_ALL,
        Permission.WRITE_ALL,
    },
    Role.SUPER_ADMIN: set(Permission),  # All permissions
}


# ============================================================================
# PERMISSION CHECKING FUNCTIONS
# ============================================================================


def get_user_role(user=None) -> Role:
    """
    Get the current user's role

    Args:
        user: Flask-Login user object (defaults to current_user)

    Returns:
        Role enum value
    """
    if user is None:
        user = current_user

    if not user or not user.is_authenticated:
        return Role.PUBLIC

    # Check user role attribute
    if hasattr(user, "is_super_admin") and user.is_super_admin:
        return Role.SUPER_ADMIN
    elif hasattr(user, "is_admin") and user.is_admin:
        return Role.ADMIN
    elif hasattr(user, "subscription_tier"):
        # Map subscription tiers to roles
        tier = user.subscription_tier.lower() if user.subscription_tier else "free"
        if tier in ["pro", "business", "enterprise", "premium"]:
            return Role.PREMIUM
        else:
            return Role.USER
    else:
        return Role.USER


def get_role_permissions(role: Role) -> Set[Permission]:
    """Get all permissions for a specific role"""
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(permission: Permission, user=None) -> bool:
    """
    Check if a user has a specific permission

    Args:
        permission: Permission to check
        user: User object (defaults to current_user)

    Returns:
        True if user has permission, False otherwise
    """
    role = get_user_role(user)
    role_perms = get_role_permissions(role)
    return permission in role_perms


def has_any_permission(permissions: List[Permission], user=None) -> bool:
    """Check if user has ANY of the specified permissions"""
    return any(has_permission(p, user) for p in permissions)


def has_all_permissions(permissions: List[Permission], user=None) -> bool:
    """Check if user has ALL of the specified permissions"""
    return all(has_permission(p, user) for p in permissions)


def has_role(role: Role, user=None) -> bool:
    """Check if user has a specific role (or higher)"""
    user_role = get_user_role(user)
    return user_role.value >= role.value


def get_user_permissions(user=None) -> Set[Permission]:
    """Get all permissions for the current user"""
    role = get_user_role(user)
    return get_role_permissions(role)


# ============================================================================
# ROUTE DECORATORS
# ============================================================================


def require_permission(permission: Permission, status_code: int = 403):
    """
    Decorator to require a specific permission for a route

    Usage:
        @app.route('/admin/dashboard')
        @require_permission(Permission.ADMIN_ACCESS)
        def admin_dashboard():
            return "Admin Dashboard"

    Args:
        permission: Required permission
        status_code: HTTP status code to return if forbidden (default 403)
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_permission(permission):
                abort(status_code)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_any_permission(*permissions: Permission, status_code: int = 403):
    """
    Decorator to require ANY of the specified permissions

    Usage:
        @require_any_permission(Permission.ADMIN_ACCESS, Permission.READ_ALL)
        def view_data():
            return "Data"
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_any_permission(list(permissions)):
                abort(status_code)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_all_permissions(*permissions: Permission, status_code: int = 403):
    """
    Decorator to require ALL of the specified permissions

    Usage:
        @require_all_permissions(Permission.ADMIN_ACCESS, Permission.WRITE_ALL)
        def modify_system():
            return "Modified"
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_all_permissions(list(permissions)):
                abort(status_code)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_role(role: Role, status_code: int = 403):
    """
    Decorator to require a specific role (or higher)

    Usage:
        @require_role(Role.ADMIN)
        def admin_panel():
            return "Admin Panel"
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_role(role):
                abort(status_code)
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def tier_required(minimum_tier):
    """Decorator to gate routes by subscription tier.

    Usage: @tier_required("starter") on a route.
    Tiers in order: explorer, starter, professional, enterprise, vip, staff
    Admin users bypass (they have 'staff' tier).
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))

            # Admin bypass
            if getattr(current_user, "is_admin", False):
                return f(*args, **kwargs)

            # Get user's tier
            from services.subscription_service import get_user_membership_tier

            user_role = getattr(current_user, "role", "") or ""
            user_tier = get_user_membership_tier(current_user.id, user_role)

            tier_order = ["explorer", "starter", "professional", "enterprise", "vip", "staff"]
            user_idx = tier_order.index(user_tier) if user_tier in tier_order else 0
            req_idx = tier_order.index(minimum_tier) if minimum_tier in tier_order else 0

            if user_idx >= req_idx:
                return f(*args, **kwargs)

            # Redirect to subscribe page for the module
            module_id = request.view_args.get("module_id", "")
            if not module_id:
                parts = request.path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] == "tools":
                    module_id = parts[1]

            if module_id:
                return redirect(f"/subscribe/{module_id}")
            return redirect("/dashboard")

        return decorated_function

    return decorator


# ============================================================================
# PERMISSION HELPERS
# ============================================================================


def can_access_module(module_id: str, user=None) -> bool:
    """
    Check if user can access a specific module (integrates with module_registry)

    Args:
        module_id: Module identifier from module_registry
        user: User object (defaults to current_user)

    Returns:
        True if user can access the module, False otherwise
    """
    try:
        from module_registry import get_module_by_id

        module = get_module_by_id(module_id)
        if not module or not module.enabled:
            return False

        # Check role requirement
        if not has_role(Role[module.minimum_role], user):
            return False

        # Check permissions
        if module.required_permissions:
            required = [Permission(p) for p in module.required_permissions]
            return has_all_permissions(required, user)

        return True

    except Exception as e:
        # If module_registry not available, deny access
        print(f"[RBAC] Error checking module access: {e}")
        return False


def get_accessible_modules(user=None) -> List[str]:
    """Get list of module IDs the user can access"""
    try:
        from module_registry import get_all_modules

        accessible = []
        for module in get_all_modules():
            if can_access_module(module.id, user):
                accessible.append(module.id)

        return accessible

    except Exception as e:
        print(f"[RBAC] Error getting accessible modules: {e}")
        return []


# ============================================================================
# AUDIT LOGGING
# ============================================================================


def log_permission_check(permission: Permission, granted: bool, user=None):
    """
    Log permission checks for audit purposes

    Args:
        permission: Permission that was checked
        granted: Whether access was granted
        user: User object
    """
    if user is None:
        user = current_user

    try:
        from tools.database import db
        from datetime import datetime

        user_id = user.id if user and hasattr(user, "id") else None
        username = user.username if user and hasattr(user, "username") else "Anonymous"

        # Log to audit_log table if it exists
        query = """
            INSERT INTO audit_log (user_id, username, action, details, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """

        details = f"Permission check: {permission.value} - {'GRANTED' if granted else 'DENIED'}"

        with db.engine.connect() as conn:
            conn.execute(
                db.text(query),
                (user_id, username, "PERMISSION_CHECK", details, datetime.now()),
            )
            conn.commit()

    except Exception as e:
        # Don't fail if audit logging fails
        print(f"[RBAC] Audit logging failed: {e}")


# ============================================================================
# TESTING & DEBUGGING
# ============================================================================


def get_rbac_summary(user=None) -> dict:
    """Get summary of user's RBAC status"""
    role = get_user_role(user)
    permissions = get_user_permissions(user)

    return {
        "role": role.name,
        "role_level": role.value,
        "permission_count": len(permissions),
        "permissions": [p.value for p in sorted(permissions, key=lambda x: x.value)],
        "can_access_admin": has_permission(Permission.ADMIN_ACCESS, user),
        "is_premium": has_role(Role.PREMIUM, user),
    }


if __name__ == "__main__":
    # Test RBAC system
    print("=" * 80)
    print("RBAC SYSTEM TEST")
    print("=" * 80)

    # Test each role
    for role in Role:
        perms = get_role_permissions(role)
        print(f"\n{role.name} ({role.value}):")
        print(f"  Permissions: {len(perms)}")

        # Show first 5 permissions
        for i, perm in enumerate(sorted(perms, key=lambda x: x.value)[:5]):
            print(f"    - {perm.value}")
        if len(perms) > 5:
            print(f"    ... and {len(perms) - 5} more")

    print("\n" + "=" * 80)
    print("Permission Hierarchy Examples:")
    print("=" * 80)

    test_cases = [
        (Role.PUBLIC, Permission.PUBLIC_VIEW),
        (Role.USER, Permission.CODE_EDITOR_WRITE),
        (Role.PREMIUM, Permission.APP_BUILDER_CREATE),
        (Role.ADMIN, Permission.ADMIN_ACCESS),
        (Role.SUPER_ADMIN, Permission.ADMIN_MINING),
    ]

    for role, permission in test_cases:
        perms = get_role_permissions(role)
        has_it = permission in perms
        status = "✅" if has_it else "❌"
        print(f"{status} {role.name} -> {permission.value}")

    print("\n" + "=" * 80)
