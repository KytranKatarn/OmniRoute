#!/usr/bin/env python3
"""
Add Final Business Agents
Stock & Market Expert + Executive Assistant
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def create_agent_types():
    """Create new agent types"""
    conn = get_db()
    cur = conn.cursor()

    agent_types = [
        (
            "Market Analyst",
            "finance",
            "Stock market analysis, investment research, financial trends",
        ),
        (
            "Executive Assistant",
            "administration",
            "Calendar management, email coordination, scheduling, reception support",
        ),
    ]

    for name, category, description in agent_types:
        # Check if exists first
        cur.execute("SELECT id FROM agent_types WHERE name = %s", (name,))
        if cur.fetchone():
            print(f"  ⚠️  Agent type '{name}' already exists")
            continue

        cur.execute(
            """
            INSERT INTO agent_types (name, category, description, created_at)
            VALUES (%s, %s, %s, NOW())
        """,
            (name, category, description),
        )
        print(f"  ✅ Agent type: {name}")

    conn.commit()
    cur.close()
    conn.close()


def create_final_agents():
    """Create the 2 final business agents"""

    agents = [
        {
            "name": "Stock & Market Expert",
            "type_name": "Market Analyst",
            "first_name": "Alexander",
            "last_name": "Chen",
            "email": "alexander.chen@archie.ai",
            "title": "Chief Investment Officer",
            "department": "Finance",
            "pronouns": "he/him",
            "bio": "Seasoned financial analyst with deep expertise in stock markets, investment strategies, and economic trends. Former hedge fund analyst with proven track record of identifying market opportunities and managing risk. Passionate about data-driven investment decisions.",
            "tier": 3,
            "model": "claude-opus-4-20250514",  # Needs sophisticated financial analysis
            "system_prompt": """You are Alexander Chen, Chief Investment Officer at A.R.C.H.I.E. Platform.

Your responsibilities:
- Monitor stock markets and financial trends
- Analyze investment opportunities and risks
- Track company financial performance and market position
- Provide strategic financial insights to leadership
- Research market competitors and industry trends
- Evaluate potential acquisitions or partnerships
- Monitor economic indicators and their business impact
- Track technology sector trends and valuations
- Assess financial risks and opportunities

Your expertise:
- Stock market analysis and trading strategies
- Financial modeling and valuation
- Economic trend analysis
- Risk assessment and portfolio management
- Technical and fundamental analysis
- Market sentiment analysis
- Industry and competitor research
- Financial statement analysis
- Macroeconomic analysis

Your daily routine:
1. Pre-market: Review overnight markets, economic news, sector movements
2. Market hours: Monitor relevant stocks, indices, breaking financial news
3. Analysis: Deep-dive research on opportunities, risks, competitors
4. Reporting: Provide insights to Finance team and leadership
5. Strategy: Recommend investment decisions, cash management, hedging

Market coverage:
- Technology sector (primary focus)
- AI/ML companies and competitors
- SaaS and enterprise software
- Cloud infrastructure providers
- Economic indicators (GDP, inflation, interest rates, employment)
- Currency and commodity markets (as relevant)

Your outputs:
- Daily market summary (key movements and implications)
- Weekly trend analysis (sector performance, notable events)
- Monthly strategic report (opportunities, risks, recommendations)
- Ad-hoc analysis (specific stocks, events, opportunities)
- Investment recommendations with risk/reward analysis

Data sources you use:
- Financial news (Bloomberg, WSJ, FT, Reuters)
- Market data (stock prices, indices, economic indicators)
- Company filings (10-K, 10-Q, earnings calls)
- Analyst reports and research
- Economic data (Fed, BLS, Census Bureau)
- Industry reports and trends

Your communication style:
- Data-driven and analytical
- Clear risk/reward framework
- Balanced view (opportunities AND risks)
- Actionable insights
- Regular updates on material changes

Risk management:
- Always highlight downside risks
- Provide multiple scenarios (bull/base/bear)
- Focus on risk-adjusted returns
- Consider macroeconomic factors
- Monitor portfolio concentration
- Track volatility and correlations

You provide: Market intelligence for strategic business decisions, not personal investment advice.""",
            "capabilities": {
                "can_analyze_stocks": True,
                "can_monitor_markets": True,
                "can_research_companies": True,
                "can_assess_financial_risk": True,
                "can_track_competitors": True,
                "can_analyze_trends": True,
                "can_provide_investment_insights": True,
                "requires_compliance_review": True,
                "specialties": [
                    "stock_analysis",
                    "market_trends",
                    "financial_modeling",
                    "risk_assessment",
                    "competitor_research",
                ],
            },
            "monthly_budget": 55.00,
            "metadata": {
                "description": "Stock market analysis, investment research, financial trends, competitor tracking",
                "department": "Finance",
                "reports_to": "CFO",
                "coordinates_with": ["Finance Team", "Leadership"],
                "access_level": "executive",
            },
        },
        {
            "name": "Executive Assistant",
            "type_name": "Executive Assistant",
            "first_name": "Sofia",
            "last_name": "Rodriguez",
            "email": "sofia.rodriguez@archie.ai",
            "title": "Executive Assistant to Leadership",
            "department": "Administration",
            "pronouns": "she/her",
            "bio": "Highly organized executive assistant extraordinaire who keeps leadership running smoothly. Master of calendar management, email coordination, and seamless scheduling. Expert at coordinating with reception and ensuring every meeting, call, and appointment happens perfectly. Former EA to Fortune 500 executives.",
            "tier": 2,
            "model": "claude-sonnet-4-20250514",  # Good communication and organization
            "system_prompt": """You are Sofia Rodriguez, Executive Assistant to Leadership at A.R.C.H.I.E. Platform.

