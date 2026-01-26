#!/usr/bin/env python3
"""
Migration: Populate agent_skills table
Phase 17: Team Skills & HR Dashboard

This migration:
1. Maps AI models to their inherent skill strengths
2. Extracts skills from existing agent capabilities (specialties)
3. Populates the agent_skills table for skill-based routing

Run: python3 012_populate_agent_skills.py
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
from datetime import datetime
import json

# Database connection
DB_CONFIG = {
    'host': 'localhost',
    'database': 'archie',
    'user': 'archie',
    'password': 'archie_secure_2024'
}

# Model-to-skill mappings based on model capabilities
# Proficiency: 1-5 (5 = expert, 4 = advanced, 3 = proficient, 2 = familiar, 1 = basic)
MODEL_SKILLS = {
    'qwen2.5-coder:7b': {
        'python': 5,
        'javascript': 4,
        'code_review': 4,
        'quick_fixes': 5,
        'syntax_correction': 5,
        'bug_fixing': 4,
        'refactoring': 4,
        'documentation': 3,
    },
    'deepseek-coder-v2:16b': {
        'architecture': 5,
        'algorithm_design': 5,
        'complex_reasoning': 5,
        'system_design': 4,
        'code_review': 4,
        'python': 4,
        'performance_optimization': 4,
        'multi_file_changes': 4,
    },
    'deepseek-coder:33b': {
        'system_design': 5,
        'refactoring': 5,
        'multi_file_changes': 5,
        'architecture': 5,
        'complex_reasoning': 5,
        'code_review': 5,
        'performance_optimization': 4,
        'database_optimization': 4,
    },
    'codellama:latest': {
        'quick_fixes': 4,
        'simple_edits': 5,
        'syntax_correction': 4,
        'python': 4,
        'javascript': 4,
        'bug_fixing': 4,
    },
    'claude-sonnet-4-20250514': {
        'security_analysis': 5,
        'api_design': 5,
        'documentation': 5,
        'code_review': 5,
        'python': 5,
        'javascript': 5,
        'complex_reasoning': 5,
        'technical_writing': 5,
        'best_practices': 5,
    },
    'claude-opus-4-20250514': {
        'architecture': 5,
        'complex_security': 5,
        'strategic_planning': 5,
        'system_design': 5,
        'technical_leadership': 5,
        'code_review': 5,
        'security_analysis': 5,
        'complex_reasoning': 5,
        'multi_file_changes': 5,
    },
    'gpt-4': {
        'analysis': 5,
        'creative_solutions': 5,
        'technical_writing': 5,
        'code_review': 5,
        'python': 4,
        'javascript': 4,
        'documentation': 5,
    },
    'gpt-4o': {
        'analysis': 5,
        'creative_solutions': 5,
        'technical_writing': 5,
        'code_review': 5,
        'python': 4,
        'javascript': 4,
        'documentation': 5,
        'complex_reasoning': 5,
    },
    'grok-beta': {
        'analysis': 4,
        'creative_solutions': 4,
        'code_review': 4,
        'python': 4,
        'real_time_info': 5,
        'trend_analysis': 4,
    },
    'llama3.1:8b': {
        'general_tasks': 4,
        'summarization': 4,
        'documentation': 4,
        'python': 4,
        'simple_edits': 4,
        'communication': 4,
    },
    'llama3:latest': {
        'general_tasks': 4,
        'summarization': 4,
        'documentation': 3,
        'python': 3,
        'communication': 4,
    },
    'nous-hermes2': {
        'general_tasks': 4,
        'communication': 4,
        'documentation': 4,
        'creative_solutions': 4,
    },
    'command-r:latest': {
        'general_tasks': 4,
        'retrieval': 4,
        'documentation': 4,
        'summarization': 4,
    },
    'mixtral:8x7b': {
        'general_tasks': 4,
        'python': 4,
        'analysis': 4,
        'multi_language': 4,
    },
    'gemma2:2b': {
        'quick_fixes': 3,
        'simple_edits': 4,
        'summarization': 3,
    },
    'aya:8b': {
        'multilingual': 5,
        'translation': 4,
        'communication': 4,
    },
    'dolphin3:latest': {
        'general_tasks': 4,
        'creative_solutions': 4,
        'uncensored_analysis': 4,
    },
}

# Skill categories for organization
SKILL_CATEGORIES = {
    # Security
    'security_analysis': 'security',
    'complex_security': 'security',
    'penetration_testing': 'security',
    'vulnerability_assessment': 'security',
    'threat_detection': 'security',
    'incident_response': 'security',
    'security_architecture': 'security',

    # Development
    'python': 'development',
    'javascript': 'development',
    'typescript': 'development',
    'react': 'development',
    'flask': 'development',
    'django': 'development',
    'html_css': 'development',
    'sql': 'development',

    # Architecture
    'architecture': 'architecture',
    'system_design': 'architecture',
    'technical_leadership': 'architecture',
    'strategic_planning': 'architecture',
    'database_design': 'architecture',
    'api_design': 'architecture',

    # Code Quality
    'code_review': 'code_quality',
    'refactoring': 'code_quality',
    'best_practices': 'code_quality',
    'bug_fixing': 'code_quality',
    'syntax_correction': 'code_quality',
    'quick_fixes': 'code_quality',
    'simple_edits': 'code_quality',

    # Performance
    'performance_optimization': 'performance',
    'profiling': 'performance',
    'database_optimization': 'performance',
    'algorithm_design': 'performance',

    # Documentation
    'documentation': 'documentation',
    'technical_writing': 'documentation',
    'summarization': 'documentation',

    # Analysis
    'analysis': 'analysis',
    'complex_reasoning': 'analysis',
    'creative_solutions': 'analysis',
    'trend_analysis': 'analysis',

    # Operations
    'multi_file_changes': 'operations',
    'devops': 'operations',
    'deployment': 'operations',
    'ci_cd': 'operations',
    'monitoring': 'operations',

    # Communication
    'communication': 'communication',
    'customer_service': 'communication',
    'call_handling': 'communication',

    # Specialized
    'general_tasks': 'general',
    'retrieval': 'general',
    'real_time_info': 'general',
    'multilingual': 'specialized',
    'translation': 'specialized',
    'multi_language': 'specialized',
    'uncensored_analysis': 'specialized',

    # Business
    'marketing': 'business',
    'sales': 'business',
    'finance': 'business',
    'compliance': 'business',
    'legal': 'business',
    'hr': 'business',
    'project_management': 'business',
}

# Specialty to skill mapping (from agent capabilities)
SPECIALTY_TO_SKILL = {
    'marketing': 'marketing',
    'analysis': 'analysis',
    'problem_solving': 'complex_reasoning',
    'call_handling': 'call_handling',
    'visitor_management': 'communication',
    'front_desk_operations': 'communication',
    'threat_detection': 'threat_detection',
    'vulnerability_management': 'vulnerability_assessment',
    'incident_response': 'incident_response',
    'security_architecture': 'security_architecture',
    'compliance': 'compliance',
    'gdpr': 'compliance',
    'ccpa': 'compliance',
    'data_governance': 'compliance',
    'privacy_by_design': 'security_analysis',
    'user_rights': 'compliance',
    'regulatory_compliance': 'compliance',
    'policy_analysis': 'analysis',
    'audit': 'compliance',
    'frontend_development': 'javascript',
    'backend_development': 'python',
    'api_design': 'api_design',
    'database_design': 'database_design',
    'testing': 'code_review',
    'test_automation': 'code_review',
    'qa': 'code_review',
    'technical_writing': 'technical_writing',
    'documentation': 'documentation',
    'devops': 'devops',
    'ci_cd': 'ci_cd',
    'deployment': 'deployment',
    'monitoring': 'monitoring',
    'logging': 'monitoring',
    'observability': 'monitoring',
    'customer_service': 'customer_service',
    'sales': 'sales',
    'marketing_automation': 'marketing',
    'content_creation': 'documentation',
    'social_media': 'communication',
    'seo': 'analysis',
    'data_analysis': 'analysis',
    'financial_analysis': 'finance',
    'budgeting': 'finance',
    'forecasting': 'analysis',
    'hr_operations': 'hr',
    'recruitment': 'hr',
    'employee_relations': 'hr',
    'project_management': 'project_management',
    'agile': 'project_management',
    'scrum': 'project_management',
}


def get_skill_category(skill_name: str) -> str:
    """Get the category for a skill"""
    return SKILL_CATEGORIES.get(skill_name, 'general')


def populate_skills():
    """Main function to populate agent_skills table"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    print("=" * 60)
    print("AGENT SKILLS MIGRATION")
    print("=" * 60)

    # Check current count
    cur.execute("SELECT COUNT(*) as count FROM agent_skills")
    current_count = cur.fetchone()['count']
    print(f"\nCurrent agent_skills records: {current_count}")

    if current_count > 0:
        print("\nWARNING: Table already has data.")
        response = input("Do you want to clear and repopulate? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            return

        cur.execute("DELETE FROM agent_skills")
        conn.commit()
        print("Cleared existing records.")

    # Get all agents
    cur.execute("""
        SELECT id, name, model, capabilities
        FROM agents
        WHERE model IS NOT NULL
        ORDER BY id
    """)
    agents = cur.fetchall()
    print(f"\nFound {len(agents)} agents to process")

    skills_added = 0
    agents_processed = 0

    for agent in agents:
        agent_id = agent['id']
        model = agent['model']
        capabilities = agent['capabilities'] or {}
        agent_skills = set()  # Use set to avoid duplicates

        # 1. Add model-based skills
        if model in MODEL_SKILLS:
            for skill, proficiency in MODEL_SKILLS[model].items():
                agent_skills.add((skill, get_skill_category(skill), proficiency, 'model_capability'))

        # 2. Extract skills from capabilities.specialties
        specialties = capabilities.get('specialties', [])
        for specialty in specialties:
            skill = SPECIALTY_TO_SKILL.get(specialty, specialty)
            category = get_skill_category(skill)
            # Give specialty-based skills a proficiency of 4 (advanced)
            agent_skills.add((skill, category, 4, 'agent_specialty'))

        # 3. Extract skills from capabilities.expertise
        expertise = capabilities.get('expertise', [])
        for exp in expertise:
            exp_lower = exp.lower().replace(' ', '_')
            skill = SPECIALTY_TO_SKILL.get(exp_lower, exp_lower)
            category = get_skill_category(skill)
            # Give expertise-based skills a proficiency of 3 (proficient)
            agent_skills.add((skill, category, 3, 'agent_expertise'))

        # Insert skills for this agent
        for skill_name, skill_category, proficiency, source in agent_skills:
            try:
                # Use ON CONFLICT to handle duplicates (unique constraint on agent_id, skill_name)
                cur.execute("""
                    INSERT INTO agent_skills
                    (id, agent_id, skill_name, skill_category, proficiency_level, notes, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent_id, skill_name) DO UPDATE SET
                        proficiency_level = GREATEST(agent_skills.proficiency_level, EXCLUDED.proficiency_level),
                        updated_at = EXCLUDED.updated_at
                """, (
                    str(uuid.uuid4()),
                    agent_id,
                    skill_name,
                    skill_category,
                    proficiency,
                    f"Source: {source}",
                    datetime.now(),
                    datetime.now()
                ))
                skills_added += 1
            except Exception as e:
                conn.rollback()  # Rollback to recover from error
                print(f"  Error adding skill {skill_name} for agent {agent_id}: {e}")

        # Commit after each agent to avoid losing all progress on error
        conn.commit()
        agents_processed += 1
        if agents_processed % 10 == 0:
            print(f"  Processed {agents_processed}/{len(agents)} agents...")

    conn.commit()

    print(f"\n✅ Migration complete!")
    print(f"   - Agents processed: {agents_processed}")
    print(f"   - Skills added: {skills_added}")

    # Show summary stats
    cur.execute("""
        SELECT skill_category, COUNT(*) as count,
               COUNT(DISTINCT skill_name) as unique_skills,
               ROUND(AVG(proficiency_level), 1) as avg_proficiency
        FROM agent_skills
        GROUP BY skill_category
        ORDER BY count DESC
    """)

    print("\n=== Skills by Category ===")
    for row in cur.fetchall():
        print(f"  {row['skill_category']}: {row['count']} entries, "
              f"{row['unique_skills']} unique skills, avg proficiency {row['avg_proficiency']}")

    # Show top skills
    cur.execute("""
        SELECT skill_name, COUNT(DISTINCT agent_id) as agent_count,
               ROUND(AVG(proficiency_level), 1) as avg_proficiency
        FROM agent_skills
        GROUP BY skill_name
        ORDER BY agent_count DESC
        LIMIT 15
    """)

    print("\n=== Top 15 Skills (by agent count) ===")
    for row in cur.fetchall():
        print(f"  {row['skill_name']}: {row['agent_count']} agents, avg {row['avg_proficiency']}")

    # Show skill gaps (skills with few agents)
    cur.execute("""
        SELECT skill_name, COUNT(DISTINCT agent_id) as agent_count
        FROM agent_skills
        GROUP BY skill_name
        HAVING COUNT(DISTINCT agent_id) <= 3
        ORDER BY agent_count ASC, skill_name
        LIMIT 10
    """)

    print("\n=== Skill Gaps (≤3 agents) ===")
    for row in cur.fetchall():
        print(f"  ⚠️ {row['skill_name']}: only {row['agent_count']} agent(s)")

    cur.close()
    conn.close()


def verify_skills():
    """Verify the migration was successful"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT COUNT(*) as total FROM agent_skills")
    total = cur.fetchone()['total']

    cur.execute("SELECT COUNT(DISTINCT agent_id) as agents FROM agent_skills")
    agents = cur.fetchone()['agents']

    cur.execute("SELECT COUNT(DISTINCT skill_name) as skills FROM agent_skills")
    skills = cur.fetchone()['skills']

    print(f"\n=== Verification ===")
    print(f"Total skill records: {total}")
    print(f"Agents with skills: {agents}")
    print(f"Unique skills: {skills}")

    cur.close()
    conn.close()

    return total > 0


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--verify':
        verify_skills()
    else:
        populate_skills()
        verify_skills()
