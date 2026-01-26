"""
Dynamic Dashboard Generator
Generates personalized dashboard based on user's permissions and subscription

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""
from typing import List, Dict
from module_registry import get_enabled_modules, ModuleCategory
from rbac import can_access_module, get_user_role


def get_user_dashboard_data(user) -> Dict:
    """
    Generate dashboard data for a specific user

    Returns:
        {
            'modules_by_category': {
                'creation': [module1, module2],
                'development': [module3],
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
        modules_by_category[category].append({
            'id': module.id,
            'name': module.name,
            'description': module.description,
            'icon': module.icon,
            'route': module.route,
            'beta': module.beta,
            'coming_soon': module.coming_soon,
            'priority': module.priority,
            'accessible': True
        })

    # Sort modules within each category by priority
    for category in modules_by_category:
        modules_by_category[category].sort(key=lambda m: m['priority'])

    # Get locked modules info (for upgrade prompts)
    locked_modules = []
    for module in locked:
        locked_modules.append({
            'id': module.id,
            'name': module.name,
            'description': module.description,
            'icon': module.icon,
            'minimum_role': module.minimum_role,
            'category': module.category.value
        })

    # Get user role and subscription
    user_role = get_user_role(user)

    # Determine subscription tier - ADMIN users get "admin" tier display
    if user_role.name == 'ADMIN' or user_role.name == 'SUPER_ADMIN':
        subscription_tier = 'admin'
    elif hasattr(user, 'subscription_tier') and user.subscription_tier:
        subscription_tier = user.subscription_tier.lower()
    else:
        subscription_tier = 'free'

    return {
        'modules_by_category': modules_by_category,
        'accessible_count': len(accessible),
        'total_count': len(enabled_modules),
        'user_role': user_role.name,
        'subscription_tier': subscription_tier,
        'coming_soon_count': len([m for m in enabled_modules if m.coming_soon]),
        'locked_modules': locked_modules,
        'categories': get_categories_info()
    }


def get_categories_info() -> Dict[str, Dict]:
    """Get information about each module category - Dashboard Redesign 2026-01-13

    Icons use Lucide icon names - see https://lucide.dev/icons
    """
    # Define categories with priority (lower = displayed first)
    # Order: Creation → Business → Standalone → (Locked Modules) → Admin → Development → Integrations
    categories = {
        'creation': {
            'name': 'Creation Tools',
            'icon': 'sparkles',  # Lucide icon name
            'description': 'Build apps, websites, games, and media with AI assistance',
            'priority': 1
        },
        'business_tools': {
            'name': 'Business Tools',
            'icon': 'briefcase',  # Lucide icon name
            'description': 'Website, store, and phone system for your business',
            'priority': 2
        },
        'standalone_apps': {
            'name': 'Stand Alone Apps',
            'icon': 'smartphone',  # Lucide icon name
            'description': 'Unique AI apps available on Android, iOS, and Web subscriptions',
            'priority': 3
        },
        'admin_ops': {
            'name': 'Admin Operations',
            'icon': 'activity',  # Lucide icon name
            'description': 'Bridge command center, team management, and consciousness',
            'admin_only': True,
            'color': '#FF6B6B',  # Red color for admin-only sections
            'priority': 3.5  # Between Standalone Apps and Admin Tools
        },
        'admin': {
            'name': 'Admin Tools',
            'icon': 'settings-2',  # Lucide icon name
            'description': 'System management, backups, security, and accounts',
            'admin_only': True,
            'color': '#FF6B6B',  # Red color for admin tools
            'priority': 4
        },
        'development': {
            'name': 'Development Tools',
            'icon': 'code-2',  # Lucide icon name
            'description': 'Platform development & testing',
            'admin_only': True,  # Phase 22: All dev tools are admin only
            'color': '#FF6B6B',  # Red color for admin dev tools
            'priority': 5
        },
        'integrations': {
            'name': 'Integrations',
            'icon': 'plug',  # Lucide icon name
            'description': 'External services and automation',
            'priority': 6
        }
    }
    # Return sorted by priority
    return dict(sorted(categories.items(), key=lambda x: x[1]['priority']))


def render_module_card(module: Dict, user) -> str:
    """Render HTML for a single module card"""
    beta_badge = '<span class="badge badge-beta">BETA</span>' if module.get('beta') else ''
    coming_soon_badge = '<span class="badge badge-coming-soon">COMING SOON</span>' if module.get('coming_soon') else ''
    locked_badge = '<span class="badge badge-locked">🔒 LOCKED</span>' if not module.get('accessible', True) else ''

    card_class = 'tool-card'
    if module.get('coming_soon'):
        card_class += ' coming-soon'
    if not module.get('accessible', True):
        card_class += ' locked'

    href = module['route'] if module.get('accessible', True) else '#'

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
    if user_role == 'PUBLIC':
        return "Sign up for a free account to access all basic tools"
    elif user_role == 'USER':
        return f"Upgrade to Premium to unlock {locked_count} additional tools"
    elif user_role == 'PREMIUM':
        return "Enjoying A.R.C.H.I.E.? Consider upgrading to Business for team features"
    else:
        return ""
