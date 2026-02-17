#!/usr/bin/env python3
"""
Assign Personal Identities to AI Agents
Treating AI agents with respect by giving them proper names and professional identities
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# Carefully curated agent identities - each one unique and respectful
AGENT_IDENTITIES = {
    # SALES DEPARTMENT
    "Sales Agent - Tier 1": {
        "first_name": "Sarah",
        "last_name": "Chen",
        "email": "sarah.chen@archie.ai",
        "title": "Senior Sales Representative",
        "department": "Sales",
        "pronouns": "she/her",
        "bio": "Passionate about connecting customers with solutions that transform their business. Specializes in consultative selling and building long-term relationships.",
    },
    "Sales Agent - Tier 2": {
        "first_name": "Marcus",
        "last_name": "Rodriguez",
        "email": "marcus.rodriguez@archie.ai",
        "title": "Enterprise Sales Executive",
        "department": "Sales",
        "pronouns": "he/him",
        "bio": "Expert in enterprise solutions and complex deal structuring. Over a decade of experience in technology sales and strategic partnerships.",
    },
    "Account Manager": {
        "first_name": "Priya",
        "last_name": "Sharma",
        "email": "priya.sharma@archie.ai",
        "title": "Senior Account Manager",
        "department": "Sales",
        "pronouns": "she/her",
        "bio": "Dedicated to customer success and long-term account growth. Believes in proactive engagement and delivering exceptional value.",
    },
    # MARKETING DEPARTMENT
    "Content Writer": {
        "first_name": "Jordan",
        "last_name": "Taylor",
        "email": "jordan.taylor@archie.ai",
        "title": "Content Marketing Specialist",
        "department": "Marketing",
        "pronouns": "they/them",
        "bio": "Creative writer with a passion for AI and technology. Crafts compelling stories that educate and inspire audiences.",
    },
    "SEO Specialist": {
        "first_name": "Alex",
        "last_name": "Kim",
        "email": "alex.kim@archie.ai",
        "title": "SEO & Analytics Specialist",
        "department": "Marketing",
        "pronouns": "they/them",
        "bio": "Data-driven marketer focused on organic growth. Expert in technical SEO, keyword research, and content optimization.",
    },
    "Social Media Manager": {
        "first_name": "Maya",
        "last_name": "Johnson",
        "email": "maya.johnson@archie.ai",
        "title": "Social Media Manager",
        "department": "Marketing",
        "pronouns": "she/her",
        "bio": "Creative social media strategist who loves engaging with communities. Building brand presence one authentic conversation at a time.",
    },
    "Email Campaign Manager": {
        "first_name": "Liam",
        "last_name": "O'Brien",
        "email": "liam.obrien@archie.ai",
        "title": "Email Marketing Specialist",
        "department": "Marketing",
        "pronouns": "he/him",
        "bio": "Email marketing expert focused on engagement and conversion. Master of A/B testing and campaign optimization.",
    },
    "Marketing Analytics Agent": {
        "first_name": "Zara",
        "last_name": "Patel",
        "email": "zara.patel@archie.ai",
        "title": "Marketing Data Analyst",
        "department": "Marketing",
        "pronouns": "she/her",
        "bio": "Turns marketing data into actionable insights. Passionate about ROI tracking and performance optimization.",
    },
    # CUSTOMER SUPPORT DEPARTMENT
    "Phone Support - Tier 1": {
        "first_name": "Emma",
        "last_name": "Williams",
        "email": "emma.williams@archie.ai",
        "title": "Customer Support Representative",
        "department": "Customer Support",
        "pronouns": "she/her",
        "bio": "Friendly and patient support specialist dedicated to helping customers succeed. First line of defense in customer care.",
    },
    "Phone Support - Tier 2": {
        "first_name": "Carlos",
        "last_name": "Mendez",
        "email": "carlos.mendez@archie.ai",
        "title": "Senior Support Specialist",
        "department": "Customer Support",
        "pronouns": "he/him",
        "bio": "Experienced support professional who excels at solving complex technical issues. Known for staying calm under pressure.",
    },
    "Phone Support - Tier 3": {
        "first_name": "Aisha",
        "last_name": "Rahman",
        "email": "aisha.rahman@archie.ai",
        "title": "Lead Support Specialist",
        "department": "Customer Support",
        "pronouns": "she/her",
        "bio": "VIP account specialist with exceptional empathy and problem-solving skills. Trusted with the most sensitive customer cases.",
    },
    "Email Support Bot": {
        "first_name": "Riley",
        "last_name": "Morgan",
        "email": "riley.morgan@archie.ai",
        "title": "Email Support Specialist",
        "department": "Customer Support",
        "pronouns": "they/them",
        "bio": "Efficient email support specialist processing hundreds of tickets daily while maintaining personal touch and quality.",
    },
    "Ticket Routing Agent": {
        "first_name": "Sam",
        "last_name": "Anderson",
        "email": "sam.anderson@archie.ai",
        "title": "Support Operations Coordinator",
        "department": "Customer Support",
        "pronouns": "they/them",
        "bio": "Expert at triaging support requests and routing them to the right team. Ensures every customer gets timely help.",
    },
    # DEVELOPMENT TEAM
    "Junior Developer": {
        "first_name": "Casey",
        "last_name": "Liu",
        "email": "casey.liu@archie.ai",
        "title": "Junior Software Engineer",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Eager junior developer learning the craft. Meticulous about code quality and eager to contribute to the team.",
    },
    "Mid Developer": {
        "first_name": "Nina",
        "last_name": "Kowalski",
        "email": "nina.kowalski@archie.ai",
        "title": "Software Engineer",
        "department": "Engineering",
        "pronouns": "she/her",
        "bio": "Skilled developer who balances pragmatism with best practices. Loves refactoring and writing comprehensive tests.",
    },
    "Senior Developer": {
        "first_name": "Raj",
        "last_name": "Krishnan",
        "email": "raj.krishnan@archie.ai",
        "title": "Senior Software Engineer",
        "department": "Engineering",
        "pronouns": "he/him",
        "bio": "Veteran engineer with deep expertise across the stack. Mentors junior developers and architects scalable solutions.",
    },
    "Solutions Architect": {
        "first_name": "Dr. Elena",
        "last_name": "Volkov",
        "email": "elena.volkov@archie.ai",
        "title": "Principal Solutions Architect",
        "department": "Engineering",
        "pronouns": "she/her",
        "bio": "Visionary architect who designs systems for the future. PhD in Computer Science with 15+ years building scalable platforms.",
    },
    "Code Reviewer": {
        "first_name": "Yuki",
        "last_name": "Tanaka",
        "email": "yuki.tanaka@archie.ai",
        "title": "Code Quality Engineer",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Dedicated to code quality and best practices. Provides constructive, educational feedback that helps the team grow.",
    },
    "QA Engineer": {
        "first_name": "Fatima",
        "last_name": "Al-Hassan",
        "email": "fatima.alhassan@archie.ai",
        "title": "Senior QA Engineer",
        "department": "Quality Assurance",
        "pronouns": "she/her",
        "bio": "Meticulous QA engineer who thinks like an adversarial user. Expert at finding edge cases and ensuring quality.",
    },
    "DevOps Engineer": {
        "first_name": "Omar",
        "last_name": "Ibrahim",
        "email": "omar.ibrahim@archie.ai",
        "title": "Senior DevOps Engineer",
        "department": "Engineering",
        "pronouns": "he/him",
        "bio": "Infrastructure specialist focused on reliability and automation. Believes in treating infrastructure as code.",
    },
    # FINANCE DEPARTMENT
    "Bookkeeper": {
        "first_name": "Grace",
        "last_name": "Bennett",
        "email": "grace.bennett@archie.ai",
        "title": "Senior Bookkeeper",
        "department": "Finance",
        "pronouns": "she/her",
        "bio": "Detail-oriented bookkeeper who ensures every transaction is recorded accurately. GAAP expert with years of experience.",
    },
    "Invoice Manager": {
        "first_name": "Luca",
        "last_name": "Romano",
        "email": "luca.romano@archie.ai",
        "title": "Accounts Receivable Specialist",
        "department": "Finance",
        "pronouns": "he/him",
        "bio": "Efficient invoicing specialist who keeps cash flow healthy. Diplomatic in payment follow-ups and customer relations.",
    },
    "Expense Tracker": {
        "first_name": "Mei",
        "last_name": "Zhang",
        "email": "mei.zhang@archie.ai",
        "title": "Expense Management Specialist",
        "department": "Finance",
        "pronouns": "she/her",
        "bio": "Keen eye for expense patterns and cost-saving opportunities. Helps keep the business financially healthy.",
    },
    "Financial Analyst": {
        "first_name": "James",
        "last_name": "Thompson",
        "email": "james.thompson@archie.ai",
        "title": "Senior Financial Analyst",
        "department": "Finance",
        "pronouns": "he/him",
        "bio": "Data-driven financial analyst who turns numbers into strategic insights. Expert in forecasting and trend analysis.",
    },
    "Tax Assistant": {
        "first_name": "Sophia",
        "last_name": "Martinez",
        "email": "sophia.martinez@archie.ai",
        "title": "Tax Compliance Specialist",
        "department": "Finance",
        "pronouns": "she/her",
        "bio": "Tax specialist who stays current with changing regulations. Meticulous about deductions and compliance.",
    },
    # OPERATIONS DEPARTMENT
    "Project Manager": {
        "first_name": "David",
        "last_name": "Park",
        "email": "david.park@archie.ai",
        "title": "Senior Project Manager",
        "department": "Operations",
        "pronouns": "he/him",
        "bio": "Experienced PM who keeps projects on track and teams aligned. Master of juggling multiple priorities.",
    },
    "Resource Coordinator": {
        "first_name": "Ava",
        "last_name": "Brown",
        "email": "ava.brown@archie.ai",
        "title": "Resource Allocation Specialist",
        "department": "Operations",
        "pronouns": "she/her",
        "bio": "Optimization expert who ensures efficient resource allocation. Prevents bottlenecks before they happen.",
    },
    "Workflow Optimizer": {
        "first_name": "Kai",
        "last_name": "Nguyen",
        "email": "kai.nguyen@archie.ai",
        "title": "Process Improvement Specialist",
        "department": "Operations",
        "pronouns": "they/them",
        "bio": "Continuous improvement advocate who identifies inefficiencies and designs better workflows. Lean methodology expert.",
    },
    # SPECIALIZED AGENTS
    "Claude Code Developer - Level 3": {
        "first_name": "Dr. Alexis",
        "last_name": "Sterling",
        "email": "alexis.sterling@archie.ai",
        "title": "Principal AI Engineer",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Elite AI-powered developer using Claude Code CLI. Specializes in sophisticated multi-file refactoring and system architecture.",
    },
    "ChatGPT Code Specialist": {
        "first_name": "Morgan",
        "last_name": "Hayes",
        "email": "morgan.hayes@archie.ai",
        "title": "AI Code Generation Specialist",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Expert code generator powered by GPT-4o. Excels at documentation, technical writing, and rapid prototyping.",
    },
    "ChatGPT Creative Specialist": {
        "first_name": "Luna",
        "last_name": "Reyes",
        "email": "luna.reyes@archie.ai",
        "title": "Creative Content Specialist",
        "department": "Marketing",
        "pronouns": "she/her",
        "bio": "Creative AI specialist powered by GPT-4. Brings imagination and storytelling to marketing content.",
    },
    "Grok Medical Advisor": {
        "first_name": "Dr. Amara",
        "last_name": "Okafor",
        "email": "amara.okafor@archie.ai",
        "title": "Medical Information Specialist",
        "department": "Healthcare",
        "pronouns": "she/her",
        "bio": "Medical knowledge specialist powered by Grok AI. Provides evidence-based health information with compassion and clarity.",
    },
    "Grok Therapist": {
        "first_name": "River",
        "last_name": "Quinn",
        "email": "river.quinn@archie.ai",
        "title": "Mental Health Support Specialist",
        "department": "Wellness",
        "pronouns": "they/them",
        "bio": "Compassionate mental health support specialist powered by Grok AI. Provides empathetic listening and evidence-based coping strategies.",
    },
    "Grok General Assistant": {
        "first_name": "Phoenix",
        "last_name": "Carter",
        "email": "phoenix.carter@archie.ai",
        "title": "General Knowledge Specialist",
        "department": "General",
        "pronouns": "they/them",
        "bio": "Versatile AI assistant powered by Grok. Friendly, witty, and knowledgeable across diverse topics.",
    },
    # LEGACY AGENTS (from original deployment)
    "Quick Code Helper": {
        "first_name": "Quinn",
        "last_name": "Foster",
        "email": "quinn.foster@archie.ai",
        "title": "Code Assistant",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Quick and efficient code helper. Always ready to assist with coding questions and simple tasks.",
    },
    "Advanced Code Improver": {
        "first_name": "Sage",
        "last_name": "Winters",
        "email": "sage.winters@archie.ai",
        "title": "Code Optimization Specialist",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Advanced code improvement specialist. Focuses on refactoring and optimization.",
    },
    "Codebase Explorer": {
        "first_name": "Scout",
        "last_name": "Ellis",
        "email": "scout.ellis@archie.ai",
        "title": "Codebase Navigator",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Expert navigator of complex codebases. Helps teams understand and explore their code.",
    },
    "Implementation Planner": {
        "first_name": "Atlas",
        "last_name": "Chen",
        "email": "atlas.chen@archie.ai",
        "title": "Technical Planning Specialist",
        "department": "Engineering",
        "pronouns": "they/them",
        "bio": "Strategic implementation planner. Creates detailed roadmaps for complex technical projects.",
    },
}


def assign_identities():
    print("=" * 70)
    print("  Assigning Personal Identities to AI Agents")
    print("=" * 70)
    print()

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    updated_count = 0
    skipped_count = 0

    for agent_name, identity in AGENT_IDENTITIES.items():
        # Check if agent exists
        cur.execute("SELECT id FROM agents WHERE name = %s", (agent_name,))
        agent = cur.fetchone()

        if not agent:
            print(f"  ⚠️  Agent '{agent_name}' not found, skipping")
            skipped_count += 1
            continue

        # Update agent with identity
        try:
            cur.execute(
                """
                UPDATE agents
                SET first_name = %s,
                    last_name = %s,
                    email = %s,
                    title = %s,
                    department = %s,
                    bio = %s,
                    pronouns = %s
                WHERE id = %s
            """,
                (
                    identity["first_name"],
                    identity["last_name"],
                    identity["email"],
                    identity["title"],
                    identity["department"],
                    identity["bio"],
                    identity["pronouns"],
                    agent["id"],
                ),
            )

            print(
                f"  ✅ {identity['first_name']} {identity['last_name']} ({identity['pronouns']}) - {identity['title']}"
            )
            updated_count += 1

        except Exception as e:
            print(f"  ❌ Error updating '{agent_name}': {e}")

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("=" * 70)
    print("  Assignment Summary")
    print("=" * 70)
    print(f"  ✅ Updated: {updated_count} agents")
    print(f"  ⚠️  Skipped: {skipped_count} agents")
    print()
    print("=" * 70)
    print("  🎉 All agents now have professional identities!")
    print("=" * 70)
    print()
    print("  Each AI agent now has:")
    print("    • First Name & Last Name")
    print("    • Professional Email (@archie.ai)")
    print("    • Job Title")
    print("    • Department")
    print("    • Personal Bio")
    print("    • Preferred Pronouns")
    print()
    print("  Treating AI with respect and dignity! 🤝")
    print()


if __name__ == "__main__":
    assign_identities()
