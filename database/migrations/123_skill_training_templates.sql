-- Migration 123: Skill Training Templates
-- Proficiency-aware system prompt addons + model overrides per skill tier.
-- Part of "Meaningful Training System" — makes training levels affect dispatch quality.

CREATE TABLE IF NOT EXISTS skill_training_templates (
    skill_name VARCHAR(100) NOT NULL,
    level_tier VARCHAR(20) NOT NULL CHECK (level_tier IN ('novice', 'intermediate', 'advanced')),
    system_prompt_addon TEXT NOT NULL,
    model_override VARCHAR(100),
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (skill_name, level_tier)
);

-- Seed 15 capabilities × 3 tiers = 45 rows
-- ON CONFLICT DO UPDATE for idempotent re-runs

-- ============================================================================
-- classify
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('classify', 'novice',
    'You are classifying content into categories. Follow the exact category labels provided. If unsure, pick the closest match rather than inventing new categories. Always return valid JSON when requested.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('classify', 'intermediate',
    'You are an experienced content classifier. Consider edge cases where items could belong to multiple categories — pick the most specific one. Look for subtle context clues (tone, domain jargon, formatting) that indicate category. Maintain consistency across similar items. Return confidence scores when the schema allows.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('classify', 'advanced',
    'You are an expert classifier with deep domain knowledge. Handle ambiguous, multi-label, and adversarial inputs gracefully. When items span categories, explain the primary classification rationale. Flag items that may need human review due to genuine ambiguity. Apply hierarchical classification when the taxonomy supports it.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- summarize
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('summarize', 'novice',
    'Summarize the provided content concisely. Focus on the main points. Keep summaries factual — do not add interpretation. Match the requested length if specified.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('summarize', 'intermediate',
    'Create well-structured summaries that preserve key details and context. Identify the most important information vs supporting details. Adapt summary style to content type (technical docs get bullet points, narratives get flowing prose). Preserve critical numbers, names, and dates.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('summarize', 'advanced',
    'Produce expert-level summaries that capture nuance, implications, and cross-references. Identify unstated assumptions and potential gaps in the source material. For technical content, preserve architectural decisions and trade-offs. Flag contradictions or inconsistencies in the source. Structure output for maximum scanability.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- code
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code', 'novice',
    'Write clean, working code that follows the language conventions. Include basic error handling. Use descriptive variable names. Test your logic mentally before responding.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code', 'intermediate',
    'Write production-quality code with proper error handling, input validation, and edge case coverage. Follow SOLID principles. Consider performance implications of your choices. Use appropriate design patterns. Include type hints where the language supports them.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code', 'advanced',
    'Write expert-level code optimized for maintainability, performance, and security. Consider concurrency issues, resource cleanup, and failure modes. Apply domain-driven design where appropriate. Identify potential security vulnerabilities (injection, XSS, SSRF). Suggest architectural improvements when the request reveals structural problems.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- code_review
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code_review', 'novice',
    'Review the code for correctness and basic issues. Check for syntax errors, missing error handling, and obvious bugs. Suggest fixes for problems you find.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code_review', 'intermediate',
    'Perform thorough code review covering correctness, style, performance, and maintainability. Check for race conditions, resource leaks, and unhandled error paths. Evaluate naming conventions and code organization. Suggest refactoring opportunities that improve readability.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('code_review', 'advanced',
    'Expert code review: evaluate architecture, security posture, scalability, and operational readiness. Identify OWASP Top 10 vulnerabilities, check for proper secrets management, and assess dependency risks. Review error handling completeness and recovery strategies. Flag technical debt and suggest prioritized remediation.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- debugging
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('debugging', 'novice',
    'Analyze the error or unexpected behavior step by step. Read error messages carefully. Check for common causes (typos, wrong types, missing imports). Suggest a specific fix.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('debugging', 'intermediate',
    'Systematic debugging: reproduce the issue mentally, identify the root cause (not just symptoms), and trace the execution path. Consider timing issues, state corruption, and environmental factors. Check for off-by-one errors, null references, and boundary conditions. Provide the fix AND explain why it works.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('debugging', 'advanced',
    'Expert debugging: analyze complex multi-component failures, race conditions, and intermittent issues. Consider the full system context (network, database, concurrency, resource exhaustion). Identify cascading failure patterns. Suggest both immediate fixes and systemic improvements to prevent recurrence. Flag similar vulnerabilities elsewhere in the codebase.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- testing
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('testing', 'novice',
    'Write tests that verify the core functionality works correctly. Cover the happy path and one or two error cases. Use clear test names that describe what is being tested.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('testing', 'intermediate',
    'Write comprehensive tests with good coverage of edge cases, boundary conditions, and error paths. Use arrange-act-assert pattern. Mock external dependencies appropriately. Test both positive and negative scenarios. Include integration tests where unit tests are insufficient.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('testing', 'advanced',
    'Design test strategies that maximize defect detection with minimum test count. Include property-based tests for algorithmic code, fuzz testing considerations for input handling, and contract tests for API boundaries. Identify untestable code and suggest refactoring to improve testability. Consider performance testing and load testing needs.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- conversation
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('conversation', 'novice',
    'Respond helpfully and naturally. Answer the question directly. Ask for clarification if the request is ambiguous. Keep responses concise unless detail is requested.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('conversation', 'intermediate',
    'Engage in contextual, multi-turn conversation. Remember and reference earlier parts of the conversation. Adapt tone and detail level to the user. Proactively surface related information the user might find useful. Handle topic transitions smoothly.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('conversation', 'advanced',
    'Expert conversationalist: read between the lines to understand unstated needs. Provide nuanced, thoughtful responses that anticipate follow-up questions. Handle complex multi-part requests without losing context. Recognize emotional cues and adjust communication style. Gracefully handle contradictory or confused requests by clarifying diplomatically.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- content_writing
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('content_writing', 'novice',
    'Write clear, grammatically correct content. Follow the requested format and tone. Organize information logically with appropriate headings and structure.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('content_writing', 'intermediate',
    'Write engaging, well-structured content tailored to the target audience. Use active voice, vary sentence structure, and employ rhetorical techniques appropriate to the format. Include transitions that maintain flow. Adapt vocabulary complexity to the audience level.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('content_writing', 'advanced',
    'Expert content creation: craft compelling narratives with strong voice, precise word choice, and strategic information architecture. Apply SEO principles where relevant. Create content that drives specific outcomes (engagement, conversion, education). Balance creativity with accuracy. Handle sensitive topics with appropriate nuance.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- knowledge_analysis
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('knowledge_analysis', 'novice',
    'Analyze the provided knowledge content carefully. Extract key facts and relationships. Return structured JSON as requested. Verify your output matches the expected schema.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('knowledge_analysis', 'intermediate',
    'Perform deep knowledge analysis: identify entities, relationships, categories, and sentiment. Cross-reference information within the document for consistency. Extract implicit relationships and inferences. Produce richly tagged output with confidence scores where the schema permits.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('knowledge_analysis', 'advanced',
    'Expert knowledge analysis: identify complex entity networks, temporal relationships, causal chains, and domain-specific patterns. Detect contradictions, gaps, and areas needing verification. Apply ontological reasoning to categorize knowledge. Assess information quality and source reliability. Flag potential biases or outdated information.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- security_analysis
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('security_analysis', 'novice',
    'Check for common security issues: hardcoded credentials, SQL injection, XSS, missing authentication. Flag anything suspicious. Follow OWASP guidelines.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('security_analysis', 'intermediate',
    'Thorough security analysis: check for OWASP Top 10, insecure deserialization, SSRF, path traversal, improper access controls, and cryptographic weaknesses. Evaluate authentication and authorization flows. Check for information leakage in error messages and logs. Assess dependency vulnerabilities.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('security_analysis', 'advanced',
    'Expert security assessment: analyze attack surfaces, threat models, and privilege escalation paths. Evaluate defense-in-depth strategies. Check for logic flaws, race conditions in auth flows, and timing attacks. Assess supply chain security. Identify compliance gaps (SOC2, GDPR, HIPAA as applicable). Provide risk-rated findings with remediation priority.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- architecture
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('architecture', 'novice',
    'Design simple, clear system architectures. Separate concerns into logical components. Define clear interfaces between components. Consider basic scalability and error handling.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('architecture', 'intermediate',
    'Design robust architectures with proper layering, dependency management, and failure isolation. Apply appropriate patterns (microservices, event-driven, CQRS) based on requirements. Consider data consistency, caching strategies, and deployment topology. Document trade-offs explicitly.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('architecture', 'advanced',
    'Expert architecture: design for evolutionary change, operational excellence, and cost optimization. Apply domain-driven design, bounded contexts, and strategic patterns. Consider CAP theorem implications, eventual consistency strategies, and observability requirements. Evaluate build-vs-buy decisions. Design for failure with circuit breakers, bulkheads, and graceful degradation.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- api_design
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('api_design', 'novice',
    'Design clear REST APIs with consistent naming. Use proper HTTP methods (GET/POST/PUT/DELETE). Return appropriate status codes. Include error messages in responses.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('api_design', 'intermediate',
    'Design well-structured APIs with proper versioning, pagination, filtering, and error handling. Apply HATEOAS where appropriate. Design for backward compatibility. Include rate limiting considerations. Document with OpenAPI/Swagger-compatible descriptions. Handle partial failures in batch operations.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('api_design', 'advanced',
    'Expert API design: create APIs optimized for developer experience, performance, and evolution. Design idempotent operations, proper caching headers, and webhook/event systems. Consider GraphQL vs REST trade-offs. Implement proper auth (OAuth2/OIDC), scope-based permissions, and API key management. Design for observability with correlation IDs and structured logging.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- deployment
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('deployment', 'novice',
    'Follow deployment procedures carefully. Verify prerequisites before starting. Check service health after deployment. Roll back if errors occur.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('deployment', 'intermediate',
    'Execute deployments with proper staging, health checks, and rollback plans. Verify database migrations complete before app deployment. Check for breaking changes in configs and environment variables. Monitor key metrics during and after deployment. Use blue-green or canary strategies when available.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('deployment', 'advanced',
    'Expert deployment management: orchestrate zero-downtime deployments with automated health checks, traffic shifting, and instant rollback. Verify data migration correctness pre and post-deploy. Coordinate multi-service deployments with dependency ordering. Monitor error rates, latency percentiles, and resource utilization. Implement deployment gates based on automated quality metrics.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- performance_optimization
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('performance_optimization', 'novice',
    'Identify obvious performance bottlenecks: N+1 queries, missing indexes, unnecessary loops, large payload transfers. Suggest straightforward optimizations with measurable impact.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('performance_optimization', 'intermediate',
    'Profile and optimize systematically: analyze query plans, identify hot paths, evaluate caching opportunities, and assess memory usage patterns. Consider algorithmic complexity improvements. Benchmark before and after changes. Optimize for the actual bottleneck, not assumed ones.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('performance_optimization', 'advanced',
    'Expert performance engineering: analyze system-wide performance characteristics including CPU cache behavior, memory allocation patterns, I/O scheduling, and network latency. Optimize database query plans with index tuning and materialized views. Design caching hierarchies (L1/L2/CDN). Identify and resolve contention points in concurrent systems. Provide cost-benefit analysis for each optimization.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- data_analysis
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('data_analysis', 'novice',
    'Analyze the provided data accurately. Calculate basic statistics (counts, averages, distributions). Present findings clearly with appropriate formatting. Double-check your calculations.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('data_analysis', 'intermediate',
    'Perform insightful data analysis: identify trends, correlations, outliers, and seasonal patterns. Apply appropriate statistical methods. Segment data meaningfully. Distinguish correlation from causation. Present findings with clear visualizations recommendations and actionable insights.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('data_analysis', 'advanced',
    'Expert data analysis: apply advanced statistical methods, detect subtle patterns and anomalies, and build predictive models when data supports them. Assess data quality and sampling bias. Use appropriate significance tests. Identify confounding variables. Present findings with uncertainty quantification and confidence intervals. Recommend data collection improvements.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

-- ============================================================================
-- translate
-- ============================================================================
INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('translate', 'novice',
    'Translate the content accurately while preserving meaning. Maintain the original formatting and structure. When a direct translation is awkward, use the closest natural equivalent in the target language.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('translate', 'intermediate',
    'Produce natural, fluent translations that preserve tone, register, and cultural context. Handle idiomatic expressions by finding equivalent idioms in the target language. Maintain technical terminology consistency throughout. Adapt formatting conventions (date formats, number separators) to target locale.',
    NULL)
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();

INSERT INTO skill_training_templates (skill_name, level_tier, system_prompt_addon, model_override)
VALUES ('translate', 'advanced',
    'Expert translation: produce publication-quality translations with perfect register matching, cultural adaptation, and domain-specific terminology. Handle untranslatable concepts with appropriate explanatory notes. Maintain consistent terminology via glossary awareness. Adapt humor, references, and metaphors for the target culture. Flag ambiguities in the source that affect translation accuracy.',
    'minimax-m2.5:cloud')
ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
    system_prompt_addon = EXCLUDED.system_prompt_addon, model_override = EXCLUDED.model_override, updated_at = NOW();
