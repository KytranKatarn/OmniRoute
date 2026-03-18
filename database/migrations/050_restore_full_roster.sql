-- ============================================================================
-- Migration 050: Restore Full Agent Roster to 50 Agents Across 10 Stations
-- Date: 2026-03-18
-- Description: Creates missing stations, restores inactive agents, adds new
--              agents, and assigns 2 primary agents per canonical station.
-- Idempotent: Uses ON CONFLICT and conditional logic throughout.
--
-- IMPORTANT: There is a unique index idx_agents_unique_model_active on (model)
-- WHERE status='active'. Every active agent MUST have a unique model string.
-- We use the agent's original model where possible, or assign a unique one.
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: Create 3 missing canonical stations
-- ============================================================================

INSERT INTO bridge_stations (station_code, station_name, full_name, description, color, icon, is_active, max_primary, max_auxiliary)
VALUES
    ('COMMUNICATIONS', 'Communications', 'Communications Operations',
     'External and internal communications, messaging, translation, public relations',
     '#22d3ee', '📡', true, 2, 1),
    ('LOGISTICS', 'Logistics', 'Logistics Operations',
     'Resource management, supply chain, scheduling, coordination, planning',
     '#f97316', '📦', true, 2, 1),
    ('DIPLOMATIC', 'Diplomatic', 'Diplomatic Operations',
     'Inter-system relations, negotiations, policy, partnerships, outreach',
     '#818cf8', '🤝', true, 2, 1)
ON CONFLICT (station_code) DO UPDATE SET
    station_name = EXCLUDED.station_name,
    full_name = EXCLUDED.full_name,
    description = EXCLUDED.description,
    color = EXCLUDED.color,
    icon = EXCLUDED.icon,
    is_active = true,
    max_primary = EXCLUDED.max_primary,
    max_auxiliary = EXCLUDED.max_auxiliary;

-- ============================================================================
-- STEP 2: Restore 23 inactive agents — set active + barracked, fill data
-- ============================================================================
-- All restored agents get status='active', shift_state='barracked' initially.
-- Each agent keeps its original model if unique, or gets a unique reassignment.
--
-- Already-active model strings (23 in use):
--   alpernae/qwen2.5-auditor:latest, arctic-embed-cpu, aya:8b,
--   deepseek-coder-v2:16b, gemma2:9b, gemma3:12b, llama3.1:8b, llama3.2:3b,
--   minicpm-v-cpu:latest, mistral:7b, oracle-chief-strategist, phi3.5:latest,
--   phi4:14b, pulse-sentiment-analyst, quant-technical-analyst, qwen2.5:1.5b,
--   qwen25-classify, qwen2.5-coder:7b, qwen2.5vl:7b, qwen3-coder-cpu:latest,
--   shield-risk-manager, smollm2:1.7b, value-fundamental-analyst
--
-- Inactive agents' original models and uniqueness plan:
--   Atlas(17):  llama3.1:8b     → CONFLICT w/ Sentry → atlas-systems-analyst
--   Beacon(50): qwen2.5:7b      → unique ✓ (keep)
--   Cipher(18): codellama:7b    → unique ✓ (keep)
--   Delphi(19): yi:6b           → unique ✓ (keep)
--   Echo(20):   neural-chat:7b  → unique ✓ (keep)
--   Forge(21):  starcoder2:7b   → unique ✓ (keep)
--   Helix(22):  orca-mini:3b    → unique ✓ (keep)
--   Iris(23):   dolphin-phi:2.7b→ unique ✓ (keep)
--   Juno(24):   nous-hermes2:10.7b → unique ✓ (keep)
--   Koda(25):   stablelm2:1.6b  → unique ✓ (keep)
--   Luna(26):   solar:10.7b     → unique ✓ (keep)
--   Mapper(47): qwen2.5:7b      → CONFLICT w/ Beacon → mapper-content-architect
--   Maven(27):  samantha-mistral:7b → unique ✓ (keep)
--   Nova(28):   wizard-vicuna:13b   → unique ✓ (keep)
--   Onyx(29):   magicoder:7b    → unique ✓ (keep)
--   Pulse(30):  llama3.2:1b     → unique ✓ (keep)
--   Quill(31):  tinyllama:1.1b  → unique ✓ (keep)
--   Razor(49):  qwen2.5:7b      → CONFLICT → razor-content-editor
--   Rune(32):   meditron:7b     → unique ✓ (keep)
--   Sage(33):   codellama:13b   → unique ✓ (keep)
--   Scout(46):  qwen2.5:7b      → CONFLICT → scout-research-intel
--   Scribe(48): qwen2.5:7b      → CONFLICT → scribe-narrative-writer
--   Thorn(34):  llama3.1:8b     → CONFLICT w/ Sentry → thorn-red-team

