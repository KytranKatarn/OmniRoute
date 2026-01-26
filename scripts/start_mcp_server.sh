#!/bin/bash
# A.R.C.H.I.E. MCP Server Startup Script
# Phase 50: AI Integration Hub
#
# Usage: ./start_mcp_server.sh [--debug] [--api-key KEY]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MCP_SERVER_DIR="$PROJECT_ROOT/platform_v2/mcp_server"

# Ensure logs directory exists
mkdir -p "$PROJECT_ROOT/logs"

# Default environment variables
export DB_HOST="${DB_HOST:-localhost}"
export DB_NAME="${DB_NAME:-archie}"
export DB_USER="${DB_USER:-archie}"
export DB_PASSWORD="${DB_PASSWORD:-archie_secure_2024}"
export ARCHIE_PLATFORM_URL="${ARCHIE_PLATFORM_URL:-http://localhost:3000}"

# Parse arguments
DEBUG=""
API_KEY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --api-key)
            API_KEY="--api-key $2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--debug] [--api-key KEY]"
            exit 1
            ;;
    esac
done

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        A.R.C.H.I.E. MCP Server - AI Integration Hub          ║"
echo "║                     Phase 50 v1.0.0                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Starting MCP Server with stdio transport..."
echo "Platform URL: $ARCHIE_PLATFORM_URL"
echo "Database: $DB_HOST/$DB_NAME"
echo ""

# Check if running inside Docker
if [ -f /.dockerenv ]; then
    echo "Running inside Docker container"
    cd /app
    python3 -m mcp_server.server $DEBUG $API_KEY
else
    echo "Running on host system"
    cd "$PROJECT_ROOT/platform_v2"

    # Check Python environment
    if ! command -v python3 &> /dev/null; then
        echo "ERROR: python3 not found"
        exit 1
    fi

    # Run the MCP server
    python3 -m mcp_server.server $DEBUG $API_KEY
fi
