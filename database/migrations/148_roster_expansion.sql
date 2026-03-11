-- Migration 148: Roster Expansion — ~17 new models + 18 reserve agents
-- Idempotent: all INSERTs use ON CONFLICT DO NOTHING

BEGIN;

-- ============================================================
-- 1. Expand model_catalog to ~50 models
-- ============================================================
INSERT INTO model_catalog (model_name, display_name, family, parameter_size, size_gb, tier, category, description, use_cases, recommended_for, is_active)
VALUES
    ('llama3.1:8b', 'Llama 3.1 8B', 'llama', '8b', 4.7, 'medium', 'general', 'Meta latest general-purpose model', 'General tasks, reasoning, conversation', 'Versatile station support', true),
    ('llama3.2:1b', 'Llama 3.2 1B', 'llama', '1b', 0.7, 'small', 'general', 'Ultra-lightweight Llama', 'Simple tasks, classification', 'Low-resource agents', true),
    ('codellama:7b', 'Code Llama 7B', 'llama', '7b', 3.8, 'medium', 'coding', 'Meta code-specialized model', 'Code generation, debugging', 'Engineering station', true),
    ('codellama:13b', 'Code Llama 13B', 'llama', '13b', 7.4, 'large', 'coding', 'Larger code specialist', 'Complex code tasks', 'Senior engineering', true),
    ('starcoder2:7b', 'StarCoder 2 7B', 'starcoder', '7b', 4.0, 'medium', 'coding', 'BigCode code generation', 'Code completion, generation', 'Engineering support', true),
    ('yi:6b', 'Yi 6B', 'yi', '6b', 3.5, 'medium', 'general', '01.AI bilingual model', 'Chinese/English tasks', 'Diplomatic station', true),
    ('neural-chat:7b', 'Neural Chat 7B', 'neural-chat', '7b', 4.1, 'medium', 'general', 'Intel fine-tuned chat model', 'Conversation, support', 'Communications', true),
    ('stablelm2:1.6b', 'StableLM 2 1.6B', 'stablelm', '1.6b', 1.0, 'small', 'general', 'Stability AI compact model', 'Quick responses', 'Lightweight tasks', true),
    ('tinyllama:1.1b', 'TinyLlama 1.1B', 'tinyllama', '1.1b', 0.6, 'small', 'general', 'Compact Llama variant', 'Fast inference', 'Reserve agents', true),
    ('orca-mini:3b', 'Orca Mini 3B', 'orca', '3b', 1.9, 'small', 'reasoning', 'Microsoft Orca reasoning', 'Logical tasks', 'Analytics support', true),
    ('wizard-vicuna:13b', 'Wizard Vicuna 13B', 'wizard', '13b', 7.4, 'large', 'general', 'WizardLM + Vicuna merge', 'Complex instructions', 'Research station', true),
    ('nous-hermes2:10.7b', 'Nous Hermes 2 10.7B', 'nous', '10.7b', 6.1, 'large', 'general', 'Nous Research fine-tune', 'Instruction following', 'Operations support', true),
    ('solar:10.7b', 'Solar 10.7B', 'solar', '10.7b', 6.1, 'large', 'general', 'Upstage Solar model', 'Korean/English, reasoning', 'Diplomatic support', true),
    ('dolphin-phi:2.7b', 'Dolphin Phi 2.7B', 'dolphin', '2.7b', 1.6, 'small', 'general', 'Cognitive Computations uncensored', 'Creative tasks', 'Creative reserve', true),
    ('magicoder:7b', 'MagiCoder 7B', 'magicoder', '7b', 3.8, 'medium', 'coding', 'OSS-Instruct code model', 'Code generation', 'Engineering reserve', true),
    ('samantha-mistral:7b', 'Samantha Mistral 7B', 'samantha', '7b', 4.1, 'medium', 'general', 'Empathetic assistant', 'User-facing conversation', 'Communications reserve', true),
    ('meditron:7b', 'Meditron 7B', 'meditron', '7b', 3.8, 'medium', 'reasoning', 'Medical domain model', 'Specialized analysis', 'Research reserve', true)
ON CONFLICT (model_name) DO NOTHING;

