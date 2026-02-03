"""
Project Builder Routes - Phase 47 Enhanced
AI-powered website and application builder with full database integration.

Features:
- Project CRUD with database persistence
- Template-based project scaffolding
- AI-assisted code generation
- File management with versioning
- Figma import integration
- Sandbox preview
"""

import os
import json
import logging
import hashlib
from datetime import datetime  # noqa: F401
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from . import project_builder_bp

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# =============================================================================
# MAIN PAGE
# =============================================================================


@project_builder_bp.route("/")
@login_required
def index():
    """Project Builder main page"""
    return render_template("tools/project_builder.html")


@project_builder_bp.route("/api/status")
@login_required
def status():
    """API endpoint for module health check"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM app_builder_projects")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify(
            {
                "module": "project_builder",
                "status": "active",
                "healthy": True,
                "total_projects": count,
                "message": "Project Builder operational",
            }
        )
    except Exception as e:
        return jsonify({"module": "project_builder", "status": "error", "healthy": False, "message": str(e)})


# =============================================================================
# DASHBOARD STATS
# =============================================================================


@project_builder_bp.route("/api/stats")
@login_required
def get_stats():
    """Get user's project statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'active') as active,
                COUNT(*) FILTER (WHERE status = 'deployed') as deployed,
                COUNT(*) FILTER (WHERE status = 'draft') as drafts
            FROM app_builder_projects
            WHERE user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total": stats["total"] or 0,
                    "active": stats["active"] or 0,
                    "deployed": stats["deployed"] or 0,
                    "drafts": stats["drafts"] or 0,
                    "templates": 12,  # Static template count
                },
            }
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# PROJECTS CRUD
# =============================================================================


@project_builder_bp.route("/api/projects", methods=["GET"])
@login_required
def get_projects():
    """Get all user projects"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, description, project_type, status, progress,
                   total_files, total_lines, deployed, deployment_url,
                   tags, created_at, updated_at
            FROM app_builder_projects
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """,
            (current_user.id,),
        )
        projects = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "projects": projects})
    except Exception as e:
        logger.error(f"Failed to get projects: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects", methods=["POST"])
@login_required
def create_project():
    """Create a new project"""
    try:
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        description = data.get("description", "")
        project_type = data.get("type", "web_app")
        template = data.get("template", "blank")
        user_prompt = data.get("prompt", f"Create a {project_type} project")

        if not name:
            return jsonify({"success": False, "error": "Project name is required"}), 400

        # Get template tech stack
        tech_stack = get_template_tech_stack(template, project_type)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO app_builder_projects
            (user_id, name, description, project_type, user_prompt, tech_stack, status, tags)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s)
            RETURNING id, name, description, project_type, status, created_at
        """,
            (current_user.id, name, description, project_type, user_prompt, json.dumps(tech_stack), [template]),
        )

        project = cur.fetchone()
        conn.commit()

        # Generate initial files based on template
        if template != "blank":
            generate_template_files(cur, project["id"], template, tech_stack)
            conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True, "project": project, "message": "Project created successfully"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"success": False, "error": "Project with this name already exists"}), 400
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects/<int:project_id>")
@login_required
def get_project(project_id):
    """Get project details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, current_user.id),
        )
        project = cur.fetchone()

        if not project:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Project not found"}), 404

        # Get project files
        cur.execute(
            """
            SELECT id, file_path, file_name, file_type, line_count, version, is_latest
            FROM app_builder_files
            WHERE project_id = %s AND is_latest = TRUE
            ORDER BY file_path
        """,
            (project_id,),
        )
        files = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "project": project, "files": files})
    except Exception as e:
        logger.error(f"Failed to get project: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects/<int:project_id>", methods=["PUT"])
