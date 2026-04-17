"""
GitHub Deployment Module for A.R.C.H.I.E. Platform
Manages website deployment from GitHub to Nginx
"""

import os
from database import _get_db_password
import subprocess
import shutil
from datetime import datetime
from github import Github
import psycopg2
from psycopg2.extras import RealDictCursor

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "KytranKatarn/kytranempowerment-site"
DEPLOY_PATH = "/var/www/kytranempowerment"
NGINX_SITES_PATH = "/etc/nginx/sites-available"


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# GITHUB OPERATIONS
# ============================================================================


def get_github_client():
    """Get authenticated GitHub client"""
    return Github(GITHUB_TOKEN)


def get_repository():
    """Get GitHub repository"""
    g = get_github_client()
    return g.get_repo(GITHUB_REPO)


def get_latest_commit():
    """Get latest commit from main branch"""
    try:
        repo = get_repository()
        commits = repo.get_commits(sha="main")
        latest = commits[0]

        return {
            "sha": latest.sha,
            "message": latest.commit.message,
            "author": latest.commit.author.name,
            "date": latest.commit.author.date.isoformat(),
            "url": latest.html_url,
        }
    except Exception as e:
        print(f"Get latest commit error: {e}")
        return None


def get_commit_history(limit=10):
    """Get recent commit history"""
    try:
        repo = get_repository()
        commits = repo.get_commits(sha="main")

        history = []
        for commit in list(commits)[:limit]:
            history.append(
                {
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": commit.commit.author.name,
                    "date": commit.commit.author.date.isoformat(),
                    "url": commit.html_url,
                }
            )

        return history
    except Exception as e:
        print(f"Get commit history error: {e}")
        return []


def get_repo_info():
    """Get repository information"""
    try:
        repo = get_repository()

        return {
            "name": repo.name,
            "description": repo.description,
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "watchers": repo.watchers_count,
            "open_issues": repo.open_issues_count,
            "default_branch": repo.default_branch,
            "created_at": repo.created_at.isoformat(),
            "updated_at": repo.updated_at.isoformat(),
            "url": repo.html_url,
        }
    except Exception as e:
        print(f"Get repo info error: {e}")
        return None


# ============================================================================
# DEPLOYMENT OPERATIONS
# ============================================================================


