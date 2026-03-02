"""GitHub Routes -- Repository indexing, search, dependencies

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- GitHub auth status and rate limits
- Selective and full-repo indexing (Tree API)
- Repository CRUD (list, update, delete)
- Indexed file listing
- Semantic search across GitHub files
- Dependency scanning and upgrade suggestions
- Repos summary API
"""

import base64
import json
import logging
import os
import threading
import traceback

import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


# ============================================================================
# GITHUB CONSTANTS
# ============================================================================

# Extensions worth downloading and indexing
INDEXABLE_CODE_EXT = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".bash",
    ".sql",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".vue",
    ".svelte",
    ".lua",
    ".r",
    ".cs",
}
INDEXABLE_DOC_EXT = {".md", ".txt", ".rst", ".adoc"}
INDEXABLE_CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".env"}
INDEXABLE_WEB_EXT = {".html", ".css", ".scss", ".less"}
INDEXABLE_EXT = INDEXABLE_CODE_EXT | INDEXABLE_DOC_EXT | INDEXABLE_CONFIG_EXT | INDEXABLE_WEB_EXT

SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    "coverage",
    ".tox",
    "target",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    "egg-info",
    ".next",
    ".nuxt",
    "vendor",
    "bower_components",
    ".gradle",
    ".mvn",
}

SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
}

# Directories with lower-value content (deprioritized, not skipped entirely)
LOW_VALUE_DIRS = {
    "tests",
    "test",
    "__tests__",
    "spec",
    "testing",
    "examples",
    "fixtures",
    "samples",
    "demo",
    "mock",
    "mocks",
    "__generated__",
    "locales",
    "translations",
    "i18n",
    ".github",
    ".circleci",
}

LOW_VALUE_FILES = {
    "changelog.md",
    "changes.md",
    "history.md",
    ".travis.yml",
    "makefile",
    "dockerfile",
}

MAX_FILE_SIZE = 500_000  # 500 KB per file
MAX_CONTENT_STORE = 100_000  # 100 KB stored in DB
MAX_FILES_PER_REPO = 2000  # global default cap per repo


# ============================================================================
# GITHUB HELPERS
# ============================================================================


def _get_github_headers():
    """Return (headers_dict, has_token) for GitHub API requests."""
    github_token = None
    try:
        token_path = "/mnt/archie_brain/secrets/api/github_token.txt"
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                github_token = f.read().strip()
    except Exception:
        pass
    if not github_token:
        github_token = os.environ.get("GITHUB_TOKEN")

    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers, bool(github_token)


def _check_rate_limit(response):
    """Check GitHub API response for rate limiting. Returns (is_limited, message)."""
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining", "")
        if remaining == "0":
            reset_ts = int(response.headers.get("X-RateLimit-Reset", 0))
            if reset_ts:
                import datetime as _dt

                reset_time = _dt.datetime.fromtimestamp(reset_ts).strftime("%H:%M:%S")
                return True, f"GitHub API rate limit exceeded. Resets at {reset_time}"
            return True, "GitHub API rate limit exceeded. Try again later."
    if response.status_code == 401:
        return True, "GitHub authentication failed. Check your token."
    return False, ""


