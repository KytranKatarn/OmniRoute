"""
Account Center Routes
=====================
API routes for account CRUD, permissions, subscriptions, sessions,
API keys, bulk operations, and activity tracking.
"""

from flask import render_template, jsonify, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from functools import wraps
from werkzeug.security import generate_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import secrets
import hashlib
import json
import csv
import io
from datetime import datetime, timedelta

from . import account_center_bp


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


def log_activity(user_id, action, module='account_center', details=None, resource_type=None, resource_id=None):
    """Log user activity"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_activity_log
            (user_id, username, action, module, resource_type, resource_id, details, ip_address, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            current_user.username if current_user.is_authenticated else None,
            action,
            module,
            resource_type,
            resource_id,
            psycopg2.extras.Json(details) if details else None,
            request.remote_addr,
            request.headers.get('User-Agent', '')[:500]
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error logging activity: {e}")


# ============================================================================
# PAGE ROUTES
# ============================================================================

@account_center_bp.route('/')
@login_required
@admin_required
def index():
    """User Management dashboard"""
    stats = {
        'total_users': 0,
        'admins': 0,
        'premium': 0,
        'free': 0,
        'active_today': 0
    }

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user counts
        cur.execute("SELECT COUNT(*) as count FROM users WHERE is_active = true")
        stats['total_users'] = cur.fetchone()['count']

        cur.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = true")
        stats['admins'] = cur.fetchone()['count']

        cur.execute("SELECT COUNT(*) as count FROM users WHERE subscription_tier IN ('pro', 'business', 'enterprise')")
        stats['premium'] = cur.fetchone()['count']

        cur.execute("SELECT COUNT(*) as count FROM users WHERE subscription_tier = 'free' OR subscription_tier IS NULL")
        stats['free'] = cur.fetchone()['count']

        cur.execute("""
            SELECT COUNT(DISTINCT user_id) as count FROM user_activity_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """)
        stats['active_today'] = cur.fetchone()['count']

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error getting stats: {e}")

    return render_template('tools/account_center.html', stats=stats)


# ============================================================================
# USER CRUD API
# ============================================================================

@account_center_bp.route('/api/users')
@login_required
@admin_required
def api_list_users():
    """List all users with optional filtering"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get filter parameters
        role_filter = request.args.get('role', '')
        tier_filter = request.args.get('tier', '')
        search = request.args.get('search', '')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        # Build query
        query = """
            SELECT id, username, email, role, subscription_tier, subscription_status,
                   is_admin, is_active, created_at, last_login
            FROM users
            WHERE 1=1
        """
        params = []

        if role_filter:
            query += " AND role = %s"
            params.append(role_filter)

        if tier_filter:
            query += " AND subscription_tier = %s"
            params.append(tier_filter)

        if search:
            query += " AND (username ILIKE %s OR email ILIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        users = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) as count FROM users WHERE 1=1"
        count_params = []

        if role_filter:
            count_query += " AND role = %s"
            count_params.append(role_filter)
        if tier_filter:
            count_query += " AND subscription_tier = %s"
            count_params.append(tier_filter)
        if search:
            count_query += " AND (username ILIKE %s OR email ILIKE %s)"
            count_params.extend([f'%{search}%', f'%{search}%'])

        cur.execute(count_query, count_params)
        total = cur.fetchone()['count']

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'users': [dict(u) for u in users],
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>')
@login_required
@admin_required
def api_get_user(user_id):
    """Get single user details"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, username, email, role, subscription_tier, subscription_status,
                   is_admin, is_active, created_at, last_login, last_login_ip,
                   preferences, metadata
            FROM users WHERE id = %s
        """, (user_id,))
        user = cur.fetchone()

        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        # Get user stats
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM conversations WHERE user_id = %s) as conversations,
                (SELECT COUNT(*) FROM app_builder_projects WHERE user_id = %s) as app_projects,
                (SELECT COUNT(*) FROM website_builder_projects WHERE user_id = %s) as website_projects
        """, (user_id, user_id, user_id))
        stats = cur.fetchone()

        # Get recent activity
        cur.execute("""
            SELECT action, module, created_at
            FROM user_activity_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (user_id,))
        recent_activity = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'user': dict(user),
            'stats': dict(stats) if stats else {},
            'recent_activity': [dict(a) for a in recent_activity]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users', methods=['POST'])
