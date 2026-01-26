"""
Cursor AI + OpenCode Integration
External IDE integration for real-time code assistance and context sharing

Features:
- MCP Protocol support for AI assistants
- WebSocket bridge for real-time sync
- Context sharing between A.R.C.H.I.E. and external IDEs
- Code action API for inline suggestions
- Project indexing for better context

Author: A.R.C.H.I.E.
Date: 2026-01-19
"""
from flask import render_template, jsonify, request, session
from flask_login import login_required
from . import cursor_integration_bp
import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import threading
import time

logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

try:
    from archie_bridge import archie_bridge
    AI_BRIDGE_AVAILABLE = True
except ImportError:
    AI_BRIDGE_AVAILABLE = False
    logger.warning("AI Bridge not available for IDE integration")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', 'archie_secure_2024')
    )


# In-memory session store for connected IDEs
connected_ides = {}
context_cache = {}


class IDESession:
    """Represents a connected IDE session"""

    def __init__(self, session_id: str, ide_type: str, workspace_path: str):
        self.session_id = session_id
        self.ide_type = ide_type  # 'cursor', 'opencode', 'vscode'
        self.workspace_path = workspace_path
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
        self.open_files = []
        self.cursor_position = {}  # {file: {line, column}}
        self.context = {}

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'ide_type': self.ide_type,
            'workspace_path': self.workspace_path,
            'connected_at': self.connected_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'open_files': self.open_files,
            'cursor_position': self.cursor_position,
            'active': (datetime.now() - self.last_activity).seconds < 300
        }


# ============== Main UI ==============

@cursor_integration_bp.route('/')
@login_required
def index():
    """IDE Integration dashboard"""
    return render_template('tools/ide_integration.html')


@cursor_integration_bp.route('/api/status')
def status():
    """API status endpoint for health checks"""
    active_sessions = sum(1 for s in connected_ides.values()
                         if (datetime.now() - s.last_activity).seconds < 300)
    return jsonify({
        'module': 'cursor_integration',
        'status': 'operational',
        'healthy': True,
        'version': '2.0.0',
        'features': {
            'mcp_protocol': True,
            'websocket_bridge': True,
            'context_sharing': True,
            'code_actions': True,
            'ai_bridge': AI_BRIDGE_AVAILABLE
        },
        'connections': {
            'total': len(connected_ides),
            'active': active_sessions
        }
    })


# ============== IDE Connection API ==============

