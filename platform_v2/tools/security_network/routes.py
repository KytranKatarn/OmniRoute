"""
Security & Network Routes
=========================
Dashboard for security monitoring, network health, and system status.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os

from . import security_network_bp


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


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


def get_system_health():
    """Get system health metrics"""
    try:
        import psutil
        return {
            'cpu': {'percent': psutil.cpu_percent(interval=0.1)},
            'memory': {'percent': psutil.virtual_memory().percent},
            'disk': {'percent': psutil.disk_usage('/').percent}
        }
    except:
        return {
            'cpu': {'percent': 0},
            'memory': {'percent': 0},
            'disk': {'percent': 0}
        }


@security_network_bp.route('/')
@login_required
@admin_required
def index():
    """Security & Network dashboard"""
    # Get security stats
    failed_logins_24h = 0
    active_sessions = 0

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get failed logins in last 24 hours
        cur.execute("""
            SELECT COUNT(*) as count FROM audit_log
            WHERE action = 'login_failed'
            AND created_at > NOW() - INTERVAL '24 hours'
        """)
        result = cur.fetchone()
        failed_logins_24h = result['count'] if result else 0

        # Get active sessions (users logged in within last hour)
        cur.execute("""
            SELECT COUNT(DISTINCT user_id) as count FROM audit_log
            WHERE action = 'login_success'
            AND created_at > NOW() - INTERVAL '1 hour'
        """)
        result = cur.fetchone()
        active_sessions = result['count'] if result else 0

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error getting security stats: {e}")

    return render_template('tools/security_network.html',
        failed_logins_24h=failed_logins_24h,
        active_sessions=active_sessions,
        system_health=get_system_health()
    )


@security_network_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """API endpoint for security statistics"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Failed logins (24h)
        cur.execute("""
            SELECT COUNT(*) as count FROM audit_log
            WHERE action = 'login_failed'
            AND created_at > NOW() - INTERVAL '24 hours'
        """)
        failed_logins = cur.fetchone()['count']

        # Recent failed login attempts
        cur.execute("""
            SELECT details, created_at
            FROM audit_log
            WHERE action = 'login_failed'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        recent_failures = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'failed_logins_24h': failed_logins,
            'recent_failures': [dict(r) for r in recent_failures],
            'system_health': get_system_health()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@security_network_bp.route('/api/auto-block', methods=['POST'])
@login_required
@admin_required
def auto_block():
    """Auto-block detected threats"""
    # Placeholder for threat blocking logic
    return jsonify({
        'success': True,
        'blocked': 0,
        'message': 'No threats detected'
    })


@security_network_bp.route('/api/audit-log')
@login_required
@admin_required
def audit_log():
    """Get audit log entries"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        action_filter = request.args.get('action', '')

        query = "SELECT * FROM audit_log"
        params = []

        if action_filter:
            query += " WHERE action = %s"
            params.append(action_filter)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        entries = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'entries': [dict(e) for e in entries]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# NETWORK & SECURITY ROUTES - Migrated from admin/routes.py
# ============================================================================

# Import network integration if available
try:
    from network_integration import (
        get_network_overview, check_security_threats, auto_block_threats
    )
    NETWORK_AVAILABLE = True
except ImportError:
    NETWORK_AVAILABLE = False


@security_network_bp.route('/api/network/overview', methods=['GET'])
@login_required
@admin_required
def network_overview():
    """Get network overview"""
    if not NETWORK_AVAILABLE:
        return jsonify({'success': False, 'error': 'Network integration not available'}), 503

    try:
        overview = get_network_overview()
        return jsonify({'success': True, 'data': overview})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@security_network_bp.route('/api/security/threats', methods=['GET'])
@login_required
@admin_required
def security_threats():
    """Get security threats"""
    if not NETWORK_AVAILABLE:
        return jsonify({'success': False, 'error': 'Network integration not available'}), 503

    try:
        threats = check_security_threats()
        return jsonify({'success': True, 'threats': threats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@security_network_bp.route('/api/security/auto-block', methods=['POST'])
@login_required
@admin_required
def security_auto_block():
    """Auto-block detected threats"""
    if not NETWORK_AVAILABLE:
        return jsonify({'success': False, 'error': 'Network integration not available'}), 503

    try:
        blocked = auto_block_threats()
        return jsonify({'success': True, 'blocked': blocked})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================

@security_network_bp.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'healthy': True,
        'module': 'security_network',
        'network_available': NETWORK_AVAILABLE
    })
