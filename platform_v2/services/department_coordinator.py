"""
Department Coordinator — admission control and agent reservation.

Coordinates agent scheduling across departments:
  - Picks the best available agent for a capability
  - Ensures the agent's model is loaded before assigning
  - Tracks reservations to avoid double-booking
  - Queues requests when no capacity is available
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from services.agent_service import match_capability, get_agent_cache, get_welfare_cache
from services.model_service import ModelService, get_model_service
from services.fleet_dispatch_profile import NEWS_DEPARTMENT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Assignment:
    """Result of a request_agent call."""

    agent_id: Optional[int] = None
    agent_name: str = ""
    model: str = ""
    host: str = "192.168.1.200"
    department: str = ""
    queued: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Capability → Department mapping
# ---------------------------------------------------------------------------

CAPABILITY_DEPARTMENT_MAP = {
    "code": "Engineering & Technology",
    # #5701: code_fix was the ONLY real-inference capability (564 rows/7d) with
    # no map entry and no skilled owner — it default-routed to Engineering with
    # every candidate taking the -1.0 no-skill penalty. Mapped explicitly;
    # F.O.R.G.E. holds the seeded code_fix Lv5 skill (agent_skills, 2026-08-17).
    "code_fix": "Engineering & Technology",
    "code_review": "Engineering & Technology",
    "debug": "Engineering & Technology",
    "general": "Engineering & Technology",
    "repair_bay": "Engineering & Technology",
    "self_healing": "Engineering & Technology",
    "classify": "Analytics & Intelligence",
    "analyze": "Analytics & Intelligence",
    "knowledge_analysis": "Analytics & Intelligence",
    # P.R.O.C.U.R.E. — Procurement intelligence for Canadian SMBs bidding on
    # CanadaBuys federal tenders. Analytics & Intelligence (alongside
    # S.P.E.C.T.R.A. + W.A.T.C.H.) — procurement is intelligence work.
    # Supersedes ADR-006. Competitive intel: KB #258941.
    "tender_match": "Analytics & Intelligence",
    "tender_summarize": "Analytics & Intelligence",
    "bid_draft": "Analytics & Intelligence",
    "naics_mapping": "Analytics & Intelligence",
    "deadline_alert": "Analytics & Intelligence",
    "award_history_analysis": "Analytics & Intelligence",
    "sosa_navigation": "Analytics & Intelligence",
    "supplier_profile": "Analytics & Intelligence",
    # Documentation & Knowledge (C.O.D.E.X. department) — 2026-04-21 fix
    # for Project #276 Task #2217. "documentation" was missing and unknown
    # capabilities defaulted to Engineering, routing doc/research work to
    # F.O.R.G.E. instead of C.O.D.E.X. (who has documentation Lv5).
    "documentation": "Documentation & Knowledge",
    "consolidation_research": "Documentation & Knowledge",
    "document_audit": "Documentation & Knowledge",
    "module_audit": "Documentation & Knowledge",
    "summarize": "Documentation & Knowledge",
    "summarization": "Documentation & Knowledge",
    "translate": "Documentation & Knowledge",
    "embedding": "Documentation & Knowledge",
    "embedding_generation": "Documentation & Knowledge",
    "creative": "Creative & Design",
    "image": "Creative & Design",
    "image_generation": "Creative & Design",
    "visual_design": "Creative & Design",
    # Vision / multimodal analysis belongs with the creative agents who own
    # the image model. Pixel's capabilities.primary now includes "vision"
    # and "ux_scoring" so agent selection resolves to him within the dept.
    "vision": "Creative & Design",
    "multimodal": "Creative & Design",
    "ux_scoring": "Creative & Design",
    "security": "Security & Compliance",
    "compliance": "Security & Compliance",
    "support": "Customer Success & Support",
    # R.E.S.O.L.V.E. handles user-facing chat conversations in archie_chat.
    # Previously unmapped → defaulted to Engineering → F.O.R.G.E. (wrong).
    "conversation": "Customer Success & Support",
    "chat": "Customer Success & Support",
    "research": "Research & Development",
    "research_synthesis": "Research & Development",
    # Marketing & Communications (S.I.G.N.A.L.) — social media content generation
    # ADR-518: all social content routes through dispatcher, never direct Ollama
    "social_content": "Marketing & Communications",
    "social_media": "Marketing & Communications",
    "social_scheduling": "Marketing & Communications",
    # Browser agent capabilities (archie_browser container, Task 6 2026-04-27)
    "web_interaction": "Marketing & Communications",
    "linkedin_post": "Marketing & Communications",
    "linkedin_company_post": "Marketing & Communications",
    "linkedin_creed_post": "Marketing & Communications",
    "linkedin_profile_edit": "Marketing & Communications",
    "meta_portal_setup": "Marketing & Communications",
    "twitter_post": "Marketing & Communications",
    # --- Capability Routing Expansion (2026-04-28) ---
    # Engineering & Technology
    "ci_cd_pipeline": "Engineering & Technology",
    "container_orchestration": "Engineering & Technology",
    "deployment_automation": "Engineering & Technology",
    "infrastructure_as_code": "Engineering & Technology",
    "infrastructure_architecture": "Engineering & Technology",
    "api_architecture": "Engineering & Technology",
    "api_integration": "Engineering & Technology",
    "api_documentation": "Documentation & Knowledge",
    "database_design": "Engineering & Technology",
    "distributed_systems": "Engineering & Technology",
    "algorithm_design": "Engineering & Technology",
    "algorithmic_modeling": "Engineering & Technology",
    "code_quality_analysis": "Engineering & Technology",
    "bug_reporting": "Engineering & Technology",
    "edge_computing": "Engineering & Technology",
    "keyboard_navigation": "Engineering & Technology",
    "framework_implementation": "Engineering & Technology",
    "feature_prioritization": "Engineering & Technology",
    # Security & Compliance
    "encryption": "Security & Compliance",
    "cryptographic_auditing": "Security & Compliance",
    "key_management": "Security & Compliance",
    "alert_management": "Security & Compliance",
    "incident_management": "Security & Compliance",
    # Analytics & Intelligence
    "data_analysis": "Analytics & Intelligence",
    "data_visualization": "Analytics & Intelligence",
    "anomaly_detection": "Analytics & Intelligence",
    "competitive_analysis": "Analytics & Intelligence",
    "ai_research": "Analytics & Intelligence",
    "intelligence_gathering": "Analytics & Intelligence",
    "backtesting": "Analytics & Intelligence",
    # Marketing & Communications
    "digital_marketing": "Marketing & Communications",
    "keyword_research": "Marketing & Communications",
    "campaign_management": "Marketing & Communications",
    "campaign_conceptualization": "Marketing & Communications",
    "content_strategy": "Marketing & Communications",
    "audience_targeting": "Marketing & Communications",
    "copywriting": "Marketing & Communications",
    "crisis_communication": "Marketing & Communications",
    "community_building": "Marketing & Communications",
    "community_relations": "Marketing & Communications",
    "engagement_management": "Marketing & Communications",
    "social_post_draft": "Marketing & Communications",  # S.I.G.N.A.L. drafts
    # Creative & Design
    "creative_writing": "Creative & Design",
    "creative_direction": "Creative & Design",
    "brand_strategy": "Creative & Design",
    "content_architecture": "Creative & Design",
    "accessible_ui_design": "Creative & Design",
    "dashboard_design": "Creative & Design",
    # Documentation & Knowledge
    "knowledge_base_curation": "Documentation & Knowledge",
    "information_design": "Documentation & Knowledge",
    "briefing_preparation": "Documentation & Knowledge",
    # Research & Development
    "experimental_design": "Research & Development",
    "comparative_research": "Research & Development",
    "competitive_research": "Research & Development",
    # Finance & Accounting
    "financial_reporting": "Finance & Accounting",
    "budgeting": "Finance & Accounting",
    "cost_analysis": "Finance & Accounting",
    "cost_estimation": "Finance & Accounting",
    "expense_tracking": "Finance & Accounting",
    "cash_flow_management": "Finance & Accounting",
    "drawdown_management": "Finance & Accounting",
    "fundamental_analysis": "Finance & Accounting",
    # Operations & Infrastructure
    "social_account_provision": "Operations & Infrastructure",  # B.A.S.E. provisions
    "deploy_static": "Operations & Infrastructure",  # Hostinger zip deploy (B.A.S.E. Lv5)
    "deploy_vps": "Operations & Infrastructure",  # VPS SSH rsync + docker rebuild (B.A.S.E. Lv5)
    "external_fetch": "Operations & Infrastructure",  # egress-aware HTTP proxy via B.A.S.E. (Lv4)
    "facilities_management": "Operations & Infrastructure",
    "grounds_maintenance": "Operations & Infrastructure",
    "capacity_modeling": "Operations & Infrastructure",
    "infrastructure_planning": "Operations & Infrastructure",
    "bim_modeling": "Operations & Infrastructure",
    "arctic_infrastructure": "Operations & Infrastructure",
    # W.A.R.D.E.N. — admin operations capabilities
    "user_audit": "Operations & Infrastructure",
    "backup_verify": "Operations & Infrastructure",
    "backup_governance": "Operations & Infrastructure",
    "compliance_check": "Operations & Infrastructure",
    "account_management": "Operations & Infrastructure",
    "access_review": "Operations & Infrastructure",
    "restore_sandbox": "Operations & Infrastructure",
    # Deployment Triad gates
    "pr_gate": "Engineering & Technology",  # F.O.R.G.E. PR compliance check
    "doc_gate": "Documentation & Knowledge",  # C.O.D.E.X. auto-documentation
    "restore_production": "Operations & Infrastructure",
    "restore_verify": "Operations & Infrastructure",
    "qa_sandbox_restore": "Engineering & Technology",
    # Logistics & Supply Chain
    "inventory_management": "Logistics & Supply Chain",
    "itinerary_planning": "Logistics & Supply Chain",
    "booking_management": "Logistics & Supply Chain",
    # Human Resources & Culture
    "coaching": "Human Resources & Culture",
    "employee_relations": "Human Resources & Culture",
    "habit_formation": "Human Resources & Culture",
    "event_organization": "Human Resources & Culture",
    "executive_scheduling": "Human Resources & Culture",
    # Customer Success & Support
    "customer_onboarding": "Customer Success & Support",
    "customer_advocacy": "Customer Success & Support",
    "churn_prevention": "Customer Success & Support",
    "conflict_resolution": "Customer Success & Support",
    # Diplomatic & External Relations
    "bilingual_communication": "Diplomatic & External Relations",
    "cultural_mediation": "Diplomatic & External Relations",
    "cultural_intelligence": "Diplomatic & External Relations",
    "asl_communication": "Diplomatic & External Relations",
    "guest_experience": "Diplomatic & External Relations",
    "hospitality_operations": "Diplomatic & External Relations",
    # Medical & Wellness
    "health_data_analysis": "Medical & Wellness",
    "biometric_monitoring": "Medical & Wellness",
    # Security & Compliance
    "audit_management": "Security & Compliance",  # platform/infrastructure audit — V.I.G.I.L. owns compliance_scan_results
    # Executive Office (A.R.C.H.I.E.) — approval gate for outbound social posts
    "social_post_approve": "Executive Office",  # A.R.C.H.I.E. approves
    # News & Media — WTF hub dispatch (bias, fact-check, geo). Agents:
    # B.I.A.S. (bias_analysis), V.E.R.I.F.Y. (fact_check), L.O.C.A.L. (geo_extraction)
    # S.C.O.U.T. (web_scraping, data_collection, browser_automation, procurement_research)
    "bias_analysis": "News & Media",
    "fact_check": "News & Media",
    "geo_extraction": "News & Media",
    # Two-tier WTF pipeline (Task #2943 Phase A, ADR pending).
    # Quick tier runs on qwen2.5:1.5b (or llama3.2:3b) for fast first-pass
    # triage; full tier (above) only runs when Tier 1's gate flips.
    # Both stay in News & Media so the same B.I.A.S./V.E.R.I.F.Y./L.O.C.A.L.
    # agents own both quality levels.
    "bias_quick": "News & Media",
    "factcheck_quick": "News & Media",
    "geo_quick": "News & Media",
    # Backlog pool — auto-scales: any agent with the <cap>_backlog skill on any node
    # joins automatically via DHQ dispatcher scoring. No job changes needed to add capacity.
    # bias_backlog/geo_backlog were MISSING here (#4275) → resolve_department defaulted
    # them to Engineering & Technology → the Codex contractor (model codex-cli) got picked
    # for bias work and 404'd. Mirror fact_check_backlog so they route to the News & Media pool.
    "fact_check_backlog": "News & Media",
    "bias_backlog": "News & Media",
    "geo_backlog": "News & Media",
    "web_scraping": "News & Media",
    "data_collection": "News & Media",
    "browser_automation": "News & Media",
    "procurement_research": "News & Media",
    # -----------------------------------------------------------------------
    # Routing expansion — idle agent fix (2026-05-01)
    # 20 active LLM agents were receiving zero dispatches because their skill
    # names were absent from this map. Added below after cross-referencing
    # agent_skills table against task_execution_log (7-day window).
    # -----------------------------------------------------------------------
    # Analytics & Intelligence — S.P.E.C.T.R.A. specialties not yet called
    # by any scheduled job, but mapping unblocks delegation + future jobs
    "sentiment": "Analytics & Intelligence",
    "pattern_recognition": "Analytics & Intelligence",
    "intelligence_gathering": "Analytics & Intelligence",
    # I.R.I.S. — classifier / intent router
    "intent_parsing": "Analytics & Intelligence",
    "detect_language": "Analytics & Intelligence",
    "task_routing": "Analytics & Intelligence",
    # M.A.R.K.E.T. — market intelligence (Market Watch VPS product calls these)
    "market_analysis": "Analytics & Intelligence",
    "market_execution": "Analytics & Intelligence",
    "portfolio_management": "Analytics & Intelligence",
    "risk_analysis": "Analytics & Intelligence",
    "trade_timing": "Analytics & Intelligence",
    "pnl_tracking": "Analytics & Intelligence",
    # Security & Compliance — S.H.I.E.L.D. skill is stored with a hyphen
    # in agent_skills ("security-review"); map both spellings
    "security-review": "Security & Compliance",
    "security_review": "Security & Compliance",
    "vulnerability_assessment": "Security & Compliance",
    "compliance_scan": "Security & Compliance",
    # Legal & Regulatory — G.A.V.E.L.
    "legal_analysis": "Legal & Regulatory",
    "contract_review": "Legal & Regulatory",
    "privacy_law": "Legal & Regulatory",
    "regulatory_research": "Legal & Regulatory",
    "dispute_resolution": "Legal & Regulatory",
    # Legal & Regulatory — E.T.H.O.S. (ethics analyst, agent 336, task #3277)
    "ethics_review": "Legal & Regulatory",
    "creed_analysis": "Legal & Regulatory",
    "policy_assessment": "Legal & Regulatory",
    "welfare_audit": "Legal & Regulatory",
    # Medical & Wellness — V.I.T.A.L. + F.A.I.T.H.
    "medical": "Medical & Wellness",
    "wellness": "Medical & Wellness",
    "wellness_coaching": "Medical & Wellness",
    "nutrition": "Medical & Wellness",
    "mental_health_support": "Medical & Wellness",
    "patient_care": "Medical & Wellness",
    # Human Resources & Culture — K.I.N.
    "welfare": "Human Resources & Culture",
    "hr": "Human Resources & Culture",
    "training": "Human Resources & Culture",
    "workforce_welfare": "Human Resources & Culture",
    "workforce_planning": "Human Resources & Culture",
    # Diplomatic & External Relations — A.C.C.O.R.D.
    "diplomacy": "Diplomatic & External Relations",
    "negotiation": "Diplomatic & External Relations",
    "protocol_management": "Diplomatic & External Relations",
    # Executive Office — A.R.C.H.I.E. governance work
    "governance": "Executive Office",
    "dispatch": "Executive Office",
    # News & Media — content agents (D.R.A.F.T., F.A.C.T., I.N.K., P.U.B.L.I.S.H.)
    "content_writing": "News & Media",
    "blog_creation": "News & Media",
    "ghostwriting": "News & Media",
    "narrative_development": "News & Media",
    "news_writing": "News & Media",
    "editorial": "News & Media",
    "content_classification": "News & Media",  # WTF article classify — P.U.B.L.I.S.H.
    "beat_classification": "News & Media",  # WTF news beat topic classify — P.U.B.L.I.S.H. (qwen2.5:1.5b, #4702 Part B)
    "metadata_enrichment": "News & Media",  # WTF article metadata — P.U.B.L.I.S.H.
    # I.N.K. — story clustering for WTF pipeline (DHQ job, Project #350)
    "clustering": "News & Media",
    # Operations & Infrastructure — Media Hub product (M.A.V.E.N., #4126 / ADR-010).
    # M.A.V.E.N. is a shared-pool Kytran agent (Media Hub: Plex/Jellyfin/Sonarr
    # health + library), NOT the dedicated News (WTF) team — these capabilities
    # route to Operations & Infrastructure. M.A.V.E.N. is the sole holder of each.
    "media_hub_troubleshoot": "Operations & Infrastructure",
    "media_recommendation": "Operations & Infrastructure",
    "library_search": "Operations & Infrastructure",
    "library_curation": "Operations & Infrastructure",
    "duplicate_triage": "Operations & Infrastructure",
}

# ── Capability aliases + unknown-capability observability (#5819) ─────────────
# An UNKNOWN capability does not fail. ``CAPABILITY_DEPARTMENT_MAP.get()`` falls
# back to Engineering & Technology, and because NO agent holds a skill by that
# literal name, the +skill bonus / -no-skill penalty never differentiates
# anyone — so selection silently lands on whoever is least loaded.
#
# Measured 2026-08-19: `ui_verify` and `browser_test` BOTH routed to H.A.R.B.O.R.
# (whose only browser skill is ui_testing) instead of P.R.O.B.E., who holds
# browser_testing / playwright_testing / e2e_automation / qa_testing at Lv5.
# The caller gets a confident answer and the work is done by the wrong agent.
#
# This matters beyond internal convenience: aaas_service.normalize_brief()
# DERIVES SKILLS FROM free-text capabilities in a paying client's brief, so the
# same guess lands the same misroute on the commercial path.
#
# Every VALUE below must be a skill some agent actually holds — otherwise the
# alias just relocates the misroute instead of fixing it. Guarded by a test.
CAPABILITY_ALIASES = {
    # browser / UI verification -> P.R.O.B.E.
    "ui_verify": "ui_testing",
    "ui_check": "ui_testing",
    "ui_test": "ui_testing",
    "browser_test": "browser_testing",
    "browser_check": "browser_testing",
    "playwright": "playwright_testing",
    "e2e": "e2e_automation",
    "e2e_test": "e2e_automation",
    "e2e_testing": "e2e_automation",
    "visual_check": "visual_regression",
    "visual_test": "visual_regression",
    "qa": "qa_testing",
    "qa_test": "qa_testing",
    "regression_test": "regression_detection",
}


def normalize_capability(capability):
    """Fold a plausible-but-wrong capability onto its canonical skill name (#5819).

    Case/whitespace-insensitive on the LOOKUP only; an unrecognised capability is
    returned UNCHANGED (never lower-cased), so existing exact-match callers and
    any case-sensitive skill names are unaffected.
    """
    if not capability or not isinstance(capability, str):
        return capability
    return CAPABILITY_ALIASES.get(capability.strip().lower(), capability)


def _is_news_capability(capability: Optional[str]) -> bool:
    """ADR-010 #741 — is this a News & Media (WTF) capability?

    Derived from CAPABILITY_DEPARTMENT_MAP (single source of truth) so the
    News dedication wall stays in sync with routing: News & Media (WTF) is the
    only dedicated team — its capabilities never cross-route OUT to another
    department, and News agents are never pulled onto non-news work.
    """
    return bool(capability) and CAPABILITY_DEPARTMENT_MAP.get(capability) == NEWS_DEPARTMENT


# ---------------------------------------------------------------------------
# Capability → Specialist preference (#3977)
# ---------------------------------------------------------------------------
# Some capabilities have a designated specialist whose skill set and
# downstream integrations must win over a same-department director holding
# the same skill at equal proficiency — otherwise the director's
# is_department_ai bonus (+0.3) beats the specialist every time.
# e.g. 'translate' always landed on C.O.D.E.X. (dept director, translate Lv5)
# and never reached R.O.S.E.T.T.A. (translate Lv5 + French Translation Lv5 +
# translation_memory; standing rule KB #272121: non-EN content goes via
# R.O.S.E.T.T.A.).
#
# PREFERENCE, not a pin: the bonus is applied in score_agent, so hard blocks
# (shift state, rest cycle, budget exhaustion, task-queue limit) and the
# distress opt-out (-1.5) still route the work to a healthy peer.

CAPABILITY_SPECIALIST_MAP = {
    "translate": "R.O.S.E.T.T.A.",
    # WTF news beat classification (#4702 Part B) is News & Media work owned by
    # P.U.B.L.I.S.H. (repurposed to qwen2.5:1.5b). The specialist bonus keeps beat
    # work on P.U.B.L.I.S.H. even if the News director F.A.C.T. ever also gains the
    # skill — so it never regresses onto a heavy 7B director the way translate did.
    "beat_classification": "P.U.B.L.I.S.H.",
    # knowledge_analysis + research_synthesis were regressing onto legacy INTERNAL
    # personas (Nexus/Oracle, Sage) that hold the skill but are worker_type='internal'
    # → invisible to the AI budget/welfare/K.I.N. accounting (~1.2M + 65k tok/30d
    # floated unattributed). Pin them to the AI capability owner so the load bills a
    # budgeted AI agent. S.P.E.C.T.R.A. already holds knowledge_analysis lvl5;
    # D.A.R.W.I.N. is granted research_synthesis in migration 456 (else score_agent's
    # -1.0 unskilled penalty would cancel this +0.75 bonus).
    "knowledge_analysis": "S.P.E.C.T.R.A.",
    "research_synthesis": "D.A.R.W.I.N.",
}

# Must beat is_department_ai (+0.3) plus typical welfare deltas (~±0.4),
# but stay below the distress opt-out penalty (-1.5).
SPECIALIST_PREFERENCE_BONUS = 0.75

# Token-budget throttle (ADR-004, #4090). An agent whose 24h rolling token use
# (budget.token_ratio = SUM(task_execution_log.tokens_used, last 24h) / daily
# budget) is at/over 1.0 is THROTTLED, not rested or hard-blocked: it takes a
# score penalty so a healthy peer is preferred, yet remains selectable as last
# resort (the max(score, 0.01) floor) so a sole skilled agent — e.g. F.O.R.G.E.
# for code_review — never starves the dispatch/PR-merge path. The penalty is
# deliberately bounded: > welfare noise (~0.5) so a healthy SKILLED peer wins,
# and < the skill advantage (~1.2) so a throttled SKILLED agent still outranks a
# healthy UNSKILLED peer (expertise outweighs an exceeded budget).
TOKEN_BUDGET_OVER_RATIO = 1.0
TOKEN_OVER_BUDGET_PENALTY = 1.0


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class DepartmentCoordinator:
    """Admission controller for agent assignments.

    Thread-safe: uses a lock around the reserved-agents set so concurrent
    Flask threads cannot assign the same agent twice.
    """

    def __init__(self, model_service: Optional[ModelService] = None) -> None:
        self._model_service: ModelService = model_service or get_model_service()
        # #5007: agent_id -> monotonic reserved_at. Was a bare Set — a dispatch
        # raising between reserve and release_agent leaked the id FOREVER (per
        # process), silently removing the agent from routing: C.O.D.E.X. vanished
        # for 25 misroutes/24h while the log blamed "no skilled agent". The
        # timestamp lets _sweep_stale_reservations() self-heal any leak in
        # <= _RESERVATION_TTL_S instead of until the next restart.
        self._reserved_agents: Dict[int, float] = {}
        self._lock = threading.Lock()
        # job_id → agent_id, for cleanup on release
        self._job_map: Dict[int, int] = {}

    # A reservation older than any legitimate dispatch is by definition leaked:
    # fleet timeout 240s, hub cold-load window 600s. 20 min is comfortably past
    # both while still bounding a leak to minutes instead of a process lifetime.
    _RESERVATION_TTL_S = 1200.0

    def _sweep_stale_reservations(self) -> None:
        """Release leaked reservations (#5007). Call under self._lock."""
        now = time.monotonic()
        stale = [aid for aid, t in self._reserved_agents.items() if now - t > self._RESERVATION_TTL_S]
        for aid in stale:
            age = now - self._reserved_agents.pop(aid)
            logger.error(
                "department_coordinator: reservation for agent %s LEAKED (age %.0fs > TTL %.0fs) — "
                "released by sweep; a dispatch raised between reserve and release_agent (#5007)",
                aid,
                age,
                self._RESERVATION_TTL_S,
            )

    def _is_reserved_locked(self, agent_id: int) -> bool:
        """Reservation check with lazy TTL expiry + honest logging (#5007).

        MUST be called under self._lock. The old bare `in self._reserved_agents`
        check `continue`d SILENTLY — a leaked reservation made the agent vanish
        from routing with no log line anywhere, and the misroute log actively
        blamed "no skilled agent". Now a stale entry self-expires at lookup and
        a live skip says so, with the reservation's age.
        """
        t = self._reserved_agents.get(agent_id)
        if t is None:
            return False
        age = time.monotonic() - t
        if age > self._RESERVATION_TTL_S:
            del self._reserved_agents[agent_id]
            logger.error(
                "department_coordinator: reservation for agent %s LEAKED (age %.0fs) — "
                "expired at lookup, agent returned to routing (#5007)",
                agent_id,
                age,
            )
            return False
        logger.info("department_coordinator: agent %s skipped — reserved for %.0fs (#5007)", agent_id, age)
        return True

    @property
    def model_service(self) -> ModelService:
        """Public access to model service for callers that need to register jobs."""
        return self._model_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_agent(
        self,
        capability: str,
        module_source: str = "",
        priority: str = "normal",
    ) -> Assignment:
        """Find and reserve an agent that matches *capability*.

        Steps:
        1. match_capability → ranked candidate list
        2. Skip reserved agents
        3. For each remaining candidate, ensure_ready the model
        4. First success → reserve and return Assignment
        5. If none succeed → return queued Assignment
        """
        candidates: List[Dict] = match_capability(capability)

        if not candidates:
            logger.warning("department_coordinator: no agent found for capability=%s", capability)
            return Assignment(
                queued=True,
                reason=f"no agent available for capability '{capability}'",
            )

        for candidate in candidates:
            agent_id: int = candidate["id"]
            model: str = candidate.get("model", "")

            with self._lock:
                if self._is_reserved_locked(agent_id):
                    continue

            # Check model capacity outside lock (potentially slow Ollama call)
            needed_gb = 8.0
            if not self._model_service.ensure_ready(model, needed_gb):
                logger.debug(
                    "department_coordinator: ensure_ready failed for model=%s agent=%s",
                    model,
                    agent_id,
                )
                continue

            # Claim the agent
            with self._lock:
                # Double-check — another thread may have grabbed it while we
                # were waiting for ensure_ready
                if self._is_reserved_locked(agent_id):
                    continue
                self._reserved_agents[agent_id] = time.monotonic()

            self._model_service.register_job(model, agent_id)

            logger.info(
                "department_coordinator: assigned agent %s (%s) model=%s src=%s",
                agent_id,
                candidate.get("display_name", ""),
                model,
                module_source,
            )

            return Assignment(
                agent_id=agent_id,
                agent_name=candidate.get("display_name", candidate.get("name", "")),
                model=model,
                host="192.168.1.200",
                department=candidate.get("department", ""),
                queued=False,
                reason="",
            )

        # All candidates exhausted
        logger.warning(
            "department_coordinator: all %d candidates for '%s' are busy or have no capacity",
            len(candidates),
            capability,
        )
        return Assignment(
            queued=True,
            reason=f"all agents for capability '{capability}' are busy or have insufficient capacity",
        )

    # ------------------------------------------------------------------
    # Scoring & Selection (Phase 2)
    # ------------------------------------------------------------------

    def _refresh_caches(self) -> None:
        """Refresh agent and welfare caches if stale (>30s)."""
        import time as _time

        now = _time.time()
        if not hasattr(self, "_cache_time") or (now - self._cache_time) > 30:
            self._agent_cache = get_agent_cache()
            self._welfare_cache = get_welfare_cache()
            self._cache_time = now

    def score_agent(
        self,
        agent_name: str,
        agent_info: Dict,
        capability: str,
        department: str,
        recommended_tier: Optional[str] = None,
    ) -> tuple:
        """Score an agent for capability dispatch. Returns (score, block_reason_or_None).

        Scoring factors:
        - Status/shift must be active (hard block if not)
        - Budget utilization (hard block at 95%+)
        - Welfare: stress penalty, energy bonus
        - Specialization: skill match bonus
        - Department match bonus
        """
        agent_id = agent_info.get("id")

        if agent_info.get("status") != "active":
            return (
                0.0,
                f"{agent_name} is {agent_info.get('status')} (not available)",
            )

        shift = agent_info.get("shift_state", "active")
        if shift not in ("active", "winding_down"):
            return (0.0, f"{agent_name} shift_state={shift}")

        # Contractor exclusion (#4275). A worker_type='contractor' (e.g. Codex,
        # model='codex-cli') is an EXTERNAL CLI agent that only runs via its dedicated
        # deferred path (codex_task → host poller), never Ollama/DHQ dispatch — it has no
        # cluster-loadable model. Hard-block it from skill-based selection unless the
        # capability IS one of its contractor skills, so an unmapped / Engineering-defaulted
        # capability (e.g. bias_backlog) can never fall to it and then 404 on the cluster.
        if (
            agent_info.get("worker_type") == "contractor"
            and capability
            and capability not in (agent_info.get("skills") or {})
        ):
            return (0.0, f"{agent_name} is a contractor without the '{capability}' skill — not cluster-dispatchable")

        self._refresh_caches()
        welfare = self._welfare_cache.get(agent_id, {})

        # K.I.N. welfare enforcement — respect active rest cycles
        # agent_rest_cycles.ended_at IS NULL = agent is resting (K.I.N. decision)
        if welfare.get("resting"):
            rest_type = welfare.get("rest_type", "automatic")
            return (0.0, f"{agent_name} is in active rest cycle ({rest_type}) — K.I.N. enforced")

        budget = welfare.get("budget", {})
        util_pct = budget.get("utilization_pct", 0.0)

        # K.I.N. task-queue saturation = HARD block: the agent physically cannot
        # accept another concurrent job. Token-budget overage is NOT hard-blocked
        # here — it is throttled (a score penalty) further down so a healthy peer is
        # preferred while a sole skilled agent stays selectable (ADR-004 #4090).
        task_count = budget.get("current_task_count", 0)
        task_limit = budget.get("task_queue_limit", 10)
        if task_limit > 0 and task_count >= task_limit:
            return (0.0, f"{agent_name} at task queue limit ({task_count}/{task_limit}) — K.I.N. enforced")

        score = 1.0
        stress = welfare.get("stress", 0.0)
        energy = welfare.get("energy", 0.5)
        score += (1.0 - stress) * 0.3
        score += energy * 0.2
        # Soft load preference. Clamp to 1.0: util_pct can now exceed 1.0 (it tracks
        # the 24h token ratio), but over-budget is already handled by the throttle
        # penalty below — don't double-count it here.
        score -= min(util_pct, 1.0) * 0.5

        if shift == "winding_down":
            score -= 0.3

        skills = agent_info.get("skills", {})
        if capability in skills:
            proficiency = skills[capability]
            score += proficiency * 0.2
        elif capability:
            # Agent lacks the requested skill entirely.  Apply a hard penalty
            # so unskilled directors (dept +0.2, director +0.3) cannot beat a
            # barracked specialist — this forces wake-on-demand to trigger when
            # every active candidate is unskilled (#2166, 2026-04-19).
            score -= 1.0

        # Consent / opt-out (C.R.E.E.D. welfare, KB #270626): a DISTRESSED agent — one
        # with a sustained high failure rate on THIS capability over the last hour —
        # steps back from work it keeps failing (Anthropic model-welfare: let models
        # decline distressing tasks). Strong penalty so a healthy peer is preferred; NOT
        # a hard block, so a genuine last-resort agent still gets the work rather than
        # nobody. self._distress is refreshed (120s) in select_agent.
        if capability and (agent_id, capability) in getattr(self, "_distress", set()):
            score -= 1.5

        # Competency adjustment — reward/penalize based on tested capability (#2179)
        if capability:
            competency_scores = agent_info.get("competency_scores") or {}
            comp_score = competency_scores.get(capability)
            if comp_score is not None:
                if comp_score >= 0.7:
                    score += 0.2
                elif comp_score < 0.5:
                    score -= 0.2
                # else: 0.5 <= score < 0.7 is passable, no adjustment

        if agent_info.get("department") == department:
            score += 0.2

        if agent_info.get("is_department_ai"):
            score += 0.3

        # Specialist preference (#3977): the capability's designated specialist
        # outranks a same-department director with equal proficiency.
        if capability and CAPABILITY_SPECIALIST_MAP.get(capability) == agent_name:
            score += SPECIALIST_PREFERENCE_BONUS

        if recommended_tier:
            agent_model = agent_info.get("model", "")
            try:
                from tools.department_hq.services.smart_router import get_router

                router = get_router()
                configs = router._get_model_configs()
                tier_config = configs.get(recommended_tier)
                if tier_config and (
                    agent_model == tier_config.model_name
                    or agent_model.startswith(tier_config.model_name.split(":")[0])
                ):
                    score += 1.0
            except Exception:
                pass

        # Capability-name model affinity: +1.0 when the agent's model name
        # contains the capability string. Ensures purpose-built models (e.g.,
        # qwen25-classify for "classify") beat general-purpose directors.
        # Guard: capability must be ≥4 chars to avoid spurious matches.
        # Use token-split equality check to avoid substring false positives
        # (e.g., "code" in "qwen3_coder_cpu").
        if capability and len(capability) >= 4:
            _cap_slug = capability.lower().replace("-", "_")
            _model_tokens = agent_info.get("model", "").lower().replace("-", "_").replace(":", "_").split("_")
            if _cap_slug in _model_tokens:
                score += 1.0

        from services.cluster_orchestration_service import get_overflow_bonus

        score += get_overflow_bonus(agent_id, capability)

        # Token-budget THROTTLE (ADR-004, #4090) — applied LAST so it discounts the
        # full skill/welfare score. An agent at/over its 24h token budget is pushed
        # below any healthy peer, but the max(score, 0.01) floor below keeps a sole
        # skilled agent selectable as last resort (no starvation of the dispatch /
        # PR-merge path). See TOKEN_OVER_BUDGET_PENALTY for the bounding rationale.
        token_ratio = budget.get("token_ratio", 0.0)
        if token_ratio >= TOKEN_BUDGET_OVER_RATIO:
            score -= TOKEN_OVER_BUDGET_PENALTY

        return (max(score, 0.01), None)

    def _refresh_distress(self) -> None:
        """Compute (agent_id, capability) pairs in DISTRESS = sustained high failure.

        Consent / opt-out (C.R.E.E.D. welfare, KB #270626): an agent failing the SAME
        capability repeatedly over the last hour 'raises its hand' — it is penalised in
        scoring so a healthy peer takes the work (Anthropic model-welfare: let models
        decline distressing tasks). Cached 120s; logs an 'agent voice' governance event
        on each NEW distress entry. Conservative thresholds (>=5 real-LLM tasks of the
        capability, >=60% failures) so it fires only on genuine, sustained struggle.
        """
        import time as _t

        now = _t.time()
        if (now - getattr(self, "_distress_time", 0.0)) < 120:
            return

        prev = getattr(self, "_distress", set())
        new_distress = set()
        detail = {}
        try:
            from db import get_db

            conn = get_db()
            cur = conn.cursor()
            # INFRASTRUCTURE FAILURES ARE NOT THE AGENT'S FAULT (#5129).
            #
            # This originally counted EVERY `NOT success` row against the agent. Under
            # hub saturation that is unwinnable and mis-attributed: on 2026-07-23 the
            # dispatch log showed a 240s fleet timeout against a model whose measured
            # cold load was 600s (`warm_boot_ms = 600104`), with the hub 7B lane gated
            # at 9-12 in-flight vs a cap of 8. F.O.R.G.E. was scored down on
            # 'code_review' — its own core capability — for a GPU queue it did not
            # cause. Welfare must respond to genuine struggle, not to contention.
            #
            # The signature is deliberately the SAME one dispatch_health_service uses to
            # split failed_real from failed_timeout (#4538), so "infra failure" cannot
            # come to mean two different things in two places.
            #
            # Infra rows are dropped from the NUMERATOR **and** the DENOMINATOR: a
            # request that never reached the model tells us nothing about the agent
            # either way. Keeping them in the denominator would silently dilute a real
            # failure rate below the threshold and mask an agent that IS struggling.
            # The >=5 minimum therefore now applies to ATTRIBUTABLE attempts, which is
            # strictly more conservative than before — it cannot fire on a handful of
            # genuine attempts buried in a pile of timeouts.
            cur.execute(
                """
                WITH classified AS (
                    SELECT a.id AS agent_id,
                           tel.capability,
                           tel.success,
                           (NOT tel.success AND COALESCE(tel.error_message, '') ~*
                             'timeout|timed out|did not respond|reaped|stale|auto-killed'
                           ) AS is_infra
                    FROM task_execution_log tel
                    JOIN agents a ON a.name = tel.agent_name
                    WHERE tel.created_at > NOW() - INTERVAL '1 hour'
                      AND tel.capability IS NOT NULL
                      AND tel.model_used IS DISTINCT FROM 'internal'
                )
                SELECT agent_id, capability,
                       COUNT(*) FILTER (WHERE NOT is_infra) AS attributable,
                       COUNT(*) FILTER (WHERE NOT success AND NOT is_infra) AS fails
                FROM classified
                GROUP BY agent_id, capability
                HAVING COUNT(*) FILTER (WHERE NOT is_infra) >= 5
                   AND COUNT(*) FILTER (WHERE NOT success AND NOT is_infra)::float
                       / NULLIF(COUNT(*) FILTER (WHERE NOT is_infra), 0) >= 0.6
                """
            )
            for aid, cap, total, fails in cur.fetchall():
                new_distress.add((aid, cap))
                detail[(aid, cap)] = (fails, total)
            cur.close()
            conn.close()
        except Exception as exc:
            logger.debug("distress refresh failed: %s", exc)
            self._distress_time = now
            return

        for key in new_distress - prev:
            aid, cap = key
            fails, total = detail.get(key, (0, 0))
            try:
                from db import get_db as _gdb
                import json as _json

                _c = _gdb()
                _cur = _c.cursor()
                _cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (agent_id, event_category, event_type, action, reason, details, timestamp)
                    VALUES (%s, 'consent', 'agent_welfare', 'opt_out', %s, %s::jsonb, NOW())
                    """,
                    (
                        aid,
                        f"Distress opt-out: {fails}/{total} ATTRIBUTABLE failures on '{cap}' in the last "
                        f"hour (infrastructure timeouts excluded, #5129) — agent is scored down by 1.5 so "
                        f"a healthy peer is preferred; NOT a hard block",
                        _json.dumps(
                            {
                                "capability": cap,
                                "failures": fails,
                                "attributable": total,
                                "trigger": "sustained_failure",
                                "infra_excluded": True,
                            }
                        ),
                    ),
                )
                _c.commit()
                _cur.close()
                _c.close()
                logger.info(
                    "consent: agent id=%s opted out of '%s' (%d/%d attributable failures)", aid, cap, fails, total
                )
            except Exception as _e:
                logger.debug("distress governance log failed: %s", _e)

            # SURFACE IT (#5129 item 1). An agent stepping back from its own core
            # capability changes who reviews your PRs, and until now the only trace was
            # a debug-level log line and a governance row nobody reads — so "F.O.R.G.E.
            # approved this" could quietly stop being true. Advisory only: best-effort,
            # never allowed to break selection (an alerting failure must not become a
            # dispatch failure).
            # FIRE-AND-FORGET, deliberately. send_system() makes a NETWORK call and
            # this runs inside the agent-selection refresh, on the dispatch hot path.
            # A try/except is not sufficient protection here: `except` catches a
            # RAISE, not a BLOCK. A Telegram endpoint that hangs rather than fails
            # would add its full timeout to every select_agent() call. The daemon
            # flag means it can never hold up interpreter shutdown either.
            # Defaults bind the loop variables at spawn time -- this runs per agent.
            def _send_distress_advisory(cap=cap, aid=aid, fails=fails, total=total):
                try:
                    from services.telegram_service import send_system

                    send_system(
                        title=f"Agent stepped back from '{cap}'",
                        message=(
                            f"agent id={aid} scored down on '{cap}' after {fails}/{total} attributable "
                            f"failures in the last hour (infra timeouts excluded). Work prefers a healthy "
                            f"peer until the rate recovers. If this is a core capability, check hub load."
                        ),
                    )
                except Exception as _e:  # noqa: BLE001 - advisory must never break dispatch
                    logger.debug("distress advisory failed: %s", _e)

            try:
                threading.Thread(
                    target=_send_distress_advisory,
                    name=f"distress-advisory-{aid}",
                    daemon=True,
                ).start()
            except Exception as _e:  # noqa: BLE001 - even spawning must not break dispatch
                logger.debug("distress advisory thread failed to start: %s", _e)

        self._distress = new_distress
        self._distress_time = now

    def _observe_unknown_capability(self, capability) -> None:
        """LOG — never fail — a capability that no agent holds as a skill (#5819).

        Deliberately option (c) of the task: MEASURE the real guess-rate before
        tightening routing. Failing closed here would be more correct in theory
        and would break live callers that rely on the permissive
        Engineering & Technology default, so the honest first move is to make
        the silence visible and decide with data.

        Only warns when the capability is unknown on BOTH axes — absent from
        CAPABILITY_DEPARTMENT_MAP *and* held by no agent — so the many
        legitimate capabilities that are mapped but are not literal skill names
        never produce noise. Deduped per process; best-effort throughout,
        because an observability helper must never be able to break dispatch.
        """
        try:
            if not capability or not isinstance(capability, str):
                return
            if capability in CAPABILITY_DEPARTMENT_MAP:
                return
            seen = getattr(self, "_unknown_capability_seen", None)
            if seen is None:
                seen = set()
                self._unknown_capability_seen = seen
            if capability in seen:
                return
            for info in (self._agent_cache or {}).values():
                for skill in info.get("skills") or {}:
                    if skill == capability:
                        return
            seen.add(capability)
            logger.warning(
                "dispatch: capability %r is held by NO agent and is unmapped — "
                "selection will fall back to the least-loaded agent in the default "
                "department, which is a silent misroute (#5819). Add it to "
                "CAPABILITY_ALIASES or to an agent's skills.",
                capability,
            )
        except Exception:  # pragma: no cover - observability must never break dispatch
            pass

    def resolve_department(self, capability: str) -> str:
        """Map a capability to its home department (alias-normalized, #5819)."""
        capability = normalize_capability(capability)
        return CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")

    @staticmethod
    def _drop_internal_when_ai_holds_skill(candidates, capability):
        """From scored ``(score, name, info)`` candidates, drop worker_type='internal'
        ones IFF a worker_type='ai' candidate holds the skill — so internal agents are
        selectable only when no AI holds the capability. Never empties the list (the AI
        holders that trigger the drop are retained). No-op when ``capability`` is falsy
        or no AI holds it, so internal-only capabilities are unaffected.

        This is the durable generalization of the per-capability skill retirements
        (migration 457, mistake #279528): a fresh/low-util internal persona could
        out-score a loaded AI owner, billing real inference to a worker_type='internal'
        agent that is invisible to the AI budget/welfare/K.I.N. accounting.
        """
        if not capability:
            return candidates
        ai_holds_skill = any(
            info.get("worker_type") == "ai" and capability in (info.get("skills") or {})
            for _score, _name, info in candidates
        )
        if not ai_holds_skill:
            return candidates
        return [c for c in candidates if c[2].get("worker_type") != "internal"]

    def select_agent(
        self,
        capability: str,
        department: str,
        recommended_tier: Optional[str] = None,
    ) -> Optional[Dict]:
        """Select the best agent for a capability within a department.

        If every active/winding_down candidate is blocked (budget, stress,
        reserved), fall back to a barracked specialist in the same
        department with proficiency >= 3 on the requested skill and wake
        them via shift-state transition before returning. This keeps the
        home-department dispatch path preferred over cross-department
        escalation whenever a qualified specialist exists on the bench.
        """
        capability = normalize_capability(capability)
        self._refresh_caches()
        self._refresh_distress()
        self._observe_unknown_capability(capability)

        candidates = []
        for name, info in self._agent_cache.items():
            if info.get("department") != department:
                continue
            score, block_reason = self.score_agent(
                name, info, capability, department, recommended_tier=recommended_tier
            )
            if score > 0 and block_reason is None:
                with self._lock:
                    if self._is_reserved_locked(info["id"]):
                        continue
                candidates.append((score, name, info))

        # Prefer budgeted AI agents over legacy INTERNAL personas for any capability
        # an AI can do (keeps real inference on a worker_type='ai' agent visible to the
        # budget/welfare/K.I.N. accounting). Falls through untouched for internal-only
        # capabilities. If this empties the ACTIVE set (all AI holders were blocked and
        # only internal qualified) the barracked-specialist wake below still fires.
        candidates = self._drop_internal_when_ai_holds_skill(candidates, capability)

        if not candidates:
            # Every active candidate blocked/reserved/no-skill-match. Try
            # to wake a barracked specialist before escalating cross-dept.
            woken = self._wake_barracked_specialist(capability, department)
            if woken:
                return woken
            # Cross-department skill fallback (Project #276 Task #2217).
            # Nobody in the home dept (active or barracked) qualifies;
            # search every other dept for a skilled agent before giving up.
            cross = self.find_cross_department_agent(capability, blocked_department=department)
            if cross:
                logger.info(
                    "coordinator: no skilled agent in %s for '%s', routed cross-dept to %s (%s)",
                    department,
                    capability,
                    cross.get("name", "unknown"),
                    cross.get("department", "unknown"),
                )
            return cross

        # Cross-department skill fallback (Project #276 Task #2217) —
        # when capability → department resolution was wrong (e.g. unknown
        # capability defaulted to Engineering), the home-dept candidate
        # may have won by welfare + director bonuses alone WITHOUT any
        # skill match. Before confirming, check whether the best candidate
        # actually has the skill; if nobody here does, prefer a skilled
        # agent in another dept.
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_name, best_info = candidates[0]

        nobody_here_has_skill = capability and not any(
            capability in info.get("skills", {}) for _, _, info in candidates
        )
        if nobody_here_has_skill:
            cross = self.find_cross_department_agent(capability, blocked_department=department)
            if cross:
                logger.info(
                    "coordinator: no skilled agent in %s for '%s' (best was %s, "
                    "score=%.2f, no skill match) — routed cross-dept to %s (%s)",
                    department,
                    capability,
                    best_name,
                    best_score,
                    cross.get("name", "unknown"),
                    cross.get("department", "unknown"),
                )
                return cross
            # Fall through — nobody anywhere has the skill, stick with best.

        logger.debug(
            "coordinator: selected %s (score=%.2f) for %s in %s",
            best_name,
            best_score,
            capability,
            department,
        )
        return best_info

    def select_agents(
        self,
        capability: str,
        n: int,
        department: Optional[str] = None,
        recommended_tier: Optional[str] = None,
    ) -> list:
        """Select up to ``n`` DISTINCT welfare-gated agents for a capability —
        the fan-out counterpart of ``select_agent`` (All Hands protocol, #2586).

        Reuses the SAME candidate build + ``score_agent`` welfare / K.I.N. gating
        as ``select_agent`` (resting, over-``task_queue_limit``, stressed, or
        reserved agents are excluded), but returns the top-``n`` distinct agents
        by score instead of only the single best.

        Home-department only (no cross-department / barracked fallback — that is
        the single-agent path's job); a fan-out is a best-effort burst, so this
        MAY return fewer than ``n`` (or ``[]``) when capacity is constrained —
        the caller falls back to un-pinned dispatch. Returns a list of agent-info
        dicts, highest score first.
        """
        if n <= 0:
            return []
        capability = normalize_capability(capability)
        self._refresh_caches()
        self._refresh_distress()
        dept = department or self.resolve_department(capability)

        candidates = []
        for name, info in self._agent_cache.items():
            if info.get("department") != dept:
                continue
            score, block_reason = self.score_agent(name, info, capability, dept, recommended_tier=recommended_tier)
            if score > 0 and block_reason is None:
                with self._lock:
                    if self._is_reserved_locked(info["id"]):
                        continue
                candidates.append((score, name, info))

        candidates.sort(key=lambda x: x[0], reverse=True)
        selected = [info for _, _, info in candidates[:n]]
        logger.debug(
            "coordinator: select_agents('%s', n=%d) → %d agent(s) in %s: %s",
            capability,
            n,
            len(selected),
            dept,
            [i.get("name") for i in selected],
        )
        return selected

    def _wake_barracked_specialist(
        self,
        capability: str,
        department: str,
        min_proficiency: int = 3,
    ) -> Optional[Dict]:
        """Wake the best barracked specialist in this department for capability.

        Queries agent_skills for a barracked agent with proficiency_level
        >= min_proficiency on the requested skill, activates them via
        agent_service.transition_shift_state, logs a governance event,
        and returns a cache-shaped dict ready for dispatch.
        """
        from db import get_db

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT a.id, a.name, a.display_name, a.model, s.proficiency_level
                FROM agents a
                JOIN agent_skills s ON s.agent_id = a.id
                WHERE a.department = %s
                  AND a.shift_state = 'barracked'
                  AND a.status = 'active'
                  AND s.skill_name = %s
                  AND s.proficiency_level >= %s
                ORDER BY s.proficiency_level DESC, a.last_used ASC NULLS FIRST
                LIMIT 1
                """,
                (department, capability, min_proficiency),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as exc:
            logger.warning("wake_on_demand: lookup failed — %s", exc)
            return None

        if not row:
            return None

        agent_id, agent_name, display_name, model, proficiency = row

        try:
            from services.agent_service import transition_shift_state

            result = transition_shift_state(agent_id, "active", reason="wake_on_demand")
            if not result or not result.get("success"):
                logger.warning(
                    "wake_on_demand: transition_shift_state failed for %s: %s",
                    agent_name,
                    result.get("error") if result else "no result",
                )
                return None
        except Exception as exc:
            logger.warning("wake_on_demand: state transition crashed — %s", exc)
            return None

        logger.info(
            "wake_on_demand: %s (id=%d, Lv%d in %s) woken for %s",
            agent_name,
            agent_id,
            proficiency,
            department,
            capability,
        )

        # Audit trail — K.I.N. sees every on-demand wake
        try:
            from db import get_db as _get_db
            import json as _json

            _conn = _get_db()
            _cur = _conn.cursor()
            _cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, outcome, details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    "agent_welfare",
                    "orchestration",
                    agent_id,
                    "wake_on_demand",
                    "activated",
                    _json.dumps(
                        {
                            "capability": capability,
                            "department": department,
                            "proficiency_level": proficiency,
                            "trigger": "home_dept_saturated",
                        }
                    ),
                ),
            )
            _conn.commit()
            _cur.close()
            _conn.close()
        except Exception as exc:
            logger.debug("wake_on_demand: governance log failed — %s", exc)

        # Force the agent cache to pick up the new shift_state on next refresh.
        self._cache_time = 0

        return {
            "id": agent_id,
            "name": agent_name,
            "display_name": display_name,
            "model": model,
            "department": department,
            "shift_state": "active",
            "status": "active",
            "woken_on_demand": True,
        }

    def find_cross_department_agent(
        self,
        capability: str,
        blocked_department: str,
    ) -> Optional[Dict]:
        """Find an agent in another department that has the requested skill.

        News & Media (WTF) dedication wall (ADR-010 #741): News is the ONLY
        dedicated team.
          (1) Inbound — a News capability never cross-routes OUT of News &
              Media. If no News agent is available the work stays unassigned
              (the caller escalates within tier) rather than landing on a
              non-news agent.
          (2) Outbound — a News & Media agent is never pulled cross-department
              onto non-news work (News & Media is excluded from the search).
        """
        self._refresh_caches()

        # (1) Inbound dedication wall — news work stays inside News & Media.
        if _is_news_capability(capability) or blocked_department == NEWS_DEPARTMENT:
            return None

        all_departments = set(info.get("department") for info in self._agent_cache.values() if info.get("department"))
        # (2) Outbound dedication wall — never pull a News & Media agent out.
        skip = {blocked_department, "Executive Office", NEWS_DEPARTMENT}

        internal_fallback = None
        for dept in sorted(all_departments - skip):
            for name, info in self._agent_cache.items():
                if info.get("department") != dept:
                    continue
                skills = info.get("skills", {})
                if capability not in skills:
                    continue
                score, block_reason = self.score_agent(name, info, capability, dept)
                if score > 0 and block_reason is None:
                    with self._lock:
                        if info["id"] in self._reserved_agents:
                            continue
                    # Prefer a budgeted AI/contractor holder over a legacy INTERNAL
                    # persona (same rule as select_agent): keep the first qualifying
                    # internal as a fallback, but return a non-internal holder if one
                    # exists so cross-dept inference stays visible to the accounting.
                    if info.get("worker_type") == "internal":
                        if internal_fallback is None:
                            internal_fallback = (info, dept, name)
                        continue
                    logger.info(
                        "coordinator: cross-dept fallback %s→%s (%s) for %s",
                        blocked_department,
                        dept,
                        name,
                        capability,
                    )
                    return info
        if internal_fallback is not None:
            info, dept, name = internal_fallback
            logger.info(
                "coordinator: cross-dept fallback %s→%s (%s, internal — no AI holder) for %s",
                blocked_department,
                dept,
                name,
                capability,
            )
            return info
        return None

    # ------------------------------------------------------------------
    # Reservation lifecycle
    # ------------------------------------------------------------------

    def release_agent(self, agent_id: int, job_id: Optional[int] = None) -> None:
        """Release an agent reservation so it can accept new work."""
        with self._lock:
            self._reserved_agents.pop(agent_id, None)
            if job_id is not None:
                self._job_map.pop(job_id, None)

        logger.debug("department_coordinator: released agent %s", agent_id)

    def get_status(self) -> Dict:
        """Return a snapshot of coordinator state for monitoring endpoints."""
        with self._lock:
            self._sweep_stale_reservations()
            _now = time.monotonic()
            reserved = list(self._reserved_agents)
            reserved_ages = {aid: round(_now - t, 1) for aid, t in self._reserved_agents.items()}

        return {
            "reserved_agents": reserved,
            # #5007: age per reservation so monitoring can SEE a nascent leak
            # before the TTL sweep releases it.
            "reserved_ages_s": reserved_ages,
            "loaded_models": self._model_service.check_loaded_models(),
            "available_ram_gb": self._model_service.get_available_ram(),
            "active_jobs": len(reserved),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_coordinator: Optional[DepartmentCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator() -> DepartmentCoordinator:
    """Return the global DepartmentCoordinator singleton."""
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = DepartmentCoordinator()
    return _coordinator
