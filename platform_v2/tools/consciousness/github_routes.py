"""GitHub Routes -- Coordinator + shared helpers/constants

Split into 3 focused route files (ADR-045 pattern):
- github_repo_routes.py    — Repository indexing, CRUD, file browsing, search
- github_skill_routes.py   — Skill pipeline discovery, adaptation, stats
- github_insights_routes.py — Auth status, dependency scanning, stats

This file retains:
- Shared helpers (_get_db, _get_github_headers, _check_rate_limit, etc.)
- Shared constants (INDEXABLE_EXT, SKIP_DIRS, etc.)
- Background workers (run_reindex_background, _reindex_repo_via_tree)
- register_github_routes() coordinator that delegates to sub-registrars
"""

import json
import logging
import os
from database import _get_db_password
import subprocess
import traceback

import psycopg2
import requests
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

REPOS_BASE = "/mnt/archie_brain/repos"


# ============================================================================
# DATABASE
# ============================================================================


def _get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# GITHUB API HELPERS
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


def _notify_ingestion_complete(repo_count, file_count, repo_names):
    """Send Telegram notification when GitHub repos are ingested.

    Tells Kytran what ARCHIE just learned so Claude can be upgraded next session.
    """
    # Build repo list (max 5 shown)
    repo_list = "\n".join(f"  \u2022 {r}" for r in repo_names[:5])
    if len(repo_names) > 5:
        repo_list += f"\n  ... and {len(repo_names) - 5} more"

    text = (
        f"{file_count} files indexed from {repo_count} repo(s)\n\n"
        f"Repos:\n{repo_list}\n\n"
        "Skills will be synced to Claude within 6 hours "
        "(Agent Loop Job #54). Next Claude session will have "
        "these skills auto-loaded.\n\n"
        "Use /archie-search to explore what was learned."
    )

    try:
        from services.telegram_service import send_sync

        send_sync("GitHub Ingestion Complete", text, source_module="consciousness.github_routes")
    except Exception as e:
        logger.warning(f"[GitHub] Telegram ingestion notification failed: {e}")


