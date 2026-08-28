"""
A.R.C.H.I.E. MCP Server - Creation Tools
Phase 50.3: AI Integration Hub

Tools for project creation, Figma import, code generation,
and deployment via Model Context Protocol.
"""

import os
from database import _get_db_password
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any
import requests

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.creation")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}

# Platform URL for HTTP calls
PLATFORM_URL = os.getenv("ARCHIE_PLATFORM_URL", "http://localhost:3000")


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


# ============================================================================
# CREATE PROJECT TOOL
# ============================================================================


async def create_project_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new project in A.R.C.H.I.E.'s Project Builder

    Initializes a project with optional template and auto-generates
    initial files based on project type.
    """
    name = arguments.get("name", "").strip()
    description = arguments.get("description", "")
    project_type = arguments.get("project_type", "web_app")
    template = arguments.get("template", "blank")
    prompt = arguments.get("prompt", "")
    user_id = arguments.get("user_id", 2)  # Default admin user

    if not name:
        return {"success": False, "error": "Project name is required"}

    # Valid project types
    valid_types = ["web_app", "mobile_app", "api", "game", "desktop", "library"]
    if project_type not in valid_types:
        return {
            "success": False,
            "error": f"Invalid project_type. Must be one of: {valid_types}",
        }

    # Valid templates
    valid_templates = [
        "blank",
        "react",
        "vue",
        "nextjs",
        "flask",
        "fastapi",
        "express",
        "django",
        "unity",
        "godot",
        "electron",
    ]

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get tech stack based on template
        tech_stack = _get_template_tech_stack(template, project_type)

        # Generate prompt if not provided
        if not prompt:
            prompt = f"Create a {project_type} project"
            if template != "blank":
                prompt += f" using {template} template"

        # Insert project
        cur.execute(
            """
            INSERT INTO app_builder_projects
            (user_id, name, description, project_type, user_prompt, tech_stack, status, tags)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s)
            RETURNING id, name, description, project_type, status, created_at
        """,
            (
                user_id,
                name,
                description,
                project_type,
                prompt,
                json.dumps(tech_stack),
                [template] if template != "blank" else [],
            ),
        )

        project = dict(cur.fetchone())
        conn.commit()

        # Generate initial template files if not blank
        files_created = 0
        if template != "blank":
            files_created = _generate_template_files(cur, conn, project["id"], template, tech_stack)

        cur.close()
        conn.close()

        logger.info(f"Created project {project['id']}: {name} ({project_type})")

        return {
            "success": True,
            "project": project,
            "template": template,
            "tech_stack": tech_stack,
            "files_created": files_created,
            "message": f"Project '{name}' created successfully",
        }

    except psycopg2.errors.UniqueViolation:
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": "Project with this name already exists"}
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


def _get_template_tech_stack(template: str, project_type: str) -> Dict:
    """Get tech stack configuration for a template"""
    stacks = {
        "blank": {"frontend": None, "backend": None, "database": None},
        "react": {
            "frontend": "react",
            "backend": None,
            "database": None,
            "styling": "tailwind",
        },
        "vue": {
            "frontend": "vue",
            "backend": None,
            "database": None,
            "styling": "tailwind",
        },
        "nextjs": {
            "frontend": "nextjs",
            "backend": "nextjs",
            "database": "prisma",
            "styling": "tailwind",
        },
        "flask": {
            "frontend": None,
            "backend": "flask",
            "database": "postgresql",
            "styling": None,
        },
        "fastapi": {
            "frontend": None,
            "backend": "fastapi",
            "database": "postgresql",
            "styling": None,
        },
        "express": {
            "frontend": None,
            "backend": "express",
            "database": "mongodb",
            "styling": None,
        },
        "django": {
            "frontend": None,
            "backend": "django",
            "database": "postgresql",
            "styling": None,
        },
        "unity": {"engine": "unity", "language": "csharp"},
        "godot": {"engine": "godot", "language": "gdscript"},
        "electron": {"frontend": "react", "backend": "electron", "database": "sqlite"},
    }
    return stacks.get(template, stacks["blank"])


def _generate_template_files(cur, conn, project_id: int, template: str, tech_stack: Dict) -> int:
    """Generate initial template files for a project"""
    files_created = 0

    # Basic files for all templates
    base_files = {
        "README.md": f"# Project\n\nCreated with A.R.C.H.I.E. Project Builder\n\nTemplate: {template}",
        ".gitignore": "node_modules/\n.env\n*.log\ndist/\nbuild/\n__pycache__/",
    }

    # Template-specific files
    template_files = {
        "react": {
            "src/App.tsx": """import React from 'react';