def _reindex_repo_via_tree(owner, repo, repo_type, importance=0.85, max_files=None):
    """
    Recursively index a GitHub repo using the Tree API (1 API call for full tree).
    Downloads content via raw.githubusercontent.com (no API quota).
    Returns (indexed_count, errors, skipped_count, total_candidates, capped, effective_cap).
    """
    headers, _has_token = _get_github_headers()
    errors = []

    # 1. Get default branch
    repo_api = f"https://api.github.com/repos/{owner}/{repo}"
    resp = requests.get(repo_api, headers=headers, timeout=30)
    is_limited, limit_msg = _check_rate_limit(resp)
    if is_limited:
        raise Exception(limit_msg)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch repo info for {owner}/{repo}: HTTP {resp.status_code}")
    default_branch = resp.json().get("default_branch", "main")

    # 2. Get full tree recursively (1 API call)
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    resp = requests.get(tree_url, headers=headers, timeout=60)
    is_limited, limit_msg = _check_rate_limit(resp)
    if is_limited:
        raise Exception(limit_msg)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch tree for {owner}/{repo}: HTTP {resp.status_code}")
    tree_data = resp.json()
    all_items = tree_data.get("tree", [])

    # 3. Filter blobs only, skip unwanted dirs/files, only indexable extensions
    candidates = []
    for item in all_items:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        size = item.get("size", 0)
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()

        # Skip by extension
        if ext not in INDEXABLE_EXT:
            continue

        # Skip by size
        if size > MAX_FILE_SIZE:
            continue

        # Skip by directory
        path_parts = path.split("/")
        if any(part in SKIP_DIRS for part in path_parts[:-1]):
            continue

        # Skip by filename
        if filename in SKIP_FILES:
            continue

        candidates.append((path, filename, ext, size))

    # 4. Sort by 5-tier priority:
    #   0 = README files
    #   1 = Core source code (not in test/example/low-value dirs)
    #   2 = Documentation (not changelogs, not in low-value dirs)
    #   3 = Tests, examples, changelogs, low-value dirs
    #   4 = Config, CI, generated, web assets, everything else
    def sort_key(item):
        _path, fname, ext, _size = item
        fname_lower = fname.lower()
        path_parts = set(_path.split("/")[:-1])
        in_low_value = bool(path_parts & LOW_VALUE_DIRS)

        if fname_lower.startswith("readme"):
            return (0, _path)
        if ext in INDEXABLE_CODE_EXT and not in_low_value:
            return (1, _path)
        if ext in INDEXABLE_DOC_EXT and not in_low_value and fname_lower not in LOW_VALUE_FILES:
            return (2, _path)
        if in_low_value or fname_lower in LOW_VALUE_FILES:
            return (3, _path)
        return (4, _path)

    candidates.sort(key=sort_key)
    total_candidates = len(candidates)
    effective_cap = max_files if max_files is not None else MAX_FILES_PER_REPO
    capped = total_candidates > effective_cap
    candidates = candidates[:effective_cap]

    # 5. Delete old entries for this repo (and their embeddings)
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """DELETE FROM memory_embeddings WHERE source_type = 'knowledge_base'
               AND source_id IN (
                   SELECT id FROM knowledge_base
                   WHERE knowledge_type = 'github_file' AND repo_type = %s
               )""",
            (repo_type,),
        )
        cur.execute(
            "DELETE FROM knowledge_base WHERE knowledge_type = 'github_file' AND repo_type = %s",
            (repo_type,),
        )
        deleted = cur.rowcount
        conn.commit()

        # 6. Chunked pipeline: concurrent download -> upsert -> batch commit
        from concurrent.futures import ThreadPoolExecutor, as_completed

        BATCH_SIZE = 50
        MAX_WORKERS = 5
        indexed_count = 0
        skipped_count = 0
        raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}"

        def _download_file(item):
            """Download a single file. Thread-safe, no DB access."""
            fpath, fname, fext, fsize = item
            try:
                raw_url = f"{raw_base}/{fpath}"
                file_resp = requests.get(raw_url, timeout=30)
                if file_resp.status_code != 200:
                    return (
                        fpath,
                        fname,
                        fext,
                        fsize,
                        None,
                        f"Download failed ({file_resp.status_code}): {fpath}",
                    )
                content = file_resp.text
                if len(content) > MAX_FILE_SIZE:
                    return (
                        fpath,
                        fname,
                        fext,
                        fsize,
                        None,
                        None,
                    )  # oversized, skip silently
                return (fpath, fname, fext, fsize, content, None)
            except Exception as dl_err:
                return (
                    fpath,
                    fname,
                    fext,
                    fsize,
                    None,
                    f"Download error: {fpath}: {str(dl_err)}",
                )

        # Process in batches of BATCH_SIZE
        for batch_start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[batch_start : batch_start + BATCH_SIZE]

            # 6a. Download batch concurrently
            downloaded = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(_download_file, item): item for item in batch}
                for future in as_completed(futures):
                    downloaded.append(future.result())

            # 6b. Insert sequentially with ON CONFLICT DO UPDATE + SAVEPOINT
            for fpath, fname, fext, fsize, content, dl_error in downloaded:
                if dl_error:
                    errors.append(dl_error)
                    skipped_count += 1
                    continue
                if content is None:
                    skipped_count += 1
                    continue

                title = f"{owner}/{repo}: {fpath}"
                try:
                    cur.execute("SAVEPOINT sp_file")
                    cur.execute(
                        """
                        INSERT INTO knowledge_base (
                            knowledge_type, title, content, category, file_path,
                            importance_score, source_type, file_name, file_extension,
                            memory_metadata, tags, repo_type, created_at
                        ) VALUES (
                            'github_file', %s, %s, 'github', %s,
                            %s, 'github_tree', %s, %s,
                            %s, %s, %s, NOW()
                        )
                        ON CONFLICT (repo_type, file_path) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            importance_score = EXCLUDED.importance_score,
                            source_type = EXCLUDED.source_type,
                            file_name = EXCLUDED.file_name,
                            file_extension = EXCLUDED.file_extension,
                            memory_metadata = EXCLUDED.memory_metadata,
                            tags = EXCLUDED.tags,
                            created_at = EXCLUDED.created_at
                        RETURNING id
                        """,
                        (
                            title,
                            content[:MAX_CONTENT_STORE],
                            f"{owner}/{repo}/{fpath}",
                            importance,
                            fname,
                            fext,
                            json.dumps(
                                {
                                    "repo": f"{owner}/{repo}",
                                    "branch": default_branch,
                                    "size": fsize,
                                }
                            ),
                            ["github", owner, repo, repo_type],
                            repo_type,
                        ),
                    )
                    row = cur.fetchone()
                    kb_id = row["id"] if row else None
                    cur.execute("RELEASE SAVEPOINT sp_file")
                    indexed_count += 1

                except Exception as file_err:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_file")
                    errors.append(f"Error: {fpath}: {str(file_err)}")
                    skipped_count += 1

            # 6c. Batch commit + update progress
            conn.commit()
            cur.execute(
                "UPDATE github_repositories SET indexed_files = %s WHERE repo_type = %s",
                (indexed_count, repo_type),
            )
            conn.commit()

        # 7. Update github_repositories row
        cur.execute(
            """
            UPDATE github_repositories
            SET indexed = true, indexed_files = %s, indexed_at = NOW(),
                status = 'indexed', updated_at = NOW()
            WHERE repo_type = %s
            """,
            (indexed_count, repo_type),
        )
        conn.commit()

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return indexed_count, errors, skipped_count, total_candidates, capped, effective_cap


