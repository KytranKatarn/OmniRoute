"""
App Builder Routes - Flask Blueprint
API endpoints for GPT-Pilot style application generation

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import sys
import os
from database import _get_db_password
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from datetime import datetime
import json

# Add paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from rbac import require_permission, Permission, has_permission
from validation import validate_schema
from logging_config import audit_log
from rate_limiting import rate_limit

# Create blueprint
app_builder_bp = Blueprint("app_builder", __name__, url_prefix="/tools/app-builder")

# Import App Builder components
from .agents.clarification_agent import ClarificationAgent

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_db():
    """Get database connection"""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# MAIN UI ROUTE
# ============================================================================


@app_builder_bp.route("/")
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def index():
    """App Builder main interface"""
    try:
        # Get user's projects
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, name, description, status, progress, created_at, updated_at
            FROM app_builder_projects
            WHERE user_id = %s
            ORDER BY updated_at DESC
            LIMIT 20
        """,
            (current_user.id,),
        )

        projects = []
        for row in cur.fetchall():
            projects.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "status": row[3],
                    "progress": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                    "updated_at": row[6].isoformat() if row[6] else None,
                }
            )

        return render_template("tools/app_builder.html", projects=projects)

    except Exception as e:
        return render_template("tools/app_builder.html", projects=[], error=str(e))
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PROJECT MANAGEMENT
# ============================================================================


