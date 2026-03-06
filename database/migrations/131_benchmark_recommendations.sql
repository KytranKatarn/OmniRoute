-- Migration 131: Station Actions for All Stations + Benchmark Recommendations
-- Seeds test actions for 8 missing stations and creates the recommendations table.
-- Part of Project #110: Agent Action Benchmarks — Recommendation Engine.

-- ============================================================
-- 1. Seed test actions for 8 missing stations
-- ============================================================

-- COMMAND (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('command.orchestrate', 'COMMAND', 'bridge', 'ORCHESTRATE', 'Prioritize competing tasks', 'layers', 'gold', 10, 'POST', '/tools/bridge/api/orchestrate', '[]'::jsonb, FALSE, NULL,
     '{"capability":"planning","prompt":"You have three competing priorities: (1) A production bug affecting 10% of users, (2) A security patch due tomorrow, (3) A feature demo for a client in 2 hours. Rank these by urgency and explain your reasoning in 3 sentences.","system_prompt":"You are an operations commander. Prioritize tasks concisely with clear rationale.","description":"Prioritize competing tasks"}'::jsonb),
    ('command.briefing', 'COMMAND', 'bridge', 'BRIEFING', 'Generate daily ops briefing', 'clipboard', 'gold', 20, 'POST', '/tools/bridge/api/briefing', '[]'::jsonb, FALSE, NULL,
     '{"capability":"summarize","prompt":"Raw data: 47 API calls (3 failed), 12 deployments (1 rolled back), 8 knowledge entries added, 2 agents idle for >4h, disk usage at 78%. Generate a concise daily operations briefing with status indicators.","system_prompt":"You are an operations briefing officer. Summarize raw metrics into a clear, actionable briefing. Use status indicators (OK/WARN/CRIT).","description":"Generate daily ops briefing from raw data"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- CREATIVE (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('creative.content_write', 'CREATIVE', 'bridge', 'WRITE', 'Write content from bullet points', 'pen', 'pink', 10, 'POST', '/tools/bridge/api/creative/write', '[]'::jsonb, FALSE, NULL,
     '{"capability":"writing","prompt":"Bullet points: - New release v5.32 shipped - 3 major features: benchmark system, station actions, skill sync - Performance improved 40% - Available now. Write an engaging social media announcement post (under 280 characters).","system_prompt":"You are a creative content writer. Write engaging, concise social media posts. Match the platform tone.","description":"Write social media post from bullet points"}'::jsonb),
    ('creative.content_review', 'CREATIVE', 'bridge', 'REVIEW', 'Review marketing copy', 'eye', 'pink', 20, 'POST', '/tools/bridge/api/creative/review', '[]'::jsonb, FALSE, NULL,
     '{"capability":"code_review","prompt":"Review this marketing copy for tone, clarity, and effectiveness:\n\n\"Our platform is very good and does many things. It has AI and databases and is fast. You should use it because it is better than others.\"\n\nProvide specific improvement suggestions.","system_prompt":"You are a content editor. Review copy for tone, clarity, grammar, and persuasiveness. Be specific and constructive.","description":"Review marketing copy for tone and clarity"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- OPERATIONS (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('operations.monitor', 'OPERATIONS', 'bridge', 'CLASSIFY', 'Classify system alert severity', 'alert-triangle', 'orange', 10, 'POST', '/tools/bridge/api/operations/classify', '[]'::jsonb, FALSE, NULL,
     '{"capability":"classification","prompt":"Classify the severity of this system alert:\n\nAlert: Database connection pool exhausted. 0/20 connections available. Query queue depth: 47. Last successful query: 3 minutes ago. Affected service: user-auth.\n\nRespond with: severity (critical/high/medium/low), impact assessment, and recommended immediate action.","system_prompt":"You are a systems monitoring specialist. Classify alert severity accurately and recommend actions. Be precise and urgent when warranted.","description":"Classify system alert severity"}'::jsonb),
    ('operations.automate', 'OPERATIONS', 'bridge', 'AUTOMATE', 'Design automation workflow', 'settings', 'orange', 20, 'POST', '/tools/bridge/api/operations/automate', '[]'::jsonb, FALSE, NULL,
     '{"capability":"planning","prompt":"Design an automation workflow for this task: Every night at 2 AM, check disk usage on all servers. If any exceed 85%, archive logs older than 7 days. If still above 85%, send a Telegram alert. Describe the steps, triggers, and error handling.","system_prompt":"You are an automation engineer. Design clear, robust workflows with error handling. Use numbered steps.","description":"Design automation workflow from description"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- RESEARCH (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('research.analyze', 'RESEARCH', 'bridge', 'ANALYZE', 'Extract findings from research', 'microscope', 'blue', 10, 'POST', '/tools/bridge/api/research/analyze', '[]'::jsonb, FALSE, NULL,
     '{"capability":"research","prompt":"Extract key findings from this research abstract:\n\nWe evaluated retrieval-augmented generation (RAG) with 768-dimensional embeddings across 5,000 knowledge base entries. Cosine similarity with a threshold of 0.72 achieved 89% recall and 94% precision. Chunk sizes of 512 tokens outperformed 1024 tokens by 12% on factual accuracy. Query latency averaged 45ms with HNSW indexing.\n\nList: (1) key metrics, (2) main finding, (3) practical implication.","system_prompt":"You are a research analyst. Extract structured findings from academic and technical texts. Be precise with numbers.","description":"Extract key findings from research abstract"}'::jsonb),
    ('research.summarize', 'RESEARCH', 'bridge', 'SUMMARIZE', 'Summarize technical paper', 'book', 'blue', 20, 'POST', '/tools/bridge/api/research/summarize', '[]'::jsonb, FALSE, NULL,
     '{"capability":"summarize","prompt":"Summarize this technical paper excerpt in 3 bullet points:\n\nTransformer architectures have become the dominant paradigm in NLP. Self-attention mechanisms allow models to weigh the importance of different tokens regardless of position. However, the quadratic complexity of attention (O(n²)) limits context length. Recent work on linear attention and sparse attention patterns aims to extend context windows beyond 100K tokens while maintaining quality. Flash Attention achieves 2-4x speedup by optimizing GPU memory access patterns.","system_prompt":"You are a technical writer. Summarize complex papers into clear, accurate bullet points. Preserve key numbers and claims.","description":"Summarize technical paper excerpt"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- DOCUMENTATION (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('docs.generate', 'DOCUMENTATION', 'bridge', 'GENERATE', 'Generate API documentation', 'file-text', 'teal', 10, 'POST', '/tools/bridge/api/docs/generate', '[]'::jsonb, FALSE, NULL,
     '{"capability":"documentation","prompt":"Generate API documentation for this function:\n\ndef search_knowledge(query: str, limit: int = 10, category: str = None, include_archived: bool = False) -> List[Dict]:\n    \"\"\"Search the knowledge base using semantic similarity.\"\"\"\n\nInclude: description, parameters table, return type, example usage.","system_prompt":"You are a technical documentation writer. Generate clear, complete API docs with examples. Use markdown format.","description":"Generate API docs from function signature"}'::jsonb),
    ('docs.review', 'DOCUMENTATION', 'bridge', 'REVIEW DOCS', 'Review documentation quality', 'check-square', 'teal', 20, 'POST', '/tools/bridge/api/docs/review', '[]'::jsonb, FALSE, NULL,
     '{"capability":"code_review","prompt":"Review this API documentation for accuracy and completeness:\n\n## search_knowledge(query)\nSearches stuff in the database.\nReturns: results\n\nRate: completeness (1-5), accuracy (1-5), usability (1-5). List specific improvements needed.","system_prompt":"You are a documentation reviewer. Evaluate docs for completeness, accuracy, and developer usability. Be specific about gaps.","description":"Review documentation for accuracy and completeness"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- RND_AI (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('rnd_ai.evaluate', 'RND_AI', 'bridge', 'EVALUATE', 'Evaluate ML architecture', 'cpu', 'violet', 10, 'POST', '/tools/bridge/api/rnd/evaluate', '[]'::jsonb, FALSE, NULL,
     '{"capability":"code_analysis","prompt":"Evaluate the tradeoffs of this ML architecture decision:\n\nWe need to choose between: (A) Fine-tuning a 7B parameter model on our domain data (requires 8GB VRAM, 4h training), or (B) Using RAG with a general-purpose model + our knowledge base (no training, 45ms query latency). Our dataset has 5,000 entries growing 50/week. Evaluate: accuracy, cost, maintenance, scalability.","system_prompt":"You are an ML architect. Evaluate architecture tradeoffs with clear pros/cons. Consider practical constraints like hardware and maintenance.","description":"Evaluate ML model architecture tradeoffs"}'::jsonb),
    ('rnd_ai.prototype', 'RND_AI', 'bridge', 'PROTOTYPE', 'Suggest ML implementation', 'zap', 'violet', 20, 'POST', '/tools/bridge/api/rnd/prototype', '[]'::jsonb, FALSE, NULL,
     '{"capability":"code_analysis","prompt":"Suggest an implementation approach for this ML feature:\n\nFeature: Auto-classify incoming knowledge base entries into categories (technical, operational, research, personal) with confidence scores. Requirements: <100ms latency, works on CPU, handles 50 entries/day.\n\nSuggest: model choice, pipeline design, confidence calibration approach.","system_prompt":"You are an ML engineer. Suggest practical implementations considering hardware constraints and maintenance burden. Prefer simple, proven approaches.","description":"Suggest implementation for ML feature"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- SUPPORT (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('support.respond', 'SUPPORT', 'bridge', 'RESPOND', 'Draft support response', 'message-circle', 'green', 10, 'POST', '/tools/bridge/api/support/respond', '[]'::jsonb, FALSE, NULL,
     '{"capability":"conversation","prompt":"Draft a customer support response for this ticket:\n\nSubject: Cannot access dashboard after update\nMessage: Hi, since the latest update yesterday I get a 403 error when trying to access my dashboard. I am an admin user. Clearing cookies did not help. Please fix ASAP.\n\nDraft a professional, empathetic response with troubleshooting steps.","system_prompt":"You are a customer support specialist. Write professional, empathetic responses with clear troubleshooting steps. Acknowledge the issue first, then provide actionable solutions.","description":"Draft customer support response"}'::jsonb),
    ('support.classify', 'SUPPORT', 'bridge', 'CLASSIFY', 'Classify support ticket', 'tag', 'green', 20, 'POST', '/tools/bridge/api/support/classify', '[]'::jsonb, FALSE, NULL,
     '{"capability":"classification","prompt":"Classify this support ticket:\n\nSubject: Slow performance on reports page\nMessage: The reports page takes 30+ seconds to load when filtering by date range > 90 days. Other pages are fine. Started after last Thursday deploy.\n\nClassify: priority (P1-P4), category (bug/feature/question/incident), component (frontend/backend/database/infrastructure), estimated complexity (low/medium/high).","system_prompt":"You are a support triage specialist. Classify tickets accurately using structured categories. Consider business impact for priority.","description":"Classify support ticket priority and category"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- QA (2 actions)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type, test_config)
VALUES
    ('qa.test_generate', 'QA', 'bridge', 'GEN TESTS', 'Generate test cases', 'check-circle', 'lime', 10, 'POST', '/tools/bridge/api/qa/tests', '[]'::jsonb, FALSE, NULL,
     '{"capability":"testing","prompt":"Generate test cases for this function:\n\ndef calculate_score(success: bool, duration_ms: int, total_tokens: int, max_duration: int, max_tokens: int) -> float:\n    if not success:\n        return 0.0\n    speed_norm = 1.0 - (duration_ms / max_duration)\n    token_norm = 1.0 - (total_tokens / max_tokens)\n    return round(40.0 + (speed_norm * 30.0) + (token_norm * 30.0), 1)\n\nWrite 5 test cases covering: normal, edge cases, failures.","system_prompt":"You are a QA engineer. Write clear, focused test cases with expected values. Cover happy path, edge cases, and error conditions.","description":"Generate test cases for a function"}'::jsonb),
    ('qa.bug_analyze', 'QA', 'bridge', 'ANALYZE BUG', 'Analyze error log', 'bug', 'lime', 20, 'POST', '/tools/bridge/api/qa/analyze', '[]'::jsonb, FALSE, NULL,
     '{"capability":"debugging","prompt":"Analyze this error log and identify the root cause:\n\n[2024-03-15 14:23:01] ERROR psycopg2.pool.PoolError: connection pool exhausted\n[2024-03-15 14:23:01] WARNING 47 queries queued, 0/20 connections available\n[2024-03-15 14:22:45] DEBUG Long-running query: SELECT * FROM knowledge_base WHERE embedding IS NOT NULL (running 18s)\n[2024-03-15 14:20:00] INFO Benchmark run started: 8 agents, concurrent mode\n\nIdentify: root cause, contributing factors, fix recommendation.","system_prompt":"You are a debugging specialist. Analyze error logs systematically: identify root cause, contributing factors, and actionable fix. Be specific about what caused what.","description":"Analyze error log and identify root cause"}'::jsonb)
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code, module_source = EXCLUDED.module_source,
    label = EXCLUDED.label, description = EXCLUDED.description, icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class, sort_order = EXCLUDED.sort_order,
    test_config = EXCLUDED.test_config, updated_at = NOW();

-- ============================================================
-- 2. Benchmark Recommendations table
-- ============================================================

CREATE TABLE IF NOT EXISTS benchmark_recommendations (
    id SERIAL PRIMARY KEY,
    station_code VARCHAR(20) NOT NULL,
    recommended_agent_id INT REFERENCES agents(id),
    recommended_agent_name VARCHAR(100) NOT NULL,
    current_agent_id INT REFERENCES agents(id),
    current_agent_name VARCHAR(100),
    avg_score REAL NOT NULL,
    score_delta REAL DEFAULT 0,
    top_3 JSONB NOT NULL DEFAULT '[]',
    human_pick_agent VARCHAR(100),
    action_keys_tested JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by INT
);

CREATE INDEX IF NOT EXISTS idx_bench_rec_station
    ON benchmark_recommendations(station_code, status, generated_at DESC);

-- ============================================================
-- 3. Ensure all needed capability_skill_map entries exist
-- ============================================================

INSERT INTO capability_skill_map (capability, skill_name) VALUES
    ('planning', 'planning'),
    ('writing', 'content_creation'),
    ('conversation', 'conversation'),
    ('classification', 'classification'),
    ('debugging', 'debugging'),
    ('testing', 'testing'),
    ('documentation', 'documentation'),
    ('research', 'research')
ON CONFLICT (capability) DO NOTHING;