def _store_dependency_scan(cursor, scan_result):
    """Store scan results as upgrade_suggestion entries in knowledge_base.

    Only stores packages that have updates OR vulnerabilities.
    Deletes old suggestions for same package+source before inserting.
    """
    source = scan_result.get("source", "unknown")
    stored = 0

    for dep in scan_result.get("dependencies", []):
        has_vulns = bool(dep.get("vulnerabilities"))
        has_update = dep.get("has_update", False)
        is_deprecated = bool(dep.get("deprecated"))

        if not has_update and not has_vulns and not is_deprecated:
            continue

        pkg = dep["package"]
        ecosystem = dep["ecosystem"]

        # Determine severity and importance score
        severities = [v["severity"] for v in dep.get("vulnerabilities", [])]
        if "CRITICAL" in severities:
            severity = "critical"
            importance = 0.95
        elif "HIGH" in severities:
            severity = "high"
            importance = 0.90
        elif "MEDIUM" in severities:
            severity = "medium"
            importance = 0.80
        elif is_deprecated:
            severity = "high"
            importance = 0.85
        else:
            severity = "low"
            importance = 0.75

        # Build markdown content
        lines = [f"## {pkg} ({ecosystem})"]
        lines.append(f"**Source:** {source}")
        if dep["current_version"]:
            lines.append(f"**Current:** {dep['current_version']}")
        if dep["latest_version"]:
            lines.append(f"**Latest:** {dep['latest_version']}")
        if is_deprecated:
            lines.append(f"**DEPRECATED:** {dep['deprecated']}")
        if has_vulns:
            lines.append(f"\n### Vulnerabilities ({len(dep['vulnerabilities'])})")
            for v in dep["vulnerabilities"]:
                lines.append(f"- **{v['severity']}** [{v['id']}]: {v.get('summary', '')}")
                if v.get("patched_version"):
                    lines.append(f"  - Patched in: {v['patched_version']}")

        content = "\n".join(lines)
        # Include source in title to avoid unique constraint collisions across repos
        source_label = source.split("/")[-1] if "/" in source else source
        title = (
            f"[{severity.upper()}] {pkg} {dep['current_version']} → {dep['latest_version']} ({source_label})"
            if has_update
            else f"[{severity.upper()}] {pkg} - vulnerability ({source_label})"
        )

        metadata = json.dumps(
            {
                "severity": severity,
                "ecosystem": ecosystem,
                "package": pkg,
                "current_version": dep["current_version"],
                "latest_version": dep["latest_version"],
                "has_update": has_update,
                "deprecated": dep.get("deprecated"),
                "vulnerability_count": len(dep.get("vulnerabilities", [])),
                "vulnerabilities": dep.get("vulnerabilities", []),
                "scan_source": source,
                "scanned_at": scan_result.get("scanned_at"),
            }
        )

        # Delete old suggestion for same package+source
        cursor.execute(
            """DELETE FROM knowledge_base
               WHERE knowledge_type = 'upgrade_suggestion'
                 AND memory_metadata->>'package' = %s
                 AND memory_metadata->>'scan_source' = %s""",
            (pkg, source),
        )

        cursor.execute(
            """INSERT INTO knowledge_base
               (title, content, knowledge_type, source_type, primary_category,
                importance_score, memory_metadata, created_at)
               VALUES (%s, %s, 'upgrade_suggestion', 'dependency_scan', 'dependency_security',
                       %s, %s, NOW())""",
            (title, content, importance, metadata),
        )
        stored += 1

    return stored


