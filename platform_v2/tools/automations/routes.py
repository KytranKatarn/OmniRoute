"""
Automations Routes
==================
N8N workflow integration for A.R.C.H.I.E. Business Tools.

Features:
- View active workflows
- Execution stats and monitoring
- Pre-built workflow templates
- Direct link to N8N editor
- Workflow management (activate/deactivate)

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, date
import os
from database import _get_db_password
import json
import requests
from decimal import Decimal

# Import user context helpers
try:
    from services.user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
automations_bp = Blueprint(
    "automations",
    __name__,
    url_prefix="/tools/automations",
    template_folder="../../templates/tools",
)

# N8N Configuration
N8N_HOST = os.getenv("N8N_HOST", "http://n8n:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def n8n_request(endpoint, method="GET", data=None):
    """Make a request to N8N API"""
    try:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if N8N_API_KEY:
            headers["X-N8N-API-KEY"] = N8N_API_KEY

        url = f"{N8N_HOST}/api/v1/{endpoint}"

        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=10)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data, timeout=10)
        else:
            return None

        if response.status_code in [200, 201]:
            return response.json()
        else:
            current_app.logger.warning(f"N8N API error: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"N8N connection error: {str(e)}")
        return None


# Service Tier definitions (merged from automation_services)
SERVICE_TIERS = [
    {
        "name": "Bronze",
        "description": "Foundational automations for basic efficiency",
        "complexity": "low",
        "node_count": "1-5",
        "example": "Automated email notifications, basic form to sheet",
    },
    {
        "name": "Silver",
        "description": "Enhanced automation with multiple integrations",
        "complexity": "medium",
        "node_count": "5-15",
        "example": "CRM lead nurturing, social media scheduling",
    },
    {
        "name": "Gold",
        "description": "Advanced AI & business process orchestration",
        "complexity": "high",
        "node_count": "15+",
        "example": "AI chatbots, market research automation, data pipelines",
    },
]

# Pre-built workflow templates
WORKFLOW_TEMPLATES = [
    {
        "id": "welcome_email",
        "name": "New Customer Welcome",
        "description": "Send welcome email when a new customer is added to CRM",
        "category": "Customer",
        "tier": "Bronze",
        "trigger": "CRM Customer Created",
        "actions": ["Send Email", "Add to Segment"],
    },
    {
        "id": "order_confirmation",
        "name": "Order Confirmation",
        "description": "Generate invoice and send confirmation when order is placed",
        "category": "Orders",
        "tier": "Silver",
        "trigger": "Store Order Placed",
        "actions": ["Create Invoice", "Send Email", "Update CRM"],
    },
    {
        "id": "subscription_renewal",
        "name": "Subscription Renewal",
        "description": "Auto-charge and send receipt for recurring subscriptions",
        "category": "Billing",
        "tier": "Gold",
        "trigger": "Scheduler Renewal Date",
        "actions": ["Charge Stripe", "Generate Invoice", "Send Receipt"],
    },
    {
        "id": "failed_payment",
        "name": "Failed Payment Handler",
        "description": "Send reminder and schedule retry for failed payments",
        "category": "Billing",
        "tier": "Silver",
        "trigger": "Stripe Webhook (Failed)",
        "actions": ["Send Reminder Email", "Update CRM Status", "Schedule Retry"],
    },
    {
        "id": "call_escalation",
        "name": "Call Escalation",
        "description": "Create CRM ticket and notify manager on escalated calls",
        "category": "Support",
        "tier": "Silver",
        "trigger": "Call Center Escalation",
        "actions": ["Create CRM Ticket", "Notify Manager", "Schedule Callback"],
    },
    {
        "id": "low_satisfaction",
        "name": "Low Satisfaction Alert",
        "description": "Alert manager and create follow-up for low satisfaction scores",
        "category": "Support",
        "tier": "Bronze",
        "trigger": "Call Rating < 3",
        "actions": ["Alert Manager", "Create Follow-up Task"],
    },
    {
        "id": "invoice_reminder",
        "name": "Invoice Reminder",
        "description": "Send reminder emails for upcoming and overdue invoices",
        "category": "Billing",
        "tier": "Bronze",
        "trigger": "Scheduler (Daily)",
        "actions": ["Check Invoices", "Send Reminders"],
    },
    {
        "id": "event_reminder",
        "name": "Event Reminder",
        "description": "Send reminders before scheduled events",
        "category": "Calendar",
        "tier": "Bronze",
        "trigger": "Scheduler (Hourly)",
        "actions": ["Check Events", "Send Email/SMS"],
    },
]


# ============================================================================
# MAIN PAGE
# ============================================================================


@automations_bp.route("/")
@login_required
def index():
    """Main Automations dashboard"""
    try:
        # Try to get workflows from N8N
        workflows = []
        executions = []
        n8n_connected = False

        try:
            # Get workflows
            workflow_response = n8n_request("workflows")
            if workflow_response and "data" in workflow_response:
                workflows = workflow_response["data"]
                n8n_connected = True

            # Get recent executions
            exec_response = n8n_request("executions?limit=20")
            if exec_response and "data" in exec_response:
                executions = exec_response["data"]

        except Exception as e:
            current_app.logger.error(f"Error connecting to N8N: {e}")

        # Calculate stats
        stats = {
            "total_workflows": len(workflows),
            "active_workflows": len([w for w in workflows if w.get("active")]),
            "recent_executions": len(executions),
            "success_rate": 0,
            "n8n_connected": n8n_connected,
        }

        # Calculate success rate
        if executions:
            successful = len([e for e in executions if e.get("finished") and not e.get("stoppedAt")])
            stats["success_rate"] = round((successful / len(executions)) * 100, 1) if executions else 0

        return render_template(
            "tools/automations.html",
            workflows=workflows,
            executions=executions[:10],
            templates=WORKFLOW_TEMPLATES,
            stats=stats,
            n8n_url=N8N_HOST.replace("n8n", "localhost"),
        )

    except Exception as e:
        current_app.logger.error(f"Automations index error: {str(e)}")
        return render_template(
            "tools/automations.html",
            workflows=[],
            executions=[],
            templates=WORKFLOW_TEMPLATES,
            stats={"n8n_connected": False},
            error=str(e),
        )


# ============================================================================
# WORKFLOWS API
# ============================================================================


@automations_bp.route("/api/workflows")
@login_required
def get_workflows():
    """Get all workflows from N8N"""
    try:
        response = n8n_request("workflows")

        if response and "data" in response:
            return jsonify({"success": True, "workflows": response["data"]})
        else:
            return jsonify({"success": False, "error": "Could not connect to N8N", "workflows": []})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/api/workflows/<workflow_id>")
@login_required
def get_workflow(workflow_id):
    """Get a specific workflow"""
    try:
        response = n8n_request(f"workflows/{workflow_id}")

        if response:
            return jsonify({"success": True, "workflow": response})
        else:
            return jsonify({"success": False, "error": "Workflow not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/api/workflows/<workflow_id>/activate", methods=["POST"])
@login_required
def activate_workflow(workflow_id):
    """Activate a workflow"""
    try:
        response = n8n_request(f"workflows/{workflow_id}/activate", method="POST")

        if response:
            return jsonify({"success": True, "message": "Workflow activated"})
        else:
            return (
                jsonify({"success": False, "error": "Failed to activate workflow"}),
                400,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/api/workflows/<workflow_id>/deactivate", methods=["POST"])
@login_required
def deactivate_workflow(workflow_id):
    """Deactivate a workflow"""
    try:
        response = n8n_request(f"workflows/{workflow_id}/deactivate", method="POST")

        if response:
            return jsonify({"success": True, "message": "Workflow deactivated"})
        else:
            return (
                jsonify({"success": False, "error": "Failed to deactivate workflow"}),
                400,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# EXECUTIONS API
# ============================================================================


@automations_bp.route("/api/executions")
@login_required
def get_executions():
    """Get workflow executions"""
    try:
        limit = request.args.get("limit", 50)
        workflow_id = request.args.get("workflow_id", "")

        endpoint = f"executions?limit={limit}"
        if workflow_id:
            endpoint += f"&workflowId={workflow_id}"

        response = n8n_request(endpoint)

        if response and "data" in response:
            return jsonify({"success": True, "executions": response["data"]})
        else:
            return jsonify(
                {
                    "success": False,
                    "error": "Could not fetch executions",
                    "executions": [],
                }
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/api/executions/<execution_id>")
@login_required
def get_execution(execution_id):
    """Get execution details"""
    try:
        response = n8n_request(f"executions/{execution_id}")

        if response:
            return jsonify({"success": True, "execution": response})
        else:
            return jsonify({"success": False, "error": "Execution not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TEMPLATES API
# ============================================================================


@automations_bp.route("/api/templates")
@login_required
def get_templates():
    """Get workflow templates"""
    category = request.args.get("category", "")

    templates = WORKFLOW_TEMPLATES
    if category:
        templates = [t for t in templates if t["category"].lower() == category.lower()]

    return jsonify({"success": True, "templates": templates})


@automations_bp.route("/api/templates/<template_id>/create", methods=["POST"])
@login_required
def create_from_template(template_id):
    """Create a workflow from a template"""
    try:
        # Find template
        template = next((t for t in WORKFLOW_TEMPLATES if t["id"] == template_id), None)
        if not template:
            return jsonify({"success": False, "error": "Template not found"}), 404

        # Create workflow definition based on template
        workflow_def = {
            "name": template["name"],
            "active": False,
            "nodes": [],
            "connections": {},
            "settings": {},
        }

        # For now, return the N8N editor URL for manual creation
        n8n_url = N8N_HOST.replace("n8n", "localhost")

        return jsonify(
            {
                "success": True,
                "message": f"Template '{template['name']}' ready. Open N8N to configure.",
                "n8n_url": f"{n8n_url}/workflow/new",
                "template": template,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATS API
# ============================================================================


@automations_bp.route("/api/stats")
@login_required
def get_stats():
    """Get automation statistics"""
    try:
        # Get workflows
        workflows = []
        workflow_response = n8n_request("workflows")
        if workflow_response and "data" in workflow_response:
            workflows = workflow_response["data"]

        # Get executions (last 100)
        executions = []
        exec_response = n8n_request("executions?limit=100")
        if exec_response and "data" in exec_response:
            executions = exec_response["data"]

        # Calculate stats
        total_workflows = len(workflows)
        active_workflows = len([w for w in workflows if w.get("active")])
        total_executions = len(executions)

        successful = len([e for e in executions if e.get("finished") and not e.get("stoppedAt")])
        failed = len([e for e in executions if e.get("stoppedAt")])

        success_rate = round((successful / total_executions) * 100, 1) if total_executions > 0 else 0

        # Executions by workflow
        by_workflow = {}
        for e in executions:
            wf_name = e.get("workflowData", {}).get("name", "Unknown")
            by_workflow[wf_name] = by_workflow.get(wf_name, 0) + 1

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_workflows": total_workflows,
                    "active_workflows": active_workflows,
                    "total_executions": total_executions,
                    "successful_executions": successful,
                    "failed_executions": failed,
                    "success_rate": success_rate,
                    "executions_by_workflow": by_workflow,
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# WEBHOOK ENDPOINTS (for N8N to call)
# ============================================================================


@automations_bp.route("/webhook/customer-created", methods=["POST"])
def webhook_customer_created():
    """Webhook for new customer trigger"""
    try:
        data = request.get_json()
        current_app.logger.info(f"Customer created webhook: {data}")
        return jsonify({"success": True, "received": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/webhook/order-placed", methods=["POST"])
def webhook_order_placed():
    """Webhook for order placed trigger"""
    try:
        data = request.get_json()
        current_app.logger.info(f"Order placed webhook: {data}")
        return jsonify({"success": True, "received": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@automations_bp.route("/webhook/invoice-paid", methods=["POST"])
def webhook_invoice_paid():
    """Webhook for invoice paid trigger"""
    try:
        data = request.get_json()
        current_app.logger.info(f"Invoice paid webhook: {data}")
        return jsonify({"success": True, "received": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TIERS API (merged from automation_services)
# ============================================================================


@automations_bp.route("/api/tiers")
@login_required
def get_tiers():
    """Get available service tiers for automation complexity"""
    return jsonify({"success": True, "tiers": SERVICE_TIERS})


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@automations_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        # Check N8N connection
        n8n_connected = False
        workflow_count = 0

        try:
            response = n8n_request("workflows")
            if response and "data" in response:
                n8n_connected = True
                workflow_count = len(response["data"])
        except:
            pass

        return jsonify(
            {
                "module": "automations",
                "status": "operational" if n8n_connected else "degraded",
                "healthy": n8n_connected,
                "n8n_connected": n8n_connected,
                "workflows": workflow_count,
                "n8n_url": N8N_HOST,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "automations",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