@login_required
@admin_required
def api_create_user():
    """Create a new user"""
    try:
        data = request.get_json()

        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'user')
        subscription_tier = data.get('subscription_tier', 'free')
        is_admin = data.get('is_admin', False)

        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password required'}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if username exists
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Username already exists'}), 400

        # Create user
        password_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, subscription_tier, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (username, email, password_hash, role, subscription_tier, is_admin))

        new_id = cur.fetchone()['id']
        conn.commit()

        log_activity(current_user.id, 'user_created', details={'new_user_id': new_id, 'username': username})

        cur.close()
        conn.close()

        return jsonify({'success': True, 'user_id': new_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_user(user_id):
    """Update user details"""
    try:
        data = request.get_json()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build update query
        updates = []
        params = []

        if 'email' in data:
            updates.append("email = %s")
            params.append(data['email'])
        if 'role' in data:
            updates.append("role = %s")
            params.append(data['role'])
        if 'subscription_tier' in data:
            updates.append("subscription_tier = %s")
            params.append(data['subscription_tier'])
        if 'is_admin' in data:
            updates.append("is_admin = %s")
            params.append(data['is_admin'])
        if 'is_active' in data:
            updates.append("is_active = %s")
            params.append(data['is_active'])
        if 'password' in data and data['password']:
            updates.append("password_hash = %s")
            params.append(generate_password_hash(data['password']))

        if not updates:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        params.append(user_id)
        cur.execute(f"""
            UPDATE users SET {', '.join(updates)}
            WHERE id = %s
        """, params)

        conn.commit()

        log_activity(current_user.id, 'user_updated', details={'target_user_id': user_id, 'fields': list(data.keys())})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_user(user_id):
    """Delete a user (soft delete - set inactive)"""
    try:
        # Prevent deleting yourself
        if user_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot delete your own account'}), 400

        conn = get_db()
        cur = conn.cursor()

        cur.execute("UPDATE users SET is_active = false WHERE id = %s", (user_id,))
        conn.commit()

        log_activity(current_user.id, 'user_deleted', details={'target_user_id': user_id})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>/password', methods=['POST'])
@login_required
@admin_required
def api_reset_password(user_id):
    """Reset user password (migrated from admin routes)"""
    try:
        data = request.get_json()
        new_password = data.get('password') if data else None

        if not new_password or len(new_password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400

        conn = get_db()
        cur = conn.cursor()

        password_hash = generate_password_hash(new_password)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))

        conn.commit()

        log_activity(current_user.id, 'password_reset', details={'target_user_id': user_id})

        cur.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Password reset successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROLES & PERMISSIONS API
# ============================================================================

@account_center_bp.route('/api/roles')
@login_required
@admin_required
def api_list_roles():
    """List available roles"""
    roles = [
        {'name': 'PUBLIC', 'level': 0, 'description': 'Not logged in'},
        {'name': 'USER', 'level': 10, 'description': 'Basic authenticated user'},
        {'name': 'PREMIUM', 'level': 20, 'description': 'Paid subscriber'},
        {'name': 'ADMIN', 'level': 90, 'description': 'Administrator'},
        {'name': 'SUPER_ADMIN', 'level': 100, 'description': 'System owner'}
    ]
    return jsonify({'success': True, 'roles': roles})


@account_center_bp.route('/api/permissions')
@login_required
@admin_required
def api_list_permissions():
    """List available permissions"""
    try:
        from rbac import Permission, ROLE_PERMISSIONS, Role

        permissions = []
        for perm in Permission:
            permissions.append({
                'value': perm.value,
                'name': perm.name,
                'roles': [role.name for role, perms in ROLE_PERMISSIONS.items() if perm in perms]
            })

        return jsonify({'success': True, 'permissions': permissions})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>/role', methods=['PUT'])
@login_required
@admin_required
def api_update_user_role(user_id):
    """Update user's role"""
    try:
        data = request.get_json()
        role = data.get('role', 'user')
        is_admin = role in ['ADMIN', 'SUPER_ADMIN']

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users SET role = %s, is_admin = %s WHERE id = %s
        """, (role.lower(), is_admin, user_id))

        conn.commit()

        log_activity(current_user.id, 'role_changed', details={'target_user_id': user_id, 'new_role': role})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# SUBSCRIPTIONS API
# ============================================================================

@account_center_bp.route('/api/tiers')
@login_required
@admin_required
def api_list_tiers():
    """List subscription tiers"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, name, display_name, description, price_monthly, price_yearly,
                   features, limits, role_level, color, enabled
            FROM subscription_tiers
            ORDER BY sort_order
        """)
        tiers = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({'success': True, 'tiers': [dict(t) for t in tiers]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>/subscription', methods=['PUT'])
@login_required
@admin_required
def api_update_subscription(user_id):
    """Update user's subscription tier"""
    try:
        data = request.get_json()
        tier = data.get('tier', 'free')
        status = data.get('status', 'active')

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE users SET subscription_tier = %s, subscription_status = %s WHERE id = %s
        """, (tier, status, user_id))

        conn.commit()

        log_activity(current_user.id, 'subscription_changed',
                    details={'target_user_id': user_id, 'new_tier': tier, 'status': status})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/users/<int:user_id>/usage')
@login_required
@admin_required
def api_get_usage(user_id):
    """Get user's usage statistics against limits"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's tier and limits
        cur.execute("""
            SELECT u.subscription_tier, t.limits
            FROM users u
            LEFT JOIN subscription_tiers t ON t.name = u.subscription_tier
            WHERE u.id = %s
        """, (user_id,))
        result = cur.fetchone()

        tier = result['subscription_tier'] if result else 'free'
        limits = result['limits'] if result and result['limits'] else {}

        # Get actual usage
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM app_builder_projects WHERE user_id = %s) as app_projects,
                (SELECT COUNT(*) FROM website_builder_projects WHERE user_id = %s) as website_projects,
                (SELECT COUNT(*) FROM token_usage_log WHERE user_id = %s AND created_at > NOW() - INTERVAL '1 day') as api_calls_today
        """, (user_id, user_id, user_id))
        usage = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'tier': tier,
            'limits': limits,
            'usage': dict(usage) if usage else {}
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ACTIVITY API
# ============================================================================

@account_center_bp.route('/api/activity')
@login_required
@admin_required
def api_get_activity():
    """Get activity log"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get filter parameters
        user_id = request.args.get('user_id', type=int)
        module = request.args.get('module', '')
        action = request.args.get('action', '')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        query = """
            SELECT a.*, u.username as user_name
            FROM user_activity_log a
            LEFT JOIN users u ON a.user_id = u.id
            WHERE 1=1
        """
        params = []

        if user_id:
            query += " AND a.user_id = %s"
            params.append(user_id)
        if module:
            query += " AND a.module = %s"
            params.append(module)
        if action:
            query += " AND a.action = %s"
            params.append(action)

        query += " ORDER BY a.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        activities = cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) as count FROM user_activity_log WHERE 1=1"
        count_params = []
        if user_id:
            count_query += " AND user_id = %s"
            count_params.append(user_id)
        if module:
            count_query += " AND module = %s"
            count_params.append(module)

        cur.execute(count_query, count_params)
        total = cur.fetchone()['count']

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'activities': [dict(a) for a in activities],
            'total': total
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/activity/modules')
@login_required
@admin_required
def api_get_activity_modules():
    """Get list of modules with activity"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT module, COUNT(*) as count
            FROM user_activity_log
            WHERE module IS NOT NULL
            GROUP BY module
            ORDER BY count DESC
        """)
        modules = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({'success': True, 'modules': [dict(m) for m in modules]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/activity/summary')
@login_required
@admin_required
def api_activity_summary():
    """Get activity summary for dashboard"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Last 7 days activity by day
        cur.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM user_activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        by_day = cur.fetchall()

        # Top actions
        cur.execute("""
            SELECT action, COUNT(*) as count
            FROM user_activity_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY action
            ORDER BY count DESC
            LIMIT 10
        """)
        top_actions = cur.fetchall()

        # Most active users
        cur.execute("""
            SELECT u.username, COUNT(*) as count
            FROM user_activity_log a
            JOIN users u ON a.user_id = u.id
            WHERE a.created_at > NOW() - INTERVAL '24 hours'
            GROUP BY u.username
            ORDER BY count DESC
            LIMIT 5
        """)
        top_users = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'by_day': [dict(d) for d in by_day],
            'top_actions': [dict(a) for a in top_actions],
            'top_users': [dict(u) for u in top_users]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# SESSION MANAGEMENT API
# ============================================================================

@account_center_bp.route('/api/sessions')
@login_required
@admin_required
def api_list_sessions():
    """List all active sessions"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        user_id = request.args.get('user_id', type=int)
        search = request.args.get('search', '')

        query = """
            SELECT s.*, u.username
            FROM active_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE 1=1
        """
        params = []

        if user_id:
            query += " AND s.user_id = %s"
            params.append(user_id)
        if search:
            query += " AND s.ip_address ILIKE %s"
            params.append(f'%{search}%')

        query += " ORDER BY s.last_activity DESC LIMIT 100"

        cur.execute(query, params)
        sessions = cur.fetchall()

        # Get users for filter dropdown
        cur.execute("""
            SELECT DISTINCT u.id, u.username
            FROM active_sessions s
            JOIN users u ON s.user_id = u.id
            ORDER BY u.username
        """)
        users = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'sessions': [dict(s) for s in sessions],
            'users': [dict(u) for u in users]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/sessions/<int:session_id>', methods=['DELETE'])
@login_required
@admin_required
def api_revoke_session(session_id):
    """Revoke a specific session"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM active_sessions WHERE id = %s", (session_id,))
        conn.commit()

        log_activity(current_user.id, 'session_revoked', details={'session_id': session_id})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/sessions/expired', methods=['DELETE'])
@login_required
@admin_required
def api_revoke_expired_sessions():
    """Revoke all expired sessions"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM active_sessions
            WHERE expires_at IS NOT NULL AND expires_at < NOW()
            RETURNING id
        """)
        deleted = cur.fetchall()
        count = len(deleted)
        conn.commit()

        log_activity(current_user.id, 'expired_sessions_revoked', details={'count': count})

        cur.close()
        conn.close()

        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# API KEYS MANAGEMENT
# ============================================================================

@account_center_bp.route('/api/api-keys')
@login_required
@admin_required
def api_list_api_keys():
    """List all API keys"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        user_id = request.args.get('user_id', type=int)
        status = request.args.get('status', '')

        query = """
            SELECT k.*, u.username
            FROM mcp_api_keys k
            LEFT JOIN users u ON k.user_id = u.id
            WHERE 1=1
        """
        params = []

        if user_id:
            query += " AND k.user_id = %s"
            params.append(user_id)
        if status == 'active':
            query += " AND k.is_active = true AND (k.expires_at IS NULL OR k.expires_at > NOW())"
        elif status == 'inactive':
            query += " AND k.is_active = false"
        elif status == 'expired':
            query += " AND k.expires_at IS NOT NULL AND k.expires_at <= NOW()"

        query += " ORDER BY k.created_at DESC"

        cur.execute(query, params)
        keys = cur.fetchall()

        # Get users for filter dropdown
        cur.execute("SELECT id, username FROM users WHERE is_active = true ORDER BY username")
        users = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'keys': [dict(k) for k in keys],
            'users': [dict(u) for u in users]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/api-keys', methods=['POST'])
@login_required
@admin_required
def api_create_api_key():
    """Generate a new API key"""
    try:
        data = request.get_json()

        user_id = data.get('user_id')
        name = data.get('name', '').strip()
        description = data.get('description', '')
        permissions = data.get('permissions', ['read'])
        expires_in_days = data.get('expires_in_days')
        rate_limit = data.get('rate_limit_per_hour', 1000)

        if not user_id or not name:
            return jsonify({'success': False, 'error': 'User and name are required'}), 400

        # Generate a secure API key
        raw_key = secrets.token_urlsafe(32)
        key_prefix = 'arch_' + raw_key[:6]
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now() + timedelta(days=int(expires_in_days))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO mcp_api_keys
            (user_id, key_hash, key_prefix, name, description, permissions,
             rate_limit_per_hour, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            user_id, key_hash, key_prefix, name, description,
            psycopg2.extras.Json(permissions), rate_limit, expires_at
        ))

        new_id = cur.fetchone()['id']
        conn.commit()

        log_activity(current_user.id, 'api_key_created',
                     details={'key_id': new_id, 'user_id': user_id, 'name': name})

        cur.close()
        conn.close()

        # Return the full key only once - it won't be retrievable later
        full_key = f"arch_{raw_key}"

        return jsonify({
            'success': True,
            'key_id': new_id,
            'api_key': full_key,
            'key_prefix': key_prefix
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/api-keys/<int:key_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_api_key(key_id):
    """Update an API key (activate/deactivate)"""
    try:
        data = request.get_json()

        conn = get_db()
        cur = conn.cursor()

        if 'is_active' in data:
            cur.execute("UPDATE mcp_api_keys SET is_active = %s WHERE id = %s",
                        (data['is_active'], key_id))

        conn.commit()

        log_activity(current_user.id, 'api_key_updated',
                     details={'key_id': key_id, 'changes': list(data.keys())})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/api-keys/<int:key_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_api_key(key_id):
    """Delete an API key"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM mcp_api_keys WHERE id = %s", (key_id,))
        conn.commit()

        log_activity(current_user.id, 'api_key_deleted', details={'key_id': key_id})

        cur.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# BULK OPERATIONS API
# ============================================================================

@account_center_bp.route('/api/bulk/export')
@login_required
@admin_required
def api_bulk_export():
    """Export users to CSV or JSON"""
    try:
        format_type = request.args.get('format', 'csv')
        scope = request.args.get('scope', 'all')

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT id, username, email, role, subscription_tier, subscription_status,
                   is_admin, is_active, created_at, last_login
            FROM users
            WHERE 1=1
        """

        if scope == 'active':
            query += " AND is_active = true"
        elif scope == 'admins':
            query += " AND is_admin = true"
        elif scope == 'premium':
            query += " AND subscription_tier IN ('pro', 'business', 'enterprise')"

        query += " ORDER BY created_at DESC"

        cur.execute(query)
        users = cur.fetchall()

        cur.close()
        conn.close()

        log_activity(current_user.id, 'users_exported',
                     details={'format': format_type, 'scope': scope, 'count': len(users)})

        if format_type == 'json':
            # Convert datetime objects to ISO format strings
            for user in users:
                for key in ['created_at', 'last_login']:
                    if user[key]:
                        user[key] = user[key].isoformat()
            return Response(
                json.dumps([dict(u) for u in users], indent=2),
                mimetype='application/json',
                headers={'Content-Disposition': 'attachment; filename=users_export.json'}
            )
        else:
            # CSV export
            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            headers = ['id', 'username', 'email', 'role', 'subscription_tier',
                       'subscription_status', 'is_admin', 'is_active', 'created_at', 'last_login']
            writer.writerow(headers)

            # Data
            for user in users:
                row = [user.get(h, '') for h in headers]
                writer.writerow(row)

            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=users_export.csv'}
            )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/bulk/preview', methods=['POST'])
@login_required
@admin_required
def api_bulk_preview():
    """Preview bulk update operation"""
    try:
        data = request.get_json()
        target = data.get('target', 'free')
        action = data.get('action', 'upgrade')
        tier = data.get('tier', 'pro')

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build query based on target
        query = "SELECT id, username, email, subscription_tier FROM users WHERE is_active = true"

        if target == 'free':
            query += " AND (subscription_tier = 'free' OR subscription_tier IS NULL)"
        elif target == 'inactive':
            query = "SELECT id, username, email, subscription_tier FROM users WHERE is_active = false"
        # 'selected' would require client-side selected IDs

        cur.execute(query)
        users = cur.fetchall()

        # Generate action description
        action_descriptions = {
            'upgrade': f'Upgrade to {tier.upper()} tier',
            'downgrade': f'Downgrade to {tier.upper()} tier',
            'deactivate': 'Deactivate accounts',
            'reactivate': 'Reactivate accounts'
        }

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'count': len(users),
            'users': [dict(u) for u in users[:50]],  # Limit preview
            'action_description': action_descriptions.get(action, action)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@account_center_bp.route('/api/bulk/update', methods=['POST'])
@login_required
@admin_required
def api_bulk_update():
    """Execute bulk update operation"""
    try:
        data = request.get_json()
        target = data.get('target', 'free')
        action = data.get('action', 'upgrade')
        tier = data.get('tier', 'pro')

        conn = get_db()
        cur = conn.cursor()

        # Build update based on action
        if action in ['upgrade', 'downgrade']:
            if target == 'free':
                cur.execute("""
                    UPDATE users SET subscription_tier = %s
                    WHERE is_active = true AND (subscription_tier = 'free' OR subscription_tier IS NULL)
                """, (tier,))
            elif target == 'inactive':
                cur.execute("""
                    UPDATE users SET subscription_tier = %s
                    WHERE is_active = false
                """, (tier,))

        elif action == 'deactivate':
            if target == 'free':
                cur.execute("""
                    UPDATE users SET is_active = false
                    WHERE is_active = true AND (subscription_tier = 'free' OR subscription_tier IS NULL)
                """)
            elif target == 'inactive':
                pass  # Already inactive

        elif action == 'reactivate':
            if target == 'inactive':
                cur.execute("UPDATE users SET is_active = true WHERE is_active = false")

        count = cur.rowcount
        conn.commit()

        log_activity(current_user.id, 'bulk_update_executed',
                     details={'target': target, 'action': action, 'tier': tier, 'count': count})

        cur.close()
        conn.close()

        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
