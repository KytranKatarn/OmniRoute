#!/bin/bash
set -e

echo "=== A.R.C.H.I.E. Node Entrypoint ==="
echo "DEPLOYMENT_MODE: ${DEPLOYMENT_MODE:-business_node}"
echo "DB_HOST: ${DB_HOST}"
echo "DB_NAME: ${DB_NAME}"

# Wait for database to be ready
echo "Waiting for database..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT:-5432}" -U "${DB_USER:-archie}" -q; do
    echo "  Database not ready, waiting 2s..."
    sleep 2
done
echo "Database is ready."

# Check if schema is already initialized (check for users table)
SCHEMA_EXISTS=$(PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-archie}" -d "${DB_NAME}" -tAc \
    "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='users')")

if [ "$SCHEMA_EXISTS" = "f" ]; then
    echo "=== First boot: Initializing database schema ==="

    # Run initial schema files
    for f in /app/db_init/schema/*.sql; do
        if [ -f "$f" ]; then
            echo "  Running schema: $(basename $f)"
            PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
                -U "${DB_USER:-archie}" -d "${DB_NAME}" -f "$f"
        fi
    done

    # Create migrations tracking table
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
        -U "${DB_USER:-archie}" -d "${DB_NAME}" -c \
        "CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"

    # Run all migrations in order
    for f in $(ls /app/db_init/migrations/*.sql 2>/dev/null | sort); do
        FNAME=$(basename "$f")
        ALREADY=$(PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
            -U "${DB_USER:-archie}" -d "${DB_NAME}" -tAc \
            "SELECT COUNT(*) FROM schema_migrations WHERE filename='${FNAME}'")
        if [ "$ALREADY" = "0" ]; then
            echo "  Running migration: $FNAME"
            PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
                -U "${DB_USER:-archie}" -d "${DB_NAME}" -f "$f" 2>&1 || echo "  WARNING: $FNAME had errors (may be OK if tables exist)"
            PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
                -U "${DB_USER:-archie}" -d "${DB_NAME}" -c \
                "INSERT INTO schema_migrations (filename) VALUES ('${FNAME}') ON CONFLICT DO NOTHING"
        fi
    done

    echo "=== Database initialization complete ==="

    # Create default admin user for the node
    echo "Creating default admin user..."
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
        -U "${DB_USER:-archie}" -d "${DB_NAME}" -c \
        "INSERT INTO users (username, email, password_hash, role, is_active, is_admin)
         VALUES ('admin', 'admin@node.local',
                 '\$2b\$12\$placeholder_hash_change_on_first_login',
                 'admin', true, true)
         ON CONFLICT (username) DO NOTHING"
else
    echo "Database schema already exists, checking for new migrations..."

    # Ensure migrations table exists
    PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
        -U "${DB_USER:-archie}" -d "${DB_NAME}" -c \
        "CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )" 2>/dev/null

    # Run any new migrations
    for f in $(ls /app/db_init/migrations/*.sql 2>/dev/null | sort); do
        FNAME=$(basename "$f")
        ALREADY=$(PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
            -U "${DB_USER:-archie}" -d "${DB_NAME}" -tAc \
            "SELECT COUNT(*) FROM schema_migrations WHERE filename='${FNAME}'" 2>/dev/null || echo "0")
        if [ "$ALREADY" = "0" ]; then
            echo "  Running new migration: $FNAME"
            PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
                -U "${DB_USER:-archie}" -d "${DB_NAME}" -f "$f" 2>&1 || echo "  WARNING: $FNAME had errors"
            PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT:-5432}" \
                -U "${DB_USER:-archie}" -d "${DB_NAME}" -c \
                "INSERT INTO schema_migrations (filename) VALUES ('${FNAME}') ON CONFLICT DO NOTHING"
        fi
    done
fi

echo "=== Starting platform ==="
exec "$@"
