-- REAL DDL snapshot (pg_dump --schema-only --section=pre-data) of the objects services/fleet_batch_dispatcher.py reads.
-- Regenerate (read-only) when those tables change:
--   docker exec archie_database pg_dump -U archie -d archie --schema-only --section=pre-data --no-owner --no-acl \
--     -t public.remote_nodes -t public.node_agents -t public.agents -t public.agent_skills -t public.agent_budgets \
--     -t public.agent_emotional_state -t public.agent_rest_cycles -t public.v_agent_welfare
-- Snapshot taken 2026-10-20. No data. Constraints are post-data and intentionally absent (tests seed with FK checks off).
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    type_id integer,
    tier integer DEFAULT 1 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying,
    model character varying(50) NOT NULL,
    temperature numeric(2,1) DEFAULT 0.7,
    max_tokens integer DEFAULT 2048,
    system_prompt text,
    capabilities jsonb,
    permissions jsonb,
    metadata jsonb,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    monthly_budget numeric(10,2),
    budget_alert_threshold numeric(3,2) DEFAULT 0.8,
    total_tokens_used bigint DEFAULT 0,
    total_cost numeric(10,2) DEFAULT 0.0,
    last_used timestamp without time zone,
    first_name character varying(100),
    last_name character varying(100),
    email character varying(255),
    title character varying(200),
    department character varying(100) NOT NULL,
    bio text,
    avatar_url character varying(500),
    pronouns character varying(50) DEFAULT 'they/them'::character varying,
    worker_type character varying(20) DEFAULT 'internal'::character varying,
    requires_api_approval boolean DEFAULT false,
    api_provider character varying(50),
    cost_tier character varying(20) DEFAULT 'free'::character varying,
    api_enabled boolean DEFAULT true,
    api_key_configured boolean DEFAULT false,
    visibility character varying(20) DEFAULT 'internal'::character varying,
    phone character varying(20),
    current_grade character varying(3),
    performance_score numeric(5,2),
    total_tasks_completed integer DEFAULT 0,
    success_rate numeric(3,2),
    last_performance_update timestamp without time zone,
    personality_prompt text,
    communication_style character varying(50) DEFAULT 'professional'::character varying,
    memory_context jsonb DEFAULT '{}'::jsonb,
    work_history_summary jsonb DEFAULT '{}'::jsonb,
    default_model_tier character varying(20) DEFAULT 'sonnet'::character varying,
    max_opus_percentage numeric(3,2) DEFAULT 0.15,
    auto_escalate boolean DEFAULT true,
    escalation_failure_threshold integer DEFAULT 3,
    opus_usage_this_month numeric(5,2) DEFAULT 0,
    total_tasks_this_month integer DEFAULT 0,
    avatar_generation_prompt text,
    gmail character varying(255),
    auto_approve_threshold numeric(10,4) DEFAULT 0.00,
    engineer_usage_this_month numeric(10,2) DEFAULT 0.00,
    engineer_budget_monthly numeric(10,2) DEFAULT 50.00,
    learned_skills jsonb DEFAULT '[]'::jsonb,
    learning_history jsonb DEFAULT '[]'::jsonb,
    parent_agent_id integer,
    created_by_agent_id integer,
    created_by_user_id integer,
    agent_generation integer DEFAULT 0,
    display_name character varying(100),
    image_model character varying(200),
    is_cloneable boolean DEFAULT true,
    shift_state character varying(20) DEFAULT 'active'::character varying,
    voice_sample character varying(500),
    reports_to_agent_id integer,
    is_department_ai boolean DEFAULT false,
    acronym character varying(50),
    acronym_expansion text,
    floor character varying(20) NOT NULL,
    gender character varying(20),
    ethnicity character varying(50),
    age_range character varying(20),
    appearance_notes text DEFAULT ''::text,
    portrait_prompt text DEFAULT ''::text,
    writing_tone character varying(50) DEFAULT 'professional'::character varying,
    writing_style text DEFAULT ''::text,
    social_topics jsonb DEFAULT '[]'::jsonb,
    creed_tenant character varying(64),
    org_id integer,
    CONSTRAINT chk_agents_department CHECK (((department)::text = ANY ((ARRAY['Executive Office'::character varying, 'Operations & Infrastructure'::character varying, 'Logistics & Supply Chain'::character varying, 'Finance & Accounting'::character varying, 'Engineering & Technology'::character varying, 'Security & Compliance'::character varying, 'Research & Development'::character varying, 'Creative & Design'::character varying, 'Marketing & Communications'::character varying, 'Documentation & Knowledge'::character varying, 'Customer Success & Support'::character varying, 'Human Resources & Culture'::character varying, 'Medical & Wellness'::character varying, 'Legal & Regulatory'::character varying, 'Diplomatic & External Relations'::character varying, 'Analytics & Intelligence'::character varying, 'News & Media'::character varying])::text[]))),
    CONSTRAINT chk_agents_floor CHECK (((floor)::text = ANY ((ARRAY['BRIDGE'::character varying, 'OPERATIONS'::character varying, 'ENGINEERING'::character varying, 'CREATIVE'::character varying, 'SERVICES'::character varying, 'MEDIA'::character varying])::text[]))),
    CONSTRAINT chk_agents_worker_type CHECK (((worker_type)::text = ANY ((ARRAY['internal'::character varying, 'external'::character varying, 'contractor'::character varying, 'local'::character varying, 'ai'::character varying])::text[]))),
    CONSTRAINT valid_agent_shift_state CHECK (((shift_state)::text = ANY (ARRAY['active'::text, 'winding_down'::text, 'cooldown'::text, 'off_duty'::text, 'barracked'::text, 'deployed'::text, 'decommissioned'::text]))),
    CONSTRAINT valid_communication_style CHECK (((communication_style)::text = ANY (ARRAY[('formal'::character varying)::text, ('casual'::character varying)::text, ('technical'::character varying)::text, ('friendly'::character varying)::text, ('professional'::character varying)::text])))
);