def clone_repository():
    """Clone repository to deploy path"""
    try:
        # Remove existing if present
        if os.path.exists(DEPLOY_PATH):
            shutil.rmtree(DEPLOY_PATH)

        # Clone repo
        repo_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

        result = subprocess.run(["git", "clone", repo_url, DEPLOY_PATH], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Git clone failed: {result.stderr}")

        return True
    except Exception as e:
        print(f"Clone repository error: {e}")
        return False


def pull_latest_changes():
    """Pull latest changes from GitHub"""
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=DEPLOY_PATH,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise Exception(f"Git pull failed: {result.stderr}")

        return True
    except Exception as e:
        print(f"Pull latest changes error: {e}")
        return False


def deploy_website(user_id):
    """Deploy website from GitHub to Nginx"""
    try:
        # Clone or pull latest
        if not os.path.exists(DEPLOY_PATH):
            if not clone_repository():
                raise Exception("Failed to clone repository")
        else:
            if not pull_latest_changes():
                raise Exception("Failed to pull latest changes")

        # Get commit info
        commit_info = get_latest_commit()

        # Set proper permissions
        subprocess.run(["chown", "-R", "www-data:www-data", DEPLOY_PATH])

        # Log deployment
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO audit_log (user_id, action, details, ip_address)
            VALUES (%s, 'deploy_website', %s, '127.0.0.1')
        """,
            (
                user_id,
                f"Deployed commit: {commit_info['sha'][:7]} - {commit_info['message']}",
            ),
        )

        # Create notification
        cur.execute(
            """
            INSERT INTO system_notifications (type, title, message, source, visibility)
            VALUES ('success', 'Website Deployed', %s, 'github_deploy', 'admin')
        """,
            (f"Successfully deployed {commit_info['sha'][:7]}: {commit_info['message']}",),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True, "commit": commit_info, "deploy_path": DEPLOY_PATH}
    except Exception as e:
        print(f"Deploy website error: {e}")

        # Log error
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO system_notifications (type, title, message, source, visibility)
                VALUES ('error', 'Deployment Failed', %s, 'github_deploy', 'admin')
            """,
                (str(e),),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

        return {"success": False, "error": str(e)}


# ============================================================================
# NGINX CONFIGURATION
# ============================================================================


def configure_nginx_site(domain, port=80, ssl=False):
    """Configure Nginx site"""
    nginx_config = f"""
server {{
    listen {port};
    {'listen 443 ssl http2;' if ssl else ''}
    server_name {domain};

    root {DEPLOY_PATH};
    index index.html index.htm;

    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Caching
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    # Logs
    access_log /var/log/nginx/{domain}_access.log;
    error_log /var/log/nginx/{domain}_error.log;
}}
"""

    try:
        config_path = f"{NGINX_SITES_PATH}/{domain}"

        with open(config_path, "w") as f:
            f.write(nginx_config)

        # Enable site
        enabled_path = f"/etc/nginx/sites-enabled/{domain}"
        if not os.path.exists(enabled_path):
            os.symlink(config_path, enabled_path)

        # Test configuration
        result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Nginx config test failed: {result.stderr}")

        # Reload Nginx
        subprocess.run(["systemctl", "reload", "nginx"])

        return True
    except Exception as e:
        print(f"Configure Nginx error: {e}")
        return False


# ============================================================================
# DOMAIN MANAGEMENT
# ============================================================================


def setup_domain(domain, deploy_type="main_site"):
    """Setup domain with Nginx"""
    try:
        domains_config = {
            "main_site": {
                "domain": "www.kytranempowerment.com",
                "path": DEPLOY_PATH,
                "port": 80,
            },
            "archie": {
                "domain": "platform.kytranempowerment.com",
                "path": "/mnt/archie_brain/platform_v2",
                "port": 3000,
                "proxy": True,
            },
            "store": {
                "domain": "store.kytranempowerment.com",
                "path": "/var/www/store",
                "port": 80,
            },
        }

        config = domains_config.get(deploy_type)

        if not config:
            raise ValueError(f"Unknown deploy type: {deploy_type}")

        if config.get("proxy"):
            # Proxy configuration
            nginx_config = f"""
server {{
    listen 80;
    server_name {config['domain']};

    location / {{
        proxy_pass http://localhost:{config['port']};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
        else:
            # Static site configuration
            nginx_config = f"""
server {{
    listen {config['port']};
    server_name {config['domain']};

    root {config['path']};
    index index.html;

    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""

        config_path = f"{NGINX_SITES_PATH}/{config['domain']}"

        with open(config_path, "w") as f:
            f.write(nginx_config)

        # Enable site
        enabled_path = f"/etc/nginx/sites-enabled/{config['domain']}"
        if not os.path.exists(enabled_path):
            os.symlink(config_path, enabled_path)

        # Test and reload
        subprocess.run(["nginx", "-t"])
        subprocess.run(["systemctl", "reload", "nginx"])

        return True
    except Exception as e:
        print(f"Setup domain error: {e}")
        return False


# ============================================================================
# DEPLOYMENT HISTORY
# ============================================================================


def get_deployment_history(limit=10):
    """Get deployment history from audit log"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT * FROM audit_log
        WHERE action = 'deploy_website'
        ORDER BY timestamp DESC
        LIMIT %s
    """,
        (limit,),
    )

    deployments = cur.fetchall()
    cur.close()
    conn.close()

    return deployments


# ============================================================================
# FILE OPERATIONS
# ============================================================================


def get_file_content(file_path):
    """Get content of a file in the repository"""
    try:
        full_path = os.path.join(DEPLOY_PATH, file_path)

        if not os.path.exists(full_path):
            return None

        with open(full_path, "r") as f:
            return f.read()
    except Exception as e:
        print(f"Get file content error: {e}")
        return None


def update_file_content(file_path, content, user_id):
    """Update file content"""
    try:
        full_path = os.path.join(DEPLOY_PATH, file_path)

        with open(full_path, "w") as f:
            f.write(content)

        # Log change
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_log (user_id, action, details)
            VALUES (%s, 'edit_website_file', %s)
        """,
            (user_id, f"Edited file: {file_path}"),
        )
        conn.commit()
        cur.close()
        conn.close()

        return True
    except Exception as e:
        print(f"Update file content error: {e}")
        return False


def list_files(directory=""):
    """List files in directory"""
    try:
        full_path = os.path.join(DEPLOY_PATH, directory)

        if not os.path.exists(full_path):
            return []

        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            files.append(
                {
                    "name": item,
                    "is_directory": os.path.isdir(item_path),
                    "size": (os.path.getsize(item_path) if os.path.isfile(item_path) else 0),
                    "modified": datetime.fromtimestamp(os.path.getmtime(item_path)).isoformat(),
                }
            )

        return files
    except Exception as e:
        print(f"List files error: {e}")
        return []