@login_required
def update_project(project_id):
    """Update project details"""
    try:
        data = request.get_json() or {}

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build dynamic update query
        updates = []
        params = []

        if "name" in data:
            updates.append("name = %s")
            params.append(data["name"])
        if "description" in data:
            updates.append("description = %s")
            params.append(data["description"])
        if "status" in data:
            updates.append("status = %s")
            params.append(data["status"])
        if "tags" in data:
            updates.append("tags = %s")
            params.append(data["tags"])

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        params.extend([project_id, current_user.id])

        cur.execute(
            f"""
            UPDATE app_builder_projects
            SET {', '.join(updates)}
            WHERE id = %s AND user_id = %s
            RETURNING id, name, status, updated_at
        """,
            params,
        )

        project = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404

        return jsonify({"success": True, "project": project, "message": "Project updated"})
    except Exception as e:
        logger.error(f"Failed to update project: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
def delete_project(project_id):
    """Delete a project"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM app_builder_projects
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (project_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Project not found"}), 404

        return jsonify({"success": True, "message": "Project deleted successfully"})
    except Exception as e:
        logger.error(f"Failed to delete project: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# FILES
# =============================================================================


@project_builder_bp.route("/api/projects/<int:project_id>/files")
@login_required
def get_project_files(project_id):
    """Get project files"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT id FROM app_builder_projects WHERE id = %s AND user_id = %s", (project_id, current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Project not found"}), 404

        cur.execute(
            """
            SELECT id, file_path, file_name, file_type, content, line_count, version
            FROM app_builder_files
            WHERE project_id = %s AND is_latest = TRUE
            ORDER BY file_path
        """,
            (project_id,),
        )
        files = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "files": files})
    except Exception as e:
        logger.error(f"Failed to get files: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects/<int:project_id>/files", methods=["POST"])
