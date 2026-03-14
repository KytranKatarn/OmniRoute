"""Template service — CRUD, versioning, and cloning for Media Studio workflow templates.

Templates are versioned via a parent_id chain. The root row has parent_id IS NULL;
each subsequent version inserts a new row with parent_id pointing to the root.
"""

import logging
from typing import Dict, List, Optional

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STEP_TYPES = {
    "generate",
    "edit_inpaint",
    "edit_outpaint",
    "edit_upscale",
    "edit_img2img",
    "edit_style_transfer",
    "batch",
}

_MAX_VERSION_WALK = 50  # guard against pathological parent chains


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_steps(steps) -> Optional[Dict]:
    """Validate a list of step dicts.

    Returns {"error": str} on failure, None on success.
    """
    if not isinstance(steps, list):
        return {"error": "steps must be a list"}
    if not steps:
        return {"error": "steps must not be empty"}

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return {"error": f"step {i}: must be a dict"}

        step_type = step.get("step_type")
        if step_type not in VALID_STEP_TYPES:
            return {"error": f"step {i}: invalid step_type '{step_type}'. " f"Valid types: {sorted(VALID_STEP_TYPES)}"}

        params = step.get("params", {})

        if step_type == "generate":
            if not params.get("prompt", "").strip():
                return {"error": f"step {i} (generate): params.prompt is required"}

        elif step_type == "edit_inpaint":
            if not params.get("prompt", "").strip():
                return {"error": f"step {i} (edit_inpaint): params.prompt is required"}

        elif step_type == "edit_upscale":
            sf = params.get("scale_factor")
            if sf not in (2, 4):
                return {"error": f"step {i} (edit_upscale): params.scale_factor must be 2 or 4"}

        elif step_type == "edit_img2img":
            if not params.get("prompt", "").strip():
                return {"error": f"step {i} (edit_img2img): params.prompt is required"}

        elif step_type == "edit_style_transfer":
            has_style = params.get("style_prompt", "").strip()
            has_ref = params.get("reference_image_id")
            if not has_style and not has_ref:
                return {
                    "error": f"step {i} (edit_style_transfer): "
                    "params.style_prompt or params.reference_image_id is required"
                }

        elif step_type == "batch":
            prompts = params.get("prompts")
            if not prompts or not isinstance(prompts, list) or len(prompts) == 0:
                return {"error": f"step {i} (batch): params.prompts must be a non-empty list"}

        # edit_outpaint: no strict requirement — direction has a default

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_template(
    name: str,
    description: str,
    steps: List[Dict],
    owner_type: str,
    owner_id: Optional[int],
    visibility: str = "private",
    tags=None,
) -> Dict:
    """Create a new template (version 1, no parent).

    Returns {"template_id": int, "version": 1} or {"error": str}.
    """
    if not name or not name.strip():
        return {"error": "name is required"}

    err = _validate_steps(steps)
    if err:
        return err

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO media_templates
                    (name, description, owner_type, owner_id, visibility, version,
                     parent_id, tags)
                VALUES (%s, %s, %s, %s, %s, 1, NULL, %s)
                RETURNING id, version
                """,
                (
                    name.strip(),
                    description or "",
                    owner_type,
                    owner_id,
                    visibility,
                    psycopg2.extras.Json(tags or []),
                ),
            )
            row = cur.fetchone()
            template_id = row["id"]

            for idx, step in enumerate(steps):
                cur.execute(
                    """
                    INSERT INTO media_template_steps
                        (template_id, step_order, step_type, step_name, params)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        template_id,
                        idx,
                        step["step_type"],
                        step.get("step_name", ""),
                        psycopg2.extras.Json(step.get("params", {})),
                    ),
                )

        return {"template_id": template_id, "version": 1}

    except Exception as exc:
        logger.error("create_template error: %s", exc)
        return {"error": str(exc)}


