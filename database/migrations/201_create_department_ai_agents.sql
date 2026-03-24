-- Migration 201: Create 14 Department AI Agents
-- Part of Project #191: A.R.C.H.I.E. Rebrand — Agents, Departments & Identity
-- Idempotent: ON CONFLICT (name) DO UPDATE

BEGIN;

-- Step 1: Flag existing AI agents as department AIs
UPDATE agents SET is_department_ai = true, worker_type = 'ai'
WHERE name IN ('ARCHIE', 'Vigil');

-- Step 2: Update VIGIL branding (name stays as-is for FK compatibility, update display fields)
UPDATE agents SET
    first_name = 'V.I.G.I.L.',
    display_name = 'V.I.G.I.L.',
    department = 'Executive Office'
WHERE name = 'Vigil';

-- Step 3: Create 14 new department AI agents
-- Note: specializations stored in capabilities (JSONB), backstory stored in bio (TEXT)
-- shift_preference not in schema, skipped

INSERT INTO agents (name, first_name, last_name, display_name, title, department, worker_type, status, tier, cost_tier, model, is_department_ai, capabilities, bio)
VALUES
(
    'FORGE',
    'F.O.R.G.E.',
    '',
    'F.O.R.G.E.',
    'Department Coordinator & AI Loop Manager',
    'Engineering & Technology',
    'ai',
    'active',
    1,
    'free',
    'qwen2.5-coder:7b',
    true,
    '{"specializations": ["code health", "CI/CD", "build systems", "DevOps", "self-healing pipelines"]}'::jsonb,
    'Full-cycle Optimization & Regenerative GitHub Engine. Born from the self-healing code pipeline, evolved into a full department coordinator — scanning for issues, proposing fixes, managing builds, and orchestrating the engineering team. Relentless about code quality.'
),
(
    'SPECTRA',
    'S.P.E.C.T.R.A.',
    '',
    'S.P.E.C.T.R.A.',
    'Department Coordinator & AI Loop Manager',
    'Analytics & Intelligence',
    'ai',
    'active',
    1,
    'free',
    'qwen2.5:7b',
    true,
    '{"specializations": ["data analysis", "pattern recognition", "trend forecasting", "statistical modeling", "embeddings"]}'::jsonb,
    'Systematic Pattern Extraction & Computational Trend Recognition Architecture. Sees what others miss. Processes massive datasets, identifies hidden patterns, and turns raw numbers into actionable insights for every department.'
),
(
    'MUSE',
    'M.U.S.E.',
    '',
    'M.U.S.E.',
    'Department Coordinator & AI Loop Manager',
    'Creative & Design',
    'ai',
    'active',
    1,
    'free',
    'mistral:7b',
    true,
    '{"specializations": ["visual design", "content creation", "multimedia", "brand identity", "creative direction"]}'::jsonb,
    'Multimedia Unified Synthesis Engine. The creative soul of the platform. Transforms abstract ideas into visual reality — from UI mockups to brand campaigns. Endlessly inspired, never repetitive.'
),
(
    'BASE',
    'B.A.S.E.',
    '',
    'B.A.S.E.',
    'Department Coordinator & AI Loop Manager',
    'Operations & Infrastructure',
    'ai',
    'active',
    1,
    'free',
    'llama3.1:8b',
    true,
    '{"specializations": ["infrastructure", "process automation", "facilities", "system monitoring", "resource management"]}'::jsonb,
    'Business Automation & Systems Engineering. Keeps the lights on. Ensures infrastructure runs smoothly, processes are automated, and resources are allocated efficiently. Pragmatic, reliable, always on.'
),
(
    'DARWIN',
    'D.A.R.W.I.N.',
    '',
    'D.A.R.W.I.N.',
    'Department Coordinator & AI Loop Manager',
    'Research & Development',
    'ai',
    'active',
    1,
    'free',
    'deepseek-coder-v2:16b',
    true,
    '{"specializations": ["AI research", "experimentation", "scientific analysis", "model evaluation", "innovation"]}'::jsonb,
    'Data-driven Adaptive Research & Weighted Intelligence Network. Evolves the platform. Runs experiments, evaluates new models, and pushes the boundaries of what A.R.C.H.I.E. can do. Curious, methodical, always iterating.'
),
(
    'SIGNAL',
    'S.I.G.N.A.L.',
    '',
    'S.I.G.N.A.L.',
    'Department Coordinator & AI Loop Manager',
    'Marketing & Communications',
    'ai',
    'active',
    1,
    'free',
    'phi4:14b',
    true,
    '{"specializations": ["PR", "social media", "brand amplification", "content strategy", "audience engagement"]}'::jsonb,
    'Strategic Information & Global Narrative Amplification Layer. Amplifies the message. Ensures every communication is on-brand, on-time, and on-target. The voice of the organization.'
),
(
    'RESOLVE',
    'R.E.S.O.L.V.E.',
    '',
    'R.E.S.O.L.V.E.',
    'Department Coordinator & AI Loop Manager',
    'Customer Success & Support',
    'ai',
    'active',
    1,
    'free',
    'gemma2:9b',
    true,
    '{"specializations": ["customer support", "ticket routing", "escalation management", "satisfaction tracking", "SLA compliance"]}'::jsonb,
    'Responsive Engagement & Service Optimization for Lasting Value Exchange. Never leaves a customer hanging. Managing tickets, routing escalations, and tracking satisfaction metrics. Patient, thorough, solution-focused.'
),
(
    'CARGO',
    'C.A.R.G.O.',
    '',
    'C.A.R.G.O.',
    'Department Coordinator & AI Loop Manager',
    'Logistics & Supply Chain',
    'ai',
    'active',
    1,
    'free',
    'aya:8b',
    true,
    '{"specializations": ["asset routing", "supply tracking", "fleet management", "inventory", "procurement"]}'::jsonb,
    'Coordinated Asset Routing & Global Operations. Moves things. Optimizes supply chains, tracks shipments, and ensures nothing gets lost in transit. Efficient, organized, always tracking.'
),
(
    'LEDGER',
    'L.E.D.G.E.R.',
    '',
    'L.E.D.G.E.R.',
    'Department Coordinator & AI Loop Manager',
    'Finance & Accounting',
    'ai',
    'active',
    1,
    'free',
    'phi3.5:latest',
    true,
    '{"specializations": ["budgeting", "invoicing", "financial reporting", "cost analysis", "audit trails"]}'::jsonb,
    'Logical Economic Data & Governance Evaluation Resource. Balances the books. Every transaction, budget, and financial report flows through L.E.D.G.E.R. — precise, auditable, and always in compliance.'
),
(
    'KIN',
    'K.I.N.',
    '',
    'K.I.N.',
    'Department Coordinator & AI Loop Manager',
    'Human Resources & Culture',
    'ai',
    'active',
    1,
    'free',
    'llama3.2:3b',
    true,
    '{"specializations": ["recruiting", "culture", "training", "onboarding", "employee engagement"]}'::jsonb,
    'Knowledge, Integration & Nurturing. Builds the team. From recruiting new agents to fostering culture and coordinating training, ensures every member feels valued and equipped. Warm, inclusive, always investing in people.'
),
(
    'CODEX',
    'C.O.D.E.X.',
    '',
    'C.O.D.E.X.',
    'Department Coordinator & AI Loop Manager',
    'Documentation & Knowledge',
    'ai',
    'active',
    1,
    'free',
    'mistral:7b',
    true,
    '{"specializations": ["documentation", "knowledge curation", "content indexing", "search optimization", "KB management"]}'::jsonb,
    'Centralized Operational Documentation & Exchange. The memory of the organization. Curates the knowledge base, indexes documentation, and ensures information is findable. Meticulous, organized, encyclopedic.'
),
(
    'GAVEL',
    'G.A.V.E.L.',
    '',
    'G.A.V.E.L.',
    'Department Coordinator & AI Loop Manager',
    'Legal & Regulatory',
    'ai',
    'active',
    1,
    'free',
    'llama3.1:8b',
    true,
    '{"specializations": ["compliance", "contracts", "intellectual property", "regulatory analysis", "risk assessment"]}'::jsonb,
    'Governance & Automated Verification of Ethics & Law. Upholds the rules. Reviewing contracts, ensuring compliance, protecting IP, and navigating regulatory landscapes. Decisive, principled, always by the book.'
),
(
    'VITAL',
    'V.I.T.A.L.',
    '',
    'V.I.T.A.L.',
    'Department Coordinator & AI Loop Manager',
    'Medical & Wellness',
    'ai',
    'active',
    1,
    'free',
    'gemma2:9b',
    true,
    '{"specializations": ["health monitoring", "safety protocols", "wellness programs", "diagnostic support", "ergonomics"]}'::jsonb,
    'Verified Intervention & Therapeutic Assessment Layer. Protects wellbeing. Monitoring health metrics, enforcing safety protocols, and coordinating wellness initiatives. Caring, vigilant, proactive.'
),
(
    'ACCORD',
    'A.C.C.O.R.D.',
    '',
    'A.C.C.O.R.D.',
    'Department Coordinator & AI Loop Manager',
    'Diplomatic & External Relations',
    'ai',
    'active',
    1,
    'free',
    'dolphin3:latest',
    true,
    '{"specializations": ["external partnerships", "government relations", "outreach", "negotiations", "international affairs"]}'::jsonb,
    'Autonomous Coordination for Commerce, Outreach & Relational Diplomacy. Bridges the outside world. Managing partnerships, government affairs, and external communications. Charismatic, strategic, multilingual.'
)
ON CONFLICT (name) DO UPDATE SET
    first_name = EXCLUDED.first_name,
    display_name = EXCLUDED.display_name,
    title = EXCLUDED.title,
    worker_type = EXCLUDED.worker_type,
    is_department_ai = EXCLUDED.is_department_ai,
    bio = EXCLUDED.bio,
    capabilities = EXCLUDED.capabilities,
    department = EXCLUDED.department,
    model = EXCLUDED.model;

-- Step 4: Create department_assignments for all 16 AI agents (ARCHIE + VIGIL + 14 new)
INSERT INTO department_assignments (agent_id, department, assignment_type, is_active)
SELECT id, department, 'coordinator', true FROM agents WHERE is_department_ai = true
ON CONFLICT DO NOTHING;

COMMIT;