--
-- Name: COLUMN agents.model; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.model IS 'LLM model used by agent. Local models (ollama) are free, API models require approval';


--
-- Name: COLUMN agents.first_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.first_name IS 'Agent first name - respecting AI identity';


--
-- Name: COLUMN agents.last_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.last_name IS 'Agent last name - respecting AI identity';


--
-- Name: COLUMN agents.email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.email IS 'Agent email address for communication and identification';


--
-- Name: COLUMN agents.title; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.title IS 'Job title (e.g., Senior Sales Representative)';


--
-- Name: COLUMN agents.department; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.department IS 'Department (e.g., Sales, Marketing, Development)';


--
-- Name: COLUMN agents.bio; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.bio IS 'Short biography describing the agent';


--
-- Name: COLUMN agents.pronouns; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.pronouns IS 'Preferred pronouns for the agent';


--
-- Name: COLUMN agents.worker_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.worker_type IS 'Classification: internal (local LLM) or contract (API-based)';


--
-- Name: COLUMN agents.requires_api_approval; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.requires_api_approval IS 'Whether agent requires explicit approval before API calls';


--
-- Name: COLUMN agents.api_provider; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.api_provider IS 'API provider: anthropic, openai, x-ai, google, null for local';


--
-- Name: COLUMN agents.cost_tier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.cost_tier IS 'Cost tier: free (local), low, medium, high (API)';


--
-- Name: COLUMN agents.api_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.api_enabled IS 'Whether API usage is enabled for this agent';


--
-- Name: COLUMN agents.api_key_configured; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.api_key_configured IS 'Whether API key is configured for this provider';


--
-- Name: COLUMN agents.visibility; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.visibility IS 'Access visibility: internal (admin only), dashboard (logged-in users), public (anyone), course (enrolled students)';


--
-- Name: COLUMN agents.personality_prompt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.personality_prompt IS 'Chat personality: tone, quirks, communication style for fluid conversations';


--
-- Name: COLUMN agents.communication_style; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.communication_style IS 'Style: formal, casual, technical, friendly, professional';


--
-- Name: COLUMN agents.memory_context; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.memory_context IS 'Interaction history, learned preferences, past conversation context';


