"""Auto-context injection — provides relevant knowledge when working on specific modules."""

from services.knowledge_rag_service import (
    get_module_context,
    get_recent_decisions,
)

MODULE_CONTEXT_MAP = {
    "media_studio": ["media-studio", "comfyui", "image generation", "gallery"],
    "game_studio": ["game-studio", "canvas engine", "multiplayer", "game builder"],
    "google_work_suite": ["gmail", "calendar", "drive", "google oauth"],
    "market_watch": ["market watch", "trading", "market data", "autonomous trading"],
    "website_studio": ["website-designer", "monaco", "hostinger", "deployment"],
    "content_studio": ["content writing", "writing pipeline", "seo"],
    "social_media": ["social media", "publishing", "instagram"],
    "consciousness": ["consciousness", "knowledge analytics", "embedding"],
    "starbase": ["starbase command", "dispatcher", "agent", "station"],
    "fitness": ["fitness", "workout", "exercise"],
    "therapy": ["therapy", "mood", "mental health"],
    "doc": ["health", "symptoms", "medication"],
    "task_planner": ["task planner", "kanban", "project management"],
    "archie_pool": ["mining", "ravencoin", "hashrate"],
}


def get_auto_context(file_path=None, module_name=None):
    """Generate context based on which file/module is being worked on."""
    if file_path:
        # Detect module from file path
        for mod, keywords in MODULE_CONTEXT_MAP.items():
            if mod in file_path or mod.replace("_", "-") in file_path:
                module_name = mod
                break

    if not module_name:
        return ""

    parts = []
    # Module knowledge
    context = get_module_context(module_name)
    if context:
        parts.append(f"## {module_name} Knowledge")
        for item in context[:5]:
            parts.append(f"- {item.get('title', '')}: {str(item.get('content', ''))[:200]}")

    # Recent decisions
    decisions = get_recent_decisions(module_name, limit=3)
    if decisions:
        parts.append(f"\n## Recent {module_name} Decisions")
        for d in decisions:
            parts.append(f"- {str(d.get('decision', ''))[:200]}")

    return "\n".join(parts)