def update_template(
    template_id: int,
    owner_type: str,
    owner_id: Optional[int],
    updates: Dict,
) -> Dict:
    """Create a new version of an existing template.

    Ownership is checked against the provided template_id row.
    Returns {"template_id": new_id, "version": new_version} or {"error": str}.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # 1. Load existing template and verify ownership
            cur.execute(
                "SELECT * FROM media_templates WHERE id = %s",
                (template_id,),
            )
            original = cur.fetchone()
            if not original:
                return {"error": f"Template {template_id} not found"}

            if original["owner_type"] != owner_type or original["owner_id"] != owner_id:
                return {"error": "Permission denied: not the template owner"}

            # 2. Walk parent_id chain to find root
            root_id = template_id
            iterations = 0
            current = original
            while current["parent_id"] is not None and iterations < _MAX_VERSION_WALK:
                cur.execute(
                    "SELECT * FROM media_templates WHERE id = %s",
                    (current["parent_id"],),
                )
                parent = cur.fetchone()
                if not parent:
                    break
                current = parent
                root_id = current["id"]
                iterations += 1

            # 3. Find max version across entire version chain
            cur.execute(
                """
                SELECT MAX(version)
                FROM media_templates
                WHERE id = %s OR parent_id = %s
                """,
                (root_id, root_id),
            )
            max_version = cur.fetchone()["max"] or 1
            new_version = max_version + 1

            # 4. Build new row values from original + updates
            new_name = updates.get("name", original["name"])
            new_description = updates.get("description", original["description"])
            new_visibility = updates.get("visibility", original["visibility"])
            new_tags = updates.get("tags", original["tags"])

            cur.execute(
                """
                INSERT INTO media_templates
                    (name, description, owner_type, owner_id, visibility, version,
                     parent_id, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, version
                """,
                (
                    new_name,
                    new_description,
                    owner_type,
                    owner_id,
                    new_visibility,
                    new_version,
                    root_id,
                    psycopg2.extras.Json(new_tags if isinstance(new_tags, list) else []),
                ),
            )
            new_row = cur.fetchone()
            new_id = new_row["id"]

            # 5. Copy or insert steps
            if "steps" in updates:
                err = _validate_steps(updates["steps"])
                if err:
                    return err
                for idx, step in enumerate(updates["steps"]):
                    cur.execute(
                        """
                        INSERT INTO media_template_steps
                            (template_id, step_order, step_type, step_name, params)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            new_id,
                            idx,
                            step["step_type"],
                            step.get("step_name", ""),
                            psycopg2.extras.Json(step.get("params", {})),
                        ),
                    )
            else:
                # Copy steps from original template
                cur.execute(
                    """
                    INSERT INTO media_template_steps
                        (template_id, step_order, step_type, step_name, params)
                    SELECT %s, step_order, step_type, step_name, params
                    FROM media_template_steps
                    WHERE template_id = %s
                    ORDER BY step_order
                    """,
                    (new_id, template_id),
                )

        return {"template_id": new_id, "version": new_version}

    except Exception as exc:
        logger.error("update_template error: %s", exc)
        return {"error": str(exc)}


def get_template(template_id: int, include_steps: bool = True) -> Optional[Dict]:
    """Fetch a single template by id.

    Returns a dict (with 'steps' list if include_steps) or None if not found.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM media_templates WHERE id = %s",
                (template_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            result = dict(row)

            if include_steps:
                cur.execute(
                    """
                    SELECT * FROM media_template_steps
                    WHERE template_id = %s
                    ORDER BY step_order
                    """,
                    (template_id,),
                )
                result["steps"] = [dict(s) for s in cur.fetchall()]
            else:
                result["steps"] = []

        return result

    except Exception as exc:
        logger.error("get_template error: %s", exc)
        return None


def list_templates(
    owner_type: Optional[str] = None,
    owner_id: Optional[int] = None,
    visibility_filter: Optional[str] = None,
    tag_filter=None,
) -> List[Dict]:
    """List latest version per template root.

    Returns shared templates plus the owner's own templates. Optionally filter
    by visibility or a tag (JSONB @> match).
    """
    try:
        with get_db_cursor() as (conn, cur):
            where_clauses = ["(t.visibility = 'shared' OR (t.owner_type = %s AND t.owner_id = %s))"]
            params: list = [owner_type, owner_id]

            if visibility_filter:
                where_clauses.append("t.visibility = %s")
                params.append(visibility_filter)

            if tag_filter is not None:
                where_clauses.append("t.tags @> %s")
                params.append(psycopg2.extras.Json([tag_filter]))

            where_sql = " AND ".join(where_clauses)

            cur.execute(
                f"""
                SELECT DISTINCT ON (COALESCE(t.parent_id, t.id)) t.*,
                    (SELECT COUNT(*) FROM media_template_steps
                     WHERE template_id = t.id) AS step_count
                FROM media_templates t
                WHERE {where_sql}
                ORDER BY COALESCE(t.parent_id, t.id), t.version DESC
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    except Exception as exc:
        logger.error("list_templates error: %s", exc)
        return []


