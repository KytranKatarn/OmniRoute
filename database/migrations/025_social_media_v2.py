#!/usr/bin/env python3
"""
Migration: Social Media Module v2.0
Phase: Social Media OAuth + Posting + Analytics Integration

This migration creates new tables for:
1. Encrypted OAuth token storage (security improvement)
2. Job execution logs (debugging + monitoring)
3. API rate limit tracking (respect platform limits)
4. Platform configuration (OAuth app credentials)

Run: python3 025_social_media_v2.py

Note: Existing tables (social_accounts, social_posts, social_media_queue, etc.)
are preserved - this migration adds supporting infrastructure.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os

# Database connection - support both local and Docker execution
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", "archie_secure_2024"),
}


def get_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG)


def run_migration():
    """Execute the migration"""
    conn = get_connection()
    cur = conn.cursor()

    print("=" * 60)
    print("Social Media v2.0 Migration")
    print("=" * 60)

    try:
        # ================================================================
        # 1. SOCIAL_OAUTH_TOKENS - Encrypted Token Storage
        # ================================================================
        print("\n[1/5] Creating social_oauth_tokens table...")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS social_oauth_tokens (
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
                platform VARCHAR(50) NOT NULL,

                -- Encrypted tokens (Fernet encryption)
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT,

                -- Token metadata
                token_type VARCHAR(50) DEFAULT 'Bearer',
                expires_at TIMESTAMP,
                scopes TEXT[],

                -- Audit fields
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),

                -- One token record per account
                UNIQUE(account_id)
            );

            -- Index for looking up by account
            CREATE INDEX IF NOT EXISTS idx_oauth_tokens_account
                ON social_oauth_tokens(account_id);

            -- Index for finding expiring tokens
            CREATE INDEX IF NOT EXISTS idx_oauth_tokens_expires
                ON social_oauth_tokens(expires_at)
                WHERE expires_at IS NOT NULL;
        """)
        print("   ✓ social_oauth_tokens created")

        # ================================================================
        # 2. SOCIAL_JOB_LOGS - Job Execution History
        # ================================================================
        print("\n[2/5] Creating social_job_logs table...")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS social_job_logs (
                id SERIAL PRIMARY KEY,

                -- Related entities (nullable for flexibility)
                queue_id INTEGER REFERENCES social_media_queue(id) ON DELETE SET NULL,
                post_id INTEGER REFERENCES social_posts(id) ON DELETE SET NULL,
                account_id INTEGER REFERENCES social_accounts(id) ON DELETE SET NULL,

                -- Job details
                job_type VARCHAR(50) NOT NULL,  -- 'post', 'analytics', 'refresh_token'
                status VARCHAR(20) NOT NULL,     -- 'started', 'success', 'failed', 'retry'
                attempt_number INTEGER DEFAULT 1,

                -- Result details
                error_message TEXT,
                error_code VARCHAR(100),
                platform_response JSONB DEFAULT '{}'::jsonb,

                -- Timing
                executed_at TIMESTAMP DEFAULT NOW(),
                duration_ms INTEGER,

                -- Searchable metadata
                metadata JSONB DEFAULT '{}'::jsonb
            );

            -- Index for finding logs by job type
            CREATE INDEX IF NOT EXISTS idx_job_logs_type
                ON social_job_logs(job_type, executed_at DESC);

            -- Index for finding failed jobs
            CREATE INDEX IF NOT EXISTS idx_job_logs_status
                ON social_job_logs(status)
                WHERE status IN ('failed', 'retry');

            -- Index for finding logs by account
            CREATE INDEX IF NOT EXISTS idx_job_logs_account
                ON social_job_logs(account_id, executed_at DESC);

            -- Index for finding logs by post
            CREATE INDEX IF NOT EXISTS idx_job_logs_post
                ON social_job_logs(post_id);
        """)
        print("   ✓ social_job_logs created")

        # ================================================================
        # 3. SOCIAL_API_RATE_LIMITS - Rate Limit Tracking
        # ================================================================
        print("\n[3/5] Creating social_api_rate_limits table...")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS social_api_rate_limits (
                id SERIAL PRIMARY KEY,

                -- Platform and endpoint identification
                platform VARCHAR(50) NOT NULL,
                endpoint VARCHAR(200) NOT NULL,
                account_id INTEGER REFERENCES social_accounts(id) ON DELETE CASCADE,

                -- Current window tracking
                calls_made INTEGER DEFAULT 0,
                limit_max INTEGER NOT NULL,
                window_start TIMESTAMP DEFAULT NOW(),
                window_duration_seconds INTEGER DEFAULT 3600,  -- 1 hour default

                -- For per-day limits (like posting limits)
                daily_calls_made INTEGER DEFAULT 0,
                daily_limit_max INTEGER,
                daily_reset_at TIMESTAMP,

                -- Unique per platform/endpoint/account combo
                UNIQUE(platform, endpoint, account_id)
            );

            -- Index for checking rate limits
            CREATE INDEX IF NOT EXISTS idx_rate_limits_lookup
                ON social_api_rate_limits(platform, endpoint, account_id);
        """)
        print("   ✓ social_api_rate_limits created")

        # ================================================================
        # 4. SOCIAL_PLATFORM_CONFIG - OAuth App Credentials
        # ================================================================
        print("\n[4/5] Creating social_platform_config table...")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS social_platform_config (
                id SERIAL PRIMARY KEY,
                platform VARCHAR(50) UNIQUE NOT NULL,

                -- OAuth credentials (encrypted)
                client_id TEXT,
                client_secret_encrypted TEXT,

                -- OAuth endpoints
                redirect_uri TEXT,
                auth_url TEXT,
                token_url TEXT,

                -- API configuration
                api_version VARCHAR(20),
                api_base_url TEXT,

                -- Rate limits (platform-wide defaults)
                rate_limit_posts_per_day INTEGER DEFAULT 25,
                rate_limit_api_calls_per_hour INTEGER DEFAULT 200,

                -- Feature flags
                enabled BOOLEAN DEFAULT FALSE,
                supports_images BOOLEAN DEFAULT TRUE,
                supports_videos BOOLEAN DEFAULT TRUE,
                supports_stories BOOLEAN DEFAULT FALSE,
                supports_reels BOOLEAN DEFAULT FALSE,

                -- Metadata
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        print("   ✓ social_platform_config created")

        # ================================================================
        # 5. SEED PLATFORM CONFIGURATIONS
        # ================================================================
        print("\n[5/5] Seeding platform configurations...")

        # Instagram configuration
        cur.execute("""
            INSERT INTO social_platform_config (
                platform, api_version, api_base_url,
                rate_limit_posts_per_day, rate_limit_api_calls_per_hour,
                enabled, supports_images, supports_videos, supports_stories, supports_reels,
                auth_url, token_url, notes
            ) VALUES (
                'instagram', 'v18.0', 'https://graph.facebook.com',
                25, 200,
                FALSE, TRUE, TRUE, TRUE, TRUE,
                'https://www.facebook.com/v18.0/dialog/oauth',
                'https://graph.facebook.com/v18.0/oauth/access_token',
                'Instagram via Facebook Graph API. Requires Facebook Developer App.'
            )
            ON CONFLICT (platform) DO UPDATE SET
                api_version = EXCLUDED.api_version,
                api_base_url = EXCLUDED.api_base_url,
                auth_url = EXCLUDED.auth_url,
                token_url = EXCLUDED.token_url,
                updated_at = NOW();
        """)
        print("   ✓ Instagram config seeded")

        # TikTok configuration
        cur.execute("""
            INSERT INTO social_platform_config (
                platform, api_version, api_base_url,
                rate_limit_posts_per_day, rate_limit_api_calls_per_hour,
                enabled, supports_images, supports_videos, supports_stories, supports_reels,
                auth_url, token_url, notes
            ) VALUES (
                'tiktok', 'v2', 'https://open.tiktokapis.com',
                10, 100,
                FALSE, FALSE, TRUE, FALSE, FALSE,
                'https://www.tiktok.com/v2/auth/authorize/',
                'https://open.tiktokapis.com/v2/oauth/token/',
                'TikTok Content API. Videos only (3-60 seconds). Requires TikTok Developer Portal app.'
            )
            ON CONFLICT (platform) DO UPDATE SET
                api_version = EXCLUDED.api_version,
                api_base_url = EXCLUDED.api_base_url,
                auth_url = EXCLUDED.auth_url,
                token_url = EXCLUDED.token_url,
                updated_at = NOW();
        """)
        print("   ✓ TikTok config seeded")

        # Facebook configuration (for future)
        cur.execute("""
            INSERT INTO social_platform_config (
                platform, api_version, api_base_url,
                rate_limit_posts_per_day, rate_limit_api_calls_per_hour,
                enabled, supports_images, supports_videos, supports_stories, supports_reels,
                notes
            ) VALUES (
                'facebook', 'v18.0', 'https://graph.facebook.com',
                50, 200,
                FALSE, TRUE, TRUE, TRUE, TRUE,
                'Facebook Pages API. Requires Facebook Developer App with pages_manage_posts permission.'
            )
            ON CONFLICT (platform) DO UPDATE SET
                api_version = EXCLUDED.api_version,
                updated_at = NOW();
        """)
        print("   ✓ Facebook config seeded")

        # Twitter/X configuration (for future)
        cur.execute("""
            INSERT INTO social_platform_config (
                platform, api_version, api_base_url,
                rate_limit_posts_per_day, rate_limit_api_calls_per_hour,
                enabled, supports_images, supports_videos, supports_stories, supports_reels,
                notes
            ) VALUES (
                'twitter', 'v2', 'https://api.twitter.com',
                100, 300,
                FALSE, TRUE, TRUE, FALSE, FALSE,
                'Twitter API v2. Requires Twitter Developer Portal app with OAuth 2.0.'
            )
            ON CONFLICT (platform) DO UPDATE SET
                api_version = EXCLUDED.api_version,
                updated_at = NOW();
        """)
        print("   ✓ Twitter config seeded")

        # Commit all changes
        conn.commit()

        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)

        # Show summary
        cur.execute("SELECT COUNT(*) FROM social_platform_config")
        config_count = cur.fetchone()[0]
        print(f"\nPlatform configs: {config_count}")

        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name LIKE 'social%'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"Total social tables: {len(tables)}")
        for t in tables:
            print(f"  - {t}")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def rollback_migration():
    """Rollback the migration (for testing)"""
    conn = get_connection()
    cur = conn.cursor()

    print("Rolling back Social Media v2.0 migration...")

    try:
        cur.execute("DROP TABLE IF EXISTS social_oauth_tokens CASCADE")
        cur.execute("DROP TABLE IF EXISTS social_job_logs CASCADE")
        cur.execute("DROP TABLE IF EXISTS social_api_rate_limits CASCADE")
        cur.execute("DROP TABLE IF EXISTS social_platform_config CASCADE")
        conn.commit()
        print("Rollback complete.")
    except Exception as e:
        conn.rollback()
        print(f"Rollback error: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--rollback":
        rollback_migration()
    else:
        run_migration()
