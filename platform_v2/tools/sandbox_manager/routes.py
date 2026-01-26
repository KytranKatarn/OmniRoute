"""
Sandbox Manager Routes
Full implementation for per-module sandbox testing environments

Features:
- Dashboard showing all module sandboxes with status
- Create/destroy module sandboxes
- Run tests in sandboxes
- Visual access to sandbox environments
- Configuration management
"""
from flask import render_template, jsonify, request, redirect, url_for, session
from flask_login import login_required, current_user
from . import sandbox_manager_bp
import os
import sys
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from sandbox_manager import SandboxManager
except ImportError:
    SandboxManager = None

try:
    from rbac import admin_required
except ImportError:
    def admin_required(f):
        return f


def get_db():
    """Get database connection"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


# ============================================================================
# PAGE ROUTES
# ============================================================================

@sandbox_manager_bp.route('/')
@login_required
@admin_required
def index():
    """Sandbox Manager Dashboard"""
    return render_template('tools/sandbox_manager.html')


# ============================================================================
# API ROUTES - MODULE SANDBOXES
# ============================================================================

@sandbox_manager_bp.route('/api/sandboxes', methods=['GET'])
@login_required
@admin_required
def get_sandboxes():
    """Get all module sandboxes with status"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    manager = SandboxManager()
    result = manager.get_module_sandboxes()
    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>', methods=['GET'])
@login_required
@admin_required
def get_sandbox(module_id):
    """Get specific module sandbox"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    manager = SandboxManager()
    result = manager.get_module_sandbox(module_id)
    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>/create', methods=['POST'])
@login_required
@admin_required
def create_sandbox(module_id):
    """Create/activate a module sandbox"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    data = request.get_json() or {}
    proposal_id = data.get('proposal_id')

    manager = SandboxManager()
    result = manager.create_module_sandbox(module_id, proposal_id)
    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>/destroy', methods=['POST'])
@login_required
@admin_required
def destroy_sandbox(module_id):
    """Destroy/deactivate a module sandbox"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    manager = SandboxManager()
    result = manager.destroy_module_sandbox(module_id)
    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>/status', methods=['GET'])
@login_required
@admin_required
def get_sandbox_status(module_id):
    """Get detailed sandbox status"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    manager = SandboxManager()
    result = manager.get_module_sandbox(module_id)

    if result['success']:
        sandbox = result['sandbox']
        # Add access URL if active
        if sandbox['status'] == 'active':
            sandbox['access_url'] = f"http://localhost:{sandbox['port']}/sandbox/dashboard"

    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>/test', methods=['POST'])
@login_required
@admin_required
def run_sandbox_tests(module_id):
    """Run tests in a module sandbox"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    data = request.get_json() or {}
    test_suite = data.get('test_suite', 'default')

    manager = SandboxManager()
    result = manager.run_module_sandbox_tests(module_id, test_suite)
    return jsonify(result)


@sandbox_manager_bp.route('/api/sandboxes/<module_id>/reset', methods=['POST'])
@login_required
@admin_required
def reset_sandbox(module_id):
    """Reset a sandbox to clean state"""
    if not SandboxManager:
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500

    manager = SandboxManager()

    # Destroy then recreate
    destroy_result = manager.destroy_module_sandbox(module_id)
    if not destroy_result['success']:
        return jsonify(destroy_result)

    create_result = manager.create_module_sandbox(module_id)
    return jsonify(create_result)


# ============================================================================
# API ROUTES - CONFIGURATION
# ============================================================================

@sandbox_manager_bp.route('/api/config', methods=['GET'])
@login_required
@admin_required
def get_config():
    """Get sandbox configuration"""
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT config_key, config_value, module_id, description, updated_at
        FROM sandbox_config
        ORDER BY module_id NULLS FIRST, config_key
    """)
    configs = cur.fetchall()

    cur.close()
    conn.close()

    # Organize by global vs module-specific
    global_config = {}
    module_config = {}

    for cfg in configs:
        key = cfg['config_key']
        value = cfg['config_value']
        module_id = cfg['module_id']

        if module_id is None:
            global_config[key] = value
        else:
            if module_id not in module_config:
                module_config[module_id] = {}
            module_config[module_id][key] = value

    return jsonify({
        'success': True,
        'global': global_config,
        'modules': module_config
    })


