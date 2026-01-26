"""
Test Improvement Workflow Status
Checks the current state of all workflow components and identifies gaps
"""
import sys
import os
from datetime import datetime

# Add paths
sys.path.insert(0, '/mnt/archie_brain')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

print("=" * 80)
print("IMPROVEMENT WORKFLOW STATUS CHECK")
print("=" * 80)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ==============================================================================
# TEST 1: Import all workflow components
# ==============================================================================
print("Test 1: Importing workflow components...")
components_status = {}

# Team Assignment Engine
try:
    from team_assignment_engine import TeamAssignmentEngine
    components_status['team_assignment_engine'] = '✅ Found'
except ImportError as e:
    components_status['team_assignment_engine'] = f'❌ Missing: {e}'

# Code Diff Engine
try:
    from code_diff_engine import CodeDiffEngine
    components_status['code_diff_engine'] = '✅ Found'
except ImportError as e:
    components_status['code_diff_engine'] = f'❌ Missing: {e}'

# Improvement Chat
try:
    from improvement_chat import chat_about_improvements
    components_status['improvement_chat'] = '✅ Found'
except ImportError as e:
    components_status['improvement_chat'] = f'❌ Missing: {e}'

# Workflow Automator
try:
    from workflow_automator import WorkflowAutomator
    components_status['workflow_automator'] = '✅ Found'
except ImportError as e:
    components_status['workflow_automator'] = f'❌ Missing: {e}'

# Escalation Handler
try:
    from escalation_handler import EscalationHandler
    components_status['escalation_handler'] = '✅ Found'
except ImportError as e:
    components_status['escalation_handler'] = f'❌ Missing: {e}'

# Sandbox Manager
try:
    from sandbox_manager import SandboxManager
    components_status['sandbox_manager'] = '✅ Found'
except ImportError as e:
    components_status['sandbox_manager'] = f'❌ Missing: {e}'

# Sandbox Docker
try:
    from sandbox_docker import DockerSandbox
    components_status['sandbox_docker'] = '✅ Found'
except ImportError as e:
    components_status['sandbox_docker'] = f'❌ Missing: {e}'

# Sandbox Schema
try:
    from sandbox_schema import SchemaSandbox
    components_status['sandbox_schema'] = '✅ Found'
except ImportError as e:
    components_status['sandbox_schema'] = f'❌ Missing: {e}'

# Safe Deployment Protocol
try:
    from safe_deployment_protocol import SafeDeploymentProtocol
    components_status['safe_deployment_protocol'] = '✅ Found'
except ImportError as e:
    components_status['safe_deployment_protocol'] = f'❌ Missing: {e}'

# Deployment Decision
try:
    from deployment_decision import DeploymentDecisionEngine
    components_status['deployment_decision'] = '✅ Found'
except ImportError as e:
    components_status['deployment_decision'] = f'❌ Missing: {e}'

# Print results
for component, status in components_status.items():
    print(f"  {component}: {status}")

imported_count = sum(1 for s in components_status.values() if '✅' in s)
total_count = len(components_status)
print(f"\n  Total: {imported_count}/{total_count} components found")
print()

# ==============================================================================
# TEST 2: Check database tables
# ==============================================================================
print("Test 2: Checking database tables...")
try:
    import psycopg2

    conn = psycopg2.connect(
        host='localhost',
        database='archie',
        user='archie',
        password='archie'
    )
    cur = conn.cursor()

    required_tables = [
        'improvement_proposals',
        'improvement_team_assignments',
        'improvement_deployments',
        'improvement_workflow_states',
        'sandbox_instances',
        'notifications'
    ]

    tables_status = {}
    for table in required_tables:
        cur.execute(f"""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema='public' AND table_name='{table}'
        """)
        exists = cur.fetchone()[0] > 0

        if exists:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            tables_status[table] = f'✅ Exists ({count} rows)'
        else:
            tables_status[table] = '❌ Missing'

    for table, status in tables_status.items():
        print(f"  {table}: {status}")

    cur.close()
    conn.close()

    existing_tables = sum(1 for s in tables_status.values() if '✅' in s)
    print(f"\n  Total: {existing_tables}/{len(required_tables)} tables exist")
    print()
except Exception as e:
    print(f"  ❌ Database check failed: {e}")
    print()

# ==============================================================================
# TEST 3: Check integration points
# ==============================================================================
print("Test 3: Checking integration points...")
integration_points = {}

# Check if admin routes have team assignment endpoints
try:
    with open('/mnt/archie_brain/platform_v2/tools/admin/routes.py', 'r') as f:
        admin_routes = f.read()

    if 'team_assignment' in admin_routes:
        integration_points['admin_routes_team_assignment'] = '✅ Integrated'
    else:
        integration_points['admin_routes_team_assignment'] = '❌ Not integrated'

    if 'sandbox' in admin_routes.lower():
        integration_points['admin_routes_sandbox'] = '✅ Integrated'
    else:
        integration_points['admin_routes_sandbox'] = '❌ Not integrated'

    if 'deployment' in admin_routes.lower():
        integration_points['admin_routes_deployment'] = '✅ Integrated'
    else:
        integration_points['admin_routes_deployment'] = '❌ Not integrated'
except Exception as e:
    integration_points['admin_routes'] = f'❌ Error: {e}'

# Check if improvement_chat has enhanced features
try:
    with open('/mnt/archie_brain/ai_bridge/improvement_chat.py', 'r') as f:
        chat_content = f.read()

    if 'diff' in chat_content.lower():
        integration_points['chat_code_diff'] = '✅ Integrated'
    else:
        integration_points['chat_code_diff'] = '❌ Not integrated'

    if 'step' in chat_content.lower() and 'guidance' in chat_content.lower():
        integration_points['chat_step_guidance'] = '✅ Integrated'
    else:
        integration_points['chat_step_guidance'] = '❌ Not integrated'
except Exception as e:
    integration_points['chat'] = f'❌ Error: {e}'

for point, status in integration_points.items():
    print(f"  {point}: {status}")

integrated_count = sum(1 for s in integration_points.values() if '✅' in s)
print(f"\n  Total: {integrated_count}/{len(integration_points)} integration points")
print()

# ==============================================================================
# FINAL SUMMARY
# ==============================================================================
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()
print(f"Components: {imported_count}/{total_count} found")
try:
    print(f"Tables: {existing_tables}/{len(required_tables)} exist")
except:
    print(f"Tables: Unable to check")
print(f"Integrations: {integrated_count}/{len(integration_points)} complete")
print()

# Calculate overall completion
try:
    total_checks = imported_count + existing_tables + integrated_count
    max_checks = total_count + len(required_tables) + len(integration_points)
    completion_percent = (total_checks / max_checks) * 100
    print(f"Overall Completion: {completion_percent:.1f}%")
except:
    print("Overall Completion: Unable to calculate")
print()

# Recommendations
print("=" * 80)
print("NEXT STEPS")
print("=" * 80)
print()

if imported_count < total_count:
    print("❌ Missing components detected")
    print("   → Fix import paths or implement missing modules")
    print()

try:
    if existing_tables < len(required_tables):
        print("❌ Missing database tables")
        print("   → Run migration 005_improvement_workflow_enhancement.sql")
        print()
except:
    pass

if integrated_count < len(integration_points):
    print("❌ Incomplete integrations")
    print("   → Complete API endpoint integrations")
    print()

if imported_count == total_count:
    try:
        if existing_tables == len(required_tables) and integrated_count == len(integration_points):
            print("✅ All components ready!")
            print("   → Ready to test end-to-end workflow")
            print()
    except:
        pass

print("=" * 80)
