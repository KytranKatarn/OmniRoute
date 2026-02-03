"""
Dynamic Dashboard Generator
Generates personalized dashboard based on user's permissions and subscription

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

from typing import Dict
from module_registry import get_enabled_modules
from rbac import can_access_module, get_user_role


def get_user_dashboard_data(user) -> Dict:
    """
    Generate dashboard data for a specific user

    Returns:
        {
            'modules_by_category': {
                'admin_operations': [module1, module2],
                'ai_command': [module3],
                ...
            },
            'accessible_count': 15,
            'total_count': 20,
            'user_role': 'PREMIUM',
            'subscription_tier': 'pro',
            'coming_soon_count': 5,
            'locked_modules': [...]
        }
    """
    enabled_modules = get_enabled_modules()

    # Filter modules by user access
    accessible = []
    locked = []

    for module in enabled_modules:
        if can_access_module(module.id, user):
            accessible.append(module)
        else:
            locked.append(module)

    # Group accessible modules by category
    modules_by_category = {}
    for module in accessible:
        category = module.category.value
        if category not in modules_by_category:
            modules_by_category[category] = []
        modules_by_category[category].append(
            {
                "id": module.id,
                "name": module.name,
                "description": module.description,
                "icon": module.icon,
                "route": module.route,
                "beta": module.beta,
                "coming_soon": module.coming_soon,
                "priority": module.priority,
                "accessible": True,
            }
        )

    # Sort modules within each category by priority
    for category in modules_by_category:
        modules_by_category[category].sort(key=lambda m: m["priority"])

    # Get locked modules info (for upgrade prompts)
    locked_modules = []
    for module in locked:
        locked_modules.append(
            {
                "id": module.id,
                "name": module.name,
                "description": module.description,
                "icon": module.icon,
                "minimum_role": module.minimum_role,
                "category": module.category.value,
            }
        )

    # Get user role and subscription
    user_role = get_user_role(user)

    # Determine subscription tier - ADMIN users get "admin" tier display
    if user_role.name == "ADMIN" or user_role.name == "SUPER_ADMIN":
        subscription_tier = "admin"
    elif hasattr(user, "subscription_tier") and user.subscription_tier:
        subscription_tier = user.subscription_tier.lower()
    else:
        subscription_tier = "free"

    return {
        "modules_by_category": modules_by_category,
        "accessible_count": len(accessible),
        "total_count": len(enabled_modules),
        "user_role": user_role.name,
        "subscription_tier": subscription_tier,
        "coming_soon_count": len([m for m in enabled_modules if m.coming_soon]),
        "locked_modules": locked_modules,
        "categories": get_categories_info(),
    }


def get_categories_info() -> Dict[str, Dict]:
    """Get information about each module category - Updated 2026-02-03

    Icons use Font Awesome icon names (fas fa-*).
    Categories aligned with ModuleCategory enum in module_registry.py.
    """
    categories = {
        "admin_operations": {
            "name": "Admin Operations",
            "icon": "fas fa-shield-alt",
            "description": "Platform management and system administration",
            "admin_only": True,
            "color": "#FF6B6B",
            "priority": 1,
        },
        "ai_command": {
            "name": "AI Command",
            "icon": "fas fa-brain",
            "description": "AI infrastructure, agents, and learning systems",
            "admin_only": True,
            "color": "#FF6B6B",
            "priority": 2,
        },
        "development_tools": {
            "name": "Development Tools",
            "icon": "fas fa-code",
            "description": "Code quality, testing, and improvements",
            "admin_only": True,
            "color": "#FF6B6B",
            "priority": 3,
        },
        "saas_services": {
            "name": "SaaS Services",
            "icon": "fas fa-cloud",
            "description": "Customer-facing business services",
            "priority": 4,
        },
        "project_knowledge": {
            "name": "Project & Knowledge",
            "icon": "fas fa-book",
            "description": "Project management and knowledge base",
            "priority": 5,
        },
        "media_home": {
            "name": "Media & Home",
            "icon": "fas fa-film",
            "description": "Media management and home automation",
            "priority": 6,
        },
        "placeholders_future": {
            "name": "Coming Soon",
            "icon": "fas fa-rocket",
            "description": "Planned features for future development",
            "priority": 7,
        },
    }
    # Return sorted by priority
    return dict(sorted(categories.items(), key=lambda x: x[1]["priority"]))


def render_module_card(module: Dict, user) -> str:
    """Render HTML for a single module card"""
    beta_badge = '<span class="badge badge-beta">BETA</span>' if module.get("beta") else ""
    coming_soon_badge = '<span class="badge badge-coming-soon">COMING SOON</span>' if module.get("coming_soon") else ""
    locked_badge = '<span class="badge badge-locked">🔒 LOCKED</span>' if not module.get("accessible", True) else ""

    card_class = "tool-card"
    if module.get("coming_soon"):
        card_class += " coming-soon"
    if not module.get("accessible", True):
        card_class += " locked"

    href = module["route"] if module.get("accessible", True) else "#"

    return f"""
    <a href="{href}" class="{card_class}">
        <div class="tool-icon">{module['icon']}</div>
        <div class="tool-title">{module['name']}</div>
        <div class="tool-description">
            {module['description']}
            {beta_badge}
            {coming_soon_badge}
            {locked_badge}
        </div>
    </a>
    """


def get_upgrade_prompt(user_role: str, locked_count: int) -> str:
    """Generate upgrade prompt based on user's current tier"""
    if user_role == "PUBLIC":
        return "Sign up for a free account to access all basic tools"
    elif user_role == "USER":
        return f"Upgrade to Premium to unlock {locked_count} additional tools"
    elif user_role == "PREMIUM":
        return "Enjoying A.R.C.H.I.E.? Consider upgrading to Business for team features"
    else:
        return ""
