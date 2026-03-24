-- Migration 200: Floors & Department Assignments
-- Phase 1.1 of A.R.C.H.I.E. Rebrand (Project #191)
-- Replaces 10-station model with 5 floors / 16 departments
-- 2026-03-24

BEGIN;

-- 1. Floors table (visual grouping for departments)
CREATE TABLE IF NOT EXISTS floors (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(50) NOT NULL,
    color VARCHAR(7) NOT NULL,
    deck_number INTEGER NOT NULL,
    departments TEXT[] NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed floors (idempotent)
INSERT INTO floors (code, name, color, deck_number, departments) VALUES
    ('BRIDGE',      'Bridge',      '#00FFFF', 1, ARRAY['Executive Office']),
    ('OPERATIONS',  'Operations',  '#FFAA00', 2, ARRAY['Operations & Infrastructure', 'Logistics & Supply Chain', 'Finance & Accounting']),
    ('ENGINEERING', 'Engineering', '#0EA5E9', 3, ARRAY['Engineering & Technology', 'Security & Compliance', 'Research & Development']),
    ('CREATIVE',    'Creative',    '#F472B6', 4, ARRAY['Creative & Design', 'Marketing & Communications', 'Documentation & Knowledge']),
    ('SERVICES',    'Services',    '#10B981', 5, ARRAY['Customer Success & Support', 'Human Resources & Culture', 'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations', 'Analytics & Intelligence'])
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    color = EXCLUDED.color,
    deck_number = EXCLUDED.deck_number,
    departments = EXCLUDED.departments;

-- 2. Department assignments table (replaces station_assignments)
CREATE TABLE IF NOT EXISTS department_assignments (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE NOT NULL,
    department VARCHAR(100) NOT NULL,
    assignment_type VARCHAR(20) DEFAULT 'member',
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

-- Unique: one active assignment per agent
CREATE UNIQUE INDEX IF NOT EXISTS idx_dept_assignments_one_active_per_agent
    ON department_assignments (agent_id) WHERE is_active = true;

-- Lookup by department
CREATE INDEX IF NOT EXISTS idx_dept_assignments_department
    ON department_assignments (department);

-- Filter by active
CREATE INDEX IF NOT EXISTS idx_dept_assignments_active
    ON department_assignments (is_active);

-- 3. Add is_department_ai column to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_department_ai BOOLEAN DEFAULT false;

-- 4. Add worker_type CHECK constraint (includes 'ai')
ALTER TABLE agents DROP CONSTRAINT IF EXISTS chk_agents_worker_type;
ALTER TABLE agents ADD CONSTRAINT chk_agents_worker_type
    CHECK (worker_type IN ('internal', 'external', 'contractor', 'local', 'ai'));

COMMIT;
