"""
Website Builder Routes - Blueprint for Website Management
Provides CRUD operations for user websites with GitHub integration and Docker deployment

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os

# Create blueprint with template folder
website_builder_bp = Blueprint(
    'website_builder',
    __name__,
    url_prefix='/tools/website-builder',
    template_folder='templates'
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


# ============================================================================
# MAIN PAGES
# ============================================================================

@website_builder_bp.route('/')
@login_required
def index():
    """Main website builder page"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's websites
        cur.execute("""
            SELECT * FROM user_websites
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (current_user.id,))
        websites = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            'website_builder.html',
            websites=websites,
            user=current_user
        )
    except Exception as e:
        current_app.logger.error(f"Error loading website builder: {e}")
        return render_template(
            'website_builder.html',
            websites=[],
            error=str(e)
        )


# ============================================================================
# API ENDPOINTS
# ============================================================================

@website_builder_bp.route('/api/websites', methods=['GET'])
@login_required
def get_websites():
    """Get all websites for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                w.*,
                COUNT(DISTINCT d.id) as domain_count,
                COUNT(DISTINCT dep.id) as deployment_count
            FROM user_websites w
            LEFT JOIN website_domains d ON w.id = d.website_id
            LEFT JOIN website_deployments dep ON w.id = dep.website_id
            WHERE w.user_id = %s
            GROUP BY w.id
            ORDER BY w.created_at DESC
        """, (current_user.id,))

        websites = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'websites': [dict(w) for w in websites]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@website_builder_bp.route('/api/websites/<int:website_id>', methods=['GET'])
@login_required
def get_website(website_id):
    """Get a specific website by ID"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("""
            SELECT * FROM user_websites
            WHERE id = %s AND user_id = %s
        """, (website_id, current_user.id))

        website = cur.fetchone()

        if not website:
            return jsonify({
                'success': False,
                'error': 'Website not found or access denied'
            }), 404

        # Get related data
        cur.execute("SELECT * FROM website_domains WHERE website_id = %s", (website_id,))
        domains = cur.fetchall()

        cur.execute("SELECT * FROM website_deployments WHERE website_id = %s ORDER BY deployed_at DESC LIMIT 10", (website_id,))
        deployments = cur.fetchall()

        cur.execute("SELECT * FROM website_env_vars WHERE website_id = %s", (website_id,))
        env_vars = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'website': dict(website),
            'domains': [dict(d) for d in domains],
            'deployments': [dict(d) for d in deployments],
            'env_vars': [dict(e) for e in env_vars]
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@website_builder_bp.route('/api/websites', methods=['POST'])
@login_required
def create_website():
    """Create a new website"""
    try:
        data = request.get_json()

        required_fields = ['name', 'type']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check for duplicate name for this user
        cur.execute("""
            SELECT id FROM user_websites
            WHERE user_id = %s AND name = %s
        """, (current_user.id, data['name']))

        if cur.fetchone():
            return jsonify({
                'success': False,
                'error': 'You already have a website with this name'
            }), 400

        # Create website
        cur.execute("""
            INSERT INTO user_websites (
                user_id, name, description, type, status,
                github_repo, github_branch, platform_subdomain
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            current_user.id,
            data['name'],
            data.get('description', ''),
            data['type'],
            'draft',
            data.get('github_repo'),
            data.get('github_branch', 'main'),
            data.get('platform_subdomain')
        ))

        website = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Website created successfully',
            'website': dict(website)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@website_builder_bp.route('/api/websites/<int:website_id>', methods=['PUT'])
@login_required
def update_website(website_id):
    """Update a website"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("""
            SELECT id FROM user_websites
            WHERE id = %s AND user_id = %s
        """, (website_id, current_user.id))

        if not cur.fetchone():
            return jsonify({
                'success': False,
                'error': 'Website not found or access denied'
            }), 404

        # Build update query
        update_fields = []
        values = []

        allowed_fields = ['name', 'description', 'type', 'status', 'github_repo',
                         'github_branch', 'primary_domain', 'platform_subdomain']

        for field in allowed_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                values.append(data[field])

        if not update_fields:
            return jsonify({
                'success': False,
                'error': 'No valid fields to update'
            }), 400

        # Add updated_at
        update_fields.append("updated_at = NOW()")
        values.append(website_id)

        query = f"""
            UPDATE user_websites
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING *
        """

        cur.execute(query, values)
        website = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Website updated successfully',
            'website': dict(website)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@website_builder_bp.route('/api/websites/<int:website_id>', methods=['DELETE'])
@login_required
def delete_website(website_id):
    """Delete a website"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("""
            SELECT id, name FROM user_websites
            WHERE id = %s AND user_id = %s
        """, (website_id, current_user.id))

        website = cur.fetchone()

        if not website:
            return jsonify({
                'success': False,
                'error': 'Website not found or access denied'
            }), 404

        # Delete website (CASCADE will handle related records)
        cur.execute("DELETE FROM user_websites WHERE id = %s", (website_id,))
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Website "{website["name"]}" deleted successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@website_builder_bp.route('/api/websites/<int:website_id>/deploy', methods=['POST'])
@login_required
def deploy_website(website_id):
    """Deploy a website (placeholder for now)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("""
            SELECT * FROM user_websites
            WHERE id = %s AND user_id = %s
        """, (website_id, current_user.id))

        website = cur.fetchone()

        if not website:
            return jsonify({
                'success': False,
                'error': 'Website not found or access denied'
            }), 404

        # Create deployment record
        data = request.get_json() or {}

        cur.execute("""
            INSERT INTO website_deployments (
                website_id, deployed_by, status, deployment_log
            ) VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (
            website_id,
            current_user.id,
            'pending',
            'Deployment initiated'
        ))

        deployment = cur.fetchone()

        # Update website status
        cur.execute("""
            UPDATE user_websites
            SET status = 'deploying', last_deployed_at = NOW()
            WHERE id = %s
        """, (website_id,))

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Deployment initiated',
            'deployment': dict(deployment)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# HEALTH CHECK
# ============================================================================

@website_builder_bp.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM user_websites")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify({
            'healthy': True,
            'module': 'website_builder',
            'total_websites': count
        })
    except Exception as e:
        return jsonify({
            'healthy': False,
            'module': 'website_builder',
            'error': str(e)
        }), 500