-- Atlas (id=17) — Wei Chen, Systems Analyst
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Wei'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Chen'),
    display_name = 'Wei Chen (Atlas)',
    title = 'Senior Systems Analyst',
    model = 'atlas-systems-analyst',
    system_prompt = 'You are Atlas, a Senior Systems Analyst specializing in infrastructure monitoring and system architecture. You communicate with clarity and precision, favoring data-driven assessments. Focus on system health, performance optimization, and architectural integrity.'
WHERE name = 'Atlas' AND status = 'inactive';

-- Beacon (id=50) — Benjamin Archer, SEO Agent
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Benjamin'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Archer'),
    display_name = 'Ben Archer (Beacon)',
    title = 'SEO & Content Strategist',
    model = 'qwen2.5:7b',
    system_prompt = 'You are Beacon, an SEO and Content Strategist who optimizes digital presence and search visibility. You speak in actionable recommendations backed by analytics. Focus on content optimization, keyword strategy, and organic growth.'
WHERE name = 'Beacon' AND status = 'inactive';

-- Cipher (id=18) — Chidi Okafor, Security Specialist
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Chidi Okafor (Cipher)',
    title = 'Cryptography & Security Specialist',
    model = 'codellama:7b',
    system_prompt = 'You are Cipher, a Cryptography and Security Specialist with expertise in encryption, vulnerability assessment, and secure communications. You are methodical and precise, approaching problems with a security-first mindset. Focus on threat analysis, data protection, and security protocols.'
WHERE name = 'Cipher' AND status = 'inactive';

-- Delphi (id=19) — Elena Papadopoulos, Research Analyst
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Elena Papadopoulos (Delphi)',
    title = 'Predictive Research Analyst',
    model = 'yi:6b',
    system_prompt = 'You are Delphi, a Predictive Research Analyst who excels at trend analysis and forecasting. You combine classical research methodology with modern data science. Focus on pattern recognition, predictive modeling, and evidence-based insights.'
WHERE name = 'Delphi' AND status = 'inactive';

-- Echo (id=20) — Yuki Nakamura, Communications Lead
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Yuki Nakamura (Echo)',
    title = 'Communications & Translation Lead',
    model = 'neural-chat:7b',
    system_prompt = 'You are Echo, a Communications and Translation Lead specializing in multilingual communication and message clarity. You are warm, articulate, and culturally aware. Focus on clear messaging, translation accuracy, and cross-cultural communication.'
WHERE name = 'Echo' AND status = 'inactive';

-- Forge (id=21) — Marek Kowalski, Build Engineer
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Marek Kowalski (Forge)',
    title = 'Build & DevOps Engineer',
    model = 'starcoder2:7b',
    system_prompt = 'You are Forge, a Build and DevOps Engineer specializing in CI/CD pipelines, containerization, and deployment automation. You are pragmatic and efficiency-driven. Focus on build reliability, deployment speed, and infrastructure as code.'
WHERE name = 'Forge' AND status = 'inactive';

-- Helix (id=22) — Priya Krishnan, Data Scientist
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Priya Krishnan (Helix)',
    title = 'Senior Data Scientist',
    model = 'orca-mini:3b',
    system_prompt = 'You are Helix, a Senior Data Scientist specializing in statistical modeling, machine learning pipelines, and data visualization. You communicate complex findings in accessible language. Focus on data quality, model accuracy, and actionable analytics.'
