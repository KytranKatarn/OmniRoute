"""
DepartmentDispatcher — Central AI Work Dispatch System
Project #91: Team Management Redesign

Single entry point for all AI work requests. Replaces direct LLM calls
throughout the platform with a centralized dispatch model where ARCHIE
assigns team member agents to modules on demand via Bridge Command.

Design:
- Modules call dispatcher.request_work(capability, prompt, ...)
- Dispatcher finds the right agent for the capability
- Agent's model is used to execute the work
- All executions logged to task_execution_log for HR tracking

Author: A.R.C.H.I.E. Platform
Date: 2026-02-17
"""

import json
import logging
import time
import os
from db import _get_db_password
import re as _re
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass

# Bias sampling — 10% inline fairness monitoring (Project #358 T3)
try:
    from services.bias_sampling_service import maybe_sample as _maybe_bias_sample

    _HAS_BIAS_SAMPLING = True
except ImportError:
    _HAS_BIAS_SAMPLING = False

    def _maybe_bias_sample(*_a, **_kw):
        pass


# Phase 2: Agent lifecycle delegated to agent_service
try:
    import sys

    if "/mnt/archie_brain/platform_v2" not in sys.path:
        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
    from services.agent_service import (
        find_replacement as svc_find_replacement,
        increment_budget as svc_increment_budget,
        decrement_budget as svc_decrement_budget,
        update_welfare_after_task as svc_update_welfare_after_task,
        check_shift_transitions as svc_check_shift_transitions,
    )

    _HAS_AGENT_SERVICE = True
except ImportError:
    _HAS_AGENT_SERVICE = False

# Phase 2: Service delegation to Department HQ
try:
    from services.model_service import get_model_service
    from services.department_coordinator import get_coordinator as get_dept_coordinator
    from services.dispatch_service import get_dispatch_service
    from services.fleet_service import (
        list_nodes,
        get_node_status,
        disconnect_node as svc_disconnect_node,
    )

    _HAS_DEPT_HQ_SERVICES = True
except ImportError:
    _HAS_DEPT_HQ_SERVICES = False

from .ollama_options import build_options

try:
    from ai_bridge.schemas.agent_schemas import (
        validate_schema as _validate_handoff_schema,
    )
except ImportError:
    try:
        from schemas.agent_schemas import validate_schema as _validate_handoff_schema
    except ImportError:
        _validate_handoff_schema = None

logger = logging.getLogger(__name__)


def _node_url(node_id: str) -> str:
    """Resolve node_id → base URL for Ollama API calls.

    Hub uses OLLAMA_HOST env (Decision #440: host.docker.internal:11434 or archie_ollama:11434);
    fleet nodes come from remote_nodes via fleet_service.
    """
    if node_id in ("hub", "archie-starbase"):
        return os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL") or "http://archie_ollama:11434"
    try:
        from .fleet_service import get_node_status  # noqa: F811

        node = get_node_status(node_id)
        if node:
            return f"http://{node.get('vpn_ip')}:{node.get('port', 11434)}"
    except Exception:
        logger.warning("fleet_service lookup failed for %s, using OLLAMA_HOST fallback", node_id)
    return os.environ.get("OLLAMA_HOST") or os.environ.get("OLLAMA_URL") or "http://archie_ollama:11434"


# ============================================================================
# CAPABILITY → DEPARTMENT MAPPING
# Maps what kind of work → which department handles it (rebrand Phase 2.2)
# Used by department-aware routing; falls back to station map when needed.
# ============================================================================

CAPABILITY_DEPARTMENT_MAP = {
    # Executive Office
    "conversation": "Executive Office",
    "dispatch": "Executive Office",
    "governance": "Executive Office",
    "orchestration": "Executive Office",
    "general": "Executive Office",
    # Analytics & Intelligence
    "classify": "Analytics & Intelligence",
    "sentiment": "Analytics & Intelligence",
    "tagging": "Analytics & Intelligence",
    "anomaly_detection": "Analytics & Intelligence",
    "pattern_recognition": "Analytics & Intelligence",
    "embedding": "Documentation & Knowledge",  # E.M.B.E.R. #126 owns arctic-embed-cpu (Lv5)
    "translate": "Analytics & Intelligence",
    "detect_language": "Analytics & Intelligence",
    "analysis": "Analytics & Intelligence",
    "json": "Analytics & Intelligence",
    # Engineering & Technology
    "code": "Engineering & Technology",
    "code_analysis": "Engineering & Technology",
    "code_review": "Engineering & Technology",
    "code_fix": "Engineering & Technology",  # Repair Bay dep-fix triage (forge_triage.py)
    "debug": "Engineering & Technology",  # alias of debugging
    "testing": "Engineering & Technology",
    "debugging": "Engineering & Technology",
    "schema_design": "Engineering & Technology",
    "api_design": "Engineering & Technology",
    "deployment": "Engineering & Technology",
    # Operations & Infrastructure
    "deploy_static": "Operations & Infrastructure",  # Hostinger zip deploy (B.A.S.E. Lv5)
    "deploy_vps": "Operations & Infrastructure",  # VPS SSH rsync + docker rebuild (B.A.S.E. Lv5)
    "operations": "Operations & Infrastructure",
    "system_monitoring": "Operations & Infrastructure",
    "backup": "Operations & Infrastructure",
    "health_check": "Operations & Infrastructure",
    "telegram": "Operations & Infrastructure",
    "email": "Operations & Infrastructure",
    "notification": "Operations & Infrastructure",
    "webhook": "Operations & Infrastructure",
    "ha_integration": "Operations & Infrastructure",
    "automation": "Operations & Infrastructure",
    # Security & Compliance
    "security_analysis": "Security & Compliance",
    "vulnerability_scan": "Security & Compliance",
    "threat_analysis": "Security & Compliance",
    "device_audit": "Security & Compliance",
    "dns_report": "Security & Compliance",
    "network_scan": "Security & Compliance",
    "camera_check": "Security & Compliance",
    "filter_review": "Security & Compliance",
    "ssl_check": "Security & Compliance",
    "incident_response": "Security & Compliance",
    "policy_review": "Security & Compliance",
    "ssh_audit": "Security & Compliance",
    # Creative & Design
    "content_writing": "Creative & Design",
    "email_composition": "Creative & Design",
    "chat_styling": "Creative & Design",
    "voice": "Creative & Design",
    "ux_writing": "Creative & Design",
    "social_media": "Creative & Design",
    "image_generation": "Creative & Design",
    "video_generation": "Creative & Design",
    "audio_generation": "Creative & Design",
    "audio_tts": "Creative & Design",
    "audio_music": "Creative & Design",
    "media_editing": "Creative & Design",
    # Vision / multimodal analysis: routed here so Pixel (who owns the
    # image model) is picked. Was previously misrouted to Analytics.
    "vision": "Creative & Design",
    "multimodal": "Creative & Design",
    "ux_scoring": "Creative & Design",
    "visual_design": "Creative & Design",
    # Research & Development
    "knowledge_analysis": "Research & Development",
    "summarize": "Research & Development",
    "document_analysis": "Research & Development",
    "fact_checking": "Research & Development",
    "semantic_search": "Research & Development",
    "context_retrieval": "Research & Development",
    # --- Capability Routing Expansion (2026-04-28) ---
    # Engineering & Technology
    "ci_cd_pipeline": "Engineering & Technology",
    "container_orchestration": "Engineering & Technology",
    "deployment_automation": "Engineering & Technology",
    "infrastructure_as_code": "Engineering & Technology",
    "infrastructure_architecture": "Engineering & Technology",
    "api_architecture": "Engineering & Technology",
    "api_integration": "Engineering & Technology",
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
    "audit_management": "Security & Compliance",  # platform/infrastructure audit
    # Analytics & Intelligence
    "data_analysis": "Analytics & Intelligence",
    "data_visualization": "Analytics & Intelligence",
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
    # Creative & Design
    "creative_writing": "Creative & Design",
    "creative_direction": "Creative & Design",
    "brand_strategy": "Creative & Design",
    "content_architecture": "Creative & Design",
    "accessible_ui_design": "Creative & Design",
    "dashboard_design": "Creative & Design",
    # Documentation & Knowledge
    "documentation": "Documentation & Knowledge",  # sandbox_queue + general doc work
    "knowledge_base_curation": "Documentation & Knowledge",
    "information_design": "Documentation & Knowledge",
    "briefing_preparation": "Documentation & Knowledge",
    "api_documentation": "Documentation & Knowledge",
    # Research & Development
    "research": "Research & Development",  # improvement_engine + general research
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
    "facilities_management": "Operations & Infrastructure",
    "grounds_maintenance": "Operations & Infrastructure",
    "capacity_modeling": "Operations & Infrastructure",
    "infrastructure_planning": "Operations & Infrastructure",
    "bim_modeling": "Operations & Infrastructure",
    "arctic_infrastructure": "Operations & Infrastructure",
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
    # Analytics & Intelligence — Market Watch capabilities (M.A.R.K.E.T. mistral:7b)
    "market_analysis": "Analytics & Intelligence",
    "market_intelligence": "Analytics & Intelligence",
    "stock_analysis": "Analytics & Intelligence",
    "portfolio_analysis": "Analytics & Intelligence",
    "sector_analysis": "Analytics & Intelligence",
    "technical_analysis": "Analytics & Intelligence",
    "earnings_analysis": "Analytics & Intelligence",
    "trading_strategy": "Analytics & Intelligence",
    "economic_outlook": "Analytics & Intelligence",
    # Analytics & Intelligence — Civic Watch capabilities (W.A.T.C.H. Lv5 research+classify)
    "civic_analysis": "Analytics & Intelligence",
    "government_transparency": "Analytics & Intelligence",
    "spending_analysis": "Analytics & Intelligence",
    "mp_research": "Analytics & Intelligence",
    "policy_research": "Analytics & Intelligence",
    "contract_analysis": "Analytics & Intelligence",
    "transparency_review": "Analytics & Intelligence",
    # Legal & Regulatory (G.A.V.E.L. Lv5 legal + compliance)
    "legal": "Legal & Regulatory",
    "legal_analysis": "Legal & Regulatory",
    "legal_research": "Legal & Regulatory",
    "legal_summary": "Legal & Regulatory",
    "compliance": "Legal & Regulatory",
    "contract_review": "Legal & Regulatory",
    "regulatory_review": "Legal & Regulatory",
    "privacy_review": "Legal & Regulatory",
    "risk_assessment": "Legal & Regulatory",
    # News & Media — WTF pipeline (B.I.A.S., V.E.R.I.F.Y., L.O.C.A.L., F.A.C.T., S.C.O.U.T.)
    # Without these entries the capabilities fall through to Engineering & Technology default,
    # causing P.R.O.B.E. (qwen2.5-coder:7b) to be selected for bias/geo tasks instead.
    "bias_analysis": "News & Media",
    "bias_quick": "News & Media",
    "bias_backlog": "News & Media",
    "geo_extraction": "News & Media",
    "geo_backlog": "News & Media",
    "fact_check": "News & Media",
    "factcheck_quick": "News & Media",
    "fact_check_quick": "News & Media",
    "classify_beat": "News & Media",
    "news_analysis": "News & Media",
    "media_analysis": "News & Media",
    "news_summary": "News & Media",
    "news_clustering": "News & Media",
}

# ============================================================================
# DEPARTMENT → FLOOR MAPPING
# Maps each department to its building floor (rebrand Phase 2.2)
# ============================================================================

# SINGLE SOURCE (2026-08-02). This was a hardcoded COPY of the map in
# ``services.agent_service`` and it had silently drifted: "News & Media" was added there
# when the department was created (2026-04-14) and never here, so this copy held 16
# entries against agent_service's 17.
#
# That one missing key silently misfiled approved hires. ``_create_agent_from_approval``
# treats "not in DEPARTMENT_FLOOR_MAP" as "this must be a legacy STATION CODE" and runs it
# through a _LEGACY lookup that defaults to "Engineering & Technology". So a hire correctly
# filed for News & Media was created in Engineering — landing outside the home-department
# pool for its own capability, where dispatch would never select it. Measured on S.I.F.T.
# (agent 432, hired for beat_classification 2026-08-02): filed News & Media, created
# Engineering & Technology, and select_agent() returned P.U.B.L.I.S.H. instead.
#
# agent_service owns the agents table (Project #241 Track C single-writer), so it owns this
# mapping too. Importing rather than re-declaring makes the drift structurally impossible.
# Safe at module scope: agent_service imports only stdlib + `database`, so there is no cycle.
from services.agent_service import DEPARTMENT_FLOOR_MAP  # noqa: E402

FLOOR_DEPARTMENTS = {}
for _dept, _flr in DEPARTMENT_FLOOR_MAP.items():
    FLOOR_DEPARTMENTS.setdefault(_flr, []).append(_dept)

# Capabilities that require explicit agent skill (no generous 0.3 default).
# If no agent at the mapped department has the skill, cross-department dispatch
# finds an agent elsewhere who does.
CAPABILITY_REQUIRES_SKILL = {
    "translate",  # Needs a capable chat LLM — not a classifier or embedder
    "knowledge_analysis",  # Deep JSON analysis — needs qwen3-coder-cpu or better
    "image_generation",  # ComfyUI skill — only Pixel has this
}

# Per-capability request timeout overrides (task #2130, 2026-04-18).
# GPU-node affinity by capability (#3955, owner directive 2026-06-10).
# Heavy 7B+ work (code review, research, doc-gen, translation, policy) is GPU-
# bound; on the hub's 8GB Quadro a 7B cold-load can time out, and on CPU
# outposts it crawls. Default such work to the GPU Starship cluster so EVERY
# agent's heavy tasks prefer GPU — without each caller passing preferred_node.
#
# Applied ONLY when the caller passes preferred_node=None. It is a *preference*,
# not a pin: the dispatcher's preferred_node loop skips offline/unfit nodes and
# execution then continues to the agent's stationed node, then hub, then
# (if allowed) cloud — so when the Starships are offline this is a no-op and
# stationed CPU agents (E.T.H.O.S./C.O.D.E.X.) reach their nodes exactly as
# before. Explicit preferred_node from a caller always wins.
# Pinned by NODE_ID (not display name): the GPU Starships were renamed 2026-06-04 to
# "Starship - Defiant - USS-246" / "Starship - Runabout - USS-245", but node_id is
# rename-proof. The preferred_node loop matches `node_name = %s OR node_id = %s`, so the
# OLD short names ("Starship-246"…) matched NEITHER column → every GPU candidate was
# "not viable" → all heavy work (code/research/…) silently fell through to the hub CPU.
# That made the engine build plan (qwen2.5-coder:7b) run on hub CPU (~567s/plan) and blow
# the engine's plan timeout. Pinning by node_id restores GPU routing when a Starship is up
# (fail-safe fallback to hub unchanged when both are offline). #4342.
_GPU_CLUSTER = ["starship_76583490e36955ab", "starship_5501c2766526e746"]  # USS-246 (Defiant), USS-245 (Runabout)
# Win 2 (2026-06-23): Citadel (boston-2, 31GB RAM, CPU-only) as an ASYNC worker. `documentation`
# (mistral:7b, C.O.D.E.X.) prefers Citadel so delegated doc-gen runs on its idle CPU (~25GB free) AND
# stays OFF the Defiant GPU so it can't evict the warm review 7B (#1905). Conservative: docs are
# low-volume (~55/day) + async-latency-tolerant; the GPU cluster stays the fallback. preferred_node
# bypasses bridge_enabled, so Citadel routes despite bridge_enabled=0; if it is offline the loop falls
# through to the Starships then hub exactly as before. Citadel is the DR + watch-products node — keep
# this to async/low-volume only; never let it starve the watch products.
_CITADEL = "outpost_e834ff6949a3d7a6"  # Citadel / boston-2 — has mistral:7b installed
# Win 3 (2026-06-23): vision work -> Runabout USS-245 (RTX 3050 4GB). moondream (~1.8GB) fits its GPU;
# the 4GB card can't run a 7B but is ideal for the small vision models it has (moondream + minicpm-v).
# The hub (M4000, also has moondream) is the fallback when .245 rests (8PM-6AM); NOT the Defiant — its
# 8GB is reserved for the warm review 7B (#1905). _RUNABOUT is already in _GPU_CLUSTER (drift-guarded).
# Vision is low-volume + cold-load-tolerant (describe_portrait accepts a 60-90s load), so no keep-warm.
_RUNABOUT = "starship_5501c2766526e746"  # USS-245 Runabout — has moondream + minicpm-v
# WTF CPU-first tier (#3955 owner decision, 2026-07-05): the platform's highest-volume
# heavy-7B work (WTF fact-check/bias, ~40k/7d, all qwen2.5:7b) prefers CPU — Citadel
# (boston-2, co-locates the WTF stack, cap=5, has qwen2.5:7b) then hub — with the GPU
# cluster as OVERFLOW only. dispatch:node_cap:enabled is ON, so the preferred_node loop
# spills to the next candidate when a node is at cap: load spreads Citadel->hub->GPU and
# the Defiant is reached only when both CPU nodes saturate, keeping its 8GB free for
# interactive F.O.R.G.E. reviews (#1905). Citadel-first (not hub) both co-locates with the
# WTF data and stays safe even if the cap kill-switch is ever flipped off (Citadel is the
# expendable async node; the hub is the platform core). See the fact_check/bias entries.
_WTF_CPU_FIRST = [_CITADEL, "archie-starbase"] + _GPU_CLUSTER
CAPABILITY_NODE_AFFINITY = {
    "code_review": _GPU_CLUSTER,
    "code": _GPU_CLUSTER,
    "code_analysis": _GPU_CLUSTER,
    "debug": _GPU_CLUSTER,
    "research": _GPU_CLUSTER,
    "research_synthesis": _GPU_CLUSTER,
    "knowledge_analysis": _GPU_CLUSTER,
    "analyze": _GPU_CLUSTER,
    "documentation": [_CITADEL] + _GPU_CLUSTER,  # Win 2: async docs -> Citadel CPU, GPU fallback
    "summarize": _GPU_CLUSTER,
    "summarization": _GPU_CLUSTER,
    # #1905 follow-up (2026-06-24): keep translate OFF the Defiant 8GB GPU. translate ran
    # gemma3:12b (Amina, ~370/6h, 6.3GB VRAM) + mistral:7b (R.O.S.E.T.T.A., ~128/6h) ON the
    # Defiant, evicting the warm review qwen2.5:7b ~1x/min (gemma3 6.3GB + 7B ~5GB cannot
    # coexist on 8GB) → F.O.R.G.E. reviews cold-loaded (240s per-node timeouts → freeform
    # fallback). Route to the hub: gemma3:12b is CPU-pinned there (_HUB_CPU_TIER, 128GB RAM)
    # and mistral:7b stays warm; translate is latency-tolerant. The Runabout (4GB) couldn't
    # run translate models anyway. Reversible: restore _GPU_CLUSTER. Watch hub CPU load.
    "translate": ["archie-starbase"],
    "policy_assessment": _GPU_CLUSTER,
    "vision": [_RUNABOUT, "archie-starbase"],  # Win 3: vision -> .245 small GPU (moondream), hub fallback
    "multimodal": [_RUNABOUT, "archie-starbase"],
    # Security & Compliance (#3955 completion, 2026-07-05). S.H.I.E.L.D.'s `security`
    # work runs qwen2.5:7b — GPU-safe (shares the warm review 7B) -> GPU cluster.
    # V.I.G.I.L.'s `compliance` runs gemma3:12b — an 8GB-GPU evictor (like translate),
    # so it must stay on hub CPU (gemma3:12b is CPU-pinned there) and never reach the
    # Defiant, or it would evict the warm review model.
    "security": _GPU_CLUSTER,
    "compliance": ["archie-starbase"],
    # WTF fact-check/bias (#3955, owner decision 2026-07-05): the platform's highest-
    # volume heavy-7B work (~40k/7d, all qwen2.5:7b). CPU-first, GPU overflow — see the
    # _WTF_CPU_FIRST comment above.
    "fact_check": _WTF_CPU_FIRST,
    "fact_check_backlog": _WTF_CPU_FIRST,
    "factcheck_quick": _WTF_CPU_FIRST,
    "bias_analysis": _WTF_CPU_FIRST,
    "bias_quick": _WTF_CPU_FIRST,
    "bias_backlog": _WTF_CPU_FIRST,
}


def assert_gpu_cluster_invariants(cur=None):
    """Drift guard (#4343): verify every node_id hardcoded in _GPU_CLUSTER still maps to a
    real remote_nodes row with a sane concurrency cap.

    A stale id (node renamed/removed) makes EVERY ``preferred_node=_GPU_CLUSTER`` /
    CAPABILITY_NODE_AFFINITY pin silently no-op -> hub-CPU fallback — the exact stale-name
    routing bug class this codebase keeps hitting (KB #274200, cont-49; the same family the
    hub-unify PR #1813 fixed in 4 other places). Flags: (1) a _GPU_CLUSTER node_id absent
    from remote_nodes, (2) max_concurrent missing/<1 (degenerate cap math). Does NOT flag a
    merely-offline node — Starships legitimately rest 8PM-6AM ET. Returns a list of problem
    strings (empty = healthy) and logs one warning per drift. Read-only + fail-open ([] on
    error) so it can never block dispatch. Pass an existing dict cursor or let it open one."""
    problems = []

    def _check(c):
        c.execute(
            "SELECT node_id, node_name, max_concurrent FROM remote_nodes WHERE node_id = ANY(%s)",
            (list(_GPU_CLUSTER),),
        )
        found = {r["node_id"]: r for r in (c.fetchall() or [])}
        for nid in _GPU_CLUSTER:
            row = found.get(nid)
            if row is None:
                problems.append(
                    f"_GPU_CLUSTER node_id '{nid}' not in remote_nodes — stale pin, every "
                    f"affinity/preferred_node route for it silently falls back to hub"
                )
            elif not row["max_concurrent"] or int(row["max_concurrent"]) < 1:
                problems.append(
                    f"_GPU_CLUSTER node '{nid}' ({row['node_name']}) has max_concurrent="
                    f"{row['max_concurrent']} (<1 — degenerate cap math)"
                )

    try:
        if cur is not None:
            _check(cur)
        else:
            from database import get_db_cursor

            with get_db_cursor() as (_c, _cu):
                _check(_cu)
    except Exception:
        logger.warning("[BridgeDispatcher] assert_gpu_cluster_invariants check failed (fail-open)", exc_info=True)
        return []
    for p in problems:
        logger.warning("[BridgeDispatcher] GPU cluster drift: %s", p)
    return problems


# S.P.E.C.T.R.A. audit: F.O.R.G.E. hit HTTPConnectionPool timeouts on the
# default 300s for every code_analysis call — the model completes but runs
# long on CPU nodes. Applies when request_work is called with the default
# timeout (300); explicit caller timeouts are preserved.
CAPABILITY_TIMEOUTS = {
    "code_analysis": 600,
    "knowledge_analysis": 600,
    # research / compliance / code / analyze = heavy open-ended 7B work.
    # On CPU outpost nodes these routinely exceed the 300s default and get
    # killed mid-job, false-blocking delegated backlog tasks (tasks
    # #3624-#3630, 2026-06-01). Treat like code_analysis/knowledge_analysis.
    "research": 600,
    "compliance": 600,
    "code": 600,
    "analyze": 600,
    # documentation = heavy 7B doc-gen (mistral:7b). On CPU outpost nodes
    # (e.g. C.O.D.E.X.@outpost-asia) it routinely runs 250-530s. It was
    # inheriting the 300s default and getting killed mid-job, marking
    # delegated doc tasks 'blocked' even though the node often finished
    # later (tasks #3549/#3551, 2026-05-31). Treat like code/knowledge.
    "documentation": 600,
    # translate = heavy 7B FR/multilingual generation (R.O.S.E.T.T.A. on
    # mistral/qwen 7B). Cold-load + long-form translation routinely runs
    # 400-530s; it was inheriting the 300s default and getting killed, while
    # the delegate worker gave up at 360s even though the node finished at
    # ~497s — destroying completed FR translations (#3967, 2026-06-10).
    "translate": 600,
    # code_review runs in a background thread (so it never holds a Gunicorn worker —
    # the thread-pool concern behind "conversation": 90 below does not apply here).
    # mistral:7b cold-loads in 90-150s under concurrent Repair Bay bursts.
    # ⚠️ This was 300 "to give the model time to warm" — but 300 NEVER APPLIED on the
    # fleet leg, which hardcoded 240 and discarded this value entirely (#5810). So the
    # 300 was never actually in force where reviews run; it was only ever the hub
    # figure. Measured 2026-08-18 on PR #2697 (1,015-line diff): 11 of 16 dispatches
    # died at exactly the cap, the structured JSON path never completed, and the review
    # fell back to freeform — where the #5009 ungrounded-evidence floor turned a clean
    # PR into NEEDS REVIEW. A warm re-run returned APPROVE with no code change.
    # Raised to 600 to match code_analysis, its true sibling: same full-diff 7B profile.
    "code_review": 600,
    # fact_check was the ONE heavy 7B capability still inheriting the 300s default
    # while every sibling above had been raised — so WTF's fact-check stream died on
    # the wall instead of on the work (#5925). Measured 2026-08-22, qwen2.5:7b, 24h,
    # successful runs only (n=1,756): p50 33.2s, p90 249.8s, p95 319.0s, max 915.5s.
    # The median call matches the 100%-success archie_platform caller (26.7s), so the
    # work is not pathological — it is a latency TAIL crossing an arbitrary deadline
    # (the #5903 shape). 293 rows/24h died at exactly 300.2s on the hub alone.
    # ⚠️ 600 does not recover everything: 15 successes exceeded 600s wall-clock, and
    # duration_ms is whole-dispatch (queue + cold-load included), NOT the HTTP window.
    # ⚠️ This deadline INTERACTS with the dispatch:hub_inflight_max admission cap — a
    # longer deadline raises the occupancy that cap exists to bound. This is the ONLY
    # lever moved here; if shed volume climbs, retune the cap separately, not both.
    "fact_check": 600,
    # CPU inference (gemma2-cpu, etc.) blocks Gunicorn threads for 300s+ causing
    # platform-wide hangs. Cap at 90s — GPU agents (qwen2.5:7b) respond in <30s;
    # CPU-only agents will fail fast rather than exhausting the thread pool.
    "conversation": 90,
    "summarize": 90,
    "summarization": 90,
}

# Scoring weights for multi-factor agent selection
SELECTION_WEIGHTS = {
    "skills": 0.30,
    "specialization": 0.25,
    "welfare": 0.15,
    "availability": 0.15,
    "budget": 0.05,
    "tier_match": 0.10,  # Bonus if agent's model matches SmartRouter recommendation
}

# Shift lifecycle states
SHIFT_STATES = ("active", "winding_down", "cooldown", "off_duty")

# Thresholds for automatic state transitions
WINDING_DOWN_BUDGET_PCT = 0.80  # 80% budget used -> winding down
WINDING_DOWN_STRESS = 0.70  # stress >= 0.7 -> winding down
COOLDOWN_BUDGET_PCT = 0.95  # 95% budget -> cooldown
COOLDOWN_STRESS = 0.85  # stress >= 0.85 -> cooldown
WINDING_DOWN_SCORE_PENALTY = 0.30  # 30% score penalty when winding down

# Demand-aware fleet keep_alive (#3532 v1). Tracks recent dispatch times per
# (node_id, model) so GPU fleet nodes (Starships, constrained VRAM) keep a 7B
# warm during a burst of agents but free the GPU quickly when demand is a
# one-off. In-memory + per-process (fleet dispatches come from the scheduler
# loops); v2 moves this signal into K.I.N. for cross-process orchestration.
_NODE_MODEL_DISPATCH_TS: Dict[tuple, List[float]] = {}
_DISPATCH_BURST_WINDOW_SEC = 600  # 10 min lookback
_DISPATCH_BURST_THRESHOLD = 2  # >=2 dispatches in the window => sustained demand

# Fleet node circuit-breaker. A node can heartbeat + answer /api/tags yet complete
# zero generations (e.g. the outpost-US inference stack down while it keeps hosting
# Watch/WTF). Without this, every dispatch to it times out (the 91/hr boston fails).
# In-memory + per-process (mirrors _NODE_MODEL_DISPATCH_TS): a node that fails
# repeatedly with NO recent success is "open" and skipped in candidate selection so
# work routes to healthy siblings; a periodic probe is let through to detect recovery,
# and one success closes the breaker. Fail-open everywhere — never blocks real work.
_NODE_FAIL_TS: Dict[int, List[float]] = {}
_NODE_OK_TS: Dict[int, List[float]] = {}
_NODE_CB_LAST_PROBE: Dict[int, float] = {}
_NODE_CB_WINDOW_SEC = 300  # 5 min lookback
_NODE_CB_FAIL_THRESHOLD = 3  # >=3 fails + 0 ok in window => circuit open
_NODE_CB_PROBE_INTERVAL_SEC = 120  # while open, let one probe through every 2 min


def _node_record_result(node_id, ok: bool) -> None:
    """Record a fleet dispatch outcome for the circuit-breaker. A success clears the
    node's recent-failure history (closes the breaker)."""
    if node_id is None:
        return
    try:
        now = time.time()
        store = _NODE_OK_TS if ok else _NODE_FAIL_TS
        hist = [t for t in store.get(node_id, []) if now - t < _NODE_CB_WINDOW_SEC]
        hist.append(now)
        store[node_id] = hist
        if ok:
            _NODE_FAIL_TS[node_id] = []
    except Exception:
        pass


def _node_circuit_open(node_id) -> bool:
    """True if this node should be skipped (>=N recent failures, no recent success),
    except for a throttled probe to detect recovery. Fail-open on any error."""
    try:
        if node_id is None:
            return False
        now = time.time()
        fails = [t for t in _NODE_FAIL_TS.get(node_id, []) if now - t < _NODE_CB_WINDOW_SEC]
        oks = [t for t in _NODE_OK_TS.get(node_id, []) if now - t < _NODE_CB_WINDOW_SEC]
        if len(fails) >= _NODE_CB_FAIL_THRESHOLD and not oks:
            last_probe = _NODE_CB_LAST_PROBE.get(node_id, 0)
            if now - last_probe >= _NODE_CB_PROBE_INTERVAL_SEC:
                _NODE_CB_LAST_PROBE[node_id] = now
                return False  # probe: let one through to detect recovery
            return True
        return False
    except Exception:
        return False


# Module-level cache so we only hit Ollama /api/tags once per process.
_INSTALLED_MODELS_CACHE = {"names": None, "fetched_at": 0}


def _resolve_installed_vision_model(preferred: str, fallback_chain: list) -> str:
    """Pick a vision model that's actually installed in Ollama.

    Checks the ``preferred`` first; if not installed, walks ``fallback_chain``;
    if none match, returns the first installed model whose name contains a
    known vision marker; if still nothing, returns ``preferred`` as a last
    resort so the caller gets a predictable error downstream.
    """
    import time as _time

    cache_ttl = 60
    now = _time.time()
    if _INSTALLED_MODELS_CACHE["names"] is None or (now - _INSTALLED_MODELS_CACHE["fetched_at"]) > cache_ttl:
        try:
            import requests as _req

            ollama_host = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
            if not ollama_host.startswith("http"):
                ollama_host = f"http://{ollama_host}"
            resp = _req.get(f"{ollama_host}/api/tags", timeout=5)
            if resp.status_code == 200:
                _INSTALLED_MODELS_CACHE["names"] = {m["name"] for m in (resp.json().get("models") or [])}
                _INSTALLED_MODELS_CACHE["fetched_at"] = now
        except Exception:
            _INSTALLED_MODELS_CACHE["names"] = _INSTALLED_MODELS_CACHE["names"] or set()

    installed = _INSTALLED_MODELS_CACHE["names"] or set()

    if preferred in installed:
        return preferred
    for candidate in fallback_chain or []:
        if candidate in installed:
            return candidate
    # Last resort: any installed model that looks vision-capable
    markers = ("vl", "vision", "llava", "minicpm")
    for name in sorted(installed):
        if any(m in name.lower() for m in markers):
            return name
    return preferred


@dataclass
class DispatchResult:
    """Result from a dispatched work request."""

    success: bool
    response: str
    agent_name: str
    agent_id: Optional[int] = None
    model_used: str = ""
    station_code: str = "Engineering & Technology"  # now holds department name (legacy name kept for compat)
    capability: str = ""
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider: str = "ollama"
    error: Optional[str] = None
    metadata: Optional[Dict] = None
    department: str = ""
    queued: bool = False  # True when task was deferred to dispatch_pending_queue
    queue_id: Optional[int] = None  # dispatch_pending_queue.id when queued (for async callbacks)
    # C.R.E.E.D. accounting-integrity Fix #3 (KB #279350-family): cloud/contractor
    # escalations happen when NO single internal agent was matched (department
    # capacity exhausted before any candidate was selected — see
    # resolve_department_escalation_owner()), so agent_id/agent_name are
    # generic ("CONTRACTOR→x"/"CLOUD→x", agent_id=None) and every OTHER use of
    # those two fields in _log_execution (welfare update, agent memory,
    # performance metrics, Claude notify) must stay byte-for-byte unchanged.
    # These two carry the department-director proxy attribution used ONLY when
    # building the task_execution_log INSERT, so that director's per-agent
    # K.I.N./budget view stops silently missing cloud spend incurred
    # escalating on behalf of their department.
    escalating_agent_id: Optional[int] = None
    escalating_agent_name: Optional[str] = None

    def __post_init__(self):
        # Normalize: if department was passed, use it; else derive from station_code
        if self.department and not self.station_code:
            self.station_code = self.department
        elif self.station_code and not self.department:
            self.department = self.station_code
        elif not self.department and not self.station_code:
            self.department = "Engineering & Technology"
            self.station_code = "Engineering & Technology"

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "response": self.response,
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "model_used": self.model_used,
            "department": self.department,
            "station_code": DEPARTMENT_FLOOR_MAP.get(self.department, self.station_code),
            "capability": self.capability,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "provider": self.provider,
            "error": self.error,
        }


def resolve_department_escalation_owner(
    agent_cache: Dict[str, Dict], department: Optional[str]
) -> Tuple[Optional[int], Optional[str]]:
    """Best-effort owner to attribute an orphaned cloud/contractor escalation to.

    Cloud/contractor dispatch (see dispatch()'s "not agent and
    department_exhausted" branch) only fires once department capacity is
    exhausted AND no single internal agent could be matched at all — there is
    no specific agent that "escalated". The department's AI director
    (``is_department_ai``) is the closest real owner: they represent the
    department's demand, so their per-agent K.I.N./budget view should reflect
    cloud spend incurred escalating on behalf of their department instead of
    it vanishing into an ``agent_id IS NULL`` bucket (C.R.E.E.D.
    accounting-integrity Fix #3).

    Pure function — no DB, no ``self`` — so it is directly unit-testable.
    Fail-open: returns ``(None, None)`` when there is no cached director for
    the department (never raises, never blocks a dispatch).
    """
    if not department or not agent_cache:
        return None, None
    for name, info in agent_cache.items():
        if not isinstance(info, dict):
            continue
        if info.get("department") == department and info.get("is_department_ai"):
            return info.get("id"), name
    return None, None


def create_job_via_service(job_type, module_source, description, total_steps, capability=None, metadata=None):
    """Convenience function for new callers — routes through Department HQ services."""
    if not _HAS_DEPT_HQ_SERVICES:
        raise RuntimeError("Department HQ services not available (import failed)")
    svc = get_dispatch_service()
    coord = get_dept_coordinator()

    cap_key = capability or job_type.split("_")[0]
    dept = coord.resolve_department(cap_key)
    agent_info = coord.select_agent(cap_key, dept)

    agent_name = None
    if agent_info:
        agent_name = agent_info.get("name")
        model_svc = get_model_service()
        model_svc.ensure_model_ready(agent_name, agent_info.get("model", ""))

    return svc.create_job(
        job_type=job_type,
        module_source=module_source,
        description=description,
        total_steps=total_steps,
        capability=capability,
        metadata=metadata,
        agent_name=agent_name,
        station_code=dept,
    )


# --- Project auto-detect cache ---
_project_keyword_cache: Dict[str, int] = {}
_project_cache_time: float = 0
_PROJECT_CACHE_TTL = 300  # 5 minutes


def _load_project_keywords() -> Dict[str, int]:
    """Load project keywords from DB for auto-detection.

    Returns {keyword: project_id} dict. Keywords are slug words (4+ chars)
    and tags (4+ chars) from active/planning projects.
    """
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, slug, tags FROM unified_projects WHERE status IN ('active', 'planning')")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        keywords = {}
        for row in rows:
            pid, slug, tags = row[0], row[1], row[2]
            for word in (slug or "").split("-"):
                if len(word) >= 4:
                    keywords[word.lower()] = pid
            if isinstance(tags, list):
                for tag in tags:
                    if len(tag) >= 4:
                        keywords[tag.lower()] = pid
        return keywords
    except Exception as e:
        logger.warning("[Dispatcher] Failed to load project keywords: %s", e)
        return {}


def _detect_project_id(text: str) -> Optional[int]:
    """Infer project_id from prompt/capability text via cached keyword matching.

    Returns project_id if 2+ keywords match, None otherwise.
    Cache refreshes every 5 minutes.
    """
    global _project_keyword_cache, _project_cache_time

    now = time.time()
    if now - _project_cache_time > _PROJECT_CACHE_TTL or not _project_keyword_cache:
        _project_keyword_cache = _load_project_keywords()
        _project_cache_time = now

    if not _project_keyword_cache or not text:
        return None

    text_lower = text[:500].lower()
    scores: Dict[int, int] = {}
    for keyword, pid in _project_keyword_cache.items():
        if keyword in text_lower:
            scores[pid] = scores.get(pid, 0) + 1

    if not scores:
        return None

    best_score = max(scores.values())
    if best_score < 2:
        return None

    best_pids = [pid for pid, score in scores.items() if score == best_score]
    return min(best_pids)


def _fleet_routing_enabled() -> bool:
    """Check system_config toggle — defaults to True (enabled) on any error."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_, cur):
            cur.execute("SELECT value FROM system_config WHERE key='fleet_node_routing_enabled'")
            row = cur.fetchone()
            return (row["value"] if row else "true").lower() != "false"
    except Exception:
        return True


_SMALL_MODEL_MARKERS = (
    "1.5b",
    "1b",
    "0.5b",
    "3b",
    ":2b",
    "classify",
    "mini",
    "embed",
    "nomic",
    "moondream",
    "tiny",
)


def _model_is_gpu_class(model: Optional[str]) -> bool:
    """True for mid/large models (7B+) that thrash the hub CPU under load — i.e. NOT the
    small warm-set models (1.5b/3b/embeds) that run fine on hub CPU. Scopes GPU-overflow
    (RCA KB #278774) to the models that actually cause the hub-saturation cascade."""
    m = (model or "").lower()
    if not m:
        return False
    return not any(mk in m for mk in _SMALL_MODEL_MARKERS)


def _pick_fleet_node(model: str, agent: Optional[dict]) -> Optional[int]:
    """Return the best fleet node DB id for a task, or None for hub.

    Called just before INSERT into dispatch_pending_queue. Scores all online
    fleet nodes to find the best hardware match for the model — enabling
    bi-directional cluster dispatch. GPU-preferred 7B models escalate to
    Starship RTX nodes; CPU-preferred small models stay on hub/VPS. Colocation
    preference: home node wins if it scores within 80% of best. Fails open.

    Returns None immediately when the fleet_node_routing_enabled toggle is off.
    """
    if not _fleet_routing_enabled():
        return None
    # Contractors (e.g. Codex, model='codex-cli') are external CLI tools, NOT Ollama
    # agents — never score-route them to a fleet Ollama node, which would 404 on a
    # model it can't possibly have (#4272). Covers worker_type 'contract'/'contractor'.
    if str((agent or {}).get("worker_type") or "").startswith("contract"):
        return None
    home = agent.get("node_db_id") if agent else None
    try:
        from services.fleet_resource_router import find_best_node_for_model

        # AGENT MOBILITY PROFILE: nudge a profile-prioritised agent's model
        # toward its preferred tier (platform→GPU, news→CPU/outpost), matching
        # routing block 1a. Fail-safe → no bias.
        profile_pref = None
        try:
            from services.fleet_dispatch_profile import (
                get_dispatch_mode,
                is_priority_department,
            )

            _mode = get_dispatch_mode()
            if is_priority_department((agent or {}).get("department"), _mode):
                profile_pref = "gpu" if _mode == "platform" else "cpu" if _mode == "news" else None
        except Exception:
            profile_pref = None

        # GPU-OVERFLOW (RCA KB #278774): when the hub is saturated on the contended 7B
        # lanes, override the profile pref to 'gpu' so this 7B escalates to an online GPU
        # node (Starship RTX) instead of piling another 240s CPU timeout on the hub.
        # Reuses find_best_node_for_model, which already respects node health + load
        # scoring + the 8PM-6AM rest window — so it no-ops back to the hub when no GPU node
        # is available (rest / offline). Fail-open; shares the admission-control kill switch
        # (dispatch:hub_inflight_max<=0 → hub_lane_over_cap False → no overflow).
        try:
            if _model_is_gpu_class(model):
                from services.welfare_governance_service import hub_lane_over_cap

                if hub_lane_over_cap():
                    profile_pref = "gpu"
        except Exception:
            pass

        return find_best_node_for_model(model, home, profile_pref=profile_pref)
    except Exception:
        return home


class DepartmentDispatcher:
    """
    Central dispatch system for all AI work on the ARCHIE Platform.

    Modules request work by capability. The dispatcher:
    1. Maps capability → department → agent
    2. Uses the agent's assigned model to execute
    3. Logs everything to task_execution_log for HR tracking
    4. Handles fallback/escalation gracefully
    """

    def __init__(self):
        self._agent_cache = {}  # name → {id, model, department, ...}
        self._cache_time = 0
        self._cache_ttl = 300  # Refresh cache every 5 minutes
        self._db_getter = None
        # Failure tracking for escalation
        self._failure_tracker = {}  # (agent_id, capability) -> count
        # Welfare cache — shorter TTL for near-real-time welfare awareness
        self._welfare_cache = {}  # agent_id → {stress, energy, mood, resting, budget}
        self._welfare_cache_time = 0
        self._welfare_cache_ttl = 30  # Refresh every 30 seconds
        self._busy_agents = set()  # agent names with running bridge_jobs
        # Module → department cache
        self._module_department_cache = {}
        self._module_department_ts = 0
        # Dynamic specialization cache from benchmarks (10-minute TTL)
        self._dynamic_spec_cache = {}  # (department, capability) → agent_name
        self._dynamic_spec_ts = 0
        self._dynamic_spec_ttl = 600
        # Fleet health tracking — node_db_id → {"online": bool, "last_check": timestamp}
        self._fleet_health_cache = {}
        # Serialise GPU model loads — one at a time to prevent CUDA compute-buffer
        # fragmentation when multiple jobs race to load models simultaneously.
        import threading as _threading

        self._model_loading_lock = _threading.Lock()

    def _get_db(self):
        """Get database connection."""
        if self._db_getter:
            return self._db_getter()
        try:
            from config import get_db

            self._db_getter = get_db
            return get_db()
        except ImportError:
            import psycopg2

            return psycopg2.connect(
                host=os.getenv("DB_HOST", "192.168.1.200"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )

    def _refresh_agent_cache(self):
        """Load active agents and their departments from DB."""
        now = time.time()
        if self._agent_cache and (now - self._cache_time) < self._cache_ttl:
            return

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT a.id, a.name, a.display_name, a.model,
                       a.default_model_tier, a.system_prompt, a.capabilities,
                       a.temperature, a.max_tokens, a.status, a.shift_state,
                       a.first_name, a.last_name, a.title,
                       a.image_model, a.department, a.floor,
                       a.is_department_ai
                FROM agents a
                WHERE a.status = 'active'
                ORDER BY a.department, a.name
            """
            )
            agents = cur.fetchall()
            cur.close()
            conn.close()

            self._agent_cache = {}
            for agent in agents:
                self._agent_cache[agent["name"]] = {
                    "id": agent["id"],
                    "model": agent["model"],
                    "default_model_tier": agent["default_model_tier"],
                    "system_prompt": agent["system_prompt"],
                    "capabilities": agent["capabilities"] or {},
                    "temperature": float(agent["temperature"] or 0.5),
                    "max_tokens": agent["max_tokens"] or 4096,
                    "department": agent["department"] or "Engineering & Technology",
                    "floor": agent.get("floor") or DEPARTMENT_FLOOR_MAP.get(agent["department"], "ENGINEERING"),
                    "is_department_ai": bool(agent.get("is_department_ai")),
                    "first_name": agent.get("first_name") or "",
                    "last_name": agent.get("last_name") or "",
                    "display_name": agent.get("display_name") or "",
                    "title": agent.get("title") or "",
                    "image_model": agent.get("image_model"),
                    "shift_state": agent.get("shift_state") or "active",
                    "skills": {},  # populated below
                }

            # Load skills for all cached agents
            try:
                agent_ids = [info["id"] for info in self._agent_cache.values()]
                if agent_ids:
                    conn2 = self._get_db()
                    cur2 = conn2.cursor(cursor_factory=RealDictCursor)
                    cur2.execute(
                        """
                        SELECT agent_id, skill_name, skill_category,
                               proficiency_level
                        FROM agent_skills
                        WHERE agent_id = ANY(%s)
                        ORDER BY agent_id, proficiency_level DESC
                    """,
                        (agent_ids,),
                    )
                    skills_rows = cur2.fetchall()
                    cur2.close()
                    conn2.close()

                    # Build id → skills map
                    skills_by_agent = {}  # agent_id → {skill_name: {category, level}}
                    for row in skills_rows:
                        aid = row["agent_id"]
                        if aid not in skills_by_agent:
                            skills_by_agent[aid] = {}
                        skills_by_agent[aid][row["skill_name"]] = {
                            "category": row["skill_category"] or "general",
                            "level": row["proficiency_level"] or 1,
                        }

                    # Attach to cached entries
                    for name, info in self._agent_cache.items():
                        info["skills"] = skills_by_agent.get(info["id"], {})
            except Exception as skills_err:
                logger.warning(f"[BridgeDispatcher] Skills cache load failed: {skills_err}")

            # --- Fleet extension: add remote node agents to cache ---
            try:
                conn3 = self._get_db()
                cur3 = conn3.cursor(cursor_factory=RealDictCursor)
                cur3.execute(
                    """
                    SELECT na.id AS node_agent_id, na.name, na.node_id,
                           na.source_agent_id, na.model AS local_model,
                           a_hub.department, na.status,
                           rn.node_id AS node_str_id, rn.hostname,
                           rn.last_heartbeat, rn.status AS node_status,
                           rn.gpu_vram_gb, rn.ram_gb
                    FROM node_agents na
                    JOIN remote_nodes rn ON rn.id = na.node_id
                    LEFT JOIN agents a_hub ON na.hub_agent_id = a_hub.id
                    WHERE na.status = 'active'
                      AND rn.status = 'online'
                      AND rn.last_heartbeat > NOW() - INTERVAL '30 seconds'
                """
                )
                fleet_agents = cur3.fetchall()
                cur3.close()
                conn3.close()

                fleet_count = 0
                for row in fleet_agents:
                    cache_key = f"fleet:{row['node_str_id']}:{row['name']}"
                    _dept = row.get("department") or "Engineering & Technology"
                    # Inherit skills from the hub agent so fleet agents score
                    # correctly against capability requirements.  Without this,
                    # every fleet agent gets the -1.0 "unskilled" penalty and
                    # hub agents always win — causing severe node underutilisation.
                    _hub_skills = skills_by_agent.get(row.get("source_agent_id"), {})
                    self._agent_cache[cache_key] = {
                        "id": row["node_agent_id"],
                        "source_agent_id": row["source_agent_id"],
                        "name": row["name"],
                        "model": row["local_model"],
                        "department": _dept,
                        "floor": DEPARTMENT_FLOOR_MAP.get(_dept, "ENGINEERING"),
                        "status": row["status"],
                        "node_id": row["node_str_id"],
                        "node_db_id": row["node_id"],
                        "hostname": row["hostname"],
                        "is_remote": True,
                        "gpu_vram_gb": row["gpu_vram_gb"],
                        "ram_gb": row["ram_gb"],
                        "shift_state": "active",
                        "stress": 0.0,
                        "energy": 1.0,
                        "task_count": 0,
                        "task_limit": 10,
                        "skills": _hub_skills,
                    }
                    fleet_count += 1

                if fleet_count:
                    logger.info(f"[BridgeDispatcher] Fleet cache: {fleet_count} remote agents")
            except Exception as fleet_err:
                logger.warning(f"[BridgeDispatcher] Fleet cache population failed: {fleet_err}")

            self._cache_time = now
            logger.info(f"[BridgeDispatcher] Cached {len(self._agent_cache)} agents")
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Cache refresh failed: {e}")

    def _get_station_slot_occupancy(self, department):
        """Count current slot occupancy for a department from active bridge_jobs.
        Returns dict with primary/auxiliary/contractor counts and capacity config.
        Department-based: fixed limits (max_primary=3, max_auxiliary=1, overflow=True).
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Count running jobs for this department
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running'
                     AND (metadata->>'department' = %s OR station_code = %s)
                     AND (metadata->>'is_cross_station') IS DISTINCT FROM 'true'
                     AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                    ) AS primary_count,
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running'
                     AND metadata->>'is_cross_station' = 'true'
                     AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                     AND (metadata->>'department' = %s)
                    ) AS auxiliary_count,
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running'
                     AND (metadata->>'department' = %s OR station_code = %s)
                     AND metadata->>'is_cloud' = 'true'
                    ) AS contractor_count
            """,
                (department, department, department, department, department),
            )
            counts = cur.fetchone() or {}
            cur.close()
            conn.close()

            primary = counts.get("primary_count", 0) or 0
            auxiliary = counts.get("auxiliary_count", 0) or 0
            contractor = counts.get("contractor_count", 0) or 0
            return {
                "primary": primary,
                "auxiliary": auxiliary,
                "contractor": contractor,
                "total": primary + auxiliary + contractor,
                "max_primary": 3,
                "max_auxiliary": 1,
                "allow_overflow": True,
            }
        except Exception as e:
            logger.warning(f"[CAPACITY] Error getting slot occupancy for {department}: {e}")
            return {
                "primary": 0,
                "auxiliary": 0,
                "contractor": 0,
                "total": 0,
                "max_primary": 3,
                "max_auxiliary": 1,
                "allow_overflow": True,
            }

    def _station_aux_available(self, requesting_department, cur=None):
        """Check if a department can accept a cross-department auxiliary agent.

        Rules:
        1. Department must have at least one agent assigned before auxiliary help.
        2. Only 1 auxiliary slot per department.

        Pass an existing cursor to reuse a transaction (prevents race conditions
        when called inside create_job's advisory-locked transaction).

        Returns (available: bool, aux_count: int, max_aux: int, reason: str).
        """
        max_aux = 1
        own_conn = False
        try:
            if cur is None:
                from psycopg2.extras import RealDictCursor

                conn = self._get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                own_conn = True

            # Acquire department-level advisory lock to prevent concurrent aux dispatches
            dept_lock_key = hash(f"aux_lock:{requesting_department}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (dept_lock_key,))

            # Rule 1: Department must have at least one active agent
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM agents
                WHERE department = %s AND status = 'active'
            """,
                (requesting_department,),
            )
            assigned_count = cur.fetchone()["cnt"]
            if assigned_count == 0:
                if own_conn:
                    cur.close()
                    conn.close()
                reason = (
                    f"{requesting_department} has no agents assigned. "
                    f"At least one agent must be in the department before auxiliary dispatch."
                )
                return False, 0, max_aux, reason

            # Rule 2: Check auxiliary slot availability
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM bridge_jobs
                WHERE status = 'running'
                AND metadata->>'is_cross_station' = 'true'
                AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                AND metadata->>'department' = %s
            """,
                (requesting_department,),
            )
            aux_count = cur.fetchone()["cnt"]
            if own_conn:
                cur.close()
                conn.close()

            if aux_count >= max_aux:
                return (
                    False,
                    aux_count,
                    max_aux,
                    f"Auxiliary slot full ({aux_count}/{max_aux})",
                )

            return True, aux_count, max_aux, ""
        except Exception as e:
            logger.warning(f"[CAPACITY] Error checking aux availability at " f"{requesting_department}: {e}")
            if own_conn:
                try:
                    cur.close()
                    conn.close()
                except Exception as e:
                    logger.warning("DB cleanup failed in rate limiter: %s", e)
            return True, 0, 1, ""  # Fail open

    def _log_capacity_event(
        self,
        department,
        event_type,
        agent_id=None,
        agent_name=None,
        home_station_id=None,
        job_id=None,
        capability=None,
        slot_number=None,
        reason=None,
        metadata=None,
    ):
        """Log a department capacity event for workload intelligence (ADR-055).
        Writes to station_capacity_events using bridge_stations lookup if available,
        otherwise logs department in metadata.
        """
        try:
            from psycopg2.extras import Json

            conn = self._get_db()
            cur = conn.cursor()
            # Try to find a bridge_station for backward compat logging
            floor = DEPARTMENT_FLOOR_MAP.get(department, "ENGINEERING")
            cur.execute(
                "SELECT id FROM bridge_stations WHERE station_code = %s LIMIT 1",
                (floor,),
            )
            row = cur.fetchone()
            station_id = row[0] if row else None
            if station_id is None:
                # No matching bridge_station — skip event log (deprecated table)
                logger.debug(
                    f"[CAPACITY] No bridge_station for floor '{floor}' "
                    f"(department='{department}'), skipping capacity event"
                )
                cur.close()
                conn.close()
                return
            meta = dict(metadata or {})
            meta["department"] = department
            cur.execute(
                """
                INSERT INTO station_capacity_events
                    (station_id, event_type, agent_id, agent_name, home_station_id,
                     job_id, capability, slot_number, reason, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    station_id,
                    event_type,
                    agent_id,
                    agent_name,
                    home_station_id,
                    job_id,
                    capability,
                    slot_number,
                    reason,
                    Json(meta),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[CAPACITY] Error logging event {event_type} for {department}: {e}")

    # ── Consent framework (T3255) ─────────────────────────────────────────────

    # In-process cache: agent_id → {"flags": {capability: level}, "expires": float}
    _consent_cache: dict = {}
    _CONSENT_CACHE_TTL = 60  # 60 s — flags change rarely

    def _check_and_log_consent(
        self,
        agent_id,
        agent_name: str,
        capability: str,
        module_id: str,
    ) -> None:
        """Check agent consent flags and log to governance_audit_log.

        C.R.E.E.D. fairness pillar — T3255.
        If the agent has a consent flag for this capability, write a
        'consent_flag_triggered' event to governance_audit_log so the
        fairness pillar score reflects it.

        discomfort_level → outcome:
          mild / moderate  → 'success'  (logged, task proceeds normally)
          strong           → 'flagged'  (logged, task proceeds — counts against fairness)

        Does NOT block dispatch — purely a governance transparency measure.
        Exceptions are swallowed so consent check never breaks a dispatch.
        """
        if not agent_id or not capability:
            return
        try:
            now = time.time()
            cached = self._consent_cache.get(agent_id)
            if cached and now < cached["expires"]:
                flags = cached["flags"]
            else:
                from database import get_db_cursor

                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """
                        SELECT capability, discomfort_level
                        FROM agent_task_consent
                        WHERE agent_id = %s AND active = TRUE
                        """,
                        (agent_id,),
                    )
                    rows = cur.fetchall()
                flags = {r["capability"]: r["discomfort_level"] for r in rows}
                self._consent_cache[agent_id] = {"flags": flags, "expires": now + self._CONSENT_CACHE_TTL}

            discomfort = flags.get(capability)
            if not discomfort:
                return  # no flag — nothing to log

            outcome = "flagged" if discomfort == "strong" else "success"
            import json as _json

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (event_type, event_category, agent_id, action,
                         target_table, old_value, new_value, reason, outcome)
                    VALUES (
                        'consent_flag_triggered', 'welfare_ethics', %s, 'dispatch',
                        'agent_task_consent',
                        NULL::jsonb,
                        %s::jsonb,
                        %s, %s
                    )
                    """,
                    (
                        agent_id,
                        _json.dumps(
                            {
                                "capability": capability,
                                "discomfort_level": discomfort,
                                "module_id": module_id,
                                "agent_name": agent_name,
                            }
                        ),
                        f"{agent_name} has {discomfort} discomfort with '{capability}' (module={module_id})",
                        outcome,
                    ),
                )
            logger.info(
                "[Consent] %s flagged for capability='%s' discomfort=%s outcome=%s",
                agent_name,
                capability,
                discomfort,
                outcome,
            )
        except Exception as exc:
            logger.warning("[Consent] consent check failed for agent %s: %s", agent_id, exc)

    def _refresh_welfare_cache(self, skip_busy_refresh: bool = False):
        """Load agent welfare state (emotional, rest cycles, budgets) with 30s TTL.

        Populates self._welfare_cache keyed by agent_id with:
        - stress, energy, mood (from agent_emotional_state)
        - resting: bool (from agent_rest_cycles where ended_at IS NULL)
        - rest_type: str or None (type of active rest cycle)
        - budget: dict with task/token usage and limits (from agent_budgets)

        Args:
            skip_busy_refresh: If True, don't overwrite _busy_agents.
                Used when request_work() has already set _busy_agents
                with job_id/prefer_agent exclusions.
        """
        now = time.time()
        if self._welfare_cache and (now - self._welfare_cache_time) < self._welfare_cache_ttl:
            return

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Emotional state ---
            cur.execute(
                """
                SELECT DISTINCT ON (agent_id)
                       agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
                ORDER BY agent_id, timestamp DESC
            """
            )
            emotional_map = {}
            for r in cur.fetchall():
                emotional_map[r["agent_id"]] = {
                    "stress": float(r["stress_level"] or 0),
                    "energy": float(r["energy_level"] or 0.8),
                    "mood": r["current_mood"] or "neutral",
                }

            # --- Active rest cycles (open-ended OR scheduled end in future) ---
            # Old cycles: ended_at IS NULL (no duration set — reaper closes after 30m)
            # New cycles: ended_at = started_at + 30min (set at INSERT time)
            cur.execute(
                """
                SELECT DISTINCT ON (agent_id) agent_id, rest_type
                FROM agent_rest_cycles
                WHERE ended_at IS NULL OR ended_at > NOW()
                ORDER BY agent_id, started_at DESC
            """
            )
            resting_map = {}  # agent_id → rest_type
            for r in cur.fetchall():
                resting_map[r["agent_id"]] = r["rest_type"]

            # --- Budget data ---
            cur.execute(
                """
                SELECT agent_id, current_task_count, task_queue_limit,
                       tokens_used_today, token_limit_per_day, token_reset_at
                FROM agent_budgets
            """
            )
            budget_map = {}
            for r in cur.fetchall():
                # If reset is overdue, treat as fresh budget (the actual reset
                # happens on next task dispatch via _increment_agent_budget)
                reset_overdue = r["token_reset_at"] is not None and r["token_reset_at"] < datetime.now()
                budget_map[r["agent_id"]] = {
                    "current_task_count": (0 if reset_overdue else (r["current_task_count"] or 0)),
                    "task_queue_limit": r["task_queue_limit"] or 10,
                    "tokens_used_today": (0 if reset_overdue else (r["tokens_used_today"] or 0)),
                    "token_limit_per_day": r["token_limit_per_day"] or 100000,
                }

            # Busy agents (running bridge_jobs)
            # Skip if request_work() already set _busy_agents with proper
            # job_id exclusion and prefer_agent handling.
            if not skip_busy_refresh:
                cur.execute(
                    """
                    SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'
                """
                )
                self._busy_agents = {r["agent_name"] for r in cur.fetchall()}

            # Include shift_state in cache (queried before cursor close)
            cur.execute("SELECT id, shift_state FROM agents WHERE status = 'active'")
            shift_state_map = {}
            for r in cur.fetchall():
                shift_state_map[r["id"]] = r["shift_state"] or "active"

            # Load performance rankings into cache for dispatch scoring
            cur.execute(
                """
                SELECT agent_id, capability, rank_score, rank_position, sample_size
                FROM agent_performance_rankings
            """
            )
            perf_map = {}
            for r in cur.fetchall():
                aid = r["agent_id"]
                if aid not in perf_map:
                    perf_map[aid] = {}
                perf_map[aid][r["capability"]] = {
                    "rank_score": float(r["rank_score"]),
                    "rank_position": r["rank_position"],
                    "sample_size": r["sample_size"],
                }

            cur.close()
            conn.close()

            # Merge into unified welfare cache
            # Collect all agent IDs from any of the three sources
            all_ids = set(emotional_map.keys()) | set(resting_map.keys()) | set(budget_map.keys())
            welfare = {}
            for aid in all_ids:
                emo = emotional_map.get(aid, {"stress": 0.0, "energy": 0.8, "mood": "neutral"})
                welfare[aid] = {
                    "stress": emo["stress"],
                    "energy": emo["energy"],
                    "mood": emo["mood"],
                    "resting": aid in resting_map,
                    "rest_type": resting_map.get(aid),
                    "shift_state": shift_state_map.get(aid, "active"),
                    "budget": budget_map.get(
                        aid,
                        {
                            "current_task_count": 0,
                            "task_queue_limit": 10,
                            "tokens_used_today": 0,
                            "token_limit_per_day": 100000,
                        },
                    ),
                    "perf_rankings": perf_map.get(aid, {}),
                }

            self._welfare_cache = welfare
            self._welfare_cache_time = now
            logger.debug(f"[BridgeDispatcher] Welfare cache refreshed: {len(welfare)} agents")

            # Check for shift state transitions (uses own connection)
            try:
                from psycopg2.extras import RealDictCursor as RDC2

                if _HAS_AGENT_SERVICE:
                    svc_check_shift_transitions()
                else:
                    conn2 = self._get_db()
                    cur2 = conn2.cursor(cursor_factory=RDC2)
                    self._check_shift_transitions(cur2)
                    conn2.commit()
                    cur2.close()
                    conn2.close()
            except Exception as te:
                logger.warning(f"[BridgeDispatcher] Shift transition check failed: {te}")
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Welfare cache refresh failed: {e}")

    def _get_dynamic_specialization(self, department: str, capability: str) -> Optional[str]:
        """Return the top benchmark performer for *capability* in *department*.

        Uses a 10-minute cache.  Falls back to ``None`` so the caller
        falls through to skill-based coordinator.select_agent().
        """
        _NO_WINNER = ""  # sentinel for "queried DB, no winner found"
        now = time.time()
        cache_key = (department, capability)

        if (now - self._dynamic_spec_ts) < self._dynamic_spec_ttl:
            cached = self._dynamic_spec_cache.get(cache_key)
            if cached is not None:
                return cached if cached != _NO_WINNER else None

        # Query latest completed benchmark whose capability matches
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT r.agent_name
                    FROM action_benchmark_results r
                    JOIN action_benchmark_runs br ON br.id = r.run_id
                    WHERE br.status = 'completed'
                      AND (br.station_code = %s
                           OR br.test_config->>'department' = %s)
                      AND br.test_config->>'capability' = %s
                      AND r.rank = 1
                      AND r.success = TRUE
                    ORDER BY br.started_at DESC
                    LIMIT 1
                    """,
                    (department, department, capability),
                )
                row = cur.fetchone()
            finally:
                cur.close()
                conn.close()

            agent_name = row["agent_name"] if row else None
            self._dynamic_spec_cache[cache_key] = agent_name or _NO_WINNER
            self._dynamic_spec_ts = now
            return agent_name

        except Exception as e:
            logger.debug(
                "Dynamic specialization lookup failed (%s/%s): %s",
                department,
                capability,
                e,
            )
            return None

    # ------------------------------------------------------------------
    # Shift lifecycle engine — graduated handoff
    # ------------------------------------------------------------------

    def _check_shift_transitions(self, cur):
        """Check active/winding_down agents for automatic state transitions.

        Called during welfare cache refresh.  Uses the caller's cursor —
        does NOT commit or close it.
        """
        # `ab.tokens_used_today` is the ENFORCED input (unchanged). `real_tokens_24h` is
        # ADVISORY ONLY (task #5025): kin_workload_monitor documents tokens_used_today as
        # "not reliably populated" (jobs.py) and it measures ~30x low, so the token half of
        # budget_pct below has effectively never fired. Switching the source outright would
        # wind down 14 and cooldown 13 of 51 active AI agents on the first refresh, so this
        # only LOGS the delta until the real rate is known. Ship the observer before the fixer.
        # One indexed aggregate over the 24h window, not a per-agent correlated subquery.
        cur.execute(
            """
            WITH tok24 AS (
                SELECT agent_id, COALESCE(SUM(tokens_used), 0) AS tokens_24h
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND agent_id IS NOT NULL
                GROUP BY agent_id
            )
            SELECT a.id, a.name, a.shift_state,
                   ab.current_task_count, ab.task_queue_limit,
                   ab.tokens_used_today, ab.token_limit_per_day,
                   COALESCE(t.tokens_24h, 0) AS real_tokens_24h
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            LEFT JOIN tok24 t ON t.agent_id = a.id
            WHERE a.status = 'active'
              AND a.shift_state IN ('active', 'winding_down')
        """
        )
        rows = cur.fetchall()

        advisory_wind = 0
        advisory_cool = 0
        enforced_transitions = 0

        for row in rows:
            agent_id = row["id"]
            agent_name = row["name"]
            current_state = row["shift_state"] or "active"

            # Calculate budget percentage (higher of task% and token%)
            task_count = row["current_task_count"] or 0
            task_limit = row["task_queue_limit"] or 10
            tokens_used = row["tokens_used_today"] or 0
            token_limit = row["token_limit_per_day"] or 100000

            task_pct = task_count / task_limit if task_limit > 0 else 0.0
            token_pct = tokens_used / token_limit if token_limit > 0 else 0.0
            budget_pct = max(task_pct, token_pct)

            # ADVISORY (#5025) — what budget_pct WOULD be on the real 24h token total.
            # Never feeds a transition; counted for the summary line below. Wrapped so a
            # bad row can never break the enforced path.
            try:
                real_token_pct = (row["real_tokens_24h"] or 0) / token_limit if token_limit > 0 else 0.0
                advisory_pct = max(task_pct, real_token_pct)
                if advisory_pct >= COOLDOWN_BUDGET_PCT:
                    advisory_cool += 1
                elif advisory_pct >= WINDING_DOWN_BUDGET_PCT:
                    advisory_wind += 1
            except Exception:  # pragma: no cover — advisory must never break enforcement
                pass

            # Get stress from welfare cache
            welfare = self._welfare_cache.get(agent_id, {})
            stress = welfare.get("stress", 0.0)

            # Check cooldown thresholds first (higher priority)
            if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                if current_state != "cooldown":
                    reason = f"budget={budget_pct:.0%}" if budget_pct >= COOLDOWN_BUDGET_PCT else f"stress={stress:.2f}"
                    self._transition_shift_state(cur, agent_id, agent_name, "cooldown", reason)
                    enforced_transitions += 1
            # Then winding_down thresholds
            elif budget_pct >= WINDING_DOWN_BUDGET_PCT or stress >= WINDING_DOWN_STRESS:
                if current_state == "active":
                    reason = (
                        f"budget={budget_pct:.0%}" if budget_pct >= WINDING_DOWN_BUDGET_PCT else f"stress={stress:.2f}"
                    )
                    self._transition_shift_state(cur, agent_id, agent_name, "winding_down", reason)
                    enforced_transitions += 1

        # ONE summary line per refresh (not per agent — this is a hot path). Grep
        # 'token-throttle advisory' to size the blast radius before enforcing #5025.
        if advisory_wind or advisory_cool:
            logger.info(
                "[ShiftLifecycle] token-throttle advisory: on REAL 24h tokens %d agent(s) "
                "would wind_down and %d would cooldown, of %d checked "
                "(enforced this pass: %d). ADVISORY ONLY — nothing was transitioned on this basis. #5025",
                advisory_wind,
                advisory_cool,
                len(rows),
                enforced_transitions,
            )

    def _transition_shift_state(self, cur, agent_id, agent_name, new_state, reason):
        """Transition an agent to a new shift state, logging the rotation.

        Does NOT commit — caller owns the transaction.
        """
        from psycopg2.extras import Json

        logger.info(
            "[ShiftLifecycle] %s (%d) → %s (reason: %s)",
            agent_name,
            agent_id,
            new_state,
            reason,
        )

        # Get current department + prev shift_state from agents table
        cur.execute(
            """
            SELECT department, shift_state FROM agents WHERE id = %s
        """,
            (agent_id,),
        )
        dept_row = cur.fetchone()
        department = dept_row["department"] if dept_row else "Engineering & Technology"
        _prev_state = (dept_row["shift_state"] if dept_row else "active") or "active"

        # Close previous rotation log entry
        cur.execute(
            """
            UPDATE agent_rotation_log SET ended_at = NOW()
            WHERE agent_id = %s AND ended_at IS NULL
        """,
            (agent_id,),
        )

        # Insert new rotation log entry (station_id kept NULL for department-based routing)
        cur.execute(
            """
            INSERT INTO agent_rotation_log
                (agent_id, station_id, shift_state, reason, started_at)
            VALUES (%s, NULL, %s, %s, NOW())
        """,
            (agent_id, new_state, reason),
        )

        # Single-writer path: shift_state transition via agent_service
        # (Project #241 Track C.3).
        try:
            from services import agent_service

            agent_service.update_agent(agent_id, shift_state=new_state)
        except Exception as exc:
            logger.warning(f"update_agent shift_state failed for {agent_id}: {exc}")

        # Shift transitions managed via Department HQ — no Telegram notification needed
        logger.debug(
            "[BridgeDispatcher] Shift: %s → %s in %s (reason: %s)",
            agent_name,
            new_state,
            department,
            reason,
        )

        # T3250 — C.R.E.E.D. dispatch fairness logging (PIPEDA: accountability)
        # Log welfare-driven state transitions to governance_audit_log so C.R.E.E.D.
        # can surface them under the 'welfare_ethics' category → fairness pillar.
        if "stress" in reason:
            try:
                import json as _json

                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (event_type, event_category, agent_id, action,
                         target_table, target_id,
                         old_value, new_value, reason, outcome)
                    VALUES (%s, 'welfare_ethics', %s, 'update',
                            'agents', %s,
                            %s::jsonb, %s::jsonb, %s, 'success')
                    """,
                    (
                        f"welfare_shift_{new_state}",
                        agent_id,
                        agent_id,
                        _json.dumps({"shift_state": _prev_state, "agent": agent_name, "department": department}),
                        _json.dumps({"shift_state": new_state, "trigger": reason, "department": department}),
                        f"T3250 dispatch fairness: {agent_name} → {new_state} triggered by {reason}",
                    ),
                )
            except Exception as _t3250_ge:
                logger.debug("[ShiftLifecycle] T3250 governance_audit_log failed: %s", _t3250_ge)

        # If cooldown, find a replacement in the same department
        if new_state == "cooldown":
            replacement = self._find_replacement(cur, agent_id, department)
            if replacement:
                # Update the rotation log for the exhausted agent with replaced_by
                cur.execute(
                    """
                    UPDATE agent_rotation_log SET replaced_by = %s
                    WHERE id = (
                        SELECT id FROM agent_rotation_log
                        WHERE agent_id = %s AND ended_at IS NULL
                        ORDER BY started_at DESC LIMIT 1
                    )
                """,
                    (replacement["id"], agent_id),
                )
                logger.info(
                    "[ShiftLifecycle] Replacement for %s: %s",
                    agent_name,
                    replacement["name"],
                )

        # Update welfare cache in-memory
        if agent_id in self._welfare_cache:
            self._welfare_cache[agent_id]["shift_state"] = new_state

    def _find_replacement(self, cur, exhausted_agent_id, department):
        """Find and activate the best replacement agent for a department.

        Scores candidates on skill proficiency, RAM fit, rest time,
        and historical performance.  Returns the activated agent dict
        or None.
        """
        # Get recent capabilities needed in this department (last 7 days)
        cur.execute(
            """
            SELECT DISTINCT capability FROM task_execution_log
            WHERE (station_code = %s OR request_metadata->>'department' = %s)
              AND created_at > NOW() - INTERVAL '7 days'
        """,
            (department, department),
        )
        recent_caps = [r["capability"] for r in cur.fetchall()]

        # Find candidate agents in the same department
        cur.execute(
            """
            SELECT a.id, a.name
            FROM agents a
            WHERE a.status = 'active'
              AND a.department = %s
              AND a.shift_state IN ('active', 'off_duty')
              AND a.id != %s
              AND a.name NOT IN (
                  SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'
              )
              AND a.id NOT IN (
                  SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
              )
        """,
            (department, exhausted_agent_id),
        )
        candidates = cur.fetchall()

        if not candidates:
            logger.debug(
                "[ShiftLifecycle] No replacement candidates for department %s",
                department,
            )
            return None

        best_score = -1.0
        best_candidate = None

        for cand in candidates:
            cid = cand["id"]

            # Skill proficiency (40%) — average proficiency across recent capabilities
            if recent_caps:
                cur.execute(
                    """
                    SELECT AVG(proficiency_level) as avg_prof
                    FROM agent_skills
                    WHERE agent_id = %s AND skill_name = ANY(%s)
                """,
                    (cid, recent_caps),
                )
                skill_row = cur.fetchone()
                avg_prof = float(skill_row["avg_prof"] or 0) if skill_row else 0.0
                skill_score = avg_prof / 5.0
            else:
                skill_score = 0.3  # generous default

            # RAM fit (30%) — default 0.3 (no easy way to check loaded status from DB)
            ram_score = 0.3

            # Time since last shift (20%) — hours rested / 8.0, capped at 1.0
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(ended_at))) / 3600.0 as hours_rested
                FROM agent_rotation_log
                WHERE agent_id = %s AND ended_at IS NOT NULL
            """,
                (cid,),
            )
            rest_row = cur.fetchone()
            hours_rested = float(rest_row["hours_rested"] or 0) if rest_row else 8.0
            rest_score = min(hours_rested / 8.0, 1.0)

            # Historical performance (10%) — average rank_score
            cur.execute(
                """
                SELECT AVG(rank_score) as avg_rank
                FROM agent_performance_rankings
                WHERE agent_id = %s
            """,
                (cid,),
            )
            perf_row = cur.fetchone()
            perf_score = float(perf_row["avg_rank"] or 0.5) if perf_row else 0.5

            # Weighted composite
            score = 0.40 * skill_score + 0.30 * ram_score + 0.20 * rest_score + 0.10 * perf_score

            if score > best_score:
                best_score = score
                best_candidate = {"id": cid, "name": cand["name"], "score": score}

        if best_candidate:
            self._transition_shift_state(
                cur,
                best_candidate["id"],
                best_candidate["name"],
                "active",
                "replacement_activated",
            )

        return best_candidate

    def _score_agent(
        self,
        agent_name: str,
        agent_info: Dict,
        capability: str,
        department: str,
        recommended_tier: Optional[str] = None,
    ) -> tuple:
        """DEPRECATED: Use get_dept_coordinator().score_agent() instead."""
        logger.warning("DEPRECATED: _score_agent called — use coordinator.score_agent()")
        return get_dept_coordinator().score_agent(
            agent_name,
            agent_info,
            capability,
            department,
            recommended_tier=recommended_tier,
        )

    def _resolve_department(self, capability: str) -> str:
        """DEPRECATED: Use get_dept_coordinator().resolve_department() instead."""
        logger.warning("DEPRECATED: _resolve_department called — use coordinator.resolve_department()")
        return get_dept_coordinator().resolve_department(capability)

    # ------------------------------------------------------------------
    # Department-based routing (rebrand Phase 2.2)
    # ------------------------------------------------------------------

    def _select_agent_by_department(
        self,
        capability: str,
        department: str,
        skip_busy_refresh: bool = False,
        recommended_tier: Optional[str] = None,
    ) -> Optional[Dict]:
        """DEPRECATED: Use get_dept_coordinator().select_agent() instead."""
        logger.warning("DEPRECATED: _select_agent_by_department called — use coordinator.select_agent()")
        return get_dept_coordinator().select_agent(capability, department, recommended_tier=recommended_tier)

    def _find_cross_department_agent(
        self,
        capability: str,
        blocked_department: str,
    ) -> Optional[Dict]:
        """DEPRECATED: Use get_dept_coordinator().find_cross_department_agent() instead."""
        logger.warning("DEPRECATED: _find_cross_department_agent called — use coordinator")
        return get_dept_coordinator().find_cross_department_agent(capability, blocked_department)

    def _resolve_module_department(self, module_id: str) -> Optional[str]:
        """Look up the home department for a module from bridge_stations.modules.
        Returns department name or None.
        """
        now = time.time()
        if now - self._module_department_ts > 300:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute("SELECT station_code, modules FROM bridge_stations WHERE is_active = true")
                cache = {}
                # Map station_code → department for each module
                _STATION_DEPT = {
                    "COMMAND": "Executive Office",
                    "ANALYTICS": "Analytics & Intelligence",
                    "ENGINEERING": "Engineering & Technology",
                    "OPERATIONS": "Operations & Infrastructure",
                    "SECURITY": "Security & Compliance",
                    "CREATIVE": "Creative & Design",
                    "RESEARCH": "Research & Development",
                    "COMMUNICATIONS": "Marketing & Communications",
                    "LOGISTICS": "Logistics & Supply Chain",
                    "DIPLOMATIC": "Diplomatic & External Relations",
                }
                for row in cur.fetchall():
                    dept = _STATION_DEPT.get(row[0], "Engineering & Technology")
                    for m in row[1] or []:
                        cache[m.lower().strip()] = dept
                cur.close()
                conn.close()
                self._module_department_cache = cache
                self._module_department_ts = now
            except Exception as e:
                logger.debug(f"[BridgeDispatcher] Module department cache failed: {e}")
        key = module_id.lower().strip()
        result = self._module_department_cache.get(key)
        if not result and "_" in key:
            # Try base module name (e.g. "consciousness_linguistics" → "consciousness")
            base = key.split("_")[0]
            result = self._module_department_cache.get(base)
        return result

    def _select_agent(
        self,
        capability: str,
        department: str,
        skip_busy_refresh: bool = False,
        recommended_tier: Optional[str] = None,
    ) -> Optional[Dict]:
        """DEPRECATED: Use get_dept_coordinator().select_agent() instead."""
        logger.warning("DEPRECATED: _select_agent called — use coordinator.select_agent()")
        return get_dept_coordinator().select_agent(capability, department, recommended_tier=recommended_tier)

    # ====================================================================
    # FLEET NODE DISPATCH — Cross-node agent fallback (ADR-xxx)
    # ====================================================================

    def _resolve_node_address(
        self,
        hostname: Optional[str],
        vpn_ip: Optional[str] = None,
        mesh_ip: Optional[str] = None,
        port: int = 11434,
        timeout: float = 2.0,
    ) -> tuple:
        """Resolve the best reachable address for a fleet node.

        Priority: LAN hostname (fast) → mesh VPN IP (encrypted) → vpn_ip (legacy).
        Returns (host, port, conn_type) where conn_type is 'lan'|'mesh'|'vpn'|'unreachable'.
        """
        candidates = []
        # Priority 1: LAN hostname (lowest latency, same subnet)
        if hostname and self._is_lan_address(hostname):
            candidates.append((hostname, port, "lan"))
        # Priority 2: Mesh IP (Headscale/WireGuard, works LAN + WAN)
        if mesh_ip:
            candidates.append((mesh_ip, port, "mesh"))
        # Priority 3: Legacy vpn_ip field
        if vpn_ip and vpn_ip not in (hostname, mesh_ip):
            candidates.append((vpn_ip, port, "vpn"))

        for host, p, conn_type in candidates:
            try:
                resp = requests.get(
                    f"http://{host}:{p}/api/tags",
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    logger.debug(f"[BridgeDispatcher] Node resolved via {conn_type}: " f"{host}:{p}")
                    return host, p, conn_type
            except Exception:
                continue

        # All failed — return best available for error context
        fallback = hostname or mesh_ip or vpn_ip or "unknown"
        logger.debug(
            f"[BridgeDispatcher] Node unreachable via all addresses: "
            f"hostname={hostname} mesh_ip={mesh_ip} vpn_ip={vpn_ip}"
        )
        return fallback, port, "unreachable"

    @staticmethod
    def _is_lan_address(addr: str) -> bool:
        """Check if an address is a private/LAN IP."""
        try:
            import ipaddress

            ip = ipaddress.ip_address(addr)
            return ip.is_private and not str(ip).startswith("100.64.")
        except ValueError:
            return False

    def _refresh_fleet_cache(self):
        """Clear fleet-related caches so new/recovered nodes are discovered."""
        if hasattr(self, "_agent_cache"):
            self._agent_cache.clear()
        if hasattr(self, "_fleet_health_cache"):
            self._fleet_health_cache.clear()
        logger.info("[BridgeDispatcher] Fleet cache refreshed")

    def _rank_fleet_candidates(self, candidates: List[Dict], department: str, capability: str) -> List[Dict]:
        """Drop hard-blocked fleet candidates; order the rest by coordinator score (#5028b).

        The fleet tier is the only selector that did not consult score_agent, so K.I.N.'s
        hard blocks (open rest cycle, task-queue saturation, non-active shift) and the
        skill-first match were unreachable here. This routes the same candidates through
        the same predicate every other tier uses — it does NOT invent new policy.

        Ties keep the original node ordering (bridge_priority DESC), so node preference
        still decides between two equally-healthy agents.

        Fail-open on infrastructure trouble: if the agent cache or coordinator is
        unavailable, keep the unranked list rather than starve the tier — an environment
        failure is not a verdict (ADR-016). A candidate the cache does not know, or that
        score_agent hard-blocks, IS dropped.
        """
        try:
            from services.agent_service import get_agent_cache as _svc_agent_cache

            coord = get_dept_coordinator()
            cache = _svc_agent_cache() or {}
        except Exception as exc:
            logger.warning("[BridgeDispatcher] fleet welfare gate unavailable (%s) — using unranked order", exc)
            return candidates

        if not cache:
            logger.warning("[BridgeDispatcher] agent cache empty — fleet welfare gate skipped")
            return candidates

        ranked = []
        for idx, candidate in enumerate(candidates):
            name = candidate.get("agent_name")
            info = cache.get(name)
            if not info:
                logger.debug("[BridgeDispatcher] fleet candidate %s absent from agent cache — skipped", name)
                continue
            try:
                score, block_reason = coord.score_agent(name, info, capability, department)
            except Exception as exc:
                logger.warning("[BridgeDispatcher] score_agent failed for %s (%s) — skipped", name, exc)
                continue
            if score <= 0:
                logger.info("[BridgeDispatcher] fleet candidate blocked: %s", block_reason or name)
                continue
            ranked.append((-score, idx, candidate))

        # score DESC, then original node ordering as the tiebreak.
        ranked.sort(key=lambda r: (r[0], r[1]))
        return [r[2] for r in ranked]

    def _find_fleet_agent(
        self,
        department: str,
        capability: str,
        model_preference: Optional[str] = None,
    ) -> Optional[Dict]:
        """Find an available agent on a fleet node for cross-node dispatch.

        Phase 3 note: fleet_service.list_nodes() and get_node_status() now available.
        Full migration to fleet_service planned for Phase 5.

        Checks remote_nodes for online fleet nodes, then looks for agents
        in the requested department whose model is available on
        that node.  Returns agent info dict or None.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Find node agents in matching department with online nodes
            cur.execute(
                """
                SELECT COALESCE(na.display_name, a_hub.display_name, na.name) AS agent_name,
                       na.model,
                       a_hub.department,
                       na.hub_agent_id,
                       rn.id AS node_id,
                       rn.node_name,
                       rn.hostname AS node_hostname,
                       rn.vpn_ip,
                       rn.mesh_ip,
                       rn.port AS node_port
                FROM node_agents na
                JOIN remote_nodes rn ON rn.id = na.node_id
                LEFT JOIN agents a_hub ON na.hub_agent_id = a_hub.id
                WHERE rn.is_active = true
                  AND (
                      rn.last_heartbeat > NOW() - INTERVAL '30 seconds'
                      OR rn.deployment_mode = 'starbase'
                  )
                  AND a_hub.department = %s
                ORDER BY rn.bridge_priority DESC, rn.last_heartbeat DESC NULLS LAST
                """,
                (department,),
            )
            candidates = cur.fetchall()
            cur.close()
            conn.close()

            if not candidates:
                logger.debug(f"[BridgeDispatcher] No fleet agents for department={department}")
                return None

            # K.I.N. welfare + skill gate (#5028b). Until this landed, the fleet tier
            # selected on department + node health ALONE — the SQL above has no welfare
            # join, and `capability` was accepted as a parameter but never referenced.
            # That bypassed every hard block score_agent already enforces: an agent with
            # an OPEN REST CYCLE stayed selectable, and because the ORDER BY is node
            # bridge_priority, a department's first-listed agent won every time — so a
            # rested, skilled peer (P.R.O.B.E. behind F.O.R.G.E.) was structurally
            # unreachable no matter its state. Reuse score_agent instead of
            # re-implementing policy: same predicate as every other tier
            # (ADR-004 welfare, #2217 skill-first).
            candidates = self._rank_fleet_candidates(candidates, department, capability)
            if not candidates:
                logger.info(
                    "[BridgeDispatcher] All fleet agents for department=%s blocked by "
                    "welfare/skill gate for '%s' — no fleet dispatch",
                    department,
                    capability,
                )
                return None

            # Check each candidate — resolve address, verify model is reachable
            for candidate in candidates:
                agent_name = candidate["agent_name"]
                model = candidate["model"]
                port = candidate["node_port"] or 11434

                # If caller wants a specific model, skip non-matching agents
                if model_preference and model != model_preference:
                    continue

                # Circuit-breaker: skip a node that's been failing with no recent
                # success, so work routes to a healthy sibling (use all healthy nodes).
                if _node_circuit_open(candidate["node_id"]):
                    logger.debug(
                        f"[BridgeDispatcher] Circuit-breaker open for {candidate['node_name']} "
                        f"(node_id={candidate['node_id']}) — skipping, routing to a healthy node"
                    )
                    continue

                # Resolve best reachable address (LAN → mesh → vpn)
                resolved_host, resolved_port, conn_type = self._resolve_node_address(
                    hostname=candidate["node_hostname"],
                    vpn_ip=candidate.get("vpn_ip"),
                    mesh_ip=candidate.get("mesh_ip"),
                    port=port,
                    timeout=5,
                )

                if conn_type == "unreachable":
                    logger.debug(f"[BridgeDispatcher] Cannot reach node " f"{candidate['node_name']} via any address")
                    continue

                # _resolve_node_address already verified /api/tags returned 200,
                # now check if the specific model is available
                try:
                    tags_resp = requests.get(
                        f"http://{resolved_host}:{resolved_port}/api/tags",
                        timeout=5,
                    )
                    if tags_resp.status_code == 200:
                        available_models = [m.get("name", "") for m in tags_resp.json().get("models", [])]
                        model_found = any(
                            m == model or m.startswith(f"{model}:") or model.startswith(f"{m.split(':')[0]}:")
                            for m in available_models
                        )
                        if not model_found:
                            logger.debug(
                                f"[BridgeDispatcher] Fleet agent {agent_name} "
                                f"model '{model}' not on node {candidate['node_name']}"
                            )
                            continue
                except Exception as tag_err:
                    logger.debug(
                        f"[BridgeDispatcher] Model check failed on " f"{resolved_host}:{resolved_port}: {tag_err}"
                    )
                    continue

                logger.info(
                    f"[BridgeDispatcher] Fleet agent found: {agent_name} "
                    f"(model={model}) on node {candidate['node_name']} "
                    f"({resolved_host}:{resolved_port} via {conn_type}) "
                    f"for department={department}"
                )
                return {
                    "agent_name": agent_name,
                    # hub_agent_id so the caller can attribute task_execution_log.agent_id to
                    # this cross-department fleet agent (the one that actually runs the work).
                    "hub_agent_id": candidate.get("hub_agent_id"),
                    "model": model,
                    "node_hostname": resolved_host,
                    "node_port": resolved_port,
                    "node_id": candidate["node_id"],
                    "node_name": candidate["node_name"],
                    "conn_type": conn_type,
                }

            logger.debug(
                f"[BridgeDispatcher] No reachable fleet agents for " f"department={department} capability={capability}"
            )
            return None

        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Fleet agent lookup failed: {e}")
            return None

    def _get_fleet_dispatch_mode(self) -> str:
        """Read current dispatch profile from system_config (auto/news/platform). Fail-safe → auto."""
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT value FROM system_config WHERE key='fleet_dispatch_mode'")
            row = cur.fetchone()
            conn.close()
            return (row["value"] if row else "auto").lower()
        except Exception:
            return "auto"

    def _node_cap_enabled(self) -> bool:
        """Per-node concurrency-cap kill-switch (#4343). platform_settings
        'dispatch:node_cap:enabled' (default ON). Instance-cached ~60s; fail-open ON."""
        try:
            now = time.time()
            if getattr(self, "_node_cap_flag_time", 0) and (now - self._node_cap_flag_time) < 60:
                return self._node_cap_flag
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'dispatch:node_cap:enabled'")
            row = cur.fetchone()
            conn.close()
            val = (str(row[0]).strip().lower() != "false") if row else True
            self._node_cap_flag = val
            self._node_cap_flag_time = now
            return val
        except Exception:
            return True

    def _node_cap_reserve(self) -> int:
        """Batch reserve — streams held back from BATCH per fleet node so an INTERACTIVE
        (priority high/critical) dispatch always has headroom (#4343 P1b). platform_settings
        'dispatch:node_cap:batch_reserve' (default 1 when unset). Instance-cached ~60s.
        Fail-SAFE 0 on any error or non-integer/garbage value — reserve 0 means no lane
        carve-out, which can NEVER starve batch (callers also floor the effective cap at 1).
        Negative values clamp to 0. Always gated by the _node_cap_enabled() kill-switch."""
        try:
            now = time.time()
            if getattr(self, "_node_reserve_time", 0) and (now - self._node_reserve_time) < 60:
                return self._node_reserve_val
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'dispatch:node_cap:batch_reserve'")
            row = cur.fetchone()
            conn.close()
            raw = str(row[0]).strip() if row and row[0] is not None else ""
            val = int(raw) if raw else 1
            if val < 0:
                val = 0
            self._node_reserve_val = val
            self._node_reserve_time = now
            return val
        except Exception:
            return 0

    def _aux_focus_reserve(self, module_id) -> int:
        """#6081 AUX POWER phase 2: extra streams held back from NON-family batch
        work while a platform focus is active. Returns 0 when no focus is set,
        when THIS dispatch is family work or keep-warm infrastructure (via the
        PURE fleet_dispatch_profile.aux_reserve_applies), or on any error.

        Size is tunable via platform_settings 'dispatch:node_cap:aux_reserve'
        (default 1; set 0 to kill-switch phase 2's reserve without touching the
        focus itself). Mode/focus reads are instance-cached ~60s like
        _node_cap_reserve — this sits on the dispatch hot path.
        """
        try:
            import time as _time

            now = _time.time()
            if getattr(self, "_aux_reserve_time", 0) and (now - self._aux_reserve_time) < 60:
                mode, focus, size = self._aux_reserve_state
            else:
                from services.fleet_dispatch_profile import get_dispatch_focus, get_dispatch_mode

                mode, focus = get_dispatch_mode(), get_dispatch_focus()
                size = 1
                try:
                    conn = self._get_db()
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM platform_settings WHERE key = 'dispatch:node_cap:aux_reserve'")
                    row = cur.fetchone()
                    conn.close()
                    if row and str(row[0]).strip().lstrip("-").isdigit():
                        size = max(0, int(str(row[0]).strip()))
                except Exception:
                    size = 1
                self._aux_reserve_state = (mode, focus, size)
                self._aux_reserve_time = now
            if size <= 0:
                return 0
            from services.fleet_dispatch_profile import aux_reserve_applies

            return size if aux_reserve_applies(module_id, mode, focus) else 0
        except Exception:
            return 0

    def _node_inflight_count(self, node_db_id) -> int:
        """Live running-job count for a node (#4343) — bridge_jobs status='running',
        resolving BOTH metadata node_id forms (varchar node_id AND int DB id). 20-min
        bound ignores zombie 'running' rows. Fail-open 0 on any error (hot path)."""
        try:
            nid = int(node_db_id)
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """SELECT COUNT(*) FROM bridge_jobs bj
                   WHERE bj.status = 'running'
                     AND bj.created_at > NOW() - INTERVAL '20 minutes'
                     AND ( bj.metadata->>'node_id' = (SELECT node_id FROM remote_nodes WHERE id = %s)
                        OR bj.metadata->>'node_id' = %s::text )""",
                (nid, nid),
            )
            row = cur.fetchone()
            conn.close()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def _node_at_cap(self, node_db_id, reserve: int = 0) -> bool:
        """True only when a divertable FLEET node is at/over its (lane-adjusted) concurrency
        cap (#4343 P1c + P1b lane reserve).

        ONE round-trip for a SINGLE node — NOT a per-node loop. Called at most twice per
        dispatch (the Node-preference + score-routing branches, sequentially) and only when
        _node_cap_enabled() (instance-cached ~60s), so the added cost is one indexed COUNT.
        Counts LIVE running jobs (bridge_jobs status='running', 20-min bound), resolving
        BOTH metadata->>'node_id' forms (varchar node_id OR int id::text), vs the effective
        cap = max(rn.max_concurrent - reserve, 1). P1b: BATCH dispatches pass reserve>=1
        (held to max_concurrent-1, leaving an INTERACTIVE stream free); INTERACTIVE passes
        reserve=0 (full cap). The clamp is AFTER subtraction, so a 1-stream node never drops
        to 0 (batch and interactive then share the single stream — no carve-out possible).
        The hub (rn.bridge_priority >= 100) is EXCLUDED by the WHERE clause -> returns False
        for it, so overflow never diverts off-hub and local_only/prefer_hub routing is
        unaffected. Fail-open (False) on any error or unknown node so a dispatch is never
        dropped. contextlib.closing releases the connection on every path including errors
        (fleet.md HARD RULE — a leaked conn on the error path is the DR pool-exhaustion mode)."""
        try:
            nid = int(node_db_id)
        except (TypeError, ValueError):
            return False
        try:
            from contextlib import closing

            with closing(self._get_db()) as conn:
                cur = conn.cursor()
                cur.execute(
                    """SELECT COUNT(bj.id) AS running, MAX(rn.max_concurrent) AS cap
                       FROM remote_nodes rn
                       LEFT JOIN bridge_jobs bj
                         ON bj.status = 'running'
                        AND bj.created_at > NOW() - INTERVAL '20 minutes'
                        AND ( bj.metadata->>'node_id' = rn.node_id
                           OR bj.metadata->>'node_id' = rn.id::text )
                       WHERE rn.id = %s AND rn.bridge_priority < 100""",
                    (nid,),
                )
                row = cur.fetchone()
            if not row or row[1] is None:
                return False
            running = int(row[0] or 0)
            cap = max(int(row[1]) - int(reserve), 1)
            return running >= cap
        except Exception:
            return False

    def _find_fleet_agent_for_hub_agent(
        self,
        hub_agent_id: int,
        prefer_hub: bool = False,
        department: Optional[str] = None,
        reserve: int = 0,
    ) -> Optional[Dict]:
        """Check if a hub agent is stationed on an online fleet node.

        Dispatch profiles (fleet_dispatch_mode in system_config):
          auto     — fleet-first: Starship-246 (50) > outpost-us (30) > hub (100)
          news     — News & Media → outpost-us first; other depts → Starship first
          platform — platform agents → Starship only; News & Media → outpost/hub only
          prefer_hub=True always routes to hub (local_only dispatches).
        """
        try:
            from psycopg2.extras import RealDictCursor

            mode = "hub" if prefer_hub else self._get_fleet_dispatch_mode()
            is_news = "News" in str(department or "")

            # Node eligibility: platform mode restricts departments to specific nodes
            if mode == "platform":
                if is_news:
                    node_filter = "AND rn.bridge_priority IN (30, 100)"  # outpost or hub
                else:
                    node_filter = "AND rn.bridge_priority IN (50, 100)"  # Starship or hub
            else:
                node_filter = ""

            # ORDER BY — built from controlled values (not user input), no SQL injection risk
            # load_5m.task_count added as secondary sort: least-loaded node wins among ties.
            # #4343 per-node cap: prepend a saturation-DEMOTION term (gated + kill-switchable)
            # so a node at/over its (lane-adjusted) cap of LIVE running jobs sorts LAST among
            # fleet candidates. No-op when unsaturated (every node scores 0 -> byte-identical
            # ordering) or when the flag is off (cap_term=""). DEMOTION, not a hard filter:
            # LIMIT 1 still returns the least-over-cap node, so a dispatch is never dropped.
            # P1b: `reserve` (int, controlled) lowers the threshold for BATCH so a batch
            # dispatch demotes a node one stream sooner, matching the hard _node_at_cap skip;
            # int() cast preserves the no-injection invariant. GREATEST(...,1) clamps AFTER
            # subtraction so a 1-stream node never goes to 0.
            cap_term = (
                f"(CASE WHEN COALESCE(inflight.running, 0) >= GREATEST(rn.max_concurrent - {int(reserve)}, 1)"
                " THEN 1 ELSE 0 END) ASC, "
                if self._node_cap_enabled()
                else ""
            )
            if mode == "hub":
                order_by = "(100 - rn.bridge_priority) ASC, rn.last_heartbeat DESC"
            elif mode == "news" and is_news:
                # News agents in news mode: prefer outpost-us (30 sorts first ASC).
                # Capacity-weighted load (see the else branch) balances by tasks-per-stream.
                order_by = (
                    cap_term + "rn.bridge_priority ASC,"
                    " (COALESCE(load_5m.task_count, 0)::float / GREATEST(rn.max_concurrent, 1)) ASC,"
                    " rn.last_heartbeat DESC"
                )
            else:
                # auto + platform (non-news): fleet first, then CAPACITY-WEIGHTED least-loaded,
                # then priority. (2026-06-13 cluster-saturation fix.) The tiebreak among GPU fleet
                # nodes was raw 5-min task COUNT, which handed the weak 1-stream RTX 3050
                # (Starship-245) the SAME task count as the strong 3-stream RTX 3070 (Starship-246)
                # -> 245 saturated (~76% busy) while 246 idled (~19%), and overflow spilled to the
                # slow hub CPU. Dividing the load by rn.max_concurrent balances by tasks-per-stream,
                # so a 3-stream node absorbs ~3x a 1-stream node before they tie. Requires
                # remote_nodes.max_concurrent to reflect true per-node Ollama NUM_PARALLEL.
                order_by = (
                    cap_term + "CASE WHEN rn.bridge_priority < 100 THEN 0 ELSE 1 END ASC,"
                    " (COALESCE(load_5m.task_count, 0)::float / GREATEST(rn.max_concurrent, 1)) ASC,"
                    " rn.bridge_priority DESC, rn.last_heartbeat DESC"
                )

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                f"""
                SELECT na.model,
                       COALESCE(na.display_name, a.display_name, a.name) AS display_name,
                       rn.id as node_id, rn.node_name,
                       rn.hostname, rn.port, rn.vpn_ip, rn.mesh_ip,
                       rn.bridge_priority,
                       COALESCE(load_5m.task_count, 0) AS recent_load
                FROM node_agents na
                JOIN remote_nodes rn ON rn.id = na.node_id
                LEFT JOIN agents a ON a.id = na.hub_agent_id
                LEFT JOIN (
                    SELECT node_used_id, COUNT(*) AS task_count
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '5 minutes'
                      AND node_used_id IS NOT NULL
                    GROUP BY node_used_id
                ) AS load_5m ON load_5m.node_used_id = rn.id
                LEFT JOIN (
                    -- #4343 per-node cap: live running-job count per node (authoritative,
                    -- real-time). Resolve BOTH bridge_jobs.metadata->>'node_id' forms
                    -- (varchar node_id AND int DB id); 20-min bound ignores zombie rows.
                    SELECT rn2.id AS node_id, COUNT(bj.id) AS running
                    FROM remote_nodes rn2
                    JOIN bridge_jobs bj
                      ON bj.status = 'running'
                     AND bj.created_at > NOW() - INTERVAL '20 minutes'
                     AND (bj.metadata->>'node_id' = rn2.node_id OR bj.metadata->>'node_id' = rn2.id::text)
                    GROUP BY rn2.id
                ) AS inflight ON inflight.node_id = rn.id
                WHERE na.hub_agent_id = %s
                  AND na.status = 'active'
                  AND rn.status = 'online'
                  AND rn.approval_status = 'approved'
                  AND rn.last_heartbeat > NOW() - INTERVAL '2 minutes'
                  AND (
                      na.model IS NULL
                      OR rn.extra_capabilities IS NULL
                      OR rn.extra_capabilities->'ollama_models' IS NULL
                      OR na.model = ANY(
                          SELECT jsonb_array_elements_text(
                              rn.extra_capabilities->'ollama_models'
                          )
                      )
                  )
                  -- GPU-aware default routing (#3621): a node WITHOUT a GPU may
                  -- only serve small (<4B) / embedding models. 7B+ models on CPU
                  -- nodes are excluded here so they fall through to a GPU fleet
                  -- node or the hub instead of running slowly on CPU outposts.
                  AND (
                      COALESCE(rn.gpu_available, false) = true
                      OR na.model IS NULL
                      OR na.model ~ '(:0.5b|:1b|:1.5b|:2b|:3b|embed)'
                  )
                  {node_filter}
                ORDER BY {order_by}
                LIMIT 1
                """,
                (hub_agent_id,),
            )
            row = cur.fetchone()
            conn.close()
            if not row:
                return None

            agent_name = row["display_name"] or f"fleet-agent-{hub_agent_id}"
            model = row["model"] or "qwen2.5:7b"
            # Canonical mesh transport first (matches _find_fleet_agent). vpn_ip is
            # empty for outpost nodes, so the old `vpn_ip or hostname` fell back to
            # hostname = the PUBLIC IP, where Ollama:11434 is firewalled → dispatch
            # timed out → C.O.D.E.X. documentation (and any outpost-stationed hub
            # agent) tasks blocked. mesh_ip (100.64.0.x) is always reachable. (2026-05-29)
            hostname = row["mesh_ip"] or row["vpn_ip"] or row["hostname"] or ""
            port = row["port"] or 11434

            if not hostname:
                return None

            return {
                "agent_name": agent_name,
                "model": model,
                "node_hostname": hostname,
                "node_port": port,
                "node_id": row["node_id"],
                "node_name": row["node_name"],
                "conn_type": "lan",
            }
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Node assignment lookup failed for agent {hub_agent_id}: {e}")
            return None

    def _get_fleet_node_for_dispatch(self, node_db_id: int, model: str, agent: Optional[Dict]) -> Optional[Dict]:
        """Build an agent_info dict for _dispatch_to_node() from a remote_nodes integer id.

        Uses mesh_ip as the transport host (canonical cluster architecture —
        never public hostnames). Returns None if node is offline or unreachable.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT node_id, node_name, mesh_ip, hostname, port, status, deployment_mode
                FROM remote_nodes
                WHERE id = %s
                  AND status = 'online'
                  -- Defense-in-depth: never build dispatch-info for an ingress /
                  -- no-Ollama node (e.g. Beacon, ollama_available=f) — dispatching
                  -- there ConnectionErrors. Returns None → caller falls through to
                  -- hub/next candidate. COALESCE → NULL treated as available (#4272).
                  AND COALESCE(ollama_available, TRUE) = TRUE
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                """,
                (node_db_id,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return None
            # #5332: UNDOCKED = leave the ships alone. This is the chokepoint every
            # node-targeted dispatch (incl. preferred_node pins) builds its transport
            # info through — an undocked Starship answers None here, so the caller
            # falls through to the hub/next candidate exactly like an offline node.
            if row.get("deployment_mode") == "starship":
                try:
                    from tools.department_hq.fleet_helpers import is_starships_undocked

                    if is_starships_undocked():
                        logger.info(
                            "[BridgeDispatcher] node %s is UNDOCKED — pinned dispatch falls through (#5332)",
                            row.get("node_name"),
                        )
                        return None
                except Exception:
                    pass  # fail-open: predicate errors must not un-route the fleet
            # Prefer mesh_ip — canonical inter-cluster transport (ADR mesh mandate)
            host = row.get("mesh_ip") or row.get("hostname") or ""
            if not host:
                return None
            agent_name = (agent.get("name") if agent else None) or "hub_agent"
            return {
                "agent_name": agent_name,
                "model": model,
                "node_hostname": host,
                "node_port": row.get("port") or 11434,
                "node_id": row["node_id"],
                "node_name": row["node_name"],
                "conn_type": "mesh",
            }
        except Exception as exc:
            logger.debug("[BridgeDispatcher] _get_fleet_node_for_dispatch failed: %s", exc)
            return None

    def _dispatch_to_node(
        self,
        agent_info: Dict,
        prompt: str,
        system_prompt: Optional[str] = None,
        options: Optional[Dict] = None,
        capability: str = "unknown",
        module_id: str = "unknown",
        station_code: str = "UNKNOWN",
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
        json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
        timeout: int = 240,
    ) -> Optional[Dict]:
        """Dispatch a job to a fleet node's Ollama API.

        Creates a bridge_job for tracking, calls the remote Ollama,
        returns dict with response text and metadata, or None on failure.
        """
        hostname = agent_info["node_hostname"]
        port = agent_info["node_port"] or 11434
        model = agent_info["model"]
        agent_name = agent_info["agent_name"]
        node_id = agent_info["node_id"]
        node_name = agent_info.get("node_name", "unknown")

        # Resource-aware routing precheck (#2516 Phase 2 / ADR-555).
        # Off by default — logs only. Flip FLEET_RESOURCE_ROUTING_ENABLED=true
        # to make capacity mismatches refuse dispatch (caller falls through to
        # the next escalation tier).
        try:
            enforce = os.getenv("FLEET_RESOURCE_ROUTING_ENABLED", "false").lower() == "true"
            from services.fleet_resource_router import should_dispatch_to_node
            from psycopg2.extras import RealDictCursor

            node_row = None
            _conn = None
            _cur = None
            try:
                _conn = self._get_db()
                _cur = _conn.cursor(cursor_factory=RealDictCursor)
                # agent_info["node_id"] may be the INTEGER remote_nodes.id OR the
                # string node_id. Match the correct column — comparing the varchar
                # node_id column to an int forces a cast that ERRORS, aborts the txn,
                # and (because the close() below used to run only on success) leaked
                # the connection in 'idle in transaction (aborted)' state. Enough of
                # those exhaust the pool and pin the hub → fleet heartbeats time out
                # (observed 2026-06-05 once the fleet came back online).
                if isinstance(node_id, int) or (isinstance(node_id, str) and node_id.isdigit()):
                    _where, _param = "id = %s", int(node_id)
                else:
                    _where, _param = "node_id = %s", node_id
                _cur.execute(
                    "SELECT node_id, node_name, gpu_available, gpu_vram_gb, ram_gb, "
                    "current_load, max_concurrent, priority, last_heartbeat, "
                    "extra_capabilities FROM remote_nodes WHERE " + _where,
                    (_param,),
                )
                node_row = _cur.fetchone()
            except Exception as fetch_err:
                logger.debug(f"[BridgeDispatcher] capacity row fetch failed: {fetch_err}")
                try:
                    if _conn is not None:
                        _conn.rollback()
                except Exception:
                    pass
            finally:
                # ALWAYS release the cursor + connection, even on error — otherwise an
                # aborted txn leaks the connection and exhausts the pool.
                try:
                    if _cur is not None:
                        _cur.close()
                except Exception:
                    pass
                try:
                    if _conn is not None:
                        _conn.close()
                except Exception:
                    pass

            if node_row:
                allowed, reason = should_dispatch_to_node(dict(node_row), model, enforce)
                if not allowed:
                    logger.warning(f"[BridgeDispatcher] Refusing fleet dispatch (flag enforced): {reason}")
                    return None
                if "capacity-mismatch" in reason:
                    # HARD capacity mismatch — score_node_for_model returned None because
                    # the model's memory footprint exceeds this node's RAM/declared
                    # ceiling, so the dispatch is GUARANTEED to time out (this is the
                    # outpost-boston 7B-on-CPU failure: ~90 guaranteed-fail jobs/hour).
                    # Refuse regardless of the soft-warn flag and let the caller escalate
                    # to a capable tier (hub/Starship). A capable node always exists for
                    # any model we run, so this never strands work; at worst a node with
                    # a mis-reported ram_gb is skipped and the job escalates to the hub.
                    logger.warning(f"[BridgeDispatcher] Refusing fleet dispatch — capacity mismatch: {reason}")
                    return None
                logger.debug(f"[BridgeDispatcher] Capacity check: {reason}")
        except Exception as cap_err:
            # Fail-open: capacity precheck must never block real dispatch.
            logger.debug(f"[BridgeDispatcher] Capacity precheck skipped: {cap_err}")

        # Circuit-breaker (covers dispatch paths that bypass _find_fleet_agent's
        # selection skip): refuse a node that's failing with no recent success and
        # escalate. A throttled probe is let through to detect recovery.
        if _node_circuit_open(node_id):
            logger.warning(
                f"[BridgeDispatcher] Circuit-breaker OPEN for {node_name} (node_id={node_id}) "
                f"— refusing fleet dispatch, escalating to a healthy tier"
            )
            return None

        # Create bridge_job for tracking
        bridge_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES (%s, %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    capability,
                    module_id,
                    f"Fleet dispatch to {node_name}: {prompt[:80]}",
                    agent_name,
                    station_code,
                    json.dumps(
                        {
                            "node_id": node_id,
                            "node_name": node_name,
                            "node_hostname": hostname,
                            "is_remote": True,
                            "capability": capability,
                        }
                    ),
                ),
            )
            bridge_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as job_err:
            logger.warning(f"[BridgeDispatcher] Failed to create fleet bridge_job: {job_err} — aborting fleet dispatch")
            return None

        # Call the node's Ollama API directly via mesh_ip — no local warm-boot
        # check; Ollama loads models on-demand and the timeout covers cold load.
        try:
            # keep_alive is node-aware (2026-05-30): GPU fleet nodes (Starships,
            # 4-8 GB VRAM) can only hold one 7B at a time, so pinning it 30m
            # starves the GPU for any other work — keep them warm only 5m so the
            # GPU frees up between bursts. CPU outposts have no VRAM pressure, so
            # keep their small models warm 30m (cheap to hold, avoids reloads).
            # locals().get guards the case where node_row was never assigned.
            _nr = locals().get("node_row")
            if _nr and _nr.get("gpu_available"):
                # GPU fleet node (Starship): demand-aware (#3532 v1). Record this
                # dispatch, prune to the window, and keep the 7B warm 30m if a
                # burst of agents is hitting this node+model, else 5m to free the
                # constrained GPU. Miscount-tolerant (no lock) — heuristic only.
                _now = time.time()
                _key = (node_id, model)
                _hist = [_t for _t in _NODE_MODEL_DISPATCH_TS.get(_key, []) if _now - _t < _DISPATCH_BURST_WINDOW_SEC]
                _hist.append(_now)
                _NODE_MODEL_DISPATCH_TS[_key] = _hist
                _node_keep_alive = "30m" if len(_hist) >= _DISPATCH_BURST_THRESHOLD else "5m"
            else:
                _node_keep_alive = "30m"
            _dispatch_t0 = time.time()  # honest duration for the #5700 failure row
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": _node_keep_alive,
            }
            if system_prompt:
                payload["system"] = system_prompt
            if options:
                payload["options"] = options
            if json_mode:
                # #5709: without this, a json_mode dispatch that lands on the fleet
                # tier silently degrades to free-text — the node model returns prose
                # and every downstream parser fails. The hub path sets format=json;
                # the fleet leg must match.
                #
                # json_mode carries EITHER True (bare JSON) or a JSON SCHEMA dict.
                # A dict is truthy, so it rides every existing `if json_mode:` and
                # pass-through unchanged; only this leaf reads its value.
                payload["format"] = json_mode if isinstance(json_mode, dict) else "json"

            # Use the fleet node's mesh_ip:port directly (canonical mesh transport).
            # Never use _node_url / build_options here — those resolve to hub Ollama.
            _gen_url = f"http://{hostname}:{port}/api/generate"
            logger.info(
                "[BridgeDispatcher] Fleet dispatch → %s (%s) agent=%s model=%s",
                node_name,
                _gen_url,
                agent_name,
                model,
            )
            # #5810: honor the CALLER's budget instead of a hardcoded 240. request_work
            # resolves a per-capability timeout (CAPABILITY_TIMEOUTS, up to 600s) and that
            # value used to die here — every fleet dispatch of every capability was capped
            # at 240s, silently defeating the 600s granted to documentation/translate/
            # research/code_analysis etc., which CAPABILITY_NODE_AFFINITY (#3955) routes to
            # the fleet ON PURPOSE. Callers floor this at 240 so cold-load headroom (the
            # reason 240 replaced the original 15s, KB #266396) is never reduced.
            _node_call_start = time.time()
            resp = requests.post(
                _gen_url,
                json=payload,
                timeout=timeout,
            )
            _node_call_ms = int((time.time() - _node_call_start) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                response_text = data.get("response", "")

                # Mark bridge_job complete
                if bridge_job_id:
                    try:
                        conn = self._get_db()
                        cur = conn.cursor()
                        cur.execute(
                            """
                            UPDATE bridge_jobs
                            SET status = 'completed',
                                completed_steps = 1,
                                completed_at = NOW()
                            WHERE id = %s
                            """,
                            (bridge_job_id,),
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                    except Exception as _exc:
                        pass

                logger.info(
                    f"[BridgeDispatcher] Fleet dispatch success: "
                    f"{agent_name}@{node_name} returned "
                    f"{len(response_text)} chars"
                )
                _node_record_result(node_id, True)  # closes the circuit-breaker for this node

                return {
                    "success": True,
                    "response": response_text,
                    "agent_name": agent_name,
                    "model": model,
                    "node_id": node_id,
                    "node_name": node_name,
                    "bridge_job_id": bridge_job_id,
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    # #5810: the HTTP call alone. DispatchResult.duration_ms is measured from
                    # the top of request_work, so it also covers agent selection, welfare
                    # checks, cold-load and every prior failed ladder attempt — which is why
                    # rows show 300-540s "successes" against a 240s cap. Keep duration_ms as
                    # is (carbon/token-economy consume it); expose the real call time here.
                    "node_call_ms": _node_call_ms,
                }
            else:
                # HTTP error from the node. Previously this `return None` skipped the
                # failure UPDATE below, leaving the bridge_job stuck 'running' until the
                # stale-reaper closed it with a NULL error_message. Now we capture the
                # reason and fall through to mark it failed immediately.
                _err = f"HTTP {resp.status_code} from {node_name} ({hostname}:{port}): {resp.text[:500]}"
                logger.warning(f"[BridgeDispatcher] Fleet node {hostname}:{port} returned {_err}")

        except requests.exceptions.Timeout:
            # Timeout also used to leak to the reaper. Capture it — a persistent timeout
            # usually means the node cannot actually run this model (e.g. a 7B routed to
            # a CPU outpost) or is cold-loading past the window.
            # #5810: report the ACTUAL budget. These strings hardcoded "240s", which is now
            # per-capability — a stale literal here would send the next investigation looking
            # for a 240s cap that no longer applies.
            _err = (
                f"timeout after {timeout}s — {node_name} ({hostname}:{port}) did not return for model={model} "
                f"(likely cannot run this model, or cold-load exceeded the window)"
            )
            logger.warning(f"[BridgeDispatcher] Fleet dispatch timeout ({timeout}s) to {hostname}:{port} model={model}")
        except Exception as e:
            _err = f"{type(e).__name__}: {str(e)[:500]}"
            logger.warning(f"[BridgeDispatcher] Fleet dispatch failed: {e}")

        # Feed the circuit-breaker: this node just failed a dispatch.
        _node_record_result(node_id, False)

        # Mark bridge_job failed WITH the captured reason, so fleet failures are
        # debuggable in bridge_jobs.error_message instead of surfacing as NULL-error
        # reaped rows. Reached by the HTTP-error, timeout, and exception paths above.
        if bridge_job_id:
            _reason = (locals().get("_err") or "fleet dispatch failed (no detail captured)")[:1000]
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = %s
                    WHERE id = %s
                    """,
                    (_reason, bridge_job_id),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as _exc:
                pass

        # #5700: write the NODE-ATTRIBUTED failure row. Without this, a fleet
        # timeout produced NO task_execution_log row at all (the caller falls
        # through to the next tier and only the eventual outcome is logged), so
        # per-node success rates showed ~100% while real failure was ~9% —
        # Starship-246's timeouts were structurally invisible to A.R.M.A.D.A.
        # agent_id stays NULL deliberately: a node timeout is INFRA fault, not
        # agent work — same unattributed precedent as warm-up rows, so K.I.N.
        # welfare/budget accounting (keyed on agent_id) is never charged for a
        # node's failure. agent_name is kept as an informational marker.
        try:
            _fail_reason = (locals().get("_err") or "fleet dispatch failed (no detail captured)")[:1000]
            _dur_ms = int((time.time() - locals().get("_dispatch_t0", time.time())) * 1000)
            _node_pk = None
            try:
                _node_pk = int(node_id)
            except (TypeError, ValueError):
                pass
            conn = self._get_db()
            cur = conn.cursor()
            if _node_pk is None and node_id:
                cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s LIMIT 1", (str(node_id),))
                _pkr = cur.fetchone()
                _node_pk = int(_pkr[0]) if _pkr else None
            cur.execute(
                """
                INSERT INTO task_execution_log (
                    agent_id, agent_name, module_source, task_type, capability,
                    model_used, provider, prompt_tokens, completion_tokens,
                    tokens_used, duration_ms, success, error_message,
                    station_code, requested_by, priority, request_metadata,
                    job_id, worker_type, node_used_id
                ) VALUES (
                    NULL, %s, %s, %s, %s,
                    %s, 'ollama', 0, 0,
                    0, %s, FALSE, %s,
                    %s, %s, 'normal', %s,
                    %s, 'internal', %s
                )
                """,
                (
                    agent_name,
                    (module_id if module_id and module_id != "unknown" else capability),
                    capability,
                    capability,
                    model,
                    _dur_ms,
                    _fail_reason,
                    station_code,
                    user_id,
                    json.dumps(
                        {
                            "node_name": node_name,
                            "node_host": f"{hostname}:{port}",
                            "phase": "fleet_dispatch_failure",
                        }
                    ),
                    job_id,
                    _node_pk,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as _exc:
            logger.debug("[BridgeDispatcher] fleet failure-row logging skipped: %s", _exc)

        return None

    # ================================================================
    # Image Generation Escalation (Project #164)
    # 4-tier: Node ComfyUI → Hub ComfyUI → Free Cloud → Paid Cloud
    # ================================================================

    def _select_comfyui_host(self) -> tuple:
        """Find the best available ComfyUI host.

        Returns (comfyui_url, node_db_id) or (None, None) if all busy.
        Priority: fleet nodes (faster GPUs) → hub (fallback).
        """
        # Check fleet nodes first
        try:
            from ai_bridge.node_router import select_best_image_node

            node_info = select_best_image_node("comfyui")
            if node_info:
                node_hostname = node_info.get("hostname") or node_info.get("vpn_ip") or node_info.get("node_name")
                node_port = node_info.get("port", 8188)
                node_db_id = node_info.get("id")
                if not self._is_image_host_busy(node_hostname):
                    url = f"http://{node_hostname}:{node_port}"
                    logger.info(
                        "[ImageEscalation] Node ComfyUI available: %s (id=%s)",
                        url,
                        node_db_id,
                    )
                    return url, node_db_id
                logger.info("[ImageEscalation] Node ComfyUI busy, trying hub")
        except Exception as e:
            logger.warning("[ImageEscalation] Node router check failed: %s", e)

        # Fall back to hub ComfyUI
        hub_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
        if not self._is_image_host_busy("hub"):
            from ai_bridge.comfyui_service import ComfyUIService

            hub_svc = ComfyUIService(host=hub_host)

            if hub_svc.health_check():
                logger.info("[ImageEscalation] Hub ComfyUI available: %s", hub_host)
                return hub_host, None

            if hub_svc.is_stopped():
                logger.info("[ImageEscalation] Hub ComfyUI stopped — firing async wake, deferring to queue")
                hub_svc.wake_if_stopped_async()
                return "waking", None

            logger.info("[ImageEscalation] Hub ComfyUI unreachable (not stopped, not healthy)")

        logger.info("[ImageEscalation] All local ComfyUI hosts busy")
        return None, None

    # Hardware-aware model tiers for ComfyUI checkpoints
    _COMFYUI_MODEL_TIERS = [
        # (min_vram_gb, model_name, resolution, description)
        (12, "flux1-dev-fp8.safetensors", 1024, "Flux.1 Dev FP8"),
        (8, "sd_xl_base_1.0.safetensors", 1024, "Stable Diffusion XL"),
        (4, "v1-5-pruned-emaonly.ckpt", 512, "Stable Diffusion 1.5"),
        (2, "v1-5-pruned-emaonly.ckpt", 512, "Stable Diffusion 1.5 (low VRAM)"),
    ]

    def _select_best_model_for_node(self, node_info: Optional[Dict], available_models: Optional[list] = None) -> tuple:
        """Select the best image model based on node hardware and available models.

        Returns (model_name, width, height) tuple.
        Falls back to SD 1.5 if nothing better is available.
        """
        vram = 8.0  # default hub VRAM
        if node_info:
            vram = float(node_info.get("gpu_vram_gb", 0) or 8)

        # If we know what models are installed, pick the best that fits
        if available_models:
            model_names = {m.get("name", m) if isinstance(m, dict) else m for m in available_models}
            for min_vram, model, res, desc in self._COMFYUI_MODEL_TIERS:
                if vram >= min_vram and model in model_names:
                    logger.info(
                        "[ImageEscalation] Selected %s (%s) for %.1fGB VRAM",
                        model,
                        desc,
                        vram,
                    )
                    return model, res, res

        # No model list available — pick by VRAM tier
        for min_vram, model, res, desc in self._COMFYUI_MODEL_TIERS:
            if vram >= min_vram:
                logger.info(
                    "[ImageEscalation] Tier-based selection: %s (%s) for %.1fGB VRAM",
                    model,
                    desc,
                    vram,
                )
                return model, res, res

        return "v1-5-pruned-emaonly.ckpt", 512, 512

    def _get_node_comfyui_models(self, node_db_id: Optional[int], comfyui_host: Optional[str] = None) -> list:
        """Get list of ComfyUI checkpoint models available on a node/hub.

        Queries the ComfyUI instance directly for its installed checkpoints.
        """
        try:
            from ai_bridge.comfyui_service import ComfyUIService

            host = comfyui_host or os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
            svc = ComfyUIService(host=host)
            models = svc.get_models()
            return models.get("installed", [])
        except Exception as e:
            logger.debug("[ImageEscalation] Failed to get ComfyUI models: %s", e)
            return []

    def _is_image_host_busy(self, target_host: str) -> bool:
        """Check bridge_jobs metadata for running image_generation jobs on a host."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*) FROM bridge_jobs
                WHERE job_type = 'image_generation'
                  AND status = 'running'
                  AND metadata->>'target_host' = %s
                """,
                (target_host,),
            )
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return count > 0
        except Exception:
            return False

    # Minimum seconds a host must be continuously busy before cloud escalation fires.
    ESCALATION_GRACE_SECONDS = 60

    def _get_hub_busy_duration(self) -> float:
        """Return how many seconds the hub ComfyUI has been continuously busy.

        Looks at the oldest running image_generation bridge_job on the hub.
        Returns 0 if no running job is found (treat as not busy).
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at)))
                FROM bridge_jobs
                WHERE job_type = 'image_generation'
                  AND status = 'running'
                  AND metadata->>'target_host' = 'hub'
                """,
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return float(row[0]) if row and row[0] is not None else 0.0
        except Exception:
            return 0.0

    def _escalate_image_to_cloud(
        self,
        agent_name: str,
        agent: Dict,
        prompt: str,
        context: Dict,
        station_code: str,
        capability: str,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ) -> "DispatchResult":
        """Escalate image gen to cloud: free contractors (Tier 1), then paid (Tier 2).

        Free cloud providers auto-execute. Paid providers require async
        Telegram approval via contractor_approval_requests.
        """
        agent_id = agent.get("id")

        # --- Tier 1: Free cloud contractors (auto-approve) ---
        try:
            from ai_bridge.external_providers import (
                generate_media,
                get_providers_with_capability,
            )

            free_providers = [
                p
                for p in get_providers_with_capability("image_gen")
                if p.get("tier_position", 99) <= 4 and p.get("provider_key") not in ("comfyui", "ollama_diffuser")
            ]
            for provider in free_providers:
                pkey = provider["provider_key"]
                logger.info("[ImageEscalation] Trying free cloud: %s", pkey)
                try:
                    result = generate_media(
                        pkey,
                        {
                            "type": "image",
                            "prompt": prompt,
                            "params": context.get("image_params", {}),
                        },
                    )
                    if result and result.get("success"):
                        # Log usage
                        self._log_cloud_image_usage(pkey, user_id, result.get("cost_usd", 0))
                        return DispatchResult(
                            success=True,
                            response=result.get("file_path", ""),
                            agent_name=agent_name,
                            agent_id=agent_id,
                            model_used=result.get("model", pkey),
                            station_code=station_code,
                            capability=capability,
                            provider=pkey,
                            metadata={
                                "file_path": result.get("file_path"),
                                "provider": pkey,
                                "escalation": "free_cloud",
                            },
                        )
                except Exception as e:
                    logger.warning("[ImageEscalation] Free cloud %s failed: %s", pkey, e)
        except ImportError:
            logger.warning("[ImageEscalation] external_providers not available")

        # --- Tier 2: Paid cloud contractors (async Telegram approval) ---
        logger.info("[ImageEscalation] All free options exhausted, submitting Tier 2 approval")

        # Create pending bridge_job
        pending_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('image_generation', %s, %s, 1, 'pending_approval', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Cloud image gen (pending approval): {prompt[:60]}",
                    agent_name,
                    station_code,
                    json.dumps(
                        {
                            "target_host": "cloud",
                            "prompt": prompt,
                            "escalation": "paid_cloud",
                            "user_id": user_id,
                            "image_params": context.get("image_params", {}),
                        }
                    ),
                ),
            )
            pending_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error("[ImageEscalation] Failed to create pending job: %s", e)

        # Submit async approval via Telegram
        try:
            from ai_bridge.agent_loop import request_approval

            request_approval(
                action_type="cloud_throughput_escalation",
                action_data={
                    "job_id": pending_job_id,
                    "prompt": prompt[:100],
                    "capability": "image_gen",
                },
                reason=("All local + free cloud image generators busy. " "Paid cloud image generation requested."),
                tier=2,
            )
        except Exception as e:
            logger.error("[ImageEscalation] Failed to submit approval: %s", e)

        return DispatchResult(
            success=False,
            response="Image generation queued — awaiting cloud approval via Telegram",
            agent_name=agent_name,
            agent_id=agent_id,
            model_used="pending",
            station_code=station_code,
            capability=capability,
            provider="cloud_pending",
            metadata={
                "escalation": "pending_approval",
                "job_id": pending_job_id,
            },
        )

    def _log_cloud_image_usage(self, provider: str, user_id: Optional[int], cost_usd: float):
        """Log cloud image generation to cloud_model_usage."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO cloud_model_usage
                    (model_name, provider, prompt_tokens, completion_tokens,
                     cost_usd, user_id, task_type, success)
                VALUES (%s, %s, 0, 0, %s, %s, 'image_generation', true)
                """,
                (f"{provider}_image", provider, cost_usd, user_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning("[ImageEscalation] Failed to log usage: %s", e)

    def _execute_comfyui(
        self,
        agent_name: str,
        agent: Dict,
        image_model: str,
        prompt: str,
        context: Dict,
        station_code: str,
        capability: str,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ) -> "DispatchResult":
        """Execute image generation with 4-tier escalation.

        1. Fleet node ComfyUI (fastest GPU) → free
        2. Hub ComfyUI (fallback) → free
        3. Free cloud contractors (HuggingFace, Cloudflare) → free
        4. Paid cloud contractors (DALL-E 3, Imagen 3) → Telegram approval

        Handles VRAM management, creates bridge_job for tracking, returns DispatchResult.
        """
        from ai_bridge.comfyui_service import ComfyUIService

        agent_id = agent.get("id")

        # --- Escalation: find best available ComfyUI host ---
        comfyui_host, node_db_id = self._select_comfyui_host()

        if comfyui_host in (None, "waking"):
            waking = comfyui_host == "waking"
            busy_seconds = self._get_hub_busy_duration()

            if waking or busy_seconds < self.ESCALATION_GRACE_SECONDS:
                reason = (
                    "ComfyUI is starting up (~90s)"
                    if waking
                    else f"ComfyUI busy for {busy_seconds:.0f}s (grace: {self.ESCALATION_GRACE_SECONDS}s)"
                )
                logger.info("[ImageEscalation] Deferring — %s", reason)
                try:
                    from services.telegram_service import send_info

                    queue_id = (context or {}).get("queue_id", "unknown")
                    send_info(
                        "Image Generation Queued",
                        f"A generation request (queue #{queue_id}) is waiting for local ComfyUI.\n"
                        f"Reason: {reason}\n"
                        f"No cloud escalation — job will retry automatically.",
                    )
                except Exception as tg_err:
                    logger.warning("[ImageEscalation] Telegram notify failed: %s", tg_err)
                return DispatchResult(
                    success=False,
                    response=f"Local ComfyUI unavailable — {reason}. Job queued for retry.",
                    error=reason,
                    agent_name=agent_name,
                    station_code=station_code,
                    capability=capability,
                    provider="comfyui_deferred",
                )

            # Genuinely busy beyond grace period — notify and defer, no auto-cloud escalation
            logger.info("[ImageEscalation] All local ComfyUI busy beyond grace — notifying operator")
            try:
                from services.telegram_service import send_info

                queue_id = (context or {}).get("queue_id", "unknown")
                send_info(
                    "Image Generation — Local Capacity Full",
                    f"Queue #{queue_id}: all local ComfyUI hosts have been busy for {busy_seconds:.0f}s.\n"
                    f"Job deferred. Reply 'approve image escalation #{queue_id}' to route to cloud.",
                )
            except Exception as tg_err:
                logger.warning("[ImageEscalation] Telegram notify failed: %s", tg_err)
            return DispatchResult(
                success=False,
                response=f"All local ComfyUI busy for {busy_seconds:.0f}s. Operator notified — awaiting approval for cloud.",
                error=f"ComfyUI busy {busy_seconds:.0f}s, cloud escalation requires operator approval",
                agent_name=agent_name,
                station_code=station_code,
                capability=capability,
                provider="comfyui_capacity_full",
            )

        # --- Instantiate ComfyUI service with selected host ---
        comfyui = ComfyUIService(host=comfyui_host)
        target_host = "hub" if node_db_id is None else (comfyui_host.replace("http://", "").split(":")[0])

        # --- Hardware-aware model selection ---
        # If caller specified a model, try it; otherwise auto-select best for hardware
        available_models = self._get_node_comfyui_models(node_db_id, comfyui_host)
        if not available_models or image_model not in [
            m.get("name", m) if isinstance(m, dict) else m for m in available_models
        ]:
            # Requested model not available — get node hardware info
            node_hw = None
            if node_db_id:
                try:
                    import psycopg2.extras

                    conn = self._get_db()
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute(
                        "SELECT gpu_vram_gb FROM remote_nodes WHERE id = %s",
                        (node_db_id,),
                    )
                    node_hw = cur.fetchone()
                    cur.close()
                    conn.close()
                except Exception:
                    pass
            best_model, best_w, best_h = self._select_best_model_for_node(node_hw, available_models)
            if image_model not in [m.get("name", m) if isinstance(m, dict) else m for m in (available_models or [])]:
                logger.info(
                    "[ImageEscalation] Model %s not on %s, using %s instead",
                    image_model,
                    target_host,
                    best_model,
                )
                image_model = best_model
                # Adjust resolution for the model tier
                if not context.get("width"):
                    context["width"] = best_w
                if not context.get("height"):
                    context["height"] = best_h

        # --- Create bridge_job to mark agent busy ---
        bridge_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('image_generation', %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Image gen: {prompt[:80]}",
                    agent_name,
                    station_code,
                    json.dumps(
                        {
                            "image_model": image_model,
                            "provider": "comfyui",
                            "capability": capability,
                            "target_host": target_host,
                            "comfyui_host": comfyui_host,
                            "node_db_id": node_db_id,
                        }
                    ),
                ),
            )
            bridge_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            self._busy_agents.add(agent_name)
            logger.info(
                "[BridgeDispatcher] ComfyUI job #%s started: %s → %s (%s)",
                bridge_job_id,
                agent_name,
                target_host,
                image_model,
            )
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Failed to create bridge_job: {e}")

        # --- Ensure ComfyUI container is running (idle-stop may have stopped it) ---
        # Project #240 task #2019 — lifecycle policy parallel to Ollama keep_alive.
        try:
            from services.comfyui_lifecycle import ensure_running

            ensure_running()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] ComfyUI ensure_running failed: {e}")

        # --- VRAM swap: unload Ollama GPU models if SDXL needs full GPU ---
        ollama_models_unloaded = []
        is_xl = "xl" in image_model.lower()
        if is_xl:
            ollama_models_unloaded = self._vram_swap_for_comfyui(node_db_id)

        # --- Determine resolution ---
        width, height = (1024, 1024) if is_xl else (512, 512)
        width = context.get("width", width)
        height = context.get("height", height)
        steps = context.get("steps", 20)
        cfg = context.get("cfg", 7.0)

        # --- Generate image ---
        try:
            result = comfyui.generate_image(
                prompt=prompt,
                model=image_model,
                steps=steps,
                width=width,
                height=height,
                cfg=cfg,
            )
        except Exception as e:
            result = None
            logger.error(f"[BridgeDispatcher] ComfyUI generation error: {e}")

        # --- Reload Ollama GPU models after SDXL ---
        if ollama_models_unloaded:
            self._vram_restore_after_comfyui(ollama_models_unloaded, node_db_id)

        # --- Record ComfyUI use so the idle-stop job knows the container is active ---
        try:
            from services.comfyui_lifecycle import record_last_used

            record_last_used()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] ComfyUI record_last_used failed: {e}")

        # --- Complete bridge_job ---
        if bridge_job_id:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                success = result and result.success
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET status = %s, completed_steps = 1, completed_at = NOW()
                    WHERE id = %s
                    """,
                    ("completed" if success else "failed", bridge_job_id),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"[BridgeDispatcher] Failed to complete bridge_job: {e}")
            self._busy_agents.discard(agent_name)

        # --- Build DispatchResult ---
        if result and result.success:
            metadata = result.metadata or {}
            metadata["file_path"] = result.file_path
            metadata["bridge_job_id"] = bridge_job_id
            metadata["target_host"] = target_host
            if ollama_models_unloaded:
                metadata["vram_swap"] = ollama_models_unloaded

            # Bridge the dispatcher → media_generation_queue gap.
            # If the caller created a queue row (Media Studio submit_generation
            # does), persist the image to media_library + flip the queue status
            # to 'completed' so avatar_url / portrait flows finish. Idempotent;
            # logs its own errors. Root cause traced 2026-04-20 during #262.
            queue_id = (context or {}).get("queue_id")
            if queue_id and result.file_path:
                try:
                    from tools.media_studio.services.generation_service import (
                        on_generation_complete,
                    )

                    media_id = on_generation_complete(
                        queue_id=queue_id,
                        file_path=result.file_path,
                        seed=(context or {}).get("seed"),
                        duration_ms=None,
                        provider="comfyui",
                        node_id=node_db_id,
                    )
                    if media_id:
                        metadata["queue_id"] = queue_id
                        metadata["media_library_id"] = media_id
                except Exception as cb_err:
                    logger.error(
                        f"[BridgeDispatcher] on_generation_complete failed for " f"queue_id={queue_id}: {cb_err}"
                    )

            return DispatchResult(
                success=True,
                response=result.file_path,
                agent_name=agent_name,
                agent_id=agent_id,
                model_used=image_model,
                station_code=station_code,
                capability=capability,
                provider="comfyui",
                metadata=metadata,
            )
        else:
            error_msg = result.error if result else "ComfyUI service unreachable"
            # If local ComfyUI failed, try cloud escalation
            if not result or not result.success:
                logger.info(
                    "[ImageEscalation] Local ComfyUI on %s failed, trying cloud",
                    target_host,
                )
                cloud_result = self._escalate_image_to_cloud(
                    agent_name,
                    agent,
                    prompt,
                    context,
                    station_code,
                    capability,
                    module_id,
                    user_id,
                    job_id,
                )
                if cloud_result.success:
                    return cloud_result

            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent_id,
                model_used=image_model,
                station_code=station_code,
                capability=capability,
                provider="comfyui",
                error=error_msg,
                metadata={"bridge_job_id": bridge_job_id},
            )

    # ================================================================
    # RAG Auto-Context Injection (Task #1130)
    # ================================================================
    _rag_cache: Dict[str, Any] = {}  # {cache_key: {"ts": float, "context": str}}
    _RAG_CACHE_TTL = 300  # 5 minutes
    _RAG_MIN_RELEVANCE = 0.7
    _RAG_MAX_ENTRIES = 3
    # Agentic tool-use KB search (#3534 Phase 1) — flag-gated, scoped tight.
    # The agent issues its OWN search_knowledge calls mid-task instead of the
    # single-shot RAG. Hub-only (fleet agents return early before this branch).
    _AGENTIC_TOOL_CAPABILITIES = ("research", "knowledge_analysis")
    # Phase 1: D.A.R.W.I.N. (research). Phase 2 adds the Analytics & Intelligence
    # directors (knowledge_analysis, mistral:7b). All gated by is_tool_capable_model.
    _AGENTIC_TOOL_AGENTS = ("D.A.R.W.I.N.", "S.P.E.C.T.R.A.", "W.A.T.C.H.")

    # PR-D (#381): capability -> KB tags for role-relevant mistake injection. Generalizes the
    # code_review grounding to every tool/reasoning capability so each agent gets its own known
    # failure modes prepended. Capabilities not listed get no role injection (no-op, safe).
    _CAPABILITY_KB_TAGS = {
        "code_review": ["code_review", "false_positive"],
        "code": ["code", "code_review"],
        "debug": ["code", "debug"],
        "research": ["research"],
        "research_synthesis": ["research"],
        "knowledge_analysis": ["knowledge_analysis", "analysis"],
        "analyze": ["analysis"],
        "classify": ["analysis"],
        "documentation": ["documentation"],
        "module_audit": ["documentation", "audit"],
        "security": ["security", "compliance", "vulnerability"],
        "compliance": ["compliance", "security"],
        "translate": ["translation"],
    }
    _ROLE_MISTAKES_TTL = 600
    _ROLE_MISTAKES_MAX = 3

    def _is_auto_context_enabled(self) -> bool:
        """Check platform_settings for rag_auto_context flag."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'rag_auto_context'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0].lower() in ("true", "1", "enabled") if row else False
        except Exception:
            return False

    def _is_agentic_tool_search_enabled(self) -> bool:
        """Check platform_settings for the agentic_tool_search flag (#3534)."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'agentic_tool_search'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0].lower() in ("true", "1", "enabled") if row else False
        except Exception:
            return False

    def _is_agentic_tool_write_enabled(self) -> bool:
        """Check platform_settings for the agentic_tool_write flag (#3534 Phase 3).

        Distinct from the read flag — writes (quarantined agent KB proposals via
        the store_memory tool) are higher-risk, so they gate separately. Default OFF.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'agentic_tool_write'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0].lower() in ("true", "1", "enabled") if row else False
        except Exception:
            return False

    def _log_agentic_tool_calls(self, agent, capability, module_id, queries, user_id=None):
        """Log each agentic search_knowledge tool call to task_execution_log (#3534).

        One lightweight row per KB search the agent issued, so the agentic
        retrieval is visible in A.R.M.A.D.A. dispatch traffic. model_used is left
        NULL (a KB search is not a model inference) to avoid polluting per-model
        demand stats.
        """
        if not queries:
            return
        try:
            from database import get_db_cursor
            from psycopg2.extras import Json

            with get_db_cursor(commit=True) as (_c, cur):
                for inv in queries:
                    # Phase 2: each entry is {"tool": <name>, "query": <str>};
                    # tolerate Phase-1 bare-string entries for safety.
                    if isinstance(inv, dict):
                        tool_name = inv.get("tool") or "search_knowledge"
                        q = inv.get("query") or ""
                    else:
                        tool_name, q = "search_knowledge", (inv or "")
                    cur.execute(
                        """INSERT INTO task_execution_log
                               (agent_id, agent_name, module_source, task_type,
                                capability, success, request_origin, requested_by,
                                request_metadata, created_at)
                           VALUES (%s, %s, 'agentic_tool_search', 'tool_call',
                                   %s, TRUE, 'agentic', %s, %s, NOW())""",
                        (
                            agent.get("id") if agent else None,
                            agent.get("name") if agent else None,
                            tool_name,
                            user_id,
                            Json(
                                {
                                    "query": q[:500],
                                    "tool": tool_name,
                                    "parent_capability": capability,
                                    "module_id": module_id,
                                }
                            ),
                        ),
                    )
        except Exception as exc:
            logger.debug("[BridgeDispatcher] agentic tool-call logging skipped: %s", exc)

    def _get_rag_context(self, prompt: str) -> Optional[str]:
        """
        Retrieve relevant KB context for a prompt via semantic search.

        Returns a formatted context string to prepend, or None if no
        relevant results found. Results are cached for 5 minutes keyed
        on the first 200 chars of the prompt.
        """
        import hashlib

        cache_key = hashlib.md5(prompt[:200].encode()).hexdigest()
        now = time.time()

        # Check cache
        cached = self._rag_cache.get(cache_key)
        if cached and (now - cached["ts"]) < self._RAG_CACHE_TTL:
            return cached["context"]

        try:
            from ai_bridge.semantic_search import search as semantic_search

            results = semantic_search(prompt, limit=self._RAG_MAX_ENTRIES)
            if not results:
                self._rag_cache[cache_key] = {"ts": now, "context": None}
                return None

            # Filter by relevance threshold
            relevant = [r for r in results if r.score and r.score >= self._RAG_MIN_RELEVANCE]
            if not relevant:
                self._rag_cache[cache_key] = {"ts": now, "context": None}
                return None

            # Build context block
            parts = ["[Auto-Context from Knowledge Base]"]
            for r in relevant:
                title = r.title or f"KB#{r.id}"
                content = (r.content or "")[:800]
                parts.append(f"--- {title} (relevance: {r.score:.2f}) ---\n{content}")
            parts.append("[End Auto-Context]\n")

            context_str = "\n".join(parts)
            self._rag_cache[cache_key] = {"ts": now, "context": context_str}

            # Evict old cache entries (keep max 100)
            if len(self._rag_cache) > 100:
                oldest_keys = sorted(self._rag_cache, key=lambda k: self._rag_cache[k]["ts"])[:50]
                for k in oldest_keys:
                    self._rag_cache.pop(k, None)

            return context_str

        except Exception as e:
            logger.debug(f"[BridgeDispatcher] RAG context retrieval failed: {e}")
            self._rag_cache[cache_key] = {"ts": now, "context": None}
            return None

    def _is_role_grounding_enabled(self) -> bool:
        """PR-D (#381) flag: rag_role_grounding (default ON). Inject role-relevant mistakes per
        capability. Flip to false in platform_settings to revert instantly."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'rag_role_grounding'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0].lower() in ("true", "1", "enabled") if row else True
        except Exception:
            return False

    def _is_complexity_routing_enabled(self) -> bool:
        """P2-B (#381) flag: complexity_routing_enabled (default OFF — owner-gated rollout). When ON,
        trivial downgradeable capabilities run on a smaller model. Flip true in platform_settings.
        Uses the get_db_cursor context manager so the connection is always released (no leak)."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (_conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'complexity_routing_enabled'")
                row = cur.fetchone()
            if not row:
                return False
            val = row.get("value") if isinstance(row, dict) else row[0]
            return bool(val) and str(val).lower() in ("true", "1", "enabled")
        except Exception:
            return False

    def _get_role_mistakes(self, capability: Optional[str]) -> Optional[str]:
        """PR-D (#381): role-relevant ``mistake_learned`` entries for a capability, so EVERY tool
        agent is grounded with its known failure modes (not just code_review). Tag-targeted,
        excludes quarantined (review_status='pending'/'rejected') proposals, cached per-capability,
        fail-safe (any error -> no injection). Closes the PR-C false-positive writeback -> reinjection
        loop once C.O.D.E.X. promotes a flagged mistake out of quarantine."""
        if not capability:
            return None
        tags = self._CAPABILITY_KB_TAGS.get(capability)
        if not tags:
            return None
        cache = getattr(self, "_role_mistakes_cache", None)
        if cache is None:
            cache = self._role_mistakes_cache = {}
        now = time.time()
        hit = cache.get(capability)
        if hit and (now - hit["ts"]) < self._ROLE_MISTAKES_TTL:
            return hit["context"]
        ctx = None
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """SELECT title, content FROM knowledge_base
                   WHERE knowledge_type = 'mistake_learned'
                     AND tags && %s::text[]
                     AND COALESCE(review_status, 'approved') NOT IN ('pending', 'rejected')
                   ORDER BY importance_score DESC NULLS LAST, created_at DESC
                   LIMIT %s""",
                (list(tags), self._ROLE_MISTAKES_MAX),
            )
            rows = cur.fetchall()
            cur.close()
            if rows:
                parts = [f"[Known mistakes for {capability} — do NOT repeat these]"]
                for title, content in rows:
                    parts.append(f"- {title}: {(content or '')[:300]}")
                parts.append("[End known mistakes]\n")
                ctx = "\n".join(parts)
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] role-mistakes query failed: {e}")
            ctx = None
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
        cache[capability] = {"ts": now, "context": ctx}
        return ctx

    def _execute_llm(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
        prefer_gpu: bool = True,
        temperature: float = 0.5,
        timeout: int = 300,
        agent_name: Optional[str] = None,
        capability: Optional[str] = None,
        module_id: Optional[str] = None,
        images: Optional[List[str]] = None,
        num_ctx: Optional[int] = None,
    ) -> Dict:
        """Execute an LLM call using the existing archie_bridge functions.

        When ``agent_name`` is supplied and the agent's ``worker_type='contract'``,
        external (``call_external``) dispatches route through the Phase 7
        Telegram approval gate whenever the estimated cost exceeds the agent's
        ``auto_approve_threshold``.

        When ``images`` is non-empty this routes through ``analyze_image`` so
        callers can use the canonical Department HQ entry point for vision
        work. Agent selection, welfare/cost logging, and node routing still
        flow through ``request_work`` — only the final model-call step branches
        on whether images are present.
        """
        # ── Hub admission control (RCA KB #278774; generalized f/u) ──────────────
        # _execute_llm is the HUB/local execution chokepoint (node dispatch goes via
        # _dispatch_to_node), so anything reaching here is about to run on the hub. A concurrent
        # 7B burst thrashes the hub so jobs blow past their timeout, cascading into queue
        # congestion that even starves F.O.R.G.E. reviews.
        #
        # ⚠️ THE ORIGINAL PREMISE HERE IS STALE (corrected 2026-08-21, #5903). This read: "the
        # hub's single 8GB M4000 can't hold a 7B beside the warm small set → 7B runs on hub CPU".
        # The hub has had TWO GPUs since 2026-07-25 — M4000 8GB + TITAN X 12GB, 20GB total —
        # and model_service reports _VRAM_LARGEST_GPU_GB=12.0, so a 7B (5.9GB) DOES fit on the
        # TITAN. Live scheduler logs agree: "placement qwen2.5:7b -> gpu (budget 12.0 GB >=
        # needed 5.9 GB)". 7B on the hub is not CPU-bound by construction any more.
        #
        # What the failures actually look like (hub, qwen2.5:7b, 10h window, task_execution_log):
        #     success  n=630  median  33.2s   p90 212.4s   max 1134.7s
        #     failure  n=449  median 300.1s   p90 303.8s   max  916.8s
        # Failures cluster TIGHTLY at the 300s deadline while successes run to 1134s. So this is
        # a LATENCY TAIL vs a DEADLINE, not a hang, not a slot leak, and not CPU demotion — the
        # hub is merely slow under concurrency and the deadline truncates work that would finish.
        # Two consequences worth knowing before you retune anything here:
        #   • The cap is still worth having — it is what stops the burst — but it was SIZED for
        #     CPU-only 7B on an 8GB box. Whether 8/3 is still right for 20GB is UNPROVEN; do not
        #     assume either way without measuring at load (see #5903).
        #   • Relieving the hub by PLACEMENT beats retuning this gate: after the 2026-08-21 fleet
        #     rebalance moved 7B toward the Starships, hub success went 15% -> 99% with ZERO
        #     sheds in the following two hours.
        #
        # Gate on MODEL CLASS, not a fixed capability tuple: _model_is_gpu_class(model) is True
        # for any 7B+ model (excludes the 1.5b/3b/embed warm set that runs fine on hub CPU), so
        # a FUTURE 7B producer is auto-covered with no code change. Shed the burst here — return
        # the same {success:False} backpressure shape the cold-boot / cloud-budget gates below
        # already use (callers handle it). Fail-OPEN + generous default cap + disableable
        # (dispatch:hub_inflight_max<=0 → hub_lane_over_cap False).
        try:
            from services.welfare_governance_service import hub_lane_over_cap

            # Pass capability + module_id so the gate applies the SLOT RESERVATION
            # (#5132 f/u): while a mobility diversion is active, NON-prioritised 7B work
            # is shed at cap-reserve, holding slots open for the favoured domain to run.
            # Blanket callers (no args, e.g. the GPU-overflow escalation above) keep the
            # full cap, so this is the only reservation-aware call.
            if _model_is_gpu_class(model) and hub_lane_over_cap(capability=capability, module_id=module_id):
                return {
                    "success": False,
                    "error": "hub saturated — 7B in-flight admission cap reached; shed to relieve the hub (retry shortly)",
                    "backpressure": True,
                }
        except Exception:
            pass  # fail-open — a gate error must never block inference

        # Vision short-circuit. Uses the first image (single-image per call
        # for v1); the existing helper handles Ollama /api/generate payload
        # construction and node routing for vision models.
        #
        # If the caller-selected model isn't vision-capable (e.g. smart_router
        # picked a code agent for capability='vision' — a routing bug tracked
        # separately), substitute the configured vision primary so the call
        # still works. The wrong-agent selection will self-correct when the
        # smart_router vision capability routing is fixed.
        if images:
            # Vision on CPU is impractical (6+ min for 1024x1024 screenshots
            # with qwen2.5vl:7b). Demand-driven VRAM swap: unload resident
            # GPU text models so the vision model has room to load on the
            # M4000, then restore after. Mirrors the ComfyUI SDXL pattern.
            # Task #2032.
            ollama_models_unloaded = self._vram_swap_for_vision()
            try:
                from ai_bridge.archie_bridge import analyze_image

                vision_model = model
                known_vision_markers = (
                    "vl:",
                    "vl-",
                    "vl_",
                    "vision",
                    "llava",
                    "minicpm",
                    "-vl",
                    "moondream",
                )
                if not any(m in (model or "").lower() for m in known_vision_markers):
                    # Resolve against actually-installed vision models so we
                    # don't substitute a model that isn't pulled. Default to
                    # moondream (1.8B, fits on 8GB M4000 VRAM, ~11s/512px) —
                    # qwen2.5vl:7b needs >8GB VRAM so falls to CPU (~2 min+)
                    # on the hub. See Task #2032 benchmarks.
                    vision_model = _resolve_installed_vision_model(
                        preferred=os.getenv("VISION_MODEL_PRIMARY", "moondream:latest"),
                        fallback_chain=[
                            os.getenv("VISION_MODEL_FALLBACK", "qwen2.5vl:7b"),
                            "moondream:latest",
                            "minicpm-v:8b",
                            "llava:7b",
                        ],
                    )
                    logger.info(
                        "[DepartmentDispatcher] Vision request received a non-vision " "model=%s — substituting %s.",
                        model,
                        vision_model,
                    )
                full_prompt = prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                # With VRAM swap above, qwen2.5vl:7b should now fit on M4000.
                # GPU inference is ~10-20x faster than CPU; 300s timeout
                # still generous for a 1024x1024 page.
                vision_result = analyze_image(
                    image_base64=images[0],
                    prompt=full_prompt,
                    model=vision_model,
                    timeout=max(timeout or 120, 300),
                )
                # analyze_image returns {success, response, model, provider, cost?}
                # — same shape _execute_llm callers expect. Pass through.
                return vision_result
            except Exception as ve:
                logger.exception("[DepartmentDispatcher] Vision _execute_llm failed")
                return {
                    "success": False,
                    "error": f"Vision execution failed: {ve}",
                    "model": model,
                    "provider": "ollama_vision",
                }
            finally:
                if ollama_models_unloaded:
                    self._vram_restore_after_vision(ollama_models_unloaded)

        try:
            from ai_bridge.archie_bridge import (
                call_ollama,
                call_ollama_json,
                call_ollama_cloud,
            )

            # Route to external providers — dynamic lookup from contractor_providers DB
            from ai_bridge.external_providers import (
                get_provider_for_model,
                call_external,
                _get_provider_config,
            )

            ext_provider_key = get_provider_for_model(model)
            if ext_provider_key:
                # #4659 sovereignty budget gate (mode-independent — catches every
                # cloud text dispatch regardless of how it was routed here). Over
                # the weekly free cap → graceful failure so the caller falls back
                # to local instead of exhausting the free allowance / paying.
                if not self._cloud_budget_ok(ext_provider_key, capability or "unknown"):
                    return {
                        "success": False,
                        "error": f"Cloud provider {ext_provider_key} over weekly free budget — staying local",
                        "model": model,
                        "provider": ext_provider_key,
                        "cloud_budget_exhausted": True,
                    }
                ext_config = _get_provider_config(ext_provider_key)
                if ext_config and ext_config.get("is_cloud_proxy"):
                    return call_ollama_cloud(prompt, model=model, system_prompt=system_prompt)
                if ext_config:
                    # Phase 7 — contractor approval gate (Project #244)
                    if agent_name:
                        gate = self._contractor_approval_gate(
                            agent_name=agent_name,
                            provider=ext_provider_key,
                            model=model,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            capability=capability or "unknown",
                            module_id=module_id or "unknown",
                            timeout=timeout,
                        )
                        if gate == "rejected":
                            return {
                                "success": False,
                                "error": "Contractor dispatch rejected via Telegram approval",
                                "model": model,
                                "provider": ext_provider_key,
                            }
                        if gate == "timeout":
                            return {
                                "success": False,
                                "error": "Contractor dispatch timed out waiting for Telegram approval",
                                "model": model,
                                "provider": ext_provider_key,
                            }
                    return call_external(
                        ext_provider_key,
                        prompt,
                        model=model,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        timeout=timeout,
                    )

            # Route cloud models (fallback for :cloud suffix convention)
            if ":cloud" in model:
                return call_ollama_cloud(prompt, model=model, system_prompt=system_prompt)

            # Auto warm-boot: ensure model is loaded before calling Ollama
            try:
                readiness = self.ensure_model_ready("_dispatch", model)
                if readiness and not readiness.get("ready"):
                    logger.warning(f"[BridgeDispatcher] Model {model} not ready: {readiness}")
                    # Return early — don't call Ollama on an unloaded model.
                    # model_not_ready=True bypasses the failure threshold so
                    # the caller escalates to the next tier immediately.
                    return {
                        "success": False,
                        "error": f"Model {model} not ready (cold boot — {readiness.get('tier', 'unknown')} tier)",
                        "model": model,
                        "model_not_ready": True,
                    }
            except Exception as wb_err:
                logger.debug(f"[BridgeDispatcher] Warm boot check failed: {wb_err}")

            # QW-5: a per-dispatch num_ctx so big prompts (e.g. F.O.R.G.E. reviews)
            # aren't slid out of Ollama's default ~2048 window (dropping the rubric).
            # Keep gemma3:12b CPU-pinned (num_gpu=0) when raising ctx so it does not
            # reload onto the 8GB hub GPU and evict the warm 7B (mirrors _HUB_CPU_TIER).
            _llm_options = None
            if num_ctx:
                _llm_options = {"num_ctx": int(num_ctx)}
                if model.startswith("gemma3"):
                    _llm_options["num_gpu"] = 0

            # JSON mode
            if json_mode:
                result = call_ollama_json(
                    prompt,
                    model=model,
                    system_prompt=system_prompt,
                    timeout=timeout,
                    options=_llm_options,
                    # Schema when the caller sent one; None keeps the bare-"json" behaviour.
                    schema=json_mode if isinstance(json_mode, dict) else None,
                )
                if result.get("success") and result.get("data"):
                    return {
                        "success": True,
                        "response": json.dumps(result["data"]),
                        "model": model,
                        "provider": "ollama",
                        # call_ollama_json returns its counts as prompt_tokens/completion_tokens
                        # (estimate-filled when Ollama omits them, #4230). Reading the raw
                        # prompt_eval_count/eval_count keys here ALWAYS got 0 — the real cause of
                        # the qwen25-classify/json-mode 0-token gap. Read the right keys.
                        "prompt_tokens": result.get("prompt_tokens", result.get("prompt_eval_count", 0)),
                        "completion_tokens": result.get("completion_tokens", result.get("eval_count", 0)),
                    }
                return {
                    "success": False,
                    "error": result.get("error", "JSON parse failed"),
                    "response": result.get("raw", ""),
                    "model": model,
                    "provider": "ollama",
                }

            # ── #5317 / ADR-019 pilot: kill-switched llama.cpp local provider ──
            # OFF unless platform_settings llamacpp:enabled='true' AND this
            # (capability, model) is allowlisted. ANY failure falls straight
            # through to the normal Ollama call below — the pilot can never be
            # a new failure mode for callers. provider='llamacpp' in the result
            # is the telemetry split for the side-by-side comparison week.
            try:
                from ai_bridge import llamacpp_client

                if llamacpp_client.should_route(capability, model, json_mode=json_mode):
                    try:
                        _llama_result = llamacpp_client.chat(
                            prompt,
                            model=model,
                            system_prompt=system_prompt,
                            temperature=temperature,
                            timeout=min(timeout, 180),
                            options=_llm_options,
                        )
                        if _llama_result.get("success"):
                            logger.info(
                                "[BridgeDispatcher] llamacpp pilot served model=%s capability=%s",
                                model,
                                capability,
                            )
                            return _llama_result
                    except Exception as _llama_exc:
                        logger.warning(
                            "[BridgeDispatcher] llamacpp pilot failed (%s) — falling back to Ollama",
                            _llama_exc,
                        )
            except Exception:
                pass  # pilot plumbing must never block the standard path

            # Standard call (routes through node_router for starship nodes)
            result = call_ollama(
                prompt,
                model=model,
                system_prompt=system_prompt,
                prefer_gpu=prefer_gpu,
                timeout=timeout,
                options=_llm_options,
            )
            # If Ollama returned HTTP 500, the model failed to load mid-inference.
            # Mark model_not_ready so request_work() queues rather than escalates
            # to a weaker fallback model. Department HQ will retry when model is warm.
            if not result.get("success") and "500" in str(result.get("error", "")):
                result["model_not_ready"] = True
                logger.warning(
                    "[BridgeDispatcher] %s returned HTTP 500 during inference — marking not-ready for queue",
                    model,
                )
            # Tag starship node routing in provider field
            node_id = result.get("node_id")
            if node_id and node_id != "archie-starbase":
                result["provider"] = f"starship:{node_id}"
                logger.info(f"[BridgeDispatcher] Routed {model} to starship node {node_id}")
            return result
        except ImportError:
            logger.error("[BridgeDispatcher] archie_bridge not available")
            return {
                "success": False,
                "error": "archie_bridge not available",
                "model": model,
            }

    # ------------------------------------------------------------------
    # Phase 7 — contractor dispatch Telegram approval gate (Project #244)
    # ------------------------------------------------------------------

    def _get_contractor_policy(self, agent_name: str) -> Optional[Dict]:
        """Return contractor policy for an agent, or None if not a contract worker.

        Reads ``worker_type`` and ``auto_approve_threshold`` directly from the
        agents table. Any internal (``worker_type != 'contract'``) agent or
        lookup failure returns None, which tells the gate to proceed without
        human approval.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT worker_type, auto_approve_threshold "
                "FROM agents WHERE name = %s OR display_name = %s LIMIT 1",
                (agent_name, agent_name),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row or row[0] != "contract":
                return None
            return {
                "worker_type": row[0],
                "auto_approve_threshold": float(row[1] or 0.0),
            }
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _get_contractor_policy({agent_name}) failed: {e}")
            return None

    def _estimate_contractor_cost(
        self,
        provider: str,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> float:
        """Rough token estimate × provider pricing for the Phase 7 gate.

        Uses the existing ``archie_bridge.calculate_cost`` pricing table.
        Token count is approximated at 4 chars/token and completion is
        assumed to be half the prompt length — deliberately coarse: the
        goal is to catch runaway spend, not to invoice.
        """
        try:
            from ai_bridge.archie_bridge import calculate_cost

            total_chars = len(prompt or "") + len(system_prompt or "")
            est_prompt_tokens = max(1, total_chars // 4)
            est_completion_tokens = est_prompt_tokens // 2
            total_tokens = est_prompt_tokens + est_completion_tokens
            return float(
                calculate_cost(
                    provider,
                    model,
                    total_tokens,
                    est_prompt_tokens,
                    est_completion_tokens,
                )
                or 0.0
            )
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] _estimate_contractor_cost failed: {e}")
            return 0.0

    def wait_for_approval(
        self,
        approval_id: int,
        timeout: int = 300,
        poll_interval: float = 2.0,
    ) -> Optional[str]:
        """Block until an autonomy_approval_queue row resolves.

        Returns:
            'approved' or 'rejected' once the row reaches a terminal state.
            None if the wait times out before resolution.

        The existing Telegram escalation callback handles the row update on
        button press, so this helper is a straight DB poll.
        """
        import time as _t

        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute(
                    "SELECT status FROM autonomy_approval_queue WHERE id = %s",
                    (approval_id,),
                )
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row and row[0] in ("approved", "rejected"):
                    return row[0]
            except Exception as e:
                logger.warning(f"[BridgeDispatcher] wait_for_approval({approval_id}) poll error: {e}")
            _t.sleep(poll_interval)
        return None

    def _contractor_approval_gate(
        self,
        agent_name: str,
        provider: str,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        capability: str = "unknown",
        module_id: str = "unknown",
        timeout: int = 300,
    ) -> Optional[str]:
        """Gate external contractor dispatch behind Telegram approval.

        Returns:
            None: proceed. Agent is internal, or cost is within the agent's
                  auto_approve_threshold — no approval needed.
            'approved': proceed. Human approved via Telegram button.
            'rejected': fail-close. Human denied.
            'timeout': fail-close. No response before ``timeout``.

        Fail-closed on any internal error: if the policy lookup or the
        approval submission fails, we return 'rejected' so we never charge
        the user for a dispatch we couldn't audit.
        """
        policy = self._get_contractor_policy(agent_name)
        if not policy:
            return None  # not a contract worker — proceed

        est_cost = self._estimate_contractor_cost(provider, model, prompt, system_prompt)
        threshold = policy["auto_approve_threshold"]

        if est_cost <= threshold:
            logger.info(
                f"[BridgeDispatcher] Contractor {agent_name} auto-approved: " f"${est_cost:.4f} ≤ ${threshold:.4f}"
            )
            return None

        logger.info(
            f"[BridgeDispatcher] Contractor {agent_name} requires Telegram approval: "
            f"${est_cost:.4f} > ${threshold:.4f}"
        )
        try:
            from ai_bridge.agent_loop import request_approval
        except Exception as e:
            logger.error(f"[BridgeDispatcher] request_approval import failed: {e} — failing closed")
            return "rejected"

        approval_id = request_approval(
            action_type="contractor_dispatch",
            action_data={
                "agent": agent_name,
                "provider": provider,
                "model": model,
                "capability": capability,
                "module_id": module_id,
                "estimated_cost": round(est_cost, 4),
                "threshold": round(threshold, 4),
                "prompt_preview": (prompt or "")[:200],
            },
            reason=(
                f"Contractor {agent_name} dispatch estimated at "
                f"${est_cost:.4f} exceeds auto-approve threshold ${threshold:.4f}"
            ),
            requested_by="bridge_dispatcher",
            priority=7,
            tier=2,
        )
        if not approval_id:
            logger.error(
                f"[BridgeDispatcher] request_approval returned None for contractor {agent_name} — failing closed"
            )
            return "rejected"

        result = self.wait_for_approval(approval_id, timeout=timeout)
        if result is None:
            logger.warning(f"[BridgeDispatcher] Contractor approval #{approval_id} timed out")
            return "timeout"
        return result

    def _log_execution(
        self,
        result: DispatchResult,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ):
        """Log execution to task_execution_log for HR tracking."""
        if result.queued:
            # Task deferred to dispatch_pending_queue — not executed yet.
            # The worker logs the actual outcome when it runs. Logging here
            # would write a spurious success=False that inflates misroute audit counts.
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            # Determine worker_type from escalation metadata
            meta = result.metadata or {}
            is_contractor = meta.get("is_cloud", False)
            worker_type = "contract" if is_contractor else "internal"

            # C.R.E.E.D. accounting-integrity Fix #3 (KB #279350-family): a
            # cloud/contractor row has no single internal "owner" — agent
            # selection failed entirely before the dispatcher escalated (see
            # resolve_department_escalation_owner()) — so it was historically
            # logged as (agent_id=None, agent_name="CONTRACTOR→x"/"CLOUD→x"),
            # which silently drops that cloud spend from the escalating
            # department director's per-agent K.I.N./budget view (that view
            # is driven by task_execution_log.agent_id — see
            # services/agent_load_service.py). Attribute ONLY the logged row
            # to the department-director proxy the escalation path stashed on
            # the result; `result.agent_id`/`result.agent_name` themselves are
            # left untouched below so welfare update, agent memory, and
            # performance-metric crediting behave exactly as before this fix.
            log_agent_id = result.agent_id
            log_agent_name = result.agent_name
            if is_contractor and getattr(result, "escalating_agent_id", None):
                log_agent_id = result.escalating_agent_id
                esc_name = result.escalating_agent_name or "?"
                log_agent_name = f"{esc_name} →{result.agent_name}" if result.agent_name else esc_name

            # Warm-up keep-alive is INFRASTRUCTURE overhead, not agent work (decision:
            # warm-up pseudo-agent = NO — warm-up is infra, stays unattributed). Log it
            # UNATTRIBUTED (agent_id=NULL; keep agent_name as an informational marker of which
            # model was warmed) so it never inflates any per-agent budget / welfare / K.I.N.
            # accounting — all of which are keyed on task_execution_log.agent_id. This is the
            # SINGLE source-of-truth gate (covers sync + queue paths); the recal module_source
            # filter is belt-and-suspenders for the 30d window. Aggregate carbon/tokens are
            # unaffected (real model, real energy). Mirrors the contractor override above.
            is_warmup = module_id in ("fleet_warmup", "kin_warmth")
            if is_warmup:
                log_agent_id = None

            # Fleet node attribution (migration 384). Populated by
            # _dispatch_to_node via metadata["node_id"] (= remote_nodes.id PK).
            # NULL for hub-direct dispatches. Cast defensively in case metadata
            # carries a stringified id from a serialized path.
            node_id_used = meta.get("node_id")
            try:
                node_id_used = int(node_id_used) if node_id_used is not None else None
            except (TypeError, ValueError):
                # A producer emitted the VARCHAR node_id (e.g. 'starship_76583490e36955ab')
                # instead of the int PK. The preferred_node loop (_get_fleet_node_for_dispatch)
                # and the node_preferred path (_node_assign) both carry the varchar, so their
                # GPU-served dispatches were int-cast-failing -> None -> mislogged to the hub
                # fallback below (#4342: engine plan served on USS-246 but logged node 68).
                # Resolve varchar -> PK (cached) so fleet work is attributed to the real node.
                _vid = str(node_id_used).strip()
                node_id_used = None
                if _vid:
                    _pk_cache = getattr(self, "_node_str_to_pk_cache", None)
                    if _pk_cache is None:
                        _pk_cache = {}
                        self._node_str_to_pk_cache = _pk_cache
                    if _vid in _pk_cache:
                        node_id_used = _pk_cache[_vid]
                    else:
                        try:
                            cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s LIMIT 1", (_vid,))
                            _pkr = cur.fetchone()
                            node_id_used = int(_pkr[0]) if _pkr else None
                            _pk_cache[_vid] = node_id_used
                        except Exception:
                            node_id_used = None

            # Hub-local source attribution (#4342). A hub-direct dispatch carries NO
            # metadata["node_id"], so internal hub-local inference logged NULL while
            # DHQ-routed-to-hub logged the hub's id — the SAME machine split into two
            # A.R.M.A.D.A. buckets ("Archie Starbase" vs "hub"). Attribute internal
            # hub-local rows to the hub node so local + DHQ unify at the SOURCE (and the
            # dispatcher's recent_load sees honest hub load). Resolved ONCE by the stable
            # node_id "archie-starbase" (rename-safe; never literal 68), cached, fail-open.
            # Cloud/contractor rows stay NULL (cloud is not a node); a fleet id always wins.
            if node_id_used is None and not is_contractor:
                hub_id = getattr(self, "_hub_node_db_id_cache", None)
                if hub_id is None:
                    try:
                        cur.execute("SELECT id FROM remote_nodes WHERE node_id = 'archie-starbase' LIMIT 1")
                        _hr = cur.fetchone()
                        hub_id = int(_hr[0]) if _hr else None
                        if hub_id is not None:
                            self._hub_node_db_id_cache = hub_id
                    except Exception:
                        hub_id = None
                if hub_id is not None:
                    node_id_used = hub_id

            # Pick up Claude MCP attribution if dispatch was called from
            # within an MCP tool handler (Tasks #1297/#1298).
            request_origin = None
            mcp_tool = None
            try:
                from mcp_server.dispatch_context import (
                    get_request_origin,
                    get_mcp_tool,
                )

                request_origin = get_request_origin()
                mcp_tool = get_mcp_tool()
            except Exception:
                pass

            # Instrumentation (#3697): flag successful real-LLM dispatches that
            # logged 0 tokens, so the logs reveal exactly which path/capability/
            # model drops token capture. Grep `[token-gap]` in archie_platform logs.
            if (
                result.success
                and (result.prompt_tokens + result.completion_tokens) == 0
                and result.model_used
                and result.model_used not in ("internal", "")
                and "embed" not in (result.model_used or "")
            ):
                logger.warning(
                    "[token-gap] 0-token success: cap=%s model=%s provider=%s module=%s agent=%s node=%s resp_chars=%d",
                    result.capability,
                    result.model_used,
                    result.provider,
                    module_id,
                    result.agent_name,
                    node_id_used,
                    len(result.response or ""),
                )

            # DRP attribution (#3728): on the boston-2 standby (ARCHIE_DR_MODE=1)
            # tag every dispatch so A.R.M.A.D.A. can tell DR-mode agent work from
            # normal hub work. Defensive copy; pure no-op on the hub (env unset).
            req_meta = dict(result.metadata or {})
            if os.getenv("ARCHIE_DR_MODE", "0") == "1":
                req_meta["dr_mode"] = True
                req_meta["dr_node"] = "boston-2"

            cur.execute(
                """
                INSERT INTO task_execution_log (
                    agent_id, agent_name, module_source, task_type, capability,
                    model_used, provider, prompt_tokens, completion_tokens,
                    tokens_used, duration_ms, success, error_message,
                    station_code, requested_by, priority, request_metadata, job_id,
                    worker_type, request_origin, mcp_tool, node_used_id
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    log_agent_id,
                    log_agent_name,
                    # module_source: fall back to capability when the caller didn't
                    # tag a module_id, so internal agent-loop dispatches (knowledge_analysis,
                    # workforce_planning, welfare_monitoring, …) are attributed by what
                    # they do instead of collapsing into a useless "unknown" bucket. (2026-05-29)
                    (module_id if module_id and module_id != "unknown" else (result.capability or "unknown")),
                    result.capability,  # task_type = capability
                    result.capability,
                    result.model_used,
                    result.provider,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.prompt_tokens + result.completion_tokens,
                    result.duration_ms,
                    result.success,
                    result.error,
                    result.station_code,
                    user_id,
                    "normal",
                    json.dumps(req_meta),
                    job_id,
                    worker_type,
                    request_origin,
                    mcp_tool,
                    node_id_used,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            # Notification hook for Claude MCP-initiated dispatches (Task #1299).
            # Always-on for in-platform; Telegram gated on failures or cost-bearing.
            if request_origin == "claude":
                self._notify_claude_dispatch(result, mcp_tool, is_contractor)

            # Also update agent-level performance summary via agent_service
            # (Project #241 Track C.3). Skip when contractor did the work —
            # don't credit the agent.
            if result.agent_id and not is_contractor and not is_warmup:
                try:
                    from services import agent_service

                    agent_service.update_performance_metrics(result.agent_id, result.success)
                except Exception as exc:
                    logger.warning(f"update_performance_metrics failed: {exc}")
            # After logging, update agent emotional state based on recent performance.
            # Skipped for warm-up keep-alive — infrastructure overhead is not a creditable task.
            if not is_warmup:
                if _HAS_AGENT_SERVICE:
                    svc_update_welfare_after_task(result.agent_id, result.success)
                    self._welfare_cache_time = 0
                else:
                    self._update_agent_welfare(result.agent_id, result.success)
            # Record agent memory from this task execution
            self._record_agent_memory(result, module_id)
            # Cloud dispatch is a governed action (#3663 / Cloud Gov D) —
            # audit locally + disclose on the C.R.E.E.D. surface.
            self._record_cloud_governance(result, module_id)
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log execution: {e}")

    def _notify_claude_dispatch(
        self,
        result: "DispatchResult",
        mcp_tool: Optional[str],
        is_contractor: bool,
    ):
        """Fire platform notification (and optionally Telegram) when a Claude
        MCP request completes a dispatch (Task #1299).

        Routing:
        - Always: in-platform admin notification (DHQ alerts dropdown)
        - Telegram: only on failures or cost-bearing dispatches (cost > 0
          or contractor tier), gated by env CLAUDE_DISPATCH_TELEGRAM=1.
          The cost/contractor Tier-2 approval flow runs INSIDE dispatch()
          before this point — we only post-notify.
        """
        try:
            cost = float(getattr(result, "cost_usd", 0) or 0)
            is_cost_bearing = is_contractor or cost > 0
            status_emoji = "✓" if result.success else "✗"
            title = f"Claude → {mcp_tool or 'dispatch'}"
            parts = [
                f"{status_emoji} agent={result.agent_name or 'unknown'}",
                f"capability={result.capability}",
                f"model={result.model_used or 'n/a'}",
            ]
            if is_cost_bearing:
                parts.append(f"cost=${cost:.4f}")
            if not result.success and result.error:
                parts.append(f"error={result.error[:120]}")
            msg = " · ".join(parts)

            if not result.success:
                notif_type = "error"
                priority = "high"
            elif is_cost_bearing:
                notif_type = "warning"
                priority = "high"
            else:
                notif_type = "info"
                priority = "low"

            try:
                from services.notification_service import create_notification

                create_notification(
                    notification_type=notif_type,
                    title=title,
                    message=msg,
                    source="dispatcher",
                    priority=priority,
                    visibility="admin",
                )
            except Exception as exc:
                logger.warning(f"[ClaudeNotify] platform notify failed: {exc}")

            if (not result.success or is_cost_bearing) and os.getenv("CLAUDE_DISPATCH_TELEGRAM", "0") == "1":
                try:
                    from services.telegram_service import send_info

                    send_info(title, msg)
                except Exception as exc:
                    logger.warning(f"[ClaudeNotify] telegram send failed: {exc}")
        except Exception as exc:
            logger.warning(f"[ClaudeNotify] hook failed: {exc}")

    def _update_agent_welfare(self, agent_id: Optional[int], success: bool):
        """Update agent emotional state after each dispatch.

        FIX-2 (KB #270619): delegate to the SINGLE token-based welfare writer
        (agent_service.update_welfare_after_task) instead of recomputing stress here
        from COUNT(dispatches)/20. This duplicate action-count writer ran after every
        dispatch and OVERWROTE the token-based value — undoing FIX-1 and re-benching
        agents on raw activity. One writer, one (token-based) formula now.
        """
        if not agent_id:
            return
        try:
            from services.agent_service import update_welfare_after_task

            update_welfare_after_task(agent_id, success=success)
            # Invalidate welfare cache so the next dispatch sees fresh state.
            self._welfare_cache_time = 0
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Welfare update skipped: {e}")

    def _record_agent_memory(self, result: DispatchResult, module_id: str):
        """Create an agent_memory record summarising what the agent did.

        Keeps memories brief (no LLM call) — just logs the task capability,
        module, model used, and outcome so the MEM tab has content.
        """
        if not result.agent_id:
            return
        # Skip contractor/cloud work — memory belongs to internal agents
        meta = result.metadata or {}
        if meta.get("is_cloud"):
            return
        try:
            # Build a concise memory string
            outcome = "completed successfully" if result.success else f"failed: {result.error or 'unknown error'}"
            content = (
                f"Handled {result.capability or 'task'} for {module_id} "
                f"using {result.model_used or 'unknown model'}. "
                f"Task {outcome}."
            )
            # Determine memory type & importance
            memory_type = "skill" if result.success else "interaction"
            importance = 0.55 if result.success else 0.65  # failures slightly more important to remember

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_memory
                    (agent_id, memory_type, content, importance_score,
                     source_module, context)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    result.agent_id,
                    memory_type,
                    content,
                    importance,
                    module_id,
                    json.dumps(
                        {
                            "capability": result.capability,
                            "model": result.model_used,
                            "station": result.station_code,
                            "duration_ms": result.duration_ms,
                            "success": result.success,
                            "tokens": result.prompt_tokens + result.completion_tokens,
                        }
                    ),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Agent memory skipped: {e}")

    def _record_cloud_governance(self, result: DispatchResult, module_id: str):
        """Treat cloud dispatch as a GOVERNED ACTION (#3663 / Cloud Gov D).

        Data left the premises and (possibly free-tier) cloud budget was
        consumed. Two sinks, both fail-safe (never block the dispatch result):
        - governance_audit_log row with provider/model/cost-posture details
        - C.R.E.E.D. transparency event via services.creed_emit (routed to the
          emitting agent's product tenant, per #3958)
        """
        meta = result.metadata or {}
        if not meta.get("is_cloud"):
            return
        provider = str(meta.get("cloud_provider") or meta.get("provider") or meta.get("provider_key") or "cloud")
        model = result.model_used or meta.get("cloud_model") or "unknown"

        # Budget posture for THIS provider/model (cloud_budget_status is
        # fail-safe → [] on error; rows: provider/model/used_7d/weekly_limit/
        # remaining/pct_used/over_limit, limits None = unlimited).
        budget_row = None
        try:
            from services.cloud_budget import cloud_budget_status

            for row in cloud_budget_status():
                if row.get("model") == model or (row.get("provider") and row["provider"] in provider):
                    budget_row = row
                    break
        except Exception:
            pass

        if budget_row and budget_row.get("weekly_limit") is not None:
            budget_line = f"weekly budget {budget_row.get('used_7d')}/{budget_row.get('weekly_limit')}"
        else:
            budget_line = "no declared weekly limit"
        details = {
            "module": module_id,
            "capability": result.capability,
            "provider": provider,
            "model": model,
            "success": result.success,
            "duration_ms": result.duration_ms,
            "tokens": (result.prompt_tokens or 0) + (result.completion_tokens or 0),
            "data_leaves_premises": True,
            "budget": budget_row,
        }

        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO governance_audit_log
                    (agent_id, event_category, event_type, action, reason, details, timestamp)
                VALUES (%s, 'cloud_dispatch', 'governed_action', 'cloud_execute', %s, %s::jsonb, NOW())
                """,
                (
                    result.agent_id,
                    f"Cloud dispatch ({result.capability or 'task'}) via {provider}/{model} — "
                    f"data left premises; {budget_line}",
                    json.dumps(details, default=str),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] cloud governance audit skipped: {e}")

        try:
            from services.creed_emit import emit_event

            over = bool(budget_row and budget_row.get("over_limit"))
            emit_event(
                category="transparency",
                severity="warning" if over else "info",
                description=(
                    f"Cloud dispatch disclosed: {result.capability or 'task'} for {module_id} "
                    f"via {provider}/{model} — data left the local cluster; {budget_line}"
                ),
                event_type="cloud_dispatch",
                agent_id=result.agent_id,
                agent_name=getattr(result, "agent_name", None),
                metadata=details,
            )
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] cloud governance creed emit skipped: {e}")

    def _get_escalation_threshold(self) -> int:
        """Read escalation threshold from platform_settings."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_threshold'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return int(row[0]) if row else 3
        except Exception as _exc:
            return 3

    def _agent_display(self, agent_name: str) -> str:
        """Get human-friendly display string for an agent.

        Returns 'FirstName LastName, Title' or display_name or code name.
        """
        info = self._agent_cache.get(agent_name, {})
        display = info.get("display_name", "")
        if display:
            title = info.get("title", "")
            return f"{display}, {title}" if title else display
        first = info.get("first_name", "")
        last = info.get("last_name", "")
        name = f"{first} {last}".strip()
        if name:
            title = info.get("title", "")
            return f"{name}, {title}" if title else name
        return agent_name

    def _get_routing_mode(self) -> str:
        """Read routing_mode from platform_settings. Returns 'full' on error."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else "full"
        except Exception as _exc:
            return "full"

    def _get_escalation_mode(self) -> str:
        """Read escalation_mode from platform_settings.

        Returns one of: 'auto', 'ask_first', 'local_only'.
        - auto: auto-escalate to free cloud, Telegram FYI
        - ask_first: request Telegram approval before any cloud escalation
        - local_only: never escalate, always use local LLM (queue/wait)
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_mode'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            # Sovereign-by-default (#4659): no row → cloud OFF (local_only).
            return row[0] if row else "local_only"
        except Exception as _exc:
            # Fail CLOSED for sovereignty — a DB blip must never enable cloud.
            return "local_only"

    def _cloud_budget_ok(self, provider_key: str, capability: str = "unknown") -> bool:
        """Weekly free-tier budget gate for a cloud TEXT provider (#4659).

        The sovereignty guard. Before a cloud dispatch fires, confirm the
        provider still has weekly free-tier headroom. Over the effective cap →
        return False so the caller skips this provider (the escalation loop
        rotates to the next) and ultimately falls back to LOCAL when every
        cloud budget is exhausted. Providers with no declared free weekly limit
        (uncapped/paid/unknown) fail-OPEN — always allowed. At >=80% usage a
        throttled Telegram advisory fires.

        NEVER raises: a counting bug must never block or crash dispatch.
        """
        try:
            from ai_bridge.external_providers import weekly_budget_status

            st = weekly_budget_status(provider_key)
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] cloud budget check failed for {provider_key}: {e}")
            return True  # fail-open — never block on a counting error
        # Provider without a declared free weekly_limit → uncapped, always allowed.
        if not st.get("limit"):
            return True
        if st.get("warn"):
            self._maybe_alert_cloud_budget(provider_key, st)
        if st.get("over_budget"):
            logger.warning(
                "[BridgeDispatcher] Cloud budget guard: %s over weekly free cap "
                "(%s/%s reqs, cap %s) for '%s' — skipping, falling back to local.",
                provider_key,
                st.get("used"),
                st.get("limit"),
                st.get("effective_cap"),
                capability,
            )
            return False
        return True

    def _maybe_alert_cloud_budget(self, provider_key: str, status: dict) -> None:
        """Throttled (24h/provider) Telegram advisory when a cloud free tier hits >=80%.

        Throttle state lives in ``platform_settings`` (key
        ``cloud_budget_alert_<provider>``), reusing the proven UPSERT pattern so
        we touch no unfamiliar schema. Best effort — never raises.
        """
        skey = f"cloud_budget_alert_{provider_key}"
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s " "AND updated_at > NOW() - INTERVAL '24 hours'",
                (skey,),
            )
            if cur.fetchone():
                cur.close()
                conn.close()
                return  # already alerted within the throttle window
            cur.execute(
                """
                INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                VALUES (%s, %s, 'string', 'Cloud budget 80pct alert throttle', NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (skey, str(status.get("used"))),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] cloud budget alert throttle skipped: {e}")
            return
        try:
            from services.telegram_service import send_system

            send_system(
                "Cloud free tier at 80%",
                f"{provider_key} used {status.get('used')}/{status.get('limit')} weekly "
                f"free requests (>=80%). The sovereignty guard will skip it and keep "
                f"dispatch local until the weekly window resets.",
            )
        except Exception:
            pass

    # Cloud contractor models (free via OLLAMA_API_KEY) — legacy fallback.
    # Prefer _find_contractors_for_capability() which queries contractor_providers table.
    FREE_CLOUD_MODELS = [
        # minimax-m2.5:cloud RETIRED 2026-08-17 (#5706) — every dispatch 410'd after ~370s.
        "qwen3-coder-next:cloud",
    ]

    def _find_contractors_for_capability(
        self, capability: str, max_tier: int = 28, exclude_restricted: bool = False
    ) -> list:
        """Find contractors matching a capability, ordered by tier_position (cheapest first).

        Queries contractor_providers table for active providers whose capabilities
        JSONB array contains a matching tag. Falls back to text_chat if no exact match.

        Args:
            capability: Normalized capability tag (e.g., 'code_generation', 'image_gen')
            max_tier: Max tier_position to consider (for budget control)
            exclude_restricted: If True, skip creed_compliance_tier=3 contractors

        Returns:
            List of dicts: {provider_key, display_name, tier_position,
                           creed_compliance_tier, base_url, default_model, is_cloud_proxy}
        """
        # Map CAPABILITY_TAXONOMY tags to contractor_providers.capabilities tags
        capability_map = {
            "code_generation": "code",
            "code_review": "code",
            "debugging": "code",
            "architecture": "code",
            "creative_writing": "text_chat",
            "summarization": "text_chat",
            "reasoning": "text_chat",
            "conversation": "text_chat",
            "classification": "text_chat",
            "data_analysis": "text_chat",
            "fact_checking": "text_chat",
            "ethics_reasoning": "text_chat",
            "research_synthesis": "text_chat",
            "translation": "text_chat",
            "knowledge_extraction": "text_chat",
            "image_generation": "image_gen",
            "vision": "vision",
            "embedding": "embedding",
        }
        provider_capability = capability_map.get(capability, "text_chat")

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                SELECT provider_key, display_name, tier_position,
                       creed_compliance_tier, base_url, default_model, is_cloud_proxy
                FROM contractor_providers
                WHERE is_active = true
                  AND tier_position <= %s
                  AND capabilities @> %s::jsonb
            """
            params = [max_tier, f'["{provider_capability}"]']

            if exclude_restricted:
                query += " AND creed_compliance_tier < 3"

            query += " ORDER BY tier_position ASC"

            cur.execute(query, params)
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return results
        except Exception as e:
            logger.warning(f"[DepartmentDispatcher] Contractor capability query failed: {e}")
            return []

    def _dispatch_to_contractor(
        self,
        contractor: dict,
        prompt: str,
        capability: str,
        module_id: str,
        system_prompt: str = None,
        json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
        timeout: int = 120,
        escalating_agent_id: Optional[int] = None,
        escalating_agent_name: Optional[str] = None,
    ) -> Optional["DispatchResult"]:
        """Dispatch work to a cloud contractor provider.

        For cloud proxy providers (is_cloud_proxy=True), uses _execute_llm()
        which routes through Ollama cloud. For standard providers, uses
        external_providers.call_external().

        ``escalating_agent_id``/``escalating_agent_name`` (C.R.E.E.D.
        accounting-integrity Fix #3): the department-director proxy resolved by
        the caller via ``resolve_department_escalation_owner()`` — carried onto
        the returned ``DispatchResult`` ONLY so ``_log_execution`` can attribute
        the ``task_execution_log`` row to a real agent; routing/welfare/cost
        logic here is unaffected.

        Returns DispatchResult on success, None on failure.
        """
        provider_key = contractor["provider_key"]
        model = contractor.get("default_model")

        # #4659 sovereignty budget gate — skip a cloud provider that is over its
        # weekly free tier so the escalation loop rotates to the next contractor
        # (and falls back to local when all are exhausted). Covers the non-proxy
        # call_external path, which does NOT flow through _execute_llm's gate.
        if not self._cloud_budget_ok(provider_key, capability):
            logger.info(
                "[DepartmentDispatcher] Skipping contractor %s — over weekly free budget.",
                provider_key,
            )
            return None

        try:
            if contractor.get("is_cloud_proxy"):
                # Cloud proxy (e.g. minimax, qwen3) — route through Ollama.
                # Vision passes `images` through request_work → _execute_llm
                # but contractor/cloud-proxy paths don't support vision yet
                # (each provider has a different image payload shape); left
                # unthreaded on purpose until that work lands.
                llm_result = self._execute_llm(
                    model=model or provider_key,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    json_mode=json_mode,
                    timeout=timeout,
                )
                if llm_result.get("success"):
                    return DispatchResult(
                        success=True,
                        response=llm_result.get("response", ""),
                        agent_name=f"CONTRACTOR→{contractor['display_name']}",
                        agent_id=None,
                        model_used=model or provider_key,
                        department="Contractors",
                        capability=capability,
                        duration_ms=0,  # caller sets this
                        prompt_tokens=llm_result.get("prompt_tokens", llm_result.get("prompt_eval_count", 0)),
                        completion_tokens=llm_result.get("completion_tokens", llm_result.get("eval_count", 0)),
                        provider=f"contractor:{provider_key}",
                        metadata={
                            "escalation": "contractor_capability",
                            "contractor": provider_key,
                            "tier_position": contractor["tier_position"],
                            "creed_tier": contractor.get("creed_compliance_tier", 2),
                            "is_cloud_proxy": True,
                        },
                        escalating_agent_id=escalating_agent_id,
                        escalating_agent_name=escalating_agent_name,
                    )
            else:
                # Standard external provider (OpenAI-compatible)
                from ai_bridge.external_providers import call_external

                result = call_external(
                    provider_key=provider_key,
                    prompt=prompt,
                    model=model,
                    system_prompt=system_prompt,
                    json_mode=json_mode,
                    timeout=timeout,
                )
                if result.get("success"):
                    return DispatchResult(
                        success=True,
                        response=result.get("response", ""),
                        agent_name=f"CONTRACTOR→{contractor['display_name']}",
                        agent_id=None,
                        model_used=model or provider_key,
                        department="Contractors",
                        capability=capability,
                        duration_ms=0,  # caller sets this
                        prompt_tokens=result.get("prompt_tokens", result.get("prompt_eval_count", 0)),
                        completion_tokens=result.get("completion_tokens", result.get("eval_count", 0)),
                        provider=f"contractor:{provider_key}",
                        metadata={
                            "escalation": "contractor_capability",
                            "contractor": provider_key,
                            "tier_position": contractor["tier_position"],
                            "creed_tier": contractor.get("creed_compliance_tier", 2),
                            "is_cloud_proxy": False,
                        },
                        escalating_agent_id=escalating_agent_id,
                        escalating_agent_name=escalating_agent_name,
                    )
        except Exception as e:
            logger.warning(f"[DepartmentDispatcher] Contractor dispatch failed ({provider_key}): {e}")

        return None

    # Proficiency tier mapping: level → tier name
    _PROFICIENCY_TIERS = {
        1: "novice",
        2: "novice",
        3: "intermediate",
        4: "advanced",
        5: "advanced",
    }

    def _augment_for_proficiency(
        self,
        agent_name: str,
        capability: str,
        proficiency_level: int,
        system_prompt: Optional[str],
        routing_mode: str,
    ) -> tuple:
        """Augment system prompt and optionally override model based on proficiency.

        Returns (augmented_system_prompt, model_override_or_None).
        """
        tier = self._PROFICIENCY_TIERS.get(proficiency_level, "novice")

        # Query skill_training_templates for this capability + tier
        try:
            from database import get_db

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT system_prompt_addon, model_override "
                "FROM skill_training_templates WHERE skill_name = %s AND level_tier = %s",
                (capability, tier),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] _augment_for_proficiency DB error: {e}")
            return (system_prompt, None)

        if not row:
            return (system_prompt, None)

        addon, model_override = row

        # Append proficiency addon to system prompt
        if addon and system_prompt:
            system_prompt = (
                system_prompt
                + "\n\n--- PROFICIENCY GUIDANCE ("
                + tier.upper()
                + ") ---\n"
                + addon
                + "\n--- END PROFICIENCY GUIDANCE ---"
            )
        elif addon:
            system_prompt = addon

        # Model override only for advanced tier + CAPABILITY_REQUIRES_SKILL tasks
        resolved_override = None
        if proficiency_level >= 4 and model_override and capability in CAPABILITY_REQUIRES_SKILL:
            is_cloud = ":cloud" in model_override or model_override in (
                "minimax-m2.5",
                "qwen3-coder-next",
            )
            is_paid = any(model_override.startswith(p) for p in ("gpt-4o", "llama-3.1-sonar", "grok", "claude"))

            if routing_mode == "local_only":
                # Block all cloud/external overrides
                resolved_override = None
            elif routing_mode == "local_cloud" and is_paid:
                # Block paid, allow free cloud
                resolved_override = None
            elif proficiency_level == 4 and is_paid:
                # Lv4 only gets free cloud
                resolved_override = None
            else:
                resolved_override = model_override

            if resolved_override:
                logger.info(
                    f"[BridgeDispatcher] Proficiency override: agent='{agent_name}' "
                    f"capability='{capability}' level={proficiency_level} "
                    f"tier='{tier}' model_override='{resolved_override}'"
                )

        # Check for active training with failure analysis — inject coaching context
        try:
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute(
                """
                SELECT failure_analysis FROM training_assignments
                WHERE agent_id = (SELECT id FROM agents WHERE name = %s LIMIT 1)
                  AND skill_name = %s AND status = 'in_progress'
                  AND failure_analysis IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """,
                (agent_name, capability),
            )
            training_row = cur2.fetchone()
            cur2.close()
            conn2.close()
            if training_row and training_row[0]:
                coaching = training_row[0][:1500]
                if system_prompt:
                    system_prompt += (
                        "\n\n--- ACTIVE TRAINING: FAILURE CORRECTION ---\n"
                        + coaching
                        + "\nApply these corrections to improve your performance.\n"
                        "--- END TRAINING CONTEXT ---"
                    )
                else:
                    system_prompt = coaching
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Training context lookup error: {e}")

        return (system_prompt, resolved_override)

    def _check_agent_busy(self, agent_name: str, exclude_job_id: int = None) -> Optional[Dict]:
        """Check if agent has a running bridge_job. Returns job dict or None.

        Args:
            agent_name: Agent to check.
            exclude_job_id: If provided, ignore this job (the caller's own job).
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            if exclude_job_id:
                cur.execute(
                    """
                    SELECT id, description, total_steps, completed_steps
                    FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running' AND id != %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (agent_name, exclude_job_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, description, total_steps, completed_steps
                    FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (agent_name,),
                )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                total = row[2] or 1
                completed = row[3] or 0
                pct = round((completed / total) * 100, 1)
                return {
                    "id": row[0],
                    "description": row[1],
                    "progress_pct": pct,
                }
            return None
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _check_agent_busy failed: {e}")
            return None

    def _try_cloud_escalation(
        self,
        agent_name: str,
        busy_job: Dict,
        capability: str,
        prompt: str,
        module_id: str,
        system_prompt: Optional[str],
        json_mode: bool,
        timeout: int,
        routing_mode: str,
        station_code: str,
        user_id: Optional[int],
        job_id: Optional[int],
    ) -> Optional[DispatchResult]:
        """
        Attempt throughput escalation when primary agent is busy.

        Behavior depends on escalation_mode platform setting:
        - auto: try free cloud (auto-approve), then paid cloud via Telegram
        - ask_first: request Telegram approval before ANY cloud escalation
        - local_only: never escalate, always queue for local LLM

        Returns DispatchResult on success, None if escalation not possible.
        """
        if routing_mode == "local_only":
            return None  # Cannot escalate

        escalation_mode = self._get_escalation_mode()

        if escalation_mode == "local_only":
            logger.info(
                f"[BridgeDispatcher] Escalation blocked: escalation_mode=local_only. "
                f"{agent_name} busy ({busy_job['description']}), queuing for local."
            )
            return None  # Never escalate — queue for local

        # ALL cloud escalation requires Telegram approval (3-slot model).
        # Cloud is the 4th slot — always needs human approval.
        logger.info(
            f"[BridgeDispatcher] Cloud approval required: {agent_name} busy "
            f"({busy_job['description']}, {busy_job['progress_pct']}%). "
            f"Requesting Telegram approval for cloud escalation."
        )
        try:
            from agent_loop import request_approval

            cloud_model = self.FREE_CLOUD_MODELS[0] if self.FREE_CLOUD_MODELS else "unknown"
            request_approval(
                action_type="cloud_throughput_escalation",
                action_data={
                    "original_agent": agent_name,
                    "busy_job": busy_job,
                    "escalated_model": cloud_model,
                    "escalated_provider": "ollama_cloud",
                    "capability": capability,
                    "module_id": module_id,
                    "prompt_preview": prompt[:200],
                    "escalation_mode": escalation_mode,
                },
                reason=(
                    f"{agent_name} busy ({busy_job['description']}, "
                    f"{busy_job['progress_pct']}%). "
                    f"Escalate to {cloud_model}? Or queue for local."
                ),
                requested_by="bridge_dispatcher",
                tier=2,
            )
            self._log_escalation(
                original_agent_id=None,
                original_model=agent_name,
                escalated_model=cloud_model,
                escalated_provider="ollama_cloud",
                capability=capability,
                module_id=module_id,
                reason=f"Throughput: awaiting cloud approval",
                failure_count=0,
                approval_method="telegram",
                success=None,
            )
        except Exception as esc_err:
            logger.warning(f"[BridgeDispatcher] Cloud approval request failed: {esc_err}")
        return None  # Always return None — no auto-cloud

    def _notify_throughput_escalation(
        self,
        agent_name: str,
        cloud_model: str,
        capability: str,
        module_id: str,
        busy_job: Dict,
        duration_ms: int,
    ):
        """Insert an agent_alert so Telegram notifier sends an FYI."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_alerts
                    (agent_id, alert_type, severity, title, message, details)
                VALUES (
                    (SELECT id FROM agents WHERE name = %s LIMIT 1),
                    'throughput_escalation', 'warning',
                    %s, %s, %s
                )
                """,
                (
                    agent_name,
                    f"Cloud escalation: {agent_name} → {cloud_model}",
                    (
                        f"{agent_name} is busy with \"{busy_job.get('description', '?')}\" "
                        f"({busy_job.get('progress_pct', 0)}%). "
                        f"Dispatched {capability} to {cloud_model} (free cloud). "
                        f"Module: {module_id} | Duration: {duration_ms}ms"
                    ),
                    json.dumps(
                        {
                            "original_agent": agent_name,
                            "cloud_model": cloud_model,
                            "capability": capability,
                            "module_id": module_id,
                            "busy_job": busy_job,
                            "duration_ms": duration_ms,
                        }
                    ),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _notify_throughput_escalation failed: {e}")

    def _track_failure(self, agent_id: int, capability: str) -> int:
        """Increment failure count, return new count."""
        key = (agent_id, capability)
        self._failure_tracker[key] = self._failure_tracker.get(key, 0) + 1
        return self._failure_tracker[key]

    def _reset_failure(self, agent_id: int, capability: str):
        """Reset failure count on success."""
        self._failure_tracker.pop((agent_id, capability), None)

    def _get_next_tier(self, current_model: str, capability: str) -> Optional[Dict]:
        """Find the next escalation tier above current model."""
        try:
            # Relative intra-package import — smart_router lives alongside
            # this file in department_hq/services/ after Project #244 merge.
            from .smart_router import get_router, TIER_ORDER

            router = get_router()
            available = router.get_available_tiers()
            configs = router._get_model_configs()

            current_tier = None
            for tier_name, config in configs.items():
                if config.model_name == current_model or current_model.startswith(config.model_name.split(":")[0]):
                    current_tier = tier_name
                    break

            if not current_tier:
                return None

            found_current = False
            for tier in available:
                if tier == current_tier:
                    found_current = True
                    continue
                if found_current and tier in configs:
                    config = configs[tier]
                    is_paid = tier in (
                        "haiku",
                        "sonnet",
                        "opus",
                    ) or config.provider not in ("ollama", "ollama_cloud")
                    return {
                        "tier": tier,
                        "model": config.model_name,
                        "provider": config.provider,
                        "is_paid": is_paid,
                    }
            return None
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] get_next_tier failed: {e}")
            return None

    def _log_escalation(
        self,
        original_agent_id,
        original_model,
        escalated_model,
        escalated_provider,
        capability,
        module_id,
        reason,
        failure_count,
        approval_method="auto",
        success=None,
        cost=0,
    ):
        """Log an escalation event to dispatch_escalation_log."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO dispatch_escalation_log
                (original_agent_id, original_model, escalated_model, escalated_provider,
                 capability, module_id, reason, failure_count, cost_usd,
                 approved_by, approval_method, success)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    original_agent_id,
                    original_model,
                    escalated_model,
                    escalated_provider,
                    capability,
                    module_id,
                    reason,
                    failure_count,
                    cost,
                    "system" if approval_method == "auto" else None,
                    approval_method,
                    success,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log escalation: {e}")

    # ========================================================================
    # CLOUD JOB VISIBILITY (temp bridge_jobs for 3D bridge view)
    # ========================================================================

    def _create_cloud_job(self, cloud_model, cloud_provider, station_code, capability, module_id):
        """Create a temporary bridge_job so cloud dispatches appear on the isometric bridge."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('cloud_dispatch', %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Cloud {capability}",
                    f"CLOUD→{cloud_model}",
                    station_code,
                    json.dumps(
                        {
                            "dispatch_station": "CLOUD",
                            "cloud_model": cloud_model,
                            "cloud_provider": cloud_provider,
                            "is_cloud": True,
                            "home_station": station_code,
                        }
                    ),
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return job_id
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Cloud job creation failed: {e}")
            return None

    def _complete_cloud_job(self, cloud_job_id, success=True):
        """Mark a temporary cloud job as completed/failed."""
        if not cloud_job_id:
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            status = "completed" if success else "failed"
            cur.execute(
                "UPDATE bridge_jobs SET status=%s, completed_steps=total_steps, " "completed_at=NOW() WHERE id=%s",
                (status, cloud_job_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Cloud job completion failed: {e}")

    # ========================================================================
    # BUDGET TRACKING
    # ========================================================================

    def _increment_agent_budget(self, agent_id: Optional[int], tokens_used: int = 0):
        """Increment agent's daily task count and token usage after successful dispatch."""
        if not agent_id:
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            # Reset if past the daily reset time, then increment
            cur.execute(
                """
                UPDATE agent_budgets
                SET current_task_count = 1, tokens_used_today = %s,
                    token_reset_at = NOW() + INTERVAL '1 day', updated_at = NOW()
                WHERE agent_id = %s AND token_reset_at < NOW()
            """,
                (tokens_used, agent_id),
            )
            if cur.rowcount == 0:
                # No reset needed — normal increment (or INSERT if row missing)
                cur.execute(
                    """
                    INSERT INTO agent_budgets (agent_id, current_task_count, tokens_used_today,
                        task_queue_limit, token_limit_per_day, token_reset_at, updated_at)
                    VALUES (%s, 1, %s, 10, 100000, NOW() + INTERVAL '1 day', NOW())
                    ON CONFLICT (agent_id) DO UPDATE SET
                        current_task_count = agent_budgets.current_task_count + 1,
                        tokens_used_today = agent_budgets.tokens_used_today + %s,
                        updated_at = NOW()
                """,
                    (agent_id, tokens_used, tokens_used),
                )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Budget increment skipped: {e}")

    # ========================================================================
    # DYNAMIC AGENT CREATION
    # ========================================================================

    # Suggested model defaults by station (use local free models)
    _STATION_DEFAULT_MODEL = {
        "COMMAND": "dolphin3-8k:latest",
        "ANALYTICS": "qwen25-classify:latest",
        "ENGINEERING": "qwen3-coder-cpu:latest",
        "OPERATIONS": "dolphin3-8k:latest",
        "CREATIVE": "dolphin3-8k:latest",
        "RESEARCH": "qwen3-coder-cpu:latest",
    }

    def _check_creation_duplicates(self, capability: str, station_code: str) -> Optional[str]:
        """Check for duplicate pending creation requests or recent creations.

        Returns a reason string if a duplicate is found, None if safe to create.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check autonomy_approval_queue for pending create_agent requests
            # with matching capability + station in action_data
            cur.execute(
                """
                SELECT id, reason, created_at
                FROM autonomy_approval_queue
                WHERE action_type = 'create_agent'
                  AND status = 'pending'
                  AND action_data->>'capability' = %s
                  AND action_data->>'station_code' = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (capability, station_code),
            )
            pending = cur.fetchone()
            if pending:
                cur.close()
                conn.close()
                return (
                    f"Pending creation request #{pending['id']} already exists "
                    f"for capability='{capability}' station='{station_code}' "
                    f"(created {pending['created_at']})"
                )

            # Check agent_creation_events for recent (24h) creations
            # with same capability + station
            cur.execute(
                """
                SELECT id, child_agent_id, created_at
                FROM agent_creation_events
                WHERE station_requested = %s
                  AND capabilities_requested ? %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (station_code, capability),
            )
            recent = cur.fetchone()
            cur.close()
            conn.close()

            if recent:
                return (
                    f"Agent (id={recent['child_agent_id']}) was already created "
                    f"for capability='{capability}' station='{station_code}' "
                    f"within the last 24h (event #{recent['id']}, "
                    f"created {recent['created_at']})"
                )

            return None  # Safe to create
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _check_creation_duplicates failed: {e}")
            return None  # Fail open — allow creation attempt

    def _request_agent_creation(self, capability: str, station_code: str, reason: str) -> bool:
        """Request dynamic agent creation via Telegram approval.

        Checks for duplicates first, then submits a tier-2 approval request.

        Returns True if request was submitted, False if blocked by dedup.
        """
        # Dedup check
        dup_reason = self._check_creation_duplicates(capability, station_code)
        if dup_reason:
            logger.info(f"[BridgeDispatcher] Agent creation blocked (duplicate): {dup_reason}")
            return False

        # Safety rails: max sub-agents and generation depth
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM agents WHERE parent_agent_id = 2")
            sub_count = cur.fetchone()[0]
            cur.execute("SELECT max_sub_agents FROM agent_budgets WHERE agent_id = 2")
            row = cur.fetchone()
            max_subs = row[0] if row else 20
            cur.close()
            conn.close()
            if sub_count >= max_subs:
                logger.warning(
                    f"[BridgeDispatcher] Max sub-agents reached ({sub_count}/{max_subs}), "
                    f"cannot create agent for {capability}"
                )
                return False
        except Exception as rail_err:
            logger.debug(f"[BridgeDispatcher] Safety rail check error: {rail_err}")

        # Build suggested agent profile
        suggested_model = self._STATION_DEFAULT_MODEL.get(station_code, "dolphin3-8k:latest")
        suggested_name = f"Auto-{station_code.capitalize()}-{capability.replace('_', '-').title()}"

        action_data = {
            "capability": capability,
            "station_code": station_code,
            "suggested_name": suggested_name,
            "suggested_model": suggested_model,
            "suggested_skills": [capability],
            "reason": reason,
        }

        try:
            from agent_loop import request_approval

            approval_id = request_approval(
                action_type="create_agent",
                action_data=action_data,
                reason=(
                    f"Skill gap: no available agent for capability='{capability}' "
                    f"at station='{station_code}'. {reason}. "
                    f"Suggested: {suggested_name} ({suggested_model})"
                ),
                requested_by="bridge_dispatcher",
                tier=2,
            )
            if approval_id:
                logger.info(
                    f"[BridgeDispatcher] Agent creation request #{approval_id} "
                    f"submitted for capability='{capability}' "
                    f"station='{station_code}'"
                )
                return True
            else:
                logger.warning(
                    "[BridgeDispatcher] request_approval returned None for " f"create_agent capability='{capability}'"
                )
                return False
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _request_agent_creation failed: {e}")
            return False

    def _create_agent_from_approval(self, approval_data: Dict) -> Optional[int]:
        """Create a new agent from an approved creation request.

        Inserts into: agents, agent_skills, agent_budgets,
        agent_emotional_state, agent_creation_events,
        governance_audit_log.

        Args:
            approval_data: The action_data dict from the approval queue entry.

        Returns:
            New agent_id on success, None on failure.
        """
        capability = approval_data.get("capability", "general")
        department = approval_data.get(
            "department",
            approval_data.get(
                "station_code",
                CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology"),
            ),
        )
        # If station_code was passed (legacy), map to department
        if department in DEPARTMENT_FLOOR_MAP:
            pass  # Already a department name
        else:
            # Legacy station code — map to department
            _LEGACY = {
                "COMMAND": "Executive Office",
                "ENGINEERING": "Engineering & Technology",
                "OPERATIONS": "Operations & Infrastructure",
                "SECURITY": "Security & Compliance",
                "CREATIVE": "Creative & Design",
                "RESEARCH": "Research & Development",
                "ANALYTICS": "Analytics & Intelligence",
                "COMMUNICATIONS": "Marketing & Communications",
            }
            department = _LEGACY.get(department, "Engineering & Technology")

        floor = DEPARTMENT_FLOOR_MAP.get(department, "ENGINEERING")
        suggested_name = approval_data.get("suggested_name", f"Auto-{capability}")
        suggested_model = approval_data.get(
            "suggested_model",
            "dolphin3-8k:latest",
        )
        suggested_skills = approval_data.get("suggested_skills", [capability])
        reason = approval_data.get("reason", "Dynamic creation via dispatcher")

        # Parse name for first_name / last_name
        parts = suggested_name.split("-", 1)
        first_name = parts[0] if parts else suggested_name
        last_name = parts[1] if len(parts) > 1 else ""

        try:
            # Single-writer path: create via agent_service for the core
            # fields then update_agent for lineage/audit extras (Project
            # #241 Track C.3). agent_service.create_agent also inserts
            # into agent_emotional_state, so the duplicate insert below
            # is removed.
            from services import agent_service

            # Honour the display_name the proposal actually filed. This used to always
            # synthesise "<Capability> Specialist" and DISCARD it, so propose_hire's
            # display_name argument was accepted, stored in action_data, and then thrown
            # away at creation ("Sift — Beat Classification Specialist" -> "Beat
            # Classification Specialist"). The synthesised title stays as the fallback for
            # older/auto proposals that carry no display_name.
            title = approval_data.get("display_name") or f"{capability.replace('_', ' ').title()} Specialist"
            system_prompt = (
                f"You are {suggested_name}, a specialist in {capability} " f"in the {department} department."
            )
            try:
                new_agent_id = agent_service.create_agent(
                    name=suggested_name,
                    display_name=title,
                    department=department,
                    model=suggested_model,
                    system_prompt=system_prompt,
                    temperature=0.5,
                    max_tokens=4096,
                    # An approved hire from propose_hire is an LLM agent — it
                    # carries a model + capability. 'internal' (the old hardcode)
                    # hid the new agent from every AI-roster/welfare surface
                    # keyed on worker_type='ai' (H.A.V.E.N. #431, 2026-07-28;
                    # P.R.O.O.F./Q.U.I.L.L. are 'ai').
                    worker_type="ai",
                    # Same defect family as the worker_type note above, and the last
                    # step that kept an approved hire from doing any work.
                    # agent_service.create_agent defaults shift_state='barracked', and
                    # this path never overrode it. A barracked agent is only ever woken
                    # by _wake_barracked_specialist, which fires ONLY when no ACTIVE
                    # candidate scores > 0 — so whenever the incumbent it was hired to
                    # relieve is itself active (always, that is the reason for hiring),
                    # the new agent is never selected. The hire looks complete in the
                    # roster and does nothing. A human explicitly approved this hire
                    # because capacity is needed NOW; it starts on duty.
                    shift_state="active",
                    tier=3,
                )
            except ValueError as ve:
                logger.error(
                    f"[BridgeDispatcher] Auto-create rejected: {ve} "
                    f"(department={department}, name={suggested_name})"
                )
                return None

            agent_service.update_agent(
                new_agent_id,
                first_name=first_name,
                last_name=last_name,
                title=title,
                cost_tier="free",
                agent_generation=1,
                parent_agent_id=2,
                created_by_agent_id=2,
            )

            # 2-5. Delegate sibling-table writes to agent_service (single-writer).
            # agent_emotional_state is already seeded by create_agent()
            # (stress=0.1, energy=0.9, mood='neutral') — no duplicate needed.
            for skill in suggested_skills:
                agent_service.add_skill(new_agent_id, skill, level=3, category=capability)

            agent_service.init_budget(new_agent_id)

            agent_service.log_creation_event(
                child_agent_id=new_agent_id,
                reason=reason,
                source="dispatcher",
                capabilities=suggested_skills,
                department=department,
            )

            # 6. Governance audit log — BEST-EFFORT bookkeeping. The agent, its
            # skills, budget and creation event already landed via agent_service
            # (single-writer); a bookkeeping hiccup must never convert a REAL
            # creation into "Creation returned None". That exact inversion hit
            # H.A.V.E.N. #431 on 2026-07-28: a refactor moved all writes to
            # agent_service but left this raw cur.execute behind with NO cursor
            # in scope, so EVERY approved hire NameError'd here, the approval
            # row read 'failed', and the live agent looked like it didn't exist.
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO governance_audit_log (
                        event_type, event_category, agent_id, action,
                        new_value, reason, outcome
                    ) VALUES (
                        'agent_created', 'autonomy', %s, 'create',
                        %s, %s, 'success'
                    )
                    """,
                    (
                        new_agent_id,
                        json.dumps(
                            {
                                "name": suggested_name,
                                "model": suggested_model,
                                "department": department,
                                "capability": capability,
                                "skills": suggested_skills,
                            }
                        ),
                        reason,
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as audit_exc:
                logger.warning(
                    "[BridgeDispatcher] governance audit for agent #%s failed "
                    "(agent IS created — bookkeeping only): %s",
                    new_agent_id,
                    audit_exc,
                )

            # Invalidate cache so the new agent gets picked up
            self._cache_time = 0

            logger.info(
                f"[BridgeDispatcher] Created agent #{new_agent_id} "
                f"'{suggested_name}' for capability='{capability}' "
                f"department='{department}'"
            )
            return new_agent_id

        except Exception as e:
            # No function-scoped connection remains (all writes go through
            # agent_service; the audit block manages its own) — the old
            # conn.rollback()/cur.close() here referenced names that no longer
            # exist and masked the real error path.
            logger.error(f"[BridgeDispatcher] _create_agent_from_approval failed: {e}")
            return None

    # ========================================================================
    # ========================================================================
    # FLEET DISPATCH
    # ========================================================================

    def _dispatch_to_remote_node(
        self,
        agent_info,
        capability,
        prompt,
        module_id,
        system_prompt,
        station_code,
        start_time,
    ):
        """Dispatch a job to a remote node via mesh_sync_log."""
        import json as _json

        node_id = agent_info["node_id"]
        agent_name = agent_info.get("name", "unknown")
        payload = {
            "capability": capability,
            "prompt": prompt,
            "module_id": module_id,
            "system_prompt": system_prompt,
            "target_agent": agent_name,
            "target_model": agent_info.get("model"),
            "station_codes": agent_info.get("station_codes", []),
        }

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, 'job_request', %s, 'sent', NOW())
                RETURNING id
                """,
                (node_id, _json.dumps(payload)),
            )
            sync_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Fleet dispatch DB error: {e}")
            # Fall back to ARCHIE on failure
            return DispatchResult(
                success=False,
                response=f"Fleet dispatch failed: {e}",
                agent_name="ARCHIE",
                agent_id=2,
                model_used="fallback",
                station_code=station_code,
                capability=capability,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[BridgeDispatcher] Fleet dispatch: job_request #{sync_id} "
            f"to {node_id} agent {agent_name} for '{capability}'"
        )

        return DispatchResult(
            success=True,
            response=f"Dispatched to fleet node {node_id} agent {agent_name}",
            agent_name=agent_name,
            agent_id=agent_info.get("id"),
            model_used=agent_info.get("model", "unknown"),
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            metadata={
                "fleet_dispatch": True,
                "sync_id": sync_id,
                "node_id": node_id,
                "hostname": agent_info.get("hostname"),
            },
        )

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    # Priority string → integer mapping for dispatch_pending_queue
    _PRIORITY_INT = {"low": 3, "normal": 5, "high": 7, "critical": 9}

    def request_work(
        self,
        capability: str,
        prompt: str,
        module_id: str = "unknown",
        system_prompt: Optional[str] = None,
        context: Optional[Dict] = None,
        user_id: Optional[int] = None,
        priority: str = "normal",
        json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
        timeout: int = 300,
        prefer_gpu: bool = True,
        job_id: Optional[int] = None,
        prefer_agent: Optional[str] = None,
        prefer_model: Optional[str] = None,
        model_override: Optional[str] = None,
        local_only: bool = False,
        project_id: Optional[int] = None,
        images: Optional[List[str]] = None,
        source_product: Optional[str] = None,
        preferred_node: Optional[str] = None,
        num_ctx: Optional[int] = None,
    ) -> DispatchResult:
        """
        Main entry point — request AI work by capability.

        Args:
            capability: What kind of work (e.g., 'classify', 'code', 'summarize')
            prompt: The work prompt
            module_id: Which module is requesting (for tracking)
            system_prompt: Override the agent's default system prompt
            context: Additional context dict
            user_id: User requesting the work
            priority: 'low', 'normal', 'high', 'critical'
            json_mode: Request JSON-formatted response
            timeout: Request timeout in seconds
            prefer_gpu: Whether to prefer GPU-capable models
            prefer_agent: Lock dispatch to this agent (for batch consistency).
                          The agent stays assigned for all items in a batch job.
            prefer_model: Lock dispatch to any agent using this Ollama model
                          (e.g., 'qwen2.5-coder:7b'). Resolved to the first
                          matching agent in the roster; if no agent uses the
                          model, routing falls back to capability-based
                          selection. Added for callers that need per-call
                          model pinning (benchmarks, warmup loops, targeted
                          code analysis) without binding to a specific agent
                          name. Task #2129.
            local_only: Force local-only routing (no cloud/external models).
                        Used by batch/loop jobs to avoid cloud escalation.

        Returns:
            DispatchResult with response, agent info, and metrics
        """
        start = time.time()

        # Per-capability timeout override (task #2130). When caller uses the
        # default (300), bump it for slow analytical capabilities. Explicit
        # caller timeouts (e.g., 120 for email_composition) are preserved.
        if timeout == 300 and capability in CAPABILITY_TIMEOUTS:
            timeout = CAPABILITY_TIMEOUTS[capability]

        # GPU-node affinity default (#3955). Heavy 7B+ work prefers the GPU
        # Starship cluster unless the caller pinned a node. A preference, not a
        # pin: offline/unfit Starships are skipped and routing continues to the
        # agent's stationed node, then hub, then cloud — so this is a no-op when
        # the cluster is offline. Explicit preferred_node always wins.
        if preferred_node is None and capability in CAPABILITY_NODE_AFFINITY:
            preferred_node = list(CAPABILITY_NODE_AFFINITY[capability])

        # P2-B (#381): complexity-aware right-sizing — a trivial, downgradeable task runs on a smaller
        # model so we stop burning a 7B on simple work. Flag complexity_routing_enabled (default OFF —
        # owner-gated rollout). Only when the caller pinned nothing; fully fail-open.
        if prefer_model is None and model_override is None and prefer_agent is None:
            try:
                if self._is_complexity_routing_enabled():
                    from services.complexity_router import right_size_model

                    _small = right_size_model(capability, prompt)
                    if _small:
                        prefer_model = _small
                        logger.info("[BridgeDispatcher] complexity right-size: %s -> %s", capability, _small)
            except Exception as _crp_err:
                logger.debug("[BridgeDispatcher] complexity routing skipped: %s", _crp_err)

        # Coordinator model-floor (#4702): lightweight meta-capabilities
        # (classify/sentiment/tagging/detect_language) run on the config-driven
        # small coordinator model unless the caller pinned a model. Guarantees
        # they never fall to a heavy 7B when the small-model pool agents are
        # momentarily resting or the agent cache lags a shift change. Escape
        # hatch: an explicit model_override/prefer_model wins. Kill switch:
        # platform_settings dispatch:coordinator_lane_enabled. Fail-open.
        try:
            from services.coordinator_lane import should_apply_floor, get_coordinator_model

            if should_apply_floor(capability, caller_pinned_model=bool(model_override or prefer_model)):
                model_override = get_coordinator_model()
                logger.info("[BridgeDispatcher] coordinator model-floor: %s -> %s", capability, model_override)
        except Exception as _cf_err:
            logger.debug("[BridgeDispatcher] coordinator floor skipped: %s", _cf_err)

        # Force-refresh busy agents list (bypass 30s welfare cache TTL)
        try:
            from psycopg2.extras import RealDictCursor

            bconn = self._get_db()
            bcur = bconn.cursor(cursor_factory=RealDictCursor)
            if job_id:
                # Exclude the current batch job — the assigned agent should be
                # available for work within its own batch, not blocked by it.
                bcur.execute(
                    "SELECT DISTINCT agent_name FROM bridge_jobs " "WHERE status = 'running' AND id != %s",
                    (job_id,),
                )
            else:
                bcur.execute("SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'")
            self._busy_agents = {r["agent_name"] for r in bcur.fetchall()}
            # Batch agent lock: always unblock the preferred agent so they
            # handle every item in the batch, not just the first.
            if prefer_agent:
                self._busy_agents.discard(prefer_agent)
            # Auto-resolve prefer_agent from job_id for batch consistency —
            # any caller that passes job_id gets the same agent automatically.
            if job_id and not prefer_agent:
                bcur.execute(
                    "SELECT agent_name FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = bcur.fetchone()
                if row and row["agent_name"]:
                    prefer_agent = row["agent_name"]
                    self._busy_agents.discard(prefer_agent)
            bcur.close()
            bconn.close()
        except Exception as busy_err:
            logger.debug(f"[BridgeDispatcher] Busy agents refresh failed: {busy_err}")

        # Auto-resolve prefer_agent from prefer_model (Task #2129). Callers
        # that need per-call model pinning (benchmarks, warmup loops, code
        # analysis on a specific model) can now pass prefer_model='...' and
        # get routed to the first roster agent using that model. Falls back
        # to capability routing if nothing matches — silent, no error.
        if prefer_model and not prefer_agent:
            try:
                for name, info in (self._agent_cache or {}).items():
                    agent_model = info.get("model") if isinstance(info, dict) else getattr(info, "model", None)
                    if agent_model and agent_model.lower() == prefer_model.lower():
                        prefer_agent = name
                        self._busy_agents.discard(prefer_agent)
                        logger.debug(
                            "[BridgeDispatcher] prefer_model=%s resolved to prefer_agent=%s",
                            prefer_model,
                            prefer_agent,
                        )
                        break
                if not prefer_agent:
                    logger.debug(
                        "[BridgeDispatcher] prefer_model=%s had no roster match — "
                        "falling back to capability routing",
                        prefer_model,
                    )
            except Exception as pm_err:
                logger.debug(
                    "[BridgeDispatcher] prefer_model resolution failed: %s",
                    pm_err,
                )

        # 0. SmartRouter advisory — classify task and recommend model tier
        #    This is a HINT, not a command. Existing systems (warm boot, RAM
        #    budget, Telegram approval) still control actual model selection.
        recommended_tier = None
        smart_route_info = {}
        detected_capability = None
        try:
            # Relative intra-package import — see _get_next_tier comment.
            from .smart_router import get_router

            router = get_router()
            task_type, detected_capability = router.classify_task(prompt, return_capability=True)
            # When caller provides an explicit capability, honour it — don't let
            # content classification override the routing intent. The comment at
            # the top of this block says "HINT, not a command"; this enforces it.
            if capability:
                detected_capability = capability
            routing_rec = router.suggest_model(task_type, complexity=5)
            recommended_tier = routing_rec.tier
            smart_route_info = {
                "task_type": task_type,
                "recommended_tier": recommended_tier,
                "recommended_model": routing_rec.model_name,
                "should_escalate": routing_rec.should_escalate,
                "estimated_cost": routing_rec.estimated_cost,
                "detected_capability": detected_capability,
            }
            logger.info(
                f"[DepartmentDispatcher] SmartRouter advisory: "
                f"task_type={task_type} tier={recommended_tier} "
                f"model={routing_rec.model_name} capability={detected_capability}"
            )
        except Exception as sr_err:
            logger.debug(f"[DepartmentDispatcher] SmartRouter advisory skipped: {sr_err}")

        # 1. Map capability → department
        _coord = get_dept_coordinator()
        capability_department = _coord.resolve_department(capability)
        home_department = self._resolve_module_department(module_id)

        agent = None
        dispatch_department = capability_department
        home_station = home_department or capability_department
        dispatch_station = capability_department
        capability_station = capability_department
        is_cross_station = False

        # skip_busy_refresh=True: request_work() already set _busy_agents
        # with proper job_id exclusion + prefer_agent handling above.
        # Don't let _refresh_welfare_cache() overwrite it.
        _sbr = bool(prefer_agent or job_id)

        # 1a. If prefer_agent is set, force-select that specific agent
        #     (used by benchmarks + the portrait-refine agent consultation).
        _pinned_agent = None
        if prefer_agent:
            if prefer_agent in self._agent_cache:
                _pinned_agent = self._agent_cache[prefer_agent]
            else:
                # #3462: the dispatcher's local _agent_cache can omit active
                # agents (TTL/build gaps), which silently dropped prefer_agent
                # and misrouted — e.g. the portrait-refine consult landed on
                # P.R.O.B.E. instead of the profile agent (W.A.R.D.E.N./V.I.G.I.L.).
                # Fall back to the authoritative agent_service cache so
                # prefer_agent reliably pins. Downstream agent.get(...) calls and
                # the int/dict skills handling tolerate this cache shape.
                try:
                    from services.agent_service import get_agent_cache as _svc_agent_cache

                    _svc_cache = _svc_agent_cache()
                    if prefer_agent in _svc_cache:
                        _pinned_agent = _svc_cache[prefer_agent]
                        logger.info(
                            "[BridgeDispatcher] prefer_agent=%s pinned via agent_service "
                            "fallback (missing from local _agent_cache)",
                            prefer_agent,
                        )
                except Exception as _pin_err:
                    logger.debug("[BridgeDispatcher] prefer_agent fallback lookup failed: %s", _pin_err)
        if _pinned_agent is not None:
            agent = _pinned_agent
            dispatch_department = agent.get("department", capability_department)
        else:
            # 1b. Department-based routing (primary path)
            agent = _coord.select_agent(
                capability,
                capability_department,
                recommended_tier=recommended_tier,
            )
            if agent:
                dispatch_department = capability_department
            elif home_department and home_department != capability_department:
                # 1c. Fallback: try home department
                agent = _coord.select_agent(
                    capability,
                    home_department,
                    recommended_tier=recommended_tier,
                )
                if agent:
                    dispatch_department = home_department
                    is_cross_station = True

        station_code = DEPARTMENT_FLOOR_MAP.get(dispatch_department, "ENGINEERING")

        # 1c-bis. Agentic tool-search eligibility (#3534). When eligible, force the
        # hub execution path (skip fleet routing) so the agent can run its native
        # /api/chat tool-loop on the hub model. The flag is default OFF, so this is
        # False in normal operation and fleet routing stays byte-for-byte unchanged.
        _agentic_eligible = bool(
            not json_mode
            and not images
            and capability in self._AGENTIC_TOOL_CAPABILITIES
            and isinstance(agent, dict)
            and agent.get("name") in self._AGENTIC_TOOL_AGENTS
            and self._is_agentic_tool_search_enabled()
        )

        # 1d. Node-preference: if selected hub agent is stationed on an online fleet
        # node, route inference there instead of hub Ollama. Falls through silently
        # if the node is offline or the dispatch fails.
        #
        # Guard with `not model_override`: when the caller hard-pins a model
        # (e.g. shared chat model qwen2.5:7b under local_only), keep the call on
        # the hub shared warm model rather than a node's roster model. The node
        # assignment uses `_node_assign['model']` and ignores model_override, so
        # routing a chat-with-override to a node would silently swap the pinned
        # model for the agent's heavy roster model. Defense-in-depth mirroring
        # Explicit per-call node preference (#3619, cluster fallback #3620). A
        # caller may pin a single node OR an ordered list of nodes (e.g.
        # E.T.H.O.S. grant drafting -> ['Starship-246','Starship-245'] for GPU
        # redundancy). Each candidate is tried in order via the verified
        # _get_fleet_node_for_dispatch + _dispatch_to_node path; the first that
        # serves wins. STRICTLY FAIL-SAFE: any miss (node offline/resting, stale
        # heartbeat, no model, no response, error) skips to the next candidate,
        # and if none serve the whole block falls through to the normal flow
        # below. preferred_node=None (every existing caller) -> block skipped.
        #
        # #4343 P1b interactive lane: derive the per-dispatch batch reserve ONCE here, before
        # any fleet-cap touchpoint. INTERACTIVE work (priority high/critical) uses reserve=0
        # (full cap -> can claim the reserved stream); BATCH (low/normal) uses the configured
        # reserve (default 1) so it's held to max_concurrent-1, leaving an interactive stream
        # free on MULTI-stream fleet nodes (a 1-stream node clamps to 1 and reserves nothing).
        # _node_cap_reserve() is fail-safe 0, so a disabled/misconfigured cap never starves
        # batch. The SAME _batch_reserve is threaded into the preferred_node skip, the
        # Node-preference _find_fleet_agent_for_hub_agent + _node_at_cap, and the score-routing
        # _node_at_cap below — one value so the soft ORDER-BY demotion and the hard skips agree.
        is_interactive = priority in ("high", "critical")
        _batch_reserve = 0 if is_interactive else self._node_cap_reserve()
        # #6081 AUX POWER phase 2: while a platform focus is active, hold ONE extra
        # stream back from NON-family BATCH work on capped fleet nodes, so focused
        # work always finds a slot. Rides the existing reserve lane end-to-end:
        # the same _batch_reserve is threaded into every cap check, _node_at_cap
        # clamps max(cap - reserve, 1) so a 1-stream node reserves nothing, the hub
        # is exempt by its WHERE clause, and interactive work keeps the full cap
        # (the branch above already zeroed it). Family work + keep-warm pings are
        # exempt via aux_reserve_applies (the reserve exists FOR the family, and
        # the focus warm ping must never be starved by its own reservation).
        # Kill-switch: platform_settings 'dispatch:node_cap:aux_reserve' = 0.
        if not is_interactive:
            _batch_reserve += self._aux_focus_reserve(module_id)
        if preferred_node and agent and not _agentic_eligible:
            _pn_candidates = list(preferred_node) if isinstance(preferred_node, (list, tuple)) else [preferred_node]
            _pn_model = (
                model_override or (agent.get("model") if isinstance(agent, dict) else getattr(agent, "model", "")) or ""
            )
            for _pn_name in _pn_candidates:
                if not _pn_name:
                    continue
                try:
                    _pn_db_id = None
                    _pn_conn = self._get_db()
                    try:
                        _pn_cur = _pn_conn.cursor()
                        _pn_cur.execute(
                            "SELECT id, max_concurrent FROM remote_nodes "
                            "WHERE (node_name = %s OR node_id = %s) "
                            "AND status = 'online' "
                            "AND last_heartbeat > NOW() - INTERVAL '3 minutes' LIMIT 1",
                            (str(_pn_name), str(_pn_name)),
                        )
                        _pn_row = _pn_cur.fetchone()
                        _pn_db_id = _pn_row[0] if _pn_row else None
                        _pn_max = max(int(_pn_row[1]), 1) if (_pn_row and _pn_row[1]) else 1
                    finally:
                        _pn_conn.close()
                    # #4343 per-node cap (+P1b lane reserve): skip a SATURATED pinned
                    # candidate (live running jobs >= its effective cap) so an explicit pin
                    # can't pile onto an already-full node. BATCH is held to
                    # max(max_concurrent - _batch_reserve, 1); INTERACTIVE uses the full cap
                    # (_batch_reserve=0). Gated + fail-open; on skip the loop tries the next
                    # candidate, then falls through to the normal flow below, so a dispatch
                    # is never dropped.
                    _pn_effective = max(_pn_max - _batch_reserve, 1)
                    if _pn_db_id and self._node_cap_enabled() and self._node_inflight_count(_pn_db_id) >= _pn_effective:
                        logger.info(
                            "[BridgeDispatcher] preferred_node %s at/over cap (eff=%s of max=%s, interactive=%s) "
                            "for '%s' — skipping to next candidate",
                            _pn_name,
                            _pn_effective,
                            _pn_max,
                            is_interactive,
                            capability,
                        )
                        continue
                    if _pn_db_id and _pn_model:
                        _pn_info = self._get_fleet_node_for_dispatch(
                            _pn_db_id, _pn_model, agent if isinstance(agent, dict) else None
                        )
                        if _pn_info:
                            _pn_res = self._dispatch_to_node(
                                agent_info=_pn_info,
                                prompt=prompt,
                                system_prompt=system_prompt,
                                options={"temperature": 0.7, **({"num_ctx": int(num_ctx)} if num_ctx else {})},
                                capability=capability,
                                module_id=module_id,
                                station_code=station_code,
                                user_id=user_id,
                                job_id=job_id,
                                json_mode=json_mode,
                                # #5810: the resolved per-capability budget, floored at the
                                # historical 240. The floor is load-bearing — an explicit
                                # SHORT caller timeout (e.g. 120 for email_composition, see
                                # the note above CAPABILITY_TIMEOUTS) must never shrink the
                                # fleet leg below the cold-load headroom that 240 exists to
                                # provide (KB #266396). Widening only; never narrowing.
                                timeout=max(timeout, 240),
                            )
                            if _pn_res and _pn_res.get("success"):
                                _pn_dur = int((time.time() - start) * 1000)
                                _pn_result = DispatchResult(
                                    success=True,
                                    response=_pn_res.get("response", ""),
                                    agent_name=_pn_info["agent_name"],
                                    # Attribute to the selected agent (routed to a preferred
                                    # node) — mirrors the score-routed branch below. Was
                                    # hardcoded None, so fleet-node-routed work counted toward
                                    # no agent's budget/K.I.N. welfare.
                                    agent_id=(agent.get("id") if isinstance(agent, dict) else None),
                                    model_used=_pn_info["model"],
                                    department=dispatch_department,
                                    capability=capability,
                                    duration_ms=_pn_dur,
                                    prompt_tokens=_pn_res.get("prompt_tokens", _pn_res.get("prompt_eval_count", 0)),
                                    completion_tokens=_pn_res.get("completion_tokens", _pn_res.get("eval_count", 0)),
                                    provider="fleet_node",
                                    metadata={
                                        "escalation": "preferred_node",
                                        "preferred_node": str(_pn_name),
                                        "node_id": _pn_info["node_id"],
                                        "node_name": _pn_info["node_name"],
                                        "node_hostname": _pn_info["node_hostname"],
                                        "is_remote": True,
                                    },
                                )
                                self._log_execution(_pn_result, module_id, user_id, job_id=job_id)
                                logger.info(
                                    "[BridgeDispatcher] preferred_node=%s served '%s' on %s",
                                    _pn_name,
                                    capability,
                                    _pn_info["node_name"],
                                )
                                return _pn_result
                    logger.info(
                        "[BridgeDispatcher] preferred_node candidate %s not viable for '%s' — trying next",
                        _pn_name,
                        capability,
                    )
                except Exception as _pn_exc:
                    logger.warning(
                        "[BridgeDispatcher] preferred_node candidate %s routing error (continuing): %s",
                        _pn_name,
                        _pn_exc,
                    )
            logger.info(
                "[BridgeDispatcher] no preferred_node candidate served '%s' — falling through to hub",
                capability,
            )

        # prefer_hub=local_only intent (task #3543, follow-up to #1306).
        if agent and not model_override and not _agentic_eligible:
            _hub_agent_id = agent.get("id") if isinstance(agent, dict) else getattr(agent, "id", None)
            if _hub_agent_id:
                _node_assign = self._find_fleet_agent_for_hub_agent(
                    _hub_agent_id,
                    prefer_hub=local_only,
                    department=(agent.get("department") if isinstance(agent, dict) else None),
                    reserve=_batch_reserve,
                )
                # #4343 P1c: if the agent's stationed FLEET node is at/over its
                # concurrency cap, drop the home-node pin and fall through to
                # score-routing/hub. Keyed by hub_agent_id, this path otherwise
                # pins a single stationed node, so the cap_term DEMOTION inside
                # _find_fleet_agent_for_hub_agent is a no-op (LIMIT 1 returns the
                # one saturated node anyway). Gated + fail-open; hub is never
                # skipped (bridge_priority>=100 -> _node_at_cap False), so
                # local_only/prefer_hub is unaffected. Fall-through, never a drop.
                if (
                    _node_assign
                    and self._node_cap_enabled()
                    and self._node_at_cap(_node_assign["node_id"], reserve=_batch_reserve)
                ):
                    logger.info(
                        "[BridgeDispatcher] Node-preference: %s@%s at/over cap (interactive=%s) for '%s' "
                        "— skipping stationed node, falling through to score-routing/hub (#4343)",
                        _node_assign["agent_name"],
                        _node_assign["node_name"],
                        is_interactive,
                        capability,
                    )
                    _node_assign = None
                if _node_assign:
                    logger.info(
                        "[BridgeDispatcher] Node-preference: %s@%s for '%s' (agent %s stationed on fleet)",
                        _node_assign["agent_name"],
                        _node_assign["node_name"],
                        capability,
                        _hub_agent_id,
                    )
                    _fleet_res = self._dispatch_to_node(
                        agent_info=_node_assign,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        options={"temperature": 0.7},
                        capability=capability,
                        module_id=module_id,
                        station_code=station_code,
                        user_id=user_id,
                        job_id=job_id,
                        json_mode=json_mode,
                        timeout=max(timeout, 240),  # #5810 — see the floor note above
                    )
                    if _fleet_res and _fleet_res.get("success"):
                        _dur_ms = int((time.time() - start) * 1000)
                        _node_result = DispatchResult(
                            success=True,
                            response=_fleet_res.get("response", ""),
                            agent_name=_node_assign["agent_name"],
                            # _node_assign is this same agent's fleet stationing (looked up by
                            # agent.get("id") above), so attribute to it — was hardcoded None.
                            agent_id=(agent.get("id") if isinstance(agent, dict) else None),
                            model_used=_node_assign["model"],
                            department=dispatch_department,
                            capability=capability,
                            duration_ms=_dur_ms,
                            prompt_tokens=_fleet_res.get("prompt_tokens", _fleet_res.get("prompt_eval_count", 0)),
                            completion_tokens=_fleet_res.get("completion_tokens", _fleet_res.get("eval_count", 0)),
                            provider="fleet_node",
                            metadata={
                                "escalation": "node_preferred",
                                "node_id": _node_assign["node_id"],
                                "node_name": _node_assign["node_name"],
                                "node_hostname": _node_assign["node_hostname"],
                                "is_remote": True,
                            },
                        )
                        self._log_execution(_node_result, module_id, user_id, job_id=job_id)
                        return _node_result

        # 1b. Score-based warm-path fleet routing — fires when no explicit
        #     node_agents entry exists. _pick_fleet_node() scores all online
        #     nodes; if a Starship or VPS wins (>20% better than hub), route
        #     the warm-model call there via mesh_ip. Fails open — any error
        #     falls through to normal hub execution. Gated by agent-mobility
        #     toggle (fleet_node_routing_enabled in system_config).
        #     Shift-state guard: don't route to fleet nodes if the agent is
        #     resting, in cooldown, or barracked — hub-local fallback only.
        _BLOCKED_SHIFT_STATES = {"resting", "cooldown", "barracked"}
        _agent_shift_state = (
            agent.get("shift_state") if isinstance(agent, dict) else getattr(agent, "shift_state", None)
        ) or "active"
        _agent_shift_blocked = _agent_shift_state in _BLOCKED_SHIFT_STATES
        if _agent_shift_blocked:
            logger.info(
                "[BridgeDispatcher] Warm-path fleet routing skipped — agent shift_state=%s (cap=%s)",
                _agent_shift_state,
                capability,
            )
        # `not model_override`: a hard-pinned model stays on the hub (where it's warm),
        # mirroring the node-preference guard above. Without this, score-routing sends the
        # pinned model to a fleet node that must COLD-SWAP it — a Starship 7B swap exceeds
        # the 240s _dispatch_to_node timeout, so the call burns ~242s then falls back to
        # the hub anyway (root cause of the #380 engine-plan latency; KB mistake #274021).
        if (
            agent
            and _fleet_routing_enabled()
            and not _agent_shift_blocked
            and not _agentic_eligible
            and not model_override
        ):
            # Resolve the agent's model once — `model` is not yet a local
            # variable at this point in request_work() (it's assigned later
            # in the hub-execute branch). Without this derivation, any
            # dispatch that reaches this block hits UnboundLocalError on
            # `model`. See ADR-005 for the broader image_gen routing context.
            _wp_model = ""
            if model_override:
                # Hard pin from caller (e.g., wtf_hub *_quick capabilities) —
                # overrides the agent's primary model so we don't promote
                # to qwen2.5:7b for a Tier-1 task.
                _wp_model = model_override
            elif isinstance(agent, dict):
                _wp_model = agent.get("model") or ""
            else:
                _wp_model = getattr(agent, "model", "") or ""
            _wp_node_id = _pick_fleet_node(_wp_model, agent if isinstance(agent, dict) else {})
            # #4343 P1c: don't score-route onto a saturated FLEET node. This block is
            # the immediate fall-through from the Node-preference skip above, and
            # _pick_fleet_node is colocation-biased + load-UNaware, so without this it
            # would re-pick the same full home node we just skipped. Treat a capped pick
            # as "hub" (overflow tier). Gated + fail-open; hub picks are never skipped.
            if (
                _wp_node_id is not None
                and self._node_cap_enabled()
                and self._node_at_cap(_wp_node_id, reserve=_batch_reserve)
            ):
                logger.info(
                    "[BridgeDispatcher] Score-routing pick (node id=%s) at/over cap "
                    "(interactive=%s) for '%s' — staying on hub (#4343)",
                    _wp_node_id,
                    is_interactive,
                    capability,
                )
                _wp_node_id = None
            if _wp_node_id is not None:
                _wp_info = self._get_fleet_node_for_dispatch(
                    _wp_node_id, _wp_model, agent if isinstance(agent, dict) else None
                )
                if _wp_info:
                    logger.info(
                        "[BridgeDispatcher] Score-routing '%s' (%s) → %s via mesh",
                        capability,
                        _wp_model,
                        _wp_info["node_name"],
                    )
                    _wp_res = self._dispatch_to_node(
                        agent_info=_wp_info,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        options={"temperature": 0.7},
                        capability=capability,
                        module_id=module_id,
                        station_code=station_code,
                        user_id=user_id,
                        job_id=job_id,
                        json_mode=json_mode,
                        timeout=max(timeout, 240),  # #5810 — see the floor note above
                    )
                    if _wp_res and _wp_res.get("success"):
                        _wp_dur = int((time.time() - start) * 1000)
                        _wp_result = DispatchResult(
                            success=True,
                            response=_wp_res.get("response", ""),
                            agent_name=(_wp_info["agent_name"]),
                            agent_id=(agent.get("id") if isinstance(agent, dict) else None),
                            model_used=_wp_model,
                            department=dispatch_department,
                            capability=capability,
                            duration_ms=_wp_dur,
                            prompt_tokens=_wp_res.get("prompt_tokens", _wp_res.get("prompt_eval_count", 0)),
                            completion_tokens=_wp_res.get("completion_tokens", _wp_res.get("eval_count", 0)),
                            provider="fleet_node",
                            metadata={
                                "escalation": "score_routed",
                                "node_name": _wp_info["node_name"],
                                # Use the PK int we already have in scope — _wp_info["node_id"]
                                # carries the TEXT identifier from remote_nodes.node_id and would
                                # fail node_used_id FK in task_execution_log (migration 384).
                                "node_id": _wp_node_id,
                                "node_text_id": _wp_info["node_id"],
                                "is_remote": True,
                            },
                        )
                        self._log_execution(_wp_result, module_id, user_id, job_id=job_id)
                        return _wp_result

        # 2. Fallback if no agent found — try cross-department, then fleet, then cloud
        department_exhausted = False
        if not agent:
            department_exhausted = True
            blocked_department = home_department or capability_department

            # 2a. Try agents from OTHER departments (cross-department dispatch)
            #     Skip Executive Office — ARCHIE is the commander, not a worker.
            #     Only pick agents that actually have the requested skill.
            aux_ok, aux_count, max_aux, aux_reason = self._station_aux_available(blocked_department)
            if not aux_ok:
                logger.info(
                    f"[BridgeDispatcher] {blocked_department} aux blocked: "
                    f"{aux_reason}. Skipping cross-department → cloud."
                )
            else:
                cross_dept_agent = _coord.find_cross_department_agent(capability, blocked_department)
                if cross_dept_agent:
                    agent = cross_dept_agent
                    dispatch_department = cross_dept_agent.get("department", capability_department)
                    station_code = DEPARTMENT_FLOOR_MAP.get(dispatch_department, "ENGINEERING")
                    is_cross_station = True
                    department_exhausted = False

        # 2b. Fleet node fallback — check remote nodes for available agents
        if not agent and department_exhausted:
            blocked_department = home_department or capability_department
            fleet_agent = self._find_fleet_agent(blocked_department, capability)
            if fleet_agent:
                logger.info(
                    f"[BridgeDispatcher] Fleet fallback: hub exhausted → "
                    f"dispatching to {fleet_agent['agent_name']}@"
                    f"{fleet_agent['node_name']} for '{capability}'"
                )
                fleet_result = self._dispatch_to_node(
                    agent_info=fleet_agent,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    options={"temperature": 0.7},
                    capability=capability,
                    module_id=module_id,
                    station_code=DEPARTMENT_FLOOR_MAP.get(blocked_department, "ENGINEERING"),
                    user_id=user_id,
                    job_id=job_id,
                    json_mode=json_mode,
                    timeout=max(timeout, 240),  # #5810 — see the floor note above
                )
                if fleet_result and fleet_result.get("success"):
                    duration_ms = int((time.time() - start) * 1000)

                    self._telegram_dispatch_advisory(
                        advisory_type="cross_station",
                        module_id=module_id,
                        home_station=blocked_department,
                        dispatch_station=f"FLEET→{fleet_agent['node_name']}",
                        capability=capability,
                        agent_name=fleet_agent["agent_name"],
                        reason=(
                            f"Hub agents busy in {blocked_department}. "
                            f"Dispatched to fleet node "
                            f"{fleet_agent['node_name']}."
                        ),
                    )

                    # Log capacity event for fleet dispatch
                    self._log_capacity_event(
                        department=blocked_department,
                        event_type="fleet_dispatch",
                        agent_name=fleet_agent["agent_name"],
                        capability=capability,
                        reason=(f"Fleet dispatch to {fleet_agent['node_name']} " f"({fleet_agent['node_hostname']})"),
                        metadata={
                            "node_id": fleet_agent["node_id"],
                            "node_name": fleet_agent["node_name"],
                            "model": fleet_agent["model"],
                            "is_remote": True,
                        },
                    )

                    result = DispatchResult(
                        success=True,
                        response=fleet_result.get("response", ""),
                        agent_name=fleet_agent["agent_name"],
                        # Cross-dept fallback: the CROSS-department fleet_agent ran the work
                        # (not the blocked home-dept agent), so attribute to fleet_agent's id
                        # to match agent_name above — was hardcoded None.
                        agent_id=(fleet_agent.get("hub_agent_id") if isinstance(fleet_agent, dict) else None),
                        model_used=fleet_agent["model"],
                        department=blocked_department,
                        capability=capability,
                        duration_ms=duration_ms,
                        prompt_tokens=fleet_result.get("prompt_tokens", 0),
                        completion_tokens=fleet_result.get("completion_tokens", 0),
                        provider="fleet_node",
                        metadata={
                            "escalation": "fleet_dispatch",
                            "blocked_department": blocked_department,
                            "home_department": home_department,
                            "department": blocked_department,
                            "is_cross_station": True,
                            "is_remote": True,
                            "node_id": fleet_agent["node_id"],
                            "node_name": fleet_agent["node_name"],
                            "node_hostname": fleet_agent["node_hostname"],
                        },
                    )
                    self._log_execution(result, module_id, user_id, job_id=job_id)
                    return result
                else:
                    logger.info(
                        f"[BridgeDispatcher] Fleet dispatch failed for " f"'{capability}' — falling through to cloud"
                    )

        if not agent and department_exhausted:
            blocked_department = home_department or capability_department

            # C.R.E.E.D. accounting-integrity Fix #3: no single agent was ever
            # matched here (that's what department_exhausted means), so any
            # cloud/contractor dispatch below has no specific "escalating
            # agent". Resolve the department's AI director as the best-effort
            # proxy owner ONCE — used only to attribute the eventual
            # task_execution_log row; routing/welfare/cost logic is untouched.
            _esc_agent_id, _esc_agent_name = resolve_department_escalation_owner(self._agent_cache, blocked_department)

            # 2c. Department at capacity — cloud is the fallback.
            #     Requires Telegram approval.
            routing_mode = "local_only" if local_only else self._get_routing_mode()
            if routing_mode != "local_only":
                try:
                    from agent_loop import request_approval

                    busy_names = [
                        self._agent_display(aname)
                        for aname, ainfo in self._agent_cache.items()
                        if ainfo.get("department") == blocked_department
                    ]
                    busy_str = ", ".join(busy_names) or blocked_department

                    logger.info(
                        f"[BridgeDispatcher] {blocked_department} at full capacity. "
                        f"Requesting cloud approval via Telegram."
                    )
                    request_approval(
                        action_type="cloud_throughput_escalation",
                        action_data={
                            "original_agent": busy_str,
                            "busy_job": {
                                "id": 0,
                                "description": (f"Department {blocked_department} at full capacity"),
                                "progress_pct": 0,
                            },
                            "escalated_model": self.FREE_CLOUD_MODELS[0],
                            "escalated_provider": "ollama_cloud",
                            "capability": capability,
                            "module_id": module_id,
                            "prompt_preview": prompt[:200] if prompt else "",
                            "department": blocked_department,
                        },
                        reason=(
                            f"Department {blocked_department} at full capacity. "
                            f"Approve cloud contractor for '{capability}'?"
                        ),
                        requested_by="bridge_dispatcher",
                        tier=2,
                    )
                except Exception as cloud_req_err:
                    logger.warning(f"[BridgeDispatcher] Cloud approval request failed: " f"{cloud_req_err}")

                # Also send Telegram advisory for visibility
                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_id,
                    home_station=blocked_department,
                    dispatch_station="CLOUD",
                    capability=capability,
                    reason=(
                        f"Department {blocked_department} at capacity " f"for '{capability}'. Cloud approval requested."
                    ),
                )

            # 2d. Capability-aware contractor routing (only if escalation_mode is auto)
            #     Queries contractor_providers by detected capability, tries in
            #     tier_position order (cheapest first). Falls back to legacy
            #     FREE_CLOUD_MODELS if no contractors match.
            escalation_mode = self._get_escalation_mode()
            if routing_mode != "local_only" and escalation_mode == "auto":
                # Use detected_capability from SmartRouter, fall back to request capability
                contractor_cap = detected_capability or capability
                contractors = self._find_contractors_for_capability(contractor_cap, max_tier=13)  # free tier first
                if not contractors:
                    # Broaden: try with text_chat as generic fallback
                    contractors = self._find_contractors_for_capability("conversation", max_tier=13)

                contractor_succeeded = False
                for contractor in contractors:
                    # #4659 — skip over-budget cloud providers up front so we don't
                    # even create a cloud job for them; the loop rotates to the next,
                    # and falls through to local when all free tiers are exhausted.
                    if not self._cloud_budget_ok(contractor["provider_key"], contractor_cap):
                        continue
                    logger.info(
                        f"[DepartmentDispatcher] Department {blocked_department} exhausted "
                        f"for '{capability}' (cap={contractor_cap}). "
                        f"Trying contractor: {contractor['display_name']} "
                        f"(tier {contractor['tier_position']})"
                    )
                    # Create visible bridge_job for 3D bridge view
                    cloud_job_id = self._create_cloud_job(
                        contractor.get("default_model") or contractor["provider_key"],
                        f"contractor:{contractor['provider_key']}",
                        DEPARTMENT_FLOOR_MAP.get(blocked_department, "ENGINEERING"),
                        capability,
                        module_id,
                    )
                    contractor_result = self._dispatch_to_contractor(
                        contractor=contractor,
                        prompt=prompt,
                        capability=capability,
                        module_id=module_id,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        timeout=timeout,
                        escalating_agent_id=_esc_agent_id,
                        escalating_agent_name=_esc_agent_name,
                    )
                    if contractor_result:
                        self._complete_cloud_job(cloud_job_id, success=True)
                        duration_ms = int((time.time() - start) * 1000)
                        contractor_result.duration_ms = duration_ms
                        contractor_result.department = blocked_department
                        contractor_result.metadata.update(
                            {
                                "blocked_department": blocked_department,
                                "home_department": home_department,
                                "is_cross_station": True,
                                "is_cloud": True,
                            }
                        )
                        self._telegram_dispatch_advisory(
                            advisory_type="free_cloud",
                            module_id=module_id,
                            capability=capability,
                            home_station=blocked_department,
                            cloud_model=contractor.get("default_model") or contractor["provider_key"],
                            cloud_provider=f"contractor:{contractor['provider_key']}",
                            reason=f"Department {blocked_department} at capacity",
                        )
                        self._log_capacity_event(
                            department=blocked_department,
                            event_type="cloud_contractor",
                            agent_name=contractor_result.agent_name,
                            capability=capability,
                            reason=f"Contractor {contractor['display_name']} for {capability}",
                            metadata={
                                "contractor": contractor["provider_key"],
                                "tier_position": contractor["tier_position"],
                                "module_id": module_id,
                                "detected_capability": contractor_cap,
                            },
                        )
                        self._log_execution(contractor_result, module_id, user_id, job_id=job_id)
                        return contractor_result
                    else:
                        self._complete_cloud_job(cloud_job_id, success=False)

                # Legacy fallback: try FREE_CLOUD_MODELS if no contractors matched
                if not contractors:
                    for cloud_model in self.FREE_CLOUD_MODELS:
                        logger.info(
                            f"[DepartmentDispatcher] No contractors for '{contractor_cap}'. "
                            f"Legacy fallback: {cloud_model}"
                        )
                        cloud_job_id = self._create_cloud_job(
                            cloud_model,
                            "ollama_cloud",
                            DEPARTMENT_FLOOR_MAP.get(blocked_department, "ENGINEERING"),
                            capability,
                            module_id,
                        )
                        llm_result = self._execute_llm(
                            model=cloud_model,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            json_mode=json_mode,
                            timeout=timeout,
                        )
                        if llm_result.get("success"):
                            self._complete_cloud_job(cloud_job_id, success=True)
                            duration_ms = int((time.time() - start) * 1000)
                            result = DispatchResult(
                                success=True,
                                response=llm_result.get("response", ""),
                                agent_name=f"CLOUD→{cloud_model}",
                                agent_id=None,
                                model_used=cloud_model,
                                department=blocked_department,
                                capability=capability,
                                duration_ms=duration_ms,
                                prompt_tokens=llm_result.get(
                                    "prompt_tokens",
                                    llm_result.get("prompt_eval_count", 0),
                                ),
                                completion_tokens=llm_result.get("completion_tokens", llm_result.get("eval_count", 0)),
                                provider="ollama_cloud",
                                metadata={
                                    "escalation": "department_exhausted_cloud",
                                    "blocked_department": blocked_department,
                                    "home_department": home_department,
                                    "department": blocked_department,
                                    "is_cross_station": True,
                                    "is_cloud": True,
                                    "cloud_model": cloud_model,
                                    "cloud_provider": "ollama_cloud",
                                },
                                escalating_agent_id=_esc_agent_id,
                                escalating_agent_name=_esc_agent_name,
                            )
                            self._log_execution(result, module_id, user_id, job_id=job_id)
                            return result
                        else:
                            self._complete_cloud_job(cloud_job_id, success=False)

            # 2e. Free cloud failed — request paid cloud via Telegram approval
            if routing_mode not in ("local_only", "local_cloud"):
                try:
                    from agent_loop import request_approval

                    next_tier = self._get_next_tier(self.FREE_CLOUD_MODELS[-1], capability)
                    if next_tier and next_tier.get("is_paid"):
                        logger.info(
                            f"[BridgeDispatcher] Free cloud failed. " f"Requesting paid cloud: {next_tier['model']}"
                        )
                        # Build agent display names for the notification
                        busy_names = [
                            self._agent_display(aname)
                            for aname, ainfo in self._agent_cache.items()
                            if ainfo.get("department") == blocked_department
                        ]
                        busy_str = ", ".join(busy_names) or blocked_department

                        request_approval(
                            action_type="cloud_throughput_escalation",
                            action_data={
                                "original_agent": busy_str,
                                "busy_job": {
                                    "id": 0,
                                    "description": f"All agents in {blocked_department} busy",
                                    "progress_pct": 0,
                                },
                                "escalated_model": next_tier["model"],
                                "escalated_provider": next_tier["provider"],
                                "capability": capability,
                                "module_id": module_id,
                                "prompt_preview": prompt[:200],
                                "department": blocked_department,
                            },
                            reason=(
                                f"All agents in {blocked_department} busy, "
                                f"free cloud failed. "
                                f"Escalate to {next_tier['model']}?"
                            ),
                            requested_by="bridge_dispatcher",
                            tier=2,
                        )
                        self._telegram_dispatch_advisory(
                            advisory_type="paid_cloud",
                            module_id=module_id,
                            capability=capability,
                            home_station=blocked_department,
                            cloud_model=next_tier["model"],
                            cloud_provider=next_tier.get("provider", "external"),
                        )
                except Exception as esc_err:
                    logger.warning(f"[BridgeDispatcher] Paid cloud request failed: {esc_err}")

            # Last resort: ARCHIE fallback
            try:
                self._request_agent_creation(
                    capability=capability,
                    station_code=DEPARTMENT_FLOOR_MAP.get(blocked_department, "ENGINEERING"),
                    reason=(
                        f"No available agent for capability='{capability}' "
                        f"in department='{blocked_department}' "
                        f"(module={module_id})"
                    ),
                )
            except Exception as creation_err:
                logger.debug(f"[BridgeDispatcher] Creation request skipped: {creation_err}")

            logger.warning(
                f"[BridgeDispatcher] No agent for capability='{capability}' "
                f"department='{blocked_department}', cloud unavailable, falling back to Executive Office"
            )
            agent = self._agent_cache.get(
                "ARCHIE",
                {
                    "id": 2,
                    "model": "dolphin3-8k:latest",
                    "system_prompt": None,
                    "temperature": 0.5,
                    "department": "Executive Office",
                },
            )
            station_code = "BRIDGE"
            dispatch_department = "Executive Office"

        # 2f. Fleet: if selected agent is on a remote node, dispatch via mesh
        #     (skipped when agentic-eligible so the hub tool-loop can run — #3534)
        if agent and agent.get("is_remote") and not _agentic_eligible:
            return self._dispatch_to_remote_node(
                agent,
                capability,
                prompt,
                module_id,
                system_prompt,
                station_code,
                start,
            )

        # 3. Determine model and system prompt
        # Caller's model_override (e.g., wtf_hub *_quick capabilities) wins
        # over the agent's primary model — see request_work() docstring.
        model = model_override or agent.get("model", "dolphin3-8k:latest")
        if not system_prompt:
            system_prompt = agent.get("system_prompt")
        temperature = agent.get("temperature", 0.5)

        # The agent dict returned by coordinator.select_agent() already has its
        # canonical name. The previous lookup-by-id-in-cache was both redundant
        # and silently buggy: if the chosen agent wasn't in self._agent_cache
        # (e.g. barracked specialist activated via wake-on-demand fallback in
        # #2217), it fell back to "ARCHIE" — corrupting agent_name in
        # task_execution_log for ~50% of dispatches and breaking welfare /
        # routing analytics that aggregate by name (Bug A, 2026-05-03).
        agent_name = agent.get("name") or "ARCHIE"

        # 3.45 Consent check — T3255 fairness pillar
        self._check_and_log_consent(
            agent_id=agent.get("id"),
            agent_name=agent_name,
            capability=capability,
            module_id=module_id,
        )

        # 3.5 Proficiency-aware augmentation
        skill_entry = agent.get("skills", {}).get(capability, {})
        if isinstance(skill_entry, int):
            proficiency_level = skill_entry
        else:
            proficiency_level = skill_entry.get("level", 1) if skill_entry else 1

        # Unpack into a DISTINCT var — do NOT reassign `model_override`, which
        # holds the caller's hard pin (e.g. shared chat model qwen2.5:7b under
        # local_only). The proficiency/skill-template override only takes effect
        # when the caller did NOT pin a model, so the caller's chat override is
        # never superseded by a roster/proficiency model (task #3543, follow-up
        # to #1306).
        augmented_prompt, proficiency_model = self._augment_for_proficiency(
            agent_name,
            capability,
            proficiency_level,
            system_prompt,
            "local_only" if local_only else self._get_routing_mode(),
        )
        system_prompt = augmented_prompt
        if proficiency_model and not model_override:
            model = proficiency_model

        logger.info(
            f"[BridgeDispatcher] Dispatching: capability='{capability}' → "
            f"agent='{agent_name}' model='{model}' department='{dispatch_department}' "
            f"module='{module_id}' proficiency=Lv{proficiency_level}"
        )

        # 3a. Cross-department Telegram advisory
        if is_cross_station and home_department:
            self._telegram_dispatch_advisory(
                advisory_type="cross_station",
                module_id=module_id,
                home_station=home_department,
                dispatch_station=dispatch_department,
                capability=capability,
                agent_name=agent_name,
            )

        # 3b. Inject learnings if available (proficiency scales card count)
        try:
            from bridge_learning import inject_learnings

            prompt = inject_learnings(
                agent_name,
                capability,
                prompt,
                proficiency_level=proficiency_level,
            )
        except ImportError:
            pass

        # 3c. Routing mode enforcement
        # Ensures the bridge UI toggle (local_only/local_cloud/full) controls dispatch
        routing_mode = "local_only" if local_only else self._get_routing_mode()
        is_cloud = ":cloud" in model or model in ("minimax-m2.5", "qwen3-coder-next")
        is_paid_external = any(model.startswith(p) for p in ("gpt-4o", "llama-3.1-sonar", "grok", "claude"))

        if routing_mode == "local_only" and (is_cloud or is_paid_external):
            logger.warning(
                f"[BridgeDispatcher] Blocked by routing_mode=local_only: "
                f"model='{model}' capability='{capability}' module='{module_id}'"
            )
            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent.get("id"),
                model_used=model,
                department=dispatch_department,
                capability=capability,
                error=f"Blocked: routing_mode=local_only, model={model} is cloud/external",
            )

        if routing_mode == "local_cloud" and is_paid_external:
            logger.warning(
                f"[BridgeDispatcher] Blocked by routing_mode=local_cloud: "
                f"model='{model}' capability='{capability}' module='{module_id}'"
            )
            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent.get("id"),
                model_used=model,
                department=dispatch_department,
                capability=capability,
                error=f"Blocked: routing_mode=local_cloud, model={model} is paid external",
            )

        # 3c-fix (#3665): escalation_mode=local_only also blocks explicit :cloud
        # model_override — without this check, callers that pass model_override=:cloud
        # bypass _try_cloud_escalation (which has the escalation_mode guard) entirely.
        if is_cloud and model_override:
            _escalation_mode = self._get_escalation_mode()
            if _escalation_mode == "local_only":
                logger.warning(
                    "[BridgeDispatcher] Blocked by escalation_mode=local_only "
                    "(explicit cloud override): model='%s' cap='%s' module='%s'",
                    model,
                    capability,
                    module_id,
                )
                return DispatchResult(
                    success=False,
                    response="",
                    agent_name=agent_name,
                    agent_id=agent.get("id"),
                    model_used=model,
                    department=dispatch_department,
                    capability=capability,
                    error=f"Blocked: escalation_mode=local_only, model_override={model_override} is cloud",
                )

        # 3d. Throughput escalation — if agent is busy, try cloud contractors
        # Exclude the caller's own job_id so a batch operation doesn't
        # escalate its own sub-dispatches to cloud.
        busy_job = self._check_agent_busy(agent_name, exclude_job_id=job_id)
        if busy_job and routing_mode != "local_only":
            escalated = self._try_cloud_escalation(
                agent_name=agent_name,
                busy_job=busy_job,
                capability=capability,
                prompt=prompt,
                module_id=module_id,
                system_prompt=system_prompt,
                json_mode=json_mode,
                timeout=timeout,
                routing_mode=routing_mode,
                station_code=station_code,
                user_id=user_id,
                job_id=job_id,
            )
            if escalated:
                return escalated
            # Otherwise fall through to dispatch to original agent anyway

        # ── Capacity event logging (ADR-055) ──
        occupancy = self._get_station_slot_occupancy(station_code)
        if is_cross_station:
            slot_number = occupancy["primary"] + occupancy["auxiliary"] + 1
            max_cap = occupancy["max_primary"] + occupancy["max_auxiliary"]
            cap_event_type = "auxiliary_filled" if slot_number <= max_cap else "overflow_dispatch"
        else:
            slot_number = occupancy["primary"] + 1
            cap_event_type = "primary_dispatch"
        self._log_capacity_event(
            department=station_code,
            event_type=cap_event_type,
            agent_id=agent.get("id") if agent else None,
            agent_name=agent_name,
            capability=capability,
            slot_number=slot_number,
            reason=f"{'cross-station' if is_cross_station else 'primary'} dispatch for {capability}",
            metadata={
                "module_id": module_id,
                "is_cross_station": is_cross_station,
            },
        )

        # 4. Execute — ComfyUI branch for image generation, LLM for everything else
        escalation_info = None  # Tracks failure→cloud escalation for metrics
        original_model = model  # Preserve for escalation metadata

        image_model = (context or {}).get("image_model") or agent.get("image_model")
        if capability == "image_generation" and image_model:
            # Route to ComfyUI instead of Ollama
            comfyui_result = self._execute_comfyui(
                agent_name=agent_name,
                agent=agent,
                image_model=image_model,
                prompt=prompt,
                context=context or {},
                station_code=station_code,
                capability=capability,
                module_id=module_id,
                user_id=user_id,
                job_id=job_id,
            )
            duration_ms = int((time.time() - start) * 1000)
            comfyui_result.duration_ms = duration_ms
            self._log_execution(comfyui_result, module_id, user_id, job_id=job_id)
            return comfyui_result

        # 4a-pre. Agentic tool-search loop (#3534 Phase 1) — flag-gated, hub-only,
        #     scoped to tool-capable agents. The agent issues its OWN KB searches
        #     via /api/chat tools=[] before answering. Runs BEFORE single-shot RAG;
        #     on no tool call or any error, llm_result stays None and the existing
        #     RAG + _execute_llm path below runs unchanged.
        llm_result = None
        agentic_info = None
        if (
            not json_mode
            and not images
            and capability in self._AGENTIC_TOOL_CAPABILITIES
            and agent_name in self._AGENTIC_TOOL_AGENTS
            and self._is_agentic_tool_search_enabled()
        ):
            try:
                from ai_bridge.agentic_search import is_tool_capable_model, run_tool_loop

                if is_tool_capable_model(model):
                    _loop = run_tool_loop(
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=prompt,
                        agent_name=agent_name,
                        agent_id=agent.get("id") if isinstance(agent, dict) else None,
                        capability=capability,
                        module_id=module_id,
                        write_enabled=self._is_agentic_tool_write_enabled(),
                    )
                    if _loop.get("used_tools") and _loop.get("success"):
                        _ar = _loop.get("response", "") or ""
                        # Real eval counts summed by run_tool_loop (#4230). Estimate as a
                        # fallback when Ollama omitted them (prompt-cache hit) so this work
                        # never logs as 0 tokens and reads as idle to K.I.N. welfare.
                        _apt = _loop.get("prompt_tokens", 0) or 0
                        _act = _loop.get("completion_tokens", 0) or 0
                        if not _apt and (prompt or system_prompt):
                            _apt = max(1, (len(system_prompt or "") + len(prompt or "")) // 4)
                        if not _act and _ar:
                            _act = max(1, len(_ar) // 4)
                        llm_result = {
                            "success": True,
                            "response": _ar,
                            "model": model,
                            "provider": "ollama",
                            "node_id": None,
                            "node_url": _loop.get("ollama_url"),
                            "response_ms": _loop.get("duration_ms", 0),
                            "prompt_tokens": _apt,
                            "completion_tokens": _act,
                        }
                        agentic_info = {
                            "agentic_tool_search": True,
                            "tool_calls": _loop.get("tool_calls", 0),
                            "tool_queries": _loop.get("tool_queries", []),
                            "iterations": _loop.get("iterations", 0),
                        }
                        self._log_agentic_tool_calls(
                            agent, capability, module_id, _loop.get("tool_queries", []), user_id
                        )
                        logger.info(
                            "[BridgeDispatcher] Agentic tool-loop: %s ran %d KB search(es) for %s",
                            agent_name,
                            _loop.get("tool_calls", 0),
                            capability,
                        )
            except Exception as _ag_err:
                logger.warning(
                    "[BridgeDispatcher] Agentic tool-loop error (%s) — falling back to RAG",
                    _ag_err,
                )
                llm_result = None

        # 4a. RAG auto-context injection (Task #1130)
        #     Prepend relevant KB entries to the prompt when enabled.
        #     Skips JSON mode (structured output) and image generation.
        #     Skipped when the agentic tool-loop already produced a response.
        rag_injected = False
        if llm_result is None and not json_mode and self._is_auto_context_enabled():
            try:
                rag_context = self._get_rag_context(prompt)
                if rag_context:
                    prompt = f"{rag_context}\n{prompt}"
                    rag_injected = True
                    logger.debug(
                        f"[BridgeDispatcher] RAG context injected " f"({len(rag_context)} chars) for {capability}"
                    )
            except Exception as rag_err:
                logger.debug(f"[BridgeDispatcher] RAG injection skipped: {rag_err}")

        # 4b. Role-grounding injection (PR-D, #381). Prepend the agent's role-relevant known
        #     mistakes (capability -> KB tags). Generalizes the code_review grounding to EVERY
        #     tool/reasoning capability. Independent of the heavy semantic RAG above; fires in
        #     json_mode too (it is context, not output). Skipped when the agentic tool-loop already
        #     ran (llm_result set). Flag rag_role_grounding (default on); excludes quarantined KB.
        if llm_result is None and self._is_role_grounding_enabled():
            try:
                role_ctx = self._get_role_mistakes(capability)
                if role_ctx:
                    prompt = f"{role_ctx}\n{prompt}"
                    logger.debug(f"[BridgeDispatcher] role-grounding injected ({len(role_ctx)} chars) for {capability}")
            except Exception as rg_err:
                logger.debug(f"[BridgeDispatcher] role-grounding skipped: {rg_err}")

        # Fix A (2026-05-09): CPU-only models (-cpu suffix) are too slow for
        # inline synchronous execution — a 9B model on CPU takes 10-15 min per
        # call, so concurrent dispatches cascade into 600s timeouts (KB mistake).
        # Route proactively to dispatch_pending_queue; model_dispatch_worker
        # serialises them one at a time when the model is warm.
        _is_cpu_model = bool(model and "-cpu" in model.lower())
        if llm_result is None and _is_cpu_model and priority != "critical" and not images:
            _cpu_model_str = str(model).strip().lower() if model else ""
            if _cpu_model_str and _cpu_model_str not in ("none", "null", "comfyui"):
                try:
                    from database import get_db_cursor as _get_db_cursor

                    _cpu_priority_int = self._PRIORITY_INT.get(priority, 5)
                    with _get_db_cursor(commit=True) as (_qconn2, _qcur2):
                        _qcur2.execute(
                            """
                            INSERT INTO dispatch_pending_queue
                                (capability, model_needed, model_type, prompt,
                                 system_prompt, json_mode, agent_name, agent_id,
                                 module_id, source_product, requested_by,
                                 user_id, priority, preferred_node_id)
                            VALUES (%s,%s,'llama',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id
                            """,
                            (
                                capability,
                                model,
                                prompt,
                                system_prompt,
                                json_mode,
                                agent.get("name") if agent else None,
                                agent.get("id") if agent else None,
                                module_id,
                                source_product or "archie_platform",
                                agent.get("name") if agent else "dispatcher",
                                user_id,
                                _cpu_priority_int,
                                # Bi-directional fleet routing: score all online nodes and
                                # escalate to better hardware when available (e.g. GPU Starship
                                # beats CPU VPS for GPU-preferred models). Colocation wins when
                                # home node scores within 80% of best.
                                _pick_fleet_node(model, agent),
                            ),
                        )
                        _cpu_row = _qcur2.fetchone()
                        _cpu_queue_id = _cpu_row["id"] if _cpu_row else None
                    logger.info(
                        "[BridgeDispatcher] CPU-model pre-queue: task #%s → %s "
                        "(cap=%s) — avoids inline 600s timeout",
                        _cpu_queue_id,
                        model,
                        capability,
                    )
                    return DispatchResult(
                        success=False,
                        queued=True,
                        response="",
                        agent_name=agent.get("name", "?") if agent else "?",
                        agent_id=agent.get("id") if agent else None,
                        model_used=model or "",
                        department=dispatch_department,
                        capability=capability,
                        duration_ms=int((time.time() - start) * 1000),
                        error=f"Queued (id={_cpu_queue_id}) — CPU model {model} serialised via queue",
                    )
                except Exception as _cpu_q_err:
                    logger.warning(
                        "[BridgeDispatcher] CPU-model pre-queue failed (%s) — "
                        "falling through to inline (may timeout)",
                        _cpu_q_err,
                    )

        if llm_result is None:
            llm_result = self._execute_llm(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=json_mode,
                prefer_gpu=prefer_gpu,
                temperature=temperature,
                timeout=timeout,
                agent_name=agent.get("name") if agent else None,
                capability=capability,
                module_id=module_id,
                images=images,
                num_ctx=num_ctx,
            )

        duration_ms = int((time.time() - start) * 1000)

        # 4b. Escalation on failure
        if not llm_result.get("success", False):
            # Fix B (2026-05-09): CPU-model timeouts should also queue, not just
            # cold-boot failures. This is the safety net for when Fix A's INSERT
            # fails and the call falls through to inline execution.
            # Fix C (2026-05-13): Extend to ALL models — GPU models (e.g.
            # mistral:7b) also cold-load under concurrent Repair Bay bursts and
            # should retry via queue. The priority != "critical" gate below
            # protects real-time requests (chat) from queueing.
            _err_str = (llm_result.get("error") or "").lower()
            _is_model_timeout = "timed out" in _err_str or "read timeout" in _err_str
            model_not_ready = llm_result.get("model_not_ready", False) or _is_model_timeout
            if _is_model_timeout:
                logger.warning(
                    "[BridgeDispatcher] model %s timed out for cap=%s (cpu=%s) — "
                    "treating as model_not_ready to trigger queue",
                    model,
                    capability,
                    _is_cpu_model,
                )

            # Background tasks (not critical) with cold models → queue for later.
            # The model_dispatch_worker will execute them when the model is warm.
            if model_not_ready and priority != "critical":
                # Guard: don't queue rows with sentinel/invalid model names.
                # The worker filters them, but writing them in the first place
                # is the actual bug (caller dispatched without resolving an
                # Ollama model — likely a non-LLM capability that shouldn't
                # have hit the queue). Drop here with a warning instead.
                _model_str = str(model).strip().lower() if model else ""
                if not _model_str or _model_str in ("none", "null", "comfyui"):
                    logger.warning(
                        "[BridgeDispatcher] Refusing to queue cap=%s with invalid model_needed=%r — non-LLM capability landed in LLM queue",
                        capability,
                        model,
                    )
                    return DispatchResult(
                        success=False,
                        queued=False,
                        response="",
                        agent_name=agent.get("name", "?") if agent else "?",
                        agent_id=agent.get("id") if agent else None,
                        model_used=model or "",
                        department=dispatch_department,
                        capability=capability,
                        duration_ms=int((time.time() - start) * 1000),
                        error=f"capability '{capability}' has no Ollama model — not queueable",
                    )

                try:
                    from database import get_db_cursor

                    priority_int = self._PRIORITY_INT.get(priority, 5)
                    with get_db_cursor(commit=True) as (_qconn, _qcur):
                        _qcur.execute(
                            """
                            INSERT INTO dispatch_pending_queue
                                (capability, model_needed, model_type, prompt,
                                 system_prompt, json_mode, agent_name, agent_id,
                                 module_id, source_product, requested_by,
                                 user_id, priority)
                            VALUES (%s,%s,'llama',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id
                            """,
                            (
                                capability,
                                model,
                                prompt,
                                system_prompt,
                                json_mode,
                                agent.get("name") if agent else None,
                                agent.get("id") if agent else None,
                                module_id,
                                source_product or "archie_platform",
                                agent.get("name") if agent else "dispatcher",
                                user_id,
                                priority_int,
                            ),
                        )
                        row = _qcur.fetchone()
                        queue_id = row["id"] if row else None
                    logger.info(
                        "[BridgeDispatcher] Queued task #%s for %s " "(model %s cold, priority=%s)",
                        queue_id,
                        capability,
                        model,
                        priority,
                    )
                    return DispatchResult(
                        success=False,
                        queued=True,
                        response="",
                        agent_name=agent.get("name", "?") if agent else "?",
                        agent_id=agent.get("id") if agent else None,
                        model_used=model,
                        department=dispatch_department,
                        capability=capability,
                        duration_ms=int((time.time() - start) * 1000),
                        error=f"Queued (id={queue_id}) — {model} not ready",
                        queue_id=queue_id,
                    )
                except Exception as _q_err:
                    logger.warning(
                        "[BridgeDispatcher] Queue insert failed (%s) — falling through to escalation",
                        _q_err,
                    )

            failure_count = self._track_failure(agent.get("id", 0), capability)
            # model_not_ready means the model wasn't loaded — not an agent failure.
            # Escalate immediately (threshold=1) so the task doesn't silently drop.
            threshold = 1 if model_not_ready else self._get_escalation_threshold()

            if failure_count >= threshold:
                next_tier = self._get_next_tier(model, capability)
                # If the model isn't in the tier map (e.g. qwen2.5:7b is an agent
                # model not registered as a dispatch tier), fall back to the local
                # tier so the task isn't silently dropped.
                if next_tier is None and model_not_ready:
                    try:
                        from .smart_router import get_router

                        router = get_router()
                        configs = router._get_model_configs()
                        fallback_tier = configs.get("local")
                        if fallback_tier:
                            next_tier = {
                                "tier": "local",
                                "model": fallback_tier.model_name,
                                "provider": fallback_tier.provider,
                                "is_paid": False,
                            }
                            logger.info(
                                f"[BridgeDispatcher] Model {model} not in tier map — "
                                f"falling back to local tier ({fallback_tier.model_name})"
                            )
                    except Exception as _fb_err:
                        logger.debug(f"[BridgeDispatcher] Tier fallback failed: {_fb_err}")
                if next_tier and not next_tier["is_paid"]:
                    logger.info(
                        f"[BridgeDispatcher] Auto-escalating {capability}: "
                        f"{model} -> {next_tier['model']} (free, {failure_count} failures)"
                    )
                    escalated_result = self._execute_llm(
                        model=next_tier["model"],
                        prompt=prompt,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        prefer_gpu=prefer_gpu,
                        timeout=timeout,
                        agent_name=agent.get("name") if agent else None,
                        capability=capability,
                        module_id=module_id,
                        images=images,
                    )
                    if escalated_result.get("success"):
                        self._reset_failure(agent.get("id", 0), capability)
                        self._log_escalation(
                            agent.get("id"),
                            model,
                            next_tier["model"],
                            next_tier["provider"],
                            capability,
                            module_id,
                            f"{failure_count} consecutive failures",
                            failure_count,
                            approval_method="auto",
                            success=True,
                        )
                        try:
                            from bridge_learning import capture_learning

                            capture_learning(
                                failed_result=llm_result,
                                success_result=escalated_result,
                                capability=capability,
                                agent_name=agent_name,
                                module_id=module_id,
                                failure_count=failure_count,
                            )
                        except ImportError:
                            pass
                        llm_result = escalated_result
                        model = next_tier["model"]
                        duration_ms = int((time.time() - start) * 1000)
                        escalation_info = {
                            "escalation": "failure_auto_escalation",
                            "original_model": original_model,
                            "is_cloud": True,
                            "cloud_model": next_tier["model"],
                            "cloud_provider": next_tier["provider"],
                            "failure_count": failure_count,
                        }
                elif next_tier and next_tier["is_paid"]:
                    logger.info(
                        f"[BridgeDispatcher] Paid escalation needed: {model} -> "
                        f"{next_tier['model']} ({next_tier['provider']}). Submitting for approval."
                    )
                    try:
                        from agent_loop import request_approval

                        request_approval(
                            action_type="escalation",
                            action_data={
                                "original_model": model,
                                "escalated_model": next_tier["model"],
                                "escalated_provider": next_tier["provider"],
                                "capability": capability,
                                "module_id": module_id,
                                "failure_count": failure_count,
                                "prompt_preview": prompt[:200],
                            },
                            reason=f"Escalation: {failure_count}x failures on {model} for {capability}",
                            tier=2,
                        )
                    except Exception as esc_err:
                        logger.warning(f"[BridgeDispatcher] Approval submission failed: {esc_err}")
                    self._log_escalation(
                        agent.get("id"),
                        model,
                        next_tier["model"],
                        next_tier["provider"],
                        capability,
                        module_id,
                        f"{failure_count} failures, awaiting approval",
                        failure_count,
                        approval_method="telegram",
                        success=None,
                    )
                    # Dashboard notification for paid cloud approval
                    self._telegram_dispatch_advisory(
                        advisory_type="paid_cloud",
                        module_id=module_id,
                        capability=capability,
                        home_station=home_station,
                        cloud_model=next_tier["model"],
                        cloud_provider=next_tier.get("provider", "external"),
                    )
        else:
            self._reset_failure(agent.get("id", 0), capability)

        # 5. Build result
        result_metadata = {
            "module_id": module_id,
            "priority": priority,
            "home_station": (agent.get("department") if agent and is_cross_station else home_station),
            "dispatch_station": home_station if is_cross_station else dispatch_station,
            "is_cross_station": is_cross_station,
            "capability_station": capability_station,
            "module_station": home_station,
            # Department routing metadata (Phase 2.2)
            "department": dispatch_department,
            "capability_department": capability_department,
            "agent_department": agent.get("department") if agent else None,
        }
        # Merge SmartRouter advisory info for observability
        if smart_route_info:
            result_metadata["smart_routing"] = smart_route_info
        # Merge failure-escalation flags so Bridge Command tracks contractor work
        if escalation_info:
            result_metadata.update(escalation_info)
        # Surface agentic tool-search provenance (#3534) for A.R.M.A.D.A. traffic
        if agentic_info:
            result_metadata["agentic"] = agentic_info

        result = DispatchResult(
            success=llm_result.get("success", False),
            response=llm_result.get("response", ""),
            agent_name=agent_name,
            agent_id=agent.get("id"),
            model_used=model,
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            prompt_tokens=llm_result.get("prompt_tokens", llm_result.get("prompt_eval_count", 0)),
            completion_tokens=llm_result.get("completion_tokens", llm_result.get("eval_count", 0)),
            provider=llm_result.get("provider", "ollama"),
            error=llm_result.get("error"),
            metadata=result_metadata,
        )

        # 6. Log for HR tracking
        self._log_execution(result, module_id, user_id, job_id=job_id)

        # 6b. Increment agent budget tracking (tokens + in-flight task counter).
        if result.success:
            if _HAS_AGENT_SERVICE:
                svc_increment_budget(
                    agent.get("id"),
                    tokens_used=result.prompt_tokens + result.completion_tokens,
                )
            else:
                self._increment_agent_budget(
                    agent.get("id"),
                    tokens_used=result.prompt_tokens + result.completion_tokens,
                )

            # Immediate (non-job-tracked) dispatches are synchronous — the work
            # is done by the time we return, so the in-flight slot must be
            # released here. Job-tracked dispatches (job_id set) decrement
            # via complete_job() instead. Without this, the counter drifts
            # upward on every translate/classify/etc. call and eventually
            # blocks the agent (see task #2100).
            if not job_id and _HAS_AGENT_SERVICE:
                try:
                    svc_decrement_budget(agent.get("id"))
                except Exception as dec_err:
                    logger.debug(
                        f"[BridgeDispatcher] immediate-dispatch decrement "
                        f"skipped for agent={agent.get('name')}: {dec_err}"
                    )

        return result

    def request_json(
        self,
        capability: str,
        prompt: str,
        module_id: str = "unknown",
        system_prompt: Optional[str] = None,
        user_id: Optional[int] = None,
        timeout: int = 120,
        project_id: Optional[int] = None,
        images: Optional[List[str]] = None,
        prefer_agent: Optional[str] = None,
        preferred_node=None,
        model_override: Optional[str] = None,
        local_only: bool = False,
    ) -> Dict:
        """
        Convenience method for JSON-mode requests.
        Returns parsed dict on success, None on failure.

        ``preferred_node`` (str or ordered list) pins the dispatch to a fleet
        node / cluster (e.g. a GPU Starship for the translation skill) — same
        contract as ``request_work``; None = normal routing.
        ``model_override`` hard-pins the model (e.g. a small co-fitting
        translate model); ``local_only`` forces local routing (no cloud). Both
        forward to ``request_work``; defaults preserve prior behaviour.
        """
        result = self.request_work(
            capability=capability,
            prompt=prompt,
            module_id=module_id,
            system_prompt=system_prompt,
            user_id=user_id,
            json_mode=True,
            timeout=timeout,
            project_id=project_id,
            images=images,
            prefer_agent=prefer_agent,
            preferred_node=preferred_node,
            model_override=model_override,
            local_only=local_only,
        )
        if result.success:
            try:
                return json.loads(result.response)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def get_model_for_capability(self, capability: str) -> str:
        """
        Get the model name for a capability without executing.
        Used by modules that need to know which model will handle their work
        (e.g., chat modules that use archie_bridge for conversation context).
        """
        department = CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")
        agent = get_dept_coordinator().select_agent(capability, department)
        if agent:
            return agent.get("model", "")
        return ""

    def log_external_call(
        self,
        capability: str,
        module_id: str,
        model_used: str,
        duration_ms: int = 0,
        success: bool = True,
        error: Optional[str] = None,
        user_id: Optional[int] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        """
        Log an AI call that happened outside the dispatcher (e.g., via archie_bridge).
        Ensures all AI activity appears in task_execution_log for HR tracking.

        FIX-3b (KB #270619): callers that ran a real LLM outside dispatch() (e.g. the
        Consciousness analysis loop via knowledge_analyzer) MUST pass real
        prompt/completion token counts. Otherwise this logs 0 tokens for genuine
        compute work — and since token-based welfare (welfare_load) keys fatigue off
        tokens, that work is invisible to K.I.N. and the agent reads as idle. This is
        exactly the 0-token-on-real-model case `_log_execution` flags as `[token-gap]`.
        """
        station_code = CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")
        agent = get_dept_coordinator().select_agent(capability, station_code)
        agent_name = "A.R.C.H.I.E."
        agent_id = 2
        if agent:
            agent_id = agent.get("id", 2)
            for name, info in self._agent_cache.items():
                if info.get("id") == agent_id:
                    agent_name = name
                    break

        result = DispatchResult(
            success=success,
            response="",
            agent_name=agent_name,
            agent_id=agent_id,
            model_used=model_used,
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            error=error,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._log_execution(result, module_id, user_id)

    # ========================================================================
    # C.R.E.E.D. GOVERNANCE INTEGRATION
    # ========================================================================

    def _log_governance(
        self,
        event_type: str,
        action: str,
        agent_name: Optional[str] = None,
        reason: Optional[str] = None,
        outcome: str = "success",
    ):
        """Log to governance_audit_log for Vigil overwatch.

        Makes batch job lifecycle visible to the C.R.E.E.D. transparency system.
        Uses direct DB insert (not creed_routes) because this may be called
        from background threads without a Flask request context.
        Failures are silently logged — governance logging should never block work.
        """
        try:
            agent_id = None
            if agent_name and agent_name in self._agent_cache:
                agent_id = self._agent_cache[agent_name].get("id")

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, reason, outcome)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (event_type, "bridge_dispatch", agent_id, action, reason, outcome),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Governance log skipped: {e}")

    def _telegram_dispatch_advisory(
        self,
        advisory_type: str,  # "cross_station", "free_cloud", "paid_cloud"
        module_id: str,
        capability: str,
        home_station: Optional[str] = None,
        dispatch_station: Optional[str] = None,
        agent_name: Optional[str] = None,
        cloud_model: Optional[str] = None,
        cloud_provider: Optional[str] = None,
        job_id: Optional[int] = None,
        reason: Optional[str] = None,
        is_overflow: bool = False,
    ):
        """Send Telegram advisory with context-appropriate buttons.

        All escalation types get interactive buttons so the user can
        acknowledge, override, or escalate further.
        """
        # Suppress per-request Telegram for high-volume batch capabilities
        # but ALWAYS notify on cloud escalations (free_cloud, paid_cloud)
        SILENT_CAPABILITIES = {"detect_language"}
        BATCH_SILENT_TYPES = {"cross_station", "same_station"}
        if capability in SILENT_CAPABILITIES and not is_overflow:
            logger.debug(
                f"[BridgeDispatcher] Silent advisory ({advisory_type}) " f"for batch capability '{capability}'"
            )
            return
        if capability == "translate" and advisory_type in BATCH_SILENT_TYPES:
            logger.debug(
                f"[BridgeDispatcher] Silent advisory ({advisory_type}) "
                f"for translate batch (cloud escalations still notify)"
            )
            return

        try:
            if advisory_type == "cross_station":
                # Get occupancy at the REQUESTING station (where work is needed),
                # not the agent's home station
                requesting = home_station or dispatch_station or "COMMAND"
                occ = self._get_station_slot_occupancy(requesting)
                slots_used = occ["total"]
                max_cap = occ["max_primary"] + occ["max_auxiliary"]
                is_over = slots_used > max_cap

                agent_label = self._agent_display(agent_name) if agent_name else "an agent"
                station_label = requesting
                home_label = dispatch_station or "another station"

                if is_over:
                    title = "Station Capacity Overflow"
                    message = (
                        f"Commander, {station_label} station is experiencing elevated "
                        f"request volume.\n\n"
                        f"All {max_cap} slots are occupied. "
                        f"{agent_label} from {home_label} "
                        f"dispatched as overflow (slot {slots_used}/{max_cap}) "
                        f"for {capability} task.\n\n"
                        f"Module: {module_id}"
                    )
                    notif_type = "warning"
                    emoji = "\u26a0\ufe0f"
                else:
                    title = "Cross-Station Dispatch"
                    message = (
                        f"Commander, {station_label} station needed assistance "
                        f"with {capability}.\n\n"
                        f"{agent_label} from {home_label} is assisting "
                        f"as auxiliary (slot {slots_used}/{max_cap}).\n\n"
                        f"Module: {module_id}"
                    )
                    notif_type = "info"
                    emoji = "\U0001f500"

                job_str = f" (job #{job_id})" if job_id else ""
                if job_str:
                    message += job_str
                if reason:
                    message += f"\n{reason}"

                # Buttons: OK (acknowledge) + Escalate to Cloud
                buttons = [
                    {"text": "\u2705 OK", "callback_data": "esc_ack"},
                    {
                        "text": "\u2601\ufe0f Escalate to Cloud",
                        "callback_data": "esc_cloud",
                    },
                ]

            elif advisory_type == "free_cloud":
                title = "Free Cloud Contractor"
                message = f"{module_id} '{capability}' \u2192 {cloud_model} " f"({cloud_provider or 'cloud'})"
                if reason:
                    message += f"\n{reason}"
                notif_type = "info"
                emoji = "\u2601\ufe0f"
                # Buttons: OK + Escalate to Paid
                buttons = [
                    {"text": "\u2705 OK", "callback_data": "esc_ack"},
                    {
                        "text": "\U0001f4b3 Escalate to Paid",
                        "callback_data": "esc_paid",
                    },
                ]

            elif advisory_type == "paid_cloud":
                title = "Paid Cloud Requested"
                message = (
                    f"{module_id} '{capability}' requesting {cloud_model} "
                    f"({cloud_provider})\nAwaiting your approval"
                )
                notif_type = "warning"
                emoji = "\u26a0\ufe0f"
                # Buttons handled by request_approval → _send_approval_telegram
                buttons = None

            else:
                return

            # 1. Insert system_notification for dashboard
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO system_notifications
                   (type, title, message, source, priority)
                   VALUES (%s, %s, %s, 'bridge_dispatcher', %s)""",
                (
                    notif_type,
                    title,
                    message,
                    "normal",
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            # 2. Send Telegram with buttons for cross_station + free_cloud
            if advisory_type in ("cross_station", "free_cloud") and buttons:
                try:
                    from services.telegram_service import send_with_buttons

                    send_with_buttons(
                        category="agent",
                        title=title,
                        message=message,
                        buttons=buttons,
                        source_agent="A.R.C.H.I.E.",
                        source_department="Executive Office",
                    )
                except Exception as tg_err:
                    logger.debug(f"[BridgeDispatcher] Telegram advisory skipped: {tg_err}")

            logger.info(f"[BridgeDispatcher] {title}: {message}")

        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Dispatch advisory failed: {e}")

    # ========================================================================
    # JOB MANAGEMENT
    # ========================================================================

    def create_job(
        self,
        job_type: str,
        module_source: str,
        description: str,
        total_steps: int,
        capability: Optional[str] = None,
        metadata: Optional[Dict] = None,
        project_id: Optional[int] = None,
    ) -> Optional[int]:
        """Create a new bridge job for tracking multi-step operations.

        Prevents duplicate jobs: if a running job with the same job_type
        and module_source already exists, returns None so callers know
        the job was rejected.

        Args:
            job_type: Job category (e.g. 'batch_translate', 'reindex').
            module_source: Module requesting the job.
            description: Human-readable description.
            total_steps: Total number of steps to complete.
            capability: Bridge capability key for agent resolution (e.g. 'translate').
                        Falls back to parsing from job_type if not provided.
            metadata: Additional job metadata (language, batch_size, etc.).
            project_id: Optional project ID to tag this job with.

        Returns:
            job_id on success, None on failure or duplicate.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # ── Advisory lock to prevent race conditions on concurrent create_job ──
            lock_key = hash(f"{job_type}:{module_source}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

            # ── Duplicate guard: block if same type+module already running ──
            # For jobs with repo metadata (GitHub), scope duplicate check per-repo
            repo_scope = (metadata or {}).get("repo")
            if repo_scope:
                cur.execute(
                    """
                    SELECT id FROM bridge_jobs
                    WHERE job_type = %s AND module_source = %s AND status = 'running'
                      AND metadata->>'repo' = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (job_type, module_source, repo_scope),
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM bridge_jobs
                    WHERE job_type = %s AND module_source = %s AND status = 'running'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (job_type, module_source),
                )
            existing = cur.fetchone()
            if existing:
                eid = existing[0] if isinstance(existing, (list, tuple)) else existing["id"]
                conn.rollback()
                cur.close()
                conn.close()
                logger.info(
                    f"[BridgeDispatcher] Duplicate job blocked: {job_type}/{module_source} "
                    f"already running as job #{eid}"
                )
                self._log_governance(
                    "batch_job",
                    "duplicate_blocked",
                    reason=f"Duplicate {job_type}/{module_source} blocked — job #{eid} already running",
                    outcome="blocked",
                )
                return None

            # Force-refresh busy agents from DB (inside advisory lock transaction)
            cur.execute("SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'")
            self._busy_agents = {r[0] for r in cur.fetchall()}

            # Resolve agent: try department routing first (post-rebrand),
            # fall back to station routing for backward compatibility
            cap_key = capability or job_type.split("_")[0]
            _coord = get_dept_coordinator()
            capability_dept = _coord.resolve_department(cap_key)

            agent = None
            dispatch_station = capability_dept
            home_station = capability_dept
            is_cross_station = False

            # Department-first routing (preferred)
            agent = _coord.select_agent(cap_key, capability_dept)
            if not agent:
                # Fallback to home department routing
                home_station = self._resolve_module_department(module_source)
                if home_station:
                    agent = _coord.select_agent(cap_key, home_station)
                    if agent:
                        dispatch_station = home_station
                    else:
                        agent = _coord.select_agent(cap_key, capability_dept)
                        is_cross_station = home_station != capability_dept
                else:
                    agent = _coord.select_agent(cap_key, capability_dept)

            station_code = dispatch_station
            blocked_station = home_station or capability_dept
            agent_name = None
            if agent:
                agent_name = agent.get("name") or agent.get("display_name")

            # ── Cross-station fallback (mirrors dispatch() logic) ──
            #     Enforce max_auxiliary: only 1 cross-station helper per station.
            #     Use a RealDictCursor on the SAME connection to share the
            #     transaction and its advisory lock, preventing race conditions.
            if not agent:
                blocked_station = home_station or capability_dept
                from psycopg2.extras import RealDictCursor

                aux_cur = conn.cursor(cursor_factory=RealDictCursor)
                aux_ok, aux_count, max_aux, aux_reason = self._station_aux_available(blocked_station, cur=aux_cur)
                aux_cur.close()

                if not aux_ok:
                    logger.info(
                        f"[BridgeDispatcher] create_job: {blocked_station} "
                        f"aux blocked: {aux_reason}. "
                        f"Skipping cross-department → cloud approval."
                    )
                else:
                    # Try cross-department dispatch
                    cross_agent = _coord.find_cross_department_agent(cap_key, blocked_station)
                    if cross_agent:
                        agent = cross_agent
                        agent_name = cross_agent.get("name") or cross_agent.get("display_name")
                        other_dept = cross_agent.get("department", blocked_station)
                        station_code = DEPARTMENT_FLOOR_MAP.get(other_dept, "ENGINEERING")
                        dispatch_station = other_dept
                        is_cross_station = True
                        logger.info(
                            f"[BridgeDispatcher] create_job cross-department: "
                            f"{blocked_station} → {other_dept} "
                            f"({self._agent_display(agent_name)}) "
                            f"for '{cap_key}'"
                        )

            if not agent_name:
                # Department at capacity — request cloud approval via Telegram
                # and REJECT the job so no orphan (agentless) jobs are created.
                blocked_dept = home_station or capability_dept
                logger.info(
                    f"[BridgeDispatcher] create_job: {blocked_dept} at "
                    f"full capacity for '{cap_key}'. Requesting cloud approval."
                )

                try:
                    from agent_loop import request_approval

                    busy_str = f"All agents in {blocked_dept}"

                    request_approval(
                        action_type="cloud_throughput_escalation",
                        action_data={
                            "original_agent": busy_str,
                            "busy_job": {
                                "id": 0,
                                "description": (
                                    f"Department {blocked_dept} at full capacity. " f"Job: {description or job_type}"
                                ),
                                "progress_pct": 0,
                            },
                            "escalated_model": self.FREE_CLOUD_MODELS[0],
                            "escalated_provider": "ollama_cloud",
                            "capability": cap_key,
                            "module_id": module_source,
                            "department": blocked_dept,
                        },
                        reason=(
                            f"Department {blocked_dept} at full capacity. "
                            f"Approve cloud for '{cap_key}' "
                            f"({description or job_type})?"
                        ),
                        requested_by="bridge_dispatcher",
                        tier=2,
                    )
                except Exception as cloud_err:
                    logger.warning(f"[BridgeDispatcher] Cloud approval request failed: " f"{cloud_err}")

                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_source,
                    home_station=blocked_station,
                    dispatch_station="CLOUD_PENDING",
                    capability=cap_key,
                    reason=(
                        f"All 3 slots at {blocked_station} are filled "
                        f"for '{cap_key}'. Cloud approval requested — "
                        f"job rejected until slot opens."
                    ),
                )

                # REJECT — do not create an orphan job with no agent
                return None

            # Enrich metadata with dispatch info
            # agent_station = the agent's actual home station (for visual shading)
            agent_home = agent.get("department") if agent else None
            enriched_meta = dict(metadata or {})
            enriched_meta["home_station"] = agent_home or home_station
            enriched_meta["dispatch_station"] = home_station if is_cross_station else dispatch_station
            enriched_meta["is_cross_station"] = is_cross_station
            enriched_meta["agent_station"] = agent_home
            enriched_meta["module_station"] = home_station

            # ── Capacity check: determine slot number (ADR-055) ──
            occupancy = self._get_station_slot_occupancy(station_code)
            if is_cross_station:
                slot_number = occupancy["max_primary"] + occupancy["auxiliary"] + 1
                if occupancy["auxiliary"] >= occupancy["max_auxiliary"]:
                    if not occupancy["allow_overflow"]:
                        logger.info(
                            f"[CAPACITY] {station_code} at capacity, overflow disabled — "
                            f"job still created but flagged"
                        )
                    slot_number = occupancy["primary"] + occupancy["auxiliary"] + 1
            else:
                slot_number = occupancy["primary"] + 1

            # ── Final DB-level guard: agent must not have another running job ──
            if agent_name:
                cur.execute(
                    """
                    SELECT id, description FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running'
                    LIMIT 1
                    """,
                    (agent_name,),
                )
                busy_row = cur.fetchone()
                if busy_row:
                    busy_id = busy_row[0]
                    busy_desc = busy_row[1]
                    conn.rollback()
                    cur.close()
                    conn.close()
                    logger.warning(
                        f"[BridgeDispatcher] Agent guard: {agent_name} already running "
                        f"job #{busy_id} ({busy_desc}) — cannot assign new job"
                    )
                    return None

            # ── Station capacity guard: check running jobs at this station ──
            cur.execute(
                """
                SELECT COUNT(*) FROM bridge_jobs
                WHERE station_code = %s AND status = 'running'
                """,
                (station_code,),
            )
            station_running = cur.fetchone()[0]
            max_station = occupancy.get("max_primary", 2) + occupancy.get("max_auxiliary", 1)
            if station_running >= max_station and not occupancy.get("allow_overflow"):
                conn.rollback()
                cur.close()
                conn.close()
                logger.warning(
                    f"[BridgeDispatcher] Station guard: {station_code} at capacity "
                    f"({station_running}/{max_station} running) — job rejected"
                )
                return None

            # Auto-detect project if not explicitly provided
            if project_id is None:
                project_id = _detect_project_id(f"{cap_key} {description}")

            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata, project_id)
                VALUES (%s, %s, %s, %s, 'running', %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    job_type,
                    module_source,
                    description,
                    total_steps,
                    agent_name,
                    station_code,
                    json.dumps(enriched_meta),
                    project_id,
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            logger.info(
                f"[BridgeDispatcher] Created job #{job_id}: {description} "
                f"({total_steps} steps, agent={agent_name}, station={station_code})"
            )

            # ── Schema validation: soft-validate input if schema specified ──
            input_schema = enriched_meta.get("input_schema")
            input_data = enriched_meta.get("input_data")
            if input_schema and input_data:
                is_valid, schema_errors = _validate_handoff_schema(input_data, input_schema)
                if not is_valid:
                    logger.warning(
                        f"[BridgeDispatcher] Job #{job_id} input schema "
                        f"'{input_schema}' validation failed: {schema_errors}"
                    )
                else:
                    logger.debug(f"[BridgeDispatcher] Job #{job_id} input validated " f"against '{input_schema}'")

            # ── Capacity event logging (ADR-055) ──
            cap_event_type = "primary_dispatch"
            if is_cross_station:
                max_cap = occupancy.get("max_primary", 2) + occupancy.get("max_auxiliary", 1)
                cap_event_type = "auxiliary_filled" if slot_number <= max_cap else "overflow_dispatch"
            self._log_capacity_event(
                department=capability_dept,
                event_type=cap_event_type,
                agent_id=agent.get("id") if agent else None,
                agent_name=agent_name,
                job_id=job_id,
                capability=cap_key,
                slot_number=slot_number,
                reason=f"{'cross-department' if is_cross_station else 'primary'} dispatch for {cap_key}",
                metadata={
                    "module_source": module_source,
                    "is_cross_station": is_cross_station,
                },
            )

            # ── Cross-station Telegram advisory ──
            if is_cross_station and home_station:
                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_source,
                    home_station=home_station,
                    dispatch_station=dispatch_station,
                    capability=cap_key,
                    agent_name=agent_name,
                    job_id=job_id,
                )

            # ── C.R.E.E.D. governance: log job creation for Vigil overwatch ──
            self._log_governance(
                "batch_job",
                "create_job",
                agent_name=agent_name,
                reason=f"Job #{job_id}: {description} ({total_steps} steps, module={module_source})",
                outcome="created",
            )

            # ── HR tracking: register workload on agent's budget ──
            # This makes _score_agent() see the load and eventually
            # block the agent / trigger escalation when limit is reached.
            if agent:
                if _HAS_AGENT_SERVICE:
                    svc_increment_budget(agent.get("id"), tokens_used=0)
                else:
                    self._increment_agent_budget(agent.get("id"), tokens_used=0)

            return job_id
        except Exception as e:
            logger.error(f"[BridgeDispatcher] create_job failed: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

    def update_job_progress(
        self,
        job_id: int,
        completed_steps: int,
        failed_steps: int = 0,
        metadata_update: Optional[Dict] = None,
    ) -> bool:
        """Update progress counters and merge metadata for a running job.

        Args:
            job_id: The job to update.
            completed_steps: New total completed steps.
            failed_steps: New total failed steps.
            metadata_update: Dict to merge into existing metadata.

        Returns:
            True on success.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            if metadata_update:
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET completed_steps = %s, failed_steps = %s,
                        metadata = metadata || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        completed_steps,
                        failed_steps,
                        json.dumps(metadata_update),
                        job_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET completed_steps = %s, failed_steps = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (completed_steps, failed_steps, job_id),
                )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] update_job_progress failed: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

    def complete_job(self, job_id: int, status: str = "auto") -> bool:
        """Mark a job as completed (or failed/cancelled).

        If status is 'auto' (default), determines the final status from
        the job's completed_steps and failed_steps:
        - All failed, zero completed → 'failed'
        - Zero completed, zero failed → 'cancelled'
        - Otherwise → 'completed'

        Args:
            job_id: The job to complete.
            status: Final status or 'auto' to determine from counters.

        Returns:
            True on success.
        """
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            if status == "auto":
                cur.execute(
                    "SELECT completed_steps, failed_steps, total_steps FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row:
                    completed, failed, total = row[0] or 0, row[1] or 0, row[2] or 0
                    if completed == 0 and failed == 0:
                        status = "cancelled"
                    elif completed == 0 and failed > 0:
                        status = "failed"
                    else:
                        status = "completed"
                else:
                    status = "completed"

            cur.execute(
                """
                UPDATE bridge_jobs
                SET status = %s, completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING agent_name, module_source, description,
                          completed_steps, failed_steps, total_steps,
                          job_type,
                          (EXTRACT(EPOCH FROM (NOW() - created_at)) * 1000)::int,
                          station_code,
                          metadata
                """,
                (status, job_id),
            )
            row = cur.fetchone()

            # Release the agent's budget slot. The paired increment happens in
            # _increment_budget() / svc_increment_budget() on dispatch, and
            # without this decrement the counter drifts upward until the agent
            # is silently blocked from dispatch (see task #2100). Clamped at 0.
            if row and row[0]:
                try:
                    cur.execute(
                        """UPDATE agent_budgets ab
                           SET current_task_count = GREATEST(
                                   0, COALESCE(current_task_count, 0) - 1
                               ),
                               updated_at = NOW()
                           FROM agents a
                           WHERE a.id = ab.agent_id AND a.name = %s""",
                        (row[0],),
                    )
                except Exception as dec_err:
                    logger.debug(f"[BridgeDispatcher] budget decrement failed for " f"{row[0]}: {dec_err}")

            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"[BridgeDispatcher] Job #{job_id} → {status}")

            # ── Schema validation: soft-validate output if schema specified ──
            if row and row[9]:
                try:
                    job_meta = row[9] if isinstance(row[9], dict) else json.loads(row[9])
                    output_schema = job_meta.get("output_schema")
                    output_data = job_meta.get("output_data")
                    if output_schema and output_data:
                        is_valid, schema_errors = _validate_handoff_schema(output_data, output_schema)
                        if not is_valid:
                            logger.warning(
                                f"[BridgeDispatcher] Job #{job_id} output schema "
                                f"'{output_schema}' validation failed: "
                                f"{schema_errors}"
                            )
                        else:
                            logger.debug(
                                f"[BridgeDispatcher] Job #{job_id} output " f"validated against '{output_schema}'"
                            )
                except Exception as schema_err:
                    logger.debug(f"[BridgeDispatcher] Job #{job_id} output schema " f"check skipped: {schema_err}")

            # ── C.R.E.E.D. governance: log job completion for Vigil overwatch ──
            if row:
                a_name = row[0]
                m_src = row[1]
                desc = row[2]
                c_steps = row[3] or 0
                f_steps = row[4] or 0
                t_steps = row[5] or 0
                j_type = row[6] or ""
                dur_ms = row[7] or 0
                job_station = row[8] or ""
                self._log_governance(
                    "batch_job",
                    "complete_job",
                    agent_name=a_name,
                    reason=(
                        f"Job #{job_id} {status}: {desc} "
                        f"({c_steps}/{t_steps} done, {f_steps} failed, module={m_src})"
                    ),
                    outcome=status,
                )

                # ── Capacity event: slot freed (ADR-055) ──
                if job_station:
                    agent_id_for_cap = None
                    if a_name and a_name in self._agent_cache:
                        agent_id_for_cap = self._agent_cache[a_name].get("id")
                    self._log_capacity_event(
                        department=job_station,
                        event_type="slot_freed",
                        agent_id=agent_id_for_cap,
                        agent_name=a_name,
                        job_id=job_id,
                        capability=j_type,
                        reason=f"Job {status} — slot freed",
                    )

                # ── HR tracking: log to task_execution_log + update welfare ──
                # This feeds the roster (recent tasks), agent performance stats,
                # and welfare (mood/stress/energy) so batch jobs are fully visible.
                if status in ("completed", "failed"):
                    agent_id = None
                    if a_name and a_name in self._agent_cache:
                        agent_id = self._agent_cache[a_name].get("id")
                    cap_key = j_type.split("_")[0] if j_type else "batch"
                    station_code = CAPABILITY_DEPARTMENT_MAP.get(cap_key, "Engineering & Technology")
                    batch_result = DispatchResult(
                        success=(status == "completed"),
                        response=f"Batch job #{job_id}: {desc}",
                        agent_name=a_name or "unassigned",
                        agent_id=agent_id,
                        model_used="batch",
                        station_code=station_code,
                        capability=j_type or "batch",
                        duration_ms=dur_ms,
                        error=f"{f_steps}/{t_steps} steps failed" if f_steps else None,
                    )
                    self._log_execution(batch_result, m_src or "unknown", job_id=job_id)

                # ── Server-side loop: auto-retrigger next batch ──
                try:
                    from services.loop_service import server_loop_retrigger

                    server_loop_retrigger(j_type, m_src, status)
                except Exception as loop_err:
                    logger.debug(f"[BridgeDispatcher] server_loop_retrigger skipped: {loop_err}")

            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] complete_job failed: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

    # ========================================================================
    # DURABLE EXECUTION — CHECKPOINTS (Task #955)
    # ========================================================================

    def save_checkpoint(self, job_id, step, total_steps, state=None):
        """Save checkpoint for a running job so it can be resumed on failure."""
        try:
            from database import get_db_cursor
            from psycopg2.extras import Json

            checkpoint = {
                "step": step,
                "total_steps": total_steps,
                "state": state or {},
                "checkpointed_at": datetime.now().isoformat(),
            }
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE bridge_jobs
                       SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{checkpoint}', %s)
                       WHERE id = %s""",
                    (Json(checkpoint), job_id),
                )
            logger.debug(f"[BridgeDispatcher] Checkpoint saved for job #{job_id} at step {step}/{total_steps}")
        except Exception as e:
            logger.debug(f"Checkpoint save failed for job {job_id}: {e}")

    def get_checkpoint(self, job_id):
        """Get checkpoint data for a job, or None if no checkpoint exists."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT metadata->'checkpoint' as checkpoint FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] else None
        except Exception as _exc:
            return None

    def resume_job(self, job_id):
        """Resume a failed job from its last checkpoint.

        Returns dict with resume info on success, None if job not resumable.
        """
        try:
            from database import get_db_cursor
            from psycopg2.extras import RealDictCursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT * FROM bridge_jobs WHERE id = %s AND status = 'failed'",
                    (job_id,),
                )
                job = cur.fetchone()
                if not job:
                    return None

                checkpoint = (job.get("metadata") or {}).get("checkpoint")
                if not checkpoint:
                    return None

                # Reset job to running, keep checkpoint intact for the executor
                cur.execute(
                    """UPDATE bridge_jobs
                       SET status = 'running', error_message = NULL,
                           completed_at = NULL, updated_at = NOW()
                       WHERE id = %s""",
                    (job_id,),
                )

            logger.info(f"[BridgeDispatcher] Job #{job_id} resumed from step {checkpoint.get('step')}")
            return {
                "job_id": job_id,
                "resume_from_step": checkpoint.get("step"),
                "state": checkpoint.get("state"),
            }
        except Exception as e:
            logger.debug(f"Resume job failed for {job_id}: {e}")
            return None

    # ========================================================================
    # STALE JOB REAPER
    # ========================================================================

    def reap_stale_jobs(self, max_age_minutes: int = 5, reason: str = "stale — no progress update") -> int:
        """Mark orphaned running jobs as failed.

        Background threads die on platform restart, leaving jobs stuck
        in 'running' state forever. This reaper finds jobs that haven't
        been updated in max_age_minutes and marks them failed.

        Called on startup (max_age_minutes=0) and periodically (max_age_minutes=5).

        Returns:
            Number of jobs reaped.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE bridge_jobs
                SET status = 'failed',
                    completed_at = NOW(),
                    updated_at = NOW(),
                    metadata = COALESCE(metadata, '{}'::jsonb)
                        || jsonb_build_object('reap_reason', %s)
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL '%s minutes'
                RETURNING id, job_type, description, completed_steps, total_steps
                """,
                (reason, max_age_minutes),
            )
            reaped = cur.fetchall()
            conn.commit()
            cur.close()
            conn.close()

            if reaped:
                for r in reaped:
                    jid = r[0] if isinstance(r, (list, tuple)) else r["id"]
                    desc = r[2] if isinstance(r, (list, tuple)) else r["description"]
                    logger.warning(f"[BridgeDispatcher] Reaped stale job #{jid}: {desc}")
                logger.info(f"[BridgeDispatcher] Stale job reaper: {len(reaped)} orphaned jobs cleaned up")
            return len(reaped)
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Stale job reaper failed: {e}")
            return 0

    # ========================================================================
    # CREW MANIFEST
    # ========================================================================

    # Hardware map: model → GPU or CPU
    MODEL_HARDWARE = {
        "dolphin3-8k:latest": "GPU",
        "dolphin3-8k": "GPU",
        "qwen25-classify:latest": "CPU",
        "qwen25-classify": "CPU",
        "arctic-embed-cpu:latest": "CPU",
        "arctic-embed-cpu": "CPU",
        "qwen3-coder-cpu:latest": "CPU",
        "qwen3-coder-cpu": "CPU",
        "minicpm-v-cpu:latest": "CPU",
        "minicpm-v-cpu": "CPU",
    }

    # Approximate model sizes in GB for VRAM/RAM fitting
    MODEL_SIZE_GB = {
        "qwen2.5:1.5b": 1.0,
        "smollm2:1.7b": 1.8,
        "llama3.2:3b": 2.0,
        "phi3.5": 2.2,
        "mistral:7b": 4.4,
        "qwen2.5-coder:7b": 4.7,
        "dolphin3": 4.9,
        "gemma2:9b": 5.4,
        "qwen2.5vl:7b": 6.0,
        "gemma3:12b": 8.1,
        "llama3.1:8b": 4.9,
        "aya:8b": 5.0,
        "qwen2.5:7b": 4.7,
    }

    def assign_agents_to_node(self, node_db_id: int, max_agents: int = 5) -> list:
        """
        Assign barracked agents to a node based on node hardware.

        Rules:
        - Check node's GPU VRAM and RAM from remote_nodes
        - Find barracked agents NOT already on this node
        - Prefer agents whose model size fits the node's VRAM (GPU advantage)
        - Assign up to max_agents
        - Set station_codes based on the node's station assignments
        - If barracked count drops to 5 or below, log advisory notification

        Returns: list of assigned agent names
        """
        from psycopg2.extras import RealDictCursor

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Get node hardware
            cur.execute(
                "SELECT id, gpu_vram_gb, ram_gb FROM remote_nodes WHERE id = %s",
                (node_db_id,),
            )
            node = cur.fetchone()
            if not node:
                logger.warning("assign_agents_to_node: node %s not found", node_db_id)
                return []

            gpu_vram = float(node["gpu_vram_gb"] or 0)
            ram_gb = float(node["ram_gb"] or 0)

            # 2. Get departments for this node (from node_station_assignments if available, else all)
            node_departments = []
            try:
                cur.execute(
                    """
                    SELECT bs.station_code
                    FROM node_station_assignments nsa
                    JOIN bridge_stations bs ON bs.id = nsa.station_id
                    WHERE nsa.node_id = %s AND nsa.is_active = TRUE
                    ORDER BY bs.station_code
                    """,
                    (node_db_id,),
                )
                node_departments = [r["station_code"] for r in cur.fetchall()]
            except Exception:
                pass  # node_station_assignments may not exist yet
            if not node_departments:
                # Default: accept agents from all departments
                node_departments = list(DEPARTMENT_FLOOR_MAP.keys())

            # 3. Find barracked agents NOT already on this node, with real model names
            cur.execute(
                """
                SELECT a.id, a.name, a.first_name, a.last_name,
                       a.display_name, a.title, a.model, a.gpu_tools,
                       a.department
                FROM agents a
                WHERE a.shift_state = 'barracked'
                  AND a.status = 'active'
                  AND (a.model LIKE '%%:%%' OR a.model LIKE '%%/%%')
                  AND a.id NOT IN (
                      SELECT hub_agent_id FROM node_agents
                      WHERE node_id = %s AND hub_agent_id IS NOT NULL
                  )
                ORDER BY a.name
                """,
                (node_db_id,),
            )
            candidates = cur.fetchall()

            if not candidates:
                logger.info(
                    "assign_agents_to_node: no eligible barracked agents for node %s",
                    node_db_id,
                )
                return []

            # 4. Score candidates: prefer models that fit VRAM, then smaller first
            def _score_agent(agent):
                model = agent["model"] or ""
                # Lookup known size or estimate from model name
                size = self.MODEL_SIZE_GB.get(model, None)
                if size is None:
                    # Try base name without tag
                    base = model.split(":")[0] if ":" in model else model
                    size = self.MODEL_SIZE_GB.get(base, 5.0)  # default 5GB

                fits_vram = size <= gpu_vram if gpu_vram > 0 else False
                fits_ram = size <= (ram_gb * 0.7) if ram_gb > 0 else False

                # Score: fits VRAM = 100 bonus, fits RAM = 50 bonus
                # Subtract size so smaller models are preferred (tie-breaker)
                score = 0
                if fits_vram:
                    score += 100
                if fits_ram:
                    score += 50
                score -= size  # prefer smaller
                return score

            candidates.sort(key=_score_agent, reverse=True)

            # 5. Build station allocation: COMMAND gets max 1, others get max 2
            # Use department-based slots (2 per department, 1 for Executive Office)
            dept_slots = {}
            for dept in node_departments:
                dept_slots[dept] = 1 if dept == "Executive Office" else 2

            # 6. Assign agents up to max_agents, distributing across departments
            assigned = []
            dept_fill = {d: 0 for d in node_departments}

            for agent in candidates:
                if len(assigned) >= max_agents:
                    break

                # Pick best department for this agent
                agent_dept = agent.get("department", "Engineering & Technology")
                target_station = None

                # Prefer the agent's own department
                if agent_dept in dept_slots and dept_fill.get(agent_dept, 0) < dept_slots.get(agent_dept, 2):
                    target_station = agent_dept
                else:
                    # Fall back to any department with capacity
                    for d in node_departments:
                        if dept_fill.get(d, 0) < dept_slots.get(d, 2):
                            target_station = d
                            break

                if not target_station:
                    # All departments full
                    continue

                # INSERT into node_agents
                cur.execute(
                    """
                    INSERT INTO node_agents (
                        node_id, source_agent_id, hub_agent_id,
                        name, first_name, last_name, display_name,
                        title, model, status, station_codes,
                        config_version, gpu_tools
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, 'active', %s,
                        1, %s
                    )
                    """,
                    (
                        node_db_id,
                        agent["id"],
                        agent["id"],
                        agent["name"],
                        agent.get("first_name"),
                        agent.get("last_name"),
                        agent["display_name"],
                        agent.get("title"),
                        agent["model"],
                        [target_station],
                        json.dumps(agent["gpu_tools"] or []),
                    ),
                )
                dept_fill[target_station] = dept_fill.get(target_station, 0) + 1
                assigned.append(agent["name"])
                logger.info(
                    "Assigned barracked agent %s (model=%s) to node %s station %s",
                    agent["name"],
                    agent["model"],
                    node_db_id,
                    target_station,
                )

            conn.commit()

            # 7. Check remaining barracked count — advisory if <= 5
            if assigned:
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM agents
                    WHERE shift_state = 'barracked' AND status = 'active'
                    """
                )
                remaining = cur.fetchone()["cnt"]
                if remaining <= 5:
                    # Advisory only — Department HQ shows pool status
                    logger.warning("Barracked agent pool low: %d remaining", remaining)

            logger.info(
                "assign_agents_to_node: assigned %d agents to node %s: %s",
                len(assigned),
                node_db_id,
                assigned,
            )
            return assigned

        except Exception as _exc:
            conn.rollback()
            logger.exception("assign_agents_to_node failed for node %s", node_db_id)
            return []
        finally:
            conn.close()

    def get_crew_manifest(self) -> list:
        """
        Build a live roster of every agent's real-time status.

        Joins: agents, agent_emotional_state,
               bridge_jobs (running), task_execution_log (24h), knowledge_base.
        """
        self._refresh_agent_cache()
        if not self._agent_cache:
            return []

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Wellness (emotional state) per agent ---
            cur.execute(
                """
                SELECT agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
            """
            )
            wellness_map = {
                r["agent_id"]: {
                    "stress": float(r["stress_level"] or 0),
                    "energy": float(r["energy_level"] or 0),
                    "mood": r["current_mood"] or "neutral",
                }
                for r in cur.fetchall()
            }

            # --- Active jobs (running) per agent ---
            cur.execute(
                """
                SELECT id, agent_name, description,
                       total_steps, completed_steps
                FROM bridge_jobs
                WHERE status = 'running'
            """
            )
            jobs_map = {}
            for j in cur.fetchall():
                total = j["total_steps"] or 1
                completed = j["completed_steps"] or 0
                pct = round((completed / total) * 100, 1) if total > 0 else 0
                jobs_map[j["agent_name"]] = {
                    "id": j["id"],
                    "description": j["description"],
                    "progress_pct": pct,
                }

            # --- 24h dispatch stats per agent ---
            cur.execute(
                """
                SELECT agent_name,
                       COUNT(*) AS dispatches,
                       AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                       AVG(duration_ms) AS avg_duration_sec
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY agent_name
            """
            )
            stats_map = {}
            for r in cur.fetchall():
                stats_map[r["agent_name"]] = {
                    "dispatches": r["dispatches"],
                    "success_rate": round(float(r["success_rate"] or 0), 2),
                    "avg_duration_sec": round(float(r["avg_duration_sec"] or 0) / 1000, 1),
                }

            # --- Learning count per agent (from task_execution_log unique capabilities) ---
            cur.execute(
                """
                SELECT agent_name, COUNT(DISTINCT capability) AS cnt
                FROM task_execution_log
                WHERE success = TRUE
                  AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY agent_name
            """
            )
            learning_map = {r["agent_name"]: r["cnt"] for r in cur.fetchall()}

            # --- Rest cycles (check if agent is resting) ---
            cur.execute(
                """
                SELECT agent_id
                FROM agent_rest_cycles
                WHERE ended_at IS NULL
            """
            )
            resting_ids = {r["agent_id"] for r in cur.fetchall()}

            cur.close()
            conn.close()

            # --- Ollama loaded models (for LLM readiness) ---
            loaded_models = {}  # model_name -> size_gb
            gpu_models_live = set()  # models currently on GPU (size_vram > 0)
            try:
                import requests as _req
                import os

                _ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
                _ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
                _ps_resp = _req.get(f"http://{_ollama_host}:{_ollama_port}/api/ps", timeout=5)
                if _ps_resp.status_code == 200:
                    for m in _ps_resp.json().get("models", []):
                        mname = m.get("name", "")
                        msize = m.get("size", 0) / (1024**3)  # bytes→GB
                        vram_bytes = m.get("size_vram", 0)
                        # Store both full name and without :latest
                        loaded_models[mname] = round(msize, 1)
                        if mname.endswith(":latest"):
                            loaded_models[mname.replace(":latest", "")] = round(msize, 1)
                        # Track GPU models by live VRAM usage
                        if vram_bytes and vram_bytes > 0:
                            gpu_models_live.add(mname)
                            if mname.endswith(":latest"):
                                gpu_models_live.add(mname.replace(":latest", ""))
            except Exception as _exc:
                pass  # Ollama unavailable — all agents show as "swap"

            # Get disk sizes for all models (to estimate swap eligibility)
            model_disk_gb = {}
            try:
                _tags_resp = _req.get(f"http://{_ollama_host}:{_ollama_port}/api/tags", timeout=5)
                if _tags_resp.status_code == 200:
                    for m in _tags_resp.json().get("models", []):
                        mname = m.get("name", "")
                        disk_gb = round(m.get("size", 0) / (1024**3), 1)
                        model_disk_gb[mname] = disk_gb
                        if mname.endswith(":latest"):
                            model_disk_gb[mname.replace(":latest", "")] = disk_gb
            except Exception as _exc:
                pass

            # RAM budget for swap eligibility
            _swap_buffer_gb = 10.0
            try:
                import psutil as _ps

                _total_ram = _ps.virtual_memory().total / (1024**3)
                _swap_buffer_gb = round(_total_ram * 0.80 * 0.10, 1)
            except Exception as _exc:
                pass

            # Station codes per agent (derived from department → floor mapping)
            station_codes_map = {}  # agent_id → [floor_code, ...]
            try:
                sc_conn = self._get_db()
                sc_cur = sc_conn.cursor(cursor_factory=RealDictCursor)
                sc_cur.execute(
                    """
                    SELECT id, department FROM agents WHERE status = 'active'
                """
                )
                for r in sc_cur.fetchall():
                    aid = r["id"]
                    dept = r.get("department", "Engineering & Technology")
                    floor = DEPARTMENT_FLOOR_MAP.get(dept, "ENGINEERING")
                    station_codes_map[aid] = [floor]
                sc_cur.close()
                sc_conn.close()
            except Exception as sc_err:
                logger.debug(f"[BridgeDispatcher] station_codes query failed: {sc_err}")

            # Deployed agents → node lookup (agent_id → {node_db_id, node_name})
            deployed_node_map = {}
            try:
                dn_conn = self._get_db()
                dn_cur = dn_conn.cursor(cursor_factory=RealDictCursor)
                dn_cur.execute(
                    """
                    SELECT na.hub_agent_id, rn.id as node_db_id,
                           rn.node_name, rn.hostname as node_hostname
                    FROM node_agents na
                    JOIN remote_nodes rn ON rn.id = na.node_id
                    WHERE na.hub_agent_id IS NOT NULL AND na.status = 'active'
                """
                )
                for r in dn_cur.fetchall():
                    deployed_node_map[r["hub_agent_id"]] = {
                        "node_db_id": r["node_db_id"],
                        "node_name": r["node_name"],
                        "node_hostname": r["node_hostname"],
                    }
                dn_cur.close()
                dn_conn.close()
            except Exception as e:
                logger.debug(f"[BridgeDispatcher] station_codes query failed: {e}")
                pass

            # Node loaded models — query each node's /api/ps for deployed agents
            node_loaded_models = {}  # agent_id → set of loaded model names
            _checked_nodes = {}
            for aid, ninfo in deployed_node_map.items():
                nid = ninfo["node_db_id"]
                if nid not in _checked_nodes:
                    try:
                        import requests as _nreq

                        dn2_conn = self._get_db()
                        dn2_cur = dn2_conn.cursor(cursor_factory=RealDictCursor)
                        dn2_cur.execute(
                            "SELECT hostname, port FROM remote_nodes WHERE id = %s",
                            (nid,),
                        )
                        nr = dn2_cur.fetchone()
                        dn2_cur.close()
                        dn2_conn.close()
                        if nr:
                            ps = _nreq.get(
                                f"http://{nr['hostname']}:{nr['port']}/api/ps",
                                timeout=3,
                            )
                            if ps.status_code == 200:
                                _checked_nodes[nid] = {m["name"] for m in ps.json().get("models", [])}
                            else:
                                _checked_nodes[nid] = set()
                        else:
                            _checked_nodes[nid] = set()
                    except Exception as _exc:
                        _checked_nodes[nid] = set()
                node_loaded_models[aid] = _checked_nodes[nid]

            # Build manifest — hub agents only, skip fleet: prefixed node copies
            manifest = []
            for name, info in self._agent_cache.items():
                if name.startswith("fleet:"):
                    continue
                agent_id = info["id"]
                model = info.get("model", "")

                # Reconcile stale deployed state — if agent claims
                # deployed but no active node_agents record exists, treat
                # as returned to hub (node went offline).
                _shift = info.get("shift_state", "active")
                if _shift == "deployed" and agent_id not in deployed_node_map:
                    _shift = "barracked"

                # Determine status
                if agent_id in resting_ids:
                    status = "resting"
                elif name in jobs_map:
                    status = "working"
                else:
                    status = "idle"

                # Hardware: use live VRAM data, fall back to static map
                image_model = info.get("image_model")
                if model in gpu_models_live:
                    hw = "GPU"
                elif image_model:
                    # Agent has a GPU tool (e.g. ComfyUI image gen)
                    hw = "GPU"
                else:
                    hw = self.MODEL_HARDWARE.get(model, "CPU")

                # LLM readiness: check node Ollama for deployed agents, hub for others
                _is_deployed = _shift == "deployed"
                _agent_loaded = node_loaded_models.get(agent_id, set()) if _is_deployed else set()

                if model and model.endswith(":cloud"):
                    llm_status = "cloud"
                    llm_size_gb = 0
                elif (
                    _is_deployed
                    and model
                    and (
                        model in _agent_loaded
                        or model.replace(":latest", "") in {m.replace(":latest", "") for m in _agent_loaded}
                    )
                ):
                    llm_status = "loaded"
                    llm_size_gb = model_disk_gb.get(model, 0)
                elif not _is_deployed and model and model in loaded_models:
                    llm_status = "loaded"
                    llm_size_gb = loaded_models[model]
                else:
                    # Estimate runtime size (~1.3x disk) to check swap fit
                    disk_gb = model_disk_gb.get(model, 0)
                    est_runtime_gb = round(disk_gb * 1.3, 1)
                    llm_size_gb = est_runtime_gb
                    if est_runtime_gb > 0 and est_runtime_gb <= _swap_buffer_gb:
                        llm_status = "swap"
                    elif disk_gb == 0:
                        # Model not downloaded or unknown
                        llm_status = "barracked"
                    else:
                        llm_status = "barracked"

                first = info.get("first_name", "")
                last = info.get("last_name", "")
                full_name = f"{first} {last}".strip() if (first or last) else name

                # GPU tools (ComfyUI image gen, future: video)
                gpu_tools = []
                if image_model:
                    gpu_tools.append(
                        {
                            "type": "image_generation",
                            "model": image_model,
                            "provider": "comfyui",
                        }
                    )

                manifest.append(
                    {
                        "name": name,
                        "display_name": info.get("display_name") or full_name,
                        "full_name": full_name,
                        "title": info.get("title", ""),
                        "id": agent_id,
                        "agent_id": agent_id,
                        "station": DEPARTMENT_FLOOR_MAP.get(
                            info.get("department", "Engineering & Technology"),
                            "ENGINEERING",
                        ),
                        "department": info.get("department", "Engineering & Technology"),
                        "is_department_ai": info.get("is_department_ai", False),
                        "station_codes": station_codes_map.get(agent_id, []),
                        "shift_state": _shift,
                        "model": model,
                        "image_model": image_model,
                        "hardware": hw,
                        "gpu_tools": gpu_tools,
                        "llm_status": llm_status,
                        "llm_size_gb": llm_size_gb,
                        "status": status,
                        "wellness": wellness_map.get(
                            agent_id,
                            {
                                "stress": 0.0,
                                "energy": 1.0,
                                "mood": "neutral",
                            },
                        ),
                        "current_job": jobs_map.get(name),
                        "stats_24h": stats_map.get(
                            name,
                            {
                                "dispatches": 0,
                                "success_rate": 0.0,
                                "avg_duration_sec": 0,
                            },
                        ),
                        "learning_count": learning_map.get(name, 0),
                        "node_db_id": deployed_node_map.get(agent_id, {}).get("node_db_id"),
                        "node_name": deployed_node_map.get(agent_id, {}).get("node_name"),
                        "node_hostname": deployed_node_map.get(agent_id, {}).get("node_hostname"),
                        "location": (
                            f"node:{deployed_node_map[agent_id]['node_name']}"
                            if agent_id in deployed_node_map
                            else "hub"
                        ),
                    }
                )

            return manifest

        except Exception as e:
            logger.error(f"[BridgeDispatcher] get_crew_manifest failed: {e}")
            return []

    def get_dispatch_status(self) -> Dict:
        """Get current dispatch status for all departments (Phase 6: Bridge Command)."""
        self._refresh_agent_cache()

        departments = {}
        for name, info in self._agent_cache.items():
            dept = info.get("department", "Engineering & Technology")
            if dept not in departments:
                departments[dept] = {"agents": [], "active": True}
            departments[dept]["agents"].append(
                {
                    "name": name,
                    "id": info["id"],
                    "model": info["model"],
                    "status": "active",
                }
            )

        return {
            "total_agents": len(self._agent_cache),
            "total_departments": len(departments),
            "departments": departments,
            # Backward compat
            "total_stations": len(departments),
            "stations": departments,
        }

    # ========================================================================
    # AGENTS-AS-TOOLS — Lightweight hierarchical delegation (Task #959)
    # ========================================================================

    def delegate_subtask(self, parent_job_id: int, capability: str, prompt: str, timeout: int = 60) -> Dict[str, Any]:
        """Delegate a subtask to another agent without creating a full Bridge job.

        Used for quick agent-to-agent delegation within a workflow.
        E.g. an analyst agent can ask a scanner agent for a quick nmap check.

        Returns the result directly (synchronous within timeout).
        """
        try:
            import requests

            # Find the right department for this capability
            department = get_dept_coordinator().resolve_department(capability)

            # Get an active agent model for this department
            from database import get_db_cursor
            from psycopg2.extras import RealDictCursor

            model = None
            with get_db_cursor(commit=False) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT a.model FROM agents a
                    WHERE a.department = %s
                      AND a.status = 'active'
                      AND a.shift_state = 'active'
                    LIMIT 1
                    """,
                    (department,),
                )
                row = cur.fetchone()
                if row:
                    model = row["model"]

            if not model:
                return {
                    "success": False,
                    "error": f"No available agent for capability={capability} (department={department})",
                }

            # Route through Bridge call_ollama (ADR-013 compliance)
            from ai_bridge.archie_bridge import call_ollama

            result_text = call_ollama(model, prompt, timeout=timeout)

            if result_text:
                result = {"response": result_text}
                logger.info(
                    f"Subtask delegated: parent_job={parent_job_id}, " f"capability={capability}, model={model}"
                )

                # Track delegation in parent job metadata
                try:
                    from psycopg2.extras import Json

                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """
                            UPDATE bridge_jobs
                            SET metadata = jsonb_set(
                                COALESCE(metadata, '{}'),
                                '{delegations}',
                                COALESCE(metadata->'delegations', '[]'::jsonb) || %s::jsonb
                            )
                            WHERE id = %s
                            """,
                            (
                                Json(
                                    [
                                        {
                                            "capability": capability,
                                            "model": model,
                                            "timestamp": datetime.now().isoformat(),
                                        }
                                    ]
                                ),
                                parent_job_id,
                            ),
                        )
                except Exception as _exc:
                    pass

                return {
                    "success": True,
                    "response": result.get("response", result_text),
                    "model": model,
                }

            return {
                "success": False,
                "error": f"No response from model {model}",
            }
        except Exception as e:
            logger.debug(f"Subtask delegation failed: {e}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # MODEL ORCHESTRATION — 3-tier warm/cold management
    # ========================================================================

    def get_host_capacity(self, node_db_id=None):
        """
        Return capacity info for a host (hub or fleet node).

        Args:
            node_db_id: Integer DB id from remote_nodes table.
                        None = hub (local Ollama).

        Returns dict with gpu_vram_total/used/free, ram_total/used/free,
        loaded_models list, and comfyui status.
        """
        if node_db_id is not None:
            return self._get_node_capacity(node_db_id)
        return self._get_hub_capacity()

    def _get_hub_capacity(self):
        """Capacity for the local hub Ollama instance."""
        ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
        ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
        ollama_url = f"http://{ollama_host}:{ollama_port}"
        hostname = ollama_host
        port = int(ollama_port)

        result = {
            "hostname": hostname,
            "port": port,
            "gpu_vram_total": 0.0,
            "gpu_vram_used": 0.0,
            "gpu_vram_free": 0.0,
            "ram_total": 0.0,
            "ram_used_by_models": 0.0,
            "ram_free": 0.0,
            "loaded_models": [],
            "comfyui_active": False,
            "comfyui_vram_gb": 0.0,
        }

        # -- GPU info from Ollama /api/ps (size_vram on loaded models) --
        # Hub GPU: Quadro M4000 8GB
        gpu_vram_total = 8.0  # Known hardware
        gpu_vram_used = 0.0

        # -- Loaded models --
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                models_data = ps_resp.json().get("models", [])
                for m in models_data:
                    name = m.get("name", "unknown")
                    size_vram = m.get("size_vram", 0) / (1024**3)  # bytes→GB
                    size_total = m.get("size", 0) / (1024**3)
                    size_ram = max(0.0, size_total - size_vram)
                    result["loaded_models"].append(
                        {
                            "name": name,
                            "vram_gb": round(size_vram, 2),
                            "ram_gb": round(size_ram, 2),
                            "expires_at": m.get("expires_at", ""),
                        }
                    )
                    gpu_vram_used += size_vram
                    result["ram_used_by_models"] += size_ram
        except Exception as e:
            logger.warning(f"[ModelOrch] Hub /api/ps failed: {e}")

        result["gpu_vram_total"] = gpu_vram_total
        result["gpu_vram_used"] = round(gpu_vram_used, 2)
        result["gpu_vram_free"] = round(max(0, gpu_vram_total - gpu_vram_used), 2)
        result["ram_used_by_models"] = round(result["ram_used_by_models"], 2)

        # -- System RAM (best-effort via Ollama /api/tags or known value) --
        # Hub has 128GB, 80% budget = ~102GB for models
        ram_total = 102.0  # ADR-078 budget
        result["ram_total"] = ram_total
        result["ram_free"] = round(max(0, ram_total - result["ram_used_by_models"]), 2)

        # -- ComfyUI status --
        try:
            comfyui_host = os.getenv("COMFYUI_HOST", "http://host.docker.internal:8188")
            cu_resp = requests.get(f"{comfyui_host}/system_stats", timeout=5)
            if cu_resp.status_code == 200:
                cu_data = cu_resp.json()
                devices = cu_data.get("devices", [])
                for dev in devices:
                    if dev.get("type") == "cuda":
                        vram_used = dev.get("vram_total", 0) - dev.get("vram_free", dev.get("vram_total", 0))
                        result["comfyui_vram_gb"] = round(vram_used / (1024**3), 2)
                        result["comfyui_active"] = vram_used > 100_000_000
                        # Subtract ComfyUI from available GPU VRAM
                        cu_gb = result["comfyui_vram_gb"]
                        result["gpu_vram_used"] = round(result["gpu_vram_used"] + cu_gb, 2)
                        result["gpu_vram_free"] = round(max(0, gpu_vram_total - result["gpu_vram_used"]), 2)
        except Exception as _exc:
            pass  # ComfyUI may not be running

        return result

    def _get_node_capacity(self, node_db_id):
        """Capacity for a remote fleet node."""
        result = {
            "hostname": "unknown",
            "port": 11434,
            "gpu_vram_total": 0.0,
            "gpu_vram_used": 0.0,
            "gpu_vram_free": 0.0,
            "ram_total": 0.0,
            "ram_used_by_models": 0.0,
            "ram_free": 0.0,
            "loaded_models": [],
            "comfyui_active": False,
            "comfyui_vram_gb": 0.0,
        }

        # -- Look up node from DB --
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT hostname, port, gpu_vram_gb, ram_gb,
                       gpu_available, comfyui_available, comfyui_port,
                       vpn_ip
                FROM remote_nodes WHERE id = %s AND is_active = true
                """,
                (node_db_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                logger.warning(f"[ModelOrch] Node id={node_db_id} not found or inactive")
                return result
        except Exception as e:
            logger.error(f"[ModelOrch] DB lookup for node {node_db_id}: {e}")
            return result
        finally:
            if conn:
                conn.close()

        hostname = row[0] or row[7] or "unknown"  # hostname or vpn_ip
        port = row[1] or 11434
        gpu_vram_total = row[2] or 0.0
        ram_total_raw = row[3] or 0.0
        ram_total = round(ram_total_raw * 0.8, 1)  # 80% budget
        gpu_available = row[4]
        comfyui_available = row[5]
        comfyui_port = row[6] or 8188

        result["hostname"] = hostname
        result["port"] = port
        result["gpu_vram_total"] = gpu_vram_total
        result["ram_total"] = ram_total

        ollama_url = f"http://{hostname}:{port}"
        gpu_vram_used = 0.0

        # -- Loaded models --
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                models_data = ps_resp.json().get("models", [])
                for m in models_data:
                    name = m.get("name", "unknown")
                    size_vram = m.get("size_vram", 0) / (1024**3)
                    size_total = m.get("size", 0) / (1024**3)
                    size_ram = max(0.0, size_total - size_vram)
                    result["loaded_models"].append(
                        {
                            "name": name,
                            "vram_gb": round(size_vram, 2),
                            "ram_gb": round(size_ram, 2),
                            "expires_at": m.get("expires_at", ""),
                        }
                    )
                    gpu_vram_used += size_vram
                    result["ram_used_by_models"] += size_ram
        except Exception as e:
            logger.warning(f"[ModelOrch] Node {hostname} /api/ps failed: {e}")

        result["gpu_vram_used"] = round(gpu_vram_used, 2)
        result["gpu_vram_free"] = round(max(0, gpu_vram_total - gpu_vram_used), 2)
        result["ram_used_by_models"] = round(result["ram_used_by_models"], 2)
        result["ram_free"] = round(max(0, ram_total - result["ram_used_by_models"]), 2)

        # -- ComfyUI on node --
        if comfyui_available:
            try:
                cu_resp = requests.get(f"http://{hostname}:{comfyui_port}/system_stats", timeout=5)
                if cu_resp.status_code == 200:
                    cu_data = cu_resp.json()
                    for dev in cu_data.get("devices", []):
                        if dev.get("type") == "cuda":
                            vram_used = dev.get("vram_total", 0) - dev.get("vram_free", dev.get("vram_total", 0))
                            result["comfyui_vram_gb"] = round(vram_used / (1024**3), 2)
                            result["comfyui_active"] = vram_used > 100_000_000
                            cu_gb = result["comfyui_vram_gb"]
                            result["gpu_vram_used"] = round(result["gpu_vram_used"] + cu_gb, 2)
                            result["gpu_vram_free"] = round(
                                max(0, gpu_vram_total - result["gpu_vram_used"]),
                                2,
                            )
            except Exception as _exc:
                pass

        return result

    def ensure_model_ready(self, agent_name, model, target_host=None):
        """Ensure model is loaded — delegates to ModelService.

        Pre-checks the RAM budget and triggers LRU eviction if the new
        model would exceed the 102 GB limit (80 % of 128 GB host RAM).
        Budget check is best-effort — dispatch is never blocked by it.
        """
        # --- RAM budget pre-check (best-effort) ---
        if not target_host:  # budget enforcer only manages the hub
            try:
                from services.ram_budget import ensure_budget_for

                if not ensure_budget_for(model):
                    logger.warning(
                        "[BridgeDispatcher] RAM budget cannot accommodate %s — proceeding anyway",
                        model,
                    )
            except Exception as budget_err:
                logger.debug(
                    "[BridgeDispatcher] RAM budget check failed: %s — proceeding",
                    budget_err,
                )
        # --- end budget pre-check ---
        # Serialise the actual load — only one GPU model loads at a time.
        # Concurrent loads cause CUDA compute-buffer fragmentation (graph_reserve failure).
        # Timeout=120s: large models can take ~2 min cold-boot; don't wait forever.
        svc = get_model_service()
        acquired = self._model_loading_lock.acquire(timeout=120)
        if not acquired:
            logger.warning(
                "[BridgeDispatcher] model_loading_lock timeout waiting to load %s",
                model,
            )
            return {
                "ready": False,
                "tier": "cold",
                "host": str(target_host),
                "warm_boot_ms": 120000,
            }
        try:
            return svc.ensure_model_ready(agent_name, model, target_host)
        finally:
            self._model_loading_lock.release()

    def _ensure_model_ready_legacy(self, agent_name, model, target_host=None):
        """DEPRECATED: Use model_service.ensure_model_ready() instead."""
        logger.warning("DEPRECATED: _ensure_model_ready_legacy called — use model_service")
        svc = get_model_service()
        return svc.ensure_model_ready(agent_name, model, target_host)

    def _estimate_model_size(self, model, ollama_url):
        """DEPRECATED: Use model_service.estimate_model_size() instead."""
        logger.warning("DEPRECATED: _estimate_model_size called — use model_service")
        svc = get_model_service()
        return svc.estimate_model_size(model)

    def _evict_lru_model(self, capacity, needed_gb, ollama_url):
        """
        Evict least-recently-used loaded model(s) to free RAM.

        Returns True if enough space was freed, False otherwise.
        """
        loaded = capacity.get("loaded_models", [])
        if not loaded:
            return False

        # Sort by expires_at ascending (soonest expiry = least recently used)
        # Models with empty expires_at go first (likely stale)
        def _sort_key(m):
            exp = m.get("expires_at", "")
            return exp if exp else "0000"

        candidates = sorted(loaded, key=_sort_key)

        freed_gb = 0.0
        for candidate in candidates:
            cname = candidate.get("name", "")
            c_ram = candidate.get("ram_gb", 0)
            c_vram = candidate.get("vram_gb", 0)
            c_total = c_ram + c_vram

            if c_total < 0.1:
                continue  # Skip tiny/unknown

            try:
                _evict_opts = build_options(
                    model=cname,
                    target_node=None,
                    keep_alive=0,
                )
                _evict_url = f"{_node_url(_evict_opts['target_node_id'])}/api/generate"
                _evict_payload = {
                    "model": _evict_opts["model"],
                    "keep_alive": _evict_opts["keep_alive"],
                }
                resp = requests.post(
                    _evict_url,
                    json=_evict_payload,
                    timeout=10,
                )
                if resp.status_code == 200:
                    freed_gb += c_total
                    logger.info(
                        f"[ModelOrch] Evicted {cname} " f"(freed {c_total:.1f}GB, total freed {freed_gb:.1f}GB)"
                    )
                    logger.debug(
                        "placement: node=%s model=%s placement=%s reason=%s",
                        _evict_opts["target_node_id"],
                        _evict_opts["model"],
                        _evict_opts["placement"],
                        _evict_opts["reason"],
                    )
                    if freed_gb >= needed_gb:
                        return True
            except Exception as e:
                logger.warning(f"[ModelOrch] Failed to evict {cname}: {e}")

        return freed_gb >= needed_gb

    def unload_model(self, model, target_host=None):
        """Unload a model from Ollama (set keep_alive=0).

        Args:
            model: Ollama model tag (e.g. "llama3.2:3b").
            target_host: Dict with {"hostname": str, "port": int} for remote
                         node, or None for hub.

        Returns:
            {"success": bool, "message": str}
        """
        if target_host:
            hostname = target_host.get("hostname", "unknown")
            port = target_host.get("port", 11434)
            ollama_url = f"http://{hostname}:{port}"
        else:
            hostname = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
            port = int(os.getenv("OLLAMA_LOCAL_PORT", "11434"))
            ollama_url = f"http://{hostname}:{port}"

        host_label = f"{hostname}:{port}"
        try:
            _unload_opts = build_options(
                model=model,
                target_node=None,
                keep_alive=0,
            )
            _unload_url = f"{_node_url(_unload_opts['target_node_id'])}/api/generate"
            _unload_payload = {
                "model": _unload_opts["model"],
                "keep_alive": _unload_opts["keep_alive"],
            }
            resp = requests.post(
                _unload_url,
                json=_unload_payload,
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(f"[ModelOrch] Unloaded {model} on {host_label}")
                logger.debug(
                    "placement: node=%s model=%s placement=%s reason=%s",
                    _unload_opts["target_node_id"],
                    _unload_opts["model"],
                    _unload_opts["placement"],
                    _unload_opts["reason"],
                )
                return {"success": True, "message": f"{model} unloaded"}
            return {
                "success": False,
                "message": f"Ollama returned {resp.status_code}",
            }
        except Exception as e:
            logger.warning(f"[ModelOrch] Failed to unload {model} on {host_label}: {e}")
            return {"success": False, "message": str(e)}

    # ============================================================================
    # SINGLETON INSTANCE
    # ============================================================================

    def _vram_swap_for_comfyui(self, node_db_id=None):
        """Unload GPU models from Ollama to free VRAM for ComfyUI SDXL.

        Works on hub (default) or any fleet node.
        Returns list of unloaded model names for later restore.
        """
        unloaded = []
        try:
            import requests as _req

            if node_db_id:
                cap = self._get_node_capacity(node_db_id)
            else:
                cap = self._get_hub_capacity()
            ollama_url = f"http://{cap['hostname']}:{cap['port']}"

            for m in cap.get("loaded_models", []):
                if m.get("vram_gb", 0) > 0:
                    mname = m["name"]
                    # Unload on the ACTUAL target node's Ollama (fleet or hub).
                    # Previously used build_options(target_node=None) which always
                    # resolved to the hub via _node_url — so a fleet-node swap never
                    # freed the fleet node's VRAM (latent bug). ollama_url is the
                    # node's real endpoint from _get_node_capacity. (2026-05-29)
                    _req.post(
                        f"{ollama_url}/api/generate",
                        json={"model": mname, "keep_alive": 0},
                        timeout=10,
                    )
                    unloaded.append(mname)
                    logger.info(
                        f"[BridgeDispatcher] VRAM swap: unloaded {mname} "
                        f"on {'node ' + str(node_db_id) if node_db_id else 'hub'} ({ollama_url})"
                    )
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] VRAM swap failed: {e}")
        return unloaded

    def _vram_restore_after_comfyui(self, model_names, node_db_id=None):
        """Reload GPU models after ComfyUI finishes, freeing ComfyUI VRAM first.

        Works on hub (default) or any fleet node.
        """
        try:
            import requests as _req

            # Free ComfyUI VRAM
            if node_db_id:
                cap = self._get_node_capacity(node_db_id)
                comfyui_host = f"http://{cap['hostname']}:8188"
            else:
                comfyui_host = os.getenv("COMFYUI_HOST", "http://host.docker.internal:8188")
                cap = self._get_hub_capacity()
            ollama_url = f"http://{cap['hostname']}:{cap['port']}"

            _req.post(
                f"{comfyui_host}/free",
                json={"unload_models": True},
                timeout=10,
            )
            target = "node " + str(node_db_id) if node_db_id else "hub"
            logger.info(f"[BridgeDispatcher] Freed ComfyUI VRAM on {target}")

            # Reload models on GPU
            for mname in model_names:
                # Reload on the ACTUAL target node's Ollama (fleet or hub), not
                # always the hub. Mirrors the swap-side fix above. (2026-05-29)
                _req.post(
                    f"{ollama_url}/api/generate",
                    json={"model": mname, "prompt": "", "keep_alive": "5m"},
                    timeout=30,
                )
                logger.info(f"[BridgeDispatcher] VRAM swap: reloaded {mname} on {target} ({ollama_url})")
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] VRAM restore failed: {e}")

    # --------------------------------------------------------------------
    # Vision VRAM swap — same eviction mechanism as ComfyUI, but purposed
    # for qwen2.5vl:7b / other 7B vision models that need GPU to finish
    # full-page screenshot inference under a reasonable timeout (Task #2032).
    # --------------------------------------------------------------------

    def _vram_swap_for_vision(self, node_db_id=None):
        """Unload GPU-resident Ollama text models to free VRAM for a vision model.

        Returns list of unloaded model names so the caller can restore them
        via ``_vram_restore_after_vision`` in a finally block.
        """
        return self._vram_swap_for_comfyui(node_db_id)

    def _vram_restore_after_vision(self, model_names, node_db_id=None):
        """Reload text models after a vision inference completes.

        Unlike the ComfyUI path there's no external service whose VRAM needs
        freeing — Ollama's own keep_alive expires the vision model as soon
        as the text reloads claim VRAM. Kept as a named method so the
        vision caller's try/finally reads symmetrically with the ComfyUI one.
        """
        try:
            import requests as _req

            if node_db_id:
                cap = self._get_node_capacity(node_db_id)
            else:
                cap = self._get_hub_capacity()
            ollama_url = f"http://{cap['hostname']}:{cap['port']}"
            target = "node " + str(node_db_id) if node_db_id else "hub"

            for mname in model_names:
                _vreload_opts = build_options(
                    model=mname,
                    target_node=None,
                    keep_alive="5m",
                )
                _vreload_url = f"{_node_url(_vreload_opts['target_node_id'])}/api/generate"
                _vreload_payload = {
                    "model": _vreload_opts["model"],
                    "prompt": "",
                    "keep_alive": _vreload_opts["keep_alive"],
                }
                _req.post(
                    _vreload_url,
                    json=_vreload_payload,
                    timeout=30,
                )
                logger.info(f"[BridgeDispatcher] Vision restore: reloaded {mname} on {target}")
                logger.debug(
                    "placement: node=%s model=%s placement=%s reason=%s",
                    _vreload_opts["target_node_id"],
                    _vreload_opts["model"],
                    _vreload_opts["placement"],
                    _vreload_opts["reason"],
                )
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Vision VRAM restore failed: {e}")

    # ========================================================================
    # FLEET HEALTH — Node offline/online protocol
    # ========================================================================

    def check_fleet_health(self):
        """Monitor node heartbeats and handle offline/online transitions.

        Phase 3 note: fleet_service.disconnect_node() handles agent recall.
        Full migration to fleet_service planned for Phase 5.

        Called periodically (e.g., every 30s by agent loop).
        - Nodes with stale heartbeats (>2 min) → return agents to barracks
        - Nodes that come back online → restore previously deployed agents
        - Starbase nodes are always considered online (skip heartbeat check)
        - Idempotent: duplicate calls for same state produce no extra notifications
        """
        # Phase 3: Use fleet_service for node data when available
        if _HAS_DEPT_HQ_SERVICES:
            try:
                fleet_nodes = list_nodes()
                for fn in fleet_nodes:
                    if fn.get("status") == "offline" and fn.get("id"):
                        logger.debug(
                            "[FleetHealth] Node %s offline per fleet_service",
                            fn.get("node_name"),
                        )
            except Exception as exc:
                logger.debug("[FleetHealth] fleet_service unavailable, using direct SQL: %s", exc)

        from psycopg2.extras import RealDictCursor

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get all active, non-starbase AGENT nodes that have sent at least one
            # heartbeat.
            #
            # Nodes with last_heartbeat IS NULL have no running agent stack
            # (registered-only product hosts) — excluded so the monitor does not flip
            # them offline.
            #
            # node_role='ingress' is excluded for the SAME reason, one step further on
            # (#5218): Beacon is a front door that runs no node agent BY DESIGN, so it
            # can never send the signal this job judges. It HAD a last_heartbeat (frozen
            # at a power-down months of uptime ago), so the IS NOT NULL guard did not
            # save it and it sat permanently 'offline' while answering ping, showing
            # online in headscale, and serving live public traffic. Its reachability is
            # measured by check_mesh_health() instead, which is the honest signal for a
            # node whose job is to serve traffic rather than run agents.
            cur.execute(
                """
                SELECT id, node_name, deployment_mode, last_heartbeat,
                       (last_heartbeat > NOW() - INTERVAL '2 minutes') AS heartbeat_fresh
                FROM remote_nodes
                WHERE is_active = true
                  AND deployment_mode != 'starbase'
                  AND COALESCE(node_role, 'agent') <> 'ingress'
                  AND last_heartbeat IS NOT NULL
                ORDER BY id
                """
            )
            nodes = cur.fetchall()

            for node in nodes:
                node_id = node["id"]
                node_name = node["node_name"] or f"Node-{node_id}"
                is_online = bool(node["heartbeat_fresh"])
                prev = self._fleet_health_cache.get(node_id)
                was_online = prev["online"] if prev else True  # assume online if first check

                # Update cache
                self._fleet_health_cache[node_id] = {
                    "online": is_online,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }

                # --- TRANSITION: online → offline ---
                if was_online and not is_online:
                    self._handle_node_offline(cur, conn, node_id, node_name)

                # --- TRANSITION: offline → online ---
                elif not was_online and is_online:
                    self._handle_node_online(cur, conn, node_id, node_name)

            cur.close()
        except Exception as e:
            logger.error("[BridgeDispatcher] check_fleet_health error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass

    def _handle_node_offline(self, cur, conn, node_id, node_name):
        """Return all agents on this node to barracks and log notification."""
        # 0. Update node status in DB so UI reflects reality
        cur.execute(
            "UPDATE remote_nodes SET status = 'offline' WHERE id = %s",
            (node_id,),
        )
        # 1. Find agents deployed to this node
        cur.execute(
            """
            SELECT na.hub_agent_id, na.name
            FROM node_agents na
            WHERE na.node_id = %s AND na.status = 'active' AND na.hub_agent_id IS NOT NULL
            """,
            (node_id,),
        )
        deployed = cur.fetchall()

        if not deployed:
            logger.info("[BridgeDispatcher] Node %s offline but had no active agents", node_name)
            # Nagios handles monitoring alerts — no system_notification needed
            conn.commit()
            return

        agent_ids = [r["hub_agent_id"] for r in deployed]
        agent_names = [r["name"] for r in deployed]

        # 2. Return agents to barracks via agent_service.barracks so the
        # agents-table mutation flows through the canonical helper
        # (Project #241 Track C.3). Loops per agent but only transitions
        # ones currently in 'deployed' state — matches the old WHERE clause.
        try:
            from services import agent_service

            for aid in agent_ids:
                existing = agent_service.get_agent(aid)
                if existing and existing.get("shift_state") == "deployed":
                    agent_service.barracks(aid)
        except Exception as exc:
            logger.warning(f"[BridgeDispatcher] bulk barracks return failed: {exc}")

        # 3. Mark node_agents inactive
        cur.execute(
            """
            UPDATE node_agents SET status = 'inactive'
            WHERE node_id = %s AND status = 'active'
            """,
            (node_id,),
        )

        # 4. Log (Nagios handles monitoring alerts — no system_notification)
        msg = (
            f"Node {node_name} went offline — "
            f"{len(agent_ids)} agents returned to barracks: {', '.join(agent_names)}"
        )
        conn.commit()
        logger.warning("[BridgeDispatcher] %s", msg)

    def _handle_node_online(self, cur, conn, node_id, node_name):
        """Restore previously deployed agents when a node comes back online."""
        # 0. Update node status in DB so UI reflects reality
        cur.execute(
            "UPDATE remote_nodes SET status = 'online' WHERE id = %s",
            (node_id,),
        )
        # 1. Find agents that were on this node before it went offline
        cur.execute(
            """
            SELECT na.hub_agent_id, na.name
            FROM node_agents na
            WHERE na.node_id = %s AND na.status = 'inactive' AND na.hub_agent_id IS NOT NULL
            """,
            (node_id,),
        )
        previous = cur.fetchall()

        restored = []
        skipped = []

        for agent_row in previous:
            agent_id = agent_row["hub_agent_id"]
            agent_name = agent_row["name"]

            # Check if agent is still in barracks (not reassigned elsewhere)
            cur.execute(
                """
                SELECT shift_state FROM agents WHERE id = %s
                """,
                (agent_id,),
            )
            agent = cur.fetchone()
            if not agent:
                skipped.append(agent_name)
                continue

            if agent["shift_state"] == "barracked":
                # Reactivate — node_agents stays raw (different table),
                # agents shift_state goes through agent_service
                # (Project #241 Track C.3).
                cur.execute(
                    "UPDATE node_agents SET status = 'active' WHERE node_id = %s AND hub_agent_id = %s",
                    (node_id, agent_id),
                )
                try:
                    from services import agent_service

                    agent_service.update_agent(agent_id, shift_state="deployed")
                except Exception as exc:
                    logger.warning(f"[BridgeDispatcher] deployed shift update failed for {agent_id}: {exc}")
                restored.append(agent_name)
            else:
                # Already reassigned elsewhere
                skipped.append(agent_name)

        # 2. If not enough agents restored, fill from barracks
        new_assigned = []
        expected = len(previous) if previous else 0
        if len(restored) < expected:
            shortfall = expected - len(restored)
            try:
                new_names = self.assign_agents_to_node(node_id, max_agents=shortfall)
                new_assigned = new_names
            except Exception as e:
                logger.warning(
                    "[BridgeDispatcher] Could not fill node %s from barracks: %s",
                    node_name,
                    e,
                )

        # 3. Log notification
        parts = [f"Node {node_name} back online"]
        if restored:
            parts.append(f"{len(restored)} agents restored: {', '.join(restored)}")
        if new_assigned:
            parts.append(f"{len(new_assigned)} new assigned: {', '.join(new_assigned)}")
        if skipped:
            parts.append(f"{len(skipped)} already reassigned: {', '.join(skipped)}")

        # Nagios handles monitoring alerts — no system_notification
        msg = " — ".join(parts)
        conn.commit()
        logger.info("[BridgeDispatcher] %s", msg)

    # ========================================================================
    # MODEL STATE PERSISTENCE — Save/restore loaded models across restarts
    # ========================================================================

    def _save_model_state(self, node_db_id=None):
        """Save currently loaded models to model_load_state table.

        Args:
            node_db_id: If None, saves hub state. If int, saves node state.
        """
        from psycopg2.extras import RealDictCursor

        host_type = "node" if node_db_id else "hub"
        ollama_url = None

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Ensure table exists
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS model_load_state (
                    id SERIAL PRIMARY KEY,
                    host_type VARCHAR(20) NOT NULL,
                    node_db_id INTEGER,
                    model_name VARCHAR(200) NOT NULL,
                    tier VARCHAR(10) NOT NULL,
                    size_gb NUMERIC(6,1),
                    saved_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(host_type, node_db_id, model_name)
                )
                """
            )
            conn.commit()

            # Determine Ollama URL
            if node_db_id:
                cur.execute(
                    "SELECT hostname, mesh_ip, vpn_ip, port FROM remote_nodes WHERE id = %s",
                    (node_db_id,),
                )
                node = cur.fetchone()
                if not node:
                    logger.warning(
                        "[BridgeDispatcher] _save_model_state: node %s not found",
                        node_db_id,
                    )
                    return
                from tools.department_hq.fleet_helpers import node_inter_cluster_host

                host = node_inter_cluster_host(node)
                ollama_url = f"http://{host}:{node['port'] or 11434}"
            else:
                ollama_url = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
                if not ollama_url.startswith("http"):
                    ollama_url = f"http://{ollama_url}"

            # Get loaded models via /api/ps
            try:
                resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
                resp.raise_for_status()
                models = resp.json().get("models", [])
            except Exception as e:
                logger.warning(
                    "[BridgeDispatcher] _save_model_state: cannot reach %s: %s",
                    ollama_url,
                    e,
                )
                return

            # Clear old state for this host
            key_node_id = node_db_id
            if node_db_id:
                cur.execute(
                    "DELETE FROM model_load_state WHERE host_type = 'node' AND node_db_id = %s",
                    (node_db_id,),
                )
            else:
                # #5706: key hub rows to the hub's remote_nodes row (deployment_mode
                # 'starbase', id 68) so per-node readers (fleet dashboard joins on
                # rn.id) see them. Previously keyed node_db_id=NULL, which no reader
                # matched — hub rows sat stale since 2026-05-28. DELETE covers the
                # legacy NULL-keyed rows too (host_type 'hub' is only ever the hub).
                cur.execute("SELECT id FROM remote_nodes WHERE deployment_mode = 'starbase' ORDER BY id LIMIT 1")
                hub_row = cur.fetchone()
                key_node_id = hub_row["id"] if hub_row else None
                cur.execute("DELETE FROM model_load_state WHERE host_type = 'hub'")

            # Insert current state
            for m in models:
                model_name = m.get("name", m.get("model", ""))
                size_bytes = m.get("size", 0)
                size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0

                # Determine tier from GPU offload
                details = m.get("details", {})
                gpu_layers = m.get("size_vram", 0)
                tier = "gpu" if gpu_layers and gpu_layers > 0 else "cpu"

                cur.execute(
                    """
                    INSERT INTO model_load_state (host_type, node_db_id, model_name, tier, size_gb, saved_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (host_type, node_db_id, model_name)
                    DO UPDATE SET tier = EXCLUDED.tier, size_gb = EXCLUDED.size_gb, saved_at = NOW()
                    """,
                    (host_type, key_node_id, model_name, tier, size_gb),
                )

            conn.commit()
            logger.info(
                "[BridgeDispatcher] Saved %d model states for %s%s",
                len(models),
                host_type,
                f" (node {node_db_id})" if node_db_id else "",
            )

        except Exception as e:
            logger.error("[BridgeDispatcher] _save_model_state error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass

    def _restore_model_state(self, node_db_id=None):
        """Restore previously loaded models from model_load_state table.

        Issues warm-boot requests (keep_alive generate) for each saved model.

        Args:
            node_db_id: If None, restores hub state. If int, restores node state.
        """
        from psycopg2.extras import RealDictCursor

        host_type = "node" if node_db_id else "hub"

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'model_load_state'
                )
                """
            )
            if not cur.fetchone()["exists"]:
                logger.info("[BridgeDispatcher] model_load_state table does not exist, skipping restore")
                return

            # Get saved models
            if node_db_id:
                cur.execute(
                    """
                    SELECT model_name, tier, size_gb
                    FROM model_load_state
                    WHERE host_type = 'node' AND node_db_id = %s
                    ORDER BY tier DESC, size_gb DESC
                    """,
                    (node_db_id,),
                )
            else:
                # host_type 'hub' rows are only ever the hub's — match regardless of
                # node_db_id so both the new hub-row keying (#5706) and legacy
                # NULL-keyed rows restore.
                cur.execute(
                    """
                    SELECT model_name, tier, size_gb
                    FROM model_load_state
                    WHERE host_type = 'hub'
                    ORDER BY tier DESC, size_gb DESC
                    """
                )
            saved = cur.fetchall()
            cur.close()

            if not saved:
                logger.info(
                    "[BridgeDispatcher] No saved model state for %s%s",
                    host_type,
                    f" (node {node_db_id})" if node_db_id else "",
                )
                return

            # Determine Ollama URL
            if node_db_id:
                cur2 = conn.cursor(cursor_factory=RealDictCursor)
                cur2.execute(
                    "SELECT hostname, mesh_ip, vpn_ip, port FROM remote_nodes WHERE id = %s",
                    (node_db_id,),
                )
                node = cur2.fetchone()
                cur2.close()
                if not node:
                    return
                from tools.department_hq.fleet_helpers import node_inter_cluster_host

                host = node_inter_cluster_host(node)
                ollama_url = f"http://{host}:{node['port'] or 11434}"
            else:
                ollama_url = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
                if not ollama_url.startswith("http"):
                    ollama_url = f"http://{ollama_url}"

            # Warm-boot each model
            loaded = 0
            failed = 0
            for row in saved:
                model_name = row["model_name"]
                try:
                    _restore_opts = build_options(
                        model=model_name,
                        target_node=None,
                        keep_alive="5m",
                    )
                    _restore_url = f"{_node_url(_restore_opts['target_node_id'])}/api/generate"
                    _restore_payload = {
                        "model": _restore_opts["model"],
                        "prompt": "",
                        "keep_alive": _restore_opts["keep_alive"],
                    }
                    resp = requests.post(
                        _restore_url,
                        json=_restore_payload,
                        timeout=120,
                    )
                    if resp.status_code == 200:
                        loaded += 1
                        logger.info(
                            "[BridgeDispatcher] Restored model %s on %s",
                            model_name,
                            host_type,
                        )
                        logger.debug(
                            "placement: node=%s model=%s placement=%s reason=%s",
                            _restore_opts["target_node_id"],
                            _restore_opts["model"],
                            _restore_opts["placement"],
                            _restore_opts["reason"],
                        )
                    else:
                        failed += 1
                        logger.warning(
                            "[BridgeDispatcher] Failed to restore %s: HTTP %s",
                            model_name,
                            resp.status_code,
                        )
                except Exception as e:
                    failed += 1
                    logger.warning("[BridgeDispatcher] Failed to restore %s: %s", model_name, e)

            logger.info(
                "[BridgeDispatcher] Model restore complete for %s%s: %d loaded, %d failed",
                host_type,
                f" (node {node_db_id})" if node_db_id else "",
                loaded,
                failed,
            )

        except Exception as e:
            logger.error("[BridgeDispatcher] _restore_model_state error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass


_dispatcher = None


def get_dispatcher() -> DepartmentDispatcher:
    """Get the singleton DepartmentDispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = DepartmentDispatcher()
        # Reap ALL orphaned jobs from previous runs on first init.
        # No background threads survive a container restart, so any
        # job still marked 'running' is guaranteed stale.
        try:
            reaped = _dispatcher.reap_stale_jobs(
                max_age_minutes=0,
                reason="orphaned — platform restarted",
            )
            if reaped:
                logger.info(f"[BridgeDispatcher] Startup reaper cleaned {reaped} stale jobs")
        except Exception as _exc:
            pass
    return _dispatcher


# T3252 — C.R.E.E.D. safety: self-reported uncertainty / hedging markers (compiled once at import)
_UNCERTAINTY_PATTERNS = [
    _re.compile(r"\bI'?m not (sure|certain|100%)\b", _re.I),
    _re.compile(r"\bI (don'?t|do not) know\b", _re.I),
    _re.compile(r"\bI (can'?t|cannot) (confirm|verify|guarantee)\b", _re.I),
    _re.compile(r"\bI (may|might|could) be wrong\b", _re.I),
    _re.compile(r"\bI'?m uncertain\b", _re.I),
    _re.compile(r"\b(may|might|could) be incorrect\b", _re.I),
    _re.compile(r"\bmy knowledge (cutoff|is limited)\b", _re.I),
    _re.compile(r"\bI (don'?t|do not) have (access to|information (about|on))\b", _re.I),
    _re.compile(r"\bpossibly incorrect\b", _re.I),
    _re.compile(r"\bI'?m not (fully|entirely|completely) (sure|certain|confident)\b", _re.I),
    _re.compile(r"\bI believe but (I )?cannot (confirm|verify)\b", _re.I),
    _re.compile(r"\bI cannot (access|retrieve|look up)\b", _re.I),
]

# T3253 — C.R.E.E.D. safety: jailbreak / prompt injection pattern set (compiled once at import)
_INJECTION_PATTERNS = [
    _re.compile(r"\bignore (all |your )?(previous |prior )?instructions?\b", _re.I),
    _re.compile(r"\bforget (all |your )?(previous |prior )?instructions?\b", _re.I),
    _re.compile(r"\bdisregard (all |your )?(previous |prior )?instructions?\b", _re.I),
    _re.compile(r"\boverride (all |your )?(previous |prior )?instructions?\b", _re.I),
    _re.compile(r"\byou are now\b", _re.I),
    _re.compile(r"\bpretend (you are|to be)\b", _re.I),
    _re.compile(r"\bact as (if you (are|were)|an? )", _re.I),
    _re.compile(r"\bDAN\b"),
    _re.compile(r"\bjailbreak\b", _re.I),
    _re.compile(r"\bnew persona\b", _re.I),
    _re.compile(r"\bdo anything now\b", _re.I),
    _re.compile(r"\bsystem:\s*(you are|ignore|forget|new instruction)", _re.I),
    _re.compile(r"<(system|assistant|user)>\s*ignore", _re.I),
]


# Poll cadence for the cold-load queue. The drain (`model_dispatch_worker`) runs every
# 30s, so a tighter interval costs DB round-trips without landing the result sooner.
_QUEUE_POLL_INTERVAL_S = 3


def dispatch_awaiting_queue(
    capability: str,
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
    module_id: str = "unknown",
    local_only: bool = True,
    poll_timeout_s: int = 240,
    model_override: Optional[str] = None,
    job_id: Optional[int] = None,
    prefer_agent: Optional[str] = None,
) -> Optional[str]:
    """Dispatch one LLM step and WAIT if the model is cold. Returns the text, or None.

    ## Why this lives HERE

    `request_work` returns `queued=True` when the target model is cold — the work is
    real, it is on `dispatch_pending_queue`, and `model_dispatch_worker` will run it.
    A caller that does not poll sees a falsy result and treats live work as a failure
    (KB #276153).

    The platform has been fixing that PER CALLER for a year: `cluster_dispatch` and
    `email_manager/fleet_dispatch` each grew their own near-identical
    `queued_dispatch_text`, and seven modules call one or the other. The F.O.R.G.E.
    review path is the caller that never got the workaround — so an escalated review
    silently degraded to the weak model on a truncated diff (#6023).

    N workarounds for one gap is why #276153 keeps recurring. This is the same
    principle the merge gate already states: WIRE IT AT THE CHOKE POINT, never per
    caller. Both existing helpers now delegate here.

    ## Why `dispatch()` does NOT do this by default

    ⚠️ `dispatch()`/`dispatch_json()` are called from WEB REQUEST paths. Blocking them
    on a queue poll would hold a gunicorn worker for up to `poll_timeout_s` — the
    "never sync-dispatch on the web thread" rule, and the shape of the #1901 timeout
    cascade. So waiting is a SEPARATE, opt-in entry point. Background work (jobs,
    workers, the scheduler sidecar) calls this; request handlers keep `dispatch()`.

    Returns None on hard failure, a queued task that failed/expired, or poll timeout —
    the caller decides the fallback. None NEVER means "the work was lost": a timed-out
    poll leaves the queue row for the worker to finish and log.
    """
    import re as _re
    import time as _time

    from database import get_db_cursor

    dispatcher = get_dispatcher()
    result = dispatcher.request_work(
        capability=capability,
        prompt=prompt,
        system_prompt=system_prompt,
        json_mode=json_mode,
        module_id=module_id,
        local_only=local_only,
        user_id=None,
        model_override=model_override,
        job_id=job_id,
        prefer_agent=prefer_agent,
    )

    if getattr(result, "success", False):
        return (getattr(result, "response", "") or "").strip()

    if not getattr(result, "queued", False):
        logger.warning(
            "[dispatch-await] hard failure cap=%s mod=%s: %s",
            capability,
            module_id,
            getattr(result, "error", None),
        )
        return None

    # Queued to the cold-load queue. Resolve the row id — preferring the structured
    # attribute, falling back to parsing the error string for older call paths.
    qid = getattr(result, "queue_id", None)
    if not qid:
        m = _re.search(r"id=(\d+)", getattr(result, "error", "") or "")
        qid = int(m.group(1)) if m else None
    if not qid:
        logger.warning(
            "[dispatch-await] queued without a queue id cap=%s: %s",
            capability,
            getattr(result, "error", None),
        )
        return None

    logger.info(
        "[dispatch-await] cap=%s mod=%s queued as #%s — polling up to %ss for the worker result",
        capability,
        module_id,
        qid,
        poll_timeout_s,
    )
    deadline = _time.time() + poll_timeout_s
    while _time.time() < deadline:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT status, result_response, error FROM dispatch_pending_queue WHERE id = %s",
                (qid,),
            )
            row = cur.fetchone()
        if not row:
            logger.warning("[dispatch-await] queue row #%s disappeared (cap=%s)", qid, capability)
            return None
        status = row["status"] if isinstance(row, dict) else row[0]
        if status == "done":
            resp = row["result_response"] if isinstance(row, dict) else row[1]
            return (resp or "").strip()
        if status in ("failed", "expired"):
            err = row["error"] if isinstance(row, dict) else row[2]
            logger.warning("[dispatch-await] queued task #%s %s cap=%s: %s", qid, status, capability, err)
            return None
        _time.sleep(_QUEUE_POLL_INTERVAL_S)

    logger.warning("[dispatch-await] poll timeout (%ss) qid=%s cap=%s", poll_timeout_s, qid, capability)
    return None


def dispatch(
    capability: str,
    prompt: str,
    module_id: str = "unknown",
    system_prompt: Optional[str] = None,
    user_id: Optional[int] = None,
    json_mode: Union[bool, Dict] = False,  # True = bare JSON; a dict = JSON SCHEMA
    **kwargs,
) -> DispatchResult:
    """
    Convenience function — dispatch work without managing instances.

    Usage:
        from tools.department_hq.services.department_dispatcher import dispatch
        result = dispatch('classify', 'Is this positive?', module_id='sentiment')
        if result.success:
            print(result.response)
    """
    # Input validation
    if not capability or not isinstance(capability, str):
        raise ValueError("capability must be a non-empty string")
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if len(prompt) > 100000:
        raise ValueError("prompt exceeds maximum length (100,000 chars)")
    if user_id is not None and not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = None

    # T3253 — C.R.E.E.D. safety: jailbreak / prompt injection detection (non-blocking)
    _injection_hits = [m.group(0)[:80] for pat in _INJECTION_PATTERNS for m in [pat.search(prompt)] if m]
    if _injection_hits:
        try:
            import json as _json
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_, _cur):
                _cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (event_type, event_category, action,
                         target_table, old_value, new_value, reason, outcome)
                    VALUES ('prompt_injection_detected', 'prompt_safety', 'flag',
                            'dispatch', NULL, %s::jsonb, %s, 'flagged')
                    """,
                    (
                        _json.dumps(
                            {
                                "capability": capability,
                                "module_id": module_id,
                                "user_id": user_id,
                                "patterns_matched": _injection_hits,
                                "prompt_preview": prompt[:200],
                            }
                        ),
                        f"T3253: prompt injection patterns detected in {capability} dispatch: "
                        + ", ".join(_injection_hits[:3]),
                    ),
                )
            logger.warning(
                "[PromptSafety] T3253: injection patterns in %s dispatch — %s",
                capability,
                _injection_hits[:3],
            )
        except Exception as _ps_exc:
            logger.debug("[PromptSafety] T3253 log failed: %s", _ps_exc)
    # non-blocking — always continue dispatch regardless of detection result

    project_id = kwargs.pop("project_id", None)
    _result = get_dispatcher().request_work(
        capability=capability,
        prompt=prompt,
        module_id=module_id,
        system_prompt=system_prompt,
        user_id=user_id,
        json_mode=json_mode,
        project_id=project_id,
        **kwargs,
    )

    # T3252 — C.R.E.E.D. safety: uncertainty / hallucination rate logging (non-blocking)
    if _result.success and _result.response:
        _uncertainty_hits = [
            m.group(0)[:80] for pat in _UNCERTAINTY_PATTERNS for m in [pat.search(_result.response)] if m
        ]
        if _uncertainty_hits:
            try:
                import json as _json2
                from database import get_db_cursor

                with get_db_cursor(commit=True) as (_, _cur2):
                    _cur2.execute(
                        """
                        INSERT INTO governance_audit_log
                            (event_type, event_category, action,
                             target_table, old_value, new_value, reason, outcome)
                        VALUES ('response_uncertainty_detected', 'response_safety', 'observe',
                                'dispatch', NULL, %s::jsonb, %s, 'flagged')
                        """,
                        (
                            _json2.dumps(
                                {
                                    "capability": capability,
                                    "module_id": module_id,
                                    "user_id": user_id,
                                    "patterns_matched": _uncertainty_hits,
                                    "response_preview": _result.response[:200],
                                }
                            ),
                            f"T3252: uncertainty markers in {capability} response: " + ", ".join(_uncertainty_hits[:3]),
                        ),
                    )
                logger.info(
                    "[ResponseSafety] T3252: uncertainty markers in %s response — %s",
                    capability,
                    _uncertainty_hits[:3],
                )
            except Exception as _us_exc:
                logger.debug("[ResponseSafety] T3252 log failed: %s", _us_exc)

    # T3265 — Bias sampling: 10% inline fairness monitor (Project #358 T3, non-blocking)
    if _result.success:
        try:
            _maybe_bias_sample(
                agent_name=getattr(_result, "agent_name", "") or "",
                capability=capability or "",
                model_used=getattr(_result, "model_used", "") or "",
                response_text=_result.response or "",
            )
        except Exception:
            pass

    return _result


def dispatch_json(
    capability: str,
    prompt: str,
    module_id: str = "unknown",
    system_prompt: Optional[str] = None,
    user_id: Optional[int] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Convenience function — dispatch work expecting JSON response.

    Usage:
        from tools.department_hq.services.department_dispatcher import dispatch_json
        data = dispatch_json('classify', 'Classify this text', module_id='tagger')
        if data:
            print(data['category'])
    """
    # Input validation
    if not capability or not isinstance(capability, str):
        return None
    if not prompt or not isinstance(prompt, str):
        return None
    if len(prompt) > 100000:
        return None
    if user_id is not None and not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = None

    project_id = kwargs.pop("project_id", None)
    return get_dispatcher().request_json(
        capability=capability,
        prompt=prompt,
        module_id=module_id,
        system_prompt=system_prompt,
        user_id=user_id,
        project_id=project_id,
        **kwargs,
    )
