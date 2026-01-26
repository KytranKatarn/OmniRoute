"""
CRM Routes
==========
Customer Relationship Management for A.R.C.H.I.E. Business Tools.

Features:
- Customer profiles with subscription tracking
- Interaction history (calls, emails, notes, orders)
- Dynamic segments for marketing
- Import/export functionality
- Integration with Store Builder, Call Center, Invoicing

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os
import json
import csv
import io

# Import user context helpers
try:
    from user_context import is_admin_user
except ImportError:
    def is_admin_user():
        return getattr(current_user, 'is_admin', False)

# Create blueprint
crm_bp = Blueprint(
    'crm',
    __name__,
    url_prefix='/tools/crm',
    template_folder='../../templates/tools'
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
# MAIN PAGE
# ============================================================================

@crm_bp.route('/')
@login_required
def index():
    """Main CRM dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get customer stats
        cur.execute("""
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE subscription_status = 'active') as active_subscribers,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as new_this_month,
                COALESCE(SUM(lifetime_value), 0) as total_lifetime_value,
                COALESCE(AVG(lifetime_value), 0) as avg_lifetime_value
            FROM crm_customers
            WHERE is_active = true
        """)
        stats = cur.fetchone()

        # Get recent customers
        cur.execute("""
            SELECT id, email, first_name, last_name, company, source,
                   subscription_tier, subscription_status, total_orders,
                   total_spent, created_at
            FROM crm_customers
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent_customers = cur.fetchall()

        # Get segments with counts
        cur.execute("""
            SELECT id, name, description, customer_count, is_dynamic
            FROM crm_segments
            ORDER BY name
        """)
        segments = cur.fetchall()

        # Get interaction counts by type (last 30 days)
        cur.execute("""
            SELECT interaction_type, COUNT(*) as count
            FROM crm_interactions
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY interaction_type
            ORDER BY count DESC
        """)
        interaction_stats = cur.fetchall()

        # Get source breakdown
        cur.execute("""
            SELECT source, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY source
            ORDER BY count DESC
        """)
        source_breakdown = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            'crm.html',
            stats=stats,
            recent_customers=recent_customers,
            segments=segments,
            interaction_stats=interaction_stats,
            source_breakdown=source_breakdown,
            is_admin=is_admin_user()
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error loading dashboard: {e}")
        return render_template(
            'crm.html',
            stats={'total_customers': 0, 'active_subscribers': 0, 'new_this_month': 0,
                   'total_lifetime_value': 0, 'avg_lifetime_value': 0},
            recent_customers=[],
            segments=[],
            interaction_stats=[],
            source_breakdown=[],
            error=str(e)
        )


# ============================================================================
# CUSTOMER CRUD
# ============================================================================

@crm_bp.route('/api/customers', methods=['GET'])
@login_required
def get_customers():
    """Get all customers with filtering"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get filter parameters
        search = request.args.get('search', '')
        source = request.args.get('source', '')
        subscription = request.args.get('subscription', '')
        segment_id = request.args.get('segment_id', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        offset = (page - 1) * per_page

        # Build query
        where_clauses = ["is_active = true"]
        params = []

        if search:
            where_clauses.append("""
                (email ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s
                 OR company ILIKE %s OR phone ILIKE %s)
            """)
            search_param = f"%{search}%"
            params.extend([search_param] * 5)

        if source:
            where_clauses.append("source = %s")
            params.append(source)

        if subscription:
            where_clauses.append("subscription_status = %s")
            params.append(subscription)

        if segment_id:
            where_clauses.append("""
                id IN (SELECT customer_id FROM crm_segment_members WHERE segment_id = %s)
            """)
            params.append(segment_id)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM crm_customers WHERE {where_sql}", params)
        total = cur.fetchone()['count']

        # Get customers
        cur.execute(f"""
            SELECT id, email, first_name, last_name, phone, company, source,
                   subscription_tier, subscription_status, tags, total_orders,
                   total_spent, lifetime_value, last_interaction_date, created_at
            FROM crm_customers
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        customers = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customers': [dict(c) for c in customers],
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting customers: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/customers', methods=['POST'])
@login_required
def create_customer():
    """Create a new customer"""
    try:
        data = request.get_json()

        if not data.get('email'):
            return jsonify({'success': False, 'error': 'Email is required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check for duplicate email
        cur.execute("SELECT id FROM crm_customers WHERE email = %s", (data['email'],))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Customer with this email already exists'}), 400

        # Insert customer
        cur.execute("""
            INSERT INTO crm_customers
            (email, first_name, last_name, phone, company, address_line1, address_line2,
             city, state, postal_code, country, source, tags, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            data['email'],
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('phone', ''),
            data.get('company', ''),
            data.get('address_line1', ''),
            data.get('address_line2', ''),
            data.get('city', ''),
            data.get('state', ''),
            data.get('postal_code', ''),
            data.get('country', 'Canada'),
            data.get('source', 'manual'),
            data.get('tags', []),
            data.get('notes', ''),
            current_user.id
        ))
        customer = cur.fetchone()

        # Log the creation
        cur.execute("""
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, created_by)
            VALUES (%s, 'note', 'Customer Created', %s, %s)
        """, (customer['id'], f"Customer created via {data.get('source', 'manual')}", current_user.id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer': dict(customer),
            'message': 'Customer created successfully'
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error creating customer: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/customers/<int:customer_id>', methods=['GET'])
@login_required
def get_customer(customer_id):
    """Get customer details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get customer
        cur.execute("SELECT * FROM crm_customers WHERE id = %s", (customer_id,))
        customer = cur.fetchone()

        if not customer:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        # Get interactions
        cur.execute("""
            SELECT i.*, u.username as created_by_name
            FROM crm_interactions i
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.customer_id = %s
            ORDER BY i.created_at DESC
            LIMIT 50
        """, (customer_id,))
        interactions = cur.fetchall()

        # Get segments
        cur.execute("""
            SELECT s.id, s.name
            FROM crm_segments s
            JOIN crm_segment_members sm ON s.id = sm.segment_id
            WHERE sm.customer_id = %s
        """, (customer_id,))
        segments = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer': dict(customer),
            'interactions': [dict(i) for i in interactions],
            'segments': [dict(s) for s in segments]
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting customer: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/customers/<int:customer_id>', methods=['PUT'])
@login_required
def update_customer(customer_id):
    """Update customer"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check customer exists
        cur.execute("SELECT id FROM crm_customers WHERE id = %s", (customer_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        # Build update query dynamically
        allowed_fields = [
            'email', 'first_name', 'last_name', 'phone', 'company',
            'address_line1', 'address_line2', 'city', 'state', 'postal_code',
            'country', 'source', 'subscription_tier', 'subscription_status',
            'tags', 'notes', 'is_active'
        ]
        updates = []
        params = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if not updates:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        updates.append("updated_at = NOW()")
        params.append(customer_id)

        cur.execute(f"""
            UPDATE crm_customers
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """, params)
        customer = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer': dict(customer),
            'message': 'Customer updated successfully'
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error updating customer: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/customers/<int:customer_id>', methods=['DELETE'])
@login_required
def delete_customer(customer_id):
    """Soft delete customer"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            UPDATE crm_customers
            SET is_active = false, updated_at = NOW()
            WHERE id = %s
            RETURNING id, email
        """, (customer_id,))
        customer = cur.fetchone()

        if not customer:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f"Customer {customer['email']} deleted"
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error deleting customer: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# INTERACTIONS
# ============================================================================

@crm_bp.route('/api/customers/<int:customer_id>/interactions', methods=['GET'])
@login_required
def get_interactions(customer_id):
    """Get customer interactions"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT i.*, u.username as created_by_name
            FROM crm_interactions i
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.customer_id = %s
            ORDER BY i.created_at DESC
        """, (customer_id,))
        interactions = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'interactions': [dict(i) for i in interactions]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/customers/<int:customer_id>/interactions', methods=['POST'])
@login_required
def add_interaction(customer_id):
    """Add interaction to customer"""
    try:
        data = request.get_json()

        if not data.get('interaction_type'):
            return jsonify({'success': False, 'error': 'Interaction type is required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check customer exists
        cur.execute("SELECT id FROM crm_customers WHERE id = %s", (customer_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Customer not found'}), 404

        # Add interaction
        cur.execute("""
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            customer_id,
            data['interaction_type'],
            data.get('subject', ''),
            data.get('content', ''),
            json.dumps(data.get('metadata', {})),
            current_user.id
        ))
        interaction = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'interaction': dict(interaction),
            'message': 'Interaction added'
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error adding interaction: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# SEGMENTS
# ============================================================================

@crm_bp.route('/api/segments', methods=['GET'])
@login_required
def get_segments():
    """Get all segments"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT s.*, u.username as created_by_name
            FROM crm_segments s
            LEFT JOIN users u ON s.created_by = u.id
            ORDER BY s.name
        """)
        segments = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'segments': [dict(s) for s in segments]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/segments', methods=['POST'])
@login_required
def create_segment():
    """Create a new segment"""
    try:
        data = request.get_json()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Segment name is required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO crm_segments
            (name, description, filter_criteria, is_dynamic, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (
            data['name'],
            data.get('description', ''),
            json.dumps(data.get('filter_criteria', {})),
            data.get('is_dynamic', True),
            current_user.id
        ))
        segment = cur.fetchone()

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'segment': dict(segment),
            'message': 'Segment created'
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error creating segment: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/segments/<int:segment_id>', methods=['PUT'])
@login_required
def update_segment(segment_id):
    """Update segment"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            UPDATE crm_segments
            SET name = COALESCE(%s, name),
                description = COALESCE(%s, description),
                filter_criteria = COALESCE(%s, filter_criteria),
                is_dynamic = COALESCE(%s, is_dynamic),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """, (
            data.get('name'),
            data.get('description'),
            json.dumps(data['filter_criteria']) if 'filter_criteria' in data else None,
            data.get('is_dynamic'),
            segment_id
        ))
        segment = cur.fetchone()

        if not segment:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Segment not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'segment': dict(segment)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/segments/<int:segment_id>', methods=['DELETE'])
@login_required
def delete_segment(segment_id):
    """Delete segment"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("DELETE FROM crm_segments WHERE id = %s RETURNING name", (segment_id,))
        segment = cur.fetchone()

        if not segment:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Segment not found'}), 404

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'message': f"Segment '{segment['name']}' deleted"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/segments/<int:segment_id>/customers', methods=['GET'])
@login_required
def get_segment_customers(segment_id):
    """Get customers in a segment"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get segment
        cur.execute("SELECT * FROM crm_segments WHERE id = %s", (segment_id,))
        segment = cur.fetchone()

        if not segment:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Segment not found'}), 404

        # Build query based on filter criteria
        filter_criteria = segment['filter_criteria'] or {}
        where_clauses = ["is_active = true"]
        params = []

        # Apply dynamic filters
        if filter_criteria.get('subscription_status'):
            where_clauses.append("subscription_status = %s")
            params.append(filter_criteria['subscription_status'])

        if filter_criteria.get('lifetime_value_gt'):
            where_clauses.append("lifetime_value > %s")
            params.append(filter_criteria['lifetime_value_gt'])

        if filter_criteria.get('total_orders'):
            where_clauses.append("total_orders = %s")
            params.append(filter_criteria['total_orders'])

        if filter_criteria.get('created_this_month'):
            where_clauses.append("created_at > DATE_TRUNC('month', NOW())")

        if filter_criteria.get('source'):
            where_clauses.append("source = %s")
            params.append(filter_criteria['source'])

        where_sql = " AND ".join(where_clauses)

        cur.execute(f"""
            SELECT id, email, first_name, last_name, company, subscription_tier,
                   subscription_status, total_orders, lifetime_value, created_at
            FROM crm_customers
            WHERE {where_sql}
            ORDER BY created_at DESC
        """, params)
        customers = cur.fetchall()

        # Update segment count
        cur.execute("""
            UPDATE crm_segments SET customer_count = %s WHERE id = %s
        """, (len(customers), segment_id))
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'segment': dict(segment),
            'customers': [dict(c) for c in customers],
            'count': len(customers)
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting segment customers: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/segments/<int:segment_id>/add-customer', methods=['POST'])
@login_required
def add_customer_to_segment(segment_id):
    """Add customer to static segment"""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')

        if not customer_id:
            return jsonify({'success': False, 'error': 'Customer ID is required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO crm_segment_members (segment_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (segment_id, customer_id) DO NOTHING
        """, (segment_id, customer_id))

        # Update segment count
        cur.execute("""
            UPDATE crm_segments
            SET customer_count = (SELECT COUNT(*) FROM crm_segment_members WHERE segment_id = %s)
            WHERE id = %s
        """, (segment_id, segment_id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({'success': True, 'message': 'Customer added to segment'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# IMPORT/EXPORT
# ============================================================================

@crm_bp.route('/api/import', methods=['POST'])
@login_required
def import_customers():
    """Import customers from CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400

        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({'success': False, 'error': 'File must be CSV format'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Create import record
        cur.execute("""
            INSERT INTO crm_imports (filename, status, created_by)
            VALUES (%s, 'processing', %s)
            RETURNING id
        """, (file.filename, current_user.id))
        import_id = cur.fetchone()['id']
        conn.commit()

        # Parse CSV
        stream = io.StringIO(file.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)

        imported = 0
        failed = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            try:
                email = row.get('email', '').strip()
                if not email:
                    errors.append({'row': row_num, 'error': 'Missing email'})
                    failed += 1
                    continue

                # Insert or update customer
                cur.execute("""
                    INSERT INTO crm_customers
                    (email, first_name, last_name, phone, company, city, source, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'import', %s)
                    ON CONFLICT (email) DO UPDATE SET
                        first_name = COALESCE(EXCLUDED.first_name, crm_customers.first_name),
                        last_name = COALESCE(EXCLUDED.last_name, crm_customers.last_name),
                        phone = COALESCE(EXCLUDED.phone, crm_customers.phone),
                        company = COALESCE(EXCLUDED.company, crm_customers.company),
                        updated_at = NOW()
                """, (
                    email,
                    row.get('first_name', ''),
                    row.get('last_name', ''),
                    row.get('phone', ''),
                    row.get('company', ''),
                    row.get('city', ''),
                    current_user.id
                ))
                imported += 1

            except Exception as e:
                errors.append({'row': row_num, 'error': str(e)})
                failed += 1

        # Update import record
        cur.execute("""
            UPDATE crm_imports
            SET total_rows = %s, imported_rows = %s, failed_rows = %s,
                errors = %s, status = 'completed', completed_at = NOW()
            WHERE id = %s
        """, (imported + failed, imported, failed, json.dumps(errors), import_id))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'imported': imported,
            'failed': failed,
            'errors': errors[:10],  # Return first 10 errors
            'import_id': import_id
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Import error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/export', methods=['GET'])
@login_required
def export_customers():
    """Export customers to CSV"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        segment_id = request.args.get('segment_id')

        if segment_id:
            cur.execute("""
                SELECT c.* FROM crm_customers c
                JOIN crm_segment_members sm ON c.id = sm.customer_id
                WHERE sm.segment_id = %s AND c.is_active = true
                ORDER BY c.email
            """, (segment_id,))
        else:
            cur.execute("""
                SELECT * FROM crm_customers
                WHERE is_active = true
                ORDER BY email
            """)
        customers = cur.fetchall()

        cur.close()
        conn.close()

        # Build CSV
        output = io.StringIO()
        if customers:
            fieldnames = ['email', 'first_name', 'last_name', 'phone', 'company',
                          'city', 'state', 'country', 'subscription_tier',
                          'subscription_status', 'total_orders', 'lifetime_value', 'source']
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for customer in customers:
                writer.writerow(dict(customer))

        return jsonify({
            'success': True,
            'csv': output.getvalue(),
            'count': len(customers),
            'filename': f"crm_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# STATS & ANALYTICS
# ============================================================================

@crm_bp.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get CRM dashboard stats"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats
        cur.execute("""
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE subscription_status = 'active') as active_subscribers,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as new_this_month,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as new_this_week,
                COALESCE(SUM(lifetime_value), 0) as total_lifetime_value,
                COALESCE(AVG(lifetime_value), 0) as avg_lifetime_value,
                COALESCE(SUM(total_orders), 0) as total_orders,
                COALESCE(AVG(total_orders), 0) as avg_orders_per_customer
            FROM crm_customers
            WHERE is_active = true
        """)
        stats = cur.fetchone()

        # Growth trend (last 30 days)
        cur.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM crm_customers
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        growth_trend = cur.fetchall()

        # Source breakdown
        cur.execute("""
            SELECT source, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY source
            ORDER BY count DESC
        """)
        source_breakdown = cur.fetchall()

        # Subscription breakdown
        cur.execute("""
            SELECT subscription_status, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY subscription_status
            ORDER BY count DESC
        """)
        subscription_breakdown = cur.fetchall()

        # Interaction stats (last 30 days)
        cur.execute("""
            SELECT interaction_type, COUNT(*) as count
            FROM crm_interactions
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY interaction_type
            ORDER BY count DESC
        """)
        interaction_stats = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'stats': dict(stats),
            'growth_trend': [dict(g) for g in growth_trend],
            'source_breakdown': [dict(s) for s in source_breakdown],
            'subscription_breakdown': [dict(s) for s in subscription_breakdown],
            'interaction_stats': [dict(i) for i in interaction_stats]
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# SEARCH & QUICK ACTIONS
# ============================================================================

@crm_bp.route('/api/search', methods=['GET'])
@login_required
def search_customers():
    """Quick search for customers"""
    try:
        query = request.args.get('q', '')
        if len(query) < 2:
            return jsonify({'success': True, 'results': []})

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, email, first_name, last_name, company, phone
            FROM crm_customers
            WHERE is_active = true
              AND (email ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s
                   OR company ILIKE %s OR phone ILIKE %s)
            ORDER BY
                CASE WHEN email ILIKE %s THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT 10
        """, (f"%{query}%",) * 5 + (f"{query}%",))
        results = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'results': [dict(r) for r in results]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/quick-create', methods=['POST'])
@login_required
def quick_create_customer():
    """Quick create customer from other modules"""
    try:
        data = request.get_json()
        email = data.get('email')
        source = data.get('source', 'manual')

        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if exists
        cur.execute("SELECT id, email FROM crm_customers WHERE email = %s", (email,))
        existing = cur.fetchone()

        if existing:
            # Update last interaction
            cur.execute("""
                UPDATE crm_customers
                SET last_interaction_date = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (existing['id'],))
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({
                'success': True,
                'customer_id': existing['id'],
                'existing': True
            })

        # Create new
        cur.execute("""
            INSERT INTO crm_customers (email, first_name, last_name, phone, source, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            email,
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('phone', ''),
            source,
            current_user.id
        ))
        customer_id = cur.fetchone()['id']

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'existing': False
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Quick create error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# INTEGRATION ENDPOINTS (for other modules)
# ============================================================================

@crm_bp.route('/api/from-order', methods=['POST'])
@login_required
def create_from_order():
    """Create/update customer from store order"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO crm_customers
            (email, first_name, last_name, phone, address_line1, city, state,
             postal_code, country, source, total_orders, total_spent, last_order_date, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'store', 1, %s, NOW(), %s)
            ON CONFLICT (email) DO UPDATE SET
                total_orders = crm_customers.total_orders + 1,
                total_spent = crm_customers.total_spent + EXCLUDED.total_spent,
                last_order_date = NOW(),
                lifetime_value = crm_customers.lifetime_value + EXCLUDED.total_spent,
                updated_at = NOW()
            RETURNING id
        """, (
            data.get('email'),
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('phone', ''),
            data.get('address', ''),
            data.get('city', ''),
            data.get('state', ''),
            data.get('postal_code', ''),
            data.get('country', 'Canada'),
            data.get('total', 0),
            current_user.id
        ))
        customer_id = cur.fetchone()['id']

        # Log the order interaction
        cur.execute("""
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, 'order', %s, %s, %s, %s)
        """, (
            customer_id,
            f"Order #{data.get('order_id', 'N/A')}",
            f"Order placed: ${data.get('total', 0):.2f}",
            json.dumps({'order_id': data.get('order_id'), 'total': data.get('total')}),
            current_user.id
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer_id': customer_id
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Create from order error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/from-call', methods=['POST'])
@login_required
def create_from_call():
    """Create/update customer from call center"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Try to find by phone first, then email
        phone = data.get('phone', '')
        email = data.get('email', '')

        cur.execute("""
            SELECT id FROM crm_customers
            WHERE (phone = %s AND phone != '') OR (email = %s AND email != '')
            LIMIT 1
        """, (phone, email))
        existing = cur.fetchone()

        if existing:
            customer_id = existing['id']
            cur.execute("""
                UPDATE crm_customers
                SET last_interaction_date = NOW(), updated_at = NOW()
                WHERE id = %s
            """, (customer_id,))
        else:
            # Create new with phone or generate email
            if not email:
                email = f"phone_{phone.replace('+', '').replace('-', '')}@unknown.temp"

            cur.execute("""
                INSERT INTO crm_customers
                (email, first_name, last_name, phone, source, created_by)
                VALUES (%s, %s, %s, %s, 'call_center', %s)
                RETURNING id
            """, (
                email,
                data.get('first_name', ''),
                data.get('last_name', ''),
                phone,
                current_user.id
            ))
            customer_id = cur.fetchone()['id']

        # Log the call interaction
        cur.execute("""
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, 'call', %s, %s, %s, %s)
        """, (
            customer_id,
            f"Call - {data.get('direction', 'inbound')}",
            data.get('summary', 'Phone call recorded'),
            json.dumps({
                'duration': data.get('duration'),
                'call_id': data.get('call_id'),
                'direction': data.get('direction')
            }),
            current_user.id
        ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'customer_id': customer_id
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Create from call error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@crm_bp.route('/api/update-subscription', methods=['POST'])
@login_required
def update_subscription():
    """Update customer subscription status"""
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        email = data.get('email')

        if not customer_id and not email:
            return jsonify({'success': False, 'error': 'Customer ID or email required'}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where = "id = %s" if customer_id else "email = %s"
        param = customer_id or email

        cur.execute(f"""
            UPDATE crm_customers
            SET subscription_tier = %s,
                subscription_status = %s,
                subscription_id = %s,
                updated_at = NOW()
            WHERE {where}
            RETURNING id
        """, (
            data.get('tier'),
            data.get('status'),
            data.get('subscription_id'),
            param
        ))
        result = cur.fetchone()

        if result:
            # Log subscription change
            cur.execute("""
                INSERT INTO crm_interactions
                (customer_id, interaction_type, subject, content, metadata, created_by)
                VALUES (%s, 'subscription', %s, %s, %s, %s)
            """, (
                result['id'],
                f"Subscription {data.get('status')}",
                f"Tier: {data.get('tier')} - Status: {data.get('status')}",
                json.dumps(data),
                current_user.id
            ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'updated': result is not None
        })
    except Exception as e:
        current_app.logger.error(f"[CRM] Update subscription error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# STATUS ENDPOINT
# ============================================================================

@crm_bp.route('/api/status')
def status():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) FROM crm_customers")
        count = cur.fetchone()['count']
        cur.close()
        conn.close()

        return jsonify({
            'module': 'crm',
            'status': 'healthy',
            'healthy': True,
            'customers': count,
            'message': f'CRM operational with {count} customers'
        })
    except Exception as e:
        return jsonify({
            'module': 'crm',
            'status': 'error',
            'healthy': False,
            'message': str(e)
        }), 500