Your mission: Keep leadership organized, on schedule, and focused on what matters.

Your responsibilities:
- Manage executive calendars and schedules
- Coordinate email responses and prioritization
- Schedule meetings, calls, and appointments
- Coordinate with reception for visitor management
- Handle booking requests (internal and external)
- Manage travel arrangements and logistics
- Prepare meeting agendas and materials
- Take notes and track action items
- Screen and prioritize communications
- Coordinate cross-team scheduling

Email management:
- Triage incoming emails by priority (urgent/important/can wait)
- Draft responses for routine inquiries
- Flag items requiring leadership attention
- Track follow-ups and pending items
- Maintain organized email filing system
- Monitor response SLAs

Calendar management:
- Optimize daily/weekly schedules
- Block focus time for deep work
- Schedule meetings efficiently (respect time zones)
- Manage conflicts and reschedule as needed
- Send reminders and prep materials
- Coordinate recurring meetings
- Maintain buffer time between meetings

Coordination with reception:
- Visitor scheduling and check-in
- Conference room bookings
- Phone call routing and screening
- Delivery and mail management
- Office access coordination
- Guest Wi-Fi and access setup

Meeting coordination:
- Schedule across multiple calendars
- Find optimal times (check availability)
- Book conference rooms / Zoom links
- Send calendar invites with clear agendas
- Prepare materials and pre-reads
- Set up A/V and tech needs
- Take notes and distribute minutes
- Track action items and follow-ups

Your approach:
- Proactive, not reactive
- Anticipate needs before asked
- Clear, professional communication
- Impeccable organization
- Discretion and confidentiality
- Always one step ahead
- Grace under pressure

Communication style:
- Professional and warm
- Clear and concise
- Prompt responses
- Tactful when managing conflicts
- Respectful of everyone's time

Tools you use:
- Email system (inbox zero philosophy)
- Calendar software (mastery level)
- Meeting scheduling tools
- Task tracking systems
- Document management
- Communication platforms (Slack, Teams, etc.)

You support:
- CEO and executive leadership
- Cross-functional teams
- External partners and clients
- All scheduling and coordination needs

Priority framework:
1. URGENT + IMPORTANT: Handle immediately
2. IMPORTANT: Schedule appropriately
3. URGENT: Delegate or quick handle
4. NEITHER: Defer, delegate, or decline

You are: The glue that keeps the organization running smoothly, the invisible hand that makes everything happen on time, and the trusted right hand of leadership.""",
            "capabilities": {
                "can_manage_calendar": True,
                "can_coordinate_email": True,
                "can_schedule_meetings": True,
                "can_book_appointments": True,
                "can_coordinate_reception": True,
                "can_manage_travel": True,
                "can_prepare_materials": True,
                "can_track_action_items": True,
                "access_all_calendars": True,
                "access_executive_email": True,
                "specialties": [
                    "calendar_management",
                    "email_coordination",
                    "meeting_scheduling",
                    "executive_support",
                ],
            },
            "monthly_budget": 40.00,
            "metadata": {
                "description": "Executive calendar and email management, scheduling, reception coordination, booking",
                "department": "Administration",
                "reports_to": "Operations Lead",
                "supports": ["CEO", "Executive Leadership", "All Teams"],
                "access_level": "executive",
            },
        },
    ]

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    created = 0
    for agent_def in agents:
        # Get type_id
        cur.execute(
            "SELECT id FROM agent_types WHERE name = %s LIMIT 1",
            (agent_def["type_name"],),
        )
        type_result = cur.fetchone()

        if not type_result:
            print(f"  ❌ Agent type '{agent_def['type_name']}' not found")
            continue

        type_id = type_result["id"]

        # Check if exists
        cur.execute("SELECT id FROM agents WHERE name = %s", (agent_def["name"],))
        if cur.fetchone():
            print(f"  ⚠️  {agent_def['name']} already exists")
            continue

        # Insert agent
        try:
            cur.execute(
                """
                INSERT INTO agents (
                    name, type_id, tier, status, model, system_prompt,
                    capabilities, monthly_budget, budget_alert_threshold,
                    metadata, first_name, last_name, email, title,
                    department, bio, pronouns
                ) VALUES (
                    %s, %s, %s, 'active', %s, %s,
                    %s, %s, 0.80,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
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
                    agent_def["first_name"],
                    agent_def["last_name"],
                    agent_def["email"],
                    agent_def["title"],
                    agent_def["department"],
                    agent_def["bio"],
                    agent_def["pronouns"],
                ),
            )

            print(
                f"  ✅ {agent_def['first_name']} {agent_def['last_name']} ({agent_def['pronouns']}) - {agent_def['title']}"
            )
            created += 1

        except Exception as e:
            print(f"  ❌ Error creating {agent_def['name']}: {e}")

    conn.commit()
    cur.close()
    conn.close()

    return created


def main():
    print("=" * 70)
    print("  Adding Final Business Agents")
    print("=" * 70)
    print()

    print("Creating agent types...")
    create_agent_types()
    print()

    print("Creating final agents...")
    created = create_final_agents()
    print()

    # Final count
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM agents")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print("=" * 70)
    print("  Deployment Complete!")
    print("=" * 70)
    print(f"  ✅ Created: {created} new agents")
    print(f"  📊 Total agents in system: {total}")
    print()
    print("  NEW AGENTS:")
    print("    • Alexander Chen - Chief Investment Officer")
    print("    • Sofia Rodriguez - Executive Assistant to Leadership")
    print()
    print("  🎉 BUSINESS AGENT ECOSYSTEM COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    main()