def _clone_or_pull_repo(repo_name, repo_type):
    """Clone or pull a GitHub repo to local disk.

    Returns (local_path, action, error) where action is 'cloned', 'pulled', or None on error.
    """
    owner, name = repo_name.split("/", 1)
    local_path = os.path.join(REPOS_BASE, repo_type, name)

    # Use token for authenticated clone (private repos, higher rate limits)
    _, has_token = _get_github_headers()
    token = None
    try:
        token_path = "/mnt/archie_brain/secrets/api/github_token.txt"
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                token = f.read().strip()
    except Exception:
        pass
    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if token:
        clone_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"
    else:
        clone_url = f"https://github.com/{repo_name}.git"

    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        if os.path.isdir(os.path.join(local_path, ".git")):
            # Pull latest
            result = subprocess.run(
                ["git", "-C", local_path, "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                # Try reset if ff-only fails (force-pushed upstream)
                subprocess.run(
                    ["git", "-C", local_path, "fetch", "origin"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                subprocess.run(
                    ["git", "-C", local_path, "reset", "--hard", "origin/HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            return local_path, "pulled", None
        else:
            # Fresh clone (shallow for speed)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, local_path],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                return None, None, f"Clone failed: {result.stderr[:200]}"
            return local_path, "cloned", None
    except subprocess.TimeoutExpired:
        return None, None, f"Timeout cloning {repo_name}"
    except Exception as e:
        return None, None, str(e)


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
# INCREMENTAL REINDEX
# ============================================================================


def _incremental_reindex_from_disk(owner, repo, repo_type, local_path, changed_files, importance=0.85):
    """Incrementally re-index only changed files from a locally cloned repo.

    Reads files from disk (no GitHub API calls). Upserts into knowledge_base.
    Deletes KB entries for files that were removed from the repo.

    Args:
        owner: GitHub owner (e.g., 'NousResearch')
        repo: GitHub repo name (e.g., 'hermes-agent')
        repo_type: Category string for the repo
        local_path: Absolute path to the local clone
        changed_files: List of relative file paths that changed (from git diff)
        importance: Importance score for indexed entries

    Returns:
        (indexed_count, deleted_count, skipped_count, errors)
    """
    repo_full = f"{owner}/{repo}"
    indexed_count = 0
    deleted_count = 0
    skipped_count = 0
    errors = []

    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        for rel_path in changed_files:
            filename = os.path.basename(rel_path)
            ext = os.path.splitext(filename)[1].lower()

            # Skip non-indexable extensions
            if ext not in INDEXABLE_EXT:
                skipped_count += 1
                continue

            # Skip by directory
            path_parts = rel_path.split("/")
            if any(part in SKIP_DIRS for part in path_parts[:-1]):
                skipped_count += 1
                continue

            # Skip by filename
            if filename in SKIP_FILES:
                skipped_count += 1
                continue

            abs_path = os.path.join(local_path, rel_path)
            title = f"{owner}/{repo}: {rel_path}"
            file_path_db = f"{owner}/{repo}/{rel_path}"

            # If file was deleted, remove from KB
            if not os.path.isfile(abs_path):
                try:
                    cur.execute("SAVEPOINT sp_del")
                    cur.execute(
                        """DELETE FROM memory_embeddings WHERE source_type = 'knowledge_base'
                           AND source_id IN (
                               SELECT id FROM knowledge_base
                               WHERE knowledge_type = 'github_file'
                                 AND file_path = %s
                           )""",
                        (file_path_db,),
                    )
                    cur.execute(
                        """DELETE FROM knowledge_base
                           WHERE knowledge_type = 'github_file'
                             AND file_path = %s""",
                        (file_path_db,),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_del")
                    deleted_count += cur.rowcount
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_del")
                continue

            # Read file from disk
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(MAX_FILE_SIZE)
                if len(content) < 10:  # Too small to be useful
                    skipped_count += 1
                    continue
            except Exception as read_err:
                errors.append(f"Read error: {rel_path}: {str(read_err)[:60]}")
                skipped_count += 1
                continue

            # Determine file type flags
            is_code = ext in INDEXABLE_CODE_EXT
            is_doc = ext in INDEXABLE_DOC_EXT

            # Upsert into knowledge_base
            try:
                cur.execute("SAVEPOINT sp_file")
                cur.execute(
                    """
                    INSERT INTO knowledge_base (
                        knowledge_type, title, content, category, file_path,
                        importance_score, source_type, file_name, file_extension,
                        memory_metadata, tags, repo_type, is_code, is_documentation,
                        created_at
                    ) VALUES (
                        'github_file', %s, %s, 'github', %s,
                        %s, 'github_tree', %s, %s,
                        %s, %s, %s, %s, %s,
                        NOW()
                    )
                    ON CONFLICT (repo_type, file_path) DO UPDATE SET
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        importance_score = EXCLUDED.importance_score,
                        file_name = EXCLUDED.file_name,
                        memory_metadata = EXCLUDED.memory_metadata,
                        created_at = NOW()
                    RETURNING id
                    """,
                    (
                        title,
                        content[:MAX_CONTENT_STORE],
                        file_path_db,
                        importance,
                        filename,
                        ext,
                        json.dumps({"repo": repo_full, "incremental": True}),
                        ["github", owner, repo, repo_type],
                        repo_type,
                        is_code,
                        is_doc,
                    ),
                )
                cur.execute("RELEASE SAVEPOINT sp_file")
                indexed_count += 1
            except Exception as db_err:
                cur.execute("ROLLBACK TO SAVEPOINT sp_file")
                errors.append(f"DB error: {rel_path}: {str(db_err)[:60]}")
                skipped_count += 1

        conn.commit()

        # Update github_repositories counts
        cur.execute(
            """
            UPDATE github_repositories
            SET indexed_files = COALESCE((
                    SELECT count(*) FROM knowledge_base
                    WHERE knowledge_type = 'github_file'
                      AND memory_metadata->>'repo' = %s
                ), 0),
                indexed_at = NOW(),
                updated_at = NOW()
            WHERE repo_name = %s
            """,
            (repo_full, repo_full),
        )
        conn.commit()

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return indexed_count, deleted_count, skipped_count, errors


# ============================================================================
# FULL REPO REINDEX VIA TREE API
# ============================================================================


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
        repo_full = f"{owner}/{repo}"
        cur.execute(
            """DELETE FROM memory_embeddings WHERE source_type = 'knowledge_base'
               AND source_id IN (
                   SELECT id FROM knowledge_base
                   WHERE knowledge_type = 'github_file'
                     AND memory_metadata->>'repo' = %s
               )""",
            (repo_full,),
        )
        cur.execute(
            """DELETE FROM knowledge_base
               WHERE knowledge_type = 'github_file'
                 AND memory_metadata->>'repo' = %s""",
            (repo_full,),
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
                "UPDATE github_repositories SET indexed_files = %s WHERE repo_name = %s",
                (indexed_count, repo_full),
            )
            conn.commit()

        # 7. Upsert github_repositories row — creates tracking row for new repos,
        #    updates existing ones. Uses repo_name (unique) not repo_type (shared).
        cur.execute(
            """
            INSERT INTO github_repositories
                (repo_name, repo_type, local_path, status, indexed, indexed_files,
                 indexed_at, github_url, created_at, updated_at)
            VALUES (%s, %s, %s, 'indexed', true,
                COALESCE((
                    SELECT count(*) FROM knowledge_base
                    WHERE knowledge_type = 'github_file'
                      AND memory_metadata->>'repo' = %s
                ), 0),
                NOW(), %s, NOW(), NOW()
            )
            ON CONFLICT (repo_name) DO UPDATE SET
                indexed = true,
                indexed_files = COALESCE((
                    SELECT count(*) FROM knowledge_base
                    WHERE knowledge_type = 'github_file'
                      AND memory_metadata->>'repo' = EXCLUDED.repo_name
                ), 0),
                indexed_at = NOW(),
                status = 'indexed',
                updated_at = NOW()
            """,
            (
                repo_full,
                repo_type,
                f"/mnt/archie_brain/repos/{repo_type}/{repo}",
                repo_full,
                f"https://github.com/{owner}/{repo}",
            ),
        )
        conn.commit()

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return indexed_count, errors, skipped_count, total_candidates, capped, effective_cap


# ============================================================================
# DEPENDENCY SCAN HELPER
# ============================================================================


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


# ============================================================================
# BACKGROUND REINDEX WORKER
# ============================================================================


def run_reindex_background(repos_list, job_id):
    """Background worker for reindexing all repos. Callable from server-loop.

    For each repo:
    1. Clone or pull to /mnt/archie_brain/repos/<repo_type>/<name>/
    2. Index files into knowledge_base via Tree API
    3. Update github_repositories with local_path, indexed_at, status
    """
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    d = get_dispatcher()
    total_indexed = 0
    completed_repos = 0
    error_count = 0
    try:
        for repo_row in repos_list:
            repo_name = repo_row["repo_name"]
            repo_type = repo_row["repo_type"]
            repo_id = repo_row["id"]
            repo_max = repo_row.get("max_files")
            try:
                # Step 1: Clone or pull to local disk
                local_path, action, clone_err = _clone_or_pull_repo(repo_name, repo_type)
                if clone_err:
                    logger.warning(f"[GitHub] Clone/pull {repo_name} failed: {clone_err}")
                    # Continue to index via API even if clone fails
                else:
                    logger.info(f"[GitHub] {action} {repo_name} → {local_path}")
                    # Update local_path in DB
                    try:
                        conn_u = _get_db()
                        cur_u = conn_u.cursor()
                        cur_u.execute(
                            """UPDATE github_repositories
                               SET local_path = %s, status = 'cloned',
                                   cloned_at = COALESCE(cloned_at, NOW()),
                                   updated_at = NOW()
                               WHERE id = %s""",
                            (local_path, repo_id),
                        )
                        conn_u.commit()
                        cur_u.close()
                        conn_u.close()
                    except Exception as db_err:
                        logger.error(f"[GitHub] DB update for {repo_name} local_path failed: {db_err}")

                # Step 2: Index files into knowledge_base
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
                    job_id,
                    completed_repos,
                    error_count,
                    {"total_indexed": total_indexed, "last_repo": repo_name},
                )
            except Exception as ue:
                logger.error(f"[GitHub] Job #{job_id} progress update failed: {ue}")
        d.complete_job(job_id)
        logger.info(f"[GitHub] Reindex-all job #{job_id} done: {total_indexed} files across {len(repos_list)} repos")

        # Telegram notification — tell Kytran what ARCHIE just learned
        try:
            _notify_ingestion_complete(
                repo_count=len(repos_list),
                file_count=total_indexed,
                repo_names=[r["repo_name"] for r in repos_list],
            )
        except Exception as tg_err:
            logger.debug(f"[GitHub] Telegram notification failed: {tg_err}")
    except Exception as fatal:
        logger.error(f"[GitHub] Reindex-all job #{job_id} thread crashed: {fatal}")
        traceback.print_exc()
        try:
            d.update_job_progress(job_id, completed_repos, error_count + 1, {"crash": str(fatal)})
            d.complete_job(job_id)
        except Exception:
            pass


# ============================================================================
# COORDINATOR — delegates to sub-route registrars
# ============================================================================


def register_github_routes(bp, admin_required):
    """Register all GitHub-related routes on the consciousness blueprint.

    Delegates to 3 focused route files:
    - github_repo_routes: indexing, CRUD, file browsing, search
    - github_skill_routes: skill pipeline discovery, adaptation, stats
    - github_insights_routes: auth status, dependency scanning, stats
    """
    from .github_repo_routes import register_github_repo_routes
    from .github_skill_routes import register_github_skill_routes
    from .github_insights_routes import register_github_insights_routes

    register_github_repo_routes(bp, admin_required)
    register_github_skill_routes(bp, admin_required)
    register_github_insights_routes(bp, admin_required)
