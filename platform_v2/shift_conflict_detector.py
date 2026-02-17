"""
Shift Conflict Detector - Phase 28
===================================

Detects and logs scheduling conflicts for the A.R.C.H.I.E. platform.
Can be run as a standalone script or imported as a module.

Conflict Types:
- understaffed: Station has no primary agent for a shift
- no_backup: Station has primary but no backup agent
- overstaffed: Station has more than 3 agents (resource waste)
- consecutive_shifts: Agent assigned to back-to-back shifts (IAAE violation)
- overlap: Agent assigned to overlapping shifts on same day
- iaae_violation: Rest cycle or workload limit exceeded

Usage:
    # Run from command line
    python shift_conflict_detector.py

    # Or import and use programmatically
    from shift_conflict_detector import ShiftConflictDetector
    detector = ShiftConflictDetector()
    conflicts = detector.run_full_check()
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class ShiftConflictDetector:
    """Detects and logs shift scheduling conflicts"""

    def __init__(self, db_config=None):
        """Initialize with optional database configuration"""
        self.db_config = db_config or {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": os.getenv("DB_PASSWORD", ""),
        }
        self.conflicts_detected = []

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def run_full_check(self) -> dict:
        """
        Run all conflict detection checks.
        Returns summary of detected conflicts.
        """
        logger.info("Starting shift conflict detection...")

        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Clear old unresolved conflicts (will be re-detected)
            cur.execute(
                """
                DELETE FROM shift_conflicts
                WHERE resolved = false
                AND detected_at < NOW() - INTERVAL '1 hour'
            """
            )
            conn.commit()

            # Run all checks
            results = {
                "understaffed": self._check_understaffed(cur),
                "no_backup": self._check_no_backup(cur),
                "overstaffed": self._check_overstaffed(cur),
                "consecutive_shifts": self._check_consecutive_shifts(cur),
                "iaae_violations": self._check_iaae_violations(cur),
            }

            conn.commit()
            cur.close()
            conn.close()

            total_conflicts = sum(results.values())
            logger.info(f"Conflict detection complete. Total: {total_conflicts}")

            return {
                "success": True,
                "total_conflicts": total_conflicts,
                "by_type": results,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error during conflict detection: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def _check_understaffed(self, cur) -> int:
        """Check for stations with no primary agent"""
        logger.info("Checking for understaffed stations...")

        cur.execute(
            """
            SELECT
                bs.id as station_id,
                bs.station_name,
                sd.id as shift_id,
                sd.shift_name
            FROM bridge_stations bs
            CROSS JOIN shift_definitions sd
            LEFT JOIN agent_shifts ash ON bs.id = ash.station_id
                AND sd.id = ash.shift_id
                AND ash.is_primary = true
                AND ash.effective_from <= CURRENT_DATE
                AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
            LEFT JOIN agents a ON ash.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = true AND sd.is_active = true
            GROUP BY bs.id, bs.station_name, sd.id, sd.shift_name
            HAVING COUNT(a.id) = 0
        """
        )

        understaffed = cur.fetchall()
        count = 0

        for row in understaffed:
            # Check if conflict already exists
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE station_id = %s AND shift_id = %s
                AND conflict_type = 'understaffed'
                AND conflict_date = CURRENT_DATE
                AND resolved = false
            """,
                (row["station_id"], row["shift_id"]),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (station_id, shift_id, conflict_date, conflict_type, severity, description)
                    VALUES (%s, %s, CURRENT_DATE, 'understaffed', 'critical', %s)
                """,
                    (
                        row["station_id"],
                        row["shift_id"],
                        f"Station {row['station_name']} has no primary agent for {row['shift_name']} shift",
                    ),
                )
                count += 1
                logger.warning(f"CRITICAL: {row['station_name']} understaffed for {row['shift_name']}")

        return count

    def _check_no_backup(self, cur) -> int:
        """Check for stations with primary but no backup agent"""
        logger.info("Checking for stations without backup agents...")

        cur.execute(
            """
            SELECT
                bs.id as station_id,
                bs.station_name,
                sd.id as shift_id,
                sd.shift_name,
                COUNT(CASE WHEN ash.is_primary = true THEN 1 END) as primary_count,
                COUNT(CASE WHEN ash.is_primary = false THEN 1 END) as backup_count
            FROM bridge_stations bs
            CROSS JOIN shift_definitions sd
            LEFT JOIN agent_shifts ash ON bs.id = ash.station_id
                AND sd.id = ash.shift_id
                AND ash.effective_from <= CURRENT_DATE
                AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
            LEFT JOIN agents a ON ash.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = true AND sd.is_active = true
            GROUP BY bs.id, bs.station_name, sd.id, sd.shift_name
            HAVING COUNT(CASE WHEN ash.is_primary = true THEN 1 END) > 0
            AND COUNT(CASE WHEN ash.is_primary = false THEN 1 END) = 0
        """
        )

        no_backup = cur.fetchall()
        count = 0

        for row in no_backup:
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE station_id = %s AND shift_id = %s
                AND conflict_type = 'no_backup'
                AND conflict_date = CURRENT_DATE
                AND resolved = false
            """,
                (row["station_id"], row["shift_id"]),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (station_id, shift_id, conflict_date, conflict_type, severity, description)
                    VALUES (%s, %s, CURRENT_DATE, 'no_backup', 'warning', %s)
                """,
                    (
                        row["station_id"],
                        row["shift_id"],
                        f"Station {row['station_name']} has no backup agent for {row['shift_name']} shift",
                    ),
                )
                count += 1
                logger.info(f"WARNING: {row['station_name']} has no backup for {row['shift_name']}")

        return count

    def _check_overstaffed(self, cur) -> int:
        """Check for stations with too many agents (resource waste)"""
        logger.info("Checking for overstaffed stations...")

        cur.execute(
            """
            SELECT
                bs.id as station_id,
                bs.station_name,
                sd.id as shift_id,
                sd.shift_name,
                COUNT(ash.id) as agent_count
            FROM bridge_stations bs
            CROSS JOIN shift_definitions sd
            JOIN agent_shifts ash ON bs.id = ash.station_id
                AND sd.id = ash.shift_id
                AND ash.effective_from <= CURRENT_DATE
                AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
            JOIN agents a ON ash.agent_id = a.id AND a.status = 'active'
            WHERE bs.is_active = true AND sd.is_active = true
            GROUP BY bs.id, bs.station_name, sd.id, sd.shift_name
            HAVING COUNT(ash.id) > 3
        """
        )

        overstaffed = cur.fetchall()
        count = 0

        for row in overstaffed:
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE station_id = %s AND shift_id = %s
                AND conflict_type = 'overstaffed'
                AND conflict_date = CURRENT_DATE
                AND resolved = false
            """,
                (row["station_id"], row["shift_id"]),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (station_id, shift_id, conflict_date, conflict_type, severity, description, details)
                    VALUES (%s, %s, CURRENT_DATE, 'overstaffed', 'info', %s, %s)
                """,
                    (
                        row["station_id"],
                        row["shift_id"],
                        f"Station {row['station_name']} has {row['agent_count']} agents for {row['shift_name']} shift (>3)",
                        json.dumps({"agent_count": row["agent_count"]}),
                    ),
                )
                count += 1
                logger.info(
                    f"INFO: {row['station_name']} overstaffed ({row['agent_count']} agents) for {row['shift_name']}"
                )

        return count

    def _check_consecutive_shifts(self, cur) -> int:
        """Check for agents working consecutive shifts (IAAE violation)"""
        logger.info("Checking for consecutive shift assignments...")

        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                array_agg(sd.shift_name ORDER BY sd.start_time) as shifts,
                COUNT(ash.id) as shift_count
            FROM agents a
            JOIN agent_shifts ash ON a.id = ash.agent_id
            JOIN shift_definitions sd ON ash.shift_id = sd.id
            WHERE
                a.status = 'active'
                AND sd.is_active = true
                AND ash.effective_from <= CURRENT_DATE
                AND (ash.effective_until IS NULL OR ash.effective_until >= CURRENT_DATE)
                AND (ash.day_of_week IS NULL OR ash.day_of_week = EXTRACT(DOW FROM CURRENT_DATE))
            GROUP BY a.id, a.name
            HAVING COUNT(ash.id) > 1
        """
        )

        consecutive = cur.fetchall()
        count = 0

        for row in consecutive:
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE agent_id = %s
                AND conflict_type = 'consecutive_shifts'
                AND conflict_date = CURRENT_DATE
                AND resolved = false
            """,
                (row["agent_id"],),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (agent_id, conflict_date, conflict_type, severity, description, details)
                    VALUES (%s, CURRENT_DATE, 'consecutive_shifts', 'warning', %s, %s)
                """,
                    (
                        row["agent_id"],
                        f"Agent {row['agent_name']} assigned to multiple shifts on same day",
                        json.dumps({"shifts": row["shifts"], "count": row["shift_count"]}),
                    ),
                )
                count += 1
                logger.warning(f"WARNING: {row['agent_name']} has {row['shift_count']} shifts today")

        return count

    def _check_iaae_violations(self, cur) -> int:
        """Check for IAAE governance violations (workload, rest cycles)"""
        logger.info("Checking for IAAE compliance violations...")

        count = 0

        # Check for agents exceeding daily task limit (500 for internal, 100 for contract)
        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                a.worker_type,
                COUNT(ae.id) as task_count,
                CASE WHEN a.worker_type = 'internal' THEN 500 ELSE 100 END as limit
            FROM agents a
            JOIN agent_executions ae ON a.id = ae.agent_id
            WHERE
                a.status = 'active'
                AND ae.started_at >= CURRENT_DATE
            GROUP BY a.id, a.name, a.worker_type
            HAVING COUNT(ae.id) > CASE WHEN a.worker_type = 'internal' THEN 500 ELSE 100 END
        """
        )

        overworked = cur.fetchall()

        for row in overworked:
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE agent_id = %s
                AND conflict_type = 'iaae_violation'
                AND conflict_date = CURRENT_DATE
                AND resolved = false
            """,
                (row["agent_id"],),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (agent_id, conflict_date, conflict_type, severity, description, details)
                    VALUES (%s, CURRENT_DATE, 'iaae_violation', 'critical', %s, %s)
                """,
                    (
                        row["agent_id"],
                        f"Agent {row['agent_name']} exceeded daily task limit ({row['task_count']}/{row['limit']})",
                        json.dumps(
                            {
                                "task_count": row["task_count"],
                                "limit": row["limit"],
                                "worker_type": row["worker_type"],
                            }
                        ),
                    ),
                )
                count += 1
                logger.error(f"CRITICAL: {row['agent_name']} exceeded task limit ({row['task_count']}/{row['limit']})")

        # Check for agents needing rest (stress > 0.85)
        cur.execute(
            """
            SELECT
                a.id as agent_id,
                a.name as agent_name,
                aes.stress_level
            FROM agents a
            JOIN agent_emotional_state aes ON a.id = aes.agent_id
            WHERE
                a.status = 'active'
                AND aes.stress_level > 0.85
        """
        )

        stressed = cur.fetchall()

        for row in stressed:
            cur.execute(
                """
                SELECT id FROM shift_conflicts
                WHERE agent_id = %s
                AND conflict_type = 'iaae_violation'
                AND conflict_date = CURRENT_DATE
                AND description LIKE '%stress%'
                AND resolved = false
            """,
                (row["agent_id"],),
            )

            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO shift_conflicts
                    (agent_id, conflict_date, conflict_type, severity, description, details)
                    VALUES (%s, CURRENT_DATE, 'iaae_violation', 'warning', %s, %s)
                """,
                    (
                        row["agent_id"],
                        f"Agent {row['agent_name']} stress level too high ({row['stress_level']:.2f}), needs rest",
                        json.dumps({"stress_level": float(row["stress_level"])}),
                    ),
                )
                count += 1
                logger.warning(f"WARNING: {row['agent_name']} stress level {row['stress_level']:.2f} > 0.85")

        return count

    def get_conflict_summary(self) -> dict:
        """Get summary of all current conflicts"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    conflict_type,
                    severity,
                    COUNT(*) as count
                FROM shift_conflicts
                WHERE resolved = false
                GROUP BY conflict_type, severity
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'warning' THEN 2
                        ELSE 3
                    END,
                    conflict_type
            """
            )

            summary = cur.fetchall()

            cur.execute("SELECT COUNT(*) as total FROM shift_conflicts WHERE resolved = false")
            total = cur.fetchone()["total"]

            cur.close()
            conn.close()

            return {
                "success": True,
                "total_unresolved": total,
                "by_type_and_severity": [dict(s) for s in summary],
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


def main():
    """Run conflict detection from command line"""
    detector = ShiftConflictDetector()

    print("\n" + "=" * 60)
    print("SHIFT CONFLICT DETECTOR - Phase 28")
    print("=" * 60 + "\n")

    # Run full check
    result = detector.run_full_check()

    if result["success"]:
        print(f"\nTotal Conflicts Detected: {result['total_conflicts']}")
        print("\nBy Type:")
        for conflict_type, count in result["by_type"].items():
            print(f"  - {conflict_type}: {count}")
    else:
        print(f"\nError: {result.get('error', 'Unknown error')}")

    # Get summary
    print("\n" + "-" * 60)
    summary = detector.get_conflict_summary()
    if summary["success"]:
        print(f"Unresolved Conflicts: {summary['total_unresolved']}")
        if summary["by_type_and_severity"]:
            print("\nBreakdown:")
            for item in summary["by_type_and_severity"]:
                print(f"  [{item['severity'].upper()}] {item['conflict_type']}: {item['count']}")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
