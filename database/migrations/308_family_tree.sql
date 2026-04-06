-- Migration 308: Family Tree module tables
-- Date: 2026-04-06

-- 1. Persons (core entity)
CREATE TABLE IF NOT EXISTS family_persons (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    maiden_name VARCHAR(100),
    gender VARCHAR(20),
    birth_date DATE,
    birth_date_approx BOOLEAN DEFAULT FALSE,
    birth_place VARCHAR(255),
    death_date DATE,
    death_date_approx BOOLEAN DEFAULT FALSE,
    death_place VARCHAR(255),
    notes TEXT,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_type VARCHAR(50) DEFAULT 'user_input',
    avatar_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_persons_user_id ON family_persons (user_id);
CREATE INDEX IF NOT EXISTS idx_family_persons_user_name ON family_persons (user_id, last_name, first_name);

-- 2. Sources
CREATE TABLE IF NOT EXISTS family_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type VARCHAR(100) NOT NULL,
    external_id VARCHAR(255),
    title VARCHAR(500),
    url TEXT,
    citation TEXT,
    retrieved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_family_sources_user_id ON family_sources (user_id);

-- 3. Relationships (persons and sources must exist first)
CREATE TABLE IF NOT EXISTS family_relationships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person_a_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    person_b_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL,
    start_date DATE,
    end_date DATE,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_id INTEGER REFERENCES family_sources(id),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(person_a_id, person_b_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_family_relationships_user_id ON family_relationships (user_id);
CREATE INDEX IF NOT EXISTS idx_family_relationships_person_a ON family_relationships (person_a_id);
CREATE INDEX IF NOT EXISTS idx_family_relationships_person_b ON family_relationships (person_b_id);

-- 4. Person-Source join table
CREATE TABLE IF NOT EXISTS family_person_sources (
    person_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES family_sources(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (person_id, source_id, field_name)
);

-- 5. Documents
CREATE TABLE IF NOT EXISTS family_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(50),
    document_type VARCHAR(100),
    ocr_text TEXT,
    ocr_status VARCHAR(20) DEFAULT 'pending' CHECK (ocr_status IN ('pending', 'processing', 'completed', 'failed')),
    extracted_data JSONB,
    linked_person_id INTEGER REFERENCES family_persons(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_documents_user_id ON family_documents (user_id);
CREATE INDEX IF NOT EXISTS idx_family_documents_ocr_status ON family_documents (ocr_status);

-- 6. Research Queue
CREATE TABLE IF NOT EXISTS family_research_queue (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    person_id INTEGER REFERENCES family_persons(id),
    research_type VARCHAR(100) NOT NULL,
    query_params JSONB,
    status VARCHAR(30) DEFAULT 'queued' CHECK (status IN ('queued', 'searching', 'found_matches', 'reviewed', 'no_results')),
    agent_name VARCHAR(100),
    results JSONB,
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_family_research_queue_user_id ON family_research_queue (user_id);
CREATE INDEX IF NOT EXISTS idx_family_research_queue_status ON family_research_queue (status);

-- 7. Face Embeddings (BYTEA instead of VECTOR to avoid pgvector dependency)
CREATE TABLE IF NOT EXISTS family_face_embeddings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES family_documents(id) ON DELETE CASCADE,
    person_id INTEGER REFERENCES family_persons(id),
    embedding BYTEA,
    bounding_box JSONB,
    cluster_id INTEGER,
    estimated_era VARCHAR(50),
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_face_embeddings_user_id ON family_face_embeddings (user_id);
CREATE INDEX IF NOT EXISTS idx_family_face_embeddings_person_id ON family_face_embeddings (person_id);
CREATE INDEX IF NOT EXISTS idx_family_face_embeddings_user_cluster ON family_face_embeddings (user_id, cluster_id);
