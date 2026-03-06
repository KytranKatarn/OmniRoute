"""Action Registry — station_actions table upsert helper.

Modules call register_station_actions() on startup to self-register
their actionable commands so Bridge can discover and trigger them.

Import:
    from services.action_registry import register_station_actions
"""

import logging
from typing import Dict, List

import psycopg2
import psycopg2.extras
from database import get_db_connection

logger = logging.getLogger(__name__)


def register_station_actions(actions: List[Dict]) -> int:
    """Upsert actions into station_actions table.

    Each dict must have at minimum:
        action_key, station_code, module_source, label, endpoint_path

    Optional keys (with defaults):
        description, icon ('play'), color_class ('purple'), sort_order (100),
        http_method ('POST'), params_schema ([]), creates_job (True),
        job_type, requires_admin (True)

    Returns number of rows upserted.
    """
    if not actions:
        return 0

    upserted = 0
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            for a in actions:
                cur.execute(
                    """
                    INSERT INTO station_actions
                        (action_key, station_code, module_source, label, description,
                         icon, color_class, sort_order, http_method, endpoint_path,
                         params_schema, creates_job, job_type, requires_admin,
                         test_config)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (action_key) DO UPDATE SET
                        station_code = EXCLUDED.station_code,
                        module_source = EXCLUDED.module_source,
                        label = EXCLUDED.label,
                        description = EXCLUDED.description,
                        icon = EXCLUDED.icon,
                        color_class = EXCLUDED.color_class,
                        sort_order = EXCLUDED.sort_order,
                        http_method = EXCLUDED.http_method,
                        endpoint_path = EXCLUDED.endpoint_path,
                        params_schema = EXCLUDED.params_schema,
                        creates_job = EXCLUDED.creates_job,
                        job_type = EXCLUDED.job_type,
                        requires_admin = EXCLUDED.requires_admin,
                        test_config = EXCLUDED.test_config,
                        updated_at = NOW()
                    """,
                    (
                        a["action_key"],
                        a["station_code"],
                        a["module_source"],
                        a["label"],
                        a.get("description", ""),
                        a.get("icon", "play"),
                        a.get("color_class", "purple"),
                        a.get("sort_order", 100),
                        a.get("http_method", "POST"),
                        a["endpoint_path"],
                        psycopg2.extras.Json(a.get("params_schema", [])),
                        a.get("creates_job", True),
                        a.get("job_type"),
                        a.get("requires_admin", True),
                        psycopg2.extras.Json(a.get("test_config")),
                    ),
                )
                upserted += 1
            conn.commit()
            logger.info(
                "Registered %d station actions for %s",
                upserted,
                actions[0].get("module_source", "unknown"),
            )
    except Exception as e:
        logger.warning("station_actions registration skipped: %s", e)
        upserted = 0

    return upserted
