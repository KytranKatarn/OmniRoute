"""Blueprint Phase Manager - CRUD operations for blueprint_phases and blueprint_tasks"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def get_all_phases(section: str = None, status: str = None) -> List[Dict[str, Any]]:
    """Get all phases with their tasks, optionally filtered by section or status."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Build query with optional filters
        query = """
            SELECT
                p.*,
                COALESCE(json_agg(
                    json_build_object(
                        'id', t.id,
                        'task_description', t.task_description,
                        'done', t.done,
                        'display_order', t.display_order,
                        'notes', t.notes,
                        'created_at', t.created_at,
                        'completed_at', t.completed_at
                    ) ORDER BY t.display_order
                ) FILTER (WHERE t.id IS NOT NULL), '[]') as tasks
            FROM blueprint_phases p
            LEFT JOIN blueprint_tasks t ON p.id = t.phase_id
            WHERE 1=1
        """
        params = []

        if section:
            query += " AND p.section = %s"
            params.append(section)

        if status:
            query += " AND p.status = %s"
            params.append(status)

        query += " GROUP BY p.id ORDER BY p.display_order"

        cur.execute(query, params)
        phases = cur.fetchall()

        # Convert to plain dicts with ISO timestamps
        result = []
        for p in phases:
            phase = dict(p)
            for key in ['created_at', 'updated_at', 'started_at', 'completed_at']:
                if phase.get(key):
                    phase[key] = phase[key].isoformat()
            result.append(phase)

        return result
    finally:
        cur.close()
        conn.close()


def get_phase(phase_id: int) -> Optional[Dict[str, Any]]:
    """Get a single phase with its tasks."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT * FROM blueprint_phases WHERE id = %s
        """, (phase_id,))
        phase = cur.fetchone()

        if not phase:
            return None

        # Get tasks
        cur.execute("""
            SELECT * FROM blueprint_tasks
            WHERE phase_id = %s
            ORDER BY display_order
        """, (phase_id,))
        tasks = cur.fetchall()

        result = dict(phase)
        result['tasks'] = [dict(t) for t in tasks]

        # Convert timestamps
        for key in ['created_at', 'updated_at', 'started_at', 'completed_at']:
            if result.get(key):
                result[key] = result[key].isoformat()

        for task in result['tasks']:
            for key in ['created_at', 'completed_at']:
                if task.get(key):
                    task[key] = task[key].isoformat()

        return result
    finally:
        cur.close()
        conn.close()


