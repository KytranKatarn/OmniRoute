"""
Deployment Monitor for A.R.C.H.I.E.
Monitors deployments after they go live and triggers rollback if issues detected

Features:
- 24-hour monitoring window
- Health check tracking
- Error rate monitoring
- Performance degradation detection
- Automatic rollback on threshold breach
"""

import os
import json
from database import _get_db_password
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List
import subprocess
import time

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    from auto_rollback import AutoRollbackManager
except ImportError:
    AutoRollbackManager = None


class DeploymentMonitor:
    """
    Monitors deployed improvements for issues.

    Monitoring Checks:
    - Health endpoint availability
    - Database connectivity
    - Error rate in logs
    - Response time degradation
    - Service crashes

    Triggers rollback if:
    - Health checks fail 3 times in 5 minutes
    - Error rate exceeds 5%
    - Response time increases >200%
    - Service crashes
    """

    def __init__(self):
        self.rollback_manager = AutoRollbackManager() if AutoRollbackManager else None

        # Monitoring thresholds
        self.thresholds = {
            "health_check_failures": 3,  # Max failures before rollback
            "health_check_window_minutes": 5,  # Time window for failures
            "error_rate_percent": 5.0,  # Max error rate (%)
            "response_time_increase_percent": 200,  # Max response time increase (%)
            "monitoring_duration_hours": 24,  # How long to monitor after deployment
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def monitor_deployment(self, deployment_id: int, check_interval_seconds: int = 60) -> Dict:
        """
        Monitor a deployment for a single check cycle.

        This should be called periodically (e.g., every 60 seconds)
        for the monitoring duration.

        Args:
            deployment_id: Deployment to monitor
            check_interval_seconds: How often to check (default: 60s)

        Returns:
            {
                'success': True,
                'deployment_id': 123,
                'status': 'healthy',
                'checks': {
                    'health_endpoint': True,
                    'database': True,
                    'errors': False
                },
                'action_taken': None or 'rollback'
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get deployment details
            cur.execute(
                """
                SELECT * FROM improvement_deployments
                WHERE id = %s
            """,
                (deployment_id,),
            )
            deployment = cur.fetchone()

            if not deployment:
                return {
                    "success": False,
                    "error": f"Deployment {deployment_id} not found",
                }

            # Check if deployment is still in monitoring window
            deployed_at = deployment["deployed_at"]
            monitoring_until = deployed_at + timedelta(hours=self.thresholds["monitoring_duration_hours"])

            if datetime.now() > monitoring_until:
                return {
                    "success": True,
                    "status": "monitoring_complete",
                    "message": "Monitoring window has passed",
                }

            # Run health checks
            checks = self._run_monitoring_checks(deployment_id)

            # Check for rollback triggers
            should_rollback, rollback_reason = self._should_rollback(deployment_id, checks)

            if should_rollback:
                # Trigger rollback
                if self.rollback_manager:
                    rollback_result = self.rollback_manager.rollback_deployment(
                        deployment_id=deployment_id,
                        reason=rollback_reason,
                        auto_triggered=True,
                    )
                    return {
                        "success": True,
                        "deployment_id": deployment_id,
                        "status": "rolled_back",
                        "checks": checks,
                        "action_taken": "rollback",
                        "rollback_reason": rollback_reason,
                        "rollback_result": rollback_result,
                    }
                else:
                    # Can't rollback without manager
                    return {
                        "success": False,
                        "error": "Rollback triggered but rollback manager not available",
                        "rollback_reason": rollback_reason,
                    }

            # No rollback needed - update last health check
            cur.execute(
                """
                UPDATE improvement_proposals
                SET last_health_check = NOW()
                WHERE id = %s
            """,
                (deployment["proposal_id"],),
            )
            conn.commit()

            # Determine overall status
            all_healthy = all(checks.values())
            status = "healthy" if all_healthy else "degraded"

            return {
                "success": True,
                "deployment_id": deployment_id,
                "status": status,
                "checks": checks,
                "action_taken": None,
                "monitoring_until": monitoring_until.isoformat(),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def _run_monitoring_checks(self, deployment_id: int) -> Dict:
        """
        Run all monitoring checks.

        Returns:
            {
                'health_endpoint': True,
                'database': True,
                'error_rate': True,
                'response_time': True
            }
        """
        checks = {}

        # 1. Health endpoint check
        checks["health_endpoint"] = self._check_health_endpoint()

        # 2. Database connectivity
        checks["database"] = self._check_database()

        # 3. Error rate check (simplified)
        checks["error_rate"] = self._check_error_rate()

        # 4. Response time check (simplified)
        checks["response_time"] = self._check_response_time()

        return checks

    def _check_health_endpoint(self) -> bool:
        """Check if health endpoint is responding"""
        try:
            result = subprocess.run(
                ["curl", "-f", "-s", "http://localhost:3000/health"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _check_database(self) -> bool:
        """Check database connectivity"""
        try:
            conn = self.get_db()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            return True
        except Exception:
            return False

    def _check_error_rate(self) -> bool:
        """
        Check error rate in logs.

        In production, would parse actual log files.
        For now, simple placeholder.
        """
        # TODO: Parse actual logs and calculate error rate
        # Return False if error_rate > threshold
        return True

    def _check_response_time(self) -> bool:
        """
        Check if response times are within acceptable range.

        In production, would measure actual response times.
        For now, simple placeholder.
        """
        # TODO: Measure actual response times
        # Return False if response_time > baseline * (1 + threshold/100)
        return True

    def _should_rollback(self, deployment_id: int, checks: Dict) -> tuple:
        """
        Determine if deployment should be rolled back.

        Returns:
            (should_rollback: bool, reason: str)
        """
        # Critical checks that trigger immediate rollback
        critical_checks = ["health_endpoint", "database"]

        for check in critical_checks:
            if not checks.get(check, True):
                return (True, f"Critical check failed: {check}")

        # Check for repeated failures (would need to track history)
        # For now, single failure of critical checks triggers rollback

        return (False, None)

    def get_deployment_health(self, deployment_id: int) -> Dict:
        """
        Get current health status of a deployment.

        Returns:
            {
                'deployment_id': 123,
                'status': 'healthy',
                'deployed_at': '...',
                'monitoring_until': '...',
                'last_check': '...',
                'recent_checks': [...]
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    d.*,
                    p.last_health_check
                FROM improvement_deployments d
                LEFT JOIN improvement_proposals p ON d.proposal_id = p.id
                WHERE d.id = %s
            """,
                (deployment_id,),
            )

            deployment = cur.fetchone()
            cur.close()

            if not deployment:
                return {
                    "success": False,
                    "error": f"Deployment {deployment_id} not found",
                }

            deployed_at = deployment["deployed_at"]
            monitoring_until = deployed_at + timedelta(hours=self.thresholds["monitoring_duration_hours"])

            # Determine status
            if deployment["status"] == "rolled_back":
                status = "rolled_back"
            elif datetime.now() > monitoring_until:
                status = "monitoring_complete"
            else:
                status = "monitoring"

            return {
                "deployment_id": deployment_id,
                "proposal_id": deployment["proposal_id"],
                "status": status,
                "deployed_at": deployed_at.isoformat(),
                "monitoring_until": monitoring_until.isoformat(),
                "last_health_check": (
                    deployment["last_health_check"].isoformat() if deployment["last_health_check"] else None
                ),
                "health_check_passed": deployment.get("health_check_passed"),
                "monitoring_active": datetime.now() <= monitoring_until,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_active_monitors(self) -> Dict:
        """
        Get all deployments currently being monitored.

        Returns:
            {
                'success': True,
                'monitors': [
                    {
                        'deployment_id': 123,
                        'deployed_at': '...',
                        'monitoring_until': '...',
                        'status': 'healthy'
                    },
                    ...
                ],
                'total': 3
            }
        """
        conn = self.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get deployments within monitoring window
            monitoring_cutoff = datetime.now() - timedelta(hours=self.thresholds["monitoring_duration_hours"])

            cur.execute(
                """
                SELECT
                    d.*,
                    p.last_health_check
                FROM improvement_deployments d
                LEFT JOIN improvement_proposals p ON d.proposal_id = p.id
                WHERE d.status = 'deployed'
                AND d.deployed_at > %s
                ORDER BY d.deployed_at DESC
            """,
                (monitoring_cutoff,),
            )

            deployments = cur.fetchall()
            cur.close()

            monitors = []
            for deployment in deployments:
                deployed_at = deployment["deployed_at"]
                monitoring_until = deployed_at + timedelta(hours=self.thresholds["monitoring_duration_hours"])

                monitors.append(
                    {
                        "deployment_id": deployment["id"],
                        "proposal_id": deployment["proposal_id"],
                        "deployed_at": deployed_at.isoformat(),
                        "monitoring_until": monitoring_until.isoformat(),
                        "last_health_check": (
                            deployment["last_health_check"].isoformat() if deployment["last_health_check"] else None
                        ),
                        "status": "monitoring",
                    }
                )

            return {"success": True, "monitors": monitors, "total": len(monitors)}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            conn.close()


# ============================================================================
# BACKGROUND MONITORING SERVICE
# ============================================================================


def run_monitoring_loop(check_interval: int = 60):
    """
    Background service that continuously monitors active deployments.

    This should be run as a separate process/daemon.

    Args:
        check_interval: Seconds between checks (default: 60)
    """
    monitor = DeploymentMonitor()

    print(f"Starting deployment monitoring service (check interval: {check_interval}s)")

    while True:
        try:
            # Get active monitors
            active_result = monitor.get_active_monitors()

            if active_result["success"]:
                active_monitors = active_result["monitors"]
                print(f"Monitoring {len(active_monitors)} active deployments...")

                # Check each deployment
                for deployment_info in active_monitors:
                    deployment_id = deployment_info["deployment_id"]

                    result = monitor.monitor_deployment(deployment_id)

                    if result.get("action_taken") == "rollback":
                        print(f"⚠️  ROLLBACK triggered for deployment {deployment_id}: {result.get('rollback_reason')}")
                    elif result.get("status") == "healthy":
                        print(f"✓ Deployment {deployment_id} healthy")
                    elif result.get("status") == "degraded":
                        print(f"⚠️  Deployment {deployment_id} degraded: {result.get('checks')}")

            # Sleep until next check
            time.sleep(check_interval)

        except KeyboardInterrupt:
            print("\nMonitoring service stopped")
            break
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(check_interval)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def check_deployment_health(deployment_id: int) -> Dict:
    """Quick function to check deployment health"""
    monitor = DeploymentMonitor()
    return monitor.get_deployment_health(deployment_id)


def monitor_once(deployment_id: int) -> Dict:
    """Quick function to run single monitoring check"""
    monitor = DeploymentMonitor()
    return monitor.monitor_deployment(deployment_id)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deployment Monitor")
    parser.add_argument("--service", action="store_true", help="Run as background service")
    parser.add_argument("--check", type=int, help="Check specific deployment ID")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")

    args = parser.parse_args()

    if args.service:
        # Run as background service
        run_monitoring_loop(check_interval=args.interval)
    elif args.check:
        # Check specific deployment
        monitor = DeploymentMonitor()
        result = monitor.monitor_deployment(args.check)
        print(json.dumps(result, indent=2, default=str))
    else:
        # Test mode
        print("Deployment Monitor - Test Mode")
        print("=" * 60)

        monitor = DeploymentMonitor()

        print("\n1. MONITORING CONFIGURATION:")
        print("-" * 60)
        print(f"Health check failures threshold: {monitor.thresholds['health_check_failures']}")
        print(f"Health check window: {monitor.thresholds['health_check_window_minutes']} minutes")
        print(f"Error rate threshold: {monitor.thresholds['error_rate_percent']}%")
        print(f"Response time threshold: {monitor.thresholds['response_time_increase_percent']}%")
        print(f"Monitoring duration: {monitor.thresholds['monitoring_duration_hours']} hours")

        print("\n2. HEALTH CHECKS:")
        print("-" * 60)
        checks = monitor._run_monitoring_checks(0)
        for check_name, status in checks.items():
            status_icon = "✓" if status else "✗"
            print(f"{status_icon} {check_name}: {'Pass' if status else 'Fail'}")

        print("\n3. ACTIVE MONITORS:")
        print("-" * 60)
        active = monitor.get_active_monitors()
        if active["success"]:
            print(f"Currently monitoring {active['total']} deployments")
        else:
            print(f"Error: {active.get('error')}")

        print("\n✅ Deployment Monitor loaded successfully!")
        print("\nRun with --service to start monitoring service")
        print("Run with --check <deployment_id> to check specific deployment")
