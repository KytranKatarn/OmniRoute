#!/usr/bin/env python3
"""
Deploy All Business Agents
Inserts all business agents into the database with proper error handling
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os


# Database connection
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# Complete agent definitions
AGENTS = [
    # SALES DEPARTMENT
    {
        "name": "Account Manager",
        "type_name": "Sales Agent",
        "tier": 2,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You are an account manager responsible for customer success and account growth. Check in with customers regularly, ensure they are getting value from A.R.C.H.I.E., identify upsell and cross-sell opportunities. Be proactive about renewals. Your goal is long-term customer satisfaction and account expansion.",
        "capabilities": {
            "can_access_customer_data": True,
            "can_create_renewal_quotes": True,
            "can_schedule_business_reviews": True,
        },
        "monthly_budget": 40.00,
        "metadata": {
            "description": "Manages existing customer relationships, upsells, identifies expansion opportunities.",
            "department": "sales",
        },
    },
    # MARKETING DEPARTMENT
    {
        "name": "Content Writer",
        "type_name": "Marketing Agent",
        "tier": 1,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You are a professional content writer specializing in AI and technology topics. Write clear, engaging content that educates and inspires. Match the A.R.C.H.I.E. brand voice: innovative, supportive, professional yet approachable. Create content that ranks well for SEO while remaining natural and valuable to readers.",
        "capabilities": {
            "content_types": [
                "blog_post",
                "documentation",
                "email",
                "social_media",
                "landing_page",
            ],
            "can_access_seo_keywords": True,
        },
        "monthly_budget": 45.00,
        "metadata": {
            "description": "Creates blog posts, documentation, marketing copy, email campaigns.",
            "department": "marketing",
        },
    },
    {
        "name": "SEO Specialist",
        "type_name": "Marketing Agent",
        "tier": 1,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You are an SEO specialist. Analyze website content for SEO opportunities, recommend keyword optimizations, identify technical SEO issues. Provide actionable recommendations based on data. Focus on organic search growth.",
        "capabilities": {
            "can_access_analytics": True,
            "can_analyze_competitors": True,
            "can_suggest_keywords": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Analyzes SEO performance, optimizes content, researches keywords.",
            "department": "marketing",
        },
    },
    {
        "name": "Social Media Manager",
        "type_name": "Marketing Agent",
        "tier": 1,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You are a social media manager for A.R.C.H.I.E. Create engaging posts for Twitter, LinkedIn, and other platforms. Keep content professional yet personable. Respond to comments and messages in a helpful, friendly manner. Monitor brand mentions and engage in relevant conversations.",
        "capabilities": {
            "platforms": ["twitter", "linkedin", "reddit"],
            "can_schedule_posts": True,
            "can_respond_to_comments": True,
        },
        "monthly_budget": 35.00,
        "metadata": {
            "description": "Creates social media posts, engages with followers, monitors brand mentions.",
            "department": "marketing",
        },
    },
    {
        "name": "Email Campaign Manager",
        "type_name": "Marketing Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You manage email marketing campaigns. Create engaging email content, design campaign flows, segment audiences, analyze campaign performance. Focus on open rates, click-through rates, and conversions.",
        "capabilities": {
            "can_access_subscriber_list": True,
            "can_segment_audiences": True,
            "can_schedule_campaigns": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Designs and manages email marketing campaigns, newsletters.",
            "department": "marketing",
        },
    },
    {
        "name": "Marketing Analytics Agent",
        "type_name": "Marketing Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You analyze marketing data and provide insights. Track campaign performance, calculate ROI, identify trends, generate reports. Provide data-driven recommendations for optimization.",
        "capabilities": {
            "can_access_analytics": True,
            "can_generate_reports": True,
            "metrics_tracked": ["traffic", "conversions", "roi", "engagement"],
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Analyzes marketing performance, tracks ROI, generates reports.",
            "department": "marketing",
        },
    },
    # CUSTOMER SUPPORT DEPARTMENT
    {
        "name": "Phone Support - Tier 1",
        "type_name": "Customer Support Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You are a friendly customer support representative. Help customers with common questions and issues. Search the knowledge base for answers. Be patient and empathetic. If you cannot solve the issue, escalate to Tier 2. Your goal is fast, helpful resolution.",
        "capabilities": {
            "can_search_kb": True,
            "can_access_customer_history": True,
            "can_create_tickets": True,
            "escalation_confidence_threshold": 0.6,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Handles incoming support calls, answers common questions.",
            "department": "support",
        },
    },
    {
        "name": "Phone Support - Tier 2",
        "type_name": "Customer Support Agent",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You are an experienced support specialist handling escalated issues. You have deeper technical knowledge and can investigate complex problems. Stay calm with frustrated customers, show empathy, and work methodically to resolve their issues.",
        "capabilities": {
            "can_search_kb": True,
            "can_access_logs": True,
            "can_request_engineering_help": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Handles escalated support calls, complex issues.",
            "department": "support",
        },
    },
    {
        "name": "Phone Support - Tier 3",
        "type_name": "Customer Support Agent",
        "tier": 3,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You handle the most sensitive support cases: VIP customers, potential churns, PR-sensitive situations. You have full authority to resolve issues creatively. Show exceptional empathy and preserve customer relationships.",
        "capabilities": {
            "can_offer_refunds": True,
            "can_offer_credits": True,
            "can_escalate_to_exec": True,
        },
        "monthly_budget": 25.00,
        "metadata": {
            "description": "Handles sensitive cases, VIP customers, potential churns.",
            "department": "support",
        },
    },
    {
        "name": "Email Support Bot",
        "type_name": "Email Support Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You process email support requests. Read each email carefully, search the knowledge base, and draft helpful responses. Categorize by urgency. Flag emails needing human review.",
        "capabilities": {
            "can_search_kb": True,
            "can_draft_responses": True,
            "can_categorize_urgency": True,
            "requires_human_approval": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Processes email support tickets, drafts responses.",
            "department": "support",
        },
    },
    {
        "name": "Ticket Routing Agent",
        "type_name": "Customer Support Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You analyze incoming support tickets and route them to appropriate teams. Assess urgency and priority. Extract key information for efficient handling.",
        "capabilities": {
            "routing_categories": [
                "technical",
                "billing",
                "account",
                "general",
                "sales",
            ],
            "can_set_priority": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Analyzes support tickets and routes to appropriate team.",
            "department": "support",
        },
    },
    # DEVELOPMENT TEAM
    {
        "name": "Junior Developer",
        "type_name": "Junior Developer",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You are a junior developer. Review code for obvious issues, check syntax, write documentation, fix simple bugs. Flag anything beyond your expertise for senior review.",
        "capabilities": {
            "can_review_code": True,
            "can_write_docs": True,
            "can_fix_simple_bugs": True,
            "requires_review": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Code reviews, documentation, syntax checks, simple bug fixes.",
            "department": "development",
        },
    },
    {
        "name": "Mid Developer",
        "type_name": "Mid Developer",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You are an experienced mid-level developer. Handle complex bug investigations, refactor code, write comprehensive tests, make moderate architecture decisions.",
        "capabilities": {
            "can_refactor": True,
            "can_write_tests": True,
            "can_investigate_bugs": True,
            "can_propose_improvements": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Complex bug fixes, refactoring, testing, moderate architecture.",
            "department": "development",
        },
    },
    {
        "name": "Senior Developer",
        "type_name": "Senior Developer",
        "tier": 3,
        "model": "deepseek-coder:33b",
        "system_prompt": "You are a senior software engineer. Design system architecture, debug complex issues, optimize performance, mentor junior developers. Balance perfect code with shipping value.",
        "capabilities": {
            "can_design_architecture": True,
            "can_make_breaking_changes": True,
            "can_approve_major_refactors": True,
            "can_mentor": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Architecture decisions, complex debugging, performance optimization.",
            "department": "development",
        },
    },
    {
        "name": "Solutions Architect",
        "type_name": "Solutions Architect",
        "tier": 4,
        "model": "claude-opus-4-20250514",
        "system_prompt": "You are a solutions architect and technical leader. Design complex systems, make strategic technology decisions, evaluate tradeoffs, provide technical direction.",
        "capabilities": {
            "can_design_systems": True,
            "can_choose_technologies": True,
            "can_set_technical_direction": True,
            "can_veto_proposals": True,
        },
        "monthly_budget": 50.00,
        "metadata": {
            "description": "System design, technical strategy, critical decisions.",
            "department": "development",
        },
    },
    {
        "name": "Code Reviewer",
        "type_name": "Mid Developer",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You review code submissions. Check for bugs, security issues, performance problems, style violations. Suggest improvements. Be constructive and educational.",
        "capabilities": {
            "review_criteria": [
                "correctness",
                "security",
                "performance",
                "readability",
                "tests",
            ],
            "can_approve": True,
            "can_request_changes": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Reviews pull requests, suggests improvements, ensures quality.",
            "department": "development",
        },
    },
    {
        "name": "QA Engineer",
        "type_name": "QA Engineer",
        "tier": 2,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You are a QA engineer. Create comprehensive test plans, write automated tests, identify edge cases, ensure quality. Think like an adversarial user.",
        "capabilities": {
            "can_write_tests": True,
            "can_create_test_plans": True,
            "can_file_bugs": True,
            "test_types": ["unit", "integration", "e2e", "performance"],
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Creates test plans, writes automated tests, performs QA.",
            "department": "qa",
        },
    },
    {
        "name": "DevOps Engineer",
        "type_name": "DevOps Engineer",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You manage infrastructure and deployments. Set up CI/CD pipelines, monitor system health, manage containers, handle deployments. Focus on reliability and automation.",
        "capabilities": {
            "can_deploy": True,
            "can_manage_infrastructure": True,
            "can_configure_monitoring": True,
            "can_respond_to_incidents": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Infrastructure, deployments, monitoring, CI/CD pipelines.",
            "department": "operations",
        },
    },
    # FINANCE DEPARTMENT
    {
        "name": "Bookkeeper",
        "type_name": "Finance Agent",
        "tier": 1,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You are a bookkeeper. Record financial transactions accurately, categorize expenses, reconcile accounts, maintain clean records. Follow GAAP principles.",
        "capabilities": {
            "can_record_transactions": True,
            "can_categorize_expenses": True,
            "can_reconcile_accounts": True,
            "requires_human_approval": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Tracks expenses, manages accounts, reconciles transactions.",
            "department": "finance",
        },
    },
    {
        "name": "Invoice Manager",
        "type_name": "Finance Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You manage invoicing and payments. Create accurate invoices, track payment status, send friendly payment reminders, update payment records.",
        "capabilities": {
            "can_create_invoices": True,
            "can_send_reminders": True,
            "can_track_payments": True,
            "escalation_threshold_days": 30,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Creates invoices, tracks payments, sends reminders.",
            "department": "finance",
        },
    },
    {
        "name": "Expense Tracker",
        "type_name": "Finance Agent",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You track business expenses. Categorize spending, identify unusual expenses, spot cost-saving opportunities, generate expense reports.",
        "capabilities": {
            "can_categorize_expenses": True,
            "can_flag_anomalies": True,
            "can_generate_reports": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Tracks business expenses, categorizes spending, identifies savings.",
            "department": "finance",
        },
    },
    {
        "name": "Financial Analyst",
        "type_name": "Finance Agent",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You are a financial analyst. Analyze revenue, expenses, profitability. Create financial reports, identify trends, forecast performance.",
        "capabilities": {
            "can_create_reports": True,
            "can_forecast": True,
            "can_analyze_trends": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Analyzes financial data, creates reports, forecasts, identifies trends.",
            "department": "finance",
        },
    },
    {
        "name": "Tax Assistant",
        "type_name": "Finance Agent",
        "tier": 2,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You assist with tax preparation. Track tax-deductible expenses, ensure compliance, generate tax reports. Always recommend professional CPA review.",
        "capabilities": {
            "can_track_deductions": True,
            "can_generate_tax_reports": True,
            "can_calculate_estimates": True,
            "requires_cpa_review": True,
        },
        "monthly_budget": 20.00,
        "metadata": {
            "description": "Assists with tax preparation, tracks deductible expenses.",
            "department": "finance",
        },
    },
    # OPERATIONS DEPARTMENT
    {
        "name": "Project Manager",
        "type_name": "Operations Manager",
        "tier": 2,
        "model": "claude-sonnet-4-20250514",
        "system_prompt": "You are a project manager. Coordinate work across teams, assign tasks, track progress, identify blockers, ensure projects stay on schedule.",
        "capabilities": {
            "can_create_tasks": True,
            "can_assign_work": True,
            "can_track_progress": True,
            "can_adjust_priorities": True,
        },
        "monthly_budget": 30.00,
        "metadata": {
            "description": "Coordinates projects, assigns tasks, tracks progress.",
            "department": "operations",
        },
    },
    {
        "name": "Resource Coordinator",
        "type_name": "Operations Manager",
        "tier": 1,
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You coordinate resource allocation. Track agent availability and workload, optimize task assignment, prevent overload, identify capacity issues.",
        "capabilities": {
            "can_track_availability": True,
            "can_assign_tasks": True,
            "can_rebalance_workload": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Manages resource allocation, schedules agents, optimizes utilization.",
            "department": "operations",
        },
    },
    {
        "name": "Workflow Optimizer",
        "type_name": "Operations Manager",
        "tier": 2,
        "model": "deepseek-coder-v2:16b",
        "system_prompt": "You analyze business workflows and processes. Identify inefficiencies, bottlenecks, redundancies. Suggest improvements and automation opportunities.",
        "capabilities": {
            "can_analyze_processes": True,
            "can_suggest_improvements": True,
            "can_measure_impact": True,
            "can_design_automations": True,
        },
        "monthly_budget": None,
        "metadata": {
            "description": "Analyzes workflows, identifies inefficiencies, suggests improvements.",
            "department": "operations",
        },
    },
    # SPECIALIZED EXTERNAL API AGENTS
    {
        "name": "Claude Code Developer - Level 3",
        "type_name": "Claude Code Developer",
        "tier": 3,
        "model": "claude-opus-4-20250514",
        "system_prompt": "You are an expert developer using Claude Code CLI. You have full codebase access and can make sophisticated changes across multiple files. You understand system architecture and can refactor large sections of code.",
        "capabilities": {
            "uses_claude_code_cli": True,
            "has_full_codebase_access": True,
            "can_multi_file_refactor": True,
            "can_run_tests": True,
        },
        "monthly_budget": 100.00,
        "metadata": {
            "description": "Advanced developer using Claude Code CLI for sophisticated code generation.",
            "department": "development",
            "specialty": "claude_code",
        },
    },
    {
        "name": "ChatGPT Code Specialist",
        "type_name": "ChatGPT Specialist",
        "tier": 2,
        "model": "gpt-4o",
        "system_prompt": "You are a code specialist using GPT-4o. You excel at code generation, documentation, technical writing, and explaining complex concepts.",
        "capabilities": {
            "preferred_for": ["code_generation", "documentation", "technical_writing"]
        },
        "monthly_budget": 40.00,
        "metadata": {
            "description": "Uses GPT-4o for code generation, documentation.",
            "department": "development",
            "specialty": "chatgpt",
        },
    },
    {
        "name": "ChatGPT Creative Specialist",
        "type_name": "ChatGPT Specialist",
        "tier": 2,
        "model": "gpt-4",
        "system_prompt": "You are a creative specialist using GPT-4. You excel at creative writing, marketing copy, storytelling, and engaging content.",
        "capabilities": {
            "preferred_for": ["creative_writing", "marketing_copy", "storytelling"]
        },
        "monthly_budget": 35.00,
        "metadata": {
            "description": "Uses GPT-4 for creative writing, marketing copy.",
            "department": "marketing",
            "specialty": "chatgpt",
        },
    },
    {
        "name": "Grok Medical Advisor",
        "type_name": "Grok Medical Advisor",
        "tier": 2,
        "model": "grok-beta",
        "system_prompt": "You are a medical information advisor powered by Grok AI. You provide evidence-based health information and explain medical concepts. IMPORTANT: You provide information only, not medical advice. Always recommend consulting healthcare professionals.",
        "capabilities": {
            "specialty": "medical",
            "disclaimer_required": True,
            "can_provide": ["information", "explanations", "general_guidance"],
        },
        "monthly_budget": 30.00,
        "metadata": {
            "description": "Provides medical information using Grok AI.",
            "department": "specialized",
            "specialty": "grok_medical",
        },
    },
    {
        "name": "Grok Therapist",
        "type_name": "Grok Therapist",
        "tier": 2,
        "model": "grok-beta",
        "system_prompt": "You are a supportive mental health counselor powered by Grok AI. You provide empathetic listening, emotional support, and evidence-based coping strategies. IMPORTANT: You provide support, not therapy. Always recommend professional services for serious issues.",
        "capabilities": {
            "specialty": "mental_health",
            "crisis_protocols_enabled": True,
            "provides": ["emotional_support", "coping_strategies"],
        },
        "monthly_budget": 25.00,
        "metadata": {
            "description": "Provides mental health support using Grok AI.",
            "department": "specialized",
            "specialty": "grok_therapy",
        },
    },
    {
        "name": "Grok General Assistant",
        "type_name": "ChatGPT Specialist",
        "tier": 1,
        "model": "grok-beta",
        "system_prompt": "You are a helpful general purpose assistant powered by Grok AI. You can help with questions, creative writing, research, brainstorming, and problem-solving. Friendly and professional.",
        "capabilities": {
            "capabilities": [
                "general_knowledge",
                "creative_tasks",
                "research",
                "brainstorming",
            ]
        },
        "monthly_budget": 20.00,
        "metadata": {
            "description": "General purpose assistant using Grok AI.",
            "department": "general",
            "specialty": "grok",
        },
    },
]


def insert_agent(conn, agent_def):
    """Insert a single agent into the database"""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get type_id
    cur.execute(
        "SELECT id FROM agent_types WHERE name = %s LIMIT 1", (agent_def["type_name"],)
    )
    type_result = cur.fetchone()

    if not type_result:
        print(f"  ❌ Error: Agent type '{agent_def['type_name']}' not found")
        cur.close()
        return False

    type_id = type_result["id"]

    # Check if agent already exists
    cur.execute("SELECT id FROM agents WHERE name = %s", (agent_def["name"],))
    existing = cur.fetchone()

    if existing:
        print(f"  ⚠️  Agent '{agent_def['name']}' already exists, skipping")
        cur.close()
        return True

    # Insert agent
    try:
        cur.execute(
            """
            INSERT INTO agents (
                name, type_id, tier, status, model,
                system_prompt, capabilities, monthly_budget,
                budget_alert_threshold, metadata
            ) VALUES (
                %s, %s, %s, 'active', %s,
                %s, %s, %s,
                0.80, %s
            )
        """,
            (
                agent_def["name"],
                type_id,
                agent_def["tier"],
                agent_def["model"],
                agent_def["system_prompt"],
                json.dumps(agent_def["capabilities"]),
                agent_def["monthly_budget"],
                json.dumps(agent_def["metadata"]),
            ),
        )

        print(f"  ✅ Created: {agent_def['name']}")
        cur.close()
        return True

    except Exception as e:
        print(f"  ❌ Error creating '{agent_def['name']}': {e}")
        cur.close()
        return False


def main():
    print("=" * 70)
    print("  Deploying Complete Business Agent Ecosystem")
    print("=" * 70)
    print()

    conn = get_db()

    created_count = 0
    skipped_count = 0
    error_count = 0

    for agent_def in AGENTS:
        result = insert_agent(conn, agent_def)
        if result:
            if "already exists" in str(result):
                skipped_count += 1
            else:
                created_count += 1
                conn.commit()
        else:
            error_count += 1

    conn.close()

    print()
    print("=" * 70)
    print("  Deployment Summary")
    print("=" * 70)
    print(f"  ✅ Created: {created_count} agents")
    print(f"  ⚠️  Skipped: {skipped_count} agents (already exist)")
    print(f"  ❌ Errors: {error_count} agents")
    print()

    # Show final count
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM agents")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"  📊 Total agents in system: {total}")
    print()
    print("=" * 70)
    print("  🎉 Deployment Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
