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
from datetime import datetime, date
from decimal import Decimal
import os
import json
import csv
import io

# Import user context helpers
try:
    from user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
crm_bp = Blueprint("crm", __name__, url_prefix="/tools/crm", template_folder="../../templates/tools")


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ============================================================================
# MAIN PAGE
# ============================================================================


@crm_bp.route("/")
@login_required
def index():
    """Main CRM dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get customer stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE subscription_status = 'active') as active_subscribers,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as new_this_month,
                COALESCE(SUM(lifetime_value), 0) as total_lifetime_value,
                COALESCE(AVG(lifetime_value), 0) as avg_lifetime_value
            FROM crm_customers
            WHERE is_active = true
        """
        )
        stats = cur.fetchone()

        # Get recent customers
        cur.execute(
            """
            SELECT id, email, first_name, last_name, company, source,
                   subscription_tier, subscription_status, total_orders,
                   total_spent, created_at
            FROM crm_customers
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        recent_customers = cur.fetchall()

        # Get segments with counts
        cur.execute(
            """
            SELECT id, name, description, customer_count, is_dynamic
            FROM crm_segments
            ORDER BY name
        """
        )
        segments = cur.fetchall()

        # Get interaction counts by type (last 30 days)
        cur.execute(
            """
            SELECT interaction_type, COUNT(*) as count
            FROM crm_interactions
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY interaction_type
            ORDER BY count DESC
        """
        )
        interaction_stats = cur.fetchall()

        # Get source breakdown
        cur.execute(
            """
            SELECT source, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY source
            ORDER BY count DESC
        """
        )
        source_breakdown = cur.fetchall()

        return render_template(
            "crm.html",
            stats=stats,
            recent_customers=recent_customers,
            segments=segments,
            interaction_stats=interaction_stats,
            source_breakdown=source_breakdown,
            is_admin=is_admin_user(),
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error loading dashboard: {e}")
        return render_template(
            "crm.html",
            stats={
                "total_customers": 0,
                "active_subscribers": 0,
                "new_this_month": 0,
                "total_lifetime_value": 0,
                "avg_lifetime_value": 0,
            },
            recent_customers=[],
            segments=[],
            interaction_stats=[],
            source_breakdown=[],
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CUSTOMER CRUD
# ============================================================================


@crm_bp.route("/api/customers", methods=["GET"])
@login_required
def get_customers():
    """Get all customers with filtering"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get filter parameters
        search = request.args.get("search", "")
        source = request.args.get("source", "")
        subscription = request.args.get("subscription", "")
        segment_id = request.args.get("segment_id", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        offset = (page - 1) * per_page

        # Build query
        where_clauses = ["is_active = true"]
        params = []

        if search:
            where_clauses.append(
                """
                (email ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s
                 OR company ILIKE %s OR phone ILIKE %s)
            """
            )
            search_param = f"%{search}%"
            params.extend([search_param] * 5)

        if source:
            where_clauses.append("source = %s")
            params.append(source)

        if subscription:
            where_clauses.append("subscription_status = %s")
            params.append(subscription)

        if segment_id:
            where_clauses.append(
                """
                id IN (SELECT customer_id FROM crm_segment_members WHERE segment_id = %s)
            """
            )
            params.append(segment_id)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM crm_customers WHERE {where_sql}", params)
        total = cur.fetchone()["count"]

        # Get customers
        cur.execute(
            f"""
            SELECT id, email, first_name, last_name, phone, company, source,
                   subscription_tier, subscription_status, tags, total_orders,
                   total_spent, lifetime_value, last_interaction_date, created_at
            FROM crm_customers
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        customers = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "customers": [dict(c) for c in customers],
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting customers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/customers", methods=["POST"])
@login_required
def create_customer():
    """Create a new customer"""
    try:
        data = request.get_json()

        if not data.get("email"):
            return jsonify({"success": False, "error": "Email is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check for duplicate email
        cur.execute("SELECT id FROM crm_customers WHERE email = %s", (data["email"],))
        if cur.fetchone():
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Customer with this email already exists",
                    }
                ),
                400,
            )

        # Insert customer
        cur.execute(
            """
            INSERT INTO crm_customers
            (email, first_name, last_name, phone, company, address_line1, address_line2,
             city, state, postal_code, country, source, tags, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data["email"],
                data.get("first_name", ""),
                data.get("last_name", ""),
                data.get("phone", ""),
                data.get("company", ""),
                data.get("address_line1", ""),
                data.get("address_line2", ""),
                data.get("city", ""),
                data.get("state", ""),
                data.get("postal_code", ""),
                data.get("country", "Canada"),
                data.get("source", "manual"),
                data.get("tags", []),
                data.get("notes", ""),
                current_user.id,
            ),
        )
        customer = cur.fetchone()

        # Log the creation
        cur.execute(
            """
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, created_by)
            VALUES (%s, 'note', 'Customer Created', %s, %s)
        """,
            (
                customer["id"],
                f"Customer created via {data.get('source', 'manual')}",
                current_user.id,
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "customer": dict(customer),
                "message": "Customer created successfully",
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error creating customer: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/customers/<int:customer_id>", methods=["GET"])
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
            return jsonify({"success": False, "error": "Customer not found"}), 404

        # Get interactions
        cur.execute(
            """
            SELECT i.*, u.username as created_by_name
            FROM crm_interactions i
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.customer_id = %s
            ORDER BY i.created_at DESC
            LIMIT 50
        """,
            (customer_id,),
        )
        interactions = cur.fetchall()

        # Get segments
        cur.execute(
            """
            SELECT s.id, s.name
            FROM crm_segments s
            JOIN crm_segment_members sm ON s.id = sm.segment_id
            WHERE sm.customer_id = %s
        """,
            (customer_id,),
        )
        segments = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "customer": dict(customer),
                "interactions": [dict(i) for i in interactions],
                "segments": [dict(s) for s in segments],
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting customer: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/customers/<int:customer_id>", methods=["PUT"])
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
            return jsonify({"success": False, "error": "Customer not found"}), 404

        # Build update query dynamically
        allowed_fields = [
            "email",
            "first_name",
            "last_name",
            "phone",
            "company",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "country",
            "source",
            "subscription_tier",
            "subscription_status",
            "tags",
            "notes",
            "is_active",
        ]
        updates = []
        params = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.append(customer_id)

        cur.execute(
            f"""
            UPDATE crm_customers
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            params,
        )
        customer = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "customer": dict(customer),
                "message": "Customer updated successfully",
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error updating customer: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/customers/<int:customer_id>", methods=["DELETE"])
@login_required
def delete_customer(customer_id):
    """Soft delete customer"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE crm_customers
            SET is_active = false, updated_at = NOW()
            WHERE id = %s
            RETURNING id, email
        """,
            (customer_id,),
        )
        customer = cur.fetchone()

        if not customer:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Customer not found"}), 404

        conn.commit()

        return jsonify({"success": True, "message": f"Customer {customer['email']} deleted"})
    except Exception as e:
        current_app.logger.error(f"[CRM] Error deleting customer: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INTERACTIONS
# ============================================================================


@crm_bp.route("/api/customers/<int:customer_id>/interactions", methods=["GET"])
@login_required
def get_interactions(customer_id):
    """Get customer interactions"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT i.*, u.username as created_by_name
            FROM crm_interactions i
            LEFT JOIN users u ON i.created_by = u.id
            WHERE i.customer_id = %s
            ORDER BY i.created_at DESC
        """,
            (customer_id,),
        )
        interactions = cur.fetchall()

        return jsonify({"success": True, "interactions": [dict(i) for i in interactions]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/customers/<int:customer_id>/interactions", methods=["POST"])
@login_required
def add_interaction(customer_id):
    """Add interaction to customer"""
    try:
        data = request.get_json()

        if not data.get("interaction_type"):
            return (
                jsonify({"success": False, "error": "Interaction type is required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check customer exists
        cur.execute("SELECT id FROM crm_customers WHERE id = %s", (customer_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Customer not found"}), 404

        # Add interaction
        cur.execute(
            """
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                customer_id,
                data["interaction_type"],
                data.get("subject", ""),
                data.get("content", ""),
                json.dumps(data.get("metadata", {})),
                current_user.id,
            ),
        )
        interaction = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "interaction": dict(interaction),
                "message": "Interaction added",
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error adding interaction: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SEGMENTS
# ============================================================================


@crm_bp.route("/api/segments", methods=["GET"])
@login_required
def get_segments():
    """Get all segments"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT s.*, u.username as created_by_name
            FROM crm_segments s
            LEFT JOIN users u ON s.created_by = u.id
            ORDER BY s.name
        """
        )
        segments = cur.fetchall()

        return jsonify({"success": True, "segments": [dict(s) for s in segments]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/segments", methods=["POST"])
@login_required
def create_segment():
    """Create a new segment"""
    try:
        data = request.get_json()

        if not data.get("name"):
            return jsonify({"success": False, "error": "Segment name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO crm_segments
            (name, description, filter_criteria, is_dynamic, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data["name"],
                data.get("description", ""),
                json.dumps(data.get("filter_criteria", {})),
                data.get("is_dynamic", True),
                current_user.id,
            ),
        )
        segment = cur.fetchone()

        conn.commit()

        return jsonify({"success": True, "segment": dict(segment), "message": "Segment created"})
    except Exception as e:
        current_app.logger.error(f"[CRM] Error creating segment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/segments/<int:segment_id>", methods=["PUT"])
@login_required
def update_segment(segment_id):
    """Update segment"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE crm_segments
            SET name = COALESCE(%s, name),
                description = COALESCE(%s, description),
                filter_criteria = COALESCE(%s, filter_criteria),
                is_dynamic = COALESCE(%s, is_dynamic),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("description"),
                (json.dumps(data["filter_criteria"]) if "filter_criteria" in data else None),
                data.get("is_dynamic"),
                segment_id,
            ),
        )
        segment = cur.fetchone()

        if not segment:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Segment not found"}), 404

        conn.commit()

        return jsonify({"success": True, "segment": dict(segment)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/segments/<int:segment_id>", methods=["DELETE"])
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
            return jsonify({"success": False, "error": "Segment not found"}), 404

        conn.commit()

        return jsonify({"success": True, "message": f"Segment '{segment['name']}' deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/segments/<int:segment_id>/customers", methods=["GET"])
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
            return jsonify({"success": False, "error": "Segment not found"}), 404

        # Build query based on filter criteria
        filter_criteria = segment["filter_criteria"] or {}
        where_clauses = ["is_active = true"]
        params = []

        # Apply dynamic filters
        if filter_criteria.get("subscription_status"):
            where_clauses.append("subscription_status = %s")
            params.append(filter_criteria["subscription_status"])

        if filter_criteria.get("lifetime_value_gt"):
            where_clauses.append("lifetime_value > %s")
            params.append(filter_criteria["lifetime_value_gt"])

        if filter_criteria.get("total_orders"):
            where_clauses.append("total_orders = %s")
            params.append(filter_criteria["total_orders"])

        if filter_criteria.get("created_this_month"):
            where_clauses.append("created_at > DATE_TRUNC('month', NOW())")

        if filter_criteria.get("source"):
            where_clauses.append("source = %s")
            params.append(filter_criteria["source"])

        where_sql = " AND ".join(where_clauses)

        cur.execute(
            f"""
            SELECT id, email, first_name, last_name, company, subscription_tier,
                   subscription_status, total_orders, lifetime_value, created_at
            FROM crm_customers
            WHERE {where_sql}
            ORDER BY created_at DESC
        """,
            params,
        )
        customers = cur.fetchall()

        # Update segment count
        cur.execute(
            """
            UPDATE crm_segments SET customer_count = %s WHERE id = %s
        """,
            (len(customers), segment_id),
        )
        conn.commit()

        return jsonify(
            {
                "success": True,
                "segment": dict(segment),
                "customers": [dict(c) for c in customers],
                "count": len(customers),
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting segment customers: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/segments/<int:segment_id>/add-customer", methods=["POST"])
@login_required
def add_customer_to_segment(segment_id):
    """Add customer to static segment"""
    try:
        data = request.get_json()
        customer_id = data.get("customer_id")

        if not customer_id:
            return jsonify({"success": False, "error": "Customer ID is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO crm_segment_members (segment_id, customer_id)
            VALUES (%s, %s)
            ON CONFLICT (segment_id, customer_id) DO NOTHING
        """,
            (segment_id, customer_id),
        )

        # Update segment count
        cur.execute(
            """
            UPDATE crm_segments
            SET customer_count = (SELECT COUNT(*) FROM crm_segment_members WHERE segment_id = %s)
            WHERE id = %s
        """,
            (segment_id, segment_id),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Customer added to segment"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# IMPORT/EXPORT
# ============================================================================


@crm_bp.route("/api/import", methods=["POST"])
@login_required
def import_customers():
    """Import customers from CSV"""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        file = request.files["file"]
        if not file.filename.endswith(".csv"):
            return jsonify({"success": False, "error": "File must be CSV format"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Create import record
        cur.execute(
            """
            INSERT INTO crm_imports (filename, status, created_by)
            VALUES (%s, 'processing', %s)
            RETURNING id
        """,
            (file.filename, current_user.id),
        )
        import_id = cur.fetchone()["id"]
        conn.commit()

        # Parse CSV
        stream = io.StringIO(file.stream.read().decode("utf-8"))
        reader = csv.DictReader(stream)

        imported = 0
        failed = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            try:
                email = row.get("email", "").strip()
                if not email:
                    errors.append({"row": row_num, "error": "Missing email"})
                    failed += 1
                    continue

                # Insert or update customer
                cur.execute(
                    """
                    INSERT INTO crm_customers
                    (email, first_name, last_name, phone, company, city, source, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'import', %s)
                    ON CONFLICT (email) DO UPDATE SET
                        first_name = COALESCE(EXCLUDED.first_name, crm_customers.first_name),
                        last_name = COALESCE(EXCLUDED.last_name, crm_customers.last_name),
                        phone = COALESCE(EXCLUDED.phone, crm_customers.phone),
                        company = COALESCE(EXCLUDED.company, crm_customers.company),
                        updated_at = NOW()
                """,
                    (
                        email,
                        row.get("first_name", ""),
                        row.get("last_name", ""),
                        row.get("phone", ""),
                        row.get("company", ""),
                        row.get("city", ""),
                        current_user.id,
                    ),
                )
                imported += 1

            except Exception as e:
                errors.append({"row": row_num, "error": str(e)})
                failed += 1

        # Update import record
        cur.execute(
            """
            UPDATE crm_imports
            SET total_rows = %s, imported_rows = %s, failed_rows = %s,
                errors = %s, status = 'completed', completed_at = NOW()
            WHERE id = %s
        """,
            (imported + failed, imported, failed, json.dumps(errors), import_id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "imported": imported,
                "failed": failed,
                "errors": errors[:10],  # Return first 10 errors
                "import_id": import_id,
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Import error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/export", methods=["GET"])
@login_required
def export_customers():
    """Export customers to CSV"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        segment_id = request.args.get("segment_id")

        if segment_id:
            cur.execute(
                """
                SELECT c.* FROM crm_customers c
                JOIN crm_segment_members sm ON c.id = sm.customer_id
                WHERE sm.segment_id = %s AND c.is_active = true
                ORDER BY c.email
            """,
                (segment_id,),
            )
        else:
            cur.execute(
                """
                SELECT * FROM crm_customers
                WHERE is_active = true
                ORDER BY email
            """
            )
        customers = cur.fetchall()

        # Build CSV
        output = io.StringIO()
        if customers:
            fieldnames = [
                "email",
                "first_name",
                "last_name",
                "phone",
                "company",
                "city",
                "state",
                "country",
                "subscription_tier",
                "subscription_status",
                "total_orders",
                "lifetime_value",
                "source",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for customer in customers:
                writer.writerow(dict(customer))

        return jsonify(
            {
                "success": True,
                "csv": output.getvalue(),
                "count": len(customers),
                "filename": f"crm_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATS & ANALYTICS
# ============================================================================


@crm_bp.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    """Get CRM dashboard stats"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats
        cur.execute(
            """
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
        """
        )
        stats = cur.fetchone()

        # Growth trend (last 30 days)
        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM crm_customers
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        )
        growth_trend = cur.fetchall()

        # Source breakdown
        cur.execute(
            """
            SELECT source, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY source
            ORDER BY count DESC
        """
        )
        source_breakdown = cur.fetchall()

        # Subscription breakdown
        cur.execute(
            """
            SELECT subscription_status, COUNT(*) as count
            FROM crm_customers
            WHERE is_active = true
            GROUP BY subscription_status
            ORDER BY count DESC
        """
        )
        subscription_breakdown = cur.fetchall()

        # Interaction stats (last 30 days)
        cur.execute(
            """
            SELECT interaction_type, COUNT(*) as count
            FROM crm_interactions
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY interaction_type
            ORDER BY count DESC
        """
        )
        interaction_stats = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "stats": dict(stats),
                "growth_trend": [dict(g) for g in growth_trend],
                "source_breakdown": [dict(s) for s in source_breakdown],
                "subscription_breakdown": [dict(s) for s in subscription_breakdown],
                "interaction_stats": [dict(i) for i in interaction_stats],
            }
        )
    except Exception as e:
        current_app.logger.error(f"[CRM] Error getting stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SEARCH & QUICK ACTIONS
# ============================================================================


@crm_bp.route("/api/search", methods=["GET"])
@login_required
def search_customers():
    """Quick search for customers"""
    try:
        query = request.args.get("q", "")
        if len(query) < 2:
            return jsonify({"success": True, "results": []})

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, email, first_name, last_name, company, phone
            FROM crm_customers
            WHERE is_active = true
              AND (email ILIKE %s OR first_name ILIKE %s OR last_name ILIKE %s
                   OR company ILIKE %s OR phone ILIKE %s)
            ORDER BY
                CASE WHEN email ILIKE %s THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT 10
        """,
            (f"%{query}%",) * 5 + (f"{query}%",),
        )
        results = cur.fetchall()

        return jsonify({"success": True, "results": [dict(r) for r in results]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/quick-create", methods=["POST"])
@login_required
def quick_create_customer():
    """Quick create customer from other modules"""
    try:
        data = request.get_json()
        email = data.get("email")
        source = data.get("source", "manual")

        if not email:
            return jsonify({"success": False, "error": "Email is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if exists
        cur.execute("SELECT id, email FROM crm_customers WHERE email = %s", (email,))
        existing = cur.fetchone()

        if existing:
            # Update last interaction
            cur.execute(
                """
                UPDATE crm_customers
                SET last_interaction_date = NOW(), updated_at = NOW()
                WHERE id = %s
            """,
                (existing["id"],),
            )
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "customer_id": existing["id"], "existing": True})

        # Create new
        cur.execute(
            """
            INSERT INTO crm_customers (email, first_name, last_name, phone, source, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                email,
                data.get("first_name", ""),
                data.get("last_name", ""),
                data.get("phone", ""),
                source,
                current_user.id,
            ),
        )
        customer_id = cur.fetchone()["id"]

        conn.commit()

        return jsonify({"success": True, "customer_id": customer_id, "existing": False})
    except Exception as e:
        current_app.logger.error(f"[CRM] Quick create error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INTEGRATION ENDPOINTS (for other modules)
# ============================================================================


@crm_bp.route("/api/from-order", methods=["POST"])
@login_required
def create_from_order():
    """Create/update customer from store order"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
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
        """,
            (
                data.get("email"),
                data.get("first_name", ""),
                data.get("last_name", ""),
                data.get("phone", ""),
                data.get("address", ""),
                data.get("city", ""),
                data.get("state", ""),
                data.get("postal_code", ""),
                data.get("country", "Canada"),
                data.get("total", 0),
                current_user.id,
            ),
        )
        customer_id = cur.fetchone()["id"]

        # Log the order interaction
        cur.execute(
            """
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, 'order', %s, %s, %s, %s)
        """,
            (
                customer_id,
                f"Order #{data.get('order_id', 'N/A')}",
                f"Order placed: ${data.get('total', 0):.2f}",
                json.dumps({"order_id": data.get("order_id"), "total": data.get("total")}),
                current_user.id,
            ),
        )

        conn.commit()

        return jsonify({"success": True, "customer_id": customer_id})
    except Exception as e:
        current_app.logger.error(f"[CRM] Create from order error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/from-call", methods=["POST"])
@login_required
def create_from_call():
    """Create/update customer from call center"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Try to find by phone first, then email
        phone = data.get("phone", "")
        email = data.get("email", "")

        cur.execute(
            """
            SELECT id FROM crm_customers
            WHERE (phone = %s AND phone != '') OR (email = %s AND email != '')
            LIMIT 1
        """,
            (phone, email),
        )
        existing = cur.fetchone()

        if existing:
            customer_id = existing["id"]
            cur.execute(
                """
                UPDATE crm_customers
                SET last_interaction_date = NOW(), updated_at = NOW()
                WHERE id = %s
            """,
                (customer_id,),
            )
        else:
            # Create new with phone or generate email
            if not email:
                email = f"phone_{phone.replace('+', '').replace('-', '')}@unknown.temp"

            cur.execute(
                """
                INSERT INTO crm_customers
                (email, first_name, last_name, phone, source, created_by)
                VALUES (%s, %s, %s, %s, 'call_center', %s)
                RETURNING id
            """,
                (
                    email,
                    data.get("first_name", ""),
                    data.get("last_name", ""),
                    phone,
                    current_user.id,
                ),
            )
            customer_id = cur.fetchone()["id"]

        # Log the call interaction
        cur.execute(
            """
            INSERT INTO crm_interactions
            (customer_id, interaction_type, subject, content, metadata, created_by)
            VALUES (%s, 'call', %s, %s, %s, %s)
        """,
            (
                customer_id,
                f"Call - {data.get('direction', 'inbound')}",
                data.get("summary", "Phone call recorded"),
                json.dumps(
                    {
                        "duration": data.get("duration"),
                        "call_id": data.get("call_id"),
                        "direction": data.get("direction"),
                    }
                ),
                current_user.id,
            ),
        )

        conn.commit()

        return jsonify({"success": True, "customer_id": customer_id})
    except Exception as e:
        current_app.logger.error(f"[CRM] Create from call error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/update-subscription", methods=["POST"])
@login_required
def update_subscription():
    """Update customer subscription status"""
    try:
        data = request.get_json()
        customer_id = data.get("customer_id")
        email = data.get("email")

        if not customer_id and not email:
            return (
                jsonify({"success": False, "error": "Customer ID or email required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where = "id = %s" if customer_id else "email = %s"
        param = customer_id or email

        cur.execute(
            f"""
            UPDATE crm_customers
            SET subscription_tier = %s,
                subscription_status = %s,
                subscription_id = %s,
                updated_at = NOW()
            WHERE {where}
            RETURNING id
        """,
            (data.get("tier"), data.get("status"), data.get("subscription_id"), param),
        )
        result = cur.fetchone()

        if result:
            # Log subscription change
            cur.execute(
                """
                INSERT INTO crm_interactions
                (customer_id, interaction_type, subject, content, metadata, created_by)
                VALUES (%s, 'subscription', %s, %s, %s, %s)
            """,
                (
                    result["id"],
                    f"Subscription {data.get('status')}",
                    f"Tier: {data.get('tier')} - Status: {data.get('status')}",
                    json.dumps(data),
                    current_user.id,
                ),
            )

        conn.commit()

        return jsonify({"success": True, "updated": result is not None})
    except Exception as e:
        current_app.logger.error(f"[CRM] Update subscription error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@crm_bp.route("/api/status")
def status():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) FROM crm_customers")
        count = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "crm",
                "status": "healthy",
                "healthy": True,
                "customers": count,
                "message": f"CRM operational with {count} customers",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "module": "crm",
                    "status": "error",
                    "healthy": False,
                    "message": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# BUSINESS ANALYTICS SECTION
# Merged from analytics module 2026-02-03
# Features: Revenue tracking, metrics, charts, dashboards, goals, reports, snapshots
# ============================================================================


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def calculate_change(current, previous):
    """Calculate percentage change"""
    if not previous or previous == 0:
        return 0 if not current else 100
    return round(((float(current) - float(previous)) / float(previous)) * 100, 1)


def safe_query(query, params=None, default=None):
    """Execute query safely, returning default on error"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        result = cur.fetchone() if default is not None else cur.fetchall()
        return result or default
    except Exception as e:
        current_app.logger.error(f"Query error: {e}")
        return default
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS DASHBOARD
# ============================================================================


@crm_bp.route("/analytics")
@login_required
def analytics_dashboard():
    """Business Analytics dashboard - unified metrics view"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get live metrics from various sources
        metrics = {}

        # Revenue metrics (from invoices)
        cur.execute(
            """
            SELECT
                COALESCE(SUM(total) FILTER (WHERE paid_at IS NOT NULL), 0) as total_revenue,
                COALESCE(SUM(total) FILTER (WHERE paid_at >= NOW() - INTERVAL '30 days'), 0) as revenue_30d,
                COALESCE(SUM(total) FILTER (WHERE paid_at >= NOW() - INTERVAL '7 days'), 0) as revenue_7d,
                COALESCE(SUM(total) FILTER (WHERE paid_at::DATE = CURRENT_DATE), 0) as revenue_today
            FROM invoices
        """
        )
        revenue = cur.fetchone() or {}
        metrics.update(revenue)

        # Customer metrics (from CRM)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') as new_customers_30d,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as new_customers_7d,
                COUNT(*) FILTER (WHERE last_activity >= NOW() - INTERVAL '30 days') as active_customers
            FROM crm_customers
        """
        )
        customers = cur.fetchone() or {}
        metrics.update(customers)

        # Subscription metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_subscriptions,
                COUNT(*) FILTER (WHERE status = 'active') as active_subscriptions,
                COALESCE(SUM(amount) FILTER (
                    WHERE status = 'active' AND billing_cycle = 'monthly'), 0) as mrr,
                COUNT(*) FILTER (
                    WHERE next_billing_date <= NOW() + INTERVAL '7 days'
                    AND status = 'active') as renewals_upcoming
            FROM subscription_schedules
        """
        )
        subscriptions = cur.fetchone() or {}
        metrics["mrr"] = subscriptions.get("mrr", 0)
        metrics["arr"] = float(metrics.get("mrr", 0)) * 12
        metrics.update(subscriptions)

        # Invoice metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_invoices,
                COUNT(*) FILTER (WHERE status = 'draft') as invoices_draft,
                COUNT(*) FILTER (WHERE status IN ('sent', 'open')) as invoices_outstanding,
                COUNT(*) FILTER (WHERE status = 'overdue') as invoices_overdue,
                COUNT(*) FILTER (WHERE status = 'paid') as invoices_paid,
                COALESCE(SUM(balance_due) FILTER (WHERE status IN ('sent', 'open', 'overdue')), 0) as amount_outstanding
            FROM invoices
        """
        )
        invoices = cur.fetchone() or {}
        metrics.update(invoices)

        # Email metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_emails,
                COUNT(*) FILTER (WHERE sent_at IS NOT NULL) as emails_sent,
                COUNT(*) FILTER (WHERE opened_at IS NOT NULL) as emails_opened,
                COUNT(*) FILTER (WHERE clicked_at IS NOT NULL) as emails_clicked
            FROM email_logs
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """
        )
        emails = cur.fetchone() or {}
        emails["email_open_rate"] = round(
            (emails.get("emails_opened", 0) / max(emails.get("emails_sent", 1), 1)) * 100,
            1,
        )
        metrics.update(emails)

        # Event metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(*) FILTER (
                    WHERE start_time >= NOW()
                    AND start_time < NOW() + INTERVAL '7 days') as upcoming_events,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_events
            FROM calendar_events
            WHERE start_time >= NOW() - INTERVAL '30 days'
        """
        )
        events = cur.fetchone() or {}
        metrics.update(events)

        # Get chart data - Revenue trend (last 30 days)
        cur.execute(
            """
            SELECT
                paid_at::DATE as date,
                SUM(total) as revenue
            FROM invoices
            WHERE paid_at >= NOW() - INTERVAL '30 days'
            GROUP BY paid_at::DATE
            ORDER BY date
        """
        )
        revenue_trend = cur.fetchall()

        # Get chart data - New customers (last 30 days)
        cur.execute(
            """
            SELECT
                created_at::DATE as date,
                COUNT(*) as count
            FROM crm_customers
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY created_at::DATE
            ORDER BY date
        """
        )
        customer_trend = cur.fetchall()

        # Get top customers
        cur.execute(
            """
            SELECT
                c.id, c.first_name, c.last_name, c.email, c.company,
                c.total_spent, c.subscription_tier, c.total_orders
            FROM crm_customers c
            ORDER BY c.total_spent DESC NULLS LAST
            LIMIT 10
        """
        )
        top_customers = cur.fetchall()

        # Get recent activity
        cur.execute(
            """
            (SELECT 'invoice' as type,
                'Invoice ' || invoice_number || ' paid' as description,
                paid_at as timestamp
             FROM invoices WHERE paid_at IS NOT NULL ORDER BY paid_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'customer' as type,
                'New customer: ' || first_name || ' ' || last_name as description,
                created_at as timestamp
             FROM crm_customers ORDER BY created_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'email' as type,
                'Email sent to ' || recipient as description,
                sent_at as timestamp
             FROM email_logs WHERE sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 5)
            ORDER BY timestamp DESC
            LIMIT 10
        """
        )
        recent_activity = cur.fetchall()

        # Get goals
        cur.execute(
            """
            SELECT * FROM analytics_goals
            WHERE status = 'in_progress'
            ORDER BY end_date
            LIMIT 5
        """
        )
        goals = cur.fetchall()

        return render_template(
            "tools/analytics.html",
            metrics=metrics,
            revenue_trend=json.dumps([dict(r) for r in revenue_trend], default=json_serial),
            customer_trend=json.dumps([dict(c) for c in customer_trend], default=json_serial),
            top_customers=top_customers,
            recent_activity=recent_activity,
            goals=goals,
        )

    except Exception as e:
        current_app.logger.error(f"Analytics dashboard error: {str(e)}")
        return render_template(
            "tools/analytics.html",
            metrics={},
            revenue_trend="[]",
            customer_trend="[]",
            top_customers=[],
            recent_activity=[],
            goals=[],
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS METRICS API
# ============================================================================


@crm_bp.route("/api/analytics/metrics")
@login_required
def get_analytics_metrics():
    """Get all business metrics"""
    try:
        period = request.args.get("period", "30d")

        # Parse period
        days = 30
        if period == "7d":
            days = 7
        elif period == "90d":
            days = 90
        elif period == "year":
            days = 365

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        metrics = {}

        # Revenue
        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) as value
            FROM invoices WHERE paid_at >= NOW() - (%s * INTERVAL '1 day')
        """,
            (days,),
        )
        metrics["revenue"] = cur.fetchone()["value"]

        # Previous period for comparison
        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) as value
            FROM invoices WHERE paid_at >= NOW() - (%s * INTERVAL '1 day')
              AND paid_at < NOW() - (%s * INTERVAL '1 day')
        """,
            (days * 2, days),
        )
        prev_revenue = cur.fetchone()["value"]
        metrics["revenue_change"] = calculate_change(metrics["revenue"], prev_revenue)

        # Customers
        cur.execute("SELECT COUNT(*) as value FROM crm_customers")
        metrics["customers"] = cur.fetchone()["value"]

        cur.execute(
            """
            SELECT COUNT(*) as value FROM crm_customers
            WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
        """,
            (days,),
        )
        metrics["new_customers"] = cur.fetchone()["value"]

        # MRR
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as value
            FROM subscription_schedules
            WHERE status = 'active' AND billing_cycle = 'monthly'
        """
        )
        metrics["mrr"] = cur.fetchone()["value"]
        metrics["arr"] = float(metrics["mrr"]) * 12

        # Invoices outstanding
        cur.execute(
            """
            SELECT COALESCE(SUM(balance_due), 0) as value
            FROM invoices WHERE status IN ('sent', 'open', 'overdue')
        """
        )
        metrics["outstanding"] = cur.fetchone()["value"]

        # Email metrics
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE sent_at IS NOT NULL) as sent,
                COUNT(*) FILTER (WHERE opened_at IS NOT NULL) as opened
            FROM email_logs WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
        """,
            (days,),
        )
        email_data = cur.fetchone()
        metrics["emails_sent"] = email_data["sent"]
        metrics["email_open_rate"] = round((email_data["opened"] / max(email_data["sent"], 1)) * 100, 1)

        return jsonify(
            {
                "success": True,
                "metrics": json.loads(json.dumps(metrics, default=json_serial)),
                "period": period,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/metrics/<metric_name>")
@login_required
def get_analytics_metric(metric_name):
    """Get a specific metric value"""
    try:
        date_from = request.args.get("from")
        date_to = request.args.get("to")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT get_metric_value(%s, %s::DATE, %s::DATE) as value
        """,
            (metric_name, date_from, date_to),
        )

        result = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "metric": metric_name,
                "value": float(result["value"]) if result else 0,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS CHART DATA API
# ============================================================================


@crm_bp.route("/api/analytics/charts/revenue")
@login_required
def get_revenue_chart():
    """Get revenue chart data"""
    try:
        period = request.args.get("period", "30d")
        group_by = request.args.get("group_by", "day")

        days = {"7d": 7, "30d": 30, "90d": 90, "year": 365}.get(period, 30)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if group_by == "day":
            cur.execute(
                """
                SELECT
                    paid_at::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY paid_at::DATE
                ORDER BY date
            """,
                (days,),
            )
        elif group_by == "week":
            cur.execute(
                """
                SELECT
                    DATE_TRUNC('week', paid_at)::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY DATE_TRUNC('week', paid_at)
                ORDER BY date
            """,
                (days,),
            )
        else:  # month
            cur.execute(
                """
                SELECT
                    DATE_TRUNC('month', paid_at)::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY DATE_TRUNC('month', paid_at)
                ORDER BY date
            """,
                (days,),
            )

        data = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": json.loads(json.dumps([dict(d) for d in data], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/charts/customers")
@login_required
def get_customers_chart():
    """Get customer growth chart data"""
    try:
        period = request.args.get("period", "30d")

        days = {"7d": 7, "30d": 30, "90d": 90, "year": 365}.get(period, 30)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                created_at::DATE as date,
                COUNT(*) as new_customers,
                SUM(COUNT(*)) OVER (ORDER BY created_at::DATE) as cumulative
            FROM crm_customers
            WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY created_at::DATE
            ORDER BY date
        """,
            (days,),
        )

        data = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "data": json.loads(json.dumps([dict(d) for d in data], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/charts/subscriptions")
@login_required
def get_subscriptions_chart():
    """Get subscription metrics chart"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Subscription by tier
        cur.execute(
            """
            SELECT tier, COUNT(*) as count, SUM(amount) as revenue
            FROM subscription_schedules
            WHERE status = 'active'
            GROUP BY tier
            ORDER BY revenue DESC
        """
        )
        by_tier = cur.fetchall()

        # Subscription by status
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM subscription_schedules
            GROUP BY status
        """
        )
        by_status = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "by_tier": json.loads(json.dumps([dict(d) for d in by_tier], default=json_serial)),
                "by_status": [dict(d) for d in by_status],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS DASHBOARDS API
# ============================================================================


@crm_bp.route("/api/analytics/dashboards")
@login_required
def get_analytics_dashboards():
    """Get user's custom dashboards"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_dashboards
            WHERE user_id = %s OR is_public = true
            ORDER BY is_default DESC, name
        """,
            (current_user.id,),
        )

        dashboards = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "dashboards": json.loads(json.dumps([dict(d) for d in dashboards], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/dashboards", methods=["POST"])
@login_required
def create_analytics_dashboard():
    """Create a new custom dashboard"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO analytics_dashboards (name, description, layout, filters, user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("description"),
                json.dumps(data.get("layout", [])),
                json.dumps(data.get("filters", {})),
                current_user.id,
            ),
        )

        dashboard = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "dashboard": json.loads(json.dumps(dict(dashboard), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS GOALS API
# ============================================================================


@crm_bp.route("/api/analytics/goals")
@login_required
def get_analytics_goals():
    """Get business goals"""
    try:
        status = request.args.get("status", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = "SELECT * FROM analytics_goals WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY end_date"

        cur.execute(query, params)
        goals = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "goals": json.loads(json.dumps([dict(g) for g in goals], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/goals", methods=["POST"])
@login_required
def create_analytics_goal():
    """Create a new business goal"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO analytics_goals (
                name, metric_name, target_value, period, start_date, end_date, user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("metric_name"),
                data.get("target_value"),
                data.get("period", "monthly"),
                data.get("start_date"),
                data.get("end_date"),
                current_user.id,
            ),
        )

        goal = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "goal": json.loads(json.dumps(dict(goal), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/goals/<int:goal_id>", methods=["PUT"])
@login_required
def update_analytics_goal(goal_id):
    """Update a business goal"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE analytics_goals SET
                name = COALESCE(%s, name),
                target_value = COALESCE(%s, target_value),
                current_value = COALESCE(%s, current_value),
                status = COALESCE(%s, status),
                progress_percentage = CASE
                    WHEN %s IS NOT NULL AND target_value > 0
                    THEN ROUND((%s::DECIMAL / target_value) * 100, 2)
                    ELSE progress_percentage
                END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("target_value"),
                data.get("current_value"),
                data.get("status"),
                data.get("current_value"),
                data.get("current_value"),
                goal_id,
            ),
        )

        goal = cur.fetchone()
        conn.commit()

        if not goal:
            return jsonify({"success": False, "error": "Goal not found"}), 404

        return jsonify(
            {
                "success": True,
                "goal": json.loads(json.dumps(dict(goal), default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/goals/<int:goal_id>", methods=["DELETE"])
@login_required
def delete_analytics_goal(goal_id):
    """Delete a business goal"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM analytics_goals WHERE id = %s", (goal_id,))
        conn.commit()

        return jsonify({"success": True, "message": "Goal deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS REPORTS API
# ============================================================================


@crm_bp.route("/api/analytics/reports")
@login_required
def get_analytics_reports():
    """Get saved reports"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_reports
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """,
            (current_user.id,),
        )

        reports = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "reports": json.loads(json.dumps([dict(r) for r in reports], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/reports/generate", methods=["POST"])
@login_required
def generate_analytics_report():
    """Generate a business report"""
    try:
        data = request.get_json()
        report_type = data.get("type", "revenue")
        date_from = data.get("from")
        date_to = data.get("to")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if report_type == "revenue":
            cur.execute(
                """
                SELECT
                    paid_at::DATE as date,
                    invoice_number,
                    customer_name,
                    total as amount,
                    payment_method
                FROM invoices i
                LEFT JOIN crm_customers c ON i.customer_id = c.id
                WHERE i.paid_at >= %s AND i.paid_at <= %s
                ORDER BY paid_at DESC
            """,
                (date_from, date_to),
            )
        elif report_type == "customers":
            cur.execute(
                """
                SELECT
                    created_at::DATE as date,
                    first_name, last_name, email,
                    company, subscription_tier, total_spent
                FROM crm_customers
                WHERE created_at >= %s AND created_at <= %s
                ORDER BY created_at DESC
            """,
                (date_from, date_to),
            )
        elif report_type == "subscriptions":
            cur.execute(
                """
                SELECT
                    s.created_at::DATE as date,
                    c.first_name || ' ' || c.last_name as customer_name,
                    s.tier, s.billing_cycle, s.amount, s.status,
                    s.next_billing_date
                FROM subscription_schedules s
                LEFT JOIN crm_customers c ON s.customer_id = c.id
                WHERE s.created_at >= %s AND s.created_at <= %s
                ORDER BY s.created_at DESC
            """,
                (date_from, date_to),
            )
        else:
            return jsonify({"success": False, "error": "Invalid report type"}), 400

        rows = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "report": {
                    "type": report_type,
                    "date_from": date_from,
                    "date_to": date_to,
                    "rows": json.loads(json.dumps([dict(r) for r in rows], default=json_serial)),
                    "count": len(rows),
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS SNAPSHOT API
# ============================================================================


@crm_bp.route("/api/analytics/snapshots/generate", methods=["POST"])
@login_required
def generate_analytics_snapshot():
    """Generate a daily metrics snapshot"""
    try:
        data = request.get_json()
        snapshot_date = data.get("date", date.today().isoformat())

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT generate_daily_snapshot(%s::DATE)", (snapshot_date,))
        snapshot_id = cur.fetchone()[0]
        conn.commit()

        return jsonify(
            {
                "success": True,
                "snapshot_id": snapshot_id,
                "message": f"Snapshot generated for {snapshot_date}",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@crm_bp.route("/api/analytics/snapshots")
@login_required
def get_analytics_snapshots():
    """Get historical snapshots"""
    try:
        days = int(request.args.get("days", 30))
        snapshot_type = request.args.get("type", "daily")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_snapshots
            WHERE snapshot_type = %s
              AND snapshot_date >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY snapshot_date DESC
        """,
            (snapshot_type, days),
        )

        snapshots = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "snapshots": json.loads(json.dumps([dict(s) for s in snapshots], default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS STATUS ENDPOINT
# ============================================================================


@crm_bp.route("/api/analytics/status")
def analytics_status():
    """Get analytics module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM analytics_snapshots")
        snapshot_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM analytics_dashboards")
        dashboard_count = cur.fetchone()[0]

        return jsonify(
            {
                "module": "analytics",
                "status": "operational",
                "healthy": True,
                "snapshots": snapshot_count,
                "dashboards": dashboard_count,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "analytics",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