@login_required
def create_file(project_id):
    """Create or update a file in the project"""
    try:
        data = request.get_json() or {}
        file_path = data.get("path", "").strip()
        content = data.get("content", "")
        file_type = data.get("type", "text")

        if not file_path:
            return jsonify({"success": False, "error": "File path is required"}), 400

        file_name = os.path.basename(file_path)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        line_count = len(content.split("\n"))
        size_bytes = len(content.encode("utf-8"))

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT id FROM app_builder_projects WHERE id = %s AND user_id = %s", (project_id, current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Project not found"}), 404

        # Check if file exists
        cur.execute(
            """
            SELECT id, version FROM app_builder_files
            WHERE project_id = %s AND file_path = %s AND is_latest = TRUE
        """,
            (project_id, file_path),
        )
        existing = cur.fetchone()

        if existing:
            # Mark old version as not latest
            cur.execute("UPDATE app_builder_files SET is_latest = FALSE WHERE id = %s", (existing["id"],))
            new_version = existing["version"] + 1
            previous_id = existing["id"]
        else:
            new_version = 1
            previous_id = None

        # Insert new version
        cur.execute(
            """
            INSERT INTO app_builder_files
            (project_id, file_path, file_name, file_type, content, content_hash,
             size_bytes, line_count, version, previous_version_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, file_path, file_name, version
        """,
            (
                project_id,
                file_path,
                file_name,
                file_type,
                content,
                content_hash,
                size_bytes,
                line_count,
                new_version,
                previous_id,
            ),
        )

        file_record = cur.fetchone()

        # Update project stats
        cur.execute(
            """
            UPDATE app_builder_projects
            SET total_files = (
                SELECT COUNT(DISTINCT file_path)
                FROM app_builder_files WHERE project_id = %s AND is_latest = TRUE
            ),
                total_lines = (
                SELECT COALESCE(SUM(line_count), 0)
                FROM app_builder_files WHERE project_id = %s AND is_latest = TRUE
            ),
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id, project_id, project_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "file": file_record,
                "message": f"File {'updated' if previous_id else 'created'} (v{new_version})",
            }
        )
    except Exception as e:
        logger.error(f"Failed to create file: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@project_builder_bp.route("/api/projects/<int:project_id>/files/<int:file_id>")
@login_required
def get_file(project_id, file_id):
    """Get a specific file with content"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT f.* FROM app_builder_files f
            JOIN app_builder_projects p ON f.project_id = p.id
            WHERE f.id = %s AND p.id = %s AND p.user_id = %s
        """,
            (file_id, project_id, current_user.id),
        )
        file = cur.fetchone()

        cur.close()
        conn.close()

        if not file:
            return jsonify({"success": False, "error": "File not found"}), 404

        return jsonify({"success": True, "file": file})
    except Exception as e:
        logger.error(f"Failed to get file: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# TEMPLATES
# =============================================================================


@project_builder_bp.route("/api/templates")
@login_required
def get_templates():
    """Get available project templates"""
    templates = [
        {
            "id": "landing-page",
            "name": "Landing Page",
            "category": "website",
            "description": "Modern single-page marketing site with hero, features, and CTA sections",
            "icon": "layout",
            "tech": ["HTML", "Tailwind CSS", "JavaScript"],
        },
        {
            "id": "portfolio",
            "name": "Portfolio",
            "category": "website",
            "description": "Showcase your work with a beautiful portfolio layout",
            "icon": "image",
            "tech": ["React", "Tailwind CSS", "Framer Motion"],
        },
        {
            "id": "blog",
            "name": "Blog",
            "category": "website",
            "description": "Content-focused publishing platform with MDX support",
            "icon": "file-text",
            "tech": ["Next.js", "MDX", "Tailwind CSS"],
        },
        {
            "id": "ecommerce",
            "name": "E-Commerce",
            "category": "website",
            "description": "Online store with cart, checkout, and payment integration",
            "icon": "shopping-cart",
            "tech": ["Next.js", "Stripe", "Tailwind CSS"],
        },
        {
            "id": "dashboard",
            "name": "Dashboard",
            "category": "webapp",
            "description": "Admin panel with analytics, charts, and data management",
            "icon": "layout-dashboard",
            "tech": ["React", "Recharts", "Tailwind CSS"],
        },
        {
            "id": "saas",
            "name": "SaaS App",
            "category": "webapp",
            "description": "Full-featured web application with auth, billing, and teams",
            "icon": "cloud",
            "tech": ["Next.js", "Prisma", "Stripe", "NextAuth"],
        },
        {
            "id": "crm",
            "name": "CRM",
            "category": "webapp",
            "description": "Customer management system with contacts and pipeline",
            "icon": "users",
            "tech": ["React", "Node.js", "PostgreSQL"],
        },
        {
            "id": "api",
            "name": "API Service",
            "category": "backend",
            "description": "RESTful backend with authentication and database",
            "icon": "server",
            "tech": ["Node.js", "Express", "PostgreSQL"],
        },
        {
            "id": "react-native",
            "name": "Mobile App",
            "category": "mobile",
            "description": "Cross-platform mobile app with React Native",
            "icon": "smartphone",
            "tech": ["React Native", "Expo", "NativeWind"],
        },
        {
            "id": "pwa",
            "name": "PWA",
            "category": "mobile",
            "description": "Progressive Web App with offline support",
            "icon": "globe",
            "tech": ["Next.js", "PWA", "Service Worker"],
        },
        {
            "id": "chrome-extension",
            "name": "Chrome Extension",
            "category": "extension",
            "description": "Browser extension with popup and content scripts",
            "icon": "puzzle",
            "tech": ["JavaScript", "Chrome APIs", "Tailwind CSS"],
        },
        {
            "id": "blank",
            "name": "Blank Project",
            "category": "other",
            "description": "Start from scratch with a clean slate",
            "icon": "plus",
            "tech": [],
        },
    ]

    return jsonify({"success": True, "templates": templates})


# =============================================================================
# AI GENERATION
# =============================================================================


@project_builder_bp.route("/api/projects/<int:project_id>/generate", methods=["POST"])
@login_required
def generate_code(project_id):
    """Generate code for a project using AI"""
    try:
        data = request.get_json() or {}
        prompt = data.get("prompt", "")
        target_file = data.get("file")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, current_user.id),
        )
        project = cur.fetchone()

        if not project:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Project not found"}), 404

        # TODO: Integrate with AI Bridge for actual code generation
        # For now, return a demo response
        demo_code = f"""// Generated code for: {prompt}
// Project: {project['name']}
// Target: {target_file or 'new file'}

import React from 'react';

export default function Component() {{
  return (
    <div className="p-4">
      <h1>Generated Component</h1>
      <p>This is a placeholder for AI-generated code.</p>
      <p>Prompt: {prompt[:100]}...</p>
    </div>
  );
}}
"""

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "code": demo_code,
                "language": "typescript",
                "note": "Demo response - AI Bridge integration coming soon",
            }
        )
    except Exception as e:
        logger.error(f"Failed to generate code: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# FIGMA IMPORT
# =============================================================================


@project_builder_bp.route("/api/projects/<int:project_id>/import-figma", methods=["POST"])
@login_required
def import_from_figma(project_id):
    """Import generated code from Figma integration"""
    try:
        data = request.get_json() or {}
        generation_id = data.get("generation_id")

        if not generation_id:
            return jsonify({"success": False, "error": "Generation ID required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify project ownership
        cur.execute("SELECT id FROM app_builder_projects WHERE id = %s AND user_id = %s", (project_id, current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Project not found"}), 404

        # Get Figma generation
        cur.execute(
            """
            SELECT files_generated FROM figma_code_generations
            WHERE id = %s AND user_id = %s
        """,
            (generation_id, current_user.id),
        )
        generation = cur.fetchone()

        if not generation:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Figma generation not found"}), 404

        files = generation["files_generated"] or []
        imported_count = 0

        for file_data in files:
            file_path = file_data.get("path", "")
            content = file_data.get("content", "")
            file_type = file_data.get("language", "text")

            if file_path and content:
                file_name = os.path.basename(file_path)
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                line_count = len(content.split("\n"))

                cur.execute(
                    """
                    INSERT INTO app_builder_files
                    (project_id, file_path, file_name, file_type, content, content_hash,
                     line_count, generated_by, generation_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'figma', 'import')
                    ON CONFLICT (project_id, file_path, version) DO UPDATE
                    SET content = EXCLUDED.content, updated_at = NOW()
                """,
                    (project_id, file_path, file_name, file_type, content, content_hash, line_count),
                )
                imported_count += 1

        # Update project stats
        cur.execute(
            """
            UPDATE app_builder_projects
            SET total_files = (
                SELECT COUNT(DISTINCT file_path)
                FROM app_builder_files WHERE project_id = %s AND is_latest = TRUE
            ),
                total_lines = (
                SELECT COALESCE(SUM(line_count), 0)
                FROM app_builder_files WHERE project_id = %s AND is_latest = TRUE
            ),
                updated_at = NOW()
            WHERE id = %s
        """,
            (project_id, project_id, project_id),
        )

        # Link Figma generation to project
        cur.execute(
            """
            UPDATE figma_code_generations
            SET exported_to_project = %s
            WHERE id = %s
        """,
            (project_id, generation_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "imported_files": imported_count,
                "message": f"Imported {imported_count} files from Figma",
            }
        )
    except Exception as e:
        logger.error(f"Failed to import from Figma: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# HELPERS
# =============================================================================


def get_template_tech_stack(template, project_type):
    """Get tech stack for a template"""
    stacks = {
        "landing-page": {"frontend": "html", "styling": "tailwind", "build": "vite"},
        "portfolio": {"frontend": "react", "styling": "tailwind", "animation": "framer-motion"},
        "blog": {"frontend": "nextjs", "content": "mdx", "styling": "tailwind"},
        "ecommerce": {"frontend": "nextjs", "payment": "stripe", "styling": "tailwind"},
        "dashboard": {"frontend": "react", "charts": "recharts", "styling": "tailwind"},
        "saas": {"frontend": "nextjs", "orm": "prisma", "auth": "nextauth", "payment": "stripe"},
        "crm": {"frontend": "react", "backend": "nodejs", "database": "postgresql"},
        "api": {"backend": "nodejs", "framework": "express", "database": "postgresql"},
        "react-native": {"mobile": "react-native", "expo": True, "styling": "nativewind"},
        "pwa": {"frontend": "nextjs", "pwa": True, "offline": True},
        "chrome-extension": {"extension": "chrome", "styling": "tailwind"},
        "blank": {},
    }
    return stacks.get(template, {})


def generate_template_files(cur, project_id, template, tech_stack):
    """Generate initial files for a template"""
    # Basic file structure for all templates
    files = []

    if template == "landing-page":
        files = [
            (
                "index.html",
                "html",
                """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Landing Page</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50">
    <header class="bg-white shadow">
        <nav class="container mx-auto px-4 py-4">
            <div class="flex justify-between items-center">
                <a href="#" class="text-xl font-bold text-indigo-600">Brand</a>
                <div class="space-x-4">
                    <a href="#features" class="text-gray-600 hover:text-indigo-600">Features</a>
                    <a href="#pricing" class="text-gray-600 hover:text-indigo-600">Pricing</a>
                    <a href="#contact" class="bg-indigo-600 text-white px-4 py-2 rounded-lg">Get Started</a>
                </div>
            </div>
        </nav>
    </header>
    <main>
        <section class="py-20 text-center">
            <h1 class="text-5xl font-bold text-gray-900 mb-6">Your Product Tagline</h1>
            <p class="text-xl text-gray-600 mb-8">Description of your amazing product goes here.</p>
            <button class="bg-indigo-600 text-white px-8 py-3 rounded-lg text-lg">Get Started</button>
        </section>
    </main>
</body>
</html>""",
            ),
            ("styles.css", "css", "/* Custom styles */"),
            ("main.js", "javascript", "// Main JavaScript"),
        ]
    elif template == "dashboard":
        files = [
            (
                "src/App.jsx",
                "jsx",
                """import React from 'react';

export default function App() {
  return (
    <div className="min-h-screen bg-gray-100">
      <nav className="bg-white shadow-sm">
        <div className="container mx-auto px-4 py-3">
          <h1 className="text-xl font-bold">Dashboard</h1>
        </div>
      </nav>
      <main className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-lg font-semibold mb-2">Total Users</h2>
            <p className="text-3xl font-bold text-indigo-600">1,234</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-lg font-semibold mb-2">Revenue</h2>
            <p className="text-3xl font-bold text-green-600">$12,345</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-lg font-semibold mb-2">Orders</h2>
            <p className="text-3xl font-bold text-orange-600">567</p>
          </div>
        </div>
      </main>
    </div>
  );
}""",
            ),
            (
                "src/index.jsx",
                "jsx",
                """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);""",
            ),
            (
                "package.json",
                "json",
                json.dumps(
                    {
                        "name": "dashboard",
                        "version": "1.0.0",
                        "scripts": {"dev": "vite", "build": "vite build"},
                        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
                        "devDependencies": {
                            "vite": "^5.0.0",
                            "@vitejs/plugin-react": "^4.0.0",
                            "tailwindcss": "^3.4.0",
                        },
                    },
                    indent=2,
                ),
            ),
        ]

    # Insert files
    for file_path, file_type, content in files:
        file_name = os.path.basename(file_path)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        line_count = len(content.split("\n"))

        cur.execute(
            """
            INSERT INTO app_builder_files
            (project_id, file_path, file_name, file_type, content, content_hash,
             line_count, generated_by, generation_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'template', 'scaffold')
        """,
            (project_id, file_path, file_name, file_type, content, content_hash, line_count),
        )
