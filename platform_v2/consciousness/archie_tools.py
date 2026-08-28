"""
A.R.C.H.I.E.'s Tool System
Tools that A.R.C.H.I.E. can use to interact with her own codebase and improve herself
"""

import logging
import os
from database import _get_db_password
import re

logger = logging.getLogger(__name__)
import subprocess
from pathlib import Path
from datetime import datetime

# Base directory for A.R.C.H.I.E.'s codebase (inside Docker container)
ARCHIE_BASE = "/app"
ALLOWED_PATHS = [
    "/app",  # Main application directory
    "/mnt/archie_brain/platform_v2",  # Host mount point (if accessible)
    "/mnt/archie_brain/ai_bridge",
    "/mnt/archie_brain/docs",
]

# ============================================================================
# SAFETY & VALIDATION
# ============================================================================


def is_safe_path(path):
    """Ensure path is within allowed directories"""
    real_path = os.path.realpath(path)  # realpath resolves symlinks; abspath does not
    return any(real_path == allowed or real_path.startswith(allowed + os.sep) for allowed in ALLOWED_PATHS)


def is_safe_operation(path, operation="read"):
    """Check if operation is safe to perform"""
    # Don't allow modifying critical files without explicit approval
    critical_files = ["app.py", "docker-compose.yml", ".env", "requirements.txt"]

    if operation == "write":
        filename = os.path.basename(path)
        if filename in critical_files:
            return False, f"Critical file {filename} requires explicit approval"

    if not is_safe_path(path):
        return False, "Path outside allowed directories"

    return True, "Safe"


# ============================================================================
# FILE OPERATIONS
# ============================================================================


