-- Migration 114: Linguistics Module Tables
-- Creates tables for AI-powered translation, translation memory, and user language preferences

BEGIN;

-- 1. translations — cached AI translations
CREATE TABLE IF NOT EXISTS translations (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL,
    language VARCHAR(10) NOT NULL DEFAULT 'fr',
    text TEXT NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'ai_generated',
    status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
    context TEXT,
    generated_by VARCHAR(50),
    reviewed_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(key, language),
    CONSTRAINT chk_translations_source CHECK (source IN ('ai_generated', 'human_edited', 'imported')),
    CONSTRAINT chk_translations_status CHECK (status IN ('pending_review', 'approved', 'rejected'))
);

-- 2. translation_memory — corrections/glossary
CREATE TABLE IF NOT EXISTS translation_memory (
    id SERIAL PRIMARY KEY,
    source_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    language VARCHAR(10) NOT NULL DEFAULT 'fr',
    category VARCHAR(50) NOT NULL DEFAULT 'ui',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_tm_category CHECK (category IN ('ui', 'chat', 'technical', 'glossary'))
);

-- 3. user_language_preferences — per-user language settings
CREATE TABLE IF NOT EXISTS user_language_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    language VARCHAR(10) NOT NULL DEFAULT 'en',
    auto_detect BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_translations_lang_status ON translations(language, status);
CREATE INDEX IF NOT EXISTS idx_translations_key ON translations(key);
CREATE INDEX IF NOT EXISTS idx_translation_memory_lang ON translation_memory(language);

COMMIT;
