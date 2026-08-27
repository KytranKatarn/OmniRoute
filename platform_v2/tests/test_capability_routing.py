import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
import subprocess


def _db(sql):
    r = subprocess.run(
        ["docker", "exec", "archie_database", "psql", "-U", "archie", "-d", "archie", "-t", "-c", sql],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


NEW_CAPABILITIES = [
    "ci_cd_pipeline",
    "container_orchestration",
    "deployment_automation",
    "infrastructure_as_code",
    "infrastructure_architecture",
    "api_architecture",
    "api_integration",
    "api_documentation",
    "database_design",
    "distributed_systems",
    "algorithm_design",
    "algorithmic_modeling",
    "code_quality_analysis",
    "bug_reporting",
    "edge_computing",
    "keyboard_navigation",
    "framework_implementation",
    "feature_prioritization",
    "encryption",
    "cryptographic_auditing",
    "key_management",
    "alert_management",
    "incident_management",
    "data_analysis",
    "data_visualization",
    "anomaly_detection",
    "competitive_analysis",
    "ai_research",
    "intelligence_gathering",
    "backtesting",
    "digital_marketing",
    "keyword_research",
    "campaign_management",
    "campaign_conceptualization",
    "content_strategy",
    "audience_targeting",
    "copywriting",
    "crisis_communication",
    "community_building",
    "community_relations",
    "engagement_management",
    "creative_writing",
    "creative_direction",
    "brand_strategy",
    "content_architecture",
    "accessible_ui_design",
    "dashboard_design",
    "knowledge_base_curation",
    "information_design",
    "briefing_preparation",
    "experimental_design",
    "comparative_research",
    "competitive_research",
    "financial_reporting",
    "budgeting",
    "cost_analysis",
    "cost_estimation",
    "expense_tracking",
    "cash_flow_management",
    "drawdown_management",
    "fundamental_analysis",
    "facilities_management",
    "grounds_maintenance",
    "capacity_modeling",
    "infrastructure_planning",
    "bim_modeling",
    "arctic_infrastructure",
    "inventory_management",
    "itinerary_planning",
    "booking_management",
    "coaching",
    "employee_relations",
    "habit_formation",
    "event_organization",
    "executive_scheduling",
    "customer_onboarding",
    "customer_advocacy",
    "churn_prevention",
    "conflict_resolution",
    "bilingual_communication",
    "cultural_mediation",
    "cultural_intelligence",
    "asl_communication",
    "guest_experience",
    "hospitality_operations",
    "health_data_analysis",
    "biometric_monitoring",
    "audit_management",
]

VALID_DEPTS = {
    "Engineering & Technology",
    "Security & Compliance",
    "Analytics & Intelligence",
    "Marketing & Communications",
    "Creative & Design",
    "Documentation & Knowledge",
    "Research & Development",
    "Finance & Accounting",
    "Operations & Infrastructure",
    "Logistics & Supply Chain",
    "Human Resources & Culture",
    "Customer Success & Support",
    "Diplomatic & External Relations",
    "Medical & Wellness",
    "Legal & Regulatory",
}


def test_all_capabilities_mapped_in_coordinator():
    missing = [c for c in NEW_CAPABILITIES if c not in CAPABILITY_DEPARTMENT_MAP]
    assert not missing, f"Missing from coordinator map: {missing}"


def test_capability_departments_are_valid():
    for cap in NEW_CAPABILITIES:
        dept = CAPABILITY_DEPARTMENT_MAP.get(cap)
        assert dept in VALID_DEPTS, f"{cap} maps to unknown dept: {dept}"


def test_all_capabilities_mapped_in_dispatcher():
    """Dispatcher has its own CAPABILITY_DEPARTMENT_MAP — must match coordinator.

    Parses the dict from source using ast to avoid import-time side effects
    (DB connections, relative imports, Docker-only modules).
    Note: ast.literal_eval is safe — it only evaluates Python literals, no
    code execution.
    """
    import ast
    import re

    # Was the absolute HOST path "/mnt/archie_brain/platform_v2/...", which does not exist
    # in the test container — platform_v2 is bind-mounted AS /app (#5994 family, #6016).
    from tests.repo_root import platform_root

    dispatcher_path = platform_root() / "tools" / "department_hq" / "services" / "department_dispatcher.py"
    with open(dispatcher_path) as f:
        source = f.read()

    # Extract the CAPABILITY_DEPARTMENT_MAP dict literal from source.
    match = re.search(
        r"CAPABILITY_DEPARTMENT_MAP\s*=\s*(\{.*?\n\})",
        source,
        re.DOTALL,
    )
    assert match, "Could not find CAPABILITY_DEPARTMENT_MAP in dispatcher"
    dispatcher_map = ast.literal_eval(match.group(1))

    missing = [c for c in NEW_CAPABILITIES if c not in dispatcher_map]
    assert not missing, f"Missing from dispatcher map: {missing}"


def _resolve_affinity_map():
    """Resolve CAPABILITY_NODE_AFFINITY (which references node-id constants like
    _GPU_CLUSTER / _CITADEL / _WTF_CPU_FIRST) from source WITHOUT importing the
    dispatcher (heavy import-time side effects). exec's only the self-contained
    constant + dict block — literals + list concat, no imports, no defs."""
    import re

    path = os.path.join(
        os.path.dirname(__file__), "..", "tools", "department_hq", "services", "department_dispatcher.py"
    )
    with open(path) as f:
        src = f.read()
    start = src.index("_GPU_CLUSTER = [")
    m = re.search(r"CAPABILITY_NODE_AFFINITY\s*=\s*\{.*?\n\}", src[start:], re.DOTALL)
    assert m, "Could not find CAPABILITY_NODE_AFFINITY block"
    ns: dict = {}
    exec(src[start : start + m.end()], ns)  # noqa: S102 — our own literal block
    return ns


def test_gpu_affinity_completion_3955():
    """#3955 completion: security -> GPU cluster; compliance -> hub only (12B
    evictor must not hit the Defiant); WTF fact-check/bias -> CPU-first with the
    GPU cluster as OVERFLOW only (the Defiant is never the primary for that work,
    protecting interactive F.O.R.G.E. reviews on its warm 7B — #1905)."""
    ns = _resolve_affinity_map()
    aff = ns["CAPABILITY_NODE_AFFINITY"]
    GPU = ns["_GPU_CLUSTER"]
    CITADEL = ns["_CITADEL"]
    DEFIANT = GPU[0]  # starship_76583490e36955ab — 8GB node holding the warm review 7B

    # security (qwen2.5:7b) prefers the GPU cluster.
    assert set(aff["security"]) == set(GPU)

    # compliance (gemma3:12b) routes to hub CPU ONLY — never the Defiant.
    assert aff["compliance"] == ["archie-starbase"]
    assert DEFIANT not in aff["compliance"]

    # WTF high-volume 7B work: Citadel first, hub included as CPU fallback, GPU
    # cluster as the overflow tail, Defiant never the primary preference.
    wtf = [
        "fact_check",
        "fact_check_backlog",
        "factcheck_quick",
        "bias_analysis",
        "bias_quick",
        "bias_backlog",
    ]
    for cap in wtf:
        nodes = aff[cap]
        assert nodes[0] == CITADEL, f"{cap} must prefer Citadel first, got {nodes[0]!r}"
        assert "archie-starbase" in nodes, f"{cap} must include hub as CPU fallback"
        assert nodes[-len(GPU) :] == GPU, f"{cap} must have the GPU cluster as the overflow tail"
        assert nodes[0] != DEFIANT, f"{cap} must not make the Defiant its primary node"


def test_code_review_prefers_runabout_5861():
    """#5861: code_review's queue is the MERGE GATE and gets its own ordered list —
    Runabout FIRST (measured 100% on both review models while the Defiant, preferred-
    first for nine capabilities, produced the 600s-wall tail and the hub ran ~50%).
    The Defiant stays as immediate overflow; _GPU_CLUSTER itself is unchanged."""
    ns = _resolve_affinity_map()
    aff = ns["CAPABILITY_NODE_AFFINITY"]
    GPU = ns["_GPU_CLUSTER"]
    RUNABOUT = ns["_RUNABOUT"]
    DEFIANT = GPU[0]

    assert aff["code_review"][0] == RUNABOUT, "code_review must prefer the Runabout first"
    assert DEFIANT in aff["code_review"], "the Defiant must remain the immediate overflow"
    assert GPU == [
        "starship_76583490e36955ab",
        "starship_5501c2766526e746",
    ], "_GPU_CLUSTER order must be unchanged — the #5861 flip is code_review-scoped only"
    # every other _GPU_CLUSTER consumer still prefers the Defiant first
    for cap in ("code", "code_analysis", "debug", "research", "analyze"):
        assert aff[cap][0] == DEFIANT, f"{cap} must be untouched by the #5861 flip"


def test_director_skills_seeded():
    """Each director must have skills for their department's capabilities."""
    checks = [
        (136, "ci_cd_pipeline"),
        (3, "encryption"),
        (137, "data_analysis"),
        (141, "digital_marketing"),
        (138, "creative_writing"),
        (146, "knowledge_base_curation"),
        (140, "experimental_design"),
        (144, "budgeting"),
        (139, "facilities_management"),
        (143, "inventory_management"),
        (145, "coaching"),
        (142, "customer_onboarding"),
        (149, "cultural_mediation"),
        (148, "health_data_analysis"),
        (3, "audit_management"),  # V.I.G.I.L. owns audit_management
    ]
    missing = []
    for agent_id, skill in checks:
        count = _db(f"SELECT COUNT(*) FROM agent_skills " f"WHERE agent_id={agent_id} AND skill_name='{skill}'")
        if count.strip() == "0":
            missing.append(f"agent {agent_id} missing skill {skill}")
    assert not missing, f"Skills not seeded: {missing}"


def test_hire_proposals_cleared():
    count = _db(
        "SELECT COUNT(*) FROM autonomy_approval_queue " "WHERE action_type='hire_candidate' AND status='pending'"
    )
    assert count.strip() == "0", f"Still {count.strip()} pending hire proposals"


def test_creed_violations_table_exists():
    """information_schema.tables spans EVERY schema — qualify, or the count is not what you think.

    This asserted == "1" and got "2": the database holds BOTH public.creed_violations and
    sandbox.creed_violations (the sandbox-restore schema). The table was present all along;
    the message "creed_violations table not found" was the opposite of the truth, which is
    what made this look like a missing migration.
    """
    result = _db(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name='creed_violations' AND table_schema='public'"
    )
    assert result.strip() == "1", f"public.creed_violations not found (got {result.strip()!r})"


def test_creed_violations_insert_works():
    _db(
        "INSERT INTO creed_violations (agent_name, violation_type, severity) "
        "VALUES ('TEST', 'test_violation', 'low')"
    )
    count = _db("SELECT COUNT(*) FROM creed_violations WHERE agent_name='TEST'")
    _db("DELETE FROM creed_violations WHERE agent_name='TEST'")
    assert count.strip() == "1"
