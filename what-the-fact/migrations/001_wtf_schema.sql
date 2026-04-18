-- WTF schema: articles, bias_scores, fact_checks, audit_trail, source_registry, failed_ingest
CREATE SCHEMA IF NOT EXISTS wtf;

CREATE TABLE IF NOT EXISTS wtf.sources (
    id         SERIAL PRIMARY KEY,
    slug       VARCHAR(64)  NOT NULL UNIQUE,
    name       VARCHAR(128) NOT NULL,
    url        VARCHAR(512) NOT NULL,
    country    VARCHAR(8)   NOT NULL DEFAULT 'CA',
    language   VARCHAR(8)   NOT NULL DEFAULT 'en',
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS wtf.articles (
    id           SERIAL PRIMARY KEY,
    source_id    INTEGER       NOT NULL REFERENCES wtf.sources(id),
    external_id  VARCHAR(512)  NOT NULL,
    title        VARCHAR(1024) NOT NULL,
    body         TEXT          NOT NULL,
    url          VARCHAR(1024) NOT NULL,
    published_at TIMESTAMP     NOT NULL,
    ingested_at  TIMESTAMP     NOT NULL DEFAULT now(),
    CONSTRAINT articles_source_external_unique UNIQUE (source_id, external_id)
);
CREATE INDEX IF NOT EXISTS ix_articles_published_at ON wtf.articles (published_at DESC);

CREATE TABLE IF NOT EXISTS wtf.bias_scores (
    id                SERIAL PRIMARY KEY,
    article_id        INTEGER      NOT NULL UNIQUE REFERENCES wtf.articles(id) ON DELETE CASCADE,
    band              VARCHAR(16)  NOT NULL,
    score             REAL         NOT NULL,
    heuristic_version VARCHAR(16)  NOT NULL,
    rationale         TEXT         NOT NULL,
    computed_at       TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT bias_band_check CHECK (band IN
        ('left','center-left','center','center-right','right'))
);

CREATE TABLE IF NOT EXISTS wtf.fact_checks (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    claim      TEXT         NOT NULL,
    verdict    VARCHAR(32)  NOT NULL,
    evidence   TEXT         NOT NULL,
    checker    VARCHAR(64)  NOT NULL,
    checked_at TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT fact_verdict_check CHECK (verdict IN
        ('true','mostly_true','mixed','false','unverified'))
);

CREATE TABLE IF NOT EXISTS wtf.audit_trail (
    id         SERIAL PRIMARY KEY,
    article_id INTEGER      NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    event_type VARCHAR(64)  NOT NULL,
    payload    JSONB        NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_article ON wtf.audit_trail (article_id);

CREATE TABLE IF NOT EXISTS wtf.failed_ingest (
    id          SERIAL PRIMARY KEY,
    source_slug VARCHAR(64) NOT NULL,
    raw_payload JSONB       NOT NULL,
    error       TEXT        NOT NULL,
    created_at  TIMESTAMP   NOT NULL DEFAULT now()
);
