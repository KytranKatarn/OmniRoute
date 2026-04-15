"""RAM Budget Enforcer — manages model loading within the 80% memory budget.

Budget: 102GB for LLM models (80% of 128GB host RAM).
Always loaded: arctic-embed-cpu (embeddings — essential for KB operations).
Strategy: LRU eviction when budget would be exceeded by a new model load.

This module wraps ModelService with a simpler API focused on budget
enforcement and monitoring.  It is called by bridge_dispatcher before
loading any model and exposes ``get_budget_status()`` for the UI.

Called by: bridge_dispatcher.ensure_model_ready() before loading any model.
"""

import logging
import os

logger = logging.getLogger(__name__)

RAM_BUDGET_GB = float(os.environ.get("LLM_RAM_BUDGET_GB", "102"))
ALWAYS_LOADED = {"arctic-embed-cpu", "nomic-embed-text"}  # embedding models


def _get_model_service():
    """Lazy import to avoid circular dependency at module load time."""
    from services.model_service import get_model_service

    return get_model_service()


def get_loaded_models():
    """Get currently loaded models with their sizes from Ollama."""
    svc = _get_model_service()
    return svc.check_loaded_models()


def get_total_loaded_gb():
    """Total RAM used by loaded models in GB."""
    models = get_loaded_models()
    return sum(m.get("size_gb", 0) for m in models)


def get_model_size_gb(model_name):
    """Estimate model size in GB using ModelService estimates."""
    svc = _get_model_service()
    return svc.estimate_model_size(model_name)


def can_load_model(model_name):
    """Check if loading a model would stay within budget."""
    svc = _get_model_service()
    needed = svc.estimate_model_size(model_name)
    return svc.get_available_ram() >= needed


def ensure_budget_for(model_name):
    """Ensure there's room in the budget for a model, evicting if necessary.

    Delegates to ModelService.ensure_capacity() which handles priority-based
    LRU eviction (PROTECTED > HIGH > MEDIUM > LOW).

    Args:
        model_name: The model about to be loaded.

    Returns:
        True if budget allows loading, False if cannot free enough space.
    """
    svc = _get_model_service()

    # Check if model is already loaded — no budget action needed
    if svc.is_model_loaded(model_name):
        logger.debug("ram_budget: %s already loaded — no eviction needed", model_name)
        return True

    needed = svc.estimate_model_size(model_name)
    available = svc.get_available_ram()

    if available >= needed:
        logger.debug(
            "ram_budget: OK — %.1fGB available, %.1fGB needed for %s",
            available,
            needed,
            model_name,
        )
        return True

    logger.info(
        "ram_budget: %.1fGB available < %.1fGB needed for %s — triggering eviction",
        available,
        needed,
        model_name,
    )

    if svc.ensure_capacity(needed):
        new_available = svc.get_available_ram()
        logger.info(
            "ram_budget: eviction freed space — %.1fGB now available for %s",
            new_available,
            model_name,
        )
        return True

    logger.warning(
        "ram_budget: cannot free enough RAM for %s (need %.1fGB, have %.1fGB)",
        model_name,
        needed,
        svc.get_available_ram(),
    )
    return False


def get_budget_status():
    """Return current budget utilization for monitoring / UI."""
    svc = _get_model_service()
    loaded = svc.check_loaded_models()
    used = sum(m.get("size_gb", 0) for m in loaded)
    budget = svc.ram_budget_gb

    return {
        "budget_gb": budget,
        "used_gb": round(used, 1),
        "available_gb": round(budget - used, 1),
        "utilization_pct": round(used / budget * 100, 1) if budget > 0 else 0,
        "models_loaded": len(loaded),
        "models": [
            {
                "name": m["name"],
                "size_gb": round(m.get("size_gb", 0), 1),
                "priority": svc.get_model_priority(m["name"]).name,
            }
            for m in loaded
        ],
    }