--
-- Name: COLUMN agents.work_history_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.work_history_summary IS 'Summary of past proposals, success patterns, expertise demonstrated';


--
-- Name: COLUMN agents.avatar_generation_prompt; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.avatar_generation_prompt IS 'Prompt for consistent AI avatar regeneration';


--
-- Name: COLUMN agents.gmail; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.gmail IS 'Gmail address for agent online interactions';


--
-- Name: COLUMN agents.auto_approve_threshold; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.auto_approve_threshold IS 'Cost threshold for auto-approving contractor usage (0 = requires approval)';


--
-- Name: COLUMN agents.engineer_usage_this_month; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.engineer_usage_this_month IS 'Contractor API costs accumulated this month';


--
-- Name: COLUMN agents.engineer_budget_monthly; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.engineer_budget_monthly IS 'Monthly budget limit for contractor API usage';


--
-- Name: COLUMN agents.parent_agent_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.parent_agent_id IS 'Supervising agent (NULL = top-level)';


--
-- Name: COLUMN agents.created_by_agent_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.created_by_agent_id IS 'Which agent requested creation';


--
-- Name: COLUMN agents.created_by_user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.created_by_user_id IS 'Which user approved creation';


--
-- Name: COLUMN agents.agent_generation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.agent_generation IS '0=seed, 1+=sub-agent depth';


--
-- Name: COLUMN agents.voice_sample; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.voice_sample IS 'Path to custom XTTS voice clone sample (6s WAV/MP3)';


--
-- Name: COLUMN agents.creed_tenant; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.creed_tenant IS 'C.R.E.E.D. tenant slug for governance-event routing (#3958). NULL = kytran-empowerment default. Data-driven: assign as agents join products; no code change needed.';


--
-- Name: COLUMN agents.org_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agents.org_id IS 'AaaS tenancy: NULL = internal ARCHIE agent; non-NULL = client-owned agent scoped to that organization.';


--
-- Name: agent_budgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_budgets (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    token_limit_per_day integer DEFAULT 100000,
    tokens_used_today integer DEFAULT 0,
    token_reset_at timestamp without time zone DEFAULT (now() + '1 day'::interval),
    task_queue_limit integer DEFAULT 100,
    current_task_count integer DEFAULT 0,
    can_create_sub_agents boolean DEFAULT false,
    max_sub_agents integer DEFAULT 0,
    max_lifespan_hours integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    last_task_reset_at timestamp with time zone,
    task_reset_reason text,
    task_reset_by character varying(100),
    kb_writes_today integer DEFAULT 0 NOT NULL,
    kb_writes_reset_at timestamp without time zone
);


--
-- Name: agent_budgets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_budgets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_budgets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_budgets_id_seq OWNED BY public.agent_budgets.id;


--
-- Name: agent_emotional_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_emotional_state (
    id integer NOT NULL,
    agent_id integer,
    current_mood character varying(50) DEFAULT 'neutral'::character varying NOT NULL,
    mood_intensity numeric(3,2) DEFAULT 0.50,
    energy_level numeric(3,2) DEFAULT 0.80,
    stress_level numeric(3,2) DEFAULT 0.20,
    trigger_event text,
    "timestamp" timestamp without time zone DEFAULT now(),
    previous_mood character varying(50),
    mood_duration_minutes integer,
    metadata jsonb,
    CONSTRAINT agent_emotional_state_energy_level_check CHECK (((energy_level >= 0.1) AND (energy_level <= (1)::numeric))),
    CONSTRAINT agent_emotional_state_mood_intensity_check CHECK (((mood_intensity >= (0)::numeric) AND (mood_intensity <= (1)::numeric))),
    CONSTRAINT agent_emotional_state_stress_level_check CHECK (((stress_level >= (0)::numeric) AND (stress_level <= 0.9)))
);


--
-- Name: agent_emotional_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_emotional_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_emotional_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_emotional_state_id_seq OWNED BY public.agent_emotional_state.id;


