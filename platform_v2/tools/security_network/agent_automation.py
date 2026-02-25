"""
Security Agent Automation Service
==================================
Manages agent suggestions, auto-actions, and configuration.
Default: suggest-only. Per-category auto-mode toggleable.
"""

import os
import json
from typing import Optional, Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor, Json


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


DEFAULT_CONFIG = {
    "mode": "suggest",
    "paused": False,
    "categories": {
        "dns": {"auto_enabled": False, "description": "DNS filtering and blocking"},
        "camera": {"auto_enabled": False, "description": "Camera arm/disarm scheduling"},
        "scanning": {"auto_enabled": False, "description": "Auto-scan new devices"},
        "access": {"auto_enabled": False, "description": "Auto-block after threshold"},
        "filters": {"auto_enabled": False, "description": "Auto-update filter lists"},
    },
}


class AgentAutomationService:
    """Agent suggestion and automation manager"""

    def __init__(self):
        self._config = None

    def get_config(self) -> Dict:
        if self._config:
            return self._config
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT setting_value FROM security_auto_block_settings
                WHERE setting_key = 'agent_config'
            """
            )
            result = cur.fetchone()
            if result:
                self._config = json.loads(result["setting_value"])
                return self._config
        except Exception:
            pass
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass
        self._config = DEFAULT_CONFIG.copy()
        return self._config

    def save_config(self, config: Dict) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_auto_block_settings (setting_key, setting_value)
                VALUES ('agent_config', %s)
                ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
            """,
                (json.dumps(config),),
            )
            conn.commit()
            self._config = config
            return True
        except Exception:
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def set_mode(self, mode: str) -> bool:
        config = self.get_config()
        config["mode"] = mode
        return self.save_config(config)

    def set_paused(self, paused: bool) -> bool:
        config = self.get_config()
        config["paused"] = paused
        return self.save_config(config)

    def toggle_category_auto(self, category: str, enabled: bool) -> bool:
        config = self.get_config()
        if category in config.get("categories", {}):
            config["categories"][category]["auto_enabled"] = enabled
            return self.save_config(config)
        return False

    def is_auto_enabled(self, category: str) -> bool:
        config = self.get_config()
        if config.get("paused"):
            return False
        if config.get("mode") != "auto":
            return False
        return config.get("categories", {}).get(category, {}).get("auto_enabled", False)

    # --- Suggestions ---
    def create_suggestion(
        self, category: str, title: str, description: str, reasoning: str, data: dict = None
    ) -> Optional[int]:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data)
                VALUES ('suggest', %s, %s, %s, %s, 'pending', %s) RETURNING id
            """,
                (category, title, description, reasoning, Json(data or {})),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            return action_id
        except Exception:
            return None
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def approve_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE security_agent_actions
                SET status = 'approved', executed_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """,
                (suggestion_id,),
            )
            affected = cur.rowcount
            conn.commit()
            return affected > 0
        except Exception:
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def dismiss_suggestion(self, suggestion_id: int) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE security_agent_actions
                SET status = 'dismissed', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
            """,
                (suggestion_id,),
            )
            affected = cur.rowcount
            conn.commit()
            return affected > 0
        except Exception:
            return False
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def get_pending_suggestions(self, category: str = None, limit: int = 50) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            if category:
                cur.execute(
                    """
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending' AND category = %s
                    ORDER BY created_at DESC LIMIT %s
                """,
                    (category, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM security_agent_actions
                    WHERE status = 'pending'
                    ORDER BY created_at DESC LIMIT %s
                """,
                    (limit,),
                )
            results = cur.fetchall()
            return [dict(r) for r in results]
        except Exception:
            return []
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def get_action_history(self, limit: int = 100) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT * FROM security_agent_actions
                ORDER BY created_at DESC LIMIT %s
            """,
                (limit,),
            )
            results = cur.fetchall()
            return [dict(r) for r in results]
        except Exception:
            return []
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    def log_auto_action(
        self, category: str, title: str, description: str, reasoning: str, data: dict = None, success: bool = True
    ) -> Optional[int]:
        status = "executed" if success else "failed"
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_agent_actions
                (action_type, category, title, description, reasoning, status, data, executed_at)
                VALUES ('auto_execute', %s, %s, %s, %s, %s, %s, NOW()) RETURNING id
            """,
                (category, title, description, reasoning, status, Json(data or {})),
            )
            action_id = cur.fetchone()[0]
            conn.commit()
            return action_id
        except Exception:
            return None
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass
