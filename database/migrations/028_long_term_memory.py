"""
Migration 028: Long-Term Memory Enhancement
Phase 9: Enhanced memory schema with semantic search

Creates:
- pgvector extension for embeddings
- memory_embeddings table for semantic search
- memory_collections for organizing memories
- memory_associations for linking related memories
- Adds embedding column to knowledge_base
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )

def run_migration():
    """Execute the migration"""
    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Check and install pgvector extension
    print("Checking pgvector extension...")
    has_vector = False
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        print("  pgvector extension installed")
        has_vector = True
    except Exception as e:
        conn.rollback()
        print(f"  Note: pgvector not available: {e}")
        print("  Continuing without vector support (will use REAL[] arrays)")

    # Double-check if vector type is available
    if has_vector:
        try:
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector')")
            has_vector = cur.fetchone()[0]
        except:
            conn.rollback()
            has_vector = False

    # Use appropriate column type
    embedding_type = "vector(1536)" if has_vector else "REAL[]"
    print(f"  Using embedding type: {embedding_type}")

    print("Creating memory_embeddings table...")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            id SERIAL PRIMARY KEY,

            -- Source reference (polymorphic)
            source_type VARCHAR(50) NOT NULL,  -- 'knowledge_base', 'agent_memory', 'long_term_memory', 'conversation'
            source_id INTEGER NOT NULL,

            -- Embedding data
            embedding {embedding_type},
            embedding_model VARCHAR(100) DEFAULT 'nomic-embed-text',
            embedding_dimension INTEGER DEFAULT 1536,

            -- Content snapshot (for display without joins)
            content_preview VARCHAR(500),

            -- Metadata
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),

            UNIQUE(source_type, source_id)
        )
    """)

    print("Creating memory_collections table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_collections (
            id SERIAL PRIMARY KEY,

            name VARCHAR(100) NOT NULL,
            description TEXT,
            collection_type VARCHAR(50) DEFAULT 'manual',  -- 'manual', 'auto', 'smart'

            -- Ownership
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,

            -- Filter criteria for auto collections
            filter_criteria JSONB,  -- {"memory_type": "skill", "min_importance": 0.7}

            -- Metadata
            icon VARCHAR(50),
            color VARCHAR(20),
            is_pinned BOOLEAN DEFAULT FALSE,
            is_private BOOLEAN DEFAULT FALSE,

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating memory_collection_items table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_collection_items (
            id SERIAL PRIMARY KEY,

            collection_id INTEGER REFERENCES memory_collections(id) ON DELETE CASCADE,

            -- Polymorphic reference to memory
            memory_type VARCHAR(50) NOT NULL,  -- 'knowledge_base', 'agent_memory', 'long_term_memory'
            memory_id INTEGER NOT NULL,

            -- Item metadata
            position INTEGER DEFAULT 0,
            notes TEXT,
            added_by INTEGER REFERENCES users(id),

            created_at TIMESTAMP DEFAULT NOW(),

            UNIQUE(collection_id, memory_type, memory_id)
        )
    """)

    print("Creating memory_associations table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_associations (
            id SERIAL PRIMARY KEY,

            -- Source memory
            source_type VARCHAR(50) NOT NULL,
            source_id INTEGER NOT NULL,

            -- Target memory
            target_type VARCHAR(50) NOT NULL,
            target_id INTEGER NOT NULL,

            -- Association metadata
            association_type VARCHAR(50) DEFAULT 'related',  -- 'related', 'contradicts', 'supports', 'extends', 'supersedes'
            strength NUMERIC(3,2) DEFAULT 0.5,  -- 0.0 to 1.0
            is_bidirectional BOOLEAN DEFAULT TRUE,

            -- How association was created
            created_by VARCHAR(50) DEFAULT 'system',  -- 'system', 'user', 'ai', 'embedding_similarity'

            created_at TIMESTAMP DEFAULT NOW(),

            UNIQUE(source_type, source_id, target_type, target_id)
        )
    """)

    print("Creating memory_access_log table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_access_log (
            id SERIAL PRIMARY KEY,

            memory_type VARCHAR(50) NOT NULL,
            memory_id INTEGER NOT NULL,

            access_type VARCHAR(50) DEFAULT 'read',  -- 'read', 'search', 'recall', 'cited'
            accessor_type VARCHAR(50),  -- 'user', 'agent', 'system'
            accessor_id INTEGER,

            context JSONB,  -- {"module": "archie_chat", "query": "..."}

            accessed_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating memory_decay_config table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS memory_decay_config (
            id SERIAL PRIMARY KEY,

            memory_type VARCHAR(50) NOT NULL,

            -- Decay parameters
            decay_enabled BOOLEAN DEFAULT TRUE,
            decay_rate NUMERIC(5,4) DEFAULT 0.01,  -- Importance decrease per day
            minimum_importance NUMERIC(3,2) DEFAULT 0.1,

            -- Reinforcement
            access_boost NUMERIC(3,2) DEFAULT 0.05,  -- Importance increase on access
            max_boost_per_day NUMERIC(3,2) DEFAULT 0.2,

            -- Archival
            archive_threshold NUMERIC(3,2) DEFAULT 0.15,
            archive_after_days INTEGER DEFAULT 90,

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),

            UNIQUE(memory_type)
        )
    """)

    # Add embedding column to knowledge_base if vector available
    if has_vector:
        print("Adding embedding column to knowledge_base...")
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'knowledge_base' AND column_name = 'embedding'
                ) THEN
                    ALTER TABLE knowledge_base ADD COLUMN embedding vector(1536);
                END IF;
            END $$;
        """)

    # Add semantic_score column to agent_memory
    print("Enhancing agent_memory table...")
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agent_memory' AND column_name = 'decay_immunity'
            ) THEN
                ALTER TABLE agent_memory ADD COLUMN decay_immunity BOOLEAN DEFAULT FALSE;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agent_memory' AND column_name = 'reinforcement_count'
            ) THEN
                ALTER TABLE agent_memory ADD COLUMN reinforcement_count INTEGER DEFAULT 0;
            END IF;
        END $$;
    """)

    # Add columns to long_term_memory
    print("Enhancing long_term_memory table...")
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'long_term_memory' AND column_name = 'emotional_valence'
            ) THEN
                ALTER TABLE long_term_memory ADD COLUMN emotional_valence VARCHAR(20);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'long_term_memory' AND column_name = 'source_module'
            ) THEN
                ALTER TABLE long_term_memory ADD COLUMN source_module VARCHAR(100);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'long_term_memory' AND column_name = 'decay_immunity'
            ) THEN
                ALTER TABLE long_term_memory ADD COLUMN decay_immunity BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;
    """)

    print("Creating indexes...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_source ON memory_embeddings(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_memory_collections_user ON memory_collections(user_id);
        CREATE INDEX IF NOT EXISTS idx_memory_collections_agent ON memory_collections(agent_id);
        CREATE INDEX IF NOT EXISTS idx_memory_collection_items_collection ON memory_collection_items(collection_id);
        CREATE INDEX IF NOT EXISTS idx_memory_associations_source ON memory_associations(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_memory_associations_target ON memory_associations(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_memory_access_log_memory ON memory_access_log(memory_type, memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_access_log_time ON memory_access_log(accessed_at DESC);
    """)

    # Create vector index if available
    if has_vector:
        print("Creating vector similarity index...")
        try:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_embeddings_vector
                ON memory_embeddings USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)
        except Exception as e:
            print(f"  Note: Vector index creation failed (may need more data): {e}")

    print("Inserting default decay configurations...")
    cur.execute("""
        INSERT INTO memory_decay_config (memory_type, decay_enabled, decay_rate, minimum_importance)
        VALUES
            ('knowledge_base', TRUE, 0.005, 0.1),
            ('agent_memory', TRUE, 0.01, 0.15),
            ('long_term_memory', TRUE, 0.008, 0.1),
            ('conversation_memory', TRUE, 0.02, 0.05)
        ON CONFLICT (memory_type) DO NOTHING
    """)

    print("Creating memory decay function...")
    cur.execute("""
        CREATE OR REPLACE FUNCTION apply_memory_decay()
        RETURNS INTEGER AS $$
        DECLARE
            updated_count INTEGER := 0;
            config RECORD;
        BEGIN
            -- Decay long_term_memory
            FOR config IN SELECT * FROM memory_decay_config WHERE decay_enabled = TRUE
            LOOP
                IF config.memory_type = 'long_term_memory' THEN
                    UPDATE long_term_memory
                    SET importance_score = GREATEST(
                        config.minimum_importance,
                        importance_score - config.decay_rate
                    )
                    WHERE importance_score > config.minimum_importance
                    AND (decay_immunity IS NULL OR decay_immunity = FALSE)
                    AND last_accessed < NOW() - INTERVAL '1 day';

                    GET DIAGNOSTICS updated_count = ROW_COUNT;
                END IF;

                IF config.memory_type = 'agent_memory' THEN
                    UPDATE agent_memory
                    SET importance_score = GREATEST(
                        config.minimum_importance,
                        importance_score - config.decay_rate
                    )
                    WHERE importance_score > config.minimum_importance
                    AND (decay_immunity IS NULL OR decay_immunity = FALSE)
                    AND last_accessed < NOW() - INTERVAL '1 day';
                END IF;
            END LOOP;

            RETURN updated_count;
        END;
        $$ LANGUAGE plpgsql;
    """)

    print("Creating memory reinforcement function...")
    cur.execute("""
        CREATE OR REPLACE FUNCTION reinforce_memory(
            p_memory_type VARCHAR,
            p_memory_id INTEGER,
            p_boost NUMERIC DEFAULT 0.05
        )
        RETURNS NUMERIC AS $$
        DECLARE
            new_score NUMERIC;
            config RECORD;
        BEGIN
            SELECT * INTO config FROM memory_decay_config WHERE memory_type = p_memory_type;

            IF config IS NULL THEN
                p_boost := 0.05;
            ELSE
                p_boost := LEAST(p_boost, config.max_boost_per_day);
            END IF;

            IF p_memory_type = 'long_term_memory' THEN
                UPDATE long_term_memory
                SET
                    importance_score = LEAST(1.0, COALESCE(importance_score, 0.5) + p_boost),
                    access_count = COALESCE(access_count, 0) + 1,
                    last_accessed = NOW()
                WHERE id = p_memory_id
                RETURNING importance_score INTO new_score;

            ELSIF p_memory_type = 'agent_memory' THEN
                UPDATE agent_memory
                SET
                    importance_score = LEAST(1.0, COALESCE(importance_score, 0.5) + p_boost),
                    access_count = COALESCE(access_count, 0) + 1,
                    last_accessed = NOW(),
                    reinforcement_count = COALESCE(reinforcement_count, 0) + 1
                WHERE id = p_memory_id
                RETURNING importance_score INTO new_score;
            END IF;

            -- Log the access
            INSERT INTO memory_access_log (memory_type, memory_id, access_type, accessor_type)
            VALUES (p_memory_type, p_memory_id, 'recall', 'system');

            RETURN new_score;
        END;
        $$ LANGUAGE plpgsql;
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 028 complete: Long-term memory enhancement")
    return True

def rollback_migration():
    """Rollback the migration"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DROP FUNCTION IF EXISTS reinforce_memory(VARCHAR, INTEGER, NUMERIC) CASCADE")
    cur.execute("DROP FUNCTION IF EXISTS apply_memory_decay() CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_access_log CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_decay_config CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_associations CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_collection_items CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_collections CASCADE")
    cur.execute("DROP TABLE IF EXISTS memory_embeddings CASCADE")

    # Remove added columns
    cur.execute("""
        ALTER TABLE agent_memory DROP COLUMN IF EXISTS decay_immunity;
        ALTER TABLE agent_memory DROP COLUMN IF EXISTS reinforcement_count;
        ALTER TABLE long_term_memory DROP COLUMN IF EXISTS emotional_valence;
        ALTER TABLE long_term_memory DROP COLUMN IF EXISTS source_module;
        ALTER TABLE long_term_memory DROP COLUMN IF EXISTS decay_immunity;
        ALTER TABLE knowledge_base DROP COLUMN IF EXISTS embedding;
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 028 rolled back")
    return True

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback_migration()
    else:
        run_migration()
