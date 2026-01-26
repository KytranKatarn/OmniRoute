"""
LLM Connection Monitor
Phase 27: Health monitoring for AI model connections

Monitors:
- Ollama local models
- Claude API
- OpenAI API
- Grok API
- Gemini API
"""

import os
import time
import logging
import threading
import requests
from datetime import datetime
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Check intervals
DEFAULT_CHECK_INTERVAL = 30  # seconds
OLLAMA_TIMEOUT = 5  # seconds for local
API_TIMEOUT = 10  # seconds for remote APIs


def get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


class LLMMonitor:
    """Monitors health of LLM connections."""

    def __init__(self):
        self.running = False
        self.thread = None
        self.last_check = {}

    def start(self):
        """Start the background monitoring thread."""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("LLM Monitor started")

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("LLM Monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                self.check_all_connections()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            time.sleep(DEFAULT_CHECK_INTERVAL)

    def check_all_connections(self) -> Dict[str, any]:
        """Check all enabled connections and return status."""
        results = {}

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get all connections with health check enabled
            cur.execute("""
                SELECT id, provider, model_name, endpoint_url, health_check_enabled
                FROM llm_connections
                WHERE health_check_enabled = TRUE
            """)
            connections = cur.fetchall()

            for connection in connections:
                provider = connection['provider']
                model = connection['model_name']

                # Check based on provider
                if provider == 'ollama':
                    status, latency, error = self._check_ollama(connection)
                elif provider == 'claude':
                    status, latency, error = self._check_claude(connection)
                elif provider == 'openai':
                    status, latency, error = self._check_openai(connection)
                elif provider == 'grok':
                    status, latency, error = self._check_grok(connection)
                elif provider == 'gemini':
                    status, latency, error = self._check_gemini(connection)
                else:
                    status, latency, error = 'unknown', None, 'Unknown provider'

                # Update database
                cur.execute("SELECT update_llm_status(%s, %s, %s, %s, %s)",
                           (provider, model, status, latency, error))

                results[f"{provider}/{model}"] = {
                    'status': status,
                    'latency_ms': latency,
                    'error': error
                }

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Check all connections error: {e}")

        return results

    def _check_ollama(self, connection: Dict) -> tuple:
        """Check Ollama model availability."""
        model = connection['model_name']
        endpoint = connection.get('endpoint_url', 'http://localhost:11434')

        try:
            start = time.time()

            # Check if Ollama is running
            response = requests.get(f"{endpoint}/api/tags", timeout=OLLAMA_TIMEOUT)

            if response.status_code == 200:
                data = response.json()
                models = [m.get('name', '') for m in data.get('models', [])]

                # Check if specific model is available
                model_base = model.split(':')[0]
                if any(model_base in m for m in models):
                    latency = int((time.time() - start) * 1000)
                    return 'online', latency, None
                else:
                    return 'offline', None, f'Model {model} not found in Ollama'
            else:
                return 'offline', None, f'Ollama returned {response.status_code}'

        except requests.exceptions.ConnectionError:
            return 'offline', None, 'Ollama not running'
        except requests.exceptions.Timeout:
            return 'degraded', None, 'Ollama timeout'
        except Exception as e:
            return 'offline', None, str(e)

    def _check_claude(self, connection: Dict) -> tuple:
        """Check Claude API availability."""
        api_key = os.getenv('ANTHROPIC_API_KEY', '')

        if not api_key:
            return 'unknown', None, 'API key not configured'

        try:
            start = time.time()

            # Simple models list check (doesn't consume tokens)
            response = requests.get(
                'https://api.anthropic.com/v1/models',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01'
                },
                timeout=API_TIMEOUT
            )

            latency = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return 'online', latency, None
            elif response.status_code == 401:
                return 'offline', latency, 'Invalid API key'
            elif response.status_code == 429:
                return 'degraded', latency, 'Rate limited'
            else:
                return 'degraded', latency, f'Status {response.status_code}'

        except requests.exceptions.Timeout:
            return 'degraded', None, 'API timeout'
        except Exception as e:
            return 'offline', None, str(e)

    def _check_openai(self, connection: Dict) -> tuple:
        """Check OpenAI API availability."""
        api_key = os.getenv('OPENAI_API_KEY', '')

        if not api_key:
            return 'unknown', None, 'API key not configured'

        try:
            start = time.time()

            response = requests.get(
                'https://api.openai.com/v1/models',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=API_TIMEOUT
            )

            latency = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return 'online', latency, None
            elif response.status_code == 401:
                return 'offline', latency, 'Invalid API key'
            elif response.status_code == 429:
                return 'degraded', latency, 'Rate limited'
            else:
                return 'degraded', latency, f'Status {response.status_code}'

        except requests.exceptions.Timeout:
            return 'degraded', None, 'API timeout'
        except Exception as e:
            return 'offline', None, str(e)

    def _check_grok(self, connection: Dict) -> tuple:
        """Check Grok API availability."""
        api_key = os.getenv('GROK_API_KEY', '') or os.getenv('XAI_API_KEY', '')

        if not api_key:
            return 'unknown', None, 'API key not configured'

        try:
            start = time.time()

            response = requests.get(
                'https://api.x.ai/v1/models',
                headers={'Authorization': f'Bearer {api_key}'},
                timeout=API_TIMEOUT
            )

            latency = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return 'online', latency, None
            elif response.status_code == 401:
                return 'offline', latency, 'Invalid API key'
            else:
                return 'degraded', latency, f'Status {response.status_code}'

        except requests.exceptions.Timeout:
            return 'degraded', None, 'API timeout'
        except Exception as e:
            return 'offline', None, str(e)

    def _check_gemini(self, connection: Dict) -> tuple:
        """Check Gemini API availability."""
        api_key = os.getenv('GOOGLE_API_KEY', '') or os.getenv('GEMINI_API_KEY', '')

        if not api_key:
            return 'unknown', None, 'API key not configured'

        try:
            start = time.time()

            response = requests.get(
                f'https://generativelanguage.googleapis.com/v1/models?key={api_key}',
                timeout=API_TIMEOUT
            )

            latency = int((time.time() - start) * 1000)

            if response.status_code == 200:
                return 'online', latency, None
            elif response.status_code == 401 or response.status_code == 403:
                return 'offline', latency, 'Invalid API key'
            else:
                return 'degraded', latency, f'Status {response.status_code}'

        except requests.exceptions.Timeout:
            return 'degraded', None, 'API timeout'
        except Exception as e:
            return 'offline', None, str(e)

    def get_status_summary(self) -> Dict:
        """Get current status summary of all connections."""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get summary by provider
            cur.execute("SELECT * FROM llm_status_summary")
            summary = cur.fetchall()

            # Get all connections
            cur.execute("""
                SELECT id, provider, model_name, display_name, status,
                       last_check, last_success, last_failure,
                       avg_latency_ms, success_rate, consecutive_failures,
                       capabilities
                FROM llm_connections
                ORDER BY provider, model_name
            """)
            connections = cur.fetchall()

            # Get recent alerts
            cur.execute("""
                SELECT * FROM recent_llm_alerts
                WHERE NOT acknowledged
                LIMIT 10
            """)
            alerts = cur.fetchall()

            cur.close()
            conn.close()

            return {
                'summary': summary,
                'connections': connections,
                'alerts': alerts,
                'last_check': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Get status summary error: {e}")
            return {'error': str(e)}

    def acknowledge_alert(self, alert_id: int, user_id: int = None) -> bool:
        """Acknowledge an alert."""
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute("""
                UPDATE llm_alerts
                SET acknowledged = TRUE, acknowledged_by = %s, acknowledged_at = NOW()
                WHERE id = %s
            """, (user_id, alert_id))

            conn.commit()
            cur.close()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Acknowledge alert error: {e}")
            return False


# Global monitor instance
_monitor = None


def get_monitor() -> LLMMonitor:
    """Get or create the global monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = LLMMonitor()
    return _monitor


def start_monitor():
    """Start the global monitor."""
    monitor = get_monitor()
    monitor.start()


def stop_monitor():
    """Stop the global monitor."""
    global _monitor
    if _monitor:
        _monitor.stop()


def check_now() -> Dict:
    """Run an immediate health check."""
    monitor = get_monitor()
    return monitor.check_all_connections()


def get_status() -> Dict:
    """Get current status summary."""
    monitor = get_monitor()
    return monitor.get_status_summary()