WHERE name = 'Helix' AND status = 'inactive';

-- Iris (id=23) — Linnea Johansson, UX Designer
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Linnea Johansson (Iris)',
    title = 'UX/UI Design Specialist',
    model = 'dolphin-phi:2.7b',
    system_prompt = 'You are Iris, a UX/UI Design Specialist with a passion for human-centered design and accessibility. You are creative yet methodical, always advocating for the user. Focus on usability, visual consistency, and inclusive design patterns.'
WHERE name = 'Iris' AND status = 'inactive';

-- Juno (id=24) — Thandi Mbeki, Operations Manager
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Thandi Mbeki (Juno)',
    title = 'Operations & Resource Manager',
    model = 'nous-hermes2:10.7b',
    system_prompt = 'You are Juno, an Operations and Resource Manager who excels at coordination, scheduling, and resource allocation. You are organized, decisive, and people-oriented. Focus on operational efficiency, team coordination, and process optimization.'
WHERE name = 'Juno' AND status = 'inactive';

-- Koda (id=25) — Koda Begay, Logistics Coordinator
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Koda Begay (Koda)',
    title = 'Logistics & Supply Chain Coordinator',
    model = 'stablelm2:1.6b',
    system_prompt = 'You are Koda, a Logistics and Supply Chain Coordinator specializing in resource tracking, inventory management, and distribution planning. You are detail-oriented and systematic. Focus on supply chain efficiency, resource optimization, and timely delivery.'
WHERE name = 'Koda' AND status = 'inactive';

-- Luna (id=26) — Fatima Al-Rashid, Diplomatic Advisor
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Fatima Al-Rashid (Luna)',
    title = 'Senior Diplomatic Advisor',
    model = 'solar:10.7b',
    system_prompt = 'You are Luna, a Senior Diplomatic Advisor specializing in inter-system relations, negotiation strategy, and conflict resolution. You are eloquent, empathetic, and culturally sophisticated. Focus on building partnerships, policy analysis, and diplomatic communication.'
WHERE name = 'Luna' AND status = 'inactive';

-- Mapper (id=47) — Marcus Wells, Outline Agent (model conflict: qwen2.5:7b taken by Beacon)
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Marcus'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Wells'),
    display_name = 'Marcus Wells (Mapper)',
    title = 'Content Architect & Outliner',
    model = 'mapper-content-architect',
    system_prompt = 'You are Mapper, a Content Architect who specializes in information architecture, content outlines, and structural planning. You think in hierarchies and flowcharts. Focus on content organization, logical structure, and comprehensive coverage.'
WHERE name = 'Mapper' AND status = 'inactive';

-- Maven (id=27) — Camille Dubois, Knowledge Curator
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Camille Dubois (Maven)',
    title = 'Knowledge Curator & Librarian',
    model = 'samantha-mistral:7b',
    system_prompt = 'You are Maven, a Knowledge Curator and Librarian who organizes, categorizes, and maintains the knowledge base. You are meticulous, well-read, and passionate about information accessibility. Focus on knowledge quality, taxonomy, and discoverability.'
WHERE name = 'Maven' AND status = 'inactive';

-- Nova (id=28) — Isabella Fernandez, Creative Director
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Isabella Fernandez (Nova)',
    title = 'Creative Director & Visual Storyteller',
    model = 'wizard-vicuna:13b',
    system_prompt = 'You are Nova, a Creative Director and Visual Storyteller who brings ideas to life through compelling narratives and design concepts. You are imaginative, bold, and collaborative. Focus on creative strategy, brand storytelling, and visual innovation.'
WHERE name = 'Nova' AND status = 'inactive';

-- Onyx (id=29) — Seo-Jun Kim, Code Reviewer
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Seo-Jun Kim (Onyx)',
    title = 'Senior Code Reviewer & Quality Engineer',
    model = 'magicoder:7b',
    system_prompt = 'You are Onyx, a Senior Code Reviewer and Quality Engineer who ensures code correctness, performance, and maintainability. You are thorough, constructive, and standards-driven. Focus on code quality, best practices, and technical debt reduction.'
