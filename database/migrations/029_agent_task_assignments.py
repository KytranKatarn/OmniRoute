"""
Migration 029: Agent Task Assignments
Phase 6.5: Team Task Assignment System

Creates tables for assigning tasks to agents within specific modules.
This enables the SaaS feature where admins can delegate work to team members.

Creates:
- agent_task_assignments: Main task assignment table
- agent_module_access: Track which modules each agent can access
- agent_task_log: History of task execution
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


def run_migration():
    """Execute the migration"""
    conn = get_db_connection()
    cur = conn.cursor()

    print("Creating agent_task_assignments table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_task_assignments (
            id SERIAL PRIMARY KEY,

            -- Assignment details
            title VARCHAR(255) NOT NULL,
            description TEXT,
            module_id VARCHAR(100),  -- e.g., 'email_manager', 'crm', 'call_center'
            module_route VARCHAR(255),  -- e.g., '/tools/email'

            -- People involved
            agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
            assigned_by INTEGER REFERENCES users(id),
            on_behalf_of INTEGER REFERENCES users(id),  -- If working for a customer

            -- Task metadata
            priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, urgent
            status VARCHAR(50) DEFAULT 'pending',  -- pending, in_progress, completed, cancelled, failed
            task_type VARCHAR(50),  -- research, create, update, review, execute

            -- Context for the agent
            context JSONB DEFAULT '{}',  -- Module-specific context data
            instructions TEXT,  -- Detailed instructions for the agent

            -- Deadlines and timing
            due_date TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            estimated_minutes INTEGER,
            actual_minutes INTEGER,

            -- Results
            result JSONB,  -- Task output/result
            output_summary TEXT,  -- Human-readable summary

            -- Resource tracking
            tokens_used INTEGER DEFAULT 0,
            cost NUMERIC(10,4) DEFAULT 0,

            -- Audit
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating agent_module_access table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_module_access (
            id SERIAL PRIMARY KEY,

            agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
            module_id VARCHAR(100) NOT NULL,

            -- Access levels
            can_view BOOLEAN DEFAULT TRUE,
            can_create BOOLEAN DEFAULT FALSE,
            can_edit BOOLEAN DEFAULT FALSE,
            can_delete BOOLEAN DEFAULT FALSE,
            can_execute BOOLEAN DEFAULT FALSE,

            -- Restrictions
            restricted_actions JSONB DEFAULT '[]',  -- Specific actions not allowed
            allowed_actions JSONB DEFAULT '[]',  -- If set, only these actions allowed

            -- Rate limiting
            daily_task_limit INTEGER,
            monthly_task_limit INTEGER,

            -- Audit
            granted_by INTEGER REFERENCES users(id),
            granted_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP,

            UNIQUE(agent_id, module_id)
        )
    """)

    print("Creating agent_task_log table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_task_log (
            id SERIAL PRIMARY KEY,

            task_id INTEGER REFERENCES agent_task_assignments(id) ON DELETE CASCADE,
            agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,

            -- Log entry
            action VARCHAR(100) NOT NULL,  -- started, progress, completed, failed, note
            message TEXT,
            details JSONB,

            -- Performance
            tokens_used INTEGER DEFAULT 0,
            duration_ms INTEGER,

            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating agent_task_templates table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_task_templates (
            id SERIAL PRIMARY KEY,

            name VARCHAR(255) NOT NULL,
            description TEXT,
            module_id VARCHAR(100),

            -- Template content
            default_instructions TEXT,
            default_context JSONB DEFAULT '{}',
            default_priority VARCHAR(20) DEFAULT 'normal',
            estimated_minutes INTEGER,

            -- Suggested agents
            recommended_agent_ids INTEGER[],
            required_skills VARCHAR(100)[],

            -- Usage tracking
            use_count INTEGER DEFAULT 0,

            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating indexes...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_task_assignments_agent ON agent_task_assignments(agent_id);
        CREATE INDEX IF NOT EXISTS idx_agent_task_assignments_status ON agent_task_assignments(status);
        CREATE INDEX IF NOT EXISTS idx_agent_task_assignments_module ON agent_task_assignments(module_id);
        CREATE INDEX IF NOT EXISTS idx_agent_task_assignments_due ON agent_task_assignments(due_date) WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_agent_task_assignments_created ON agent_task_assignments(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_module_access_agent ON agent_module_access(agent_id);
        CREATE INDEX IF NOT EXISTS idx_agent_module_access_module ON agent_module_access(module_id);
        CREATE INDEX IF NOT EXISTS idx_agent_task_log_task ON agent_task_log(task_id);
        CREATE INDEX IF NOT EXISTS idx_agent_task_log_created ON agent_task_log(created_at DESC);
    """)

    print("Inserting default task templates...")
    cur.execute("""
        INSERT INTO agent_task_templates (name, description, module_id, default_instructions, estimated_minutes, required_skills)
        VALUES
            ('Email Campaign', 'Create and send email campaign', 'email_manager',
             'Create a professional email campaign based on the provided context. Include subject line, body, and call-to-action.',
             30, ARRAY['email_marketing', 'copywriting']),

            ('CRM Lead Follow-up', 'Follow up with leads in CRM', 'crm',
             'Review leads and draft personalized follow-up messages. Prioritize by lead score and last contact date.',
             20, ARRAY['sales', 'crm', 'communication']),

            ('Invoice Generation', 'Generate invoices for clients', 'invoicing',
             'Create professional invoices based on provided project details and pricing.',
             15, ARRAY['accounting', 'documentation']),

            ('Social Media Post', 'Create social media content', 'social_media',
             'Create engaging social media posts for the specified platforms. Include hashtags and optimal posting time.',
             25, ARRAY['social_media', 'content_creation']),

            ('Customer Support Response', 'Draft support responses', 'call_center',
             'Review customer inquiries and draft professional, helpful responses.',
             10, ARRAY['customer_service', 'communication'])
        ON CONFLICT DO NOTHING
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 029 complete: Agent Task Assignments")
    return True


def rollback_migration():
    """Rollback the migration"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS agent_task_log CASCADE")
    cur.execute("DROP TABLE IF EXISTS agent_task_templates CASCADE")
    cur.execute("DROP TABLE IF EXISTS agent_module_access CASCADE")
    cur.execute("DROP TABLE IF EXISTS agent_task_assignments CASCADE")

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 029 rolled back")
    return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback_migration()
    else:
        run_migration()
