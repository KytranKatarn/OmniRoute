-- REAL DDL snapshot (pg_dump --schema-only --section=pre-data) of the tables ingest/tier2_upgrade.persist_upgrade writes.
-- Regenerate (read-only) on Citadel when they change:
--   docker exec what-the-fact-wtf-postgres-1 pg_dump -U wtfuser -d wtf --schema-only --section=pre-data --no-owner --no-acl \
--     -t wtf.bias_scores -t wtf.fact_checks -t wtf.articles
-- Snapshot 2026-10-20. No data; constraints other than CHECK are post-data and absent (tests seed without FK ordering).
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg12+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg12+2)

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
-- Name: articles; Type: TABLE; Schema: wtf; Owner: -
--

CREATE TABLE wtf.articles (
    id integer NOT NULL,
    source_id integer NOT NULL,
    external_id character varying(512) NOT NULL,
    title character varying(1024) NOT NULL,
    body text NOT NULL,
    url character varying(1024) NOT NULL,
    published_at timestamp without time zone NOT NULL,
    ingested_at timestamp without time zone DEFAULT now() NOT NULL,
    cluster_id integer,
    province_code character varying(2),
    city character varying(100),
    lat numeric(9,6),
    lng numeric(9,6),
    geo_scope character varying(20) DEFAULT 'national'::character varying NOT NULL,
    ai_analyzed boolean DEFAULT false NOT NULL,
    ai_analyzed_at timestamp without time zone,
    country_code character varying(2),
    analysis_tier character varying(32) DEFAULT 'pending'::character varying,
    tier1_at timestamp without time zone,
    tier2_at timestamp without time zone,
    tier2_failures integer DEFAULT 0,
    tier2_pending boolean DEFAULT false,
    bias_v2_score numeric(4,3),
    bias_v2_label text,
    bias_v2_confidence numeric(4,3),
    bias_v2_model text,
    bias_v2_computed_at timestamp with time zone,
    bias_ensemble_score numeric(4,3),
    bias_ensemble_band text,
    body_source character varying(50) DEFAULT NULL::character varying,
    beat character varying(64),
    suppressed_reason text,
    content_type text DEFAULT 'journalism'::text NOT NULL,
    canonical_article_id integer,
    geo_processed_at timestamp with time zone,
    latest_verdict character varying(50),
    CONSTRAINT article_latest_verdict_check CHECK (((latest_verdict IS NULL) OR ((latest_verdict)::text = ANY (ARRAY['verified'::text, 'mostly_true'::text, 'mixed'::text, 'disputed'::text, 'unverifiable'::text, 'descriptive_reporting'::text])))),
    CONSTRAINT articles_geo_scope_check CHECK (((geo_scope)::text = ANY (ARRAY[('national'::character varying)::text, ('provincial'::character varying)::text, ('municipal'::character varying)::text, ('international'::character varying)::text, ('unmappable'::character varying)::text])))
);


--
-- Name: COLUMN articles.country_code; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.country_code IS 'ISO 3166-1 alpha-2 (CA, US, GB, ...). NULL = unknown.';


--
-- Name: COLUMN articles.analysis_tier; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.analysis_tier IS 'Most recent tier that produced canonical results. Values: pending, quick_v1, quick_v1+full, quick_v1+failed.';


--
-- Name: COLUMN articles.tier1_at; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.tier1_at IS 'Timestamp when Tier 1 (quick_v1) completed. NULL means never ran.';


--
-- Name: COLUMN articles.tier2_at; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.tier2_at IS 'Timestamp when Tier 2 (full) completed. NULL means never ran (or skipped by gate).';


--
-- Name: COLUMN articles.tier2_failures; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.tier2_failures IS 'Consecutive Tier-2 failures for this article. Worker stops retrying after 3.';


--
-- Name: COLUMN articles.tier2_pending; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.tier2_pending IS 'TRUE when Tier 1 ran successfully but Tier 2 should still upgrade the result.';


--
-- Name: COLUMN articles.bias_v2_score; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_v2_score IS 'DistilBERT zero-shot bias score, signed [-1.0, +1.0] (negative=left, positive=right)';


