"""
Migration 027: Mining Pool Integration Tables
Phase 30: Mining Pool Integration

Creates tables for:
- Resource scheduler configuration
- Resource allocation tracking
- Mining contributors and rewards
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

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

    print("Creating resource_scheduler_config table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS resource_scheduler_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            mode VARCHAR(20) DEFAULT 'balanced',
            ai_weight INTEGER DEFAULT 50,
            mining_weight INTEGER DEFAULT 50,
            gpu_for_mining BOOLEAN DEFAULT TRUE,
            cpu_for_ai BOOLEAN DEFAULT TRUE,
            auto_scale BOOLEAN DEFAULT FALSE,
            peak_hours_mode VARCHAR(20),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT single_config CHECK (id = 1)
        )
    """)

    print("Creating resource_allocation table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS resource_allocation (
            id SERIAL PRIMARY KEY,
            task_type VARCHAR(20) NOT NULL,
            resource_type VARCHAR(20),
            node_id INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,
            task_id VARCHAR(100),
            allocated_at TIMESTAMP DEFAULT NOW(),
            released_at TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)

    print("Creating mining_contributors table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mining_contributors (
            id SERIAL PRIMARY KEY,
            wallet_address VARCHAR(100) UNIQUE NOT NULL,
            display_name VARCHAR(100),
            contributor_type VARCHAR(20) DEFAULT 'miner',

            -- Stats
            total_hashrate_contributed BIGINT DEFAULT 0,
            total_blocks_found INTEGER DEFAULT 0,
            total_rewards_earned DECIMAL(18,8) DEFAULT 0,
            pending_rewards DECIMAL(18,8) DEFAULT 0,

            -- AI Credits (earned through mining contribution)
            ai_credits_earned INTEGER DEFAULT 0,
            ai_credits_used INTEGER DEFAULT 0,

            last_contribution TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    print("Creating contributor_rewards table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contributor_rewards (
            id SERIAL PRIMARY KEY,
            contributor_id INTEGER REFERENCES mining_contributors(id) ON DELETE CASCADE,

            reward_type VARCHAR(20) NOT NULL,
            amount DECIMAL(18,8) NOT NULL,
            ai_credits INTEGER DEFAULT 0,

            block_height INTEGER,
            txid VARCHAR(100),

            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW(),
            paid_at TIMESTAMP
        )
    """)

    print("Creating indexes...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_resource_allocation_active ON resource_allocation(is_active);
        CREATE INDEX IF NOT EXISTS idx_resource_allocation_type ON resource_allocation(task_type);
        CREATE INDEX IF NOT EXISTS idx_mining_contributors_wallet ON mining_contributors(wallet_address);
        CREATE INDEX IF NOT EXISTS idx_mining_contributors_active ON mining_contributors(is_active);
        CREATE INDEX IF NOT EXISTS idx_contributor_rewards_contributor ON contributor_rewards(contributor_id);
        CREATE INDEX IF NOT EXISTS idx_contributor_rewards_status ON contributor_rewards(status);
    """)

    print("Inserting default scheduler config...")
    cur.execute("""
        INSERT INTO resource_scheduler_config (id, mode, ai_weight, mining_weight)
        VALUES (1, 'balanced', 50, 50)
        ON CONFLICT (id) DO NOTHING
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 027 complete: Mining integration tables created")
    return True

def rollback_migration():
    """Rollback the migration"""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS contributor_rewards CASCADE")
    cur.execute("DROP TABLE IF EXISTS mining_contributors CASCADE")
    cur.execute("DROP TABLE IF EXISTS resource_allocation CASCADE")
    cur.execute("DROP TABLE IF EXISTS resource_scheduler_config CASCADE")

    conn.commit()
    cur.close()
    conn.close()

    print("Migration 027 rolled back")
    return True

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback_migration()
    else:
        run_migration()