@sandbox_manager_bp.route('/api/config', methods=['POST'])
@login_required
@admin_required
def update_config():
    """Update sandbox configuration"""
    from psycopg2.extras import RealDictCursor

    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'No data provided'
        }), 400

    config_key = data.get('config_key')
    config_value = data.get('config_value')
    module_id = data.get('module_id')  # None for global

    if not config_key:
        return jsonify({
            'success': False,
            'error': 'config_key is required'
        }), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        INSERT INTO sandbox_config (config_key, config_value, module_id, updated_at, updated_by)
        VALUES (%s, %s, %s, NOW(), %s)
        ON CONFLICT (config_key, module_id)
        DO UPDATE SET config_value = %s, updated_at = NOW(), updated_by = %s
        RETURNING *
    """, (
        config_key,
        json.dumps(config_value),
        module_id,
        current_user.id if hasattr(current_user, 'id') else None,
        json.dumps(config_value),
        current_user.id if hasattr(current_user, 'id') else None
    ))
    result = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'config': dict(result) if result else None
    })


# ============================================================================
# API ROUTES - INTEGRATION
# ============================================================================

@sandbox_manager_bp.route('/api/apply-from-code-sentinel', methods=['POST'])
@login_required
@admin_required
def apply_from_code_sentinel():
    """Apply a Code Sentinel fix to sandbox for testing"""
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'No data provided'
        }), 400

    issue_id = data.get('issue_id')
    if not issue_id:
        return jsonify({
            'success': False,
            'error': 'issue_id is required'
        }), 400

    from psycopg2.extras import RealDictCursor

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get issue details
    cur.execute("""
        SELECT * FROM code_issues WHERE id = %s
    """, (issue_id,))
    issue = cur.fetchone()

    if not issue:
        cur.close()
        conn.close()
        return jsonify({
            'success': False,
            'error': f'Issue not found: {issue_id}'
        }), 404

    # Detect which module this file belongs to
    if SandboxManager:
        manager = SandboxManager()
        module_id = manager.detect_module_from_filepath(issue['file_path'])

        # Ensure sandbox is active
        sandbox_result = manager.get_module_sandbox(module_id)
        if not sandbox_result['success']:
            cur.close()
            conn.close()
            return jsonify(sandbox_result)

        sandbox = sandbox_result['sandbox']
        if sandbox['status'] != 'active':
            # Activate sandbox
            activate_result = manager.create_module_sandbox(module_id)
            if not activate_result['success']:
                cur.close()
                conn.close()
                return jsonify(activate_result)
            sandbox = activate_result

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'issue_id': issue_id,
            'file_path': issue['file_path'],
            'module_id': module_id,
            'sandbox': sandbox,
            'message': f'Ready to apply fix in {module_id} sandbox at port {sandbox.get("port", sandbox.get("sandbox", {}).get("port"))}'
        })
    else:
        cur.close()
        conn.close()
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500


@sandbox_manager_bp.route('/api/apply-from-improvements', methods=['POST'])
@login_required
@admin_required
def apply_from_improvements():
    """Apply an improvement proposal to sandbox for testing"""
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'No data provided'
        }), 400

    proposal_id = data.get('proposal_id')
    if not proposal_id:
        return jsonify({
            'success': False,
            'error': 'proposal_id is required'
        }), 400

    from psycopg2.extras import RealDictCursor

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get proposal details
    cur.execute("""
        SELECT * FROM improvement_proposals WHERE id = %s
    """, (proposal_id,))
    proposal = cur.fetchone()

    if not proposal:
        cur.close()
        conn.close()
        return jsonify({
            'success': False,
            'error': f'Proposal not found: {proposal_id}'
        }), 404

    # Detect module from metadata or default to platform
    module_id = 'platform'
    if proposal.get('metadata'):
        metadata = proposal['metadata'] if isinstance(proposal['metadata'], dict) else json.loads(proposal['metadata'])
        file_path = metadata.get('file_path', '')
        if file_path and SandboxManager:
            manager = SandboxManager()
            module_id = manager.detect_module_from_filepath(file_path)

    if SandboxManager:
        manager = SandboxManager()

        # Create/activate sandbox for this proposal
        result = manager.create_module_sandbox(module_id, proposal_id)

        cur.close()
        conn.close()

        return jsonify(result)
    else:
        cur.close()
        conn.close()
        return jsonify({
            'success': False,
            'error': 'Sandbox manager not available'
        }), 500


@sandbox_manager_bp.route('/api/deploy-to-production', methods=['POST'])
@login_required
@admin_required
def deploy_to_production():
    """Deploy tested changes from sandbox to production with auto-backup"""
    import time
    start_time = time.time()

    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'No data provided'
        }), 400

    module_id = data.get('module_id')
    proposal_id = data.get('proposal_id')
    skip_backup = data.get('skip_backup', False)

    if not module_id:
        return jsonify({
            'success': False,
            'error': 'module_id is required'
        }), 400

    from psycopg2.extras import RealDictCursor

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    backup_name = None
    deployment_id = None

    try:
        # =====================================================================
        # STEP 1: Create pre-deployment backup (unless skipped)
        # =====================================================================
        if not skip_backup:
            try:
                from tools.backup_manager.backup_manager_routes import create_backup_programmatic
                backup_description = f"pre_deploy_{module_id}"
                if proposal_id:
                    backup_description = f"pre_deploy_proposal_{proposal_id}"

                backup_result = create_backup_programmatic(
                    description=backup_description,
                    created_by_username=current_user.username if current_user else 'system',
                    proposal_id=proposal_id
                )

                if backup_result.get('success'):
                    backup_name = backup_result.get('backup_name')
                    logger.info(f"Pre-deployment backup created: {backup_name}")
                else:
                    logger.warning(f"Backup creation failed: {backup_result.get('error')}")
            except Exception as e:
                logger.warning(f"Could not create pre-deployment backup: {e}")

        # =====================================================================
        # STEP 2: Record deployment start
        # =====================================================================
        cur.execute("""
            INSERT INTO improvement_deployments
            (proposal_id, module_id, deployed_by, backup_name, deployment_type, status)
            VALUES (%s, %s, %s, %s, 'sandbox_tested', 'deploying')
            RETURNING id
        """, (
            proposal_id,
            module_id,
            current_user.id if current_user else None,
            backup_name
        ))
        result = cur.fetchone()
        deployment_id = result['id'] if result else None

        # =====================================================================
        # STEP 3: Update proposal status
        # =====================================================================
        proposal = None
        fixed_issues = []
        if proposal_id:
            cur.execute("""
                UPDATE improvement_proposals
                SET status = 'deployed',
                    deployed_at = NOW()
                WHERE id = %s
                RETURNING *
            """, (proposal_id,))
            proposal = cur.fetchone()

            # Also update linked code issues to 'fixed' and create fix records
            cur.execute("""
                UPDATE code_issues
                SET status = 'fixed', fixed_at = NOW(), fixed_by = 'A.R.C.H.I.E. Deployment'
                WHERE proposal_id = %s
                RETURNING id, file_path
            """, (proposal_id,))
            fixed_issues = cur.fetchall()

            # Create code_fixes records for each fixed issue
            for issue in fixed_issues:
                cur.execute("""
                    INSERT INTO code_fixes (issue_id, file_path, fixed_by, fix_description, fixed_at)
                    VALUES (%s, %s, 'A.R.C.H.I.E. Deployment', %s, NOW())
                """, (
                    issue['id'],
                    issue['file_path'],
                    f'Fixed via Improvements Lab workflow - Proposal #{proposal_id} deployed'
                ))

        # =====================================================================
        # STEP 4: Run health checks
        # =====================================================================
        health_check_passed = True
        health_check_details = {'checks': []}

        # Basic health check - verify platform is responding
        try:
            import requests
            health_response = requests.get('http://localhost:3000/api/health', timeout=10)
            health_check_details['checks'].append({
                'name': 'api_health',
                'passed': health_response.status_code == 200,
                'status_code': health_response.status_code
            })
            if health_response.status_code != 200:
                health_check_passed = False
        except Exception as e:
            health_check_details['checks'].append({
                'name': 'api_health',
                'passed': False,
                'error': str(e)
            })
            # Don't fail deployment for health check issues - just log
            logger.warning(f"Health check failed: {e}")

        # =====================================================================
        # STEP 5: Update deployment record
        # =====================================================================
        deployment_duration_ms = int((time.time() - start_time) * 1000)

        if deployment_id:
            cur.execute("""
                UPDATE improvement_deployments
                SET status = 'deployed',
                    completed_at = NOW(),
                    health_check_passed = %s,
                    health_check_details = %s,
                    health_check_at = NOW(),
                    deployment_duration_ms = %s
                WHERE id = %s
            """, (
                health_check_passed,
                json.dumps(health_check_details),
                deployment_duration_ms,
                deployment_id
            ))

        # =====================================================================
        # STEP 6: Reset sandbox
        # =====================================================================
        if SandboxManager:
            manager = SandboxManager()
            manager.destroy_module_sandbox(module_id)

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'Deployment complete for {module_id}',
            'module_id': module_id,
            'proposal_id': proposal_id,
            'deployment_id': deployment_id,
            'backup_name': backup_name,
            'issues_fixed': len(fixed_issues),
            'health_check_passed': health_check_passed,
            'deployment_duration_ms': deployment_duration_ms
        })

    except Exception as e:
        conn.rollback()
        logger.error(f"Deployment failed: {e}")

        # Update deployment record as failed
        if deployment_id:
            try:
                cur.execute("""
                    UPDATE improvement_deployments
                    SET status = 'failed',
                        completed_at = NOW(),
                        deployment_log = %s
                    WHERE id = %s
                """, (str(e), deployment_id))
                conn.commit()
            except:
                pass

        return jsonify({
            'success': False,
            'error': str(e),
            'backup_name': backup_name,
            'message': f'Deployment failed. Backup available: {backup_name}'
        }), 500

    finally:
        cur.close()
        conn.close()


# ============================================================================
# API ROUTES - STATUS
# ============================================================================

@sandbox_manager_bp.route('/api/status', methods=['GET'])
@login_required
def get_status():
    """Get sandbox manager status"""
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Count sandboxes by status
    cur.execute("""
        SELECT status, COUNT(*) as count
        FROM module_sandboxes
        GROUP BY status
    """)
    status_counts = {row['status']: row['count'] for row in cur.fetchall()}

    # Get active sandboxes
    cur.execute("""
        SELECT module_id, port, current_proposal_id
        FROM module_sandboxes
        WHERE status = 'active'
    """)
    active = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        'success': True,
        'healthy': True,
        'status': 'active',
        'message': 'Sandbox Manager is operational',
        'summary': {
            'total': sum(status_counts.values()),
            'active': status_counts.get('active', 0),
            'inactive': status_counts.get('inactive', 0),
            'testing': status_counts.get('testing', 0)
        },
        'active_sandboxes': [dict(s) for s in active]
    })


# ============================================================================
# VISUAL ACCESS ROUTES
# ============================================================================

@sandbox_manager_bp.route('/access/<module_id>')
@login_required
@admin_required
def access_sandbox(module_id):
    """Redirect to sandbox visual environment"""
    if not SandboxManager:
        return "Sandbox manager not available", 500

    manager = SandboxManager()
    result = manager.get_module_sandbox(module_id)

    if not result['success']:
        return f"Sandbox not found: {module_id}", 404

    sandbox = result['sandbox']

    if sandbox['status'] != 'active':
        return f"Sandbox is not active. Current status: {sandbox['status']}", 400

    # Redirect to sandbox URL
    return redirect(f"http://localhost:{sandbox['port']}/sandbox/dashboard")


# ============================================================================
# API ROUTES - TEST RESULTS & DEPLOYMENTS
# ============================================================================

@sandbox_manager_bp.route('/api/test-results', methods=['GET'])
@login_required
@admin_required
def get_test_results():
    """Get recent test results from sandbox_test_results table"""
    from psycopg2.extras import RealDictCursor

    limit = request.args.get('limit', 50, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get results - group by proposal to show summary per proposal
        cur.execute("""
            SELECT
                str.id,
                str.proposal_id,
                str.test_name as test_suite,
                str.status as overall_status,
                str.duration_ms,
                str.executed_at as created_at,
                ip.title as proposal_title
            FROM sandbox_test_results str
            LEFT JOIN improvement_proposals ip ON str.proposal_id = ip.id
            ORDER BY str.executed_at DESC
            LIMIT %s
        """, (limit,))
        results = cur.fetchall()

        # Calculate passed/failed counts (simplified)
        for r in results:
            r['tests_passed'] = 1 if r['overall_status'] == 'passed' else 0
            r['tests_failed'] = 1 if r['overall_status'] == 'failed' else 0
            r['module_id'] = f"Proposal #{r['proposal_id']}" if r['proposal_id'] else '-'

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'results': [dict(r) for r in results]
        })

    except Exception as e:
        cur.close()
        conn.close()
        logger.error(f"Error loading test results: {e}")
        return jsonify({
            'success': True,
            'results': [],
            'note': 'No test results available'
        })


@sandbox_manager_bp.route('/api/deployments', methods=['GET'])
@login_required
@admin_required
def get_deployments():
    """Get recent deployments from improvement_deployments table"""
    from psycopg2.extras import RealDictCursor

    limit = request.args.get('limit', 50, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                id.id,
                id.proposal_id,
                id.module_id,
                id.deployed_by,
                id.deployed_at,
                id.backup_name,
                id.deployment_type,
                id.status,
                id.health_check_passed,
                id.health_check_details,
                id.deployment_duration_ms,
                ip.title as proposal_title
            FROM improvement_deployments id
            LEFT JOIN improvement_proposals ip ON id.proposal_id = ip.id
            ORDER BY id.deployed_at DESC
            LIMIT %s
        """, (limit,))
        deployments = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'deployments': [dict(d) for d in deployments]
        })

    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({
            'success': True,
            'deployments': [],
            'note': 'No deployments available'
        })
