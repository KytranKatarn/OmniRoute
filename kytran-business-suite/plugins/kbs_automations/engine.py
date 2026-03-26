"""Automations Engine — trigger matching, condition evaluation, workflow execution."""

import fnmatch
import logging

from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trigger matching
# ---------------------------------------------------------------------------


def matches_trigger(workflow: dict, event_type: str) -> bool:
    """Return True if *workflow*'s trigger_event matches *event_type*.

    Supports exact matches and wildcard patterns (e.g. ``contact.*`` matches
    ``contact.created``).
    """
    trigger = workflow.get("trigger_event", "")
    if not trigger:
        return False
    # fnmatch handles exact matches and wildcards like "contact.*"
    return fnmatch.fnmatch(event_type, trigger)


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


def evaluate_conditions(conditions: dict, event_data: dict) -> bool:
    """Evaluate workflow conditions against event_data.

    *conditions* is a dict like::

        {"field": "status", "operator": "equals", "value": "active"}

    Supported operators: equals, not_equals, contains, exists.
    Empty (or falsy) conditions always return True.
    Multiple conditions in a list use AND logic.
    """
    if not conditions:
        return True

    # Support both a single condition dict and a list of conditions
    if isinstance(conditions, dict):
        items = [conditions]
    elif isinstance(conditions, list):
        items = conditions
    else:
        return True

    for cond in items:
        if not _evaluate_single_condition(cond, event_data):
            return False
    return True


def _evaluate_single_condition(cond: dict, event_data: dict) -> bool:
    field = cond.get("field")
    operator = cond.get("operator", "equals")
    expected = cond.get("value")

    if not field:
        return True

    actual = event_data.get(field)

    if operator == "equals":
        return actual == expected
    elif operator == "not_equals":
        return actual != expected
    elif operator == "contains":
        if actual is None:
            return False
        return expected in str(actual)
    elif operator == "exists":
        return field in event_data
    else:
        logger.warning("Unknown condition operator: %s", operator)
        return True


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


def execute_action(action: dict, event_data: dict, tenant_id) -> dict:
    """Execute a single workflow action. Returns ``{"success": bool, ...}``."""
    action_type = action.get("type")
    config = action.get("config", {})

    try:
        if action_type == "log":
            message = config.get("message", "Automation triggered")
            logger.info("[Automation] tenant=%s — %s | event_data=%s", tenant_id, message, event_data)
            return {"success": True}

        elif action_type == "create_interaction":
            customer_id = event_data.get("customer_id") or config.get("customer_id")
            if not customer_id:
                return {"success": False, "error": "create_interaction requires customer_id"}

            interaction_type = config.get("interaction_type", "note")
            subject = config.get("subject", "Automated interaction")
            content = config.get("content", "")

            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO crm_interactions (customer_id, type, subject, content, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        customer_id,
                        interaction_type,
                        subject,
                        content,
                        Json({"source": "automation", "event_data": event_data}),
                    ),
                )
                row = cur.fetchone()
            return {"success": True, "interaction_id": row["id"]}

        else:
            logger.warning("[Automation] Unknown action type: %s", action_type)
            return {"success": False, "error": f"unknown action type: {action_type}"}

    except Exception as exc:
        logger.exception("[Automation] Action %s failed", action_type)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Workflow execution
# ---------------------------------------------------------------------------


def execute_workflow(template: dict, event_data: dict, tenant_id) -> dict:
    """Run a full workflow: evaluate conditions, execute actions, log execution.

    Returns the execution result dict.
    """
    template_id = template["id"]
    trigger_event = template.get("trigger_event", "")
    conditions = template.get("conditions") or {}
    actions = template.get("actions") or []

    # --- Create execution record (status=running) ---
    execution_id = None
    try:
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO workflow_executions
                    (template_id, trigger_event, event_data, status)
                VALUES (%s, %s, %s, 'running')
                RETURNING id
                """,
                (template_id, trigger_event, Json(event_data)),
            )
            execution_id = cur.fetchone()["id"]
    except Exception as exc:
        logger.exception("[Automation] Failed to create execution record for template %s", template_id)
        return {"success": False, "error": str(exc)}

    # --- Evaluate conditions ---
    if not evaluate_conditions(conditions, event_data):
        _finish_execution(tenant_id, execution_id, status="completed", result={"skipped": "conditions not met"})
        return {"success": True, "skipped": True, "reason": "conditions not met"}

    # --- Execute each action ---
    action_results = []
    failed = False
    error_message = None

    for idx, action in enumerate(actions):
        result = execute_action(action, event_data, tenant_id)
        action_results.append({"action_index": idx, "type": action.get("type"), **result})
        if not result.get("success"):
            failed = True
            error_message = result.get("error", "unknown error")
            break  # stop on first failure

    final_status = "failed" if failed else "completed"
    final_result = {"actions": action_results}

    _finish_execution(
        tenant_id,
        execution_id,
        status=final_status,
        result=final_result,
        error_message=error_message,
    )

    return {
        "success": not failed,
        "execution_id": execution_id,
        "status": final_status,
        "actions": action_results,
    }


def _finish_execution(tenant_id, execution_id, status, result, error_message=None):
    """Update execution record to completed/failed."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE workflow_executions
                SET status = %s, result = %s, completed_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                (status, Json(result), error_message, execution_id),
            )
    except Exception:
        logger.exception("[Automation] Failed to finish execution record %s", execution_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def process_event(event_type: str, event_data: dict, tenant_id) -> None:
    """Find all active workflows matching *event_type* for *tenant_id* and run them.

    Called by the wildcard event consumer wired in ``__init__.py``.
    """
    try:
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                "SELECT id, name, trigger_event, conditions, actions FROM workflow_templates WHERE is_active = TRUE"
            )
            workflows = cur.fetchall()
    except Exception:
        logger.exception("[Automation] Failed to fetch workflows for tenant %s", tenant_id)
        return

    for workflow in workflows:
        if not matches_trigger(workflow, event_type):
            continue

        logger.info(
            "[Automation] Triggering workflow '%s' (id=%s) for event '%s' tenant=%s",
            workflow["name"],
            workflow["id"],
            event_type,
            tenant_id,
        )
        execute_workflow(workflow, event_data, tenant_id)