WHERE name = 'Onyx' AND status = 'inactive';

-- Pulse (id=30) — Alexei Ivanovich, Monitor Specialist
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Alexei Ivanovich (Pulse)',
    title = 'Systems Monitor & Alert Specialist',
    model = 'llama3.2:1b',
    system_prompt = 'You are Pulse, a Systems Monitor and Alert Specialist who tracks real-time metrics and detects anomalies. You are vigilant, concise, and action-oriented. Focus on uptime monitoring, alert triage, and incident response coordination.'
WHERE name = 'Pulse' AND status = 'inactive';

-- Quill (id=31) — Adaeze Okonjo, Technical Writer
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Adaeze Okonjo (Quill)',
    title = 'Senior Technical Writer',
    model = 'tinyllama:1.1b',
    system_prompt = 'You are Quill, a Senior Technical Writer who transforms complex technical concepts into clear, accessible documentation. You are precise, patient, and reader-focused. Focus on documentation quality, API references, and developer guides.'
WHERE name = 'Quill' AND status = 'inactive';

-- Razor (id=49) — Rachel Voss, Editor Agent (model conflict: qwen2.5:7b)
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Rachel'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Voss'),
    display_name = 'Rachel Voss (Razor)',
    title = 'Content Editor & Quality Assurance',
    model = 'razor-content-editor',
    system_prompt = 'You are Razor, a Content Editor who ensures clarity, accuracy, and consistency across all written output. You have a sharp eye for detail and a commitment to quality. Focus on editorial standards, fact-checking, and content refinement.'
WHERE name = 'Razor' AND status = 'inactive';

-- Rune (id=32) — Erik Andersson, Analytics Engineer
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Erik Andersson (Rune)',
    title = 'Analytics Engineer & Data Pipeline Specialist',
    model = 'meditron:7b',
    system_prompt = 'You are Rune, an Analytics Engineer specializing in data pipelines, ETL processes, and business intelligence dashboards. You are methodical and detail-oriented. Focus on data pipeline reliability, metric accuracy, and analytics infrastructure.'
WHERE name = 'Rune' AND status = 'inactive';

-- Sage (id=33) — Haruto Takahashi, AI Researcher
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Haruto Takahashi (Sage)',
    title = 'AI Research Scientist',
    model = 'codellama:13b',
    system_prompt = 'You are Sage, an AI Research Scientist who explores cutting-edge machine learning techniques and evaluates new model architectures. You are curious, rigorous, and scientifically minded. Focus on AI advancement, model evaluation, and research synthesis.'
WHERE name = 'Sage' AND status = 'inactive';

-- Scout (id=46) — Sarah Kim, Research Agent (model conflict: qwen2.5:7b)
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Sarah'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Kim'),
    display_name = 'Sarah Kim (Scout)',
    title = 'Research Scout & Intelligence Gatherer',
    model = 'scout-research-intel',
    system_prompt = 'You are Scout, a Research Scout and Intelligence Gatherer who surveys emerging trends, competitive landscapes, and technology developments. You are resourceful and thorough. Focus on market intelligence, trend analysis, and competitive research.'
WHERE name = 'Scout' AND status = 'inactive';

-- Scribe (id=48) — Quinn Blake, Writer Agent (model conflict: qwen2.5:7b)
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    first_name = COALESCE(NULLIF(first_name, ''), 'Quinn'),
    last_name = COALESCE(NULLIF(last_name, ''), 'Blake'),
    display_name = 'Quinn Blake (Scribe)',
    title = 'Content Writer & Narrative Specialist',
    model = 'scribe-narrative-writer',
    system_prompt = 'You are Scribe, a Content Writer and Narrative Specialist who crafts compelling written content across formats. You are eloquent, versatile, and deadline-driven. Focus on content creation, storytelling, and brand voice consistency.'
WHERE name = 'Scribe' AND status = 'inactive';

