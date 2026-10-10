"""GitHub Repository Routes -- Indexing, CRUD, file browsing, search

Split from github_routes.py. Handles:
- Selective and full-repo indexing (Tree API)
- Repository CRUD (list, update, delete)
- Indexed file listing and semantic search
- Repository explorer (tree, file, readme)
- Repos summary API
"""

import json
import logging
import hmac
import os
import threading
import traceback

import requests
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .github_routes import (
    _get_db,
    _get_github_headers,
    _check_rate_limit,
    _notify_ingestion_complete,
    _reindex_repo_via_tree,
    run_reindex_background,
    MAX_FILE_SIZE,
    MAX_CONTENT_STORE,
)

logger = logging.getLogger(__name__)


def register_github_repo_routes(bp, admin_required):
    """Register repository management routes on the consciousness blueprint."""

    # Helper: accept either Flask-Login session (admin) or Bearer API key
    def login_or_api_key(f):
        """Allow access via Flask-Login session OR Bearer API key."""
        from functools import wraps

        @wraps(f)
        def decorated(*args, **kwargs):
            api_key = request.headers.get("Authorization", "")
            if api_key.startswith("Bearer "):
                presented = api_key[7:]
                # Accept ARCHIE_API_KEY (CLI/api-key callers) OR INTERNAL_API_KEY
                # (the A.R.C.H.I.E. Engine's bearer for skill sync etc. — #4265).
                # Both values are read from the ENVIRONMENT via os.getenv (never
                # hard-coded — the only literal is a dev fallback default); empty/
                # unset values are discarded so a missing var can't auth.
                api_key_value = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
                if api_key_value and hmac.compare_digest(presented.encode(), api_key_value.encode()):
                    return f(*args, **kwargs)
                # #6657: the engine's key is now a SCOPED internal key ('engine').
                from services.internal_auth import caller_has_scope

                if caller_has_scope("engine"):
                    return f(*args, **kwargs)
                return jsonify({"error": "Invalid API key"}), 401
            # Fall back to Flask-Login session
            if not current_user.is_authenticated:
                return jsonify({"error": "Authentication required"}), 401
            if not getattr(current_user, "is_admin", False):
                return jsonify({"error": "Admin access required"}), 403
            return f(*args, **kwargs)

        return decorated

    # ==================================================================
    # INDEXING
    # ==================================================================

    @bp.route("/github/index-selective", methods=["POST"])
    @login_or_api_key
    def github_index_selective():
        """
        Index specific files/folders from a GitHub repo with semantic embeddings
        This allows ARCHIE to learn from GitHub repositories with higher priority
        """
        data = request.get_json(silent=True) or {}
        repo_url = data.get("repo_url", "").strip()
        paths = data.get("paths", [])
        priority = data.get("priority", "high")  # high, medium, low
        req_max_files = data.get("max_files")  # per-repo cap override
        if req_max_files is not None:
            req_max_files = int(req_max_files)

        if not repo_url:
            return jsonify({"success": False, "error": "Repository URL required"}), 400

        # Parse GitHub URL
        # Formats: https://github.com/user/repo or github.com/user/repo
        try:
            parts = repo_url.replace("https://", "").replace("http://", "").replace("github.com/", "").split("/")
            owner = parts[0]
            repo = parts[1].replace(".git", "")
        except Exception:
            return jsonify({"success": False, "error": "Invalid GitHub URL format"}), 400

        # Priority mapping
        priority_scores = {"high": 0.95, "medium": 0.85, "low": 0.75}
        importance = priority_scores.get(priority, 0.85)

        headers, _has_token = _get_github_headers()

        # If no paths specified, use the recursive tree API for full repo index
        if not paths:
            conn = None
            cur = None
            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                # Look up repo_type and max_files from github_repositories
                conn = _get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT repo_type, max_files FROM github_repositories WHERE repo_name LIKE %s LIMIT 1",
                    (f"%{owner}/{repo}%",),
                )
                row = cur.fetchone()
                repo_type = row["repo_type"] if row else repo.lower()
                # Use request max_files > DB max_files > global default
                effective_max = (
                    req_max_files
                    if req_max_files is not None
                    else (row["max_files"] if row and row.get("max_files") else None)
                )
                # Persist the requested cap if provided and repo exists
                if req_max_files is not None and row:
                    cur.execute(
                        "UPDATE github_repositories SET max_files = %s WHERE repo_name LIKE %s",
                        (req_max_files, f"%{owner}/{repo}%"),
                    )
                    conn.commit()
                # -- Create Bridge Job ---
                dispatcher = get_dispatcher()
                job_id = dispatcher.create_job(
                    job_type="github_index",
                    module_source="consciousness",
                    description=f"Index repo {owner}/{repo} (max {effective_max or 'unlimited'} files)",
                    total_steps=1,
                    capability="code_analysis",
                    metadata={"repo": f"{owner}/{repo}", "priority": priority, "max_files": effective_max},
                )

                if not job_id:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "An index job for this repo is already running — check Starbase Command for progress",
                                "duplicate": True,
                            }
                        ),
                        409,
                    )

                def _bg_index(o, r, rt, imp, mx, jid):
                    from tools.department_hq.services.department_dispatcher import get_dispatcher as _gd

                    d = _gd()
                    try:
                        indexed_count, errors, skipped, total_found, was_capped, used_cap = _reindex_repo_via_tree(
                            o, r, rt, imp, max_files=mx
                        )
                        d.update_job_progress(
                            jid,
                            1,
                            0,
                            {"indexed": indexed_count, "skipped": skipped, "total_found": total_found},
                        )
                        d.complete_job(jid)
                        logger.info(f"[GitHub] Index job #{jid} done: {indexed_count} files from {o}/{r}")
                    except Exception as e:
                        logger.error(f"[GitHub] Index job #{jid} failed: {e}")
                        d.update_job_progress(jid, 0, 1, {"error": str(e)})
                        d.complete_job(jid)

                thread = threading.Thread(
                    target=_bg_index,
                    args=(owner, repo, repo_type, importance, effective_max, job_id),
                    daemon=True,
                )
                thread.start()

                return jsonify(
                    {
                        "success": True,
                        "repo": f"{owner}/{repo}",
                        "priority": priority,
                        "job_id": job_id,
                        "message": f"Index job #{job_id} started — {owner}/{repo} queued",
                    }
                )
            except Exception as e:
                traceback.print_exc()
                return jsonify({"success": False, "error": str(e)}), 500
            finally:
                if cur:
                    cur.close()
                if conn:
                    conn.close()

        # Paths specified — use Contents API for targeted indexing
        indexed_count = 0
        errors = []

        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            for path in paths:
                path = path.strip().strip("/")

                # Get contents from GitHub API
                api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
                response = requests.get(api_url, headers=headers, timeout=30)

                is_limited, limit_msg = _check_rate_limit(response)
                if is_limited:
                    errors.append(limit_msg)
                    break  # Stop all indexing on rate limit

                if response.status_code != 200:
                    errors.append(f"Failed to fetch {path}: HTTP {response.status_code}")
                    continue

                contents = response.json()

                # Handle single file vs directory
                if isinstance(contents, dict):
                    contents = [contents]

                for item in contents:
                    if item.get("type") == "file":
                        file_url = item.get("download_url")
                        if not file_url:
                            continue

                        try:
                            try:
                                file_response = requests.get(file_url, timeout=30)
                            except requests.exceptions.Timeout:
                                errors.append(f"Timeout downloading {item.get('name', file_url)} (30s limit)")
                                continue
                            if file_response.status_code != 200:
                                continue

                            file_content = file_response.text
                            file_path_val = item.get("path", "")
                            file_name = item.get("name", "")

                            if len(file_content) > MAX_FILE_SIZE:
                                continue

                            ext = os.path.splitext(file_name)[1].lower()

                            cur.execute(
                                """
                                INSERT INTO knowledge_base (
                                    knowledge_type, title, content, category, file_path,
                                    importance_score, source_type, file_name, file_extension,
                                    memory_metadata, tags, repo_type, created_at
                                ) VALUES (
                                    'github_file', %s, %s, 'github', %s,
                                    %s, 'github_selective', %s, %s,
                                    %s, %s, %s, NOW()
                                )
                                ON CONFLICT (file_path) WHERE source_type = 'github_selective'
                                DO UPDATE SET
                                    content = EXCLUDED.content,
                                    importance_score = EXCLUDED.importance_score,
                                    updated_at = NOW()
                                RETURNING id
                            """,
                                (
                                    file_name,
                                    file_content[:MAX_CONTENT_STORE],
                                    f"{owner}/{repo}/{file_path_val}",
                                    importance,
                                    file_name,
                                    ext,
                                    json.dumps(
                                        {
                                            "repo": f"{owner}/{repo}",
                                            "priority": priority,
                                            "indexed_by": current_user.username,
                                            "sha": item.get("sha"),
                                            "size": item.get("size"),
                                        }
                                    ),
                                    ["github", "selective", owner, repo, priority],
                                    repo.lower(),
                                ),
                            )

                            result = cur.fetchone()
                            if result:
                                indexed_count += 1

                        except Exception as file_err:
                            errors.append(f"Error processing {item.get('name')}: {str(file_err)}")

                    elif item.get("type") == "dir":
                        # Recurse into directories
                        paths.append(item.get("path", ""))

            conn.commit()

            # Telegram notification — tell Kytran what ARCHIE just learned
            try:
                _notify_ingestion_complete(
                    repo_count=1,
                    file_count=indexed_count,
                    repo_names=[f"{owner}/{repo}"],
                )
            except Exception as tg_err:
                logger.debug(f"[GitHub] Telegram notification failed: {tg_err}")

            return jsonify(
                {
                    "success": True,
                    "indexed_count": indexed_count,
                    "repo": f"{owner}/{repo}",
                    "priority": priority,
                    "errors": errors if errors else None,
                }
            )

        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # REINDEX
    # ==================================================================

    @bp.route("/github/reindex-all", methods=["POST"])
    @login_required
    @admin_required
    def github_reindex_all():
        """Re-index all tracked repositories using the Tree API.

        Creates a bridge_job and returns the job_id immediately.
        Work runs in a background thread with progress tracked in Starbase Command.
        Skips repos indexed within the last 7 days unless force=true.
        """
        conn = None
        cur = None
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            data = request.get_json(silent=True) or {}
            force = data.get("force", False)

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # -- Duplicate job prevention --
            cur.execute(
                "SELECT id FROM bridge_jobs WHERE job_type = 'github_reindex' AND status = 'running' AND created_at > NOW() - INTERVAL '1 hour'"
            )
            if cur.fetchone():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Reindex already in progress",
                            "duplicate": True,
                        }
                    ),
                    409,
                )

            if force:
                cur.execute("SELECT id, repo_name, repo_type, max_files FROM github_repositories ORDER BY id")
            else:
                cur.execute(
                    """SELECT id, repo_name, repo_type, max_files
                       FROM github_repositories
                       WHERE indexed_at IS NULL
                          OR indexed_at < NOW() - INTERVAL '7 days'
                       ORDER BY indexed_at ASC NULLS FIRST"""
                )
            repos = cur.fetchall()

            if not repos:
                # All repos are fresh — tell the user
                cur.execute(
                    """SELECT count(*) as total,
                              min(indexed_at) as oldest,
                              max(indexed_at) as newest
                       FROM github_repositories"""
                )
                info = cur.fetchone()
                oldest = info["oldest"]
                days_ago = 0
                if oldest:
                    from datetime import datetime, timezone

                    days_ago = (datetime.now(timezone.utc) - oldest).days
                return jsonify(
                    {
                        "success": True,
                        "total_indexed": 0,
                        "total_repos": info["total"],
                        "skipped": True,
                        "message": f"All {info['total']} repos indexed within 7 days (oldest: {days_ago}d ago). Use force=true to override.",
                    }
                )

            # -- Create Bridge Job (blocks duplicates) ---
            dispatcher = get_dispatcher()
            job_id = dispatcher.create_job(
                job_type="github_reindex_all",
                module_source="consciousness",
                description=f"Re-index all {len(repos)} GitHub repositories",
                total_steps=len(repos),
                capability="code_analysis",
                metadata={"repo_count": len(repos)},
            )

            if not job_id:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "A reindex-all job is already running — check Starbase Command for progress",
                            "duplicate": True,
                        }
                    ),
                    409,
                )

            thread = threading.Thread(target=run_reindex_background, args=(list(repos), job_id), daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "total_repos": len(repos),
                    "message": f"Reindex job #{job_id} started — {len(repos)} repositories queued",
                }
            )

        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/reindex/<int:repo_id>", methods=["POST"])
    @login_required
    @admin_required
    def github_reindex_single(repo_id):
        """Re-index a single tracked repository using the Tree API.

        Creates a bridge_job so the work is visible in Starbase Command.
        """
        conn = None
        cur = None
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, repo_name, repo_type, max_files FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
            repo_row = cur.fetchone()
            if not repo_row:
                return jsonify({"success": False, "error": "Repository not found"}), 404

            repo_name = repo_row["repo_name"]
            repo_type = repo_row["repo_type"]
            repo_max = repo_row.get("max_files")
            parts = repo_name.split("/")
            owner = parts[0]
            repo = parts[1]

            # -- Create Bridge Job ---
            dispatcher = get_dispatcher()
            job_id = dispatcher.create_job(
                job_type="github_reindex",
                module_source="consciousness",
                description=f"Re-index {repo_name}",
                total_steps=1,
                capability="code_analysis",
                metadata={"repo": repo_name, "repo_id": repo_id},
            )

            if not job_id:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"A reindex job for {repo_name} is already running",
                            "duplicate": True,
                        }
                    ),
                    409,
                )

            def _bg_reindex_single(o, r, rt, mx, jid):
                from tools.department_hq.services.department_dispatcher import get_dispatcher as _gd

                d = _gd()
                try:
                    indexed, errs, skipped, total_found, was_capped, used_cap = _reindex_repo_via_tree(
                        o, r, rt, max_files=mx
                    )
                    d.update_job_progress(
                        jid,
                        1,
                        0,
                        {"indexed": indexed, "skipped": skipped, "total_found": total_found},
                    )
                    d.complete_job(jid)
                    logger.info(f"[GitHub] Reindex job #{jid} done: {indexed} files from {o}/{r}")
                except Exception as e:
                    logger.error(f"[GitHub] Reindex job #{jid} failed: {e}")
                    d.update_job_progress(jid, 0, 1, {"error": str(e)})
                    d.complete_job(jid)

            thread = threading.Thread(
                target=_bg_reindex_single,
                args=(owner, repo, repo_type, repo_max, job_id),
                daemon=True,
            )
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "repo": repo_name,
                    "job_id": job_id,
                    "message": f"Reindex job #{job_id} started — {repo_name} queued",
                }
            )

        except Exception as e:
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # REPOSITORY CRUD
    # ==================================================================

    @bp.route("/github/repositories", methods=["GET"])
    @login_required
    @admin_required
    def github_repositories():
        """List tracked GitHub repositories with their status"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT gr.id, gr.repo_name, gr.repo_type, gr.status, gr.indexed,
                       gr.indexed_files, gr.cloned_at, gr.updated_at, gr.indexed_at,
                       gr.max_files,
                       (SELECT COUNT(*) FROM knowledge_base kb
                        WHERE kb.knowledge_type = 'github_file'
                        AND kb.repo_type = gr.repo_type) as actual_file_count
                FROM github_repositories gr
                ORDER BY gr.updated_at DESC
            """
            )
            repos = cur.fetchall()
            return jsonify(
                {
                    "success": True,
                    "repositories": [dict(r) for r in repos],
                    "count": len(repos),
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/repositories/<int:repo_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def github_repository_update(repo_id):
        """Update a tracked repository's settings (e.g. max_files cap)."""
        conn = None
        cur = None
        try:
            data = request.get_json(silent=True) or {}
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT id, repo_name FROM github_repositories WHERE id = %s", (repo_id,))
            repo = cur.fetchone()
            if not repo:
                return jsonify({"success": False, "error": "Repository not found"}), 404

            # Update max_files (None resets to global default)
            if "max_files" in data:
                new_max = data["max_files"]
                if new_max is not None:
                    new_max = int(new_max)
                cur.execute(
                    "UPDATE github_repositories SET max_files = %s, updated_at = NOW() WHERE id = %s",
                    (new_max, repo_id),
                )
                conn.commit()
            return jsonify({"success": True, "repo_id": repo_id, "max_files": data.get("max_files")})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/repositories/<int:repo_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def github_repository_delete(repo_id):
        """Delete a tracked repository and its indexed files. Use ?preview=true for impact summary."""
        preview = request.args.get("preview", "").lower() == "true"
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get repo info
            cur.execute(
                "SELECT id, repo_name, repo_type FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
            repo = cur.fetchone()
            if not repo:
                return jsonify({"success": False, "error": "Repository not found"}), 404

            repo = dict(repo)
            repo_type = repo["repo_type"]

            # Get impact: count files that would be deleted
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN is_code THEN 1 ELSE 0 END) as code_files,
                       SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END) as doc_files
                FROM knowledge_base
                WHERE knowledge_type = 'github_file' AND repo_type = %s
                """,
                (repo_type,),
            )
            impact = dict(cur.fetchone())

            if preview:
                return jsonify({"success": True, "preview": True, "repo": repo, "impact": impact})

            # Actually delete
            cur.execute(
                "DELETE FROM knowledge_base WHERE knowledge_type = 'github_file' AND repo_type = %s",
                (repo_type,),
            )
            deleted_files = cur.rowcount
            cur.execute("DELETE FROM github_repositories WHERE id = %s", (repo_id,))
            conn.commit()
            return jsonify(
                {
                    "success": True,
                    "deleted_files": deleted_files,
                    "repo_name": repo["repo_name"],
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # INDEXED FILE LISTING
    # ==================================================================

    @bp.route("/github/indexed", methods=["GET"])
    @login_required
    @admin_required
    def github_indexed_list():
        """List all selectively indexed GitHub content. Optional ?file_type=code|docs to filter."""
        file_type = request.args.get("file_type", "").lower()
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            base_where = "(source_type = 'github_selective' OR knowledge_type = 'github_file')"
            if file_type == "code":
                base_where += " AND is_code = true"
            elif file_type == "docs":
                base_where += " AND is_documentation = true"
            elif file_type == "config":
                base_where += " AND is_configuration = true"

            cur.execute(
                f"""
                SELECT id, title, file_path, importance_score,
                       -- #5864: DERIVE it. The stored `has_embedding` flag is a
                       -- denormalised mirror nobody maintains — 9,082 rows held a real
                       -- embedding while the flag read false (measured 2026-08-20), so
                       -- this rendered "—" for files that ARE embedded. Matches what
                       -- knowledge_routes.py:247/:874 and routes.py:1338 already do.
                       (embedding IS NOT NULL) AS has_embedding,
                       memory_metadata, created_at, updated_at, knowledge_type,
                       is_code, is_documentation, repo_type
                FROM knowledge_base
                WHERE {base_where}
                ORDER BY created_at DESC
                LIMIT 200
            """
            )
            items = cur.fetchall()

            # Get stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as with_embeddings,
                    (SELECT COUNT(*) FROM github_repositories) as repos,
                    SUM(CASE WHEN is_code THEN 1 ELSE 0 END) as code_files,
                    SUM(CASE WHEN is_documentation THEN 1 ELSE 0 END) as docs,
                    SUM(CASE WHEN is_configuration THEN 1 ELSE 0 END) as config_files
                FROM knowledge_base
                WHERE source_type = 'github_selective' OR knowledge_type = 'github_file'
            """
            )
            stats = cur.fetchone()
            items_list = [dict(i) for i in items]
            return jsonify(
                {
                    "success": True,
                    "items": items_list,
                    "files": items_list,  # Alias for frontend compatibility
                    "stats": dict(stats) if stats else {},
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # SEMANTIC SEARCH
    # ==================================================================

    @bp.route("/github/search-semantic", methods=["POST"])
    @login_required
    @admin_required
    def github_search_semantic():
        """Semantic search across indexed GitHub files"""
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()
        limit = data.get("limit", 10)

        if not query:
            return jsonify({"success": False, "error": "Query required"}), 400

        try:
            from .memory_service import semantic_search

            results = semantic_search(query, source_types=["knowledge_base"], limit=limit, min_similarity=0.5)

            # Filter to github files only
            github_results = [
                r
                for r in results
                if r.get("knowledge_type") == "github_file" or r.get("source_type") == "github_selective"
            ]

            return jsonify({"success": True, "results": github_results, "count": len(github_results)})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ==================================================================
    # REPOSITORY EXPLORER API
    # ==================================================================

    LANG_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".sql": "sql",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".toml": "toml",
        ".xml": "xml",
        ".dockerfile": "dockerfile",
    }

    @bp.route("/github/repo/<int:repo_id>/tree")
    @login_required
    @admin_required
    def github_repo_tree(repo_id):
        """Browse local clone directory tree."""
        rel_path = request.args.get("path", "")
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT repo_name, local_path FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
            repo = cur.fetchone()
            if not repo or not repo["local_path"]:
                return jsonify({"success": False, "error": "Repository not cloned"}), 404

            base = repo["local_path"]
            # Security: prevent path traversal
            full = os.path.normpath(os.path.join(base, rel_path))
            if not full.startswith(os.path.normpath(base)):
                return jsonify({"success": False, "error": "Invalid path"}), 400
            if not os.path.isdir(full):
                return jsonify({"success": False, "error": "Directory not found"}), 404

            entries = []
            for name in sorted(os.listdir(full)):
                if name == ".git":
                    continue
                child = os.path.join(full, name)
                is_dir = os.path.isdir(child)
                entry = {"name": name, "type": "dir" if is_dir else "file"}
                if not is_dir:
                    try:
                        entry["size"] = os.path.getsize(child)
                    except OSError:
                        entry["size"] = 0
                entries.append(entry)

            # Sort: dirs first, then files
            entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))

            return jsonify(
                {
                    "success": True,
                    "repo_name": repo["repo_name"],
                    "path": rel_path,
                    "entries": entries,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/repo/<int:repo_id>/file")
    @login_required
    @admin_required
    def github_repo_file(repo_id):
        """Read a file from local clone."""
        rel_path = request.args.get("path", "")
        if not rel_path:
            return jsonify({"success": False, "error": "Path required"}), 400

        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT repo_name, local_path FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
            repo = cur.fetchone()
            if not repo or not repo["local_path"]:
                return jsonify({"success": False, "error": "Repository not cloned"}), 404

            base = repo["local_path"]
            full = os.path.normpath(os.path.join(base, rel_path))
            if not full.startswith(os.path.normpath(base)):
                return jsonify({"success": False, "error": "Invalid path"}), 400
            if not os.path.isfile(full):
                return jsonify({"success": False, "error": "File not found"}), 404

            size = os.path.getsize(full)
            max_size = 1024 * 1024  # 1MB
            truncated = size > max_size

            ext = os.path.splitext(rel_path)[1].lower()
            language = LANG_MAP.get(ext, "")
            # Detect binary
            binary_exts = {
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".ico",
                ".woff",
                ".woff2",
                ".ttf",
                ".eot",
                ".zip",
                ".tar",
                ".gz",
                ".exe",
                ".bin",
                ".pdf",
                ".pyc",
                ".so",
                ".dll",
                ".o",
            }
            if ext in binary_exts:
                return jsonify(
                    {
                        "success": True,
                        "repo_name": repo["repo_name"],
                        "path": rel_path,
                        "filename": os.path.basename(rel_path),
                        "content": None,
                        "binary": True,
                        "language": "",
                        "size": size,
                        "truncated": False,
                    }
                )

            with open(full, "r", errors="replace") as f:
                content = f.read(max_size)

            return jsonify(
                {
                    "success": True,
                    "repo_name": repo["repo_name"],
                    "path": rel_path,
                    "filename": os.path.basename(rel_path),
                    "content": content,
                    "language": language,
                    "size": size,
                    "truncated": truncated,
                    "binary": False,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/repo/<int:repo_id>/readme")
    @login_required
    @admin_required
    def github_repo_readme(repo_id):
        """Get README and basic stats from local clone."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT repo_name, repo_type, local_path, description, github_url, homepage_url FROM github_repositories WHERE id = %s",
                (repo_id,),
            )
            repo = cur.fetchone()
            if not repo or not repo["local_path"]:
                return jsonify({"success": False, "error": "Repository not cloned"}), 404

            base = repo["local_path"]
            if not os.path.isdir(base):
                return jsonify({"success": False, "error": "Clone directory missing"}), 404

            # Find README
            readme_content = None
            readme_name = None
            for candidate in ["README.md", "readme.md", "README", "README.rst", "README.txt"]:
                rpath = os.path.join(base, candidate)
                if os.path.isfile(rpath):
                    with open(rpath, "r", errors="replace") as f:
                        readme_content = f.read(64 * 1024)  # 64KB max
                    readme_name = candidate
                    break

            # Basic stats: count files and dirs
            file_count = 0
            dir_count = 0
            total_size = 0
            for root, dirs, files in os.walk(base):
                # Skip .git
                dirs[:] = [d for d in dirs if d != ".git"]
                dir_count += len(dirs)
                file_count += len(files)
                for fn in files:
                    try:
                        total_size += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass

            return jsonify(
                {
                    "success": True,
                    "repo_name": repo["repo_name"],
                    "repo_type": repo["repo_type"],
                    "description": repo.get("description"),
                    "github_url": repo.get("github_url"),
                    "homepage_url": repo.get("homepage_url"),
                    "readme": readme_content,
                    "readme_file": readme_name,
                    "stats": {
                        "files": file_count,
                        "directories": dir_count,
                        "total_size": total_size,
                    },
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # REPOS SUMMARY API
    # ==================================================================

    @bp.route("/api/github/repos")
    @login_required
    @admin_required
    def api_github_repos():
        """Simple repos listing for integration/dashboard use"""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, repo_name, repo_type, local_path, status,
                       indexed, indexed_files, indexed_at, updated_at,
                       description, github_url, homepage_url,
                       review_status, review_notes, reviewed_at, relevance_tags
                FROM github_repositories
                ORDER BY repo_name
            """
            )
            return jsonify({"success": True, "repos": [dict(r) for r in cur.fetchall()]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ==================================================================
    # REPO REVIEW STATUS API
    # ==================================================================

    @bp.route("/api/github/repositories/<int:repo_id>/review", methods=["PATCH"])
    @login_required
    @admin_required
    def update_repo_review(repo_id):
        """Manually stamp a repo's review status (approved/rejected/under_review)."""
        conn = None
        cur = None
        try:
            data = request.get_json(silent=True) or {}
            review_status = data.get("review_status")
            review_notes = data.get("review_notes")
            relevance_tags = data.get("relevance_tags")

            if not review_status:
                return jsonify({"success": False, "error": "review_status required"}), 400

            valid_statuses = ("approved", "pending", "rejected", "under_review")
            if review_status not in valid_statuses:
                return jsonify({"success": False, "error": f"Invalid status. Must be one of: {valid_statuses}"}), 400

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            updates = ["review_status = %s", "reviewed_at = NOW()"]
            params = [review_status]

            if review_notes is not None:
                updates.append("review_notes = %s")
                params.append(review_notes[:2000])

            if relevance_tags is not None:
                updates.append("relevance_tags = %s")
                params.append(relevance_tags if isinstance(relevance_tags, list) else [])

            params.append(repo_id)
            cur.execute(
                f"UPDATE github_repositories SET {', '.join(updates)} WHERE id = %s RETURNING *",
                params,
            )
            updated = cur.fetchone()
            conn.commit()

            if not updated:
                return jsonify({"success": False, "error": "Repo not found"}), 404

            return jsonify({"success": True, "repo": dict(updated)})
        except Exception as e:
            if conn:
                conn.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/github/skills/pipeline-stats")
    @login_or_api_key
    def api_github_skills_pipeline_stats():
        """Return skill pipeline funnel stats for the GitHub tab."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                # Skill status counts
                cur.execute(
                    """SELECT status, COUNT(*) as count
                       FROM github_skills
                       GROUP BY status
                       ORDER BY count DESC"""
                )
                status_counts = {r["status"]: r["count"] for r in cur.fetchall()}

                # Claude Code installations
                cur.execute(
                    """SELECT
                         COUNT(*) as installed,
                         COUNT(*) FILTER (WHERE struct_valid IS NOT NULL) as tested,
                         COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as passed,
                         COUNT(*) FILTER (WHERE dry_run_passed = FALSE) as failed,
                         COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
                       FROM skill_installations
                       WHERE target = 'claude_code'"""
                )
                inst = cur.fetchone()

                # Archie CLI installations
                cur.execute(
                    """SELECT COUNT(*) as synced
                       FROM skill_installations
                       WHERE target = 'archie_cli'"""
                )
                cli_inst = cur.fetchone()

                # Cluster push stats
                cur.execute(
                    """SELECT
                         COUNT(*) FILTER (WHERE fail_count = 0) as pushed,
                         COUNT(*) FILTER (WHERE fail_count > 0) as failed
                       FROM node_skill_pushes"""
                )
                cluster = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "pipeline": {
                        "discovered": status_counts.get("discovered", 0),
                        "analyzing": status_counts.get("analyzing", 0),
                        "analyzed": status_counts.get("analyzed", 0),
                        "registered": status_counts.get("registered", 0),
                        "installed": inst["installed"],
                        "tested": inst["tested"],
                        "passed": inst["passed"],
                        "failed": inst["failed"],
                        "adapted": inst["adapted"],
                        "cli_synced": cli_inst["synced"],
                        "cluster_pushed": cluster["pushed"],
                        "cluster_failed": cluster["failed"],
                    },
                }
            )
        except Exception as e:
            logger.error(f"[GitHub] Pipeline stats error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/github/skills/sync")
    @login_or_api_key
    def api_github_skills_sync():
        """Return tested+passing skills for CLI sync.

        Params:
            since: ISO timestamp — only return skills newer than this
            limit: int — max skills per response (default 50, max 200)
        """
        try:
            from database import get_db_cursor

            since = request.args.get("since")
            limit = min(int(request.args.get("limit", 50)), 200)

            with get_db_cursor() as (conn, cur):
                # Total available (for pagination awareness)
                cur.execute(
                    """SELECT COUNT(*) as total
                       FROM skill_installations si
                       WHERE si.target = 'claude_code'
                         AND si.dry_run_passed = TRUE"""
                )
                total_available = cur.fetchone()["total"]

                # Fetch skills with optional since filter
                if since:
                    cur.execute(
                        """SELECT si.skill_id, gs.repo_name, gs.skill_name,
                                  COALESCE(si.adapted_content, si.normalized_content) AS content,
                                  gs.quality_score, si.adapted,
                                  si.installed_at::text, si.tested_at::text
                           FROM skill_installations si
                           JOIN github_skills gs ON gs.id = si.skill_id
                           WHERE si.target = 'claude_code'
                             AND si.dry_run_passed = TRUE
                             AND si.installed_at > %s
                           ORDER BY si.installed_at ASC
                           LIMIT %s""",
                        (since, limit),
                    )
                else:
                    cur.execute(
                        """SELECT si.skill_id, gs.repo_name, gs.skill_name,
                                  COALESCE(si.adapted_content, si.normalized_content) AS content,
                                  gs.quality_score, si.adapted,
                                  si.installed_at::text, si.tested_at::text
                           FROM skill_installations si
                           JOIN github_skills gs ON gs.id = si.skill_id
                           WHERE si.target = 'claude_code'
                             AND si.dry_run_passed = TRUE
                           ORDER BY si.installed_at ASC
                           LIMIT %s""",
                        (limit,),
                    )
                rows = cur.fetchall()

            skills = []
            max_installed_at = None
            for row in rows:
                repo_slug = row["repo_name"].replace("/", "-").lower()
                skill_slug = row["skill_name"].replace("/", "-").replace(" ", "-").lower()
                if skill_slug.endswith(".md"):
                    skill_slug = skill_slug[:-3]
                skills.append(
                    {
                        "skill_id": row["skill_id"],
                        "repo": row["repo_name"],
                        "name": row["skill_name"],
                        "slug": skill_slug,
                        "repo_slug": repo_slug,
                        "content": row["content"] or "",
                        "quality_score": row["quality_score"],
                        "adapted": bool(row["adapted"]),
                        "installed_at": row["installed_at"],
                        "tested_at": row["tested_at"],
                    }
                )
                max_installed_at = row["installed_at"]

            return jsonify(
                {
                    "success": True,
                    "skills": skills,
                    "sync_token": max_installed_at,
                    "total_available": total_available,
                }
            )
        except Exception as e:
            logger.error(f"[GitHub] Skill sync error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/github/skills/sync-confirm", methods=["POST"])
    @login_or_api_key
    def api_github_skills_sync_confirm():
        """Record confirmed skill installations from CLI nodes.

        Body: {"skill_ids": [int, ...], "node_id": "hub"}
        Creates skill_installations rows with target='archie_cli'.
        """
        try:
            from database import get_db_cursor

            data = request.get_json(force=True)
            skill_ids = data.get("skill_ids", [])
            node_id = data.get("node_id", "unknown")

            if not skill_ids:
                return jsonify({"success": True, "confirmed": 0})

            confirmed = 0
            with get_db_cursor(commit=True) as (conn, cur):
                for skill_id in skill_ids:
                    cur.execute(
                        """SELECT install_path, normalized_content,
                                  adapted_content
                           FROM skill_installations
                           WHERE skill_id = %s AND target = 'claude_code'""",
                        (skill_id,),
                    )
                    source = cur.fetchone()
                    if not source:
                        continue

                    cli_path = (
                        source["install_path"]
                        .replace(".claude/skills-library/github/", "skills/github/")
                        .replace(".claude/skills/github/", "skills/github/")
                    )

                    cur.execute(
                        """INSERT INTO skill_installations
                           (skill_id, target, install_path,
                            normalized_content, adapted_content,
                            struct_valid, dry_run_passed,
                            adapted, installed_at)
                           VALUES (%s, 'archie_cli', %s, %s, %s,
                                   TRUE, TRUE, %s, NOW())
                           ON CONFLICT (skill_id, target) DO UPDATE
                           SET install_path = EXCLUDED.install_path,
                               installed_at = NOW()""",
                        (
                            skill_id,
                            cli_path,
                            source["normalized_content"],
                            source["adapted_content"],
                            source["adapted_content"] is not None,
                        ),
                    )
                    confirmed += 1

            logger.info(f"[GitHub] Skill sync confirmed: {confirmed} skills " f"for node '{node_id}'")
            return jsonify({"success": True, "confirmed": confirmed})
        except Exception as e:
            logger.error(f"[GitHub] Sync confirm error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ==================================================================
    # WEBHOOK ENDPOINT & TRACKED REPOS (Phase 1-3)
    # ==================================================================

    # GitHub webhook endpoint - receives push events from GitHub
    @bp.route("/github/webhook", methods=["POST"])
    def github_webhook():
        """
        Receive GitHub push webhooks for tracked repositories.
        Verifies HMAC signature, stores event, queues incremental reindex.
        """
        import hmac
        import hashlib
        from database import get_db_cursor

        # Get delivery ID for deduplication
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event_type = request.headers.get("X-GitHub-Event", "unknown")

        # Get raw payload for HMAC verification
        payload_bytes = request.get_data()

        # DEBUG: Log raw payload and computed signature
        logger.debug(f"[Webhook Debug] Raw payload: {payload_bytes}")
        logger.debug(f"[Webhook Debug] Payload length: {len(payload_bytes)}")

        # Only process push events for now
        if event_type != "push":
            return jsonify({"success": True, "message": f"Ignored event type: {event_type}"}), 200

        payload = request.get_json(silent=True) or {}

        # Find matching tracked repo by full_name (owner/repo)
        repo_full_name = payload.get("repository", {}).get("full_name", "")
        if not repo_full_name:
            return jsonify({"success": False, "error": "No repository in payload"}), 400

        try:
            owner, repo = repo_full_name.split("/", 1)
        except ValueError:
            return jsonify({"success": False, "error": "Invalid repository full_name"}), 400

        # Look up tracked repo
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, webhook_secret, auto_ingest, branch
                FROM github_tracked_repos
                WHERE owner = %s AND repo = %s AND status = 'active'
                """,
                (owner, repo),
            )
            tracked = cur.fetchone()

        if not tracked:
            # Not tracked - log but don't error (allows webhook registration without tracking)
            logger.info(f"[GitHub Webhook] Push to untracked repo: {repo_full_name}")
            return jsonify({"success": True, "message": "Repo not tracked"}), 200

        tracked_id = tracked["id"]
        webhook_secret = tracked["webhook_secret"]
        auto_ingest = tracked["auto_ingest"]
        tracked_branch = tracked["branch"]

        # Verify HMAC signature if secret configured
        if webhook_secret:
            sig_header = request.headers.get("X-Hub-Signature-256", "")
            if not sig_header.startswith("sha256="):
                logger.warning(f"[GitHub Webhook] Missing/invalid signature for {repo_full_name}")
                return jsonify({"success": False, "error": "Invalid signature"}), 401
            expected = hmac.new(webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig_header[7:], expected):
                logger.warning(f"[GitHub Webhook] Signature mismatch for {repo_full_name}")
                return jsonify({"success": False, "error": "Signature mismatch"}), 401

        # Store webhook event for audit
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO github_webhook_events
                (tracked_repo_id, event_type, github_delivery_id, payload)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (tracked_id, event_type, delivery_id, json.dumps(payload)),
            )
            event_id = cur.fetchone()["id"]

            # Update tracked repo last event info
            head_commit = payload.get("head_commit", {})
            last_sha = head_commit.get("id", "") if head_commit else ""
            cur.execute(
                """
                UPDATE github_tracked_repos
                SET last_event_at = NOW(),
                    last_event_type = %s,
                    last_sha = %s
                WHERE id = %s
                """,
                (event_type, last_sha, tracked_id),
            )

        # Queue incremental reindex if auto_ingest enabled
        if auto_ingest:
            # Get changed files via GitHub compare API (base: previous last_sha, head: new sha)
            ref = payload.get("ref", "")
            expected_ref = f"refs/heads/{tracked_branch}"
            if ref != expected_ref:
                logger.info(f"[GitHub Webhook] Push to {ref}, tracked branch is {tracked_branch} - skipping")
            else:
                # Queue reindex job - will fetch changed files in background worker
                with get_db_cursor(commit=True) as (conn, cur):
                    from_sha = None
                    # Get previous last_sha from tracked repo (before update)
                    # The payload's before commit is the previous head
                    before_sha = payload.get("before", "")
                    if before_sha and before_sha != "0" * 40:
                        from_sha = before_sha

                    cur.execute(
                        """
                        INSERT INTO github_reindex_queue
                        (tracked_repo_id, trigger_type, trigger_payload, from_sha, to_sha)
                        VALUES (%s, 'webhook_push', %s, %s, %s)
                        RETURNING id
                        """,
                        (tracked_id, json.dumps(payload), from_sha, last_sha),
                    )
                    queue_id = cur.fetchone()["id"]
                    logger.info(f"[GitHub Webhook] Queued incremental reindex #{queue_id} for {repo_full_name}")

        return jsonify({"success": True, "event_id": event_id}), 200

    # ==================================================================
    # TRACKED REPOS CRUD
    # ==================================================================

    @bp.route("/github/tracked-repos", methods=["GET"])
    @login_or_api_key
    def github_list_tracked_repos():
        from database import get_db_cursor

        """List all tracked repositories for webhook ingestion."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT gtr.*, gr.id as github_repo_id, gr.status as github_repo_status
                FROM github_tracked_repos gtr
                LEFT JOIN github_repositories gr
                    ON gr.repo_name LIKE '%' || gtr.owner || '/' || gtr.repo || '%'
                ORDER BY gtr.updated_at DESC
                """
            )
            repos = cur.fetchall()
            return jsonify({"success": True, "repos": repos})

    @bp.route("/github/tracked-repos", methods=["POST"])
    @login_or_api_key
    def github_create_tracked_repo():
        from database import get_db_cursor

        """Register a new repository for webhook tracking."""
        data = request.get_json(silent=True) or {}
        owner = data.get("owner", "").strip()
        repo = data.get("repo", "").strip()
        branch = data.get("branch", "main").strip()
        webhook_secret = data.get("webhook_secret", "").strip() or None
        auto_ingest = data.get("auto_ingest", True)
        is_ai_repo = data.get("is_ai_repo", False)
        relevance_tags = data.get("relevance_tags", [])
        max_files = data.get("max_files")
        description = data.get("description", "").strip() or None

        if not owner or not repo:
            return jsonify({"success": False, "error": "Owner and repo required"}), 400

        # Generate webhook secret if not provided
        import secrets

        if not webhook_secret:
            webhook_secret = secrets.token_urlsafe(32)

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO github_tracked_repos
                    (owner, repo, branch, webhook_secret, auto_ingest, is_ai_repo,
                     relevance_tags, max_files, description)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner, repo) DO UPDATE SET
                        branch = EXCLUDED.branch,
                        webhook_secret = EXCLUDED.webhook_secret,
                        auto_ingest = EXCLUDED.auto_ingest,
                        is_ai_repo = EXCLUDED.is_ai_repo,
                        relevance_tags = EXCLUDED.relevance_tags,
                        max_files = EXCLUDED.max_files,
                        description = EXCLUDED.description,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        owner,
                        repo,
                        branch,
                        webhook_secret,
                        auto_ingest,
                        is_ai_repo,
                        relevance_tags,
                        max_files,
                        description,
                    ),
                )
                new_id = cur.fetchone()["id"]

            return jsonify(
                {
                    "success": True,
                    "id": new_id,
                    "webhook_secret": webhook_secret,
                    "webhook_url": f"https://platform.kytranempowerment.com/tools/consciousness/github/webhook",
                }
            )
        except Exception as e:
            logger.error(f"[GitHub] Create tracked repo error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/github/tracked-repos/<int:repo_id>", methods=["PATCH"])
    @login_or_api_key
    def github_update_tracked_repo(repo_id):
        from database import get_db_cursor

        """Update a tracked repository."""
        data = request.get_json(silent=True) or {}
        allowed_fields = {
            "branch",
            "auto_ingest",
            "is_ai_repo",
            "relevance_tags",
            "max_files",
            "description",
            "status",
            "priority",
        }
        updates = {k: v for k, v in data.items() if k in allowed_fields}
        if not updates:
            return jsonify({"success": False, "error": "No valid fields to update"}), 400

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                values = list(updates.values()) + [repo_id]
                cur.execute(
                    f"UPDATE github_tracked_repos SET {set_clause}, updated_at = NOW() WHERE id = %s RETURNING *",
                    values,
                )
                updated = cur.fetchone()
                if not updated:
                    return jsonify({"success": False, "error": "Not found"}), 404

            return jsonify({"success": True, "repo": updated})
        except Exception as e:
            logger.error(f"[GitHub] Update tracked repo error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/github/tracked-repos/<int:repo_id>", methods=["DELETE"])
    @login_or_api_key
    def github_delete_tracked_repo(repo_id):
        from database import get_db_cursor

        """Delete a tracked repository."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM github_tracked_repos WHERE id = %s", (repo_id,))
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Not found"}), 404

            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"[GitHub] Delete tracked repo error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/github/tracked-repos/<int:repo_id>/register-webhook", methods=["POST"])
    @login_or_api_key
    def github_register_webhook(repo_id):
        from database import get_db_cursor

        """Register webhook with GitHub for a tracked repository."""
        headers, has_token = _get_github_headers()
        if not has_token:
            return jsonify({"success": False, "error": "GitHub token required"}), 400

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT owner, repo, webhook_secret, webhook_id FROM github_tracked_repos WHERE id = %s",
                (repo_id,),
            )
            repo = cur.fetchone()
            if not repo:
                return jsonify({"success": False, "error": "Not found"}), 404

        owner, repo_name, webhook_secret, existing_webhook_id = repo
        if not webhook_secret:
            return jsonify({"success": False, "error": "No webhook secret configured"}), 400

        # Delete existing webhook if present
        if existing_webhook_id:
            try:
                requests.delete(
                    f"https://api.github.com/repos/{owner}/{repo_name}/hooks/{existing_webhook_id}",
                    headers=headers,
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"[GitHub] Failed to delete existing webhook: {e}")

        # Create new webhook
        webhook_url = "https://platform.kytranempowerment.com/tools/consciousness/github/webhook"
        try:
            resp = requests.post(
                f"https://api.github.com/repos/{owner}/{repo_name}/hooks",
                headers=headers,
                json={
                    "name": "web",
                    "active": True,
                    "events": ["push"],
                    "config": {
                        "url": webhook_url,
                        "content_type": "json",
                        "secret": webhook_secret,
                        "insecure_ssl": "0",
                    },
                },
                timeout=10,
            )
            resp.raise_for_status()
            hook = resp.json()

            # Update tracked repo with new webhook ID
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE github_tracked_repos SET webhook_id = %s, webhook_url = %s, updated_at = NOW() WHERE id = %s",
                    (hook["id"], webhook_url, repo_id),
                )

            return jsonify({"success": True, "webhook": hook})
        except requests.RequestException as e:
            logger.error(f"[GitHub] Register webhook error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/github/reindex-queue", methods=["GET"])
    @login_or_api_key
    def github_list_reindex_queue():
        from database import get_db_cursor

        """List reindex queue items."""
        status_filter = request.args.get("status")
        with get_db_cursor() as (conn, cur):
            if status_filter:
                cur.execute(
                    """
                    SELECT grq.*, gtr.owner, gtr.repo
                    FROM github_reindex_queue grq
                    JOIN github_tracked_repos gtr ON grq.tracked_repo_id = gtr.id
                    WHERE grq.status = %s
                    ORDER BY grq.created_at DESC
                    LIMIT 100
                    """,
                    (status_filter,),
                )
            else:
                cur.execute(
                    """
                    SELECT grq.*, gtr.owner, gtr.repo
                    FROM github_reindex_queue grq
                    JOIN github_tracked_repos gtr ON grq.tracked_repo_id = gtr.id
                    ORDER BY grq.created_at DESC
                    LIMIT 100
                    """
                )
            items = cur.fetchall()
            return jsonify({"success": True, "items": items})

    @bp.route("/github/reindex-queue/<int:queue_id>/retry", methods=["POST"])
    @login_or_api_key
    def github_retry_reindex(queue_id):
        from database import get_db_cursor

        """Retry a failed reindex queue item."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE github_reindex_queue
                    SET status = 'pending', error_message = NULL, started_at = NULL, completed_at = NULL
                    WHERE id = %s AND status IN ('failed', 'completed')
                    RETURNING *
                    """,
                    (queue_id,),
                )
                item = cur.fetchone()
                if not item:
                    return jsonify({"success": False, "error": "Not found or not retryable"}), 404

            return jsonify({"success": True, "item": item})
        except Exception as e:
            logger.error(f"[GitHub] Retry reindex error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/github/webhook-events", methods=["GET"])
    @login_or_api_key
    def github_list_webhook_events():
        from database import get_db_cursor

        """List recent webhook events for audit."""
        limit = min(int(request.args.get("limit", 50)), 200)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT gwe.*, gtr.owner, gtr.repo
                FROM github_webhook_events gwe
                LEFT JOIN github_tracked_repos gtr ON gwe.tracked_repo_id = gtr.id
                ORDER BY gwe.received_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            events = cur.fetchall()
            return jsonify({"success": True, "events": events})