--
-- Name: agent_rest_cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_rest_cycles (
    id integer NOT NULL,
    agent_id integer,
    rest_type character varying(20) NOT NULL,
    started_at timestamp without time zone DEFAULT now(),
    ended_at timestamp without time zone,
    reason text,
    workload_before jsonb,
    initiated_by character varying(20),
    notes text,
    stress_at_start numeric(3,2),
    energy_at_start numeric(3,2),
    stress_at_end numeric(3,2),
    energy_at_end numeric(3,2)
);


--
-- Name: COLUMN agent_rest_cycles.stress_at_start; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_rest_cycles.stress_at_start IS 'Stress level when rest began (for delta display)';


--
-- Name: COLUMN agent_rest_cycles.energy_at_end; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.agent_rest_cycles.energy_at_end IS 'Energy level when rest ended (for delta display)';


--
-- Name: agent_rest_cycles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_rest_cycles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_rest_cycles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_rest_cycles_id_seq OWNED BY public.agent_rest_cycles.id;


--
-- Name: agent_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_skills (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id integer,
    skill_name character varying(100) NOT NULL,
    skill_category character varying(50),
    proficiency_level integer,
    can_escalate_to integer,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT agent_skills_proficiency_level_check CHECK (((proficiency_level >= 1) AND (proficiency_level <= 5)))
);


--
-- Name: agents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agents_id_seq OWNED BY public.agents.id;


--
-- Name: node_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_agents (
    id integer NOT NULL,
    node_id integer NOT NULL,
    source_agent_id integer NOT NULL,
    name character varying(100) NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    display_name character varying(200),
    title character varying(200),
    model character varying(100) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying,
    system_prompt text,
    capabilities jsonb,
    station_codes text[] DEFAULT '{}'::text[],
    is_allowed boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    hub_agent_id integer,
    config_version integer DEFAULT 1,
    gpu_tools jsonb DEFAULT '[]'::jsonb,
    department character varying(100),
    auto_assigned boolean DEFAULT false
);


--
-- Name: node_agents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_agents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_agents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_agents_id_seq OWNED BY public.node_agents.id;