def create_phase(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new phase."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get max display_order
        cur.execute("SELECT COALESCE(MAX(display_order), 0) + 1 as next_order FROM blueprint_phases")
        next_order = cur.fetchone()['next_order']

        cur.execute("""
            INSERT INTO blueprint_phases
            (phase_number, name, section, status, description, display_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            data['phase_number'],
            data['name'],
            data.get('section', 'future'),
            data.get('status', 'planned'),
            data.get('description', ''),
            data.get('display_order', next_order)
        ))

        phase = dict(cur.fetchone())
        conn.commit()

        logger.info(f"Created phase: {phase['name']}")
        return phase
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating phase: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def update_phase(phase_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a phase."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Build dynamic update query
        updates = []
        params = []

        allowed_fields = ['phase_number', 'name', 'section', 'status', 'description',
                          'completion_percent', 'display_order', 'started_at', 'completed_at']

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if not updates:
            return get_phase(phase_id)

        params.append(phase_id)
        query = f"UPDATE blueprint_phases SET {', '.join(updates)} WHERE id = %s RETURNING *"

        cur.execute(query, params)
        phase = cur.fetchone()

        if not phase:
            return None

        conn.commit()

        logger.info(f"Updated phase {phase_id}: {phase['name']}")
        return dict(phase)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating phase: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def delete_phase(phase_id: int) -> bool:
    """Delete a phase (tasks are cascaded)."""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM blueprint_phases WHERE id = %s", (phase_id,))
        deleted = cur.rowcount > 0
        conn.commit()

        if deleted:
            logger.info(f"Deleted phase {phase_id}")

        return deleted
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting phase: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def reorder_phases(order_list: List[Dict[str, int]]) -> bool:
    """Reorder phases by updating display_order."""
    conn = get_db()
    cur = conn.cursor()

    try:
        for item in order_list:
            cur.execute(
                "UPDATE blueprint_phases SET display_order = %s WHERE id = %s",
                (item['display_order'], item['id'])
            )

        conn.commit()
        logger.info(f"Reordered {len(order_list)} phases")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error reordering phases: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def add_task(phase_id: int, task_description: str, done: bool = False, notes: str = None) -> Dict[str, Any]:
    """Add a task to a phase."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get max display_order for this phase
        cur.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 as next_order FROM blueprint_tasks WHERE phase_id = %s",
            (phase_id,)
        )
        next_order = cur.fetchone()['next_order']

        cur.execute("""
            INSERT INTO blueprint_tasks (phase_id, task_description, done, display_order, notes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (phase_id, task_description, done, next_order, notes))

        task = dict(cur.fetchone())

        # Update phase completion percent
        _update_phase_completion(cur, phase_id)

        conn.commit()
        logger.info(f"Added task to phase {phase_id}: {task_description[:50]}")
        return task
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding task: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def toggle_task(task_id: int) -> Optional[Dict[str, Any]]:
    """Toggle a task's done status."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            UPDATE blueprint_tasks
            SET done = NOT done,
                completed_at = CASE WHEN NOT done THEN NOW() ELSE NULL END
            WHERE id = %s
            RETURNING *
        """, (task_id,))

        task = cur.fetchone()
        if not task:
            return None

        # Update phase completion percent
        _update_phase_completion(cur, task['phase_id'])

        conn.commit()
        logger.info(f"Toggled task {task_id}: done={task['done']}")
        return dict(task)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error toggling task: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def update_task(task_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a task."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        updates = []
        params = []

        allowed_fields = ['task_description', 'done', 'display_order', 'notes']

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if 'done' in data:
            if data['done']:
                updates.append("completed_at = NOW()")
            else:
                updates.append("completed_at = NULL")

        if not updates:
            cur.execute("SELECT * FROM blueprint_tasks WHERE id = %s", (task_id,))
            task = cur.fetchone()
            return dict(task) if task else None

        params.append(task_id)
        query = f"UPDATE blueprint_tasks SET {', '.join(updates)} WHERE id = %s RETURNING *"

        cur.execute(query, params)
        task = cur.fetchone()

        if not task:
            return None

        # Update phase completion percent
        _update_phase_completion(cur, task['phase_id'])

        conn.commit()
        logger.info(f"Updated task {task_id}")
        return dict(task)
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating task: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def delete_task(task_id: int) -> bool:
    """Delete a task."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get phase_id first
        cur.execute("SELECT phase_id FROM blueprint_tasks WHERE id = %s", (task_id,))
        result = cur.fetchone()

        if not result:
            return False

        phase_id = result['phase_id']

        cur.execute("DELETE FROM blueprint_tasks WHERE id = %s", (task_id,))
        deleted = cur.rowcount > 0

        if deleted:
            # Update phase completion percent
            _update_phase_completion(cur, phase_id)

        conn.commit()

        if deleted:
            logger.info(f"Deleted task {task_id}")

        return deleted
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting task: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def _update_phase_completion(cur, phase_id: int):
    """Update phase completion_percent based on task status."""
    cur.execute("""
        UPDATE blueprint_phases SET completion_percent = (
            SELECT COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE done = true) / NULLIF(COUNT(*), 0)), 0)
            FROM blueprint_tasks WHERE phase_id = %s
        )
        WHERE id = %s
    """, (phase_id, phase_id))


def get_roadmap_summary() -> Dict[str, Any]:
    """Get summary statistics for the roadmap."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                COUNT(*) as total_phases,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_phases,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_phases,
                COUNT(*) FILTER (WHERE status = 'planned') as planned_phases,
                COUNT(*) FILTER (WHERE status = 'blocked') as blocked_phases,
                (SELECT COUNT(*) FROM blueprint_tasks) as total_tasks,
                (SELECT COUNT(*) FROM blueprint_tasks WHERE done = true) as done_tasks
            FROM blueprint_phases
        """)

        stats = dict(cur.fetchone())
        stats['progress_percent'] = round(100 * stats['done_tasks'] / max(stats['total_tasks'], 1))

        return stats
    finally:
        cur.close()
        conn.close()


def get_sections() -> List[Dict[str, Any]]:
    """Get phases grouped by section."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                section,
                COUNT(*) as phase_count,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status = 'planned') as planned
            FROM blueprint_phases
            GROUP BY section
            ORDER BY
                CASE section
                    WHEN 'foundation' THEN 1
                    WHEN 'workflow' THEN 2
                    WHEN 'modules' THEN 3
                    WHEN 'future' THEN 4
                    ELSE 5
                END
        """)

        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()