@app_builder_bp.route("/api/projects", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
@rate_limit(limit=10)  # 10 projects per minute
def create_project():
    """
    Create a new App Builder project

    Request Body:
        {
            "name": "My App",
            "description": "Optional description",
            "user_prompt": "Build me a todo app with authentication",
            "project_type": "web_app"  # optional
        }

    Returns:
        {
            "success": true,
            "project_id": 123,
            "status": "clarifying",
            "questions": [...]  # Clarification questions
        }
    """
    try:
        # Validate request
        schema = {
            "name": {
                "type": "string",
                "required": True,
                "min_length": 3,
                "max_length": 255,
            },
            "description": {"type": "string", "required": False, "max_length": 1000},
            "user_prompt": {"type": "string", "required": True, "min_length": 10},
            "project_type": {
                "type": "enum",
                "required": False,
                "allowed_values": ["web_app", "api", "mobile", "desktop", "cli"],
            },
        }

        result = validate_schema(request.get_json() or {}, schema)
        if not result.valid:
            return jsonify({"success": False, "errors": result.errors}), 400

        data = result.sanitized_data

        # Check subscription limits
        if not has_permission(Permission.APP_BUILDER_UNLIMITED, current_user):
            # FREE tier: Check project limit
            conn = get_db()
            cur = conn.cursor()

            # Count projects created this month
            cur.execute(
                """
                SELECT COUNT(*) FROM app_builder_projects
                WHERE user_id = %s
                AND created_at >= DATE_TRUNC('month', NOW())
            """,
                (current_user.id,),
            )

            project_count = cur.fetchone()[0]
            cur.close()
            conn.close()

            if project_count >= 1:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "FREE tier limit: 1 project per month. Upgrade to PREMIUM for unlimited projects.",
                        }
                    ),
                    403,
                )

        # Create project in database
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO app_builder_projects
            (user_id, created_by, name, description, user_prompt, project_type, status, progress)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                current_user.id,
                current_user.id,
                data["name"],
                data.get("description", ""),
                data["user_prompt"],
                data.get("project_type", "web_app"),
                "planning",
                0,
            ),
        )

        project_id = cur.fetchone()[0]
        conn.commit()

        # Generate clarification questions
        agent = ClarificationAgent(project_id, current_user.id)
        import asyncio

        questions = asyncio.run(agent.generate_questions(data["user_prompt"]))

        # Save questions to database
        asyncio.run(agent.save_to_database(questions))

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_PROJECT_CREATED",
                {
                    "project_id": project_id,
                    "name": data["name"],
                    "prompt": data["user_prompt"],
                },
                user_id=current_user.id,
                success=True,
            )

        return jsonify(
            {
                "success": True,
                "project_id": project_id,
                "status": "clarifying",
                "questions": questions,
            }
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_project(project_id):
    """Get project details"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, user_id, name, description, user_prompt, project_type,
                   status, progress, current_step, created_at, updated_at,
                   clarification_questions, clarification_answers,
                   project_plan, plan_approved, tech_stack, total_files
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        # Check ownership
        if row[1] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        project = {
            "id": row[0],
            "user_id": row[1],
            "name": row[2],
            "description": row[3],
            "user_prompt": row[4],
            "project_type": row[5],
            "status": row[6],
            "progress": row[7],
            "current_step": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
            "clarification_questions": row[11],
            "clarification_answers": row[12],
            "project_plan": row[13],
            "plan_approved": row[14],
            "tech_stack": row[15],
            "total_files": row[16],
        }

        return jsonify({"success": True, "project": project})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def list_projects():
    """List user's projects"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, name, description, status, progress, created_at, updated_at
            FROM app_builder_projects
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """,
            (current_user.id,),
        )

        projects = []
        for row in cur.fetchall():
            projects.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "status": row[3],
                    "progress": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                    "updated_at": row[6].isoformat() if row[6] else None,
                }
            )

        return jsonify({"success": True, "projects": projects})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CLARIFICATION
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/clarifications", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def submit_clarifications(project_id):
    """
    Submit answers to clarification questions

    Request Body:
        {
            "answers": {
                "app_type": "Web Application",
                "core_features": "User auth, dashboard, data export",
                ...
            }
        }

    Returns:
        {
            "success": true,
            "status": "planning",
            "message": "Generating project plan..."
        }
    """
    try:
        data = request.get_json() or {}
        answers = data.get("answers", {})

        # Verify ownership
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT user_id, clarification_questions FROM app_builder_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        questions = row[1] or []

        # Validate answers
        agent = ClarificationAgent(project_id, current_user.id)
        errors = agent.validate_answers(questions, answers)

        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        # Save answers to database
        import asyncio

        asyncio.run(agent.save_to_database(questions, answers))

        # Get user_prompt before closing connection
        cur.execute("SELECT user_prompt FROM app_builder_projects WHERE id = %s", (project_id,))
        user_prompt = cur.fetchone()[0]

        # Update project with answers
        cur.execute(
            """
            UPDATE app_builder_projects
            SET clarification_answers = %s, status = %s, updated_at = NOW()
            WHERE id = %s
        """,
            (json.dumps(answers), "planning", project_id),
        )

        conn.commit()

        # Generate plan using planner agent
        from .agents.planner_agent import PlannerAgent
        from .agents.architect_agent import ArchitectAgent

        # Generate plan
        planner = PlannerAgent(project_id, answers)
        plan = asyncio.run(planner.generate_plan(user_prompt, answers))

        # Save plan
        asyncio.run(planner.save_to_database(plan))

        # Enhance plan with architect agent
        architect = ArchitectAgent(project_id, plan)
        architecture = asyncio.run(architect.enhance_plan())
        asyncio.run(architect.save_to_database())

        # Combine plan and architecture for response
        full_plan = {**plan, "architecture": architecture}

        return jsonify(
            {
                "success": True,
                "status": "plan_approval",
                "message": "Project plan and architecture generated successfully!",
                "plan": full_plan,
            }
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PLAN APPROVAL
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/approve-plan", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def approve_plan(project_id):
    """
    Approve the generated plan and start code generation

    Returns:
        {
            "success": true,
            "status": "generating",
            "message": "Starting code generation..."
        }
    """
    try:
        # Verify ownership and plan exists
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, project_plan, status
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        if not row[1]:
            return jsonify({"success": False, "error": "No plan to approve"}), 400

        # Approve plan
        cur.execute(
            """
            UPDATE app_builder_projects
            SET plan_approved = TRUE,
                plan_approved_at = NOW(),
                status = 'generating',
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id,),
        )

        conn.commit()

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_PLAN_APPROVED",
                {"project_id": project_id},
                user_id=current_user.id,
                success=True,
            )

        return jsonify(
            {
                "success": True,
                "status": "generating",
                "message": "Plan approved! Starting code generation...",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CODE GENERATION
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/generate", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def generate_code(project_id):
    """
    Generate backend code for the project

    Request Body:
        {
            "backend": true,   // Generate backend code
            "frontend": false, // Generate frontend code (future)
            "database": false  // Generate database schema (future)
        }

    Returns:
        {
            "success": true,
            "files_generated": 14,
            "message": "Backend code generated successfully"
        }
    """
    try:
        data = request.get_json() or {} or {}
        generate_backend = data.get("backend", True)
        generate_frontend = data.get("frontend", True)
        generate_database = data.get("database", True)

        # Verify ownership and plan approval
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, project_plan, architecture_plan, plan_approved, status
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        if not row[3]:  # plan_approved
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Plan must be approved before generating code",
                    }
                ),
                400,
            )

        project_plan = row[1]
        architecture_plan = row[2]

        if not project_plan:
            return jsonify({"success": False, "error": "No plan found"}), 400

        files_generated = 0
        results = {}

        # Generate backend code
        if generate_backend:
            from .agents.backend_generator import BackendGenerator
            import asyncio

            generator = BackendGenerator(project_id, project_plan, architecture_plan or {})
            backend_result = asyncio.run(generator.generate_backend())
            asyncio.run(generator.save_to_database())

            files_generated += backend_result["file_count"]
            results["backend"] = {
                "framework": backend_result["framework"],
                "files": backend_result["file_count"],
            }

        # Generate frontend code
        if generate_frontend:
            from .agents.frontend_generator import FrontendGenerator
            import asyncio

            generator = FrontendGenerator(project_id, project_plan, architecture_plan or {})
            frontend_result = asyncio.run(generator.generate_frontend())
            asyncio.run(generator.save_to_database())

            files_generated += frontend_result["file_count"]
            results["frontend"] = {
                "framework": frontend_result["framework"],
                "files": frontend_result["file_count"],
            }

        # Generate database schema
        if generate_database:
            from .agents.database_generator import DatabaseGenerator
            import asyncio

            generator = DatabaseGenerator(project_id, project_plan, architecture_plan or {})
            database_result = asyncio.run(generator.generate_database())
            asyncio.run(generator.save_to_database())

            files_generated += database_result["file_count"]
            results["database"] = {
                "database_type": database_result["database_type"],
                "files": database_result["file_count"],
                "tables": database_result["tables"],
            }

        # Update project status
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE app_builder_projects
            SET status = 'generated',
                code_generated_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id,),
        )
        conn.commit()

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_CODE_GENERATED",
                {"project_id": project_id, "files_generated": files_generated},
                user_id=current_user.id,
                success=True,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "files_generated": files_generated,
                    "results": results,
                    "message": f"Code generated successfully! {files_generated} files created.",
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/generate-tests", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def generate_tests(project_id):
    """
    Generate test files for backend and frontend code

    Request Body:
        {
            "backend": true,   // Generate backend tests (pytest)
            "frontend": true   // Generate frontend tests (Jest)
        }

    Returns:
        {
            "success": true,
            "test_files": 17,
            "backend_tests": 8,
            "frontend_tests": 9,
            "message": "Tests generated successfully"
        }
    """
    try:
        data = request.get_json() or {} or {}
        test_backend = data.get("backend", True)
        test_frontend = data.get("frontend", True)

        # Verify ownership and code generation
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, project_plan, status
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        if row[2] not in ["generated", "tested"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Code must be generated before creating tests",
                    }
                ),
                400,
            )

        project_plan = row[1]

        if not project_plan:
            return jsonify({"success": False, "error": "No plan found"}), 400

        # Generate tests
        from .agents.test_generator import TestGenerator
        import asyncio

        generator = TestGenerator(project_id, project_plan)
        test_result = asyncio.run(generator.generate_tests(test_backend=test_backend, test_frontend=test_frontend))
        asyncio.run(generator.save_to_database())

        # Update project status
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE app_builder_projects
            SET tests_generated_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id,),
        )
        conn.commit()

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_TESTS_GENERATED",
                {"project_id": project_id, "test_files": test_result["file_count"]},
                user_id=current_user.id,
                success=True,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "test_files": test_result["file_count"],
                    "backend_tests": test_result["backend_tests"],
                    "frontend_tests": test_result["frontend_tests"],
                    "frameworks": test_result["frameworks"],
                    "message": f"Tests generated successfully! {test_result['file_count']} test files created.",
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/run-tests", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def run_tests(project_id):
    """
    Run tests for backend and frontend code

    Request Body:
        {
            "backend": true,      // Run backend tests
            "frontend": true,     // Run frontend tests
            "test_type": "all"   // Test type: "all", "unit", "integration"
        }

    Returns:
        {
            "success": true,
            "overall_success": true,
            "total_tests": 25,
            "passed_tests": 24,
            "failed_tests": 1,
            "success_rate": 96.0,
            "backend": { ... },
            "frontend": { ... }
        }
    """
    try:
        data = request.get_json() or {} or {}
        test_backend = data.get("backend", True)
        test_frontend = data.get("frontend", True)
        test_type = data.get("test_type", "all")

        # Verify ownership
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, project_path
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        project_path = row[1] or f"/tmp/app_builder_projects/{project_id}"

        # Run tests
        from .agents.test_runner import TestRunner
        import asyncio

        runner = TestRunner(project_id, project_path)
        test_results = asyncio.run(
            runner.run_tests(
                test_backend=test_backend,
                test_frontend=test_frontend,
                test_type=test_type,
            )
        )

        # Save results to database
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE app_builder_projects
            SET
                status = %s,
                test_results = %s,
                last_test_run = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """,
            (
                "tested" if test_results["overall_success"] else "test_failed",
                json.dumps(test_results),
                project_id,
            ),
        )
        conn.commit()

        # Generate report
        report_text = runner.generate_report(format="text")

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_TESTS_RUN",
                {
                    "project_id": project_id,
                    "total_tests": test_results["total_tests"],
                    "passed": test_results["passed_tests"],
                    "failed": test_results["failed_tests"],
                    "success": test_results["overall_success"],
                },
                user_id=current_user.id,
                success=test_results["overall_success"],
            )

        return (
            jsonify(
                {
                    "success": True,
                    "test_results": test_results,
                    "report": report_text,
                    "message": (
                        "Tests executed successfully"
                        if test_results["overall_success"]
                        else "Tests completed with failures"
                    ),
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/test-results", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_test_results(project_id):
    """
    Get test results for a project

    Returns:
        {
            "success": true,
            "test_results": { ... },
            "last_test_run": "2026-01-07T12:00:00"
        }
    """
    try:
        # Verify ownership
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, test_results, last_test_run
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        test_results = row[1]
        last_test_run = row[2].isoformat() if row[2] else None

        if not test_results:
            return (
                jsonify(
                    {
                        "success": True,
                        "test_results": None,
                        "last_test_run": None,
                        "message": "No tests have been run yet",
                    }
                ),
                200,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "test_results": test_results,
                    "last_test_run": last_test_run,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# DEPLOYMENT
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/generate-deployment", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def generate_deployment(project_id):
    """
    Generate deployment files (Docker, CI/CD, scripts)

    Request Body:
        {
            "docker": true,        // Generate Docker files
            "ci_cd": true,         // Generate CI/CD configurations
            "kubernetes": false    // Generate Kubernetes manifests
        }

    Returns:
        {
            "success": true,
            "deployment_files": 19,
            "docker_enabled": true,
            "ci_cd_enabled": true,
            "message": "Deployment files generated successfully"
        }
    """
    try:
        data = request.get_json() or {} or {}
        generate_docker = data.get("docker", True)
        generate_ci_cd = data.get("ci_cd", True)
        generate_kubernetes = data.get("kubernetes", False)

        # Verify ownership and testing
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, project_plan, architecture_plan, status
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        if row[3] not in ["generated", "tested", "test_failed"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Code must be generated before creating deployment files",
                    }
                ),
                400,
            )

        project_plan = row[1]
        architecture_plan = row[2]

        if not project_plan:
            return jsonify({"success": False, "error": "No plan found"}), 400

        # Generate deployment files
        from .agents.deployment_generator import DeploymentGenerator
        import asyncio

        generator = DeploymentGenerator(project_id, project_plan, architecture_plan or {})
        deploy_result = asyncio.run(
            generator.generate_deployment(
                docker=generate_docker,
                ci_cd=generate_ci_cd,
                kubernetes=generate_kubernetes,
            )
        )
        asyncio.run(generator.save_to_database())

        # Update project status
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE app_builder_projects
            SET
                status = 'deployment_ready',
                deployment_generated_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id,),
        )
        conn.commit()

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_DEPLOYMENT_GENERATED",
                {
                    "project_id": project_id,
                    "deployment_files": deploy_result["file_count"],
                },
                user_id=current_user.id,
                success=True,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "deployment_files": deploy_result["file_count"],
                    "docker_enabled": deploy_result["docker_enabled"],
                    "ci_cd_enabled": deploy_result["ci_cd_enabled"],
                    "kubernetes_enabled": deploy_result["kubernetes_enabled"],
                    "message": f"Deployment files generated successfully! {deploy_result['file_count']} files created.",
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/deploy", methods=["POST"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def deploy_project(project_id):
    """
    Deploy project to production (placeholder for actual deployment logic)

    Request Body:
        {
            "environment": "production",  // "production", "staging", "development"
            "auto_rollback": true         // Enable auto-rollback on failure
        }

    Returns:
        {
            "success": true,
            "deployment_id": "deploy_123",
            "status": "deploying",
            "message": "Deployment started"
        }
    """
    try:
        data = request.get_json() or {} or {}
        environment = data.get("environment", "production")
        auto_rollback = data.get("auto_rollback", True)

        # Verify ownership
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, status
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        if row[1] not in ["deployment_ready", "deployed"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Deployment files must be generated first",
                    }
                ),
                400,
            )

        # Update project status to deploying
        deployment_id = f"deploy_{project_id}_{int(datetime.now().timestamp())}"

        cur.execute(
            """
            UPDATE app_builder_projects
            SET
                status = 'deploying',
                last_deployment_id = %s,
                last_deployment_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """,
            (deployment_id, project_id),
        )
        conn.commit()

        # NOTE: Actual deployment logic would go here
        # This could include:
        # - SSH to deployment server
        # - Run deploy.sh script
        # - Monitor deployment progress
        # - Run health checks
        # - Rollback on failure if auto_rollback=True

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_DEPLOYMENT_STARTED",
                {
                    "project_id": project_id,
                    "deployment_id": deployment_id,
                    "environment": environment,
                },
                user_id=current_user.id,
                success=True,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "deployment_id": deployment_id,
                    "status": "deploying",
                    "environment": environment,
                    "auto_rollback": auto_rollback,
                    "message": f"Deployment started to {environment} environment",
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/deployment-status", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_deployment_status(project_id):
    """
    Get deployment status for a project

    Returns:
        {
            "success": true,
            "status": "deployed",
            "deployment_id": "deploy_123",
            "last_deployment_at": "2026-01-07T12:00:00"
        }
    """
    try:
        # Verify ownership
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id, status, last_deployment_id, last_deployment_at, deployment_generated_at
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id:
            return jsonify({"success": False, "error": "Access denied"}), 403

        status = row[1]
        deployment_id = row[2]
        last_deployment_at = row[3].isoformat() if row[3] else None
        deployment_generated_at = row[4].isoformat() if row[4] else None

        return (
            jsonify(
                {
                    "success": True,
                    "status": status,
                    "deployment_id": deployment_id,
                    "last_deployment_at": last_deployment_at,
                    "deployment_generated_at": deployment_generated_at,
                    "deployment_ready": status in ["deployment_ready", "deploying", "deployed"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# FILES & GENERATION
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/files", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_project_files(project_id):
    """Get all files for a project"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute("SELECT user_id FROM app_builder_projects WHERE id = %s", (project_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get files
        cur.execute(
            """
            SELECT id, file_path, file_name, file_type, size_bytes, line_count,
                   generated_by, status, created_at
            FROM app_builder_files
            WHERE project_id = %s AND is_latest = TRUE
            ORDER BY file_path
        """,
            (project_id,),
        )

        files = []
        for row in cur.fetchall():
            files.append(
                {
                    "id": row[0],
                    "path": row[1],
                    "name": row[2],
                    "type": row[3],
                    "size_bytes": row[4],
                    "line_count": row[5],
                    "generated_by": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat() if row[8] else None,
                }
            )

        return jsonify({"success": True, "files": files, "total": len(files)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/files/<int:file_id>", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_file_content(project_id, file_id):
    """Get content of a specific file"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute(
            """
            SELECT p.user_id
            FROM app_builder_projects p
            WHERE p.id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get file content
        cur.execute(
            """
            SELECT file_path, file_name, file_type, content, generated_by, created_at
            FROM app_builder_files
            WHERE id = %s AND project_id = %s
        """,
            (file_id, project_id),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "File not found"}), 404

        file_data = {
            "path": row[0],
            "name": row[1],
            "type": row[2],
            "content": row[3],
            "generated_by": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
        }

        return jsonify({"success": True, "file": file_data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PROGRESS & STATUS
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/status", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_project_status(project_id):
    """Get current project status and progress"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute(
            """
            SELECT user_id, status, progress, current_step, total_files,
                   tests_passed, deployed, deployment_url
            FROM app_builder_projects
            WHERE id = %s
        """,
            (project_id,),
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        status = {
            "status": row[1],
            "progress": row[2],
            "current_step": row[3],
            "total_files": row[4],
            "tests_passed": row[5],
            "deployed": row[6],
            "deployment_url": row[7],
        }

        return jsonify({"success": True, "status": status})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# EXECUTION LOGS
# ============================================================================


@app_builder_bp.route("/api/projects/<int:project_id>/logs", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def get_execution_logs(project_id):
    """Get execution logs for a project"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute("SELECT user_id FROM app_builder_projects WHERE id = %s", (project_id,))
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get logs
        cur.execute(
            """
            SELECT step_name, step_type, status, progress, started_at, completed_at, duration_ms,
                   success, error_message, agent
            FROM app_builder_execution_logs
            WHERE project_id = %s
            ORDER BY started_at DESC
            LIMIT 100
        """,
            (project_id,),
        )

        logs = []
        for row in cur.fetchall():
            logs.append(
                {
                    "step_name": row[0],
                    "step_type": row[1],
                    "status": row[2],
                    "progress": row[3],
                    "started_at": row[4].isoformat() if row[4] else None,
                    "completed_at": row[5].isoformat() if row[5] else None,
                    "duration_ms": row[6],
                    "success": row[7],
                    "error_message": row[8],
                    "agent": row[9],
                }
            )

        return jsonify({"success": True, "logs": logs, "total": len(logs)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def delete_project(project_id):
    """Delete a project"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute(
            "SELECT user_id, name FROM app_builder_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        project_name = row[1]

        # Delete project (CASCADE will delete related records)
        cur.execute("DELETE FROM app_builder_projects WHERE id = %s", (project_id,))
        conn.commit()

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_PROJECT_DELETED",
                {"project_id": project_id, "project_name": project_name},
                user_id=current_user.id,
                success=True,
            )

        return jsonify({"success": True, "message": "Project deleted successfully"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/download", methods=["GET"])
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def download_project(project_id):
    """Download project as ZIP file"""
    import zipfile
    import io
    from flask import send_file

    try:
        conn = get_db()
        cur = conn.cursor()

        # Verify ownership
        cur.execute(
            "SELECT user_id, name FROM app_builder_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        if row[0] != current_user.id and not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"success": False, "error": "Access denied"}), 403

        project_name = row[1]

        # Get all files
        cur.execute(
            """
            SELECT file_path, file_content
            FROM app_builder_files
            WHERE project_id = %s AND is_latest = TRUE
            ORDER BY file_path
        """,
            (project_id,),
        )

        files = cur.fetchall()

        if not files:
            return jsonify({"success": False, "error": "No files to download"}), 404

        # Create ZIP file in memory
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path, file_content in files:
                if file_content:
                    zf.writestr(file_path, file_content)

        memory_file.seek(0)

        # Audit log
        if audit_log:
            audit_log(
                "APP_BUILDER_PROJECT_DOWNLOADED",
                {"project_id": project_id, "file_count": len(files)},
                user_id=current_user.id,
                success=True,
            )

        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{project_name}.zip",
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@app_builder_bp.route("/api/projects/<int:project_id>/stream")
@login_required
@require_permission(Permission.APP_BUILDER_CREATE)
def stream_project_updates(project_id):
    """Server-Sent Events stream for real-time project updates"""
    from flask import Response, stream_with_context
    import time

    def generate():
        # Verify ownership
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM app_builder_projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row or row[0] != current_user.id:
            yield f"data: {json.dumps({'error': 'Access denied'})}\n\n"
            return

        # Send initial status
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, progress FROM app_builder_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if row:
            yield f"data: {json.dumps({'status': row[0], 'progress': row[1]})}\n\n"
        cur.close()
        conn.close()

        # Poll for updates every 2 seconds
        last_progress = None
        for _ in range(150):  # 5 minutes max
            time.sleep(2)

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT status, progress FROM app_builder_projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                status, progress = row
                if progress != last_progress:
                    yield f"data: {json.dumps({'status': status, 'progress': progress})}\n\n"
                    last_progress = progress

                # Stop streaming if project is in final state
                if status in ["completed", "failed", "deployed"]:
                    break

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app_builder_bp.route("/docs")
@login_required
def documentation():
    """App Builder documentation"""
    return render_template("tools/app_builder_docs.html")
