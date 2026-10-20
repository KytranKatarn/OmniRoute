-- DS9 Criterion 4 — Phase 5c: Recreate views with engineer naming

-- v_engineer_approval_queue
CREATE OR REPLACE VIEW v_engineer_approval_queue AS
 SELECT car.id,
    car.status,
    car.priority,
    car.task_type,
    car.task_description,
    car.module_source,
    car.estimated_cost,
    car.engineer_model,
    car.engineer_provider,
    car.created_at,
    car.expires_at,
    (car.expires_at < now()) AS is_expired,
    a.id AS agent_id,
    a.name AS agent_name,
    a.first_name,
    a.last_name,
    a.department,
    u.username AS requested_by_username
   FROM ((engineer_approval_requests car
     JOIN agents a ON ((car.agent_id = a.id)))
     LEFT JOIN users u ON ((car.requested_by = u.id)))
  WHERE ((car.status)::text = 'pending'::text)
  ORDER BY
        CASE car.priority
            WHEN 'urgent'::text THEN 1
            WHEN 'high'::text THEN 2
            WHEN 'normal'::text THEN 3
            WHEN 'low'::text THEN 4
            ELSE NULL::integer
        END, car.created_at;

-- v_engineer_spending
CREATE OR REPLACE VIEW v_engineer_spending AS
 SELECT id AS agent_id,
    name AS agent_name,
    first_name,
    last_name,
    department,
    engineer_budget_monthly AS budget,
    engineer_usage_this_month AS used,
    (engineer_budget_monthly - engineer_usage_this_month) AS remaining,
    round(((100.0 * engineer_usage_this_month) / NULLIF(engineer_budget_monthly, (0)::numeric)), 2) AS usage_percent,
        CASE
            WHEN (engineer_usage_this_month >= engineer_budget_monthly) THEN 'exhausted'::text
            WHEN (engineer_usage_this_month >= (engineer_budget_monthly * 0.8)) THEN 'warning'::text
            ELSE 'ok'::text
        END AS budget_status
   FROM agents a
  WHERE (((worker_type)::text = 'contract'::text) AND ((status)::text = 'active'::text))
  ORDER BY engineer_usage_this_month DESC;

-- v_escalation_analysis (updated column reference)
CREATE OR REPLACE VIEW v_escalation_analysis AS
 SELECT intent_type,
    count(*) AS total,
    sum(
        CASE
            WHEN escalated_to_engineer THEN 1
            ELSE 0
        END) AS escalated,
    round(((100.0 * (sum(
        CASE
            WHEN escalated_to_engineer THEN 1
            ELSE 0
        END))::numeric) / (count(*))::numeric), 2) AS escalation_rate,
    avg(
        CASE
            WHEN (NOT escalated_to_engineer) THEN
            CASE
                WHEN success THEN 1.0
                ELSE 0.0
            END
            ELSE NULL::numeric
        END) AS local_success_rate,
    avg(
        CASE
            WHEN escalated_to_engineer THEN
            CASE
                WHEN success THEN 1.0
                ELSE 0.0
            END
            ELSE NULL::numeric
        END) AS engineer_success_rate
   FROM archie_command_log
  GROUP BY intent_type;

-- v_internal_agents (updated column references)
CREATE OR REPLACE VIEW v_internal_agents AS
 SELECT id,
    name,
    type_id,
    tier,
    status,
    model,
    temperature,
    max_tokens,
    system_prompt,
    capabilities,
    permissions,
    metadata,
    created_by,
    created_at,
    updated_at,
    monthly_budget,
    budget_alert_threshold,
    total_tokens_used,
    total_cost,
    last_used,
    first_name,
    last_name,
    email,
    title,
    department,
    bio,
    avatar_url,
    pronouns,
    worker_type,
    requires_api_approval,
    api_provider,
    cost_tier,
    api_enabled,
    api_key_configured,
    visibility,
    phone,
    current_grade,
    performance_score,
    total_tasks_completed,
    success_rate,
    last_performance_update,
    personality_prompt,
    communication_style,
    memory_context,
    work_history_summary,
    default_model_tier,
    max_opus_percentage,
    auto_escalate,
    escalation_failure_threshold,
    opus_usage_this_month,
    total_tasks_this_month,
    avatar_generation_prompt,
    gmail,
    auto_approve_threshold,
    engineer_usage_this_month,
    engineer_budget_monthly,
    learned_skills,
    learning_history,
    parent_agent_id,
    created_by_agent_id,
    created_by_user_id,
    agent_generation,
    display_name,
    image_model,
    is_cloneable,
    shift_state,
    voice_sample,
    reports_to_agent_id,
    is_department_ai,
    acronym,
    acronym_expansion,
    floor,
    gender,
    ethnicity,
    age_range,
    appearance_notes,
    portrait_prompt,
    writing_tone,
    writing_style,
    social_topics,
    creed_tenant,
    org_id
   FROM agents
  WHERE (org_id IS NULL);

-- v_module_usage_stats (updated column reference)
CREATE OR REPLACE VIEW v_module_usage_stats AS
 SELECT module_source,
    count(*) AS total_tasks,
    count(DISTINCT agent_id) AS agents_involved,
    sum(tokens_used) AS total_tokens,
    sum(cost) AS total_cost,
    avg(duration_ms) AS avg_duration_ms,
    round(((100.0 * (count(*) FILTER (WHERE (success = true)))::numeric) / (NULLIF(count(*), 0))::numeric), 2) AS success_rate,
    count(*) FILTER (WHERE ((worker_type)::text = 'internal'::text)) AS internal_tasks,
    count(*) FILTER (WHERE ((worker_type)::text = 'contract'::text)) AS engineer_tasks
   FROM task_execution_log
  WHERE ((created_at > (now() - '30 days'::interval)) AND (module_source IS NOT NULL))
  GROUP BY module_source
  ORDER BY (count(*)) DESC;
