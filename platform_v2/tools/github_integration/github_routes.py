"""
GitHub Integration Routes
Handles repository management, cloning, syncing, and content indexing
"""

from flask import Blueprint, request, jsonify, session
from flask_login import login_required, current_user
from functools import wraps
import os
from database import _get_db_password
import subprocess
import json
import requests
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from pathlib import Path

# Create Blueprint
github_bp = Blueprint("github", __name__, url_prefix="/tools/github")


# Database connection
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# Authentication decorator - uses Flask-Login
def require_auth(f):
    """Require authentication for routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Unauthorized - Please log in"}), 401
        return f(*args, **kwargs)

    return decorated_function


# ============================================================================
# GITHUB AUTHENTICATION & TESTING
# ============================================================================


@github_bp.route("/test-connection", methods=["POST"])
@require_auth
def test_github_connection():
    """Test GitHub API connection with provided token"""
    try:
        data = request.get_json() or {}
        token = data.get("token")

        if not token:
            return jsonify({"error": "GitHub token is required"}), 400

        # Test GitHub API with token
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        response = requests.get("https://api.github.com/user", headers=headers)

        if response.status_code == 200:
            user_data = response.json()
            return jsonify(
                {
                    "success": True,
                    "message": f'✓ Connected as {user_data.get("login")}',
                    "username": user_data.get("login"),
                    "name": user_data.get("name"),
                    "email": user_data.get("email"),
                }
            )
        elif response.status_code == 401:
            return jsonify({"error": "Invalid GitHub token"}), 401
        else:
            return jsonify({"error": f"GitHub API error: {response.status_code}"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@github_bp.route("/save-settings", methods=["POST"])
@require_auth
def save_github_settings():
    """Save GitHub configuration settings"""
    try:
        data = request.get_json() or {}

        # Store settings in database
        conn = get_db_connection()
        cursor = conn.cursor()

        settings = {
            "github_token": data.get("token"),
            "github_username": data.get("username"),
            "github_email": data.get("email"),
            "website_repo": data.get("website_repo"),
            "auto_deploy": data.get("auto_deploy", False),
            "auto_commit_docs": data.get("auto_commit_docs", True),
        }

        # Upsert settings
        for key, value in settings.items():
            cursor.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """,
                (key, json.dumps(value)),
            )

        conn.commit()
        cursor.close()

        return jsonify({"success": True, "message": "GitHub settings saved successfully"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@github_bp.route("/get-settings", methods=["GET"])
@require_auth
def get_github_settings():
    """Get saved GitHub configuration settings"""
    try:
        settings = {
            "token": get_setting("github_token", ""),
            "username": get_setting("github_username", ""),
            "email": get_setting("github_email", ""),
            "website_repo": get_setting("website_repo", ""),
            "auto_deploy": get_setting("auto_deploy", False),
            "auto_commit_docs": get_setting("auto_commit_docs", True),
        }

        return jsonify({"success": True, "settings": settings})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# REPOSITORY CLONING & MANAGEMENT
# ============================================================================


@github_bp.route("/clone-repo", methods=["POST"])
@require_auth
def clone_repository():
    """Clone a GitHub repository to local storage"""
    try:
        data = request.get_json() or {}
        repo = data.get("repo")  # Format: username/repository
        repo_type = data.get("type")  # 'website', 'ai-agents', 'prompts', 'n8n'

        if not repo:
            return jsonify({"error": "Repository is required"}), 400

        # Determine local path based on type
        if repo_type == "website":
            local_path = "/mnt/archie_brain/website"
        else:
            repo_name = repo.split("/")[-1]
            local_path = f"/mnt/archie_brain/learning_resources/{repo_name}"

        # Get GitHub token
        token = get_setting("github_token")

        # Clone repository
        if token:
            # Use token in clone URL for private repos
            clone_url = f"https://{token}@github.com/{repo}.git"
        else:
            # Public repo
            clone_url = f"https://github.com/{repo}.git"

        # Check if directory already exists
        if os.path.exists(local_path):
            return jsonify({"error": f"Directory already exists: {local_path}"}), 400

        # Create parent directory if needed
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # Clone repository
        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            # Update repository status in database
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO github_repositories
                (repo_name, repo_type, local_path, status, cloned_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (repo_name) DO UPDATE
                SET status = 'cloned', cloned_at = NOW(), updated_at = NOW()
            """,
                (repo, repo_type, local_path, "cloned"),
            )

            conn.commit()
            cursor.close()
            conn.close()

            # Count files
            file_count = sum(1 for _ in Path(local_path).rglob("*") if _.is_file())

            return jsonify(
                {
                    "success": True,
                    "message": f"✓ Repository cloned successfully",
                    "local_path": local_path,
                    "file_count": file_count,
                }
            )
        else:
            return jsonify({"error": f"Git clone failed: {result.stderr}"}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Clone operation timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@github_bp.route("/pull-repo", methods=["POST"])
@require_auth
def pull_repository():
    """Pull latest changes from GitHub repository"""
    try:
        data = request.get_json() or {}
        repo_type = data.get("type")
        local_path = data.get("local_path")

        if not local_path or not os.path.exists(local_path):
            return jsonify({"error": "Repository not found locally"}), 404

        # Pull latest changes
        result = subprocess.run(
            ["git", "-C", local_path, "pull"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            # Update repository status
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE github_repositories
                SET updated_at = NOW(), last_pull = NOW()
                WHERE local_path = %s
            """,
                (local_path,),
            )

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": "✓ Repository updated successfully",
                    "output": result.stdout,
                }
            )
        else:
            return jsonify({"error": f"Git pull failed: {result.stderr}"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@github_bp.route("/push-repo", methods=["POST"])
@require_auth
def push_repository():
    """Push local changes to GitHub repository"""
    try:
        data = request.get_json() or {}
        local_path = data.get("local_path")
        commit_message = data.get("commit_message", "Update from A.R.C.H.I.E. Platform")

        if not local_path or not os.path.exists(local_path):
            return jsonify({"error": "Repository not found locally"}), 404

        # Get GitHub credentials
        username = get_setting("github_username") or "A.R.C.H.I.E. Platform"
        email = get_setting("github_email") or "archie@platform.local"

        # Configure git user
        subprocess.run(["git", "-C", local_path, "config", "user.name", username], check=True)
        subprocess.run(["git", "-C", local_path, "config", "user.email", email], check=True)

        # Add all changes
        subprocess.run(["git", "-C", local_path, "add", "."], check=True)

        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "-C", local_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )

        if not status_result.stdout.strip():
            return jsonify({"success": True, "message": "No changes to commit"})

        # Commit changes
        subprocess.run(
            ["git", "-C", local_path, "commit", "-m", commit_message],
            check=True,
            capture_output=True,
        )

        # Push to origin
        push_result = subprocess.run(
            ["git", "-C", local_path, "push"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if push_result.returncode == 0:
            # Update repository status
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE github_repositories
                SET updated_at = NOW(), last_push = NOW()
                WHERE local_path = %s
            """,
                (local_path,),
            )

            conn.commit()
            cursor.close()
            conn.close()

            return jsonify({"success": True, "message": "✓ Changes pushed to GitHub successfully"})
        else:
            return jsonify({"error": f"Git push failed: {push_result.stderr}"}), 500

    except subprocess.CalledProcessError as e:
        return (
            jsonify({"error": f"Git operation failed: {e.stderr.decode() if e.stderr else str(e)}"}),
            500,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@github_bp.route("/sync-repo", methods=["POST"])
@require_auth
def sync_repository():
    """Sync repository (pull then push)"""
    try:
        data = request.get_json() or {}
        local_path = data.get("local_path")

        # First pull
        pull_response = pull_repository()
        if pull_response[1] != 200:
            return pull_response

        # Then push
        push_response = push_repository()
        return push_response

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# CONTENT INDEXING
# ============================================================================


@github_bp.route("/index-repo", methods=["POST"])
@require_auth
def index_repository_content():
    """Index repository content into A.R.C.H.I.E.'s knowledge database"""
    try:
        data = request.get_json() or {}
        repo_type = data.get("type")
        local_path = data.get("local_path")

        if not local_path or not os.path.exists(local_path):
            return jsonify({"error": "Repository not found locally"}), 404

        conn = get_db_connection()
        cursor = conn.cursor()

        indexed_count = 0
        total_files = 0

        # Define file patterns to index based on repo type
        if repo_type == "ai-agents":
            patterns = ["*.md", "*.py", "*.json", "*.txt"]
        elif repo_type == "prompts":
            patterns = ["*.md", "*.txt", "*.json"]
        elif repo_type == "n8n":
            patterns = ["*.json"]
        else:
            patterns = ["*.md", "*.txt"]

        # Index files
        for pattern in patterns:
            for file_path in Path(local_path).rglob(pattern):
                if file_path.is_file():
                    total_files += 1
                    try:
                        # Read file content
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()

                        # Skip if too large (> 1MB)
                        if len(content) > 1048576:
                            continue

                        # Extract metadata
                        rel_path = str(file_path.relative_to(local_path))
                        file_name = file_path.name
                        file_ext = file_path.suffix

                        # Store in knowledge base
                        cursor.execute(
                            """
                            INSERT INTO knowledge_base
                            (repo_type, file_path, file_name, file_extension, content, indexed_at)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (repo_type, file_path) DO UPDATE
                            SET content = EXCLUDED.content, indexed_at = NOW()
                        """,
                            (repo_type, rel_path, file_name, file_ext, content),
                        )

                        indexed_count += 1

                    except Exception as e:
                        # Skip files that can't be read
                        continue

        # Update repository status
        cursor.execute(
            """
            UPDATE github_repositories
            SET indexed = true, indexed_at = NOW(), indexed_files = %s
            WHERE local_path = %s
        """,
            (indexed_count, local_path),
        )

        conn.commit()
        cursor.close()

        return jsonify(
            {
                "success": True,
                "message": f"✓ Indexed {indexed_count} files into knowledge base",
                "indexed_count": indexed_count,
                "total_files": total_files,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# DOCUMENTATION SYNC
# ============================================================================


@github_bp.route("/sync-docs", methods=["POST"])
@require_auth
def sync_documentation():
    """Sync /docs/ directory and TODO_LIST.md to GitHub"""
    try:
        docs_path = "/mnt/archie_brain/docs"

        # Get GitHub credentials
        username = get_setting("github_username") or "A.R.C.H.I.E. Platform"
        email = get_setting("github_email") or "archie@platform.local"

        # Configure git
        subprocess.run(["git", "-C", docs_path, "config", "user.name", username], check=True)
        subprocess.run(["git", "-C", docs_path, "config", "user.email", email], check=True)

        # Add all changes
        subprocess.run(["git", "-C", docs_path, "add", "."], check=True)

        # Check for changes
        status_result = subprocess.run(
            ["git", "-C", docs_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
        )

        if not status_result.stdout.strip():
            return jsonify({"success": True, "message": "Documentation is up to date"})

        # Commit with timestamp
        commit_msg = f'Update documentation - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        subprocess.run(["git", "-C", docs_path, "commit", "-m", commit_msg], check=True)

        # Push (if docs is a git repo)
        try:
            push_result = subprocess.run(
                ["git", "-C", docs_path, "push"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if push_result.returncode == 0:
                return jsonify({"success": True, "message": "✓ Documentation synced to GitHub"})
            else:
                # Commit succeeded but push failed (maybe not a git repo)
                return jsonify(
                    {
                        "success": True,
                        "message": "✓ Documentation committed locally (push failed - may need repo setup)",
                    }
                )
        except:
            return jsonify(
                {
                    "success": True,
                    "message": "✓ Documentation committed locally (not a git repository)",
                }
            )

    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Git operation failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@github_bp.route("/view-doc-changes", methods=["GET"])
@require_auth
def view_doc_changes():
    """View pending documentation changes"""
    try:
        docs_path = "/mnt/archie_brain/docs"

        # Get git status
        result = subprocess.run(
            ["git", "-C", docs_path, "status", "--short"],
            capture_output=True,
            text=True,
        )

        changes = result.stdout.strip().split("\n") if result.stdout.strip() else []

        return jsonify({"changes": changes, "count": len([c for c in changes if c])})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# REPOSITORY STATUS
# ============================================================================


@github_bp.route("/status", methods=["GET"])
@require_auth
def get_repository_status():
    """Get status of all repositories"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            """
            SELECT
                repo_name,
                repo_type,
                local_path,
                status,
                indexed,
                indexed_files,
                cloned_at,
                updated_at,
                last_pull,
                last_push
            FROM github_repositories
            ORDER BY repo_type, repo_name
        """
        )

        repos = cursor.fetchall()

        # Get stats
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_repos,
                COUNT(*) FILTER (WHERE status = 'cloned') as cloned_repos,
                COUNT(*) FILTER (WHERE indexed = true) as indexed_repos,
                MAX(updated_at) as last_sync
            FROM github_repositories
        """
        )

        stats = cursor.fetchone()

        cursor.close()

        return jsonify({"repositories": repos, "stats": stats})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_setting(key, default=None):
    """Get a setting from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
        row = cursor.fetchone()

        cursor.close()

        if row:
            return json.loads(row[0])
        return default

    except:
        return default
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
