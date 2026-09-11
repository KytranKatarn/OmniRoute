"""
Dynamic Dashboard Generator
Generates personalized dashboard based on user's permissions and subscription

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

import re
from typing import Dict, List, Optional
from module_registry import get_enabled_modules
from rbac import can_access_module, get_user_role


# Tier hierarchy — higher index = more access
TIER_ORDER = ["explorer", "starter", "professional", "enterprise", "vip", "staff"]


def _user_meets_tier(user_tier: str, required_tier: str) -> bool:
    """Check if user's subscription tier meets the minimum requirement."""
    user_idx = TIER_ORDER.index(user_tier) if user_tier in TIER_ORDER else 0
    req_idx = TIER_ORDER.index(required_tier) if required_tier in TIER_ORDER else 0
    return user_idx >= req_idx


def get_featured_modules(user, pinned_ids: Optional[List[str]] = None) -> list:
    """Get featured/pinned modules for dashboard hero section.

    Returns a list of module dicts for the Priority Stations section.
    Default pins: archie_chat, bridge, consciousness.
    """
    default_pins = ["archie_chat", "bridge", "consciousness"]
    pin_ids = pinned_ids if pinned_ids else default_pins

    enabled_modules = get_enabled_modules()
    featured = []
    for module in enabled_modules:
        if module.id in pin_ids and can_access_module(module.id, user):
            # Extract clean Lucide icon name from module icon field.
            # module.icon is typically a plain name like "brain" or "monitor".
            # If it ever contains HTML like '<i data-lucide="brain"></i>',
            # extract just the icon name.
            icon_name = module.icon or "box"
            lucide_match = re.search(r'data-lucide="([^"]+)"', icon_name)
            if lucide_match:
                icon_name = lucide_match.group(1)
            # Strip any remaining HTML tags as safety
            icon_name = re.sub(r"<[^>]+>", "", icon_name).strip() or "box"

            featured.append(
                {
                    "id": module.id,
                    "name": module.name,
                    "description": module.description,
                    "icon": icon_name,
                    "route": module.route,
                    "category": module.category.value,
                    "external_url": module.external_url,
                }
            )

    # Maintain pin order
    return sorted(
        featured,
        key=lambda m: pin_ids.index(m["id"]) if m["id"] in pin_ids else 99,
    )


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

    # Get user role and subscription tier
    user_role = get_user_role(user)
    is_admin = user_role.name in ("ADMIN", "SUPER_ADMIN")

    # Determine subscription tier — admins map to "staff"
    if is_admin:
        subscription_tier = "admin"
        effective_tier = "staff"
    elif hasattr(user, "subscription_tier") and user.subscription_tier:
        subscription_tier = user.subscription_tier.lower()
        effective_tier = subscription_tier if subscription_tier in TIER_ORDER else "explorer"
    else:
        subscription_tier = "free"
        effective_tier = "explorer"

    # Categorize modules: accessible, tier-locked, or hidden
    accessible = []
    locked = []
    modules_by_category = {}

    for module in enabled_modules:
        if not module.show_on_dashboard:
            continue

        has_role = can_access_module(module.id, user)
        has_tier = _user_meets_tier(effective_tier, module.minimum_tier)

        # Staff-only modules are HIDDEN entirely for non-admin users
        if module.minimum_tier == "staff" and not is_admin:
            continue

        category = module.category.value
        if category not in modules_by_category:
            modules_by_category[category] = []

        if has_role and has_tier:
            # Fully accessible
            accessible.append(module)
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
                    "locked": False,
                    "required_tier": None,
                    "external_url": module.external_url,
                }
            )
        else:
            # Tier-locked — show with blur overlay
            locked.append(module)
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
                    "accessible": False,
                    "locked": True,
                    "required_tier": module.minimum_tier,
                    "external_url": module.external_url,
                }
            )

    # Sort modules within each category by priority
    for category in modules_by_category:
        modules_by_category[category].sort(key=lambda m: m["priority"])

    # Remove empty categories
    modules_by_category = {k: v for k, v in modules_by_category.items() if v}

    # Legacy locked_modules list (for upgrade prompt text)
    locked_modules = [
        {
            "id": module.id,
            "name": module.name,
            "description": module.description,
            "icon": module.icon,
            "minimum_role": module.minimum_role,
            "category": module.category.value,
        }
        for module in locked
    ]

    return {
        "modules_by_category": modules_by_category,
        "accessible_count": len(accessible),
        "total_count": len(enabled_modules),
        "user_role": user_role.name,
        "subscription_tier": subscription_tier,
        "coming_soon_count": len([m for m in enabled_modules if m.coming_soon]),
        "locked_modules": locked_modules,
        "locked_count": len(locked),
        "categories": get_categories_info(),
        "featured_modules": get_featured_modules(user),
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
        "what_the_fact": {
            "name": "What The Fact",
            "icon": "fas fa-newspaper",
            "description": "Bridge orchestration + public product for what-the-fact.com",
            "color": "#3b82f6",
            "priority": 3,
        },
        "creed": {
            "name": "C.R.E.E.D.",
            "icon": "fas fa-scale-balanced",
            "description": "Ethics and governance — internal command deck and the public institute",
            "color": "#a855f7",
            "priority": 4,
        },
        "saas_services": {
            "name": "SaaS Services",
            "icon": "fas fa-cloud",
            "description": "Customer-facing business services",
            "priority": 5,
        },
        "project_knowledge": {
            "name": "Project & Knowledge",
            "icon": "fas fa-book",
            "description": "Project management and knowledge base",
            "priority": 6,
        },
        "applications_concepts": {
            "name": "Applications & Concepts",
            "icon": "fas fa-lightbulb",
            "description": "Applications, media hub, and concept modules",
            "priority": 7,
        },
        "crypto": {
            "name": "Crypto",
            "icon": "fas fa-coins",
            "description": "Cryptocurrency mining and pool management",
            "priority": 8,
        },
        "watch_series": {
            "name": "The Watch Series",
            "icon": "fas fa-binoculars",
            "description": "Civic intelligence products: Gov, Market, Legal and Civic Watch",
            "priority": 9,
        },
        "creative_studios": {
            "name": "Creative Studios",
            "icon": "fas fa-palette",
            "description": "Game development and media creation",
            "priority": 10,
        },
        "placeholders_future": {
            "name": "Coming Soon",
            "icon": "fas fa-rocket",
            "description": "Planned features for future development",
            "priority": 11,
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
