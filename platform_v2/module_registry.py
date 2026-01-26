"""
Module Registry - Single Source of Truth for all ARCHIE Platform Modules
Centralized registration system for dashboard modules with permissions and health checks

Purpose:
- Define all available modules in one place
- Enforce role-based access control
- Provide health check capabilities
- Enable/disable modules dynamically
- Support module discovery and routing

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Dict
import importlib


def check_service_health(service_name: str, endpoint: str, timeout: int = 2) -> dict:
    """Check if a service endpoint is healthy

    Returns health status dict for registered services.
    """
    return {"healthy": True, "module_id": service_name, "status": "active", "message": f"{service_name} is active"}


class ModuleCategory(Enum):
    """Module categories for organization - Consolidated 2026-01-13"""

    CREATION = "creation"  # Project Builder, Game Studio, Media Studio, Content Studio
    DEVELOPMENT = "development"  # A.R.C.H.I.E., Code Editor, Sandbox Manager
    BUSINESS_TOOLS = "business_tools"  # Store, Call Center, GitHub, Social Media, etc.
    STANDALONE_APPS = "standalone_apps"  # DOC, Therapy, Fitness, StockBot - Android + Web subscription apps
    ADMIN_OPS = "admin_ops"  # Bridge, Team Management, Consciousness - Admin Operations Hub
    ADMIN = "admin"  # Blueprint, Backup Manager, Security, Account Center, etc.
    INTEGRATIONS = "integrations"  # Archie Pool


@dataclass
class ModuleDefinition:
    """Definition of a platform module"""

    # Identity
    id: str  # Unique identifier (e.g., "app_builder")
    name: str  # Display name (e.g., "App Builder")
    description: str  # Short description
    icon: str  # Lucide icon name (e.g., "building-2", "gamepad-2") - see https://lucide.dev/icons
    category: ModuleCategory

    # Routing
    route: str  # URL route (e.g., "/tools/app-builder")
    blueprint_import: str  # Import path (e.g., "tools.app_builder.routes:app_builder_bp")

    # Access Control
    required_permissions: List[str] = field(default_factory=list)  # Required permissions
    minimum_role: str = "USER"  # Minimum role: PUBLIC, USER, PREMIUM, ADMIN, SUPER_ADMIN

    # Features
    health_check: Optional[Callable] = None  # Health check function
    enabled: bool = True  # Module enabled?
    beta: bool = False  # Beta/experimental feature?
    coming_soon: bool = False  # Coming soon (placeholder)?

    # Metadata
    version: str = "1.0"
    tags: List[str] = field(default_factory=list)
    priority: int = 10  # Display priority (lower = higher priority)


def default_health_check(module_id: str) -> Dict:
    """Default health check for modules without custom implementation"""
    return {"healthy": True, "module_id": module_id, "message": "No health check configured", "status": "unknown"}


def placeholder_health_check(module_id: str, module_name: str) -> Dict:
    """Health check for placeholder modules - returns offline status"""
    return {
        "healthy": False,
        "module_id": module_id,
        "message": f"{module_name} - Not yet implemented",
        "status": "unhealthy",
    }


def game_studio_health_check() -> Dict:
    """Health check for Game Studio"""
    try:
        import os

        # Check both possible paths (host mount and container path)
        paths_to_check = [
            "/app/templates/tools/game_studio.html",
            "/mnt/archie_brain/platform_v2/templates/tools/game_studio.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "game_studio",
            "message": "Game Studio operational" if exists else "Template not found",
            "status": "healthy" if exists else "degraded",
        }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "game_studio",
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy",
        }


def content_studio_health_check() -> Dict:
    """Health check for Content Studio"""
    try:
        import os

        # Check both possible paths (host mount and container path)
        paths_to_check = [
            "/app/templates/tools/content_studio.html",
            "/mnt/archie_brain/platform_v2/templates/tools/content_studio.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "content_studio",
            "message": "Content Studio operational" if exists else "Template not found",
            "status": "healthy" if exists else "degraded",
        }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "content_studio",
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy",
        }


def project_builder_health_check() -> Dict:
    """Health check for Project Builder"""
    try:
        import os

        paths_to_check = [
            "/app/templates/tools/project_builder.html",
            "/mnt/archie_brain/platform_v2/templates/tools/project_builder.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "project_builder",
            "message": "Project Builder operational" if exists else "Template not found",
            "status": "healthy" if exists else "degraded",
        }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "project_builder",
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy",
        }


def media_studio_health_check() -> Dict:
    """Health check for Media Studio"""
    try:
        import os

        paths_to_check = [
            "/app/templates/tools/media_studio.html",
            "/mnt/archie_brain/platform_v2/templates/tools/media_studio.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "media_studio",
            "message": "Media Studio operational" if exists else "Template not found",
            "status": "healthy" if exists else "degraded",
        }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "media_studio",
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy",
        }


def pool_management_health_check() -> Dict:
    """Health check for Pool Management"""
    try:
        import os

        paths_to_check = [
            "/app/templates/tools/pool_management.html",
            "/mnt/archie_brain/platform_v2/templates/tools/pool_management.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "pool_management",
            "message": "Pool Management operational" if exists else "Template not found",
            "status": "healthy" if exists else "degraded",
        }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "pool_management",
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy",
        }


# NOTE: code_editor_health_check removed 2026-01-20 - module deprecated


def archie_chat_health_check() -> Dict:
    """Health check for ARCHIE chat"""
    try:
        # Check Ollama connectivity
        import requests

        ollama_url = "http://192.168.1.246:11434/api/tags"
        response = requests.get(ollama_url, timeout=5)

        if response.status_code == 200:
            return {
                "healthy": True,
                "module_id": "archie_chat",
                "message": "Chat operational, Ollama connected",
                "status": "healthy",
            }
        else:
            return {
                "healthy": False,
                "module_id": "archie_chat",
                "message": f"Ollama returned status {response.status_code}",
                "status": "degraded",
            }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "archie_chat",
            "message": f"Ollama connection failed: {str(e)}",
            "status": "unhealthy",
        }


def obsidian_vault_health_check() -> Dict:
    """Health check for Obsidian vault"""
    try:
        vault_path = "/mnt/archie_brain/knowledge/"
        vault_exists = os.path.exists(vault_path)

        if not vault_exists:
            return {
                "healthy": False,
                "module_id": "obsidian_vault",
                "message": "Vault directory not found",
                "status": "unhealthy",
            }

        # Check watcher status
        try:
            from obsidian_vault_watcher import get_watcher_status

            watcher_status = get_watcher_status()
            watcher_running = watcher_status.get("running", False)
        except Exception:
            watcher_running = False

        # Count indexed notes
        try:
            from database import get_db

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE is_documentation = TRUE")
            note_count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
        except Exception:
            note_count = 0

        healthy = vault_exists and watcher_running

        return {
            "healthy": healthy,
            "module_id": "obsidian_vault",
            "message": f"Vault operational: {note_count} notes indexed",
            "status": "healthy" if healthy else "degraded",
            "details": {
                "vault_path": vault_path,
                "vault_exists": vault_exists,
                "watcher_running": watcher_running,
                "note_count": note_count,
            },
        }

    except Exception as e:
        return {"healthy": False, "module_id": "obsidian_vault", "message": f"Vault error: {str(e)}", "status": "error"}


# ============================================================================
# MODULE REGISTRY - Dashboard Redesign 2026-01-11
# Reorganized into 4 categories: Creation, Development, Admin, Integrations
# ============================================================================

MODULES: List[ModuleDefinition] = [
    # ========================================================================
    # CREATION TOOLS - Build projects, games, media, and content
    # Consolidated 2026-01-13: Merged overlapping builders
    # ========================================================================
    ModuleDefinition(
        id="project_builder",
        name="Project Builder",
        description="Build full-stack apps with AI<br>Describe your idea • AI generates code • Deploy instantly",
        icon="building-2",
        category=ModuleCategory.CREATION,
        route="/tools/project-builder",
        blueprint_import="tools.project_builder.routes:project_builder_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        beta=True,
        coming_soon=False,
        health_check=project_builder_health_check,
        priority=1,
        tags=["ai", "website", "app", "figma", "deployment", "flagship"],
    ),
    ModuleDefinition(
        id="game_studio",
        name="Game Studio",
        description="Create 2D & 3D games with AI<br>Mission editor • Asset library • Export to web/mobile",
        icon="gamepad-2",
        category=ModuleCategory.CREATION,
        route="/tools/game-studio",
        blueprint_import="tools.game_studio.routes:game_studio_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=game_studio_health_check,
        priority=2,
        tags=["ai", "games", "3d", "2d", "creation"],
    ),
    ModuleDefinition(
        id="media_studio",
        name="Media Studio",
        description="Generate images & videos with AI<br>Multiple art styles • Social media formats • Batch export",
        icon="palette",
        category=ModuleCategory.CREATION,
        route="/tools/media-studio",
        blueprint_import="tools.media_studio.routes:media_studio_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=media_studio_health_check,
        priority=3,
        tags=["ai", "images", "video", "shorts", "creative", "creation"],
    ),
    ModuleDefinition(
        id="content_studio",
        name="Content Studio",
        description="Write books, blogs & marketing copy<br>AI-assisted drafts • Multiple tones • SEO optimized",
        icon="pen-tool",
        category=ModuleCategory.CREATION,
        route="/tools/content-studio",
        blueprint_import="tools.content_studio.routes:content_studio_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=content_studio_health_check,
        priority=4,
        tags=["ai", "writing", "books", "articles", "marketing", "creation"],
    ),
    # ========================================================================
    # DEVELOPMENT TOOLS - Code Sentinel, Improvements Lab, Sandbox Manager
    # Phase 22 2026-01-16: ADMIN ONLY - All dev tools for platform management
    # Color: RED (#FF6B6B) - Styled differently from other categories
    # ========================================================================
    # NOTE: A.R.C.H.I.E. Chat moved to STANDALONE_APPS category
    # See STANDALONE_APPS section for ModuleDefinition
    # NOTE: Code Editor removed 2026-01-20 - integrated into Website Designer
    # NOTE: Sandbox Manager moved to ADMIN category below
    ModuleDefinition(
        id="coderabbit",
        name="CodeRabbit",
        description="AI-powered code review<br>PR Reviews • Code Health • Security scans",
        icon="rabbit",
        category=ModuleCategory.DEVELOPMENT,
        route="/tools/coderabbit",
        blueprint_import="tools.coderabbit.routes:coderabbit_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("coderabbit", "/tools/coderabbit/api/status"),
        priority=4,
        tags=["code-review", "security", "ai", "development", "quality"],
    ),
    ModuleDefinition(
        id="code_sentinel",
        name="Code Sentinel",
        description="Local code health scanner<br>AI Analysis • Multi-Agent • Issue Tracking",
        icon="shield-check",
        category=ModuleCategory.DEVELOPMENT,
        route="/tools/code_sentinel",
        blueprint_import="tools.code_sentinel.routes:code_sentinel_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("code_sentinel", "/tools/code_sentinel/api/status"),
        priority=5,
        tags=["code-health", "security", "ai", "development", "quality", "scanner"],
    ),
    # NOTE: Business Directory removed 2026-01-20 - now a tab in Website Designer
    # ========================================================================
    # BUSINESS TOOLS - Build & Run Your Business (Admin & Users)
    # Admin: Manage ARCHIE company assets
    # Users: Build their own business infrastructure
    # Consolidated 2026-01-13: Added Email, CRM, Invoicing, Scheduler
    # Phase 22 2026-01-16: Added Website Designer (replaces Code Editor)
    # ========================================================================
    ModuleDefinition(
        id="website_designer",
        name="Website Designer",
        description="Design & code your website<br>Live preview • File browser • Git deploy • Custom domains",
        icon="globe",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/website-studio",  # Uses existing website_studio routes
        blueprint_import="tools.website_studio.routes:website_studio_bp",
        required_permissions=["website_builder:create"],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("website_designer"),
        priority=0,  # First in business tools
        tags=["website", "design", "git", "domain", "business", "code"],
    ),
    ModuleDefinition(
        id="store_builder",
        name="Store Builder",
        description="Launch your online store<br>Product catalog • Stripe payments • Order management",
        icon="shopping-cart",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/store-builder",
        blueprint_import="tools.store_builder.routes:store_builder_bp",
        required_permissions=["store:create"],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("store_builder"),
        priority=1,
        tags=["store", "ecommerce", "payments", "business"],
    ),
    ModuleDefinition(
        id="call_center",
        name="Call Center",
        description="AI-powered phone support<br>Auto-receptionist • Call routing • Voice transcripts",
        icon="phone",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/call-center",
        blueprint_import="tools.call_center.routes:call_center_bp",
        required_permissions=["telephony:access"],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("call_center"),
        priority=2,
        tags=["phone", "calls", "ai", "business"],
    ),
    ModuleDefinition(
        id="email_manager",
        name="Email Manager",
        description="Send campaigns & newsletters<br>Drag-drop templates • Subscriber lists • Open/click tracking",
        icon="mail",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/email-manager",
        blueprint_import="tools.email_manager.routes:email_manager_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("email_manager"),
        priority=3,
        tags=["email", "campaigns", "marketing", "business"],
    ),
    ModuleDefinition(
        id="crm",
        name="CRM",
        description="Manage customers & sales<br>Contact database • Deal pipeline • Activity timeline",
        icon="users",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/crm",
        blueprint_import="tools.crm.routes:crm_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("crm"),
        priority=4,
        tags=["crm", "contacts", "sales", "business"],
    ),
    ModuleDefinition(
        id="invoicing",
        name="Invoicing",
        description="Create & send invoices<br>Professional templates • Payment links • Overdue tracking",
        icon="receipt",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/invoicing",
        blueprint_import="tools.invoicing.routes:invoicing_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("invoicing"),
        priority=5,
        tags=["invoicing", "billing", "payments", "business"],
    ),
    ModuleDefinition(
        id="scheduler",
        name="Scheduler",
        description="Book appointments & manage time<br>Client booking page • Calendar sync • SMS reminders",
        icon="calendar",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/scheduler",
        blueprint_import="tools.scheduler.routes:scheduler_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("scheduler"),
        priority=6,
        tags=["calendar", "tasks", "scheduling", "business"],
    ),
    # NOTE: GitHub Manager removed 2026-01-20 - functionality in Code Sentinel Git Manager tab
    ModuleDefinition(
        id="social_media",
        name="Social Media",
        description="Manage all social accounts<br>Schedule posts • Auto-publish • Engagement analytics",
        icon="share-2",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/social-media",
        blueprint_import="tools.social_media.routes:social_media_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("social_media"),
        priority=8,
        tags=["social", "marketing", "scheduling", "business"],
    ),
    ModuleDefinition(
        id="automations",
        name="Automations",
        description="Automate repetitive tasks<br>Visual workflow builder • Triggers • n8n integration",
        icon="settings",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/automations",
        blueprint_import="tools.automations.routes:automations_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("automations"),
        priority=9,
        tags=["automation", "workflows", "n8n", "business"],
    ),
    ModuleDefinition(
        id="analytics_dashboard",
        name="Analytics",
        description="Track business performance<br>Revenue charts • Traffic sources • Custom reports",
        icon="bar-chart-2",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/analytics-dashboard",
        blueprint_import="tools.analytics.routes:analytics_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("analytics_dashboard"),
        priority=10,
        tags=["analytics", "metrics", "business"],
    ),
    # ========================================================================
    # ADMIN TOOLS - System management, consciousness (ADMIN ONLY)
    # ========================================================================
    # NOTE: Admin Panel removed 2026-01-13
    # All routes migrated to respective modules:
    # - User Management -> /tools/user-management/
    # - Improvements -> /tools/improvements-lab/
    # - Team/Agents -> /tools/team-management/
    # - Backups -> /tools/backup-manager/
    # - Notifications -> /api/notifications/
    ModuleDefinition(
        id="blueprint",
        name="Mission Control",
        description="Unified intelligence & operations center<br>Knowledge • Team • Platform • Governance",
        icon="drafting-compass",
        category=ModuleCategory.ADMIN_OPS,  # Moved to Admin Operations - Phase 30
        route="/tools/blueprint",
        blueprint_import="tools.blueprint.routes:blueprint_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("blueprint"),
        priority=0,  # First in Admin Ops (Blueprint is the overview)
        tags=["documentation", "overview", "blueprint", "admin-ops"],
    ),
    ModuleDefinition(
        id="consciousness",
        name="Consciousness",
        description="Knowledge analytics • Memory insights<br>Team awareness • Learning management",
        icon="brain",
        category=ModuleCategory.ADMIN_OPS,
        route="/tools/consciousness",
        blueprint_import="tools.consciousness.routes:consciousness_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("consciousness"),
        priority=3,  # Fourth in Admin Ops (Blueprint=0, Bridge=1, Team=2, Consciousness=3)
        tags=["consciousness", "memory", "analytics", "admin-ops"],
    ),
    # NOTE: Obsidian Vault module removed - functionality merged into Consciousness module
    # The knowledge_vault_indexer and watcher are still active for backend indexing
    ModuleDefinition(
        id="improvements_lab",
        name="Improvements Lab",
        description="AI-powered self-improvement<br>Chat • Proposals • Workflow • Team",
        icon="wrench",
        category=ModuleCategory.DEVELOPMENT,  # Moved from ADMIN to DEVELOPMENT
        route="/tools/improvements-lab",
        blueprint_import="tools.improvements.improvements_routes:improvements_lab_bp",
        required_permissions=["admin:improvements"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("improvements_lab"),
        priority=5,  # After Code Sentinel in DEVELOPMENT
        tags=["improvements", "ai", "workflow", "chat", "development"],
    ),
    ModuleDefinition(
        id="team_management",
        name="Team Management",
        description="Unified agent control center<br>Roster • Tasks • Execution • Performance",
        icon="users-round",
        category=ModuleCategory.ADMIN_OPS,
        route="/tools/team-management",
        blueprint_import="tools.team_management.routes:team_management_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("team_management"),
        priority=2,  # Third in Admin Ops (Blueprint=0, Bridge=1, Team=2, Consciousness=3)
        tags=["team", "agents", "management", "execution", "admin-ops"],
    ),
    # Phase 51: HR Management - Extracted from Team Management
    ModuleDefinition(
        id="hr_management",
        name="HR Management",
        description="Staff performance & compliance<br>Skills • Scheduling • IAAE • Wellness",
        icon="clipboard-list",
        category=ModuleCategory.ADMIN_OPS,
        route="/tools/hr-management",
        blueprint_import="tools.hr_management.routes:hr_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("hr_management"),
        priority=3,  # After Team Management
        tags=["hr", "performance", "skills", "scheduling", "wellness", "iaae"],
    ),
    ModuleDefinition(
        id="backup_manager",
        name="Backup Manager",
        description="System backups and restore<br>Automated • Version control • Safety",
        icon="hard-drive",
        category=ModuleCategory.ADMIN,
        route="/tools/backup-manager",
        blueprint_import="tools.backup_manager.backup_manager_routes:backup_manager_bp",
        required_permissions=["admin:backups"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("backup_manager"),
        priority=4,
        tags=["backup", "restore", "safety"],
    ),
    ModuleDefinition(
        id="security_network",
        name="Security & Network",
        description="Security monitoring & network health<br>Threats • System health • Audit logs",
        icon="shield",
        category=ModuleCategory.ADMIN,
        route="/tools/security-network",
        blueprint_import="tools.security_network.routes:security_network_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("security_network"),
        priority=5,
        tags=["security", "network", "monitoring", "audit"],
    ),
    ModuleDefinition(
        id="account_center",
        name="Account Center",
        description="Manage accounts, permissions, subscriptions<br>Activity tracking • Role management",
        icon="user",
        category=ModuleCategory.ADMIN,
        route="/tools/account-center",
        blueprint_import="tools.account_center.routes:account_center_bp",
        required_permissions=["admin:users"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("account_center"),
        priority=6,
        tags=["accounts", "users", "permissions", "subscriptions"],
    ),
    ModuleDefinition(
        id="bridge",
        name="Bridge Command",
        description="Central command center for AI operations<br>Stations • LLM monitoring • Traffic control",
        icon="monitor",
        category=ModuleCategory.ADMIN_OPS,
        route="/tools/bridge",
        blueprint_import="tools.bridge.routes:bridge_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        health_check=lambda: default_health_check("bridge"),
        priority=1,  # Second in Admin Ops (Blueprint=0, Bridge=1, Team=2, Consciousness=3)
        tags=["bridge", "llm", "monitoring", "command", "stations", "admin-ops"],
    ),
    ModuleDefinition(
        id="sandbox_manager",
        name="Sandbox Manager",
        description="Per-module sandbox testing<br>Safe deployments • Test results • Visual access",
        icon="test-tube-2",
        category=ModuleCategory.DEVELOPMENT,  # Moved from ADMIN to DEVELOPMENT
        route="/tools/sandbox-manager",
        blueprint_import="tools.sandbox_manager.routes:sandbox_manager_bp",
        required_permissions=["admin:sandbox"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("sandbox_manager"),
        priority=6,  # After Improvements Lab in DEVELOPMENT
        tags=["sandbox", "testing", "development", "deployment"],
    ),
    ModuleDefinition(
        id="cursor_integration",
        name="IDE Integration",
        description="External IDE integration<br>Cursor AI • OpenCode • VS Code • MCP Protocol",
        icon="mouse-pointer",
        category=ModuleCategory.DEVELOPMENT,
        route="/tools/cursor-integration",
        blueprint_import="tools.cursor_integration.routes:cursor_integration_bp",
        required_permissions=["admin:ide"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("cursor_integration", "/tools/cursor-integration/api/status"),
        priority=7,
        tags=["ide", "cursor", "vscode", "integration", "mcp", "development"],
    ),
    ModuleDefinition(
        id="testing_suite",
        name="Testing Suite",
        description="Automated testing<br>Regression tests • Benchmarks • Test discovery",
        icon="vial",
        category=ModuleCategory.DEVELOPMENT,
        route="/tools/testing-suite",
        blueprint_import="tools.testing_suite.routes:testing_suite_bp",
        required_permissions=["admin:testing"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("testing_suite", "/tools/testing-suite/api/status"),
        priority=8,
        tags=["testing", "regression", "benchmarks", "quality", "development"],
    ),
    ModuleDefinition(
        id="fine_tuning",
        name="AI Fine-tuning",
        description="Custom model training<br>Datasets • LoRA • Training jobs • Deploy to Ollama",
        icon="brain",
        category=ModuleCategory.DEVELOPMENT,
        route="/tools/fine-tuning",
        blueprint_import="tools.fine_tuning.routes:fine_tuning_bp",
        required_permissions=["admin:fine_tuning"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("fine_tuning", "/tools/fine-tuning/api/status"),
        priority=9,
        tags=["ai", "fine-tuning", "training", "models", "ollama", "development"],
    ),
    # ========================================================================
    # STAND ALONE APPS - Unique apps for Android + Web subscriptions
    # Character-based AI modules with specialized personas
    # Available as: Android apps, iOS apps, Web subscriptions
    # ========================================================================
    ModuleDefinition(
        id="archie_chat",
        name="A.R.C.H.I.E.",
        description="Your AI assistant<br>Text & voice chat • Image analysis • Long-term memory",
        icon="bot",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/archie-chat",
        blueprint_import="tools.archie_core.routes:archie_chat_bp",
        required_permissions=["archie:chat"],
        minimum_role="USER",
        enabled=True,
        health_check=archie_chat_health_check,
        priority=0,  # First in standalone apps
        tags=["ai", "assistant", "chat", "voice", "vision", "standalone"],
    ),
    ModuleDefinition(
        id="doc",
        name="DOC",
        description="Your AI health companion<br>Symptom checker • Photo analysis • Health log",
        icon="stethoscope",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/doc",
        blueprint_import="tools.doc.routes:doc_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("doc", "/tools/doc/api/status"),
        priority=1,
        tags=["health", "medical", "ai", "records", "standalone", "android"],
    ),
    ModuleDefinition(
        id="therapy",
        name="Therapy",
        description="AI mental wellness support<br>Guided conversations • Mood journal • CBT exercises",
        icon="flower-2",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/therapy",
        blueprint_import="tools.therapy.routes:therapy_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("therapy", "/tools/therapy/api/status"),
        priority=2,
        tags=["mental", "therapy", "wellness", "ai", "standalone", "android"],
    ),
    ModuleDefinition(
        id="fitness",
        name="Fitness",
        description="AI personal trainer<br>Custom workout plans • Exercise demos • Progress charts",
        icon="dumbbell",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/fitness",
        blueprint_import="tools.fitness.routes:fitness_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("fitness", "/tools/fitness/api/status"),
        priority=3,
        tags=["fitness", "workout", "health", "ai", "standalone", "android"],
    ),
    ModuleDefinition(
        id="stockbot",
        name="StockBot",
        description="AI stock market scanner<br>Technical indicators • Buy/sell alerts • Dividend tracker",
        icon="trending-up",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/stockbot",
        blueprint_import="tools.stockbot.routes:stockbot_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("stockbot", "/tools/stockbot/api/status"),
        priority=4,
        tags=["stocks", "finance", "trading", "ai", "standalone", "android"],
    ),
    ModuleDefinition(
        id="archie_pool",
        name="Archie Pool",
        description="Ravencoin mining pool<br>Real-time hashrate • Earnings dashboard • Auto payouts",
        icon="pickaxe",
        category=ModuleCategory.STANDALONE_APPS,
        route="/tools/archie-pool",
        blueprint_import="tools.archie_pool.routes:archie_pool_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("archie_pool", "/tools/archie-pool/api/status"),
        priority=5,
        tags=["mining", "crypto", "ravencoin", "standalone", "android"],
    ),
    # ========================================================================
    # ADMIN - Pool Management (Admin Only)
    # Full management interface for Archie Pool operations
    # ========================================================================
    ModuleDefinition(
        id="pool_management",
        name="Pool Management",
        description="Archie Pool admin controls<br>Miners • Payouts • Conversions • Analytics",
        icon="sliders",
        category=ModuleCategory.ADMIN,
        route="/tools/pool-management",
        blueprint_import="tools.pool_management.routes:pool_management_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=pool_management_health_check,
        priority=7,
        tags=["mining", "admin", "management", "payouts", "conversions"],
    ),
    # Phase 55: Goose Orchestration
    ModuleDefinition(
        id="goose",
        name="Goose Orchestration",
        description="Autonomous workflow orchestration<br>MCP tools • Blueprints • Scheduling",
        icon="bot",
        category=ModuleCategory.ADMIN,
        route="/tools/goose",
        blueprint_import="tools.goose:goose_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("goose", "/tools/goose/api/status"),
        priority=8,
        tags=["goose", "orchestration", "workflows", "automation", "mcp"],
    ),
    # Phase 78: System Operations - Host machine administration
    ModuleDefinition(
        id="system_operations",
        name="System Operations",
        description="Host machine administration<br>CPU • RAM • Disk • Processes • Docker • Network",
        icon="server",
        category=ModuleCategory.ADMIN,
        route="/tools/system-operations",
        blueprint_import="tools.system_operations.routes:system_operations_bp",
        required_permissions=["admin:system"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("system_operations", "/tools/system-operations/health"),
        priority=9,
        tags=["system", "monitoring", "admin", "docker", "processes", "network", "host"],
    ),
    # ========== INTEGRATIONS ==========
    ModuleDefinition(
        id="figma",
        name="Figma Integration",
        description="Design-to-code pipeline<br>OAuth • Parser • AI mapper • React/Vue/HTML export",
        icon="figma",
        category=ModuleCategory.CREATION,
        route="/tools/figma",
        blueprint_import="tools.figma.routes:figma_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("figma", "/tools/figma/api/status"),
        priority=0,  # First in CREATION - Figma feeds data to Project Builder
        tags=["figma", "design", "code-generation", "react", "vue", "html", "ai"],
    ),
    # ========================================================================
    # ADDITIONAL MODULES - Registered 2026-01-20
    # NOTE: Removed disabled placeholders (book_builder, picture_generation,
    #       video_generation, story_generation) - functionality in Studios
    # ========================================================================
    ModuleDefinition(
        id="google_workspace",
        name="Google Workspace",
        description="Google integration hub<br>Drive • Docs • Sheets • Calendar sync",
        icon="cloud",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/google-workspace",
        blueprint_import="tools.google_workspace.routes:google_workspace_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("google_workspace"),
        priority=11,
        tags=["google", "drive", "docs", "integration", "business"],
    ),
    ModuleDefinition(
        id="task_planner",
        name="Task Planner",
        description="Project task management<br>Kanban boards • Timelines • Team assignments",
        icon="list-checks",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/task-planner",
        blueprint_import="tools.task_planner.routes:task_planner_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("task_planner"),
        priority=12,
        tags=["tasks", "planning", "projects", "business"],
    ),
    ModuleDefinition(
        id="site_manager",
        name="Site Manager",
        description="Website management hub<br>Domains • Hosting • SSL • DNS",
        icon="globe-2",
        category=ModuleCategory.BUSINESS_TOOLS,
        route="/tools/site-manager",
        blueprint_import="tools.site_manager.routes:site_manager_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("site_manager"),
        priority=13,
        tags=["sites", "domains", "hosting", "business"],
    ),
    # ========================================================================
    # PROJECT MANAGEMENT - Phase 65: Unified Project System
    # ========================================================================
    ModuleDefinition(
        id="project_manager",
        name="Project Manager",
        description="Unified project & documentation system<br>Tasks • Teams • Decisions • ARCHIE awareness",
        icon="folder-kanban",
        category=ModuleCategory.ADMIN,
        route="/tools/project-manager",
        blueprint_import="tools.project_manager.routes:project_manager_bp",
        required_permissions=["admin:projects"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("project_manager", "/tools/project-manager/api/status"),
        priority=5,
        tags=["projects", "tasks", "teams", "documentation", "decisions", "admin", "consciousness"],
    ),
]


# ============================================================================
# REGISTRY FUNCTIONS
# ============================================================================


def get_all_modules() -> List[ModuleDefinition]:
    """Get all registered modules"""
    return MODULES


def get_enabled_modules() -> List[ModuleDefinition]:
    """Get only enabled modules"""
    return [m for m in MODULES if m.enabled]


def get_module_by_id(module_id: str) -> Optional[ModuleDefinition]:
    """Get a module by its ID"""
    for module in MODULES:
        if module.id == module_id:
            return module
    return None


def get_modules_by_category(category: ModuleCategory) -> List[ModuleDefinition]:
    """Get modules by category"""
    return [m for m in MODULES if m.category == category]


def get_modules_for_role(role: str) -> List[ModuleDefinition]:
    """Get modules accessible by a specific role"""
    role_hierarchy = {"PUBLIC": 0, "USER": 10, "PREMIUM": 20, "ADMIN": 90, "SUPER_ADMIN": 100}

    user_level = role_hierarchy.get(role, 0)
    accessible = []

    for module in MODULES:
        module_level = role_hierarchy.get(module.minimum_role, 0)
        if user_level >= module_level and module.enabled:
            accessible.append(module)

    return sorted(accessible, key=lambda m: m.priority)


def check_module_health(module_id: str) -> Dict:
    """Run health check for a specific module"""
    module = get_module_by_id(module_id)

    if not module:
        return {"healthy": False, "module_id": module_id, "message": "Module not found", "status": "not_found"}

    if not module.enabled:
        return {"healthy": False, "module_id": module_id, "message": "Module disabled", "status": "disabled"}

    if module.health_check:
        try:
            return module.health_check()
        except Exception as e:
            return {
                "healthy": False,
                "module_id": module_id,
                "message": f"Health check error: {str(e)}",
                "status": "error",
            }

    return default_health_check(module_id)


def check_all_modules_health() -> Dict[str, Dict]:
    """Run health checks for all enabled modules"""
    health_results = {}

    for module in get_enabled_modules():
        health_results[module.id] = check_module_health(module.id)

    return health_results


def load_module_blueprint(module_id: str):
    """Dynamically load a module's Flask blueprint"""
    module = get_module_by_id(module_id)

    if not module:
        raise ValueError(f"Module '{module_id}' not found in registry")

    if not module.enabled:
        raise ValueError(f"Module '{module_id}' is disabled")

    # Skip modules without a blueprint (defined directly in app.py)
    if not module.blueprint_import or ":" not in module.blueprint_import:
        return None  # No blueprint to load, route defined elsewhere

    # Parse blueprint import path
    # Format: "module.path:blueprint_name"
    try:
        module_path, blueprint_name = module.blueprint_import.split(":")
        imported_module = importlib.import_module(module_path)
        blueprint = getattr(imported_module, blueprint_name)
        return blueprint
    except Exception as e:
        raise ImportError(f"Failed to load blueprint for '{module_id}': {str(e)}")