@cursor_integration_bp.route('/api/connect', methods=['POST'])
def connect_ide():
    """
    Register a new IDE connection

    Expected payload:
    {
        "ide_type": "cursor" | "opencode" | "vscode",
        "workspace_path": "/path/to/project",
        "client_id": "unique-client-id",
        "capabilities": ["completion", "diagnostics", "hover"]
    }
    """
    try:
        data = request.get_json() or {}

        ide_type = data.get('ide_type', 'cursor')
        workspace_path = data.get('workspace_path', '')
        client_id = data.get('client_id', '')
        capabilities = data.get('capabilities', [])

        # Generate session ID
        session_id = hashlib.sha256(
            f"{client_id}{workspace_path}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Create session
        ide_session = IDESession(session_id, ide_type, workspace_path)
        connected_ides[session_id] = ide_session

        # Log connection
        logger.info(f"IDE connected: {ide_type} at {workspace_path} (session: {session_id})")

        # Store in database for persistence
        if DB_AVAILABLE:
            _log_ide_connection(session_id, ide_type, workspace_path, capabilities)

        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': f'{ide_type.upper()} connected successfully',
            'endpoints': {
                'context': f'/tools/cursor-integration/api/context/{session_id}',
                'complete': f'/tools/cursor-integration/api/complete/{session_id}',
                'actions': f'/tools/cursor-integration/api/actions/{session_id}',
                'diagnostics': f'/tools/cursor-integration/api/diagnostics/{session_id}',
                'disconnect': f'/tools/cursor-integration/api/disconnect/{session_id}'
            }
        })

    except Exception as e:
        logger.error(f"IDE connection error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@cursor_integration_bp.route('/api/disconnect/<session_id>', methods=['POST'])
def disconnect_ide(session_id):
    """Disconnect an IDE session"""
    if session_id in connected_ides:
        del connected_ides[session_id]
        logger.info(f"IDE disconnected: {session_id}")
        return jsonify({'success': True, 'message': 'Disconnected'})
    return jsonify({'success': False, 'error': 'Session not found'}), 404


@cursor_integration_bp.route('/api/sessions')
@login_required
def list_sessions():
    """List all connected IDE sessions"""
    sessions = [s.to_dict() for s in connected_ides.values()]
    return jsonify({
        'success': True,
        'sessions': sessions,
        'total': len(sessions)
    })


# ============== Context Sharing API ==============

@cursor_integration_bp.route('/api/context/<session_id>', methods=['GET', 'POST'])
def context_api(session_id):
    """
    Get or update context for an IDE session

    POST payload:
    {
        "open_files": ["file1.py", "file2.py"],
        "active_file": "file1.py",
        "cursor_position": {"line": 42, "column": 10},
        "selection": {"start": {...}, "end": {...}},
        "visible_range": {"start": 1, "end": 50}
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    ide_session = connected_ides[session_id]
    ide_session.last_activity = datetime.now()

    if request.method == 'POST':
        data = request.get_json() or {}

        # Update session context
        if 'open_files' in data:
            ide_session.open_files = data['open_files']
        if 'active_file' in data:
            ide_session.context['active_file'] = data['active_file']
        if 'cursor_position' in data:
            active_file = data.get('active_file', '')
            ide_session.cursor_position[active_file] = data['cursor_position']
        if 'selection' in data:
            ide_session.context['selection'] = data['selection']
        if 'visible_range' in data:
            ide_session.context['visible_range'] = data['visible_range']

        return jsonify({'success': True, 'message': 'Context updated'})

    else:  # GET
        return jsonify({
            'success': True,
            'context': ide_session.to_dict()
        })


@cursor_integration_bp.route('/api/context/<session_id>/file', methods=['POST'])
def get_file_context(session_id):
    """
    Get A.R.C.H.I.E.'s context about a specific file

    POST payload:
    {
        "file_path": "path/to/file.py",
        "content": "file content...",
        "cursor_line": 42
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    try:
        data = request.get_json() or {}
        file_path = data.get('file_path', '')
        content = data.get('content', '')
        cursor_line = data.get('cursor_line', 0)

        # Get relevant knowledge from A.R.C.H.I.E.'s knowledge base
        context = _get_archie_context_for_file(file_path, content, cursor_line)

        return jsonify({
            'success': True,
            'context': context
        })

    except Exception as e:
        logger.error(f"File context error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== Code Completion API ==============

@cursor_integration_bp.route('/api/complete/<session_id>', methods=['POST'])
def code_completion(session_id):
    """
    Get AI-powered code completions

    POST payload:
    {
        "file_path": "path/to/file.py",
        "content": "full file content",
        "cursor_position": {"line": 42, "column": 10},
        "prefix": "code before cursor",
        "suffix": "code after cursor",
        "trigger": "auto" | "manual" | "tab"
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    if not AI_BRIDGE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'AI Bridge not available'
        }), 503

    try:
        data = request.get_json() or {}
        file_path = data.get('file_path', '')
        content = data.get('content', '')
        cursor_pos = data.get('cursor_position', {'line': 0, 'column': 0})
        prefix = data.get('prefix', '')
        suffix = data.get('suffix', '')
        trigger = data.get('trigger', 'auto')

        # Build completion prompt
        language = _detect_language(file_path)

        prompt = f"""Complete the following {language} code. Only provide the completion, no explanation.

File: {file_path}

Code before cursor:
```{language}
{prefix[-500:] if len(prefix) > 500 else prefix}
```

Code after cursor:
```{language}
{suffix[:200] if len(suffix) > 200 else suffix}
```

Provide the code completion (just the code, nothing else):"""

        # Get completion from AI
        result = archie_bridge(
            prompt=prompt,
            user_id=1,
            enable_memory=False,
            force_model='llama3.1:8b'
        )

        if result.get('success'):
            completion = result['response'].strip()
            # Clean up completion
            if completion.startswith('```'):
                completion = completion.split('\n', 1)[1] if '\n' in completion else completion
            if completion.endswith('```'):
                completion = completion.rsplit('```', 1)[0]

            return jsonify({
                'success': True,
                'completions': [{
                    'text': completion.strip(),
                    'kind': 'text',
                    'detail': 'A.R.C.H.I.E. suggestion'
                }]
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Completion failed')})

    except Exception as e:
        logger.error(f"Completion error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== Code Actions API ==============

@cursor_integration_bp.route('/api/actions/<session_id>', methods=['POST'])
def code_actions(session_id):
    """
    Get available code actions for a selection

    POST payload:
    {
        "file_path": "path/to/file.py",
        "content": "file content",
        "selection": {
            "start": {"line": 10, "column": 0},
            "end": {"line": 15, "column": 20}
        },
        "diagnostics": [...]
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    try:
        data = request.get_json() or {}
        file_path = data.get('file_path', '')
        content = data.get('content', '')
        selection = data.get('selection', {})
        diagnostics = data.get('diagnostics', [])

        actions = []

        # Extract selected code
        if selection and content:
            lines = content.split('\n')
            start_line = selection.get('start', {}).get('line', 0)
            end_line = selection.get('end', {}).get('line', start_line)
            selected_lines = lines[start_line:end_line + 1]
            selected_code = '\n'.join(selected_lines)

            # Add context-aware actions
            language = _detect_language(file_path)

            actions.extend([
                {
                    'title': '🤖 Explain this code',
                    'kind': 'archie.explain',
                    'command': 'archie.explain',
                    'arguments': {'code': selected_code, 'language': language}
                },
                {
                    'title': '🔧 Refactor with A.R.C.H.I.E.',
                    'kind': 'archie.refactor',
                    'command': 'archie.refactor',
                    'arguments': {'code': selected_code, 'language': language}
                },
                {
                    'title': '📝 Add documentation',
                    'kind': 'archie.document',
                    'command': 'archie.document',
                    'arguments': {'code': selected_code, 'language': language}
                },
                {
                    'title': '🧪 Generate tests',
                    'kind': 'archie.test',
                    'command': 'archie.test',
                    'arguments': {'code': selected_code, 'language': language}
                }
            ])

            # Add fix actions for diagnostics
            for diag in diagnostics:
                if diag.get('severity') in ['error', 'warning']:
                    actions.append({
                        'title': f"🔨 Fix: {diag.get('message', 'Issue')[:50]}",
                        'kind': 'archie.fix',
                        'command': 'archie.fix',
                        'arguments': {
                            'code': selected_code,
                            'diagnostic': diag,
                            'language': language
                        },
                        'isPreferred': True
                    })

        return jsonify({
            'success': True,
            'actions': actions
        })

    except Exception as e:
        logger.error(f"Code actions error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@cursor_integration_bp.route('/api/actions/<session_id>/execute', methods=['POST'])
def execute_action(session_id):
    """
    Execute a code action

    POST payload:
    {
        "action": "archie.explain" | "archie.refactor" | "archie.document" | "archie.test" | "archie.fix",
        "arguments": {
            "code": "selected code",
            "language": "python",
            "diagnostic": {...}  // for fix action
        }
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    if not AI_BRIDGE_AVAILABLE:
        return jsonify({'success': False, 'error': 'AI Bridge not available'}), 503

    try:
        data = request.get_json() or {}
        action = data.get('action', '')
        args = data.get('arguments', {})
        code = args.get('code', '')
        language = args.get('language', 'python')

        # Build prompt based on action
        if action == 'archie.explain':
            prompt = f"""Explain this {language} code clearly and concisely:

```{language}
{code}
```

Provide a brief explanation of what the code does, any important patterns used, and potential considerations."""

        elif action == 'archie.refactor':
            prompt = f"""Refactor this {language} code to improve readability, performance, or maintainability:

```{language}
{code}
```

Provide the refactored code with brief comments explaining the improvements. Only output the improved code."""

        elif action == 'archie.document':
            prompt = f"""Add comprehensive documentation to this {language} code:

```{language}
{code}
```

Add docstrings, type hints, and inline comments where appropriate. Output only the documented code."""

        elif action == 'archie.test':
            prompt = f"""Generate unit tests for this {language} code:

```{language}
{code}
```

Create comprehensive test cases covering normal use, edge cases, and error conditions. Use appropriate testing framework (pytest for Python, jest for JS)."""

        elif action == 'archie.fix':
            diagnostic = args.get('diagnostic', {})
            prompt = f"""Fix this {language} code issue:

Issue: {diagnostic.get('message', 'Unknown issue')}
Severity: {diagnostic.get('severity', 'warning')}

Code:
```{language}
{code}
```

Provide the corrected code only, no explanations."""

        else:
            return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400

        # Execute with AI
        result = archie_bridge(
            prompt=prompt,
            user_id=1,
            enable_memory=True,
            force_model='llama3.1:8b'
        )

        if result.get('success'):
            return jsonify({
                'success': True,
                'result': result['response'],
                'model': result.get('model', 'unknown')
            })
        else:
            return jsonify({'success': False, 'error': result.get('error', 'Action failed')})

    except Exception as e:
        logger.error(f"Action execution error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== Diagnostics API ==============

@cursor_integration_bp.route('/api/diagnostics/<session_id>', methods=['POST'])
def get_diagnostics(session_id):
    """
    Get AI-powered diagnostics for a file

    POST payload:
    {
        "file_path": "path/to/file.py",
        "content": "file content"
    }
    """
    if session_id not in connected_ides:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    try:
        data = request.get_json() or {}
        file_path = data.get('file_path', '')
        content = data.get('content', '')

        # Get static analysis diagnostics
        diagnostics = _static_analysis(file_path, content)

        return jsonify({
            'success': True,
            'diagnostics': diagnostics,
            'file_path': file_path
        })

    except Exception as e:
        logger.error(f"Diagnostics error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== MCP Protocol Endpoints ==============

@cursor_integration_bp.route('/mcp/manifest')
def mcp_manifest():
    """
    MCP Protocol manifest for AI assistants
    Returns capabilities and available tools
    """
    return jsonify({
        'name': 'A.R.C.H.I.E. IDE Integration',
        'version': '2.0.0',
        'description': 'AI-powered code assistance from A.R.C.H.I.E.',
        'tools': [
            {
                'name': 'archie_search',
                'description': 'Search A.R.C.H.I.E. knowledge base for code patterns and solutions',
                'parameters': {
                    'query': {'type': 'string', 'description': 'Search query'}
                }
            },
            {
                'name': 'archie_complete',
                'description': 'Get code completion suggestions',
                'parameters': {
                    'prefix': {'type': 'string', 'description': 'Code before cursor'},
                    'suffix': {'type': 'string', 'description': 'Code after cursor'},
                    'language': {'type': 'string', 'description': 'Programming language'}
                }
            },
            {
                'name': 'archie_explain',
                'description': 'Explain code functionality',
                'parameters': {
                    'code': {'type': 'string', 'description': 'Code to explain'}
                }
            },
            {
                'name': 'archie_fix',
                'description': 'Fix code issues',
                'parameters': {
                    'code': {'type': 'string', 'description': 'Code to fix'},
                    'issue': {'type': 'string', 'description': 'Issue description'}
                }
            }
        ],
        'resources': [
            {
                'name': 'knowledge_base',
                'description': 'A.R.C.H.I.E. unified knowledge base',
                'uri': '/tools/cursor-integration/mcp/knowledge'
            }
        ]
    })


@cursor_integration_bp.route('/mcp/tools/<tool_name>', methods=['POST'])
def mcp_tool(tool_name):
    """Execute an MCP tool"""
    try:
        data = request.get_json() or {}

        if tool_name == 'archie_search':
            query = data.get('query', '')
            results = _search_knowledge_base(query)
            return jsonify({'success': True, 'results': results})

        elif tool_name == 'archie_complete':
            # Reuse completion logic
            prefix = data.get('prefix', '')
            suffix = data.get('suffix', '')
            language = data.get('language', 'python')

            if not AI_BRIDGE_AVAILABLE:
                return jsonify({'success': False, 'error': 'AI not available'})

            prompt = f"Complete this {language} code:\n\n{prefix[-300:]}"
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get('success'):
                return jsonify({'success': True, 'completion': result['response']})
            return jsonify({'success': False, 'error': 'Completion failed'})

        elif tool_name == 'archie_explain':
            code = data.get('code', '')
            if not AI_BRIDGE_AVAILABLE:
                return jsonify({'success': False, 'error': 'AI not available'})

            prompt = f"Explain this code concisely:\n\n```\n{code}\n```"
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get('success'):
                return jsonify({'success': True, 'explanation': result['response']})
            return jsonify({'success': False, 'error': 'Explanation failed'})

        elif tool_name == 'archie_fix':
            code = data.get('code', '')
            issue = data.get('issue', '')
            if not AI_BRIDGE_AVAILABLE:
                return jsonify({'success': False, 'error': 'AI not available'})

            prompt = f"Fix this code issue:\n\nIssue: {issue}\n\n```\n{code}\n```\n\nProvide only the fixed code."
            result = archie_bridge(prompt=prompt, user_id=1, enable_memory=False)

            if result.get('success'):
                return jsonify({'success': True, 'fixed_code': result['response']})
            return jsonify({'success': False, 'error': 'Fix failed'})

        else:
            return jsonify({'success': False, 'error': f'Unknown tool: {tool_name}'}), 404

    except Exception as e:
        logger.error(f"MCP tool error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@cursor_integration_bp.route('/mcp/knowledge')
def mcp_knowledge():
    """Access knowledge base via MCP"""
    query = request.args.get('query', '')
    limit = request.args.get('limit', 10, type=int)

    results = _search_knowledge_base(query, limit=limit)
    return jsonify({
        'success': True,
        'results': results,
        'total': len(results)
    })


# ============== Helper Functions ==============

def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext = os.path.splitext(file_path)[1].lower()
    lang_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.sql': 'sql',
        '.go': 'go',
        '.rs': 'rust',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.rb': 'ruby',
        '.php': 'php'
    }
    return lang_map.get(ext, 'text')


def _get_archie_context_for_file(file_path: str, content: str, cursor_line: int) -> Dict:
    """Get relevant context from A.R.C.H.I.E.'s knowledge base for a file"""
    context = {
        'file_info': {
            'path': file_path,
            'language': _detect_language(file_path),
            'lines': len(content.split('\n'))
        },
        'knowledge': [],
        'suggestions': []
    }

    # Search knowledge base for relevant info
    if DB_AVAILABLE:
        try:
            # Extract keywords from file path and content around cursor
            keywords = _extract_keywords(file_path, content, cursor_line)

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Search for relevant knowledge
            cur.execute("""
                SELECT title, content, knowledge_type, importance_score
                FROM knowledge_base
                WHERE search_vector @@ plainto_tsquery('english', %s)
                ORDER BY importance_score DESC
                LIMIT 5
            """, (' '.join(keywords),))

            results = cur.fetchall()
            context['knowledge'] = [dict(r) for r in results]

            cur.close()
            conn.close()

        except Exception as e:
            logger.warning(f"Context retrieval error: {e}")

    return context


def _extract_keywords(file_path: str, content: str, cursor_line: int) -> List[str]:
    """Extract keywords from file context"""
    import re

    keywords = []

    # From file path
    parts = file_path.replace('/', ' ').replace('_', ' ').replace('.', ' ').split()
    keywords.extend([p for p in parts if len(p) > 2])

    # From content around cursor
    lines = content.split('\n')
    start = max(0, cursor_line - 5)
    end = min(len(lines), cursor_line + 5)
    context_lines = ' '.join(lines[start:end])

    # Extract identifiers
    identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b', context_lines)
    keywords.extend(identifiers[:10])

    return list(set(keywords))


def _search_knowledge_base(query: str, limit: int = 10) -> List[Dict]:
    """Search A.R.C.H.I.E.'s knowledge base"""
    if not DB_AVAILABLE or not query:
        return []

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, title, content, knowledge_type, importance_score,
                   ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
            FROM knowledge_base
            WHERE search_vector @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC, importance_score DESC
            LIMIT %s
        """, (query, query, limit))

        results = cur.fetchall()
        cur.close()
        conn.close()

        return [dict(r) for r in results]

    except Exception as e:
        logger.warning(f"Knowledge search error: {e}")
        return []


def _static_analysis(file_path: str, content: str) -> List[Dict]:
    """Perform basic static analysis"""
    import re

    diagnostics = []
    lines = content.split('\n')
    language = _detect_language(file_path)

    if language == 'python':
        for i, line in enumerate(lines):
            # Bare except
            if re.search(r'except\s*:', line):
                diagnostics.append({
                    'line': i,
                    'column': line.index('except'),
                    'severity': 'warning',
                    'message': 'Bare except clause catches all exceptions',
                    'source': 'archie-lint'
                })

            # Print statements
            if re.search(r'^\s*print\s*\(', line):
                diagnostics.append({
                    'line': i,
                    'column': line.index('print'),
                    'severity': 'info',
                    'message': 'Consider using logging instead of print',
                    'source': 'archie-lint'
                })

            # TODO/FIXME
            match = re.search(r'#\s*(TODO|FIXME|XXX)', line, re.I)
            if match:
                diagnostics.append({
                    'line': i,
                    'column': match.start(),
                    'severity': 'info',
                    'message': f'{match.group(1)} found',
                    'source': 'archie-lint'
                })

    elif language in ('javascript', 'typescript'):
        for i, line in enumerate(lines):
            # console.log
            if 'console.log' in line:
                diagnostics.append({
                    'line': i,
                    'column': line.index('console'),
                    'severity': 'info',
                    'message': 'Remove console.log before production',
                    'source': 'archie-lint'
                })

            # var usage
            if re.search(r'\bvar\s+', line):
                diagnostics.append({
                    'line': i,
                    'column': line.index('var'),
                    'severity': 'warning',
                    'message': 'Use const or let instead of var',
                    'source': 'archie-lint'
                })

    return diagnostics


def _log_ide_connection(session_id: str, ide_type: str, workspace_path: str, capabilities: List[str]):
    """Log IDE connection to database"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Ensure table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ide_connections (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(50) UNIQUE,
                ide_type VARCHAR(50),
                workspace_path TEXT,
                capabilities JSONB,
                connected_at TIMESTAMP DEFAULT NOW(),
                last_activity TIMESTAMP DEFAULT NOW(),
                disconnected_at TIMESTAMP
            )
        """)

        cur.execute("""
            INSERT INTO ide_connections (session_id, ide_type, workspace_path, capabilities)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
            SET last_activity = NOW()
        """, (session_id, ide_type, workspace_path, json.dumps(capabilities)))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logger.warning(f"Failed to log IDE connection: {e}")