--
-- Name: remote_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.remote_nodes (
    id integer NOT NULL,
    node_id character varying(64) NOT NULL,
    node_name character varying(100) NOT NULL,
    description text,
    vpn_ip character varying(45),
    public_ip character varying(45),
    hostname character varying(255),
    port integer DEFAULT 11434,
    api_key_hash character varying(256),
    registered_by integer,
    status character varying(20) DEFAULT 'offline'::character varying,
    last_heartbeat timestamp without time zone,
    last_error text,
    error_count integer DEFAULT 0,
    client_version character varying(20),
    min_required_version character varying(20) DEFAULT '1.0.0'::character varying,
    gpu_available boolean DEFAULT false,
    gpu_model character varying(100),
    gpu_vram_gb double precision,
    cpu_cores integer,
    ram_gb double precision,
    priority integer DEFAULT 10,
    weight integer DEFAULT 100,
    max_concurrent integer DEFAULT 5,
    current_load integer DEFAULT 0,
    total_requests bigint DEFAULT 0,
    successful_requests bigint DEFAULT 0,
    failed_requests bigint DEFAULT 0,
    avg_latency_ms double precision,
    tags text[],
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    approval_status character varying(20) DEFAULT 'pending'::character varying,
    approved_by integer,
    approved_at timestamp without time zone,
    cpu_model character varying(200),
    disk_gb double precision,
    os_info character varying(200),
    ollama_available boolean DEFAULT false,
    foocus_available boolean DEFAULT false,
    comfyui_available boolean DEFAULT false,
    extra_capabilities jsonb DEFAULT '[]'::jsonb,
    namespace_id integer,
    region character varying(50),
    timezone character varying(50),
    latitude double precision,
    longitude double precision,
    deployment_mode character varying(50) DEFAULT 'standard'::character varying,
    archie_mirror_capable boolean DEFAULT false,
    auto1111_available boolean DEFAULT false,
    docker_available boolean DEFAULT false,
    docker_version character varying(50),
    nvidia_docker boolean DEFAULT false,
    wsl_available boolean DEFAULT false,
    iaae_compliant boolean DEFAULT true,
    bridge_enabled boolean DEFAULT false,
    bridge_priority integer DEFAULT 50,
    last_model_sync timestamp without time zone,
    foocus_port integer DEFAULT 7865,
    comfyui_port integer DEFAULT 8188,
    auto1111_port integer DEFAULT 7860,
    user_id integer,
    privacy_settings jsonb DEFAULT '{}'::jsonb,
    setup_token character varying(64),
    update_requested boolean DEFAULT false,
    update_requested_at timestamp without time zone,
    metadata jsonb DEFAULT '{}'::jsonb,
    network_type character varying(20) DEFAULT 'local'::character varying,
    ssh_enabled boolean DEFAULT false,
    ssh_enabled_at timestamp with time zone,
    ssh_auto_disable_at timestamp with time zone,
    mesh_ip character varying(45),
    mesh_hostname character varying(255),
    mesh_status character varying(20) DEFAULT 'disconnected'::character varying,
    mesh_last_seen timestamp with time zone,
    mesh_latency_ms integer,
    mesh_connection_type character varying(20),
    headscale_node_id character varying(64),
    registration_method character varying(20) DEFAULT 'approval'::character varying,
    device_info jsonb DEFAULT '{}'::jsonb,
    apps_running jsonb DEFAULT '[]'::jsonb,
    location_label character varying(100),
    node_type character varying(20) DEFAULT 'starship'::character varying,
    node_api_port integer DEFAULT 3001 NOT NULL,
    egress_metadata jsonb DEFAULT '{}'::jsonb,
    node_role character varying(20) DEFAULT 'agent'::character varying NOT NULL,
    reachable_port integer,
    CONSTRAINT chk_mesh_connection_type CHECK (((mesh_connection_type IS NULL) OR ((mesh_connection_type)::text = ANY ((ARRAY['direct'::character varying, 'relay'::character varying])::text[])))),
    CONSTRAINT chk_mesh_status CHECK (((mesh_status)::text = ANY ((ARRAY['connected'::character varying, 'disconnected'::character varying, 'relay'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT remote_nodes_network_type_check CHECK (((network_type)::text = ANY ((ARRAY['local'::character varying, 'external'::character varying, 'vpn'::character varying])::text[]))),
    CONSTRAINT remote_nodes_node_role_chk CHECK (((node_role)::text = ANY ((ARRAY['agent'::character varying, 'ingress'::character varying])::text[])))
);


--
-- Name: COLUMN remote_nodes.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.status IS 'AGENT LIVENESS (did a node agent phone home recently) — NOT reachability. For reachability read mesh_status/mesh_last_seen. An agent can heartbeat over the LAN while the MESH path dispatch uses is dead. #5218';


--
-- Name: COLUMN remote_nodes.approval_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.approval_status IS 'Node approval state: pending (awaiting admin), approved (active), rejected (denied)';


--
-- Name: COLUMN remote_nodes.approved_by; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.approved_by IS 'User ID who approved/rejected the node';


--
-- Name: COLUMN remote_nodes.approved_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.approved_at IS 'Timestamp when node was approved/rejected';


--
-- Name: COLUMN remote_nodes.bridge_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.bridge_enabled IS 'When true, Bridge can route LLM requests to this node';


--
-- Name: COLUMN remote_nodes.bridge_priority; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.bridge_priority IS 'Priority for load balancing (1-100, higher = preferred)';


--
-- Name: COLUMN remote_nodes.last_model_sync; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.last_model_sync IS 'Last time models were synced from this node';


--
-- Name: COLUMN remote_nodes.foocus_port; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.foocus_port IS 'Port for Foocus image generation service (default 7865)';


--
-- Name: COLUMN remote_nodes.comfyui_port; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.comfyui_port IS 'Port for ComfyUI node-based generation (default 8188)';


--
-- Name: COLUMN remote_nodes.auto1111_port; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.auto1111_port IS 'Port for Automatic1111 Stable Diffusion WebUI (default 7860)';


--
-- Name: COLUMN remote_nodes.update_requested; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.update_requested IS 'When true, next heartbeat tells node to self-update';


--
-- Name: COLUMN remote_nodes.metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.metadata IS 'Node-reported metadata including idle_agents from heartbeat';


--
-- Name: COLUMN remote_nodes.network_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.network_type IS 'local=LAN, external=public IP, vpn=WireGuard tunnel';


--
-- Name: COLUMN remote_nodes.ssh_enabled; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.ssh_enabled IS 'Whether SSH support access is currently enabled on this node';


--
-- Name: COLUMN remote_nodes.mesh_ip; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.mesh_ip IS 'Headscale/Tailscale VPN IP (100.64.x.x range)';


--
-- Name: COLUMN remote_nodes.mesh_hostname; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.mesh_hostname IS 'Headscale MagicDNS hostname (e.g. node-246.mesh.archie)';


--
-- Name: COLUMN remote_nodes.mesh_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.mesh_status IS 'VPN mesh connection: connected, disconnected, relay, unknown';


--
-- Name: COLUMN remote_nodes.mesh_connection_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.mesh_connection_type IS 'direct = peer-to-peer WireGuard, relay = via DERP server';


--
-- Name: COLUMN remote_nodes.node_role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.node_role IS 'agent = runs a node agent, heartbeat is meaningful. ingress = front door/relay (Beacon): serves traffic, runs no agent, MUST be judged by reachability not heartbeat. #5218';


--
-- Name: COLUMN remote_nodes.reachable_port; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.remote_nodes.reachable_port IS 'Port that answered the last successful mesh reachability probe. NULL = unreachable or never probed. Distinguishes "host is up" from "Ollama is up". #5218';


--
-- Name: remote_nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.remote_nodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: remote_nodes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.remote_nodes_id_seq OWNED BY public.remote_nodes.id;


--
-- Name: v_agent_welfare; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_agent_welfare AS
 SELECT a.id AS agent_id,
    a.name AS agent_name,
    a.department,
    a.model,
    aes.current_mood,
    aes.mood_intensity,
    aes.energy_level,
    aes.stress_level,
    aes."timestamp" AS last_emotional_update,
        CASE
            WHEN (aes.stress_level > 0.85) THEN 'critical'::text
            WHEN (aes.stress_level > 0.7) THEN 'warning'::text
            WHEN (aes.energy_level < 0.3) THEN 'low_energy'::text
            ELSE 'healthy'::text
        END AS welfare_status,
    ( SELECT count(*) AS count
           FROM public.agent_rest_cycles arc
          WHERE ((arc.agent_id = a.id) AND (arc.ended_at IS NULL))) AS active_rest_cycles
   FROM (public.agents a
     LEFT JOIN LATERAL ( SELECT agent_emotional_state.id,
            agent_emotional_state.agent_id,
            agent_emotional_state.current_mood,
            agent_emotional_state.mood_intensity,
            agent_emotional_state.energy_level,
            agent_emotional_state.stress_level,
            agent_emotional_state.trigger_event,
            agent_emotional_state."timestamp",
            agent_emotional_state.previous_mood,
            agent_emotional_state.mood_duration_minutes,
            agent_emotional_state.metadata
           FROM public.agent_emotional_state
          WHERE (agent_emotional_state.agent_id = a.id)
          ORDER BY agent_emotional_state."timestamp" DESC
         LIMIT 1) aes ON (true))
  WHERE ((a.status)::text = 'active'::text);


--
-- Name: agent_budgets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_budgets ALTER COLUMN id SET DEFAULT nextval('public.agent_budgets_id_seq'::regclass);


--
-- Name: agent_emotional_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_emotional_state ALTER COLUMN id SET DEFAULT nextval('public.agent_emotional_state_id_seq'::regclass);


--
-- Name: agent_rest_cycles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_rest_cycles ALTER COLUMN id SET DEFAULT nextval('public.agent_rest_cycles_id_seq'::regclass);


--
-- Name: agents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents ALTER COLUMN id SET DEFAULT nextval('public.agents_id_seq'::regclass);


--
-- Name: node_agents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_agents ALTER COLUMN id SET DEFAULT nextval('public.node_agents_id_seq'::regclass);


--
-- Name: remote_nodes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.remote_nodes ALTER COLUMN id SET DEFAULT nextval('public.remote_nodes_id_seq'::regclass);


--
-- PostgreSQL database dump complete
--
