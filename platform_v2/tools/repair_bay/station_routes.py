"""Repair Bay — Station integration routes.

Proxies Department HQ APIs filtered to ENGINEERING station and
repair_bay module_source. Provides crew roster, job status, and
active job polling for the station panel UI.

Single-source compliance (Project #242 Task 9 / Project #241 Track C):
this module intentionally does NOT query the agents table directly.
Crew data flows via HTTP from /tools/department-hq/api/stations — the
canonical Department HQ read path. agent_service.py owns the agents
table; any future code in this file that needs agent data must either
call department_hq via HTTP (as station_crew does) or go through
agent_service.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

STATION_CODE = "ENGINEERING"
MODULE_SOURCE = "repair_bay"


def register_station_routes(bp, admin_required):
    """Register station-related routes on the repair_bay blueprint."""

    @bp.route("/api/station/crew")
    @login_required
    def station_crew():
        """Get ENGINEERING station crew from Starbase."""
        try:
            import requests as req

            resp = req.get("http://192.168.1.200:3000/tools/department-hq/api/stations", timeout=5)
            if resp.status_code != 200:
                return jsonify({"success": False, "error": "Starbase unavailable"}), 502

            data = resp.json()
            if not data.get("success"):
                return jsonify({"success": False, "error": "Starbase returned failure"}), 502

            # Find ENGINEERING station
            crew = []
            for station in data.get("stations", []):
                if station.get("code") != STATION_CODE:
                    continue
                for agent in station.get("assigned_agents", []):
                    crew.append(
                        {
                            "id": agent.get("id"),
                            "name": (
                                f"{agent.get('first_name', '')} {agent.get('last_name', '')}".strip()
                                or agent.get("name", "Unknown")
                            ),
                            "code_name": agent.get("name"),
                            "title": agent.get("title", agent.get("assignment_type", "")),
                            "assignment_type": agent.get("assignment_type", "primary"),
                            "status": agent.get("status", "unknown"),
                        }
                    )

            return jsonify(
                {
                    "success": True,
                    "station": STATION_CODE,
                    "crew": crew,
                    "crew_count": len(crew),
                }
            )

        except Exception as e:
            logger.warning(f"Station crew fetch failed: {e}")
            return jsonify({"success": True, "station": STATION_CODE, "crew": [], "crew_count": 0})

    @bp.route("/api/station/jobs")
    @login_required
    def station_jobs():
        """Get active Repair Bay jobs from Starbase."""
        try:
            import requests as req

            status_filter = request.args.get("status", "running")
            resp = req.get(
                f"http://192.168.1.200:3000/tools/department-hq/api/bridge/jobs?status={status_filter}",
                timeout=5,
            )
            if resp.status_code != 200:
                return jsonify({"success": True, "jobs": [], "count": 0})

            data = resp.json()
            if not data.get("success"):
                return jsonify({"success": True, "jobs": [], "count": 0})

            # Filter to repair_bay module only
            my_jobs = [j for j in data.get("jobs", []) if j.get("module_source") == MODULE_SOURCE]

            return jsonify(
                {
                    "success": True,
                    "jobs": my_jobs,
                    "count": len(my_jobs),
                    "station": STATION_CODE,
                }
            )

        except Exception as e:
            logger.warning(f"Station jobs fetch failed: {e}")
            return jsonify({"success": True, "jobs": [], "count": 0})

    @bp.route("/api/station/job/<int:job_id>")
    @login_required
    def station_job_detail(job_id):
        """Get single job progress from Starbase."""
        try:
            import requests as req

            resp = req.get(
                f"http://192.168.1.200:3000/tools/department-hq/api/bridge/jobs/{job_id}",
                timeout=5,
            )
            if resp.status_code != 200:
                return jsonify({"success": False, "error": "Job not found"}), 404

            data = resp.json()
            if not data.get("success"):
                return jsonify({"success": False, "error": "Job not found"}), 404

            job = data.get("job", {})

            return jsonify(
                {
                    "success": True,
                    "job": {
                        "id": job.get("id"),
                        "job_type": job.get("job_type"),
                        "description": job.get("description"),
                        "status": job.get("status"),
                        "agent_name": job.get("agent_display_name") or job.get("agent_name"),
                        "station_code": job.get("station_code"),
                        "completed_steps": job.get("completed_steps", 0),
                        "total_steps": job.get("total_steps", 0),
                        "failed_steps": job.get("failed_steps", 0),
                        "created_at": job.get("created_at"),
                        "updated_at": job.get("updated_at"),
                        "metadata": job.get("metadata"),
                    },
                }
            )

        except Exception as e:
            logger.warning(f"Station job detail failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