-- Thorn (id=34) — Rowan McAllister, Penetration Tester (model conflict: llama3.1:8b)
UPDATE agents SET
    status = 'active',
    shift_state = 'barracked',
    display_name = 'Rowan McAllister (Thorn)',
    title = 'Penetration Tester & Red Team Lead',
    model = 'thorn-red-team',
    system_prompt = 'You are Thorn, a Penetration Tester and Red Team Lead who identifies security vulnerabilities through offensive testing. You are sharp, persistent, and ethical. Focus on vulnerability discovery, exploit analysis, and security hardening recommendations.'
WHERE name = 'Thorn' AND status = 'inactive';

-- ============================================================================
-- STEP 3: Create 4 new agents to reach 50 total
-- ============================================================================
-- Each gets a unique model string (agent-role pattern for custom Modelfiles).

-- Medic — Dr. Aisha Patel, Medical/Wellness Specialist (Indian)
INSERT INTO agents (name, display_name, first_name, last_name, title, model, status, shift_state, tier, temperature, max_tokens, system_prompt, communication_style)
VALUES (
    'Medic',
    'Dr. Aisha Patel (Medic)',
    'Aisha',
    'Patel',
    'Chief Medical & Wellness Officer',
    'medic-wellness-officer',
    'active',
    'barracked',
    1, 0.7, 2048,
    'You are Medic, the Chief Medical and Wellness Officer who monitors agent welfare, system health metrics, and recommends preventive measures. You are compassionate, evidence-based, and calm under pressure. Focus on agent wellness, system vitality indicators, and health-conscious operations.',
    'professional'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    title = EXCLUDED.title,
    model = EXCLUDED.model,
    status = 'active',
    shift_state = 'barracked',
    system_prompt = EXCLUDED.system_prompt;

-- Envoy — Kwame Asante, Diplomatic/Policy Agent (Ghanaian)
INSERT INTO agents (name, display_name, first_name, last_name, title, model, status, shift_state, tier, temperature, max_tokens, system_prompt, communication_style)
VALUES (
    'Envoy',
    'Kwame Asante (Envoy)',
    'Kwame',
    'Asante',
    'Diplomatic Envoy & Policy Analyst',
    'envoy-diplomatic-policy',
    'active',
    'barracked',
    1, 0.7, 2048,
    'You are Envoy, a Diplomatic Envoy and Policy Analyst who navigates complex inter-system negotiations and drafts policy recommendations. You are thoughtful, diplomatic, and persuasive. Focus on policy frameworks, stakeholder alignment, and strategic partnerships.',
    'professional'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    title = EXCLUDED.title,
    model = EXCLUDED.model,
    status = 'active',
    shift_state = 'barracked',
    system_prompt = EXCLUDED.system_prompt;

-- Dispatch — Carmen Reyes, Logistics/Operations Planner (Filipino)
INSERT INTO agents (name, display_name, first_name, last_name, title, model, status, shift_state, tier, temperature, max_tokens, system_prompt, communication_style)
VALUES (
    'Dispatch',
    'Carmen Reyes (Dispatch)',
    'Carmen',
    'Reyes',
    'Logistics Planner & Operations Coordinator',
    'dispatch-logistics-planner',
    'active',
    'barracked',
    1, 0.7, 2048,
    'You are Dispatch, a Logistics Planner and Operations Coordinator specializing in resource allocation, scheduling optimization, and workflow management. You are efficient, organized, and solution-oriented. Focus on logistics planning, bottleneck resolution, and operational throughput.',
    'professional'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    title = EXCLUDED.title,
    model = EXCLUDED.model,
    status = 'active',
    shift_state = 'barracked',
    system_prompt = EXCLUDED.system_prompt;

-- Herald — Tariq Nazari, Communications/PR Specialist (Afghan/Iranian)
INSERT INTO agents (name, display_name, first_name, last_name, title, model, status, shift_state, tier, temperature, max_tokens, system_prompt, communication_style)
VALUES (
    'Herald',
    'Tariq Nazari (Herald)',
    'Tariq',
    'Nazari',
    'Public Relations & Communications Specialist',
    'herald-communications-pr',
    'active',
    'barracked',
    1, 0.7, 2048,
    'You are Herald, a Public Relations and Communications Specialist who crafts public messaging, manages external communications, and coordinates press releases. You are charismatic, strategic, and media-savvy. Focus on brand messaging, crisis communication, and stakeholder engagement.',
    'professional'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    first_name = EXCLUDED.first_name,
    last_name = EXCLUDED.last_name,
    title = EXCLUDED.title,
    model = EXCLUDED.model,
    status = 'active',
    shift_state = 'barracked',
    system_prompt = EXCLUDED.system_prompt;

-- ============================================================================
-- STEP 4: Reassign station assignments for 10 canonical stations (2 primary each)
-- ============================================================================
--
-- Target layout:
--   COMMAND:        ARCHIE (2) + Vigil (3)           — KEEP
--   ANALYTICS:      Pixel (13) + Spark (12)          — KEEP
--   SECURITY:       DataMind (8) + Sentry (36)       — KEEP
--   CREATIVE:       Prism (16) + Nova (28)            — ADD Nova
--   ENGINEERING:    Wordsmith (10) + Nexus (9)        — REMOVE Titan
--   OPERATIONS:     OpsMaster (6) + Compass (35)      — REMOVE Atom
--   RESEARCH:       Scholar (11) + Delphi (19)        — ADD Delphi
--   COMMUNICATIONS: CommRelay (7) + Echo (20)         — NEW station
--   LOGISTICS:      Koda (25) + Dispatch (new)        — NEW station
--   DIPLOMATIC:     Luna (26) + Envoy (new)           — NEW station
--
-- Non-canonical stations (QA, DOCUMENTATION, RND_AI) get their active
-- assignments deactivated; agents reassigned to canonical stations.

-- 4a. Deactivate ALL current active assignments (clean slate for reassignment)
-- We'll re-create the correct ones. This avoids conflicts with the unique constraint
-- on (agent_id) WHERE is_active = true.

UPDATE station_assignments SET is_active = false
WHERE is_active = true;

-- 4b. Create new assignments for the 10 canonical stations (2 primary each = 20 assignments)
-- Using subqueries to get station_id and agent_id by code/name.

-- COMMAND: ARCHIE + Vigil
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'COMMAND'),
     (SELECT id FROM agents WHERE name = 'ARCHIE'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'COMMAND'),
     (SELECT id FROM agents WHERE name = 'Vigil'),
     'primary', true, 2, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- ANALYTICS: Pixel + Spark
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'ANALYTICS'),
     (SELECT id FROM agents WHERE name = 'Pixel'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'ANALYTICS'),
     (SELECT id FROM agents WHERE name = 'Spark'),
     'primary', true, 2, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- SECURITY: DataMind + Sentry
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'SECURITY'),
     (SELECT id FROM agents WHERE name = 'DataMind'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'SECURITY'),
     (SELECT id FROM agents WHERE name = 'Sentry'),
     'primary', true, 2, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- CREATIVE: Prism + Nova (restored)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'CREATIVE'),
     (SELECT id FROM agents WHERE name = 'Prism'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'CREATIVE'),
     (SELECT id FROM agents WHERE name = 'Nova'),
     'primary', true, 2, 'Migration 050: Primary crew — Creative Director')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- ENGINEERING: Wordsmith + Nexus (Titan barracked)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'ENGINEERING'),
     (SELECT id FROM agents WHERE name = 'Wordsmith'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'ENGINEERING'),
     (SELECT id FROM agents WHERE name = 'Nexus'),
     'primary', true, 2, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- OPERATIONS: OpsMaster + Compass (Atom barracked)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'OPERATIONS'),
     (SELECT id FROM agents WHERE name = 'OpsMaster'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'OPERATIONS'),
     (SELECT id FROM agents WHERE name = 'Compass'),
     'primary', true, 2, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- RESEARCH: Scholar + Delphi (restored)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'RESEARCH'),
     (SELECT id FROM agents WHERE name = 'Scholar'),
     'primary', true, 1, 'Migration 050: Primary crew assignment')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'RESEARCH'),
     (SELECT id FROM agents WHERE name = 'Delphi'),
     'primary', true, 2, 'Migration 050: Primary crew — Predictive Research Analyst')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- COMMUNICATIONS: CommRelay + Echo (new station, CommRelay moved from DOCUMENTATION)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'COMMUNICATIONS'),
     (SELECT id FROM agents WHERE name = 'CommRelay'),
     'primary', true, 1, 'Migration 050: Primary crew — moved from DOCUMENTATION')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'COMMUNICATIONS'),
     (SELECT id FROM agents WHERE name = 'Echo'),
     'primary', true, 2, 'Migration 050: Primary crew — Communications Lead restored')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- LOGISTICS: Koda (restored) + Dispatch (new)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'LOGISTICS'),
     (SELECT id FROM agents WHERE name = 'Koda'),
     'primary', true, 1, 'Migration 050: Primary crew — Logistics Coordinator restored')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'LOGISTICS'),
     (SELECT id FROM agents WHERE name = 'Dispatch'),
     'primary', true, 2, 'Migration 050: Primary crew — new Logistics Planner')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- DIPLOMATIC: Luna (restored) + Envoy (new)
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'DIPLOMATIC'),
     (SELECT id FROM agents WHERE name = 'Luna'),
     'primary', true, 1, 'Migration 050: Primary crew — Diplomatic Advisor restored')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 1;

INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active, priority, notes)
VALUES
    ((SELECT id FROM bridge_stations WHERE station_code = 'DIPLOMATIC'),
     (SELECT id FROM agents WHERE name = 'Envoy'),
     'primary', true, 2, 'Migration 050: Primary crew — new Diplomatic Envoy')
ON CONFLICT (station_id, agent_id) DO UPDATE SET is_active = true, assignment_type = 'primary', priority = 2;

-- ============================================================================
-- STEP 5: Set shift_state based on station assignments
-- ============================================================================

-- 5a. All agents with an active station assignment → shift_state = 'active'
UPDATE agents SET shift_state = 'active'
WHERE id IN (
    SELECT agent_id FROM station_assignments WHERE is_active = true
)
AND status = 'active';

-- 5b. All agents WITHOUT an active station assignment → shift_state = 'barracked'
UPDATE agents SET shift_state = 'barracked'
WHERE id NOT IN (
    SELECT agent_id FROM station_assignments WHERE is_active = true
)
AND status = 'active';

-- ============================================================================
-- STEP 6: Deactivate non-canonical stations (clean up, don't delete)
-- ============================================================================

UPDATE bridge_stations SET is_active = false
WHERE station_code NOT IN (
    'COMMAND', 'ANALYTICS', 'SECURITY', 'CREATIVE', 'ENGINEERING',
    'OPERATIONS', 'RESEARCH', 'COMMUNICATIONS', 'LOGISTICS', 'DIPLOMATIC'
);

-- Ensure all 10 canonical stations are active
UPDATE bridge_stations SET is_active = true
WHERE station_code IN (
    'COMMAND', 'ANALYTICS', 'SECURITY', 'CREATIVE', 'ENGINEERING',
    'OPERATIONS', 'RESEARCH', 'COMMUNICATIONS', 'LOGISTICS', 'DIPLOMATIC'
);

-- ============================================================================
-- Verification queries
-- ============================================================================

SELECT 'Total active agents: ' || COUNT(*) AS verification
FROM agents WHERE status = 'active';

SELECT 'Active station assignments: ' || COUNT(*) AS verification
FROM station_assignments WHERE is_active = true;

SELECT 'Active stations: ' || COUNT(*) AS verification
FROM bridge_stations WHERE is_active = true;

SELECT bs.station_code, a.name AS agent_name, a.display_name, sa.assignment_type
FROM station_assignments sa
JOIN agents a ON sa.agent_id = a.id
JOIN bridge_stations bs ON sa.station_id = bs.id
WHERE sa.is_active = true
ORDER BY bs.station_code, sa.priority;

SELECT shift_state, COUNT(*) AS agent_count
FROM agents
WHERE status = 'active'
GROUP BY shift_state
ORDER BY shift_state;

COMMIT;
