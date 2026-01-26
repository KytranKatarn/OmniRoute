#!/bin/bash
# Deploy Complete Business Agent Ecosystem
# This script deploys token tracking, budget management, and all business agents

set -e  # Exit on error

echo "🚀 Starting A.R.C.H.I.E. Business Agent Deployment..."
echo ""

# Database connection details
DB_HOST=${DB_HOST:-archie_database}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME:-archie}
DB_USER=${DB_USER:-archie}

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo "📦 Running inside Docker container"
    PSQL_CMD="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME"
else
    echo "🐳 Running from host, using Docker exec"
    PSQL_CMD="docker exec -i archie_database psql -U $DB_USER -d $DB_NAME"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  STEP 1: Deploy Token Tracking & Budget Management"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ -f /.dockerenv ]; then
    $PSQL_CMD < /mnt/archie_brain/database/migrations/add_token_tracking_and_budgets.sql
else
    cat /mnt/archie_brain/database/migrations/add_token_tracking_and_budgets.sql | $PSQL_CMD
fi

if [ $? -eq 0 ]; then
    echo "✅ Token tracking and budget management deployed successfully"
else
    echo "❌ Failed to deploy token tracking"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  STEP 2: Deploy Business Agents"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ -f /.dockerenv ]; then
    $PSQL_CMD < /mnt/archie_brain/database/migrations/add_business_agents.sql
else
    cat /mnt/archie_brain/database/migrations/add_business_agents.sql | $PSQL_CMD
fi

if [ $? -eq 0 ]; then
    echo "✅ Business agents deployed successfully"
else
    echo "❌ Failed to deploy business agents"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  STEP 3: Verify Deployment"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Count agents
AGENT_COUNT=$($PSQL_CMD -t -c "SELECT COUNT(*) FROM agents;" | tr -d ' ')
echo "📊 Total agents in system: $AGENT_COUNT"

# Count by department
echo ""
echo "Agents by Department:"
$PSQL_CMD -c "SELECT at.category, COUNT(*) as agent_count FROM agents a JOIN agent_types at ON a.type_id = at.id GROUP BY at.category ORDER BY agent_count DESC;"

echo ""
echo "Budget Status:"
$PSQL_CMD -c "SELECT COUNT(*) as agents_with_budgets, SUM(monthly_budget) as total_monthly_budget FROM agents WHERE monthly_budget IS NOT NULL;"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE! 🎉"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "✅ Token tracking enabled"
echo "✅ Budget management active"
echo "✅ All business agents deployed"
echo ""
echo "Next Steps:"
echo "  1. Configure API keys (.env file):"
echo "     - CLAUDE_API_KEY"
echo "     - OPENAI_API_KEY"
echo "     - GROK_API_KEY"
echo ""
echo "  2. Test agent connections:"
echo "     docker exec archie_app python3 /mnt/archie_brain/scripts/test_agents.py"
echo ""
echo "  3. Access agent dashboard:"
echo "     http://localhost:5000/tools/admin/agents"
echo ""
echo "  4. Monitor costs:"
echo "     docker exec -i archie_database psql -U archie -d archie -c 'SELECT * FROM agent_cost_summary;'"
echo ""