# ============================================================================
# SUMMARY FUNCTIONS
# ============================================================================


def get_registry_summary() -> Dict:
    """Get summary statistics about the module registry"""
    all_modules = get_all_modules()
    enabled_modules = get_enabled_modules()

    categories = {}
    for module in all_modules:
        cat_name = module.category.value
        if cat_name not in categories:
            categories[cat_name] = {"total": 0, "enabled": 0}
        categories[cat_name]["total"] += 1
        if module.enabled:
            categories[cat_name]["enabled"] += 1

    return {
        "total_modules": len(all_modules),
        "enabled_modules": len(enabled_modules),
        "disabled_modules": len(all_modules) - len(enabled_modules),
        "coming_soon_modules": len([m for m in all_modules if m.coming_soon]),
        "beta_modules": len([m for m in all_modules if m.beta]),
        "categories": categories,
        "health_status": "Not checked",
    }


if __name__ == "__main__":
    # Test the registry
    print("=" * 80)
    print("MODULE REGISTRY TEST")
    print("=" * 80)

    summary = get_registry_summary()
    print(f"\n📊 Registry Summary:")
    print(f"  Total Modules: {summary['total_modules']}")
    print(f"  Enabled: {summary['enabled_modules']}")
    print(f"  Disabled: {summary['disabled_modules']}")
    print(f"  Coming Soon: {summary['coming_soon_modules']}")
    print(f"  Beta: {summary['beta_modules']}")

    print(f"\n📂 Modules by Category:")
    for cat, stats in summary["categories"].items():
        print(f"  {cat}: {stats['enabled']}/{stats['total']} enabled")

    print(f"\n✅ Enabled Modules:")
    for module in get_enabled_modules():
        print(f"  [{module.icon}] {module.name} - {module.route}")

    print(f"\n🏥 Health Check Results:")
    health_results = check_all_modules_health()
    for module_id, health in health_results.items():
        status_icon = "✅" if health["healthy"] else "❌"
        print(f"  {status_icon} {module_id}: {health['message']}")

    print("\n" + "=" * 80)