def read_file(path, start_line=None, end_line=None):
    """
    Read a file from the codebase

    Args:
        path: File path (absolute or relative to ARCHIE_BASE)
        start_line: Optional start line (1-indexed)
        end_line: Optional end line (1-indexed)

    Returns:
        {
            'success': bool,
            'content': str,
            'lines': int,
            'path': str,
            'error': str (if failed)
        }
    """
    try:
        # Convert relative to absolute
        if not os.path.isabs(path):
            path = os.path.join(ARCHIE_BASE, path)

        # Safety check
        safe, msg = is_safe_operation(path, "read")
        if not safe:
            return {"success": False, "error": msg}

        if not os.path.exists(path):
            return {"success": False, "error": f"File not found: {path}"}

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Apply line range if specified
        if start_line is not None or end_line is not None:
            start = (start_line - 1) if start_line else 0
            end = end_line if end_line else len(lines)
            lines = lines[start:end]

        content = "".join(lines)

        return {
            "success": True,
            "content": content,
            "lines": len(lines),
            "path": path,
            "full_lines": len(lines) if start_line or end_line else None,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def edit_file(path, old_content, new_content, line_start=None, line_end=None, proposal_id=None):
    """
    Safely edit a file by replacing specific content (SAFER than write_file)

    Args:
        path: File path
        old_content: Exact content to find and replace
        new_content: New content to insert
        line_start: Optional starting line number for context
        line_end: Optional ending line number for context
        proposal_id: Optional proposal ID for backup naming/tracking

    Returns:
        {
            'success': bool,
            'path': str,
            'backup_path': str,
            'diff': str,  # Shows what changed
            'lines_changed': int
        }
    """
    try:
        # Convert relative to absolute
        if not os.path.isabs(path):
            path = os.path.join(ARCHIE_BASE, path)

        # Safety check
        safe, msg = is_safe_operation(path, "write")
        if not safe:
            return {"success": False, "error": msg, "requires_approval": True}

        # Read current file
        if not os.path.exists(path):
            return {"success": False, "error": f"File not found: {path}"}

        with open(path, "r") as f:
            original_content = f.read()

        # Check if old_content exists
        if old_content not in original_content:
            return {
                "success": False,
                "error": "Content to replace not found in file",
                "suggestion": "Use read_file first to verify exact content",
            }

        # Create backup with proposal reference if provided
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if proposal_id:
            backup_path = f"{path}.backup_proposal{proposal_id}_{timestamp}"
        else:
            backup_path = f"{path}.backup_{timestamp}"

        with open(backup_path, "w") as f:
            f.write(original_content)

        # Apply edit
        new_file_content = original_content.replace(old_content, new_content, 1)

        # Calculate diff
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                original_content.splitlines(),
                new_file_content.splitlines(),
                fromfile=f"{os.path.basename(path)} (original)",
                tofile=f"{os.path.basename(path)} (modified)",
                lineterm="",
            )
        )

        # Count changed lines
        lines_changed = len([line for line in diff.splitlines() if line.startswith("+") or line.startswith("-")])

        # Write new content
        with open(path, "w") as f:
            f.write(new_file_content)

        return {
            "success": True,
            "path": path,
            "backup_path": backup_path,
            "diff": diff,
            "lines_changed": lines_changed,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(path, content, create_backup=True, proposal_id=None):
    """
    Write content to a file (REQUIRES APPROVAL)

    Args:
        path: File path
        content: New file content
        create_backup: Whether to create backup before writing
        proposal_id: Optional proposal ID for backup naming/tracking

    Returns:
        {
            'success': bool,
            'path': str,
            'backup_path': str (if backup created),
            'requires_approval': bool,
            'error': str (if failed)
        }
    """
    try:
        # Convert relative to absolute
        if not os.path.isabs(path):
            path = os.path.join(ARCHIE_BASE, path)

        # Safety check
        safe, msg = is_safe_operation(path, "write")
        if not safe:
            return {
                "success": False,
                "error": msg,
                "requires_approval": True,
                "path": path,
            }

        backup_path = None

        # Create backup if file exists with proposal reference if provided
        if create_backup and os.path.exists(path):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if proposal_id:
                backup_path = f"{path}.backup_proposal{proposal_id}_{timestamp}"
            else:
                backup_path = f"{path}.backup_{timestamp}"

            with open(path, "r") as f:
                backup_content = f.read()
            with open(backup_path, "w") as f:
                f.write(backup_content)

        # Write new content
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "path": path,
            "backup_path": backup_path,
            "requires_approval": False,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def list_files(directory, pattern="*", recursive=False):
    """
    List files in a directory

    Args:
        directory: Directory path
        pattern: File pattern (e.g., "*.py")
        recursive: Search subdirectories

    Returns:
        {
            'success': bool,
            'files': list of dicts with {path, size, modified},
            'count': int,
            'error': str (if failed)
        }
    """
    try:
        if not os.path.isabs(directory):
            directory = os.path.join(ARCHIE_BASE, directory)

        safe, msg = is_safe_operation(directory, "read")
        if not safe:
            return {"success": False, "error": msg}

        if not os.path.exists(directory):
            return {"success": False, "error": f"Directory not found: {directory}"}

        path_obj = Path(directory)

        if recursive:
            file_paths = path_obj.rglob(pattern)
        else:
            file_paths = path_obj.glob(pattern)

        files = []
        for file_path in file_paths:
            if file_path.is_file():
                stat = file_path.stat()
                files.append(
                    {
                        "path": str(file_path),
                        "name": file_path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

        # Sort by name
        files.sort(key=lambda x: x["name"])

        return {
            "success": True,
            "files": files,
            "count": len(files),
            "directory": directory,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# CODE SEARCH
# ============================================================================


def search_code(pattern, directory=None, file_pattern="*.py", max_results=50):
    """
    Search for code patterns in files

    Args:
        pattern: Regex pattern to search for
        directory: Directory to search (default: ARCHIE_BASE)
        file_pattern: File pattern to search in
        max_results: Maximum results to return

    Returns:
        {
            'success': bool,
            'matches': list of {file, line_number, line_content, context},
            'count': int,
            'error': str (if failed)
        }
    """
    try:
        if directory is None:
            directory = ARCHIE_BASE
        elif not os.path.isabs(directory):
            directory = os.path.join(ARCHIE_BASE, directory)

        safe, msg = is_safe_operation(directory, "read")
        if not safe:
            return {"success": False, "error": msg}

        matches = []
        regex = re.compile(pattern, re.IGNORECASE)

        # Get all files matching pattern
        path_obj = Path(directory)
        file_paths = path_obj.rglob(file_pattern)

        for file_path in file_paths:
            if not file_path.is_file():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        # Get context (2 lines before and after)
                        start = max(0, i - 3)
                        end = min(len(lines), i + 2)
                        context = "".join(lines[start:end])

                        matches.append(
                            {
                                "file": str(file_path),
                                "line_number": i,
                                "line_content": line.strip(),
                                "context": context,
                            }
                        )

                        if len(matches) >= max_results:
                            break
            except Exception:
                # Skip files that can't be read
                continue

            if len(matches) >= max_results:
                break

        return {
            "success": True,
            "matches": matches,
            "count": len(matches),
            "pattern": pattern,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# GIT OPERATIONS
# ============================================================================


def git_diff(path=None):
    """
    Get git diff for a file or entire repo

    Args:
        path: Optional file path (None for entire repo)

    Returns:
        {
            'success': bool,
            'diff': str,
            'has_changes': bool,
            'error': str (if failed)
        }
    """
    try:
        cmd = ["git", "diff"]

        if path:
            if not os.path.isabs(path):
                path = os.path.join(ARCHIE_BASE, path)
            cmd.append(path)

        result = subprocess.run(cmd, cwd=ARCHIE_BASE, capture_output=True, text=True)

        diff_output = result.stdout

        return {
            "success": True,
            "diff": diff_output,
            "has_changes": len(diff_output) > 0,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def git_status():
    """Get git status of the repository"""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=ARCHIE_BASE,
            capture_output=True,
            text=True,
        )

        status = result.stdout
        files = []

        for line in status.split("\n"):
            if line.strip():
                status_code = line[:2]
                filename = line[3:].strip()
                files.append({"file": filename, "status": status_code.strip()})

        return {"success": True, "files": files, "has_changes": len(files) > 0}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# CODE ANALYSIS
# ============================================================================


def analyze_file(path):
    """
    Analyze a Python file for potential improvements

    Returns:
        {
            'success': bool,
            'analysis': {
                'lines': int,
                'functions': list,
                'classes': list,
                'imports': list,
                'suggestions': list
            },
            'error': str (if failed)
        }
    """
    try:
        result = read_file(path)
        if not result["success"]:
            return result

        content = result["content"]
        lines = content.split("\n")

        # Basic analysis
        functions = []
        classes = []
        imports = []

        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()

            # Find functions
            if line_stripped.startswith("def "):
                func_name = line_stripped.split("(")[0].replace("def ", "")
                functions.append({"name": func_name, "line": i})

            # Find classes
            if line_stripped.startswith("class "):
                class_name = line_stripped.split("(")[0].split(":")[0].replace("class ", "")
                classes.append({"name": class_name, "line": i})

            # Find imports
            if line_stripped.startswith("import ") or line_stripped.startswith("from "):
                imports.append({"statement": line_stripped, "line": i})

        # Generate suggestions
        suggestions = []

        # Check for long functions (>50 lines is a rough heuristic)
        # Check for missing docstrings
        # Check for repeated code patterns

        return {
            "success": True,
            "analysis": {
                "path": path,
                "lines": len(lines),
                "functions": functions,
                "classes": classes,
                "imports": imports,
                "suggestions": suggestions,
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# TOOL EXECUTION
# ============================================================================

# ============================================================================
# KNOWLEDGE BASE TOOLS - A.R.C.H.I.E.'s Self-Knowledge
# ============================================================================


def query_knowledge(search_term, knowledge_type=None, limit=10):
    """
    Query A.R.C.H.I.E.'s knowledge base about her own codebase

    Args:
        search_term: What to search for
        knowledge_type: Optional filter (file, function, class, module, concept)
        limit: Max results

    Returns:
        {
            'success': bool,
            'results': list of knowledge entries,
            'count': int
        }
    """
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build query
        conditions = ["(entity_name ILIKE %s OR description ILIKE %s OR purpose ILIKE %s)"]
        params = [f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"]

        if knowledge_type:
            conditions.append("knowledge_type = %s")
            params.append(knowledge_type)

        query = f"""
            SELECT * FROM archie_codebase_knowledge
            WHERE {' AND '.join(conditions)}
            ORDER BY importance_score DESC, last_updated DESC
            LIMIT %s
        """
        params.append(limit)

        cur.execute(query, params)
        results = cur.fetchall()

        cur.close()
        conn.close()

        # Convert datetime objects to strings for JSON serialization
        serializable_results = []
        for result in results:
            result_dict = dict(result)
            # Convert datetime fields to ISO format strings
            if "last_updated" in result_dict and result_dict["last_updated"]:
                result_dict["last_updated"] = result_dict["last_updated"].isoformat()
            serializable_results.append(result_dict)

        return {
            "success": True,
            "results": serializable_results,
            "count": len(serializable_results),
            "search_term": search_term,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def add_knowledge(
    entity_name,
    knowledge_type,
    description,
    file_path=None,
    purpose=None,
    code_snippet=None,
    importance=0.5,
):
    """
    Add new knowledge to A.R.C.H.I.E.'s knowledge base

    Args:
        entity_name: Name of the thing (function, file, class, etc.)
        knowledge_type: Type (file, function, class, module, concept)
        description: What it does
        file_path: Optional path to file
        purpose: Why it exists
        code_snippet: Example code
        importance: 0.0 to 1.0

    Returns:
        {
            'success': bool,
            'knowledge_id': int,
            'message': str
        }
    """
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO archie_codebase_knowledge
            (entity_name, knowledge_type, description, file_path, purpose,
             code_snippet, importance_score, auto_learned)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
        """,
            (
                entity_name,
                knowledge_type,
                description,
                file_path,
                purpose,
                code_snippet,
                importance,
            ),
        )

        knowledge_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "knowledge_id": knowledge_id,
            "message": f"Learned about {entity_name} ({knowledge_type})",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def learn_from_file(file_path):
    """
    Analyze a file and add knowledge about it to A.R.C.H.I.E.'s knowledge base

    Args:
        file_path: Path to file to learn from

    Returns:
        {
            'success': bool,
            'learned': list of what was learned,
            'knowledge_ids': list of IDs
        }
    """
    try:
        # Read and analyze the file
        file_result = read_file(file_path)
        if not file_result["success"]:
            return file_result

        analysis_result = analyze_file(file_path)
        if not analysis_result["success"]:
            return analysis_result

        analysis = analysis_result["analysis"]
        learned = []
        knowledge_ids = []

        # Learn about the file itself
        file_knowledge = add_knowledge(
            entity_name=os.path.basename(file_path),
            knowledge_type="file",
            description=f'File with {analysis["lines"]} lines, {len(analysis["functions"])} functions, {len(analysis["classes"])} classes',
            file_path=file_path,
            importance=0.7,
        )
        if file_knowledge["success"]:
            learned.append(f"File: {os.path.basename(file_path)}")
            knowledge_ids.append(file_knowledge["knowledge_id"])

        # Learn about each function
        for func in analysis["functions"][:5]:  # Limit to first 5
            func_knowledge = add_knowledge(
                entity_name=func["name"],
                knowledge_type="function",
                description=f'Function in {os.path.basename(file_path)} at line {func["line"]}',
                file_path=file_path,
                importance=0.6,
            )
            if func_knowledge["success"]:
                learned.append(f'Function: {func["name"]}')
                knowledge_ids.append(func_knowledge["knowledge_id"])

        # Learn about each class
        for cls in analysis["classes"][:5]:  # Limit to first 5
            cls_knowledge = add_knowledge(
                entity_name=cls["name"],
                knowledge_type="class",
                description=f'Class in {os.path.basename(file_path)} at line {cls["line"]}',
                file_path=file_path,
                importance=0.7,
            )
            if cls_knowledge["success"]:
                learned.append(f'Class: {cls["name"]}')
                knowledge_ids.append(cls_knowledge["knowledge_id"])

        return {
            "success": True,
            "learned": learned,
            "knowledge_ids": knowledge_ids,
            "count": len(learned),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# AGENT-SPECIFIC TOOLS
# ============================================================================


def create_improvement_proposal(title, description, category="general", priority="medium"):
    """
    Create a new improvement proposal (for Quality Assurance, Engineering agents)

    Args:
        title: Proposal title
        description: Detailed description of the improvement
        category: Category (general, bug_fix, feature, refactor, etc.)
        priority: Priority level (low, medium, high, critical)

    Returns:
        {
            'success': bool,
            'proposal_id': int,
            'message': str
        }
    """
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, description, category, priority, status, proposed_at)
            VALUES (%s, %s, %s, %s, 'pending', NOW())
            RETURNING id
        """,
            (title, description, category, priority),
        )

        proposal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "proposal_id": proposal_id,
            "message": f"Created improvement proposal #{proposal_id}: {title}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def query_database(query, description=None):
    """
    Execute a SAFE read-only database query (SELECT only)

    Args:
        query: SQL query (SELECT only)
        description: Optional description of what you're querying for

    Returns:
        {
            'success': bool,
            'rows': list,
            'count': int
        }
    """
    try:
        # Safety check: only allow SELECT queries
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT"):
            return {
                "success": False,
                "error": "Only SELECT queries allowed. Use create_improvement_proposal for changes.",
            }

        # Block dangerous keywords
        dangerous_keywords = [
            "DROP",
            "DELETE",
            "UPDATE",
            "INSERT",
            "ALTER",
            "TRUNCATE",
            "CREATE",
        ]
        if any(keyword in query_upper for keyword in dangerous_keywords):
            return {
                "success": False,
                "error": "Query contains dangerous keywords. Only SELECT allowed.",
            }

        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(query)
        rows = cur.fetchall()

        cur.close()
        conn.close()

        return {
            "success": True,
            "rows": [dict(r) for r in rows],
            "count": len(rows),
            "query": query,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def search_documentation(search_term, doc_type=None):
    """
    Search through A.R.C.H.I.E.'s documentation

    Args:
        search_term: Term to search for
        doc_type: Optional filter (api, guide, architecture, etc.)

    Returns:
        {
            'success': bool,
            'results': list of matching docs
        }
    """
    try:
        docs_path = "/mnt/archie_brain/docs"
        results = []

        if not os.path.exists(docs_path):
            return {"success": False, "error": "Documentation directory not found"}

        # Simple file search
        for root, dirs, files in os.walk(docs_path):
            for file in files:
                if file.endswith(".md") or file.endswith(".txt"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r") as f:
                            content = f.read()
                            if search_term.lower() in content.lower():
                                results.append(
                                    {
                                        "file": file,
                                        "path": file_path,
                                        "excerpt": content[:200] + "...",
                                    }
                                )
                    except Exception as e:
                        logger.debug("archie_tools search: skipped file %s — %s", file_path, e)
                        continue

        return {
            "success": True,
            "results": results[:10],  # Limit to 10 results
            "count": len(results),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


AVAILABLE_TOOLS = {
    # File operations
    "read_file": read_file,
    "edit_file": edit_file,
    "write_file": write_file,
    "list_files": list_files,
    "search_code": search_code,
    # Git operations
    "git_diff": git_diff,
    "git_status": git_status,
    # Analysis
    "analyze_file": analyze_file,
    # Knowledge & Learning
    "query_knowledge": query_knowledge,
    "add_knowledge": add_knowledge,
    "learn_from_file": learn_from_file,
    # Agent-specific tools
    "create_improvement_proposal": create_improvement_proposal,
    "query_database": query_database,
    "search_documentation": search_documentation,
}


def execute_tool(tool_name, **kwargs):
    """
    Execute a tool by name with arguments

    Args:
        tool_name: Name of the tool to execute
        **kwargs: Tool arguments

    Returns:
        Tool execution result
    """
    if tool_name not in AVAILABLE_TOOLS:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(AVAILABLE_TOOLS.keys()),
        }

    try:
        tool_func = AVAILABLE_TOOLS[tool_name]
        result = tool_func(**kwargs)
        result["tool"] = tool_name
        result["args"] = kwargs
        return result

    except Exception as e:
        return {
            "success": False,
            "error": f"Tool execution error: {str(e)}",
            "tool": tool_name,
        }


def get_tool_description(tool_name):
    """Get description of a tool"""
    descriptions = {
        # File operations
        "read_file": "Read contents of a file. Args: path, start_line (optional), end_line (optional)",
        "edit_file": "SAFELY edit a file by replacing specific content (PREFERRED over write_file). Args: path, old_content, new_content. Returns diff showing changes.",
        "write_file": "Write entire file content (DANGEROUS - use edit_file instead). Args: path, content, create_backup (default: True)",
        "list_files": "List files in a directory. Args: directory, pattern (default: *), recursive (default: False)",
        "search_code": "Search for code patterns in codebase. Args: pattern, directory (optional), file_pattern (default: *.py), max_results (default: 50)",
        # Git operations
        "git_diff": "Show git diff. Args: path (optional, None for entire repo)",
        "git_status": "Get git status of repository. No args.",
        # Analysis
        "analyze_file": "Analyze a Python file for structure and potential improvements. Args: path",
        # Knowledge & Learning
        "query_knowledge": "Query YOUR OWN knowledge base about your codebase. Use this to remember what you learned before! Args: search_term, knowledge_type (optional), limit (default: 10)",
        "add_knowledge": "Add new knowledge about your codebase to YOUR knowledge base. Use this to remember things! Args: entity_name, knowledge_type, description, file_path (optional), purpose (optional), importance (0-1)",
        "learn_from_file": "Analyze a file and automatically add it to YOUR knowledge base. Args: file_path",
        # Agent-specific tools
        "create_improvement_proposal": "Create a new improvement proposal in the system. Args: title, description, category (default: general), priority (default: medium)",
        "query_database": "Execute a read-only SELECT query on the database. Args: query, description (optional). Only SELECT allowed for safety.",
        "search_documentation": "Search through A.R.C.H.I.E. documentation. Args: search_term, doc_type (optional)",
    }
    return descriptions.get(tool_name, "No description available")


def list_available_tools():
    """Get list of all available tools with descriptions"""
    return {tool: get_tool_description(tool) for tool in AVAILABLE_TOOLS.keys()}