def delete_template(
    template_id: int,
    owner_type: str,
    owner_id: Optional[int],
) -> Dict:
    """Delete a template (CASCADE removes steps).

    Returns {"success": True} or {"error": str}.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT owner_type, owner_id FROM media_templates WHERE id = %s",
                (template_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": f"Template {template_id} not found"}

            if row["owner_type"] != owner_type or row["owner_id"] != owner_id:
                return {"error": "Permission denied: not the template owner"}

            cur.execute(
                "DELETE FROM media_templates WHERE id = %s",
                (template_id,),
            )

        return {"success": True}

    except Exception as exc:
        logger.error("delete_template error: %s", exc)
        return {"error": str(exc)}


def get_template_versions(template_id: int) -> List[Dict]:
    """Return all versions for the version chain containing template_id.

    Walks parent_id to find root, then returns all rows ordered by version.
    """
    try:
        with get_db_cursor() as (conn, cur):
            # Walk to root
            cur.execute(
                "SELECT * FROM media_templates WHERE id = %s",
                (template_id,),
            )
            current = cur.fetchone()
            if not current:
                return []

            root_id = current["id"]
            iterations = 0
            while current["parent_id"] is not None and iterations < _MAX_VERSION_WALK:
                cur.execute(
                    "SELECT * FROM media_templates WHERE id = %s",
                    (current["parent_id"],),
                )
                parent = cur.fetchone()
                if not parent:
                    break
                current = parent
                root_id = current["id"]
                iterations += 1

            cur.execute(
                """
                SELECT * FROM media_templates
                WHERE id = %s OR parent_id = %s
                ORDER BY version
                """,
                (root_id, root_id),
            )
            return [dict(r) for r in cur.fetchall()]

    except Exception as exc:
        logger.error("get_template_versions error: %s", exc)
        return []


def clone_template(
    template_id: int,
    new_owner_type: str,
    new_owner_id: Optional[int],
) -> Dict:
    """Clone a template for a new owner (version=1, parent_id=NULL).

    Returns {"template_id": new_id, "version": 1} or {"error": str}.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT * FROM media_templates WHERE id = %s",
                (template_id,),
            )
            original = cur.fetchone()
            if not original:
                return {"error": f"Template {template_id} not found"}

            cur.execute(
                """
                INSERT INTO media_templates
                    (name, description, owner_type, owner_id, visibility, version,
                     parent_id, tags)
                VALUES (%s, %s, %s, %s, %s, 1, NULL, %s)
                RETURNING id
                """,
                (
                    original["name"],
                    original["description"],
                    new_owner_type,
                    new_owner_id,
                    original["visibility"],
                    psycopg2.extras.Json(original["tags"] if isinstance(original["tags"], list) else []),
                ),
            )
            new_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO media_template_steps
                    (template_id, step_order, step_type, step_name, params)
                SELECT %s, step_order, step_type, step_name, params
                FROM media_template_steps
                WHERE template_id = %s
                ORDER BY step_order
                """,
                (new_id, template_id),
            )

        return {"template_id": new_id, "version": 1}

    except Exception as exc:
        logger.error("clone_template error: %s", exc)
        return {"error": str(exc)}
