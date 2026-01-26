"""
Migration 026: Remote Nodes Infrastructure
Phase 29: A.R.C.H.I.E. Bridge - VPN Remote Nodes

Creates tables for distributed node architecture:
- remote_nodes: Track connected compute nodes
- node_capabilities: What each node can do
- node_heartbeats: Health monitoring history
- node_requests: Load balancing request log
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
    cur = conn.cursor()

    print("Creating remote_nodes table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS remote_nodes (
            id SERIAL PRIMARY KEY,
            node_id VARCHAR(64) UNIQUE NOT NULL,
            node_name VARCHAR(100) NOT NULL,
            description TEXT,

            -- Connection info
            vpn_ip VARCHAR(45),
            public_ip VARCHAR(45),
            hostname VARCHAR(255),
            port INTEGER DEFAULT 11434,

            -- Authentication
            api_key_hash VARCHAR(256),
            registered_by INTEGER REFERENCES users(id),

            -- Status
            status VARCHAR(20) DEFAULT 'offline',
            last_heartbeat TIMESTAMP,
            last_error TEXT,
            error_count INTEGER DEFAULT 0,

            -- Version control
            client_version VARCHAR(20),
            min_required_version VARCHAR(20) DEFAULT '1.0.0',

            -- Capabilities
            gpu_available BOOLEAN DEFAULT FALSE,
            gpu_model VARCHAR(100),
            gpu_vram_gb FLOAT,
            cpu_cores INTEGER,
            ram_gb FLOAT,

            -- Load balancing
            priority INTEGER DEFAULT 10,
            weight INTEGER DEFAULT 100,
            max_concurrent INTEGER DEFAULT 5,
            current_load INTEGER DEFAULT 0,

            -- Stats
            total_requests BIGINT DEFAULT 0,
            successful_requests BIGINT DEFAULT 0,
            failed_requests BIGINT DEFAULT 0,
            avg_latency_ms FLOAT,

            -- Metadata
            tags TEXT[],
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating node_capabilities table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_capabilities (
            id SERIAL PRIMARY KEY,
            node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,

            -- LLM capabilities
            provider VARCHAR(50) NOT NULL,
            model_name VARCHAR(100) NOT NULL,

            -- Performance
            is_available BOOLEAN DEFAULT TRUE,
            avg_tokens_per_sec FLOAT,
            max_context_length INTEGER,

            -- Config
            priority INTEGER DEFAULT 10,

            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),

            UNIQUE(node_id, provider, model_name)
        )
    """)

    print("Creating node_heartbeats table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_heartbeats (
            id SERIAL PRIMARY KEY,
            node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,

            status VARCHAR(20) NOT NULL,
            latency_ms INTEGER,
            cpu_usage FLOAT,
            memory_usage FLOAT,
            gpu_usage FLOAT,
            current_load INTEGER,

            details JSONB,

            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating node_requests table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_requests (
            id SERIAL PRIMARY KEY,
            node_id INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,

            request_type VARCHAR(50),
            model_name VARCHAR(100),

            tokens_in INTEGER,
            tokens_out INTEGER,
            latency_ms INTEGER,

            status VARCHAR(20),
            error_message TEXT,

            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating indexes...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_remote_nodes_status ON remote_nodes(status);
        CREATE INDEX IF NOT EXISTS idx_remote_nodes_active ON remote_nodes(is_active);
        CREATE INDEX IF NOT EXISTS idx_remote_nodes_node_id ON remote_nodes(node_id);
        CREATE INDEX IF NOT EXISTS idx_node_capabilities_node ON node_capabilities(node_id);
        CREATE INDEX IF NOT EXISTS idx_node_capabilities_model ON node_capabilities(model_name);
        CREATE INDEX IF NOT EXISTS idx_node_heartbeats_node ON node_heartbeats(node_id);
        CREATE INDEX IF NOT EXISTS idx_node_heartbeats_time ON node_heartbeats(created_at);
        CREATE INDEX IF NOT EXISTS idx_node_requests_node ON node_requests(node_id);
        CREATE INDEX IF NOT EXISTS idx_node_requests_time ON node_requests(created_at);
    """)

    print("Creating update trigger...")
    cur.execute("""
        CREATE OR REPLACE FUNCTION update_remote_nodes_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_remote_nodes_updated ON remote_nodes;
        CREATE TRIGGER trg_remote_nodes_updated
            BEFORE UPDATE ON remote_nodes
            FOR EACH ROW
            EXECUTE FUNCTION update_remote_nodes_timestamp();
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 026 complete: Remote Nodes infrastructure created")
    return True

def rollback_migration():
    """Rollback the migration"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS node_requests CASCADE")
    cur.execute("DROP TABLE IF EXISTS node_heartbeats CASCADE")
    cur.execute("DROP TABLE IF EXISTS node_capabilities CASCADE")
    cur.execute("DROP TABLE IF EXISTS remote_nodes CASCADE")
    cur.execute("DROP FUNCTION IF EXISTS update_remote_nodes_timestamp() CASCADE")

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 026 rolled back")
    return True

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback_migration()
    else:
        run_migration()
