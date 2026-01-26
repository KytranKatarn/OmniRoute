"""
System Operations Routes
API endpoints for system monitoring and management
"""

from flask import render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor, Json
import os
from datetime import datetime

from . import system_operations_bp
from .system_service import get_system_service


# ============================================================================
# DECORATORS
# ============================================================================

def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not getattr(current_user, 'is_admin', False):
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# HELPERS
# ============================================================================

def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


def audit_log(action_type: str, target: str, details: dict = None, success: bool = True, error_message: str = None):
    """Log system operation to audit table"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO system_operations_audit
            (user_id, action_type, target, details, success, error_message, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            current_user.id if current_user.is_authenticated else None,
            action_type,
            target,
            Json(details) if details else None,
            success,
            error_message,
            request.remote_addr
        ))
        audit_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return audit_id
    except Exception as e:
        print(f"Audit log error: {e}")
        return None


def record_metric(metric_type: str, value: float, details: dict = None):
    """Record a system metric for historical tracking"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO system_metrics_history (metric_type, value, details)
            VALUES (%s, %s, %s)
        """, (metric_type, value, Json(details) if details else None))
        conn.commit()

        # Run cleanup (delete records older than 7 days) - every 100th insert
        import random
        if random.randint(1, 100) == 1:
            cur.execute("SELECT cleanup_old_system_metrics()")
            conn.commit()

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Metric recording error: {e}")


# ============================================================================
# PAGE ROUTES
# ============================================================================

@system_operations_bp.route('/')
@login_required
@admin_required
def index():
    """Main System Operations dashboard"""
    return render_template('tools/system_operations.html')


# ============================================================================
# READ-ONLY API ENDPOINTS
# ============================================================================

@system_operations_bp.route('/api/overview')
@login_required
@admin_required
def api_overview():
    """Get complete system overview"""
    try:
        service = get_system_service()
        data = service.get_overview()

        # Record metrics for history
        record_metric('cpu', data['cpu']['usage_percent'])
        record_metric('memory', data['memory']['usage_percent'])
        if data['gpu']['available']:
            record_metric('gpu', data['gpu']['usage_percent'])

        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@system_operations_bp.route('/api/cpu')
@login_required
@admin_required
def api_cpu():
    """Get CPU details"""
    try:
        service = get_system_service()
        data = service.get_cpu_info()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/memory')
@login_required
@admin_required
def api_memory():
    """Get memory details"""
    try:
        service = get_system_service()
        data = service.get_memory_info()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/disks')
@login_required
@admin_required
def api_disks():
    """Get disk information"""
    try:
        service = get_system_service()
        data = service.get_disk_info()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/processes')
@login_required
@admin_required
def api_processes():
    """Get running processes"""
    try:
        sort_by = request.args.get('sort', 'cpu')
        limit = int(request.args.get('limit', 50))

        service = get_system_service()
        data = service.get_process_list(sort_by=sort_by, limit=limit)
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/services')
@login_required
@admin_required
def api_services():
    """Get systemd services"""
    try:
        filter_type = request.args.get('filter', 'all')

        service = get_system_service()
        data = service.get_services_list(filter_type=filter_type)
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/docker')
@login_required
@admin_required
def api_docker():
    """Get Docker containers"""
    try:
        service = get_system_service()
        data = service.get_docker_containers()
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/network')
@login_required
@admin_required
def api_network():
    """Get network information"""
    try:
        service = get_system_service()
        data = service.get_network_info()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/history')
@login_required
@admin_required
def api_history():
    """Get historical metrics for graphs"""
    try:
        metric_type = request.args.get('type', 'cpu')
        hours = int(request.args.get('hours', 1))

        # Validate hours (max 168 = 7 days)
        hours = min(max(hours, 1), 168)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use interval multiplication instead of string interpolation
        cur.execute("""
            SELECT value, recorded_at
            FROM system_metrics_history
            WHERE metric_type = %s
              AND recorded_at > NOW() - (%s * INTERVAL '1 hour')
            ORDER BY recorded_at ASC
            LIMIT 720
        """, (metric_type, hours))

        data = cur.fetchall()
        cur.close()
        conn.close()

        # Convert to chart format
        labels = [row['recorded_at'].strftime('%H:%M') for row in data]
        values = [float(row['value']) for row in data]

        return jsonify({
            'success': True,
            'data': {
                'labels': labels,
                'values': values,
                'metric_type': metric_type,
                'count': len(values)
            }
        })
    except Exception as e:
        import traceback
        print(f"History API error: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ACTION API ENDPOINTS (Require confirmation)
# ============================================================================

@system_operations_bp.route('/api/process/<int:pid>/kill', methods=['POST'])
@login_required
@admin_required
def api_kill_process(pid):
    """Kill a process"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        signal = data.get('signal', 'SIGTERM')
        service = get_system_service()
        result = service.kill_process(pid, signal)

        # Audit log
        audit_id = audit_log(
            action_type='process_kill',
            target=str(pid),
            details={'signal': signal},
            success=result['success'],
            error_message=result.get('error')
        )

        result['audit_id'] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log('process_kill', str(pid), success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/service/<service_name>/action', methods=['POST'])
@login_required
@admin_required
def api_service_action(service_name):
    """Perform action on a systemd service"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        action = data.get('action', 'restart')
        service = get_system_service()
        result = service.service_action(service_name, action)

        # Audit log
        audit_id = audit_log(
            action_type='service_action',
            target=service_name,
            details={'action': action},
            success=result['success'],
            error_message=result.get('error')
        )

        result['audit_id'] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log('service_action', service_name, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/docker/<container_id>/action', methods=['POST'])
@login_required
@admin_required
def api_docker_action(container_id):
    """Perform action on a Docker container"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        action = data.get('action', 'restart')
        service = get_system_service()
        result = service.docker_action(container_id, action)

        # Audit log
        audit_id = audit_log(
            action_type='docker_action',
            target=container_id,
            details={'action': action},
            success=result['success'],
            error_message=result.get('error')
        )

        result['audit_id'] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log('docker_action', container_id, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/docker/compose', methods=['POST'])
@login_required
@admin_required
def api_docker_compose():
    """Execute docker-compose commands"""
    try:
        data = request.get_json() or {}

        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        action = data.get('action', 'up')
        allowed_actions = ['up', 'down', 'restart', 'pull']
        if action not in allowed_actions:
            return jsonify({'success': False, 'error': f'Invalid action. Allowed: {allowed_actions}'}), 400

        import subprocess
        compose_file = '/mnt/archie_brain/docker-compose.yml'

        cmd_map = {
            'up': ['docker-compose', '-f', compose_file, 'up', '-d'],
            'down': ['docker-compose', '-f', compose_file, 'down'],
            'restart': ['docker-compose', '-f', compose_file, 'restart'],
            'pull': ['docker-compose', '-f', compose_file, 'pull']
        }

        result = subprocess.run(cmd_map[action], capture_output=True, text=True, timeout=120)

        success = result.returncode == 0
        audit_log(
            action_type='docker_compose',
            target=action,
            details={'stdout': result.stdout[:500], 'stderr': result.stderr[:500]},
            success=success,
            error_message=result.stderr if not success else None
        )

        return jsonify({
            'success': success,
            'output': result.stdout,
            'error': result.stderr if not success else None
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Command timed out'}), 500
    except Exception as e:
        audit_log('docker_compose', 'error', success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/docker/<container_id>/logs', methods=['GET'])
@login_required
@admin_required
def api_docker_logs(container_id):
    """Get container logs"""
    try:
        import subprocess
        tail = request.args.get('tail', '100')

        result = subprocess.run(
            ['docker', 'logs', '--tail', tail, container_id],
            capture_output=True, text=True, timeout=30
        )

        # Return as plain text
        from flask import Response
        logs = result.stdout + result.stderr
        return Response(logs, mimetype='text/plain')
    except Exception as e:
        return f"Error fetching logs: {str(e)}", 500


# ============================================================================
# STACK MANAGEMENT ENDPOINTS
# ============================================================================

@system_operations_bp.route('/api/stack/compose', methods=['GET'])
@login_required
@admin_required
def api_get_compose():
    """Get docker-compose.yml content and parse services"""
    try:
        import yaml
        compose_file = '/mnt/archie_brain/docker-compose.yml'

        if not os.path.exists(compose_file):
            return jsonify({'success': False, 'error': 'Compose file not found'}), 404

        # Read file content
        with open(compose_file, 'r') as f:
            content = f.read()

        # Get file modification time
        stat = os.stat(compose_file)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        # Parse services
        services = []
        try:
            parsed = yaml.safe_load(content)
            if parsed and 'services' in parsed:
                # Get running containers to check status
                import subprocess
                result = subprocess.run(
                    ['docker', 'ps', '--format', '{{.Names}}'],
                    capture_output=True, text=True, timeout=10
                )
                running_containers = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()

                for name, config in parsed['services'].items():
                    services.append({
                        'name': name,
                        'image': config.get('image', ''),
                        'running': name in running_containers or f"archie_brain-{name}-1" in running_containers or f"archie_brain_{name}_1" in running_containers
                    })
        except yaml.YAMLError as ye:
            # YAML parse error - still return content but note the error
            pass

        return jsonify({
            'success': True,
            'content': content,
            'modified': modified,
            'services': services,
            'file': compose_file
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/stack/compose', methods=['PUT'])
@login_required
@admin_required
def api_save_compose():
    """Save docker-compose.yml content"""
    try:
        import yaml
        data = request.get_json() or {}
        content = data.get('content', '')

        if not content:
            return jsonify({'success': False, 'error': 'No content provided'}), 400

        compose_file = data.get('file', '/mnt/archie_brain/docker-compose.yml')

        # Security: Only allow specific files to be edited
        allowed_files = [
            '/mnt/archie_brain/docker-compose.yml',
            '/mnt/archie_brain/.env',
            '/mnt/archie_brain/platform_v2/.env'
        ]

        if compose_file not in allowed_files:
            return jsonify({'success': False, 'error': 'File not allowed to be edited'}), 403

        # Validate YAML syntax
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as ye:
            return jsonify({
                'success': False,
                'error': f'Invalid YAML syntax: {str(ye)}'
            }), 400

        # Create backup
        backup_file = f"{compose_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(compose_file):
            import shutil
            shutil.copy2(compose_file, backup_file)

        # Write new content
        with open(compose_file, 'w') as f:
            f.write(content)

        # Audit log
        audit_log(
            action_type='compose_file_edit',
            target=compose_file,
            details={'backup_file': backup_file, 'content_length': len(content)},
            success=True
        )

        return jsonify({
            'success': True,
            'message': 'Compose file saved',
            'backup': backup_file
        })
    except Exception as e:
        audit_log('compose_file_edit', compose_file, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/stack/env', methods=['GET'])
@login_required
@admin_required
def api_get_env():
    """Get environment file content"""
    try:
        filename = request.args.get('file', '.env')

        # Security: Only allow specific env files
        allowed_files = {
            '.env': '/mnt/archie_brain/.env',
            'platform_v2/.env': '/mnt/archie_brain/platform_v2/.env'
        }

        if filename not in allowed_files:
            return jsonify({'success': False, 'error': 'File not allowed'}), 403

        env_file = allowed_files[filename]

        if not os.path.exists(env_file):
            return jsonify({'success': False, 'error': 'File not found'}), 404

        with open(env_file, 'r') as f:
            content = f.read()

        stat = os.stat(env_file)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

        return jsonify({
            'success': True,
            'content': content,
            'modified': modified,
            'file': env_file
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/stack/env', methods=['PUT'])
@login_required
@admin_required
def api_save_env():
    """Save environment file content"""
    try:
        data = request.get_json() or {}
        content = data.get('content', '')
        filename = data.get('file', '')

        # Security: Only allow specific env files
        allowed_files = [
            '/mnt/archie_brain/.env',
            '/mnt/archie_brain/platform_v2/.env'
        ]

        if filename not in allowed_files:
            return jsonify({'success': False, 'error': 'File not allowed to be edited'}), 403

        # Create backup
        backup_file = f"{filename}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(filename):
            import shutil
            shutil.copy2(filename, backup_file)

        # Write new content
        with open(filename, 'w') as f:
            f.write(content)

        # Audit log
        audit_log(
            action_type='env_file_edit',
            target=filename,
            details={'backup_file': backup_file},
            success=True
        )

        return jsonify({
            'success': True,
            'message': 'Environment file saved',
            'backup': backup_file
        })
    except Exception as e:
        audit_log('env_file_edit', filename, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/disk/<path:device>/mount', methods=['POST'])
@login_required
@admin_required
def api_mount_disk(device):
    """Mount a disk"""
    try:
        data = request.get_json() or {}

        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        mountpoint = data.get('mountpoint')
        if not mountpoint:
            return jsonify({'success': False, 'error': 'Mountpoint required'}), 400

        # Execute mount
        import subprocess
        result = subprocess.run(
            ['sudo', 'mount', f'/dev/{device}', mountpoint],
            capture_output=True, text=True, timeout=30
        )

        success = result.returncode == 0
        audit_log(
            action_type='disk_mount',
            target=device,
            details={'mountpoint': mountpoint},
            success=success,
            error_message=result.stderr if not success else None
        )

        if success:
            return jsonify({'success': True, 'message': f'Mounted /dev/{device} at {mountpoint}'})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500

    except Exception as e:
        audit_log('disk_mount', device, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/disk/<path:device>/unmount', methods=['POST'])
@login_required
@admin_required
def api_unmount_disk(device):
    """Unmount a disk"""
    try:
        data = request.get_json() or {}

        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        # Execute unmount
        import subprocess
        result = subprocess.run(
            ['sudo', 'umount', f'/dev/{device}'],
            capture_output=True, text=True, timeout=30
        )

        success = result.returncode == 0
        audit_log(
            action_type='disk_unmount',
            target=device,
            success=success,
            error_message=result.stderr if not success else None
        )

        if success:
            return jsonify({'success': True, 'message': f'Unmounted /dev/{device}'})
        else:
            return jsonify({'success': False, 'error': result.stderr}), 500

    except Exception as e:
        audit_log('disk_unmount', device, success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# LVM EXTEND ENDPOINT
# ============================================================================

@system_operations_bp.route('/api/lvm/<vg_name>/<lv_name>/extend', methods=['POST'])
@login_required
@admin_required
def api_extend_lvm(vg_name, lv_name):
    """Extend an LVM logical volume"""
    try:
        data = request.get_json() or {}

        # Require confirmation
        if not data.get('confirm'):
            return jsonify({
                'success': False,
                'error': 'Confirmation required',
                'requires_confirm': True
            }), 400

        size_gb = data.get('size_gb')
        extend_all = data.get('extend_all', False)

        if not size_gb and not extend_all:
            return jsonify({
                'success': False,
                'error': 'Must specify size_gb or extend_all'
            }), 400

        service = get_system_service()
        result = service.extend_lvm(vg_name, lv_name, size_gb=size_gb, extend_all=extend_all)

        # Audit log
        audit_id = audit_log(
            action_type='lvm_extend',
            target=f'{vg_name}/{lv_name}',
            details={'size_gb': size_gb, 'extend_all': extend_all},
            success=result['success'],
            error_message=result.get('error')
        )

        result['audit_id'] = audit_id
        return jsonify(result)
    except Exception as e:
        audit_log('lvm_extend', f'{vg_name}/{lv_name}', success=False, error_message=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@system_operations_bp.route('/api/lvm')
@login_required
@admin_required
def api_lvm_info():
    """Get LVM information"""
    try:
        service = get_system_service()
        data = service._get_lvm_info()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# AUDIT LOG ENDPOINT
# ============================================================================

@system_operations_bp.route('/api/audit-log')
@login_required
@admin_required
def api_audit_log():
    """Get system operations audit log"""
    try:
        limit = int(request.args.get('limit', 50))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                soa.id,
                soa.action_type,
                soa.target,
                soa.details,
                soa.success,
                soa.error_message,
                soa.ip_address,
                soa.created_at,
                u.username
            FROM system_operations_audit soa
            LEFT JOIN users u ON soa.user_id = u.id
            ORDER BY soa.created_at DESC
            LIMIT %s
        """, (limit,))

        data = cur.fetchall()
        cur.close()
        conn.close()

        # Convert datetime objects
        for row in data:
            if row['created_at']:
                row['created_at'] = row['created_at'].isoformat()

        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# HOST DATA ENDPOINT
# ============================================================================

@system_operations_bp.route('/api/host-data')
@login_required
@admin_required
def api_host_data():
    """Get host system data from host monitor"""
    try:
        import json as json_lib
        host_data_file = '/mnt/archie_brain/host_monitor_data.json'

        if not os.path.exists(host_data_file):
            return jsonify({
                'success': False,
                'error': 'Host monitor data not available',
                'hint': 'Run scripts/host_monitor.py on the host machine'
            })

        # Check if data is stale (older than 5 minutes)
        file_age = os.path.getmtime(host_data_file)
        import time
        age_seconds = time.time() - file_age

        with open(host_data_file, 'r') as f:
            data = json_lib.load(f)

        data['data_age_seconds'] = int(age_seconds)
        data['is_stale'] = age_seconds > 300  # 5 minutes

        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================

@system_operations_bp.route('/health')
def health_check():
    """Health check endpoint (no auth required)"""
    return jsonify({
        'healthy': True,
        'module': 'system_operations'
    })
