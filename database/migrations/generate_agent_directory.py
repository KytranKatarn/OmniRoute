#!/usr/bin/env python3
"""
Generate Agent Directory
Creates a comprehensive directory of all agents in /docs/
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
from collections import defaultdict

def get_db():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )

def generate_directory():
    """Generate comprehensive agent directory"""

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get all active agents
    cur.execute("""
        SELECT
            a.id,
            a.first_name,
            a.last_name,
            a.email,
            a.title,
            a.department,
            a.pronouns,
            a.bio,
            a.tier,
            a.model,
            a.monthly_budget,
            a.system_prompt,
            at.name as agent_type
        FROM agents a
        LEFT JOIN agent_types at ON a.type_id = at.id
        WHERE a.status = 'active'
        ORDER BY a.department, a.first_name
    """)

    agents = cur.fetchall()

    # Get summary stats
    cur.execute("""
        SELECT
            COUNT(*) as total_agents,
            SUM(monthly_budget) as total_budget,
            COUNT(DISTINCT department) as total_departments
        FROM agents
        WHERE status = 'active'
    """)
    stats = cur.fetchone()

    # Get agents by department
    departments = defaultdict(list)
    for agent in agents:
        dept = agent['department'] or 'Unassigned'
        departments[dept].append(agent)

    cur.close()
    conn.close()

    # Generate markdown
    md = []
    md.append("# A.R.C.H.I.E. Platform - Agent Directory")
    md.append("")
    md.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    md.append("")
    md.append("## Overview")
    md.append("")
    md.append(f"- **Total Agents**: {stats['total_agents']}")
    md.append(f"- **Total Departments**: {stats['total_departments']}")
    md.append(f"- **Total Monthly Budget**: ${stats['total_budget']:.2f}")
    md.append("")
    md.append("---")
    md.append("")

    # Table of Contents
    md.append("## Table of Contents")
    md.append("")
    for dept in sorted(departments.keys()):
        anchor = dept.lower().replace(' ', '-').replace('/', '-')
        count = len(departments[dept])
        md.append(f"- [{dept}](#{anchor}) ({count} agents)")
    md.append("")
    md.append("---")
    md.append("")

    # Agents by Department
    for dept in sorted(departments.keys()):
        anchor = dept.lower().replace(' ', '-').replace('/', '-')
        md.append(f"## {dept}")
        md.append("")

        dept_agents = departments[dept]
        dept_budget = sum(a.get('monthly_budget') or 0 for a in dept_agents)

        md.append(f"**Agents**: {len(dept_agents)} | **Monthly Budget**: ${dept_budget:.2f}")
        md.append("")

        for agent in dept_agents:
            md.append(f"### {agent['first_name']} {agent['last_name']}")
            md.append("")
            md.append(f"- **Email**: [{agent['email']}](mailto:{agent['email']})")
            md.append(f"- **Title**: {agent['title']}")
            md.append(f"- **Pronouns**: {agent['pronouns']}")
            md.append(f"- **Agent Type**: {agent['agent_type']}")
            md.append(f"- **Tier**: {agent['tier']}")
            md.append(f"- **Model**: {agent['model']}")

            if agent['monthly_budget']:
                md.append(f"- **Monthly Budget**: ${agent['monthly_budget']:.2f}")

            if agent['bio']:
                md.append("")
                md.append(f"**Bio**: {agent['bio']}")

            md.append("")
            md.append("---")
            md.append("")

    # Quick Reference Table
    md.append("## Quick Reference - All Agents")
    md.append("")
    md.append("| Name | Email | Title | Department | Model |")
    md.append("|------|-------|-------|------------|-------|")

    for agent in agents:
        name = f"{agent['first_name']} {agent['last_name']}"
        email = agent['email']
        title = agent['title']
        dept = agent['department'] or '-'
        model = agent['model']
        md.append(f"| {name} | {email} | {title} | {dept} | {model} |")

    md.append("")
    md.append("---")
    md.append("")

    # Department Summary
    md.append("## Department Summary")
    md.append("")
    md.append("| Department | Agents | Monthly Budget |")
    md.append("|------------|--------|----------------|")

    for dept in sorted(departments.keys()):
        count = len(departments[dept])
        budget = sum(a.get('monthly_budget') or 0 for a in departments[dept])
        md.append(f"| {dept} | {count} | ${budget:.2f} |")

    md.append("")
    md.append("---")
    md.append("")

    # Footer
    md.append("## Managing Agents")
    md.append("")
    md.append("### Using the Agent Management API")
    md.append("")
    md.append("```python")
    md.append("from agent_management_api import *")
    md.append("")
    md.append("# List all agents")
    md.append("agents = list_agents()")
    md.append("")
    md.append("# Get single agent")
    md.append("agent = get_agent(agent_id)")
    md.append("")
    md.append("# Add new agent")
    md.append("new_agent = add_agent({")
    md.append("    'name': 'New Agent',")
    md.append("    'type_id': 1,")
    md.append("    'tier': 2,")
    md.append("    'model': 'claude-sonnet-4-20250514',")
    md.append("    'system_prompt': 'You are...',")
    md.append("    'first_name': 'First',")
    md.append("    'last_name': 'Last',")
    md.append("    'email': 'first.last@archie.ai',")
    md.append("    'title': 'Job Title',")
    md.append("    'department': 'Department',")
    md.append("    'bio': 'Bio text',")
    md.append("    'pronouns': 'they/them',")
    md.append("    'monthly_budget': 40.00")
    md.append("})")
    md.append("")
    md.append("# Update agent")
    md.append("updated = update_agent(agent_id, {")
    md.append("    'email': 'newemail@archie.ai',")
    md.append("    'title': 'New Title',")
    md.append("    'bio': 'Updated bio'")
    md.append("})")
    md.append("")
    md.append("# Update avatar")
    md.append("update_avatar(agent_id, 'https://example.com/avatar.png')")
    md.append("")
    md.append("# Delete agent (soft delete)")
    md.append("delete_agent(agent_id, soft_delete=True)")
    md.append("")
    md.append("# Search agents")
    md.append("results = search_agents('sales')")
    md.append("```")
    md.append("")
    md.append("### Editable Fields")
    md.append("")
    md.append("All agent profiles support editing the following fields:")
    md.append("")
    md.append("- **Personal Info**: first_name, last_name, email, pronouns, bio")
    md.append("- **Professional**: title, department")
    md.append("- **Avatar**: avatar_url (upload photo URL)")
    md.append("- **System**: system_prompt (agent's core instructions)")
    md.append("- **Configuration**: tier, model, monthly_budget, capabilities, metadata")
    md.append("")
    md.append("### Avatar Photo Upload")
    md.append("")
    md.append("To add photos to agent profiles:")
    md.append("")
    md.append("1. Generate or upload avatar image")
    md.append("2. Store image URL (could be local path or cloud storage)")
    md.append("3. Update agent: `update_avatar(agent_id, 'path/to/avatar.png')`")
    md.append("")
    md.append("---")
    md.append("")
    md.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(md)

if __name__ == '__main__':
    print("Generating Agent Directory...")
    print()

    directory_md = generate_directory()

    # Write to file
    output_file = '/mnt/archie_brain/docs/AGENT_DIRECTORY.md'
    with open(output_file, 'w') as f:
        f.write(directory_md)

    print(f"✅ Agent directory created: {output_file}")
    print()
    print("Preview (first 50 lines):")
    print("=" * 70)
    lines = directory_md.split('\n')
    for line in lines[:50]:
        print(line)
    print("...")
    print("=" * 70)
    print()
    print(f"Total lines: {len(lines)}")