export default function App() {
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <h1 className="text-3xl font-bold text-gray-900">Welcome to Your App</h1>
      <p className="mt-4 text-gray-600">Built with A.R.C.H.I.E. Project Builder</p>
    </div>
  );
}
""",
            "src/index.tsx": """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
""",
            "package.json": json.dumps(
                {
                    "name": "archie-project",
                    "version": "0.1.0",
                    "scripts": {
                        "dev": "vite",
                        "build": "vite build",
                        "preview": "vite preview",
                    },
                    "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
                    "devDependencies": {
                        "vite": "^5.0.0",
                        "@vitejs/plugin-react": "^4.0.0",
                        "typescript": "^5.0.0",
                    },
                },
                indent=2,
            ),
        },
        "flask": {
            "app.py": """from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({'message': 'Welcome to your Flask API', 'status': 'ok'})

@app.route('/api/health')
def health():
    return jsonify({'healthy': True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
""",
            "requirements.txt": "flask>=3.0.0\nflask-cors>=4.0.0\npsycopg2-binary>=2.9.9\npython-dotenv>=1.0.0",
        },
        "fastapi": {
            "main.py": """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="A.R.C.H.I.E. Project")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to your FastAPI project"}

@app.get("/health")
async def health():
    return {"healthy": True}
""",
            "requirements.txt": "fastapi>=0.109.0\nuvicorn>=0.27.0\npydantic>=2.0.0",
        },
    }

    # Merge base files with template files
    all_files = {**base_files, **template_files.get(template, {})}

    for filename, content in all_files.items():
        try:
            cur.execute(
                """
                INSERT INTO app_builder_files
                (project_id, file_name, file_path, content, file_type, status)
                VALUES (%s, %s, %s, %s, %s, 'generated')
            """,
                (project_id, filename, filename, content, _get_file_type(filename)),
            )
            files_created += 1
        except Exception as e:
            logger.warning(f"Failed to create file {filename}: {e}")

    conn.commit()
    return files_created


def _get_file_type(filename: str) -> str:
    """Determine file type from filename"""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".md": "markdown",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".sql": "sql",
    }
    for ext, ftype in ext_map.items():
        if filename.endswith(ext):
            return ftype
    return "text"


# ============================================================================
# LIST PROJECTS TOOL
# ============================================================================


async def list_projects_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all projects for a user

    Returns projects with their status, type, and file counts.
    """
    user_id = arguments.get("user_id", 2)
    status = arguments.get("status")  # Optional filter: draft, active, archived
    project_type = arguments.get("project_type")  # Optional filter
    limit = min(arguments.get("limit", 20), 100)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        conditions = ["user_id = %s"]
        params = [user_id]

        if status:
            conditions.append("status = %s")
            params.append(status)

        if project_type:
            conditions.append("project_type = %s")
            params.append(project_type)

        where_clause = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT p.*,
                   (SELECT COUNT(*) FROM app_builder_files f WHERE f.project_id = p.id) as file_count
            FROM app_builder_projects p
            WHERE {where_clause}
            ORDER BY p.updated_at DESC NULLS LAST, p.created_at DESC
            LIMIT %s
        """,
            params + [limit],
        )

        projects = [dict(p) for p in cur.fetchall()]

        # Get summary stats
        cur.execute(
            """
            SELECT project_type, COUNT(*) as count
            FROM app_builder_projects
            WHERE user_id = %s
            GROUP BY project_type
        """,
            (user_id,),
        )
        by_type = {row["project_type"]: row["count"] for row in cur.fetchall()}

        cur.close()
        conn.close()

        return {
            "success": True,
            "total": len(projects),
            "projects": projects,
            "by_type": by_type,
            "filters_applied": {"status": status, "project_type": project_type},
        }

    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# GET PROJECT TOOL
# ============================================================================


async def get_project_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get detailed information about a specific project

    Includes project metadata, files, and recent activity.
    """
    project_id = arguments.get("project_id")
    include_files = arguments.get("include_files", True)
    user_id = arguments.get("user_id", 2)

    if not project_id:
        return {"success": False, "error": "project_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get project
        cur.execute(
            """
            SELECT * FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, user_id),
        )

        project = cur.fetchone()
        if not project:
            cur.close()
            conn.close()
            return {"success": False, "error": "Project not found"}

        project = dict(project)

        # Get files if requested
        files = []
        if include_files:
            cur.execute(
                """
                SELECT id, file_name, file_path, file_type, status,
                       LENGTH(content) as size, created_at, updated_at
                FROM app_builder_files
                WHERE project_id = %s
                ORDER BY file_path
            """,
                (project_id,),
            )
            files = [dict(f) for f in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "success": True,
            "project": project,
            "files": files,
            "file_count": len(files),
        }

    except Exception as e:
        logger.error(f"Error getting project: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# GENERATE CODE TOOL
# ============================================================================


async def generate_code_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate code using AI for a project

    Uses A.R.C.H.I.E.'s AI Bridge to generate code based on a prompt.
    Can target a specific file or create new files.
    """
    project_id = arguments.get("project_id")
    prompt = arguments.get("prompt", "")
    target_file = arguments.get("target_file")
    language = arguments.get("language", "typescript")
    user_id = arguments.get("user_id", 2)

    if not project_id:
        return {"success": False, "error": "project_id is required"}
    if not prompt:
        return {"success": False, "error": "prompt is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Verify project exists
        cur.execute(
            """
            SELECT id, name, project_type, tech_stack
            FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, user_id),
        )

        project = cur.fetchone()
        if not project:
            cur.close()
            conn.close()
            return {"success": False, "error": "Project not found"}

        project = dict(project)

        # Get existing file content if targeting a file
        existing_code = None
        if target_file:
            cur.execute(
                """
                SELECT content FROM app_builder_files
                WHERE project_id = %s AND file_name = %s
            """,
                (project_id, target_file),
            )
            result = cur.fetchone()
            if result:
                existing_code = result["content"]

        # Build context for AI
        tech_stack = project.get("tech_stack", {})
        if isinstance(tech_stack, str):
            tech_stack = json.loads(tech_stack)

        context = f"""Project: {project['name']}
Type: {project['project_type']}
Tech Stack: {json.dumps(tech_stack)}
Language: {language}
"""
        if existing_code:
            context += f"\nExisting code to modify:\n```\n{existing_code[:2000]}\n```"

        full_prompt = f"{context}\n\nUser Request: {prompt}"

        # Route through Department HQ dispatcher (ADR-013, Task #1298). The
        # legacy /tools/starbase/api/generate route was removed when Starbase
        # merged into Fleet — every prior call to this handler 404'd and
        # silently fell back to a template. Going through dispatch() gives
        # us welfare gating, agent selection, and a tagged
        # task_execution_log row courtesy of claude_request.
        try:
            from tools.department_hq.services.department_dispatcher import dispatch

            try:
                from mcp_server.dispatch_context import claude_request
            except Exception:
                from contextlib import contextmanager

                @contextmanager
                def claude_request(mcp_tool: str, origin: str = "claude"):  # type: ignore[no-redef]
                    yield

            with claude_request(mcp_tool="generate_code", origin="claude"):
                dispatch_result = dispatch(
                    capability="code",
                    prompt=full_prompt,
                    module_id="mcp_generate_code",
                )

            if dispatch_result.success and getattr(dispatch_result, "response", None):
                generated_code = dispatch_result.response

                # Save to file if target specified
                if target_file and generated_code:
                    cur.execute(
                        """
                        INSERT INTO app_builder_files
                        (project_id, file_name, file_path, content, file_type, status)
                        VALUES (%s, %s, %s, %s, %s, 'generated')
                        ON CONFLICT (project_id, file_path)
                        DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                    """,
                        (
                            project_id,
                            target_file,
                            target_file,
                            generated_code,
                            language,
                        ),
                    )
                    conn.commit()

                cur.close()
                conn.close()

                return {
                    "success": True,
                    "code": generated_code,
                    "language": language,
                    "target_file": target_file,
                    "saved": target_file is not None,
                    "project": project["name"],
                    "agent": getattr(dispatch_result, "agent_name", None),
                    "model": getattr(dispatch_result, "model_used", None),
                }

            # Dispatch failed (no agent, welfare block, model unavailable, etc.)
            cur.close()
            conn.close()
            return {
                "success": True,
                "code": _generate_fallback_code(prompt, language, project),
                "language": language,
                "note": (
                    "Generated using fallback template — dispatch failed: "
                    f"{getattr(dispatch_result, 'error', None) or 'unknown'}"
                ),
            }

        except Exception as dispatch_err:
            logger.warning(f"Bridge dispatch raised in generate_code: {dispatch_err}")
            cur.close()
            conn.close()
            return {
                "success": True,
                "code": _generate_fallback_code(prompt, language, project),
                "language": language,
                "note": f"Generated using fallback template (dispatch error: {dispatch_err})",
            }

    except Exception as e:
        logger.error(f"Error generating code: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


def _generate_fallback_code(prompt: str, language: str, project: Dict) -> str:
    """Generate fallback code when AI is unavailable"""
    templates = {
        "typescript": f"""// Generated for: {prompt[:100]}
// Project: {project.get('name', 'Unknown')}

import React from 'react';

interface Props {{
  // Add props here
}}

export default function Component({{ }}: Props) {{
  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold">Component</h1>
      <p className="mt-2 text-gray-600">Generated from prompt: {prompt[:50]}...</p>
    </div>
  );
}}
""",
        "python": f'''# Generated for: {prompt[:100]}
# Project: {project.get('name', 'Unknown')}

def main():
    """Main function"""
    print("Generated from A.R.C.H.I.E. Project Builder")
    # TODO: Implement based on prompt
    pass

if __name__ == "__main__":
    main()
''',
        "javascript": f"""// Generated for: {prompt[:100]}
// Project: {project.get('name', 'Unknown')}

function main() {{
  console.log('Generated from A.R.C.H.I.E. Project Builder');
  // TODO: Implement based on prompt
}}

module.exports = {{ main }};
""",
    }
    return templates.get(language, templates["typescript"])


# ============================================================================
# IMPORT FIGMA DESIGN TOOL
# ============================================================================


async def import_figma_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Import a design from Figma into a project

    Fetches design data from Figma and generates code components.
    Requires Figma OAuth to be connected for the user.
    """
    project_id = arguments.get("project_id")
    figma_file_key = arguments.get("file_key")
    node_ids = arguments.get("node_ids", [])  # Specific nodes to import
    framework = arguments.get("framework", "react")
    user_id = arguments.get("user_id", 2)

    if not project_id:
        return {"success": False, "error": "project_id is required"}
    if not figma_file_key:
        return {
            "success": False,
            "error": "file_key is required (Figma file key from URL)",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Verify project
        cur.execute(
            """
            SELECT id, name FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, user_id),
        )

        project = cur.fetchone()
        if not project:
            cur.close()
            conn.close()
            return {"success": False, "error": "Project not found"}

        # Check if user has Figma token
        cur.execute(
            """
            SELECT access_token FROM user_oauth_tokens
            WHERE user_id = %s AND provider = 'figma' AND expires_at > NOW()
        """,
            (user_id,),
        )

        token = cur.fetchone()
        if not token:
            cur.close()
            conn.close()
            return {
                "success": False,
                "error": "Figma not connected. Please connect Figma OAuth first at /tools/figma",
                "action_required": "connect_figma",
            }

        # Call Figma API through platform
        try:
            response = requests.post(
                f"{PLATFORM_URL}/tools/figma/api/parse",
                json={
                    "file_key": figma_file_key,
                    "node_ids": (node_ids if isinstance(node_ids, list) else [node_ids] if node_ids else []),
                    "framework": framework,
                },
                headers={"X-User-Id": str(user_id)},
                timeout=120,
            )

            if response.status_code == 200:
                result = response.json()
                parse_id = result.get("parse_id")

                # If successful, generate code
                if parse_id:
                    gen_response = requests.post(
                        f"{PLATFORM_URL}/tools/figma/api/generate",
                        json={
                            "parse_id": parse_id,
                            "framework": framework,
                            "options": {"tailwind": True, "typescript": True},
                        },
                        headers={"X-User-Id": str(user_id)},
                        timeout=120,
                    )

                    if gen_response.status_code == 200:
                        gen_result = gen_response.json()

                        # Import generated files to project
                        files_imported = 0
                        for comp in gen_result.get("components", []):
                            comp_filename = f"src/components/{comp.get('name', 'Component')}.tsx"
                            code = comp.get("code", "")

                            cur.execute(
                                """
                                INSERT INTO app_builder_files
                                (project_id, file_name, file_path, content, file_type, status)
                                VALUES (%s, %s, %s, %s, 'typescript', 'imported')
                                ON CONFLICT (project_id, file_path)
                                DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                            """,
                                (project_id, comp_filename, comp_filename, code),
                            )
                            files_imported += 1

                        conn.commit()
                        cur.close()
                        conn.close()

                        return {
                            "success": True,
                            "files_imported": files_imported,
                            "parse_id": parse_id,
                            "components": len(gen_result.get("components", [])),
                            "message": f"Imported {files_imported} components from Figma",
                        }

            cur.close()
            conn.close()
            return {
                "success": False,
                "error": f"Figma import failed: {response.text[:200]}",
            }

        except requests.exceptions.RequestException as e:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Figma API request failed: {e}"}

    except Exception as e:
        logger.error(f"Error importing from Figma: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# DEPLOY PROJECT TOOL
# ============================================================================


async def deploy_project_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deploy a project to a hosting platform

    Supports deployment to GitHub Pages, Vercel, Netlify, or custom servers.
    Requires the respective platform to be connected via OAuth.
    """
    project_id = arguments.get("project_id")
    deployment_type = arguments.get("deployment_type", "github_pages")
    branch = arguments.get("branch", "main")
    environment = arguments.get("environment", "production")
    user_id = arguments.get("user_id", 2)

    if not project_id:
        return {"success": False, "error": "project_id is required"}

    valid_deployments = ["github_pages", "vercel", "netlify", "custom"]
    if deployment_type not in valid_deployments:
        return {
            "success": False,
            "error": f"Invalid deployment_type. Must be one of: {valid_deployments}",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get project
        cur.execute(
            """
            SELECT * FROM app_builder_projects
            WHERE id = %s AND user_id = %s
        """,
            (project_id, user_id),
        )

        project = cur.fetchone()
        if not project:
            cur.close()
            conn.close()
            return {"success": False, "error": "Project not found"}

        project = dict(project)

        # Check OAuth connection for deployment type
        provider = deployment_type.split("_")[0]  # github_pages -> github
        cur.execute(
            """
            SELECT id FROM user_oauth_tokens
            WHERE user_id = %s AND provider = %s AND expires_at > NOW()
        """,
            (user_id, provider),
        )

        if not cur.fetchone():
            cur.close()
            conn.close()
            return {
                "success": False,
                "error": f"Please connect your {provider} account first",
                "action_required": f"connect_{provider}",
            }

        # Call deployment endpoint
        try:
            response = requests.post(
                f"{PLATFORM_URL}/tools/website-studio/api/projects/{project_id}/deploy",
                json={
                    "deployment_type": deployment_type,
                    "branch": branch,
                    "environment": environment,
                },
                headers={"X-User-Id": str(user_id)},
                timeout=180,
            )

            if response.status_code == 200:
                result = response.json()

                # Log deployment
                cur.execute(
                    """
                    INSERT INTO website_deployments
                    (project_id, deployed_by, deployment_type, environment, status)
                    VALUES (%s, %s, %s, %s, 'completed')
                    RETURNING id
                """,
                    (project_id, user_id, deployment_type, environment),
                )
                deployment_id = cur.fetchone()["id"]
                conn.commit()

                cur.close()
                conn.close()

                return {
                    "success": True,
                    "deployment_id": deployment_id,
                    "deployment_type": deployment_type,
                    "url": result.get("url"),
                    "status": "deployed",
                    "message": f"Project deployed to {deployment_type}",
                }
            else:
                cur.close()
                conn.close()
                return {
                    "success": False,
                    "error": f"Deployment failed: {response.text[:200]}",
                }

        except requests.exceptions.RequestException as e:
            cur.close()
            conn.close()
            return {"success": False, "error": f"Deployment request failed: {e}"}

    except Exception as e:
        logger.error(f"Error deploying project: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_creation_tools():
    """Register all creation tools with the MCP server"""

    # Create Project
    register_tool(
        name="create_project",
        category="creation",
        description="Create a new project in A.R.C.H.I.E. Project Builder with optional template. Supports web apps, APIs, mobile apps, games, and more.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name (required)"},
                "description": {"type": "string", "description": "Project description"},
                "project_type": {
                    "type": "string",
                    "enum": [
                        "web_app",
                        "mobile_app",
                        "api",
                        "game",
                        "desktop",
                        "library",
                    ],
                    "description": "Type of project",
                    "default": "web_app",
                },
                "template": {
                    "type": "string",
                    "enum": [
                        "blank",
                        "react",
                        "vue",
                        "nextjs",
                        "flask",
                        "fastapi",
                        "express",
                        "django",
                        "unity",
                        "godot",
                        "electron",
                    ],
                    "description": "Project template to use",
                    "default": "blank",
                },
                "prompt": {
                    "type": "string",
                    "description": "Initial prompt/description for the project",
                },
            },
            "required": ["name"],
        },
        handler=create_project_handler,
        requires_permission="write",
    )

    # List Projects
    register_tool(
        name="list_projects",
        category="creation",
        description="List all projects for a user. Filter by status or project type.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "active", "archived"],
                    "description": "Filter by project status",
                },
                "project_type": {
                    "type": "string",
                    "description": "Filter by project type",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max projects to return (default: 20)",
                    "default": 20,
                },
            },
        },
        handler=list_projects_handler,
        requires_permission="read",
    )

    # Get Project
    register_tool(
        name="get_project",
        category="creation",
        description="Get detailed information about a specific project including files.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (required)",
                },
                "include_files": {
                    "type": "boolean",
                    "description": "Include file list in response",
                    "default": True,
                },
            },
            "required": ["project_id"],
        },
        handler=get_project_handler,
        requires_permission="read",
    )

    # Generate Code
    register_tool(
        name="generate_code",
        category="creation",
        description="Generate code using AI for a project. Can create new files or modify existing ones.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (required)",
                },
                "prompt": {
                    "type": "string",
                    "description": "What code to generate (required)",
                },
                "target_file": {
                    "type": "string",
                    "description": "File to create/modify (optional)",
                },
                "language": {
                    "type": "string",
                    "enum": ["typescript", "javascript", "python", "rust", "go"],
                    "description": "Programming language",
                    "default": "typescript",
                },
            },
            "required": ["project_id", "prompt"],
        },
        handler=generate_code_handler,
        requires_permission="write",
    )

    # Import Figma Design
    register_tool(
        name="import_figma_design",
        category="creation",
        description="Import a Figma design into a project. Generates React/Vue components from Figma frames.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Project ID to import into (required)",
                },
                "file_key": {
                    "type": "string",
                    "description": "Figma file key from URL (required)",
                },
                "node_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific node IDs to import (optional, imports all if empty)",
                },
                "framework": {
                    "type": "string",
                    "enum": ["react", "vue", "html"],
                    "description": "Target framework for generated code",
                    "default": "react",
                },
            },
            "required": ["project_id", "file_key"],
        },
        handler=import_figma_handler,
        requires_permission="write",
    )

    # Deploy Project
    register_tool(
        name="deploy_project",
        category="creation",
        description="Deploy a project to a hosting platform (GitHub Pages, Vercel, Netlify).",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "integer",
                    "description": "Project ID to deploy (required)",
                },
                "deployment_type": {
                    "type": "string",
                    "enum": ["github_pages", "vercel", "netlify", "custom"],
                    "description": "Deployment platform",
                    "default": "github_pages",
                },
                "branch": {
                    "type": "string",
                    "description": "Git branch to deploy from",
                    "default": "main",
                },
                "environment": {
                    "type": "string",
                    "enum": ["production", "staging", "preview"],
                    "description": "Deployment environment",
                    "default": "production",
                },
            },
            "required": ["project_id"],
        },
        handler=deploy_project_handler,
        requires_permission="write",
    )

    logger.info(
        "Registered 6 creation tools: create_project, list_projects, get_project, generate_code, import_figma_design, deploy_project"
    )


# Auto-register when module is imported
register_creation_tools()