--
-- Name: COLUMN articles.bias_v2_label; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_v2_label IS 'Top label from zero-shot: left | center | right';


--
-- Name: COLUMN articles.bias_v2_confidence; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_v2_confidence IS 'Top-label probability from classifier, [0.0, 1.0]';


--
-- Name: COLUMN articles.bias_v2_model; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_v2_model IS 'HF model id used for scoring (e.g., valhalla/distilbart-mnli-12-3)';


--
-- Name: COLUMN articles.bias_ensemble_score; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_ensemble_score IS '0.5 * bias_score (LLM tier-1) + 0.5 * bias_v2_score (DistilBERT)';


--
-- Name: COLUMN articles.bias_ensemble_band; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.bias_ensemble_band IS 'Band derived from bias_ensemble_score via _band_for()';


--
-- Name: COLUMN articles.suppressed_reason; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.suppressed_reason IS 'NULL = visible. Non-NULL hides the row from reader-facing surfaces without deleting it or its downstream analysis. Set by data-quality fixes; reversible.';


--
-- Name: COLUMN articles.content_type; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.content_type IS 'journalism (default, fail-safe) | wire = press-release/newswire copy. Wire items are EXCLUDED from outlet bias averages and their political score is suppressed in the UI: there is no partisan lean in a corporate announcement, and averaging one in dilutes the outlet''s measured lean. Set by ingest/content_kind.classify() from distributor boilerplate only.';


--
-- Name: COLUMN articles.canonical_article_id; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.canonical_article_id IS 'For a suppressed duplicate: the surviving article it duplicates. NULL for visible articles and for suppression reasons that are not duplication (e.g. publisher_suffix_title, which has no survivor). Drives the 301 on /article/<id> and the entity-graph re-point. See migration 070.';


--
-- Name: COLUMN articles.geo_processed_at; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.articles.geo_processed_at IS 'When L.O.C.A.L. finished geo for this article — set on BOTH a successful geocode and a terminal geo_scope=''unmappable''. NULL = pre-dates migration 073 or not yet processed. Deliberately NOT backfilled: it measures a forward throughput rate, and a synthesised past would fabricate history (#6263).';


--
-- Name: articles_id_seq; Type: SEQUENCE; Schema: wtf; Owner: -
--

CREATE SEQUENCE wtf.articles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: articles_id_seq; Type: SEQUENCE OWNED BY; Schema: wtf; Owner: -
--

ALTER SEQUENCE wtf.articles_id_seq OWNED BY wtf.articles.id;


--
-- Name: bias_scores; Type: TABLE; Schema: wtf; Owner: -
--

CREATE TABLE wtf.bias_scores (
    id integer NOT NULL,
    article_id integer NOT NULL,
    band character varying(16) NOT NULL,
    score real NOT NULL,
    heuristic_version character varying(16) NOT NULL,
    rationale text NOT NULL,
    computed_at timestamp without time zone DEFAULT now() NOT NULL,
    analyzed_by character varying(20) DEFAULT 'heuristic'::character varying,
    trigger_phrases jsonb,
    confidence numeric(4,3),
    agent_name text,
    signal_detected boolean DEFAULT true NOT NULL,
    CONSTRAINT bias_band_check CHECK (((band)::text = ANY (ARRAY[('left'::character varying)::text, ('center-left'::character varying)::text, ('center'::character varying)::text, ('center-right'::character varying)::text, ('right'::character varying)::text])))
);


--
-- Name: COLUMN bias_scores.agent_name; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.bias_scores.agent_name IS 'A.R.C.H.I.E. agent that produced this score, per the dispatcher. NULL = not recorded (do not default to a name).';


--
-- Name: COLUMN bias_scores.signal_detected; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.bias_scores.signal_detected IS 'FALSE = the detector matched NO trigger term for this article. score (0.0) and band (center) carry schema-required values ONLY and assert nothing — do NOT render such a row as a centrist finding. The outlet rollup (ingest/outlet_bias.py) averages `signal_detected IS NOT FALSE` rows only. TRUE = a real measurement, including a genuine 0.0.';


--
-- Name: bias_scores_id_seq; Type: SEQUENCE; Schema: wtf; Owner: -
--

