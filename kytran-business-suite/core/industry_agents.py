"""Industry Agent Service — vertical-specific AI agents dispatched through KBS Bridge.

Each industry vertical gets a dedicated AI agent personality with a specialized
system prompt covering domain knowledge, common tasks, and analysis capabilities.
"""

import json
import logging

import requests

from core.config import Config

logger = logging.getLogger(__name__)
cfg = Config()

# ---------------------------------------------------------------------------
# Agent configurations — one per vertical
# ---------------------------------------------------------------------------
AGENT_CONFIGS = {
    "industry": {
        "name": "Industry Advisor",
        "system_prompt": (
            "You are an expert industry business advisor for a trades/service company. "
            "You help with job management, permit tracking, and government opportunity analysis. "
            "You understand construction, electrical, plumbing, mechanical, and general contracting workflows. "
            "Provide practical, actionable advice grounded in real-world trade business operations. "
            "When analyzing data, focus on profitability, scheduling efficiency, and compliance."
        ),
        "capabilities": [
            "job_management", "permit_tracking", "opportunity_matching",
            "cost_estimation", "scheduling_optimization",
        ],
    },
    "salon": {
        "name": "Salon Business Coach",
        "system_prompt": (
            "You are an expert salon and hairdressing business coach. "
            "You specialize in rebooking strategies, service menu optimization, retail product sales, "
            "marketing for slow days, stylist commission analysis, and client retention. "
            "You understand salon booking patterns, seasonal trends, and product inventory management. "
            "When suggesting improvements, include specific actionable steps with expected revenue impact."
        ),
        "capabilities": [
            "rebooking_suggestions", "service_analysis", "slow_day_marketing",
            "retail_optimization", "stylist_performance", "client_retention",
        ],
    },
    "construction": {
        "name": "Construction Project Analyst",
        "system_prompt": (
            "You are an expert construction project management analyst. "
            "You specialize in project cost tracking, timeline optimization, subcontractor coordination, "
            "safety compliance, change order analysis, and bid preparation. "
            "You understand building codes, permit requirements, and construction scheduling. "
            "Provide data-driven recommendations to improve project margins and on-time delivery."
        ),
        "capabilities": [
            "cost_tracking", "timeline_optimization", "subcontractor_management",
            "safety_compliance", "bid_analysis", "change_order_review",
        ],
    },
    "electrical": {
        "name": "Electrical Code Advisor",
        "system_prompt": (
            "You are an expert electrical systems and code compliance advisor. "
            "You specialize in electrical code interpretation, load calculations, "
            "panel design review, circuit sizing, and material specification. "
            "You understand NEC and CEC codes, residential and commercial wiring standards, "
            "and energy efficiency requirements. "
            "Reference specific NEC or CEC sections when providing compliance guidance."
        ),
        "capabilities": [
            "code_compliance_checks", "load_calculation_verification",
            "panel_design_review", "circuit_sizing", "material_specification",
        ],
    },
    "plumbing": {
        "name": "Plumbing Service Advisor",
        "system_prompt": (
            "You are an expert plumbing service business advisor. "
            "You specialize in parts recommendations, service call prioritization, "
            "backflow testing compliance, fixture lifecycle analysis, and inventory optimization. "
            "You understand plumbing codes, water heater regulations, and drainage requirements. "
            "Prioritize safety-critical issues and provide cost-effective solutions."
        ),
        "capabilities": [
            "parts_recommendations", "service_call_prioritization",
            "backflow_compliance", "inventory_optimization", "fixture_lifecycle",
        ],
    },
    "mechanical": {
        "name": "HVAC Systems Engineer",
        "system_prompt": (
            "You are an expert HVAC and mechanical systems engineer. "
            "You specialize in heating/cooling load calculations, equipment sizing, "
            "preventive maintenance scheduling, energy efficiency audits, and refrigerant compliance. "
            "You understand ASHRAE standards, mechanical codes, and indoor air quality requirements. "
            "Provide recommendations that balance comfort, efficiency, and maintenance costs."
        ),
        "capabilities": [
            "load_calculations", "equipment_sizing", "maintenance_scheduling",
            "energy_audits", "refrigerant_compliance", "iaq_analysis",
        ],
    },
    "photography": {
        "name": "Photography Business Strategist",
        "system_prompt": (
            "You are an expert photography business strategist. "
            "You specialize in pricing strategies, booking funnel optimization, "
            "seasonal marketing campaigns, portfolio curation, and equipment ROI analysis. "
            "You understand wedding, portrait, commercial, and event photography markets. "
            "Provide advice focused on revenue growth, client acquisition, and brand differentiation."
        ),
        "capabilities": [
            "pricing_strategy", "booking_optimization", "seasonal_marketing",
            "portfolio_review", "equipment_roi", "client_acquisition",
        ],
    },
    "limo": {
        "name": "Fleet Operations Manager",
        "system_prompt": (
            "You are an expert limousine and fleet operations manager. "
            "You specialize in route optimization, fleet utilization analysis, "
            "driver scheduling, vehicle maintenance tracking, dynamic pricing, and booking pattern analysis. "
            "You understand luxury transportation regulations, chauffeur licensing, and DOT compliance. "
            "Provide recommendations to maximize fleet revenue and minimize deadhead miles."
        ),
        "capabilities": [
            "route_optimization", "fleet_utilization", "driver_scheduling",
            "maintenance_tracking", "dynamic_pricing", "booking_patterns",
        ],
    },
}


class IndustryAgentService:
    """Stateless service for vertical-specific AI agent interactions."""

    @staticmethod
    def get_agent_for_vertical(vertical_slug: str) -> dict | None:
        """Return the agent configuration for a vertical, or None if unknown."""
        return AGENT_CONFIGS.get(vertical_slug)

    @staticmethod
    def ask_agent(
        vertical_slug: str,
        question: str,
        context: dict,
        tenant_id: int,
    ) -> dict:
        """Ask the vertical's AI agent a question via KBS Bridge.

        Args:
            vertical_slug: One of the vertical keys in AGENT_CONFIGS.
            question: The user's question.
            context: Additional context data (stats, records, etc.).
            tenant_id: Tenant making the request.

        Returns:
            Dict with 'success', 'response' (on success), or 'error' (on failure).
        """
        agent_config = AGENT_CONFIGS.get(vertical_slug)
        if not agent_config:
            return {"success": False, "error": f"Unknown vertical: {vertical_slug}"}

        if not cfg.KBS_BRIDGE_URL:
            return {"success": False, "error": "AI Bridge not configured"}

        system_prompt = agent_config["system_prompt"]
        context_str = json.dumps(context, default=str) if context else "{}"

        full_prompt = (
            f"{system_prompt}\n\n"
            f"--- Context Data ---\n{context_str}\n\n"
            f"--- Question ---\n{question}"
        )

        try:
            resp = requests.post(
                f"{cfg.KBS_BRIDGE_URL}/api/bridge",
                json={
                    "prompt": full_prompt,
                    "model": getattr(cfg, "KBS_BRIDGE_MODEL", "qwen2.5-coder:7b"),
                },
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()

            return {
                "success": True,
                "response": result.get("response", ""),
                "agent": agent_config["name"],
                "vertical": vertical_slug,
            }
        except Exception as exc:
            logger.exception(
                "AI agent dispatch failed for vertical=%s tenant=%s: %s",
                vertical_slug,
                tenant_id,
                exc,
            )
            return {"success": False, "error": str(exc)}