def register_github_routes(bp, admin_required):
    """Register all GitHub-related routes on the consciousness blueprint."""

    # ==================================================================
    # AUTH STATUS
    # ==================================================================

    @bp.route("/github/auth-status", methods=["GET"])
    @login_required
    @admin_required
    def github_auth_status():
        """Check GitHub token validity and rate limit status."""
        headers, has_token = _get_github_headers()
        if not has_token:
            return jsonify(
                {
                    "success": True,
                    "authenticated": False,
                    "rate_limit": 60,
                    "rate_remaining": None,
                    "message": "No token configured — 60 requests/hour limit",
                }
            )
        try:
            resp = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                core = data.get("resources", {}).get("core", {})
                return jsonify(
                    {
                        "success": True,
                        "authenticated": True,
                        "rate_limit": core.get("limit", 5000),
                        "rate_remaining": core.get("remaining", 0),
                        "rate_reset": core.get("reset", 0),
                        "message": f"Authenticated — {core.get('remaining', 0)}/{core.get('limit', 5000)} requests remaining",
                    }
                )
            return jsonify(
                {
                    "success": True,
                    "authenticated": False,
                    "message": f"Token invalid (HTTP {resp.status_code})",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # ==================================================================
    # INDEXING
    # ==================================================================

    @bp.route("/github/index-selective", methods=["POST"])
    @login_required
    @admin_required
    def github_index_selective():
        """
        Index specific files/folders from a GitHub repo with semantic embeddings
        This allows ARCHIE to learn from GitHub repositories with higher priority
        """
        data = request.get_json() or {}
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
            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

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
                # ── Create Bridge Job ───────────────────────
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
                                "error": "An index job for this repo is already running — check Bridge Command for progress",
                                "duplicate": True,
                            }
                        ),
                        409,
                    )

                def _bg_index(o, r, rt, imp, mx, jid):
                    from ai_bridge.bridge_dispatcher import get_dispatcher as _gd

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

                cur.close()

                conn.close()

        # Paths specified — use Contents API for targeted indexing
        indexed_count = 0
        errors = []

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
                            file_response = requests.get(file_url, timeout=30)
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

            cur.close()

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
        Work runs in a background thread with progress tracked in Bridge Command.
        """
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT id, repo_name, repo_type, max_files FROM github_repositories ORDER BY id")
            repos = cur.fetchall()
            if not repos:
                return jsonify({"success": True, "total_indexed": 0, "total_repos": 0, "results": []})

            # ── Create Bridge Job (blocks duplicates) ───
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
                            "error": "A reindex-all job is already running — check Bridge Command for progress",
                            "duplicate": True,
                        }
                    ),
                    409,
                )

            def _bg_reindex(repos_list, jid):
                from ai_bridge.bridge_dispatcher import get_dispatcher as _gd

                d = _gd()
                total_indexed = 0
                completed_repos = 0
                error_count = 0
                try:
                    for repo_row in repos_list:
                        repo_name = repo_row["repo_name"]
                        repo_type = repo_row["repo_type"]
                        repo_max = repo_row.get("max_files")
                        try:
                            parts = repo_name.split("/")
                            indexed, errs, skipped, total_found, was_capped, used_cap = _reindex_repo_via_tree(
                                parts[0], parts[1], repo_type, max_files=repo_max
                            )
                            total_indexed += indexed
                            if errs:
                                error_count += 1
                            completed_repos += 1
                        except Exception as e:
                            logger.error(f"[GitHub] Reindex {repo_name} failed: {e}")
                            traceback.print_exc()
                            error_count += 1
                            completed_repos += 1
                        try:
                            d.update_job_progress(
                                jid,
                                completed_repos,
                                error_count,
                                {"total_indexed": total_indexed, "last_repo": repo_name},
                            )
                        except Exception as ue:
                            logger.error(f"[GitHub] Job #{jid} progress update failed: {ue}")
                    d.complete_job(jid)
                    logger.info(
                        f"[GitHub] Reindex-all job #{jid} done: {total_indexed} files across {len(repos_list)} repos"
                    )
                except Exception as fatal:
                    logger.error(f"[GitHub] Reindex-all job #{jid} thread crashed: {fatal}")
                    traceback.print_exc()
                    try:
                        d.update_job_progress(jid, completed_repos, error_count + 1, {"crash": str(fatal)})
                        d.complete_job(jid)
                    except Exception:
                        pass

            thread = threading.Thread(target=_bg_reindex, args=(list(repos), job_id), daemon=True)
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

            cur.close()

            conn.close()

    @bp.route("/github/reindex/<int:repo_id>", methods=["POST"])
    @login_required
    @admin_required
    def github_reindex_single(repo_id):
        """Re-index a single tracked repository using the Tree API.

        Creates a bridge_job so the work is visible in Bridge Command.
        """
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

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

            # ── Create Bridge Job ───────────────────────
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
                from ai_bridge.bridge_dispatcher import get_dispatcher as _gd

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

            cur.close()

            conn.close()

    # ==================================================================
    # REPOSITORY CRUD
    # ==================================================================

    @bp.route("/github/repositories", methods=["GET"])
    @login_required
    @admin_required
    def github_repositories():
        """List tracked GitHub repositories with their status"""
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

            cur.close()

            conn.close()

    @bp.route("/github/repositories/<int:repo_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def github_repository_update(repo_id):
        """Update a tracked repository's settings (e.g. max_files cap)."""
        try:
            data = request.get_json() or {}
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

            cur.close()

            conn.close()

    @bp.route("/github/repositories/<int:repo_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def github_repository_delete(repo_id):
        """Delete a tracked repository and its indexed files. Use ?preview=true for impact summary."""
        preview = request.args.get("preview", "").lower() == "true"
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

            cur.close()

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
                SELECT id, title, file_path, importance_score, has_embedding,
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

            cur.close()

            conn.close()

    # ==================================================================
    # SEMANTIC SEARCH
    # ==================================================================

    @bp.route("/github/search-semantic", methods=["POST"])
    @login_required
    @admin_required
    def github_search_semantic():
        """Semantic search across indexed GitHub files"""
        data = request.get_json() or {}
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
    # DEPENDENCY SCANNING
    # ==================================================================

    @bp.route("/github/scan-dependencies", methods=["POST"])
    @login_required
    @admin_required
    def github_scan_dependencies():
        """Scan GitHub repos for dependency updates and vulnerabilities."""
        from .dependency_scanner import DependencyScanner

        data = request.get_json() or {}
        repo_id = data.get("repo_id")
        include_platform = data.get("include_platform", True)

        # Load GitHub token from env or file
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            try:
                with open("/mnt/archie_brain/secrets/api/github_token.txt", "r") as f:
                    github_token = f.read().strip()
            except FileNotFoundError:
                pass

        scanner = DependencyScanner(github_token=github_token)
        results_summary = {
            "scans_performed": 0,
            "entries_created": 0,
            "total_updates": 0,
            "total_vulnerabilities": 0,
            "critical_count": 0,
            "scan_details": [],
        }

        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get repos to scan
            if repo_id:
                cur.execute(
                    "SELECT id, repo_name FROM github_repositories WHERE id = %s",
                    (repo_id,),
                )
            else:
                cur.execute("SELECT id, repo_name FROM github_repositories WHERE status IN ('cloned', 'indexed')")
            repos = cur.fetchall()

            dep_files = ["package.json", "requirements.txt"]

            for repo in repos:
                repo_name = repo["repo_name"]
                # repo_name is already in owner/repo format
                owner_repo = repo_name

                headers = {}
                if github_token:
                    headers["Authorization"] = f"Bearer {github_token}"
                    headers["Accept"] = "application/vnd.github.v3+json"

                for dep_file in dep_files:
                    try:
                        resp = requests.get(
                            f"https://api.github.com/repos/{owner_repo}/contents/{dep_file}",
                            headers=headers,
                            timeout=10,
                        )
                        if resp.status_code != 200:
                            continue

                        file_data = resp.json()
                        content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

                        scan = scanner.scan_dependency_file(content, dep_file, owner_repo)
                        cur.execute("SAVEPOINT dep_scan")
                        stored = _store_dependency_scan(cur, scan)
                        cur.execute("RELEASE SAVEPOINT dep_scan")

                        results_summary["scans_performed"] += 1
                        results_summary["entries_created"] += stored
                        results_summary["total_updates"] += scan.get("updates_available", 0)
                        results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                        results_summary["critical_count"] += scan.get("critical_count", 0)
                        results_summary["scan_details"].append(
                            {
                                "source": owner_repo,
                                "file": dep_file,
                                "packages": scan.get("packages_scanned", 0),
                                "updates": scan.get("updates_available", 0),
                                "vulnerabilities": scan.get("vulnerabilities_found", 0),
                            }
                        )
                    except Exception as e:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT dep_scan")
                        except Exception:
                            conn.rollback()
                        logger.warning(f"Failed to scan {owner_repo}/{dep_file}: {e}")

            # Scan local platform requirements.txt if requested
            if include_platform:
                try:
                    local_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "requirements.txt",
                    )
                    with open(local_path, "r") as f:
                        content = f.read()

                    scan = scanner.scan_dependency_file(content, "requirements.txt", "local/platform_v2")
                    cur.execute("SAVEPOINT local_scan")
                    stored = _store_dependency_scan(cur, scan)
                    cur.execute("RELEASE SAVEPOINT local_scan")

                    results_summary["scans_performed"] += 1
                    results_summary["entries_created"] += stored
                    results_summary["total_updates"] += scan.get("updates_available", 0)
                    results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                    results_summary["critical_count"] += scan.get("critical_count", 0)
                    results_summary["scan_details"].append(
                        {
                            "source": "local/platform_v2",
                            "file": "requirements.txt",
                            "packages": scan.get("packages_scanned", 0),
                            "updates": scan.get("updates_available", 0),
                            "vulnerabilities": scan.get("vulnerabilities_found", 0),
                        }
                    )
                except Exception as e:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT local_scan")
                    except Exception:
                        conn.rollback()
                    logger.warning(f"Failed to scan local requirements.txt: {e}")

            conn.commit()
            return jsonify({"success": True, **results_summary})

        except Exception as e:
            logger.error(f"Dependency scan failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # DEPENDENCY REPORTS & SUGGESTIONS
    # ==================================================================

    @bp.route("/github/dependency-report", methods=["GET"])
    @login_required
    @admin_required
    def github_dependency_report():
        """Get summary report of dependency scan results."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    COUNT(*) as total_suggestions,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'critical') as critical_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'high') as high_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'medium') as medium_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'low') as low_count,
                    COUNT(*) FILTER (WHERE (memory_metadata->>'has_update')::boolean = true) as updates_available,
                    COUNT(*) FILTER (WHERE (memory_metadata->>'vulnerability_count')::int > 0) as with_vulnerabilities,
                    MAX(created_at) as last_scan
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
            """
            )
            summary = dict(cur.fetchone())

            # Group by ecosystem
            cur.execute(
                """
                SELECT
                    memory_metadata->>'ecosystem' as ecosystem,
                    COUNT(*) as count
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
                GROUP BY memory_metadata->>'ecosystem'
            """
            )
            by_ecosystem = [dict(r) for r in cur.fetchall()]

            # Group by source
            cur.execute(
                """
                SELECT
                    memory_metadata->>'scan_source' as source,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' IN ('critical', 'high')) as urgent
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
                GROUP BY memory_metadata->>'scan_source'
                ORDER BY urgent DESC
            """
            )
            by_source = [dict(r) for r in cur.fetchall()]
            return jsonify(
                {
                    "success": True,
                    "summary": summary,
                    "by_ecosystem": by_ecosystem,
                    "by_source": by_source,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/github/upgrade-suggestions", methods=["GET"])
    @login_required
    @admin_required
    def github_upgrade_suggestions():
        """List upgrade suggestions with optional filters."""
        severity = request.args.get("severity")
        ecosystem = request.args.get("ecosystem")
        source = request.args.get("source")
        limit = request.args.get("limit", 50, type=int)

        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            conditions = ["knowledge_type = 'upgrade_suggestion'"]
            params = []

            if severity:
                conditions.append("memory_metadata->>'severity' = %s")
                params.append(severity)
            if ecosystem:
                conditions.append("memory_metadata->>'ecosystem' = %s")
                params.append(ecosystem)
            if source:
                conditions.append("memory_metadata->>'scan_source' = %s")
                params.append(source)

            where = " AND ".join(conditions)
            params.append(limit)

            cur.execute(
                f"""SELECT id, title, content, importance_score, memory_metadata, created_at
                    FROM knowledge_base
                    WHERE {where}
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT %s""",
                params,
            )
            suggestions = []
            for row in cur.fetchall():
                r = dict(row)
                if isinstance(r.get("memory_metadata"), str):
                    r["memory_metadata"] = json.loads(r["memory_metadata"])
                suggestions.append(r)
            return jsonify({"success": True, "suggestions": suggestions, "count": len(suggestions)})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # REPOS SUMMARY API (NEW)
    # ==================================================================

    # ==================================================================
    # GITHUB-SPECIFIC STATS
    # ==================================================================

    @bp.route("/github/stats")
    @login_required
    @admin_required
    def github_stats():
        """GitHub-specific file counts and embedding coverage."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_files,
                    SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded_files
                FROM knowledge_base
                WHERE knowledge_type = 'github_file'
                """
            )
            row = cur.fetchone()
            total = row["total_files"] or 0
            embedded = row["embedded_files"] or 0
            pct = round((embedded / total) * 100) if total > 0 else 0

            # Per-repo breakdown for verification
            cur.execute(
                """
                SELECT r.id, r.repo_name, r.indexed_files as expected,
                       COUNT(kb.id) as actual,
                       SUM(CASE WHEN kb.embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded
                FROM github_repositories r
                LEFT JOIN knowledge_base kb ON kb.knowledge_type = 'github_file'
                    AND kb.memory_metadata->>'repo' = r.repo_name
                GROUP BY r.id, r.repo_name, r.indexed_files
                ORDER BY r.repo_name
                """
            )
            repos = [dict(r) for r in cur.fetchall()]
            mismatches = [r for r in repos if (r["expected"] or 0) != (r["actual"] or 0)]
            return jsonify(
                success=True,
                total_files=total,
                embedded_files=embedded,
                embed_pct=pct,
                repos=repos,
                mismatches=mismatches,
            )
        except Exception as e:
            logger.error(f"GitHub stats error: {e}")
            return jsonify(success=False, error=str(e)), 500
        finally:

            cur.close()

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
                       indexed, indexed_files, indexed_at, updated_at
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
