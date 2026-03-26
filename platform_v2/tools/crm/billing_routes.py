"""
CRM Billing Routes — admin API endpoints for the Billing tab.

All routes are under the CRM blueprint prefix ``/tools/crm``.
"""

import logging

from flask import jsonify, request, Response
from flask_login import login_required

from tools.crm.billing_service import (
    get_revenue_metrics,
    get_revenue_by_month,
    get_subscription_distribution,
    get_billing_customers,
    get_customer_stripe_detail,
    create_subscription_for_customer,
    cancel_subscription,
    change_subscription_tier,
    link_crm_customer,
    auto_link_by_email,
    export_billing_csv,
)
from database import get_db_cursor

log = logging.getLogger(__name__)


def register_billing_routes(bp, admin_required):
    """Register all /api/billing/* routes on the CRM blueprint."""

    # ------------------------------------------------------------------
    # GET  /api/billing/metrics
    # ------------------------------------------------------------------
    @bp.route("/api/billing/metrics")
    @login_required
    @admin_required
    def api_billing_metrics():
        try:
            metrics = get_revenue_metrics()
            return jsonify(metrics)
        except Exception as e:
            log.exception("billing metrics error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/revenue-by-month
    # ------------------------------------------------------------------
    @bp.route("/api/billing/revenue-by-month")
    @login_required
    @admin_required
    def api_billing_revenue_by_month():
        try:
            months = request.args.get("months", 12, type=int)
            data = get_revenue_by_month(months)
            return jsonify(data)
        except Exception as e:
            log.exception("billing revenue-by-month error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/distribution
    # ------------------------------------------------------------------
    @bp.route("/api/billing/distribution")
    @login_required
    @admin_required
    def api_billing_distribution():
        try:
            data = get_subscription_distribution()
            return jsonify(data)
        except Exception as e:
            log.exception("billing distribution error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/customers
    # ------------------------------------------------------------------
    @bp.route("/api/billing/customers")
    @login_required
    @admin_required
    def api_billing_customers():
        try:
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 25, type=int)
            search = request.args.get("search", "")
            data = get_billing_customers(page, per_page, search)
            return jsonify(data)
        except Exception as e:
            log.exception("billing customers error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/customers/<id>/detail
    # ------------------------------------------------------------------
    @bp.route("/api/billing/customers/<int:id>/detail")
    @login_required
    @admin_required
    def api_billing_customer_detail(id):
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT stripe_customer_id FROM billing_customers WHERE id = %s",
                    (id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"error": "Customer not found"}), 404
            data = get_customer_stripe_detail(row[0])
            if "error" in data:
                return jsonify(data), 400
            return jsonify(data)
        except Exception as e:
            log.exception("billing customer detail error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # POST /api/billing/subscribe
    # ------------------------------------------------------------------
    @bp.route("/api/billing/subscribe", methods=["POST"])
    @login_required
    @admin_required
    def api_billing_subscribe():
        try:
            body = request.get_json(force=True)
            billing_customer_id = body.get("billing_customer_id")
            price_id = body.get("price_id")
            if not billing_customer_id or not price_id:
                return jsonify({"error": "billing_customer_id and price_id required"}), 400
            result = create_subscription_for_customer(billing_customer_id, price_id)
            if "error" in result:
                return jsonify(result), 400
            return jsonify(result)
        except Exception as e:
            log.exception("billing subscribe error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # POST /api/billing/cancel
    # ------------------------------------------------------------------
    @bp.route("/api/billing/cancel", methods=["POST"])
    @login_required
    @admin_required
    def api_billing_cancel():
        try:
            body = request.get_json(force=True)
            subscription_id = body.get("subscription_id")
            if not subscription_id:
                return jsonify({"error": "subscription_id required"}), 400
            result = cancel_subscription(subscription_id)
            if "error" in result:
                return jsonify(result), 400
            return jsonify(result)
        except Exception as e:
            log.exception("billing cancel error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # POST /api/billing/change-tier
    # ------------------------------------------------------------------
    @bp.route("/api/billing/change-tier", methods=["POST"])
    @login_required
    @admin_required
    def api_billing_change_tier():
        try:
            body = request.get_json(force=True)
            subscription_id = body.get("subscription_id")
            new_price_id = body.get("new_price_id")
            if not subscription_id or not new_price_id:
                return jsonify({"error": "subscription_id and new_price_id required"}), 400
            result = change_subscription_tier(subscription_id, new_price_id)
            if "error" in result:
                return jsonify(result), 400
            return jsonify(result)
        except Exception as e:
            log.exception("billing change-tier error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # POST /api/billing/link
    # ------------------------------------------------------------------
    @bp.route("/api/billing/link", methods=["POST"])
    @login_required
    @admin_required
    def api_billing_link():
        try:
            body = request.get_json(force=True)
            crm_customer_id = body.get("crm_customer_id")
            billing_customer_id = body.get("billing_customer_id")
            if not crm_customer_id or not billing_customer_id:
                return jsonify({"error": "crm_customer_id and billing_customer_id required"}), 400
            result = link_crm_customer(crm_customer_id, billing_customer_id)
            return jsonify(result)
        except Exception as e:
            log.exception("billing link error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # POST /api/billing/auto-link
    # ------------------------------------------------------------------
    @bp.route("/api/billing/auto-link", methods=["POST"])
    @login_required
    @admin_required
    def api_billing_auto_link():
        try:
            count = auto_link_by_email()
            return jsonify({"linked": count})
        except Exception as e:
            log.exception("billing auto-link error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/export
    # ------------------------------------------------------------------
    @bp.route("/api/billing/export")
    @login_required
    @admin_required
    def api_billing_export():
        try:
            csv_data = export_billing_csv()
            return Response(
                csv_data,
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=billing_export.csv"},
            )
        except Exception as e:
            log.exception("billing export error")
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------
    # GET  /api/billing/products
    # ------------------------------------------------------------------
    @bp.route("/api/billing/products")
    @login_required
    @admin_required
    def api_billing_products():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, stripe_product_id, stripe_price_id,
                              module, name, amount_cents, currency, interval,
                              active, created_at
                       FROM billing_products
                       ORDER BY module, name"""
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            products = [dict(zip(cols, r)) for r in rows]
            return jsonify(products)
        except Exception as e:
            log.exception("billing products error")
            return jsonify({"error": str(e)}), 500