CREATE SEQUENCE wtf.bias_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bias_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: wtf; Owner: -
--

ALTER SEQUENCE wtf.bias_scores_id_seq OWNED BY wtf.bias_scores.id;


--
-- Name: fact_checks; Type: TABLE; Schema: wtf; Owner: -
--

CREATE TABLE wtf.fact_checks (
    id integer NOT NULL,
    article_id integer NOT NULL,
    claim text NOT NULL,
    verdict character varying(32) NOT NULL,
    evidence text NOT NULL,
    checker character varying(64) NOT NULL,
    checked_at timestamp without time zone DEFAULT now() NOT NULL,
    analyzed_by character varying(20) DEFAULT 'heuristic'::character varying,
    claims jsonb,
    overall_verdict character varying(50),
    agent_name text,
    analysis_tier character varying(40),
    CONSTRAINT fact_overall_verdict_check CHECK (((overall_verdict IS NULL) OR ((overall_verdict)::text = ANY (ARRAY[('verified'::character varying)::text, ('mostly_true'::character varying)::text, ('mixed'::character varying)::text, ('disputed'::character varying)::text, ('unverifiable'::character varying)::text, ('descriptive_reporting'::character varying)::text])))),
    CONSTRAINT fact_verdict_check CHECK (((verdict)::text = ANY (ARRAY[('true'::character varying)::text, ('mostly_true'::character varying)::text, ('mixed'::character varying)::text, ('false'::character varying)::text, ('unverified'::character varying)::text])))
);


--
-- Name: COLUMN fact_checks.overall_verdict; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.fact_checks.overall_verdict IS 'PER-ARTICLE verdict: verified|mostly_true|mixed|disputed|unverifiable|descriptive_reporting, or NULL when no analysis was recorded. DISTINCT vocabulary from the per-claim `verdict` column — `unverified` belongs there, `unverifiable` belongs here. Canonicalize via ingest/verdicts.canonical_overall().';


--
-- Name: COLUMN fact_checks.agent_name; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.fact_checks.agent_name IS 'A.R.C.H.I.E. agent that performed this check, per the dispatcher. NULL = not recorded (do not default to a name). Distinct from checker (pipeline version / external partner) and analyzed_by (dedup selector).';


--
-- Name: COLUMN fact_checks.analysis_tier; Type: COMMENT; Schema: wtf; Owner: -
--

COMMENT ON COLUMN wtf.fact_checks.analysis_tier IS 'How this verdict was produced. quick_v1 = TIER 1 ONLY: claims were extracted but NEVER verified, and overall_verdict is a SYNTHESIZED placeholder (ingest/tier_router._factcheck_tier1_only) — do NOT render it as an adjudication. quick_v1+full / quick_v1_failed+full = tier 2 actually ran. direct = DHQ job, full check with no tier gating. on_demand = Deep Dive. A leading ~ means the value was RECONSTRUCTED by migration 062 from articles.analysis_tier, not recorded at write time.';


--
-- Name: fact_checks_id_seq; Type: SEQUENCE; Schema: wtf; Owner: -
--

CREATE SEQUENCE wtf.fact_checks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fact_checks_id_seq; Type: SEQUENCE OWNED BY; Schema: wtf; Owner: -
--

ALTER SEQUENCE wtf.fact_checks_id_seq OWNED BY wtf.fact_checks.id;


--
-- Name: articles id; Type: DEFAULT; Schema: wtf; Owner: -
--

ALTER TABLE ONLY wtf.articles ALTER COLUMN id SET DEFAULT nextval('wtf.articles_id_seq'::regclass);


--
-- Name: bias_scores id; Type: DEFAULT; Schema: wtf; Owner: -
--

ALTER TABLE ONLY wtf.bias_scores ALTER COLUMN id SET DEFAULT nextval('wtf.bias_scores_id_seq'::regclass);


--
-- Name: fact_checks id; Type: DEFAULT; Schema: wtf; Owner: -
--

ALTER TABLE ONLY wtf.fact_checks ALTER COLUMN id SET DEFAULT nextval('wtf.fact_checks_id_seq'::regclass);


--
-- PostgreSQL database dump complete
--