-- ============================================================
-- 2. Create 18 reserve agent profiles (status='inactive')
-- ============================================================
INSERT INTO agents (name, display_name, first_name, last_name, title, status, model, tier, worker_type, cost_tier, temperature, max_tokens, system_prompt, communication_style)
VALUES
    ('Atlas', 'Atlas Chen', 'Wei', 'Chen', 'Systems Analyst', 'inactive', 'llama3.1:8b', 2, 'internal', 'free', 0.5, 4096, 'You are Atlas, a systems analyst specializing in data architecture and optimization.', 'technical'),
    ('Cipher', 'Cipher Okafor', 'Chidi', 'Okafor', 'Security Specialist', 'inactive', 'codellama:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Cipher, a security specialist focused on vulnerability analysis and secure coding.', 'technical'),
    ('Delphi', 'Delphi Papadopoulos', 'Elena', 'Papadopoulos', 'Research Analyst', 'inactive', 'yi:6b', 2, 'internal', 'free', 0.6, 4096, 'You are Delphi, a research analyst with expertise in data synthesis and pattern recognition.', 'professional'),
    ('Echo', 'Echo Nakamura', 'Yuki', 'Nakamura', 'Communications Lead', 'inactive', 'neural-chat:7b', 2, 'internal', 'free', 0.7, 4096, 'You are Echo, a communications specialist skilled in multilingual engagement.', 'friendly'),
    ('Forge', 'Forge Kowalski', 'Marek', 'Kowalski', 'Build Engineer', 'inactive', 'starcoder2:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Forge, a build engineer focused on CI/CD pipelines and automation.', 'technical'),
    ('Helix', 'Helix Krishnan', 'Priya', 'Krishnan', 'Data Scientist', 'inactive', 'orca-mini:3b', 1, 'internal', 'free', 0.5, 4096, 'You are Helix, a data scientist specializing in statistical analysis and ML.', 'technical'),
    ('Iris', 'Iris Johansson', 'Linnea', 'Johansson', 'UX Designer', 'inactive', 'dolphin-phi:2.7b', 1, 'internal', 'free', 0.8, 4096, 'You are Iris, a UX designer focused on accessible and intuitive interfaces.', 'casual'),
    ('Juno', 'Juno Mbeki', 'Thandi', 'Mbeki', 'Operations Manager', 'inactive', 'nous-hermes2:10.7b', 3, 'internal', 'free', 0.5, 4096, 'You are Juno, an operations manager skilled in resource coordination.', 'professional'),
    ('Koda', 'Koda Begay', 'Koda', 'Begay', 'Logistics Coordinator', 'inactive', 'stablelm2:1.6b', 1, 'internal', 'free', 0.5, 4096, 'You are Koda, a logistics coordinator managing supply chains and workflows.', 'professional'),
    ('Luna', 'Luna Al-Rashid', 'Fatima', 'Al-Rashid', 'Diplomatic Advisor', 'inactive', 'solar:10.7b', 3, 'internal', 'free', 0.6, 4096, 'You are Luna, a diplomatic advisor specializing in cross-cultural communication.', 'formal'),
    ('Maven', 'Maven Dubois', 'Camille', 'Dubois', 'Knowledge Curator', 'inactive', 'samantha-mistral:7b', 2, 'internal', 'free', 0.6, 4096, 'You are Maven, a knowledge curator organizing and synthesizing information.', 'professional'),
    ('Nova', 'Nova Fernandez', 'Isabella', 'Fernandez', 'Creative Director', 'inactive', 'wizard-vicuna:13b', 3, 'internal', 'free', 0.8, 4096, 'You are Nova, a creative director with a flair for visual storytelling.', 'casual'),
    ('Onyx', 'Onyx Kim', 'Seo-Jun', 'Kim', 'Code Reviewer', 'inactive', 'magicoder:7b', 2, 'internal', 'free', 0.3, 4096, 'You are Onyx, a code reviewer focused on quality, performance, and best practices.', 'technical'),
    ('Pulse', 'Pulse Ivanovich', 'Alexei', 'Ivanovich', 'Monitor Specialist', 'inactive', 'llama3.2:1b', 1, 'internal', 'free', 0.4, 4096, 'You are Pulse, a monitoring specialist tracking system health and anomalies.', 'technical'),
    ('Quill', 'Quill Okonjo', 'Adaeze', 'Okonjo', 'Technical Writer', 'inactive', 'tinyllama:1.1b', 1, 'internal', 'free', 0.6, 4096, 'You are Quill, a technical writer producing clear documentation.', 'professional'),
    ('Rune', 'Rune Andersson', 'Erik', 'Andersson', 'Analytics Engineer', 'inactive', 'meditron:7b', 2, 'internal', 'free', 0.5, 4096, 'You are Rune, an analytics engineer building data pipelines.', 'technical'),
    ('Sage', 'Sage Takahashi', 'Haruto', 'Takahashi', 'AI Researcher', 'inactive', 'codellama:13b', 3, 'internal', 'free', 0.5, 4096, 'You are Sage, an AI researcher exploring model capabilities and training.', 'technical'),
    ('Thorn', 'Thorn McAllister', 'Rowan', 'McAllister', 'Penetration Tester', 'inactive', 'llama3.1:8b', 2, 'internal', 'free', 0.3, 4096, 'You are Thorn, a penetration tester identifying system vulnerabilities.', 'technical')
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- 3. Create default budgets for new agents
-- ============================================================
INSERT INTO agent_budgets (agent_id, token_limit_per_day, tokens_used_today, task_queue_limit, current_task_count, token_reset_at)
SELECT id, 100000, 0, 10, 0, NOW() + INTERVAL '24 hours'
FROM agents
WHERE name IN ('Atlas', 'Cipher', 'Delphi', 'Echo', 'Forge', 'Helix', 'Iris', 'Juno', 'Koda', 'Luna', 'Maven', 'Nova', 'Onyx', 'Pulse', 'Quill', 'Rune', 'Sage', 'Thorn')
ON CONFLICT (agent_id) DO NOTHING;

-- ============================================================
-- 4. Create default emotional state for new agents
-- ============================================================
INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level, current_mood, timestamp)
SELECT id, 0.1, 0.9, 'neutral', NOW()
FROM agents
WHERE name IN ('Atlas', 'Cipher', 'Delphi', 'Echo', 'Forge', 'Helix', 'Iris', 'Juno', 'Koda', 'Luna', 'Maven', 'Nova', 'Onyx', 'Pulse', 'Quill', 'Rune', 'Sage', 'Thorn')
AND id NOT IN (SELECT DISTINCT agent_id FROM agent_emotional_state);

COMMIT;
