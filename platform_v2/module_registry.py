"""
Module Registry - Single Source of Truth for all A.R.C.H.I.E. Platform Modules
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
import os


def check_service_health(service_name: str, endpoint: str, timeout: int = 2) -> dict:
    """Check if a service endpoint is healthy

    Returns health status dict for registered services.
    """
    return {
        "healthy": True,
        "module_id": service_name,
        "status": "active",
        "message": f"{service_name} is active",
    }


class ModuleCategory(Enum):
    """Module categories for organization - Reorganized 2026-02-03"""

    # New category structure from consolidation plan (2026-02-03)
    ADMIN_OPERATIONS = "admin_operations"  # backup_manager, security_network, account_center, system_ops
    AI_COMMAND = "ai_command"  # consciousness, team_management, bridge, repair_bay
    SAAS_SERVICES = "saas_services"  # crm, website_studio, store_builder, call_center, etc.
    PROJECT_KNOWLEDGE = "project_knowledge"  # project_manager, api_docs
    APPLICATIONS_CONCEPTS = "applications_concepts"  # media_hub, fitness, therapy, doc, family_tree
    CRYPTO = "crypto"  # archie_pool, pool_management
    MEDIA_OUTREACH = "media_outreach"  # watch products, news, creed
    CREATIVE_STUDIOS = "creative_studios"  # game_studio, media_studio
    PLACEHOLDERS_FUTURE = "placeholders_future"  # future modules
    WHAT_THE_FACT = "what_the_fact"  # wtf_hub (orchestration) + what_the_fact (public product)


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
    blueprint_import: str = ""  # Import path (e.g., "tools.app_builder.routes:app_builder_bp")
    external_url: str = ""  # External URL for standalone products (opens in new tab)

    # Access Control
    required_permissions: List[str] = field(default_factory=list)  # Required permissions
    minimum_role: str = "USER"  # Minimum role: PUBLIC, USER, PREMIUM, ADMIN, SUPER_ADMIN
    minimum_tier: str = "explorer"  # explorer, starter, professional, enterprise, vip, staff

    # Features
    health_check: Optional[Callable] = None  # Health check function
    enabled: bool = True  # Module enabled?
    beta: bool = False  # Beta/experimental feature?
    coming_soon: bool = False  # Coming soon (placeholder)?

    # Metadata
    version: str = "1.0"
    tags: List[str] = field(default_factory=list)
    priority: int = 10  # Display priority (lower = higher priority)
    show_on_dashboard: bool = True  # Show card on dashboard? (False = API-only module)


def default_health_check(module_id: str) -> Dict:
    """Default health check for modules without custom implementation"""
    return {
        "healthy": True,
        "module_id": module_id,
        "message": "No health check configured",
        "status": "unknown",
    }


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


# DEPRECATED 2026-02-03: Using project_manager instead
# def project_builder_health_check() -> Dict:
#     """Health check for Project Builder"""
#     try:
#         import os
#
#         paths_to_check = [
#             "/app/templates/tools/project_builder.html",
#             "/mnt/archie_brain/platform_v2/templates/tools/project_builder.html",
#         ]
#         exists = any(os.path.exists(p) for p in paths_to_check)
#
#         return {
#             "healthy": exists,
#             "module_id": "project_builder",
#             "message": "Project Builder operational" if exists else "Template not found",
#             "status": "healthy" if exists else "degraded",
#         }
#     except Exception as e:
#         return {
#             "healthy": False,
#             "module_id": "project_builder",
#             "message": f"Health check failed: {str(e)}",
#             "status": "unhealthy",
#         }


def media_studio_health_check() -> Dict:
    """Health check for Media Studio"""
    try:

        paths_to_check = [
            "/app/tools/media_studio/templates/tools/media_studio/media_studio.html",
            "/mnt/archie_brain/platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html",
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

        paths_to_check = [
            "/app/templates/tools/pool_management.html",
            "/mnt/archie_brain/platform_v2/templates/tools/pool_management.html",
        ]
        exists = any(os.path.exists(p) for p in paths_to_check)

        return {
            "healthy": exists,
            "module_id": "pool_management",
            "message": ("Pool Management operational" if exists else "Template not found"),
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
    """Health check for A.R.C.H.I.E. chat — checks Bridge availability + agents"""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM service_status WHERE service_name = 'ai_bridge'")
            row = cur.fetchone()
            bridge_online = row and row["status"] == "online"
            cur.execute("SELECT COUNT(*) as cnt FROM agents WHERE status = 'active'")
            agent_count = cur.fetchone()["cnt"]

        if bridge_online and agent_count > 0:
            return {
                "healthy": True,
                "module_id": "archie_chat",
                "message": f"Chat operational, Bridge online, {agent_count} agents",
                "status": "healthy",
            }
        else:
            return {
                "healthy": False,
                "module_id": "archie_chat",
                "message": f"Bridge: {'online' if bridge_online else 'offline'}, Agents: {agent_count}",
                "status": "degraded",
            }
    except Exception as e:
        return {
            "healthy": False,
            "module_id": "archie_chat",
            "message": f"Ollama connection failed: {str(e)}",
            "status": "unhealthy",
        }


# ============================================================================
# MODULE REGISTRY - Reorganized 2026-02-03
# Categories: Admin Operations, AI Command, Development Tools, SaaS Services,
#             Project & Knowledge, Media & Home, Placeholders - Future
# ============================================================================

MODULES: List[ModuleDefinition] = [
    # ============================================
    # ADMIN OPERATIONS (4 modules)
    # ============================================
    # backup_manager, security_network, account_center, system_operations
    ModuleDefinition(
        id="backup_manager",
        name="Backup Manager",
        description="Automated backup and restore<br>Scheduled snapshots • Version history • One-click recovery",
        icon="hard-drive",
        category=ModuleCategory.ADMIN_OPERATIONS,
        route="/tools/backup-manager",
        blueprint_import="tools.backup_manager:backup_manager_bp",
        required_permissions=["admin:backups"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("backup_manager"),
        priority=1,
        tags=["backup", "restore", "safety", "admin-operations"],
    ),
    ModuleDefinition(
        id="security_network",
        name="Security & Network",
        description="Security operations center<br>DNS • Surveillance • Recon • Threat scanning • Compliance",
        icon="shield",
        category=ModuleCategory.ADMIN_OPERATIONS,
        route="/tools/security-network",
        blueprint_import="tools.security_network.routes:security_network_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("security_network"),
        priority=2,
        tags=["security", "network", "dns", "surveillance", "recon", "scanning", "agent", "admin-operations"],
    ),
    ModuleDefinition(
        id="account_center",
        name="Account Center",
        description="User and subscription management<br>Roles • Permissions • Activity tracking • Billing tiers",
        icon="user",
        category=ModuleCategory.ADMIN_OPERATIONS,
        route="/tools/account-center",
        blueprint_import="tools.account_center.routes:account_center_bp",
        required_permissions=["admin:users"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("account_center"),
        priority=3,
        tags=["accounts", "users", "permissions", "subscriptions", "admin-operations"],
    ),
    # RETIRED: System Operations migrated to Kytran System Operations standalone (:8085)
    # See standalone launcher at id="kytran_system_ops" below
    ModuleDefinition(
        id="system_operations",
        name="System Operations",
        description="Migrated to Kytran System Operations standalone",
        icon="server",
        category=ModuleCategory.ADMIN_OPERATIONS,
        route="/tools/system-operations",
        blueprint_import="tools.system_operations.routes:system_operations_bp",
        required_permissions=["admin:system"],
        minimum_role="ADMIN",
        enabled=False,
        coming_soon=False,
        health_check=lambda: check_service_health("system_operations", "/tools/system-operations/health"),
        priority=99,
        tags=["retired"],
    ),
    ModuleDefinition(
        id="saas_manager",
        name="SaaS Manager",
        description="Multi-tenant platform management<br>Organizations • Domains • Modules",
        icon="building-2",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/saas-manager",
        blueprint_import="tools.saas_manager.saas_manager_routes:saas_manager_bp",
        required_permissions=["admin:saas"],
        minimum_role="ADMIN",
        enabled=True,
        show_on_dashboard=False,  # Folded into Account Center ORGS tab
        health_check=lambda: default_health_check("saas_manager"),
        priority=0,
        tags=["saas", "organizations", "domains", "multi-tenant"],
        version="1.0",
    ),
    # ============================================
    # AI COMMAND (1 module)
    # ============================================
    # consciousness
    # NOTE: team_management removed (Decision #431) — C.R.E.E.D. admin moved to tools/creed/
    # NOTE: blueprint removed (Decision #431) — intelligence moved to consciousness
    # NOTE: Starbase + Starship → A.R.M.A.D.A. → fully merged into Department HQ (2026-04-08)
    ModuleDefinition(
        id="department_hq",
        name="Department HQ",
        description="Command center for 17 departments<br>Org chart \u2022 Roster \u2022 Dispatch \u2022 Fleet \u2022 Performance \u2022 C.R.E.E.D.",
        icon="building",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/department-hq",
        blueprint_import="tools.department_hq:department_hq_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("department_hq"),
        priority=2,
        tags=["departments", "org-chart", "roster", "performance", "creed", "ai-command"],
    ),
    ModuleDefinition(
        id="consciousness",
        name="Consciousness",
        description="Knowledge analytics and AI processing<br>Embeddings • Dev HQ • GitHub • Languages • Memory insights",
        icon="brain",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/consciousness",
        blueprint_import="tools.consciousness.routes:consciousness_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("consciousness"),
        priority=4,
        tags=["consciousness", "memory", "analytics", "ai-command"],
    ),
    ModuleDefinition(
        id="archie_chat",
        name="A.R.C.H.I.E.",
        description="Private comms channel<br>Chat • Voice • Vision • Collaboration • Watchdog",
        icon="bot",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/archie-chat",
        blueprint_import="tools.archie_chat:archie_chat_bp",
        required_permissions=["archie:chat"],
        minimum_role="COLLABORATOR",
        minimum_tier="staff",
        enabled=True,
        health_check=archie_chat_health_check,
        priority=1,
        tags=["ai", "assistant", "chat", "voice", "vision", "ai-command"],
    ),
    # Repair Bay — F.O.R.G.E.'s primary tool
    ModuleDefinition(
        id="repair_bay",
        name="Repair Bay",
        description="Self-healing code pipeline<br>Scan \u2022 Propose \u2022 Sandbox \u2022 Test \u2022 PR review \u2022 Deploy",
        icon="git-branch",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/repair-bay",
        blueprint_import="tools.repair_bay:repair_bay_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("repair_bay", "/tools/repair-bay/api/status"),
        priority=0,
        tags=[
            "development",
            "pipeline",
            "scanning",
            "testing",
            "deployment",
            "development-tools",
        ],
    ),
    ModuleDefinition(
        id="creed_command",
        name="C.R.E.E.D. Command",
        description="E.T.H.O.S. governance command center<br>Mail • Grants • Marketing • Files • Governance",
        icon="shield-check",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/creed-command",
        blueprint_import="tools.creed_command:creed_command_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("creed_command", "/tools/creed-command/api/status"),
        priority=6,
        tags=["creed", "ethics", "governance", "ethos", "email", "grants", "marketing"],
    ),
    ModuleDefinition(
        id="agent_academy",
        name="Agent Academy",
        description="Agent training and evaluation<br>Benchmarks \u2022 A/B testing \u2022 Skills \u2022 Competency reports",
        icon="graduation-cap",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/agent-academy",
        blueprint_import="tools.agent_academy:agent_academy_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        health_check=lambda: default_health_check("agent_academy"),
        priority=3,
        tags=["training", "benchmarks", "testing", "models", "ai-command"],
    ),
    # ============================================
    # SAAS SERVICES (modules — KBS modules removed 2026-03-30, now in Kytran Business Suite)
    # ============================================
    # email_manager, scheduler, social_media
    ModuleDefinition(
        id="email_manager",
        name="Email HQ",
        description="Unified email oversight — all agent & business mailboxes<br>Inbox • Sent • Provisioning • Stalwart integration",
        icon="mail",
        category=ModuleCategory.AI_COMMAND,
        route="/tools/email-manager",
        blueprint_import="tools.email_manager.routes:email_manager_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("email_manager"),
        priority=6,
        tags=["email", "mailbox", "agents", "stalwart", "ai-command"],
    ),
    ModuleDefinition(
        id="wtf_hub",
        name="WTF Hub",
        description="Orchestration hub for what-the-fact.com — Bridge dispatch, ingest pipeline, story clustering",
        icon="globe",
        category=ModuleCategory.WHAT_THE_FACT,
        route="/tools/wtf-hub",
        blueprint_import="tools.wtf_hub:wtf_hub_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=None,
        priority=7,
        tags=["wtf", "news", "orchestration", "ai-command"],
    ),
    ModuleDefinition(
        id="scheduler",
        name="Scheduler",
        description="Book appointments & manage time<br>Client booking page • Calendar sync • SMS reminders",
        icon="calendar",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/scheduler",
        blueprint_import="tools.scheduler.routes:scheduler_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=False,
        coming_soon=False,
        health_check=lambda: default_health_check("scheduler"),
        priority=8,
        tags=["calendar", "tasks", "scheduling", "business", "saas-services"],
    ),
    ModuleDefinition(
        id="social_media",
        name="Social Media",
        description="Manage all social accounts<br>Schedule posts • Auto-publish • Engagement analytics",
        icon="share-2",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/social-media",
        blueprint_import="tools.social_media.routes:social_media_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=False,
        coming_soon=False,
        health_check=lambda: default_health_check("social_media"),
        priority=9,
        tags=["social", "marketing", "scheduling", "business", "saas-services"],
    ),
    # ============================================
    # PROJECT & KNOWLEDGE (1 module)
    # ============================================
    # project_manager (api_docs placeholder)
    ModuleDefinition(
        id="project_manager",
        name="Project Manager",
        description="Unified project & documentation system<br>Tasks • Teams • Decisions • A.R.C.H.I.E. awareness",
        icon="folder-kanban",
        category=ModuleCategory.PROJECT_KNOWLEDGE,
        route="/tools/project-manager",
        blueprint_import="tools.project_manager.routes:project_manager_bp",
        required_permissions=["admin:projects"],
        minimum_role="ADMIN",
        enabled=False,  # Deprecated — Dev HQ handles all project/task management
        coming_soon=False,
        health_check=lambda: check_service_health("project_manager", "/tools/project-manager/api/status"),
        priority=1,
        tags=[
            "projects",
            "tasks",
            "teams",
            "documentation",
            "decisions",
            "admin",
            "consciousness",
            "project-knowledge",
        ],
    ),
    # NOTE: obsidian_vault removed (Decision #431) — functionality in Consciousness.
    # Wikilink graph concept salvaged as Task #1806.
    # NOTE: api_docs placeholder - could be implemented as OpenAPI/Swagger docs viewer
    # ============================================
    # MEDIA & HOME (1 module)
    # ============================================
    # media_hub
    #
    # Extracted as a standalone Docker product (Project #273 / #384).
    # Runs at https://media.kytranempowerment.com (hub :8105).
    # Fully consolidated 2026-07-08: the in-platform blueprint was retired and
    # all module code relocated into standalone/media_hub/. Launch tile only.
    ModuleDefinition(
        id="media_hub",
        name="Media Hub",
        description="Unified media server dashboard<br>Now standalone — launches media.kytranempowerment.com",
        icon="tv-2",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/media-hub",
        external_url="https://media.kytranempowerment.com",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("media_hub"),
        priority=1,
        tags=[
            "media",
            "standalone",
            "product",
            "plex",
            "jellyfin",
            "sonarr",
            "radarr",
            "streaming",
            "applications-concepts",
        ],
    ),
    # ============================================
    # APPLICATIONS & CONCEPTS
    # ============================================
    ModuleDefinition(
        id="family_tree",
        name="Family Tree",
        description="AI-powered genealogy research<br>Record search • Document OCR • Face matching • Restoration",
        icon="tree-deciduous",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/family-tree",
        blueprint_import="tools.family_tree:family_tree_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="enterprise",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("family_tree", "/tools/family-tree/api/status"),
        priority=2,
        tags=["genealogy", "family", "tree", "ancestry", "ai", "photos", "ocr"],
    ),
    ModuleDefinition(
        id="mailbox_story",
        name="Chronicle",
        description="Upload a .pst → a LOCAL AI reconstructs the account's story<br>Local-sovereign · admin-gated · nothing leaves the infra",
        icon="mailbox",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/chronicle",
        blueprint_import="tools.mailbox_story:mailbox_story_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("mailbox_story", "/tools/chronicle/api/status"),
        priority=2,
        tags=["mailbox", "pst", "email", "local-ai", "intelligence", "privacy", "sovereign"],
    ),
    # ============================================
    # PLACEHOLDERS - FUTURE (12 modules)
    # ============================================
    # fitness, therapy, doc, stockbot, game_studio, archie_pool, pool_management,
    # task_planner, google_workspace, content_studio, media_studio, app_builder
    ModuleDefinition(
        id="fitness",
        name="Fitness",
        description="AI-powered personal trainer<br>Custom workouts • Exercise library • Progress tracking",
        icon="dumbbell",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/fitness",
        blueprint_import="tools.fitness.routes:fitness_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("fitness", "/tools/fitness/api/status"),
        priority=1,
        tags=[
            "fitness",
            "workout",
            "health",
            "ai",
            "standalone",
            "android",
            "placeholder",
        ],
    ),
    ModuleDefinition(
        id="therapy",
        name="Therapy",
        description="AI-guided mental wellness<br>Structured conversations • Mood journaling • CBT exercises",
        icon="flower-2",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/therapy",
        blueprint_import="tools.therapy.routes:therapy_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("therapy", "/tools/therapy/api/status"),
        priority=2,
        tags=[
            "mental",
            "therapy",
            "wellness",
            "ai",
            "standalone",
            "android",
            "placeholder",
        ],
    ),
    ModuleDefinition(
        id="faith",
        name="Faith",
        description="Spiritual care companion — F.A.I.T.H. AI + Emmanuel Adeyemi chaplain",
        icon="cross",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/faith",
        blueprint_import="tools.faith.routes:faith_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("faith", "/tools/faith/api/faith/status"),
        priority=2,
        tags=[
            "faith",
            "spiritual",
            "wellness",
            "ai",
            "chaplain",
        ],
    ),
    ModuleDefinition(
        id="doc",
        name="DOC",
        description="AI-powered health companion<br>Symptom analysis • Photo assessment • Health records",
        icon="stethoscope",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/doc",
        blueprint_import="tools.doc.routes:doc_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("doc", "/tools/doc/api/status"),
        priority=3,
        tags=[
            "health",
            "medical",
            "ai",
            "records",
            "standalone",
            "android",
            "placeholder",
        ],
    ),
    ModuleDefinition(
        id="brainstorm",
        name="Brainstorm",
        description="Structured ideation workspace<br>Sessions • Clusters • Votes • KB export • AI expansion",
        icon="lightbulb",
        category=ModuleCategory.APPLICATIONS_CONCEPTS,
        route="/tools/brainstorm",
        blueprint_import="tools.brainstorm:brainstorm_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("brainstorm", "/tools/brainstorm/api/status"),
        priority=2,
        tags=["brainstorm", "ideas", "creativity", "productivity", "planning"],
    ),
    # market_watch removed — duplicate of kytran_market_watch in APPLICATIONS (line 896)
    # site_builder — Creative Studios launch tile → the Kytran Business Suite
    # Website Builder (kbs_website_builder plugin). No in-platform blueprint; opens
    # KBS in a new tab. Creative Studios modularization (#387 / #4932): Site
    # Builder lives in KBS, not the platform.
    ModuleDefinition(
        id="site_builder",
        name="Site Builder",
        description="Drag-and-drop website builder with AI generation<br>Launches the Business Suite Website Builder",
        icon="globe",
        category=ModuleCategory.CREATIVE_STUDIOS,
        route="/tools/site-builder",
        external_url="https://business.kytranempowerment.com/plugins/website-builder/",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("site_builder"),
        priority=3,
        tags=[
            "website",
            "site-builder",
            "kbs",
            "standalone",
            "product",
            "ai",
            "creative-studios",
        ],
    ),
    # code_builder — Creative Studios launch tile → archie.kytranempowerment.com,
    # the machine's OWN build surface (the A.R.C.H.I.E. cockpit that drives the
    # engine to write and edit code). No in-platform blueprint; opens the comms
    # cockpit in a new tab. Owner directive 2026-09-09: the studios (Site Builder,
    # Game Studio, Media Studio) build with the cloud token systems, and the
    # fourth tile here is the code builder on our machine. Its LAYOUT is the
    # cockpit UI (master-command build order 4), designed separately.
    ModuleDefinition(
        id="code_builder",
        name="Code Builder",
        description="Build and edit code on our own machine<br>Launches the A.R.C.H.I.E. cockpit at archie.kytranempowerment.com",
        icon="terminal",
        category=ModuleCategory.CREATIVE_STUDIOS,
        route="/tools/code-builder",
        external_url="https://archie.kytranempowerment.com/cockpit#builder",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=lambda: default_health_check("code_builder"),
        priority=4,
        tags=[
            "code",
            "builder",
            "archie",
            "standalone",
            "product",
            "code-builder",
            "creative-studios",
        ],
    ),
    ModuleDefinition(
        id="game_studio",
        name="Game Studio",
        description="AI-assisted game development<br>Mission editor • Asset library • Export to web and mobile",
        icon="gamepad-2",
        category=ModuleCategory.CREATIVE_STUDIOS,
        route="/tools/game-studio",
        blueprint_import="tools.game_studio.routes:game_studio_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="enterprise",
        enabled=True,
        coming_soon=False,
        health_check=game_studio_health_check,
        priority=5,
        tags=["ai", "games", "3d", "2d", "creation"],
    ),
    ModuleDefinition(
        id="archie_pool",
        name="Archie Pool",
        description="Ravencoin mining pool dashboard<br>Real-time hashrate • Earnings tracker • Auto payouts",
        icon="pickaxe",
        category=ModuleCategory.CRYPTO,
        route="/tools/archie-pool",
        blueprint_import="tools.archie_pool.routes:archie_pool_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="enterprise",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health("archie_pool", "/tools/archie-pool/api/status"),
        priority=6,
        tags=["mining", "crypto", "ravencoin", "standalone", "android"],
    ),
    ModuleDefinition(
        id="pool_management",
        name="Pool Management",
        description="Mining pool administration<br>Miner management • Payout config • Conversions • Analytics",
        icon="sliders",
        category=ModuleCategory.CRYPTO,
        route="/tools/pool-management",
        blueprint_import="tools.pool_management.routes:pool_management_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="enterprise",
        enabled=True,
        coming_soon=False,
        health_check=pool_management_health_check,
        priority=7,
        tags=["mining", "admin", "management", "payouts", "conversions"],
    ),
    ModuleDefinition(
        id="task_planner",
        name="Task Planner",
        description="Project task management<br>Kanban boards • Timelines • Team assignments",
        icon="list-checks",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/task-planner",
        blueprint_import="tools.task_planner.routes:task_planner_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=False,  # Disabled — consolidating into Dev HQ (Task #1984)
        coming_soon=False,
        health_check=lambda: default_health_check("task_planner"),
        priority=8,
        tags=["tasks", "planning", "projects", "business"],
    ),
    # content_studio removed 2026-03-30 — now in Kytran Business Suite
    ModuleDefinition(
        id="media_studio",
        name="Media Studio",
        description="AI image, video and audio generation<br>GPU-routed models • Gallery • Queue tracking • ComfyUI",
        icon="palette",
        category=ModuleCategory.CREATIVE_STUDIOS,
        route="/tools/media-studio",
        blueprint_import="tools.media_studio.routes:media_studio_bp",
        required_permissions=[],
        minimum_role="USER",
        minimum_tier="enterprise",
        enabled=True,
        coming_soon=False,
        health_check=media_studio_health_check,
        priority=11,
        tags=["ai", "images", "video", "audio", "creative", "generation", "media"],
    ),
    # Autonomy — DELETED: All features migrated to Department HQ Dispatch tab (2026-04-08)
    # User Profile - accessible to all authenticated users
    ModuleDefinition(
        id="user_profile",
        name="My Profile",
        description="View your profile, accessible modules, and notifications",
        icon="user",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/my-profile",
        blueprint_import="tools.user_profile:user_profile_bp",
        required_permissions=[],
        minimum_role="USER",
        enabled=True,
        health_check=lambda: default_health_check("user_profile"),
        priority=20,
        tags=["profile", "user", "settings", "notifications"],
        show_on_dashboard=False,
    ),
    # app_builder placeholder - not yet implemented
    # ModuleDefinition(
    #     id="app_builder",
    #     name="App Builder",
    #     description="Build mobile apps with AI<br>iOS • Android • Cross-platform • App Store deploy",
    #     icon="smartphone",
    #     category=ModuleCategory.PLACEHOLDERS_FUTURE,
    #     route="/tools/app-builder",
    #     blueprint_import="tools.app_builder.routes:app_builder_bp",
    #     required_permissions=[],
    #     minimum_role="USER",
    #     enabled=False,
    #     coming_soon=True,
    #     health_check=lambda: placeholder_health_check("app_builder", "App Builder"),
    #     priority=12,
    #     tags=["ai", "mobile", "apps", "ios", "android"],
    # ),
    # Starship Command — MERGED into Fleet Command (2026-04-08)
    # Old URLs redirect via app.py starship_compat_redirect
    # ModuleDefinition(
    #     id="starship",
    #     name="Starship Command",
    #     description="[Merged] → Fleet Command",
    #     icon="rocket",
    #     category=ModuleCategory.SAAS_SERVICES,
    #     route="/tools/starship",
    #     blueprint_import="tools.starship.routes:starship_bp",
    #     required_permissions=[],
    #     minimum_role="USER",
    #     enabled=False,
    #     health_check=lambda: default_health_check("starship"),
    #     priority=14,
    #     tags=["starship", "fleet", "nodes"],
    # ),
    ModuleDefinition(
        id="google_work_suite",
        name="Google Work Suite",
        description="Gmail, Calendar and Drive integration<br>OAuth accounts • Agent email • Smart rules • AI replies",
        icon="mail",
        category=ModuleCategory.SAAS_SERVICES,
        route="/tools/google-work-suite",
        blueprint_import="tools.google_work_suite:google_work_suite_bp",
        required_permissions=["google:email"],
        minimum_role="USER",
        minimum_tier="professional",
        enabled=True,
        coming_soon=False,
        priority=12,
        tags=["google", "gmail", "email", "calendar", "agents", "ai"],
    ),
    # ============================================
    # STANDALONE PRODUCTS (6 external launchers)
    # ============================================
    ModuleDefinition(
        id="kytran_system_ops",
        name="Kytran System Operations",
        description="Server management dashboard<br>CPU • RAM • Docker • Network • Firewall • Compliance badges",
        icon="server",
        category=ModuleCategory.ADMIN_OPERATIONS,
        route="/external/kso",
        external_url="https://server.kytranempowerment.com",
        priority=1,
        tags=["standalone", "product", "admin-operations"],
    ),
    ModuleDefinition(
        id="kytran_business_suite",
        name="Kytran Business Suite",
        description="Modular SaaS platform<br>CRM • Invoicing • Store • Website builder • 26 industry plugins",
        icon="briefcase",
        category=ModuleCategory.SAAS_SERVICES,
        route="/external/kbs",
        external_url="https://business.kytranempowerment.com",
        priority=1,
        tags=["standalone", "product"],
    ),
    ModuleDefinition(
        id="kytran_gov_watch",
        name="Kytran Gov Watch",
        description="Government tender intelligence<br>P.R.O.C.U.R.E. agent (Analytics &amp; Intelligence) • Live tenders • RFP analysis • Personalized bids",
        icon="landmark",
        category=ModuleCategory.MEDIA_OUTREACH,
        route="/external/gov",
        external_url="https://gov.kytranempowerment.com",
        priority=2,
        tags=["standalone", "product"],
    ),
    ModuleDefinition(
        id="kytran_market_watch",
        name="Kytran Market Watch",
        description="Market intelligence platform<br>Autonomous trading • Real-time feeds • Portfolio analytics",
        icon="trending-up",
        category=ModuleCategory.MEDIA_OUTREACH,
        route="/external/market",
        external_url="https://market.kytranempowerment.com",
        priority=2,
        tags=["standalone", "product"],
    ),
    ModuleDefinition(
        id="what_the_fact",
        name="What The Fact",
        description="AI-powered transparent news<br>Bias detection • Fact-check summaries • Audit trails",
        icon="newspaper",
        category=ModuleCategory.WHAT_THE_FACT,
        route="/external/wtf",
        external_url="https://what-the-fact.com",
        priority=2,
        tags=["standalone", "product", "watch-series"],
    ),
    ModuleDefinition(
        id="kytran_legal_watch",
        name="Kytran Legal Watch",
        description="Legal intelligence platform<br>Case monitoring • Regulatory alerts • Compliance tracking",
        icon="scale",
        category=ModuleCategory.MEDIA_OUTREACH,
        route="/external/legal",
        external_url="https://legal.kytranempowerment.com",
        priority=2,
        tags=["standalone", "product"],
    ),
    ModuleDefinition(
        id="kytran_civic_watch",
        name="Kytran Civic Watch",
        description="Civic engagement intelligence<br>Local government • Community alerts • Transparency tracking",
        icon="building-2",
        category=ModuleCategory.MEDIA_OUTREACH,
        route="/external/civic",
        external_url="https://civic.kytranempowerment.com",
        priority=2,
        tags=["standalone", "product"],
    ),
    ModuleDefinition(
        id="creed_institute",
        name="C.R.E.E.D. Institute",
        description="AI ethics and governance institute<br>Compliance frameworks • Agent welfare • Public transparency",
        icon="shield-check",
        category=ModuleCategory.MEDIA_OUTREACH,
        route="/external/creed",
        external_url="https://creed.kytranempowerment.com",
        priority=3,
        tags=["standalone", "product", "ethics", "governance", "creed"],
    ),
    # Cross-Watch Alert System — API-only, no dashboard card
    ModuleDefinition(
        id="cross_watch",
        name="Cross-Watch Alerts",
        description="Unified alert system — entity follows + cross-product signals",
        icon="bell",
        category=ModuleCategory.AI_COMMAND,
        route="/api/cross-watch",
        blueprint_import="tools.cross_watch:cross_watch_bp",
        required_permissions=["admin:access"],
        minimum_role="ADMIN",
        minimum_tier="staff",
        enabled=True,
        coming_soon=False,
        health_check=None,
        show_on_dashboard=False,
        priority=99,
        tags=["cross-watch", "alerts", "signals", "entities", "api"],
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
    role_hierarchy = {
        "PUBLIC": 0,
        "USER": 10,
        "PREMIUM": 20,
        "ADMIN": 90,
        "SUPER_ADMIN": 100,
    }

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
        return {
            "healthy": False,
            "module_id": module_id,
            "message": "Module not found",
            "status": "not_found",
        }

    if not module.enabled:
        return {
            "healthy": False,
            "module_id": module_id,
            "message": "Module disabled",
            "status": "disabled",
        }

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

    if module.external_url:
        return None  # External modules have no local blueprint

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
    print("\nRegistry Summary:")
    print(f"  Total Modules: {summary['total_modules']}")
    print(f"  Enabled: {summary['enabled_modules']}")
    print(f"  Disabled: {summary['disabled_modules']}")
    print(f"  Coming Soon: {summary['coming_soon_modules']}")
    print(f"  Beta: {summary['beta_modules']}")

    print("\nModules by Category:")
    for cat, stats in summary["categories"].items():
        print(f"  {cat}: {stats['enabled']}/{stats['total']} enabled")

    print("\nEnabled Modules:")
    for module in get_enabled_modules():
        print(f"  [{module.icon}] {module.name} - {module.route}")

    print("\nHealth Check Results:")
    health_results = check_all_modules_health()
    for module_id, health in health_results.items():
        status_icon = "✅" if health["healthy"] else "❌"
        print(f"  {status_icon} {module_id}: {health['message']}")

    print("\n" + "=" * 80)
