"""
Testing Suite Routes
Automated regression testing with test discovery, execution, and reporting

Features:
- Test discovery across codebase
- Automated test execution with live progress
- Test history and trends
- Performance benchmarking
- Integration with sandbox testing

Author: A.R.C.H.I.E.
Date: 2026-01-19
"""
from flask import render_template, jsonify, request, session
from flask_login import login_required, current_user
from . import testing_suite_bp
import os
import sys
import json
import subprocess
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import glob as glob_module
import re

logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

try:
    from rbac import admin_required
except ImportError:
    def admin_required(f):
        return f

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


# In-memory test run tracking
active_test_runs = {}
BASE_PATH = '/mnt/archie_brain'


# ============== Page Routes ==============

@testing_suite_bp.route('/')
@login_required
@admin_required
def index():
    """Testing Suite dashboard"""
    return render_template('tools/testing_suite.html')


@testing_suite_bp.route('/api/status')
def status():
    """API status endpoint"""
    return jsonify({
        'module': 'testing_suite',
        'status': 'operational',
        'healthy': True,
        'version': '1.0.0',
        'features': {
            'test_discovery': True,
            'regression_testing': True,
            'performance_benchmarks': True,
            'test_history': True
        },
        'active_runs': len(active_test_runs)
    })


# ============== Test Discovery ==============

@testing_suite_bp.route('/api/discover')
@login_required
@admin_required
def discover_tests():
    """
    Discover all test files in the codebase

    Returns categorized test files by type
    """
    try:
        discovered = {
            'python': [],
            'javascript': [],
            'shell': [],
            'total': 0
        }

        # Python test files
        python_patterns = [
            f'{BASE_PATH}/**/test_*.py',
            f'{BASE_PATH}/**/*_test.py',
            f'{BASE_PATH}/**/tests/*.py'
        ]
        for pattern in python_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if 'backups' not in path and '__pycache__' not in path:
                    rel_path = path.replace(BASE_PATH + '/', '')
                    if rel_path not in [t['path'] for t in discovered['python']]:
                        test_info = _analyze_test_file(path, 'python')
                        discovered['python'].append(test_info)

        # JavaScript test files
        js_patterns = [
            f'{BASE_PATH}/**/*.test.js',
            f'{BASE_PATH}/**/*.spec.js',
            f'{BASE_PATH}/**/tests/*.js'
        ]
        for pattern in js_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if 'backups' not in path and 'node_modules' not in path:
                    rel_path = path.replace(BASE_PATH + '/', '')
                    if rel_path not in [t['path'] for t in discovered['javascript']]:
                        test_info = _analyze_test_file(path, 'javascript')
                        discovered['javascript'].append(test_info)

        # Shell test scripts
        shell_patterns = [
            f'{BASE_PATH}/**/test*.sh',
            f'{BASE_PATH}/**/run_tests.sh'
        ]
        for pattern in shell_patterns:
            for path in glob_module.glob(pattern, recursive=True):
                if 'backups' not in path:
                    rel_path = path.replace(BASE_PATH + '/', '')
                    if rel_path not in [t['path'] for t in discovered['shell']]:
                        test_info = _analyze_test_file(path, 'shell')
                        discovered['shell'].append(test_info)

        discovered['total'] = (
            len(discovered['python']) +
            len(discovered['javascript']) +
            len(discovered['shell'])
        )

        return jsonify({
            'success': True,
            'tests': discovered
        })

    except Exception as e:
        logger.error(f"Test discovery error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _analyze_test_file(path: str, language: str) -> Dict:
    """Analyze a test file to extract test information"""
    rel_path = path.replace(BASE_PATH + '/', '')
    info = {
        'path': rel_path,
        'full_path': path,
        'language': language,
        'name': os.path.basename(path),
        'test_count': 0,
        'last_modified': None
    }

    try:
        # Get last modified time
        stat = os.stat(path)
        info['last_modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Count tests
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        if language == 'python':
            # Count def test_ functions
            info['test_count'] = len(re.findall(r'def\s+test_\w+', content))
        elif language == 'javascript':
            # Count it() or test() calls
            info['test_count'] = len(re.findall(r'(it|test)\s*\(', content))
        elif language == 'shell':
            # Count @test annotations or test functions
            info['test_count'] = len(re.findall(r'(^test_|@test)', content, re.MULTILINE))

    except Exception as e:
        logger.warning(f"Failed to analyze {path}: {e}")

    return info


# ============== Test Suites ==============

@testing_suite_bp.route('/api/suites')
@login_required
@admin_required
def get_test_suites():
    """Get configured test suites"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, name, description, test_type, test_command,
                   timeout_seconds, required, enabled, created_at
            FROM sandbox_test_suites
            ORDER BY required DESC, name
        """)
        suites = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'suites': [dict(s) for s in suites]
        })

    except Exception as e:
        logger.error(f"Get suites error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/suites', methods=['POST'])
@login_required
@admin_required
def create_test_suite():
    """Create a new test suite"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        data = request.get_json() or {}

        name = data.get('name')
        description = data.get('description', '')
        test_type = data.get('test_type', 'custom')
        test_command = data.get('test_command')
        timeout = data.get('timeout_seconds', 300)
        required = data.get('required', False)

        if not name or not test_command:
            return jsonify({
                'success': False,
                'error': 'name and test_command are required'
            }), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO sandbox_test_suites
            (name, description, test_type, test_command, timeout_seconds, required, enabled)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            RETURNING *
        """, (name, description, test_type, test_command, timeout, required))

        suite = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'suite': dict(suite)
        })

    except Exception as e:
        logger.error(f"Create suite error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/suites/<int:suite_id>', methods=['PUT'])
@login_required
@admin_required
def update_test_suite(suite_id):
    """Update a test suite"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        data = request.get_json() or {}

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updates = []
        values = []

        for field in ['name', 'description', 'test_type', 'test_command', 'timeout_seconds', 'required', 'enabled']:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        values.append(suite_id)

        cur.execute(f"""
            UPDATE sandbox_test_suites
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """, values)

        suite = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if suite:
            return jsonify({'success': True, 'suite': dict(suite)})
        return jsonify({'success': False, 'error': 'Suite not found'}), 404

    except Exception as e:
        logger.error(f"Update suite error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/suites/<int:suite_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_test_suite(suite_id):
    """Delete a test suite"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("DELETE FROM sandbox_test_suites WHERE id = %s", (suite_id,))
        deleted = cur.rowcount > 0

        conn.commit()
        cur.close()
        conn.close()

        if deleted:
            return jsonify({'success': True, 'message': 'Suite deleted'})
        return jsonify({'success': False, 'error': 'Suite not found'}), 404

    except Exception as e:
        logger.error(f"Delete suite error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== Test Execution ==============

@testing_suite_bp.route('/api/run', methods=['POST'])
@login_required
@admin_required
def run_tests():
    """
    Run tests

    POST body:
    {
        "type": "suite" | "file" | "all" | "regression",
        "suite_id": int (for suite type),
        "file_path": str (for file type),
        "timeout": int (optional, default 300)
    }
    """
    try:
        data = request.get_json() or {}
        run_type = data.get('type', 'all')
        timeout = data.get('timeout', 300)

        # Generate run ID
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"

        # Create run record
        run_info = {
            'id': run_id,
            'type': run_type,
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'tests': [],
            'summary': {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'errors': 0
            }
        }
        active_test_runs[run_id] = run_info

        # Start test execution in background
        if run_type == 'suite':
            suite_id = data.get('suite_id')
            if not suite_id:
                return jsonify({'success': False, 'error': 'suite_id required'}), 400
            thread = threading.Thread(
                target=_run_suite_tests,
                args=(run_id, suite_id, timeout)
            )
        elif run_type == 'file':
            file_path = data.get('file_path')
            if not file_path:
                return jsonify({'success': False, 'error': 'file_path required'}), 400
            thread = threading.Thread(
                target=_run_file_tests,
                args=(run_id, file_path, timeout)
            )
        elif run_type == 'regression':
            thread = threading.Thread(
                target=_run_regression_tests,
                args=(run_id, timeout)
            )
        else:  # 'all'
            thread = threading.Thread(
                target=_run_all_tests,
                args=(run_id, timeout)
            )

        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'run_id': run_id,
            'message': 'Test run started'
        })

    except Exception as e:
        logger.error(f"Run tests error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/run/<run_id>')
@login_required
@admin_required
def get_run_status(run_id):
    """Get status of a test run"""
    if run_id in active_test_runs:
        return jsonify({
            'success': True,
            'run': active_test_runs[run_id]
        })
    return jsonify({'success': False, 'error': 'Run not found'}), 404


@testing_suite_bp.route('/api/run/<run_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_run(run_id):
    """Cancel a running test"""
    if run_id in active_test_runs:
        active_test_runs[run_id]['status'] = 'cancelled'
        return jsonify({'success': True, 'message': 'Run cancelled'})
    return jsonify({'success': False, 'error': 'Run not found'}), 404


def _run_suite_tests(run_id: str, suite_id: int, timeout: int):
    """Execute tests for a specific suite"""
    run = active_test_runs[run_id]

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM sandbox_test_suites WHERE id = %s", (suite_id,))
        suite = cur.fetchone()

        if not suite:
            run['status'] = 'failed'
            run['error'] = 'Suite not found'
            return

        result = _execute_test_command(
            suite['test_command'],
            suite['timeout_seconds'] or timeout
        )

        run['tests'].append({
            'name': suite['name'],
            'type': suite['test_type'],
            'status': 'passed' if result['exit_code'] == 0 else 'failed',
            'duration_ms': result['duration_ms'],
            'output': result['output'][:5000],
            'error': result['error'][:1000] if result['error'] else None
        })

        run['summary']['total'] = 1
        if result['exit_code'] == 0:
            run['summary']['passed'] = 1
        else:
            run['summary']['failed'] = 1

        run['status'] = 'completed'
        run['completed_at'] = datetime.now().isoformat()

        # Save to database
        _save_test_run(run_id, run)

        cur.close()
        conn.close()

    except Exception as e:
        run['status'] = 'failed'
        run['error'] = str(e)
        logger.error(f"Suite test error: {e}")


def _run_file_tests(run_id: str, file_path: str, timeout: int):
    """Execute tests for a specific file"""
    run = active_test_runs[run_id]

    try:
        full_path = os.path.join(BASE_PATH, file_path) if not file_path.startswith('/') else file_path

        if not os.path.exists(full_path):
            run['status'] = 'failed'
            run['error'] = f'File not found: {file_path}'
            return

        # Detect test framework and build command
        ext = os.path.splitext(full_path)[1].lower()
        if ext == '.py':
            command = f"cd {BASE_PATH} && python3 -m pytest {full_path} -v --tb=short"
        elif ext == '.js':
            command = f"cd {BASE_PATH} && npm test -- {full_path}"
        elif ext == '.sh':
            command = f"bash {full_path}"
        else:
            command = f"python3 {full_path}"

        result = _execute_test_command(command, timeout)

        run['tests'].append({
            'name': os.path.basename(file_path),
            'type': 'file',
            'file_path': file_path,
            'status': 'passed' if result['exit_code'] == 0 else 'failed',
            'duration_ms': result['duration_ms'],
            'output': result['output'][:5000],
            'error': result['error'][:1000] if result['error'] else None
        })

        run['summary']['total'] = 1
        if result['exit_code'] == 0:
            run['summary']['passed'] = 1
        else:
            run['summary']['failed'] = 1

        run['status'] = 'completed'
        run['completed_at'] = datetime.now().isoformat()

        _save_test_run(run_id, run)

    except Exception as e:
        run['status'] = 'failed'
        run['error'] = str(e)
        logger.error(f"File test error: {e}")


def _run_regression_tests(run_id: str, timeout: int):
    """Execute all regression test suites"""
    run = active_test_runs[run_id]

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all enabled, required test suites
        cur.execute("""
            SELECT * FROM sandbox_test_suites
            WHERE enabled = TRUE AND required = TRUE
            ORDER BY name
        """)
        suites = cur.fetchall()

        for suite in suites:
            if run.get('status') == 'cancelled':
                break

            result = _execute_test_command(
                suite['test_command'],
                suite['timeout_seconds'] or timeout
            )

            test_result = {
                'name': suite['name'],
                'type': suite['test_type'],
                'suite_id': suite['id'],
                'status': 'passed' if result['exit_code'] == 0 else 'failed',
                'duration_ms': result['duration_ms'],
                'output': result['output'][:2000],
                'error': result['error'][:500] if result['error'] else None
            }

            run['tests'].append(test_result)
            run['summary']['total'] += 1

            if result['exit_code'] == 0:
                run['summary']['passed'] += 1
            else:
                run['summary']['failed'] += 1

        run['status'] = 'completed' if run.get('status') != 'cancelled' else 'cancelled'
        run['completed_at'] = datetime.now().isoformat()

        _save_test_run(run_id, run)

        cur.close()
        conn.close()

    except Exception as e:
        run['status'] = 'failed'
        run['error'] = str(e)
        logger.error(f"Regression test error: {e}")


def _run_all_tests(run_id: str, timeout: int):
    """Execute all test suites"""
    run = active_test_runs[run_id]

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT * FROM sandbox_test_suites
            WHERE enabled = TRUE
            ORDER BY required DESC, name
        """)
        suites = cur.fetchall()

        for suite in suites:
            if run.get('status') == 'cancelled':
                break

            result = _execute_test_command(
                suite['test_command'],
                suite['timeout_seconds'] or timeout
            )

            test_result = {
                'name': suite['name'],
                'type': suite['test_type'],
                'suite_id': suite['id'],
                'required': suite['required'],
                'status': 'passed' if result['exit_code'] == 0 else 'failed',
                'duration_ms': result['duration_ms'],
                'output': result['output'][:2000],
                'error': result['error'][:500] if result['error'] else None
            }

            run['tests'].append(test_result)
            run['summary']['total'] += 1

            if result['exit_code'] == 0:
                run['summary']['passed'] += 1
            else:
                run['summary']['failed'] += 1

        run['status'] = 'completed' if run.get('status') != 'cancelled' else 'cancelled'
        run['completed_at'] = datetime.now().isoformat()

        _save_test_run(run_id, run)

        cur.close()
        conn.close()

    except Exception as e:
        run['status'] = 'failed'
        run['error'] = str(e)
        logger.error(f"All tests error: {e}")


def _execute_test_command(command: str, timeout: int) -> Dict:
    """Execute a test command and return results"""
    start_time = time.time()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE_PATH
        )

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            'exit_code': result.returncode,
            'output': result.stdout,
            'error': result.stderr,
            'duration_ms': duration_ms
        }

    except subprocess.TimeoutExpired:
        return {
            'exit_code': -1,
            'output': '',
            'error': f'Command timed out after {timeout} seconds',
            'duration_ms': timeout * 1000
        }
    except Exception as e:
        return {
            'exit_code': -1,
            'output': '',
            'error': str(e),
            'duration_ms': int((time.time() - start_time) * 1000)
        }


def _save_test_run(run_id: str, run: Dict):
    """Save test run to database"""
    if not DB_AVAILABLE:
        return

    try:
        conn = get_db()
        cur = conn.cursor()

        # Ensure table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                id VARCHAR(100) PRIMARY KEY,
                run_type VARCHAR(50),
                status VARCHAR(50),
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                summary JSONB,
                results JSONB,
                error TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            INSERT INTO test_runs (id, run_type, status, started_at, completed_at, summary, results, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET status = %s, completed_at = %s, summary = %s, results = %s, error = %s
        """, (
            run_id,
            run.get('type'),
            run.get('status'),
            run.get('started_at'),
            run.get('completed_at'),
            json.dumps(run.get('summary', {})),
            json.dumps(run.get('tests', [])),
            run.get('error'),
            run.get('status'),
            run.get('completed_at'),
            json.dumps(run.get('summary', {})),
            json.dumps(run.get('tests', [])),
            run.get('error')
        ))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logger.warning(f"Failed to save test run: {e}")


# ============== Test History ==============

@testing_suite_bp.route('/api/history')
@login_required
@admin_required
def get_test_history():
    """Get test run history"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, run_type, status, started_at, completed_at, summary, error
            FROM test_runs
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

        runs = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM test_runs")
        total = cur.fetchone()['count']

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'runs': [dict(r) for r in runs],
            'total': total
        })

    except Exception as e:
        logger.error(f"Get history error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/history/<run_id>')
@login_required
@admin_required
def get_run_details(run_id):
    """Get detailed results for a test run"""
    # Check active runs first
    if run_id in active_test_runs:
        return jsonify({
            'success': True,
            'run': active_test_runs[run_id]
        })

    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT * FROM test_runs WHERE id = %s
        """, (run_id,))

        run = cur.fetchone()

        cur.close()
        conn.close()

        if run:
            return jsonify({
                'success': True,
                'run': dict(run)
            })
        return jsonify({'success': False, 'error': 'Run not found'}), 404

    except Exception as e:
        logger.error(f"Get run details error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@testing_suite_bp.route('/api/trends')
@login_required
@admin_required
def get_test_trends():
    """Get test result trends over time"""
    if not DB_AVAILABLE:
        return jsonify({'success': False, 'error': 'Database not available'}), 500

    try:
        days = request.args.get('days', 30, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                DATE(started_at) as date,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                AVG((summary->>'passed')::int) as avg_passed,
                AVG((summary->>'failed')::int) as avg_failed
            FROM test_runs
            WHERE started_at >= NOW() - INTERVAL '%s days'
            GROUP BY DATE(started_at)
            ORDER BY date
        """, (days,))

        trends = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'trends': [dict(t) for t in trends]
        })

    except Exception as e:
        logger.error(f"Get trends error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== Performance Benchmarks ==============

@testing_suite_bp.route('/api/benchmark', methods=['POST'])
@login_required
@admin_required
def run_benchmark():
    """
    Run performance benchmark

    POST body:
    {
        "type": "api" | "database" | "module",
        "target": str (endpoint or module name),
        "iterations": int (default 10)
    }
    """
    try:
        data = request.get_json() or {}
        bench_type = data.get('type', 'api')
        target = data.get('target', '/')
        iterations = min(data.get('iterations', 10), 100)

        results = {
            'type': bench_type,
            'target': target,
            'iterations': iterations,
            'timings': [],
            'summary': {}
        }

        if bench_type == 'api':
            results = _benchmark_api(target, iterations)
        elif bench_type == 'database':
            results = _benchmark_database(iterations)
        elif bench_type == 'module':
            results = _benchmark_module(target, iterations)

        return jsonify({
            'success': True,
            'benchmark': results
        })

    except Exception as e:
        logger.error(f"Benchmark error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _benchmark_api(endpoint: str, iterations: int) -> Dict:
    """Benchmark API endpoint response times"""
    import requests as req

    timings = []
    base_url = 'http://localhost:3000'

    for i in range(iterations):
        start = time.time()
        try:
            response = req.get(f"{base_url}{endpoint}", timeout=30)
            duration = (time.time() - start) * 1000
            timings.append({
                'iteration': i + 1,
                'duration_ms': round(duration, 2),
                'status': response.status_code
            })
        except Exception as e:
            timings.append({
                'iteration': i + 1,
                'duration_ms': 0,
                'status': 'error',
                'error': str(e)
            })

    valid_timings = [t['duration_ms'] for t in timings if t.get('status') != 'error']

    return {
        'type': 'api',
        'target': endpoint,
        'iterations': iterations,
        'timings': timings,
        'summary': {
            'min_ms': min(valid_timings) if valid_timings else 0,
            'max_ms': max(valid_timings) if valid_timings else 0,
            'avg_ms': round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            'errors': len([t for t in timings if t.get('status') == 'error'])
        }
    }


def _benchmark_database(iterations: int) -> Dict:
    """Benchmark database query performance"""
    timings = []

    for i in range(iterations):
        start = time.time()
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM knowledge_base")
            cur.fetchone()
            cur.close()
            conn.close()
            duration = (time.time() - start) * 1000
            timings.append({
                'iteration': i + 1,
                'duration_ms': round(duration, 2),
                'status': 'ok'
            })
        except Exception as e:
            timings.append({
                'iteration': i + 1,
                'duration_ms': 0,
                'status': 'error',
                'error': str(e)
            })

    valid_timings = [t['duration_ms'] for t in timings if t.get('status') != 'error']

    return {
        'type': 'database',
        'target': 'knowledge_base',
        'iterations': iterations,
        'timings': timings,
        'summary': {
            'min_ms': min(valid_timings) if valid_timings else 0,
            'max_ms': max(valid_timings) if valid_timings else 0,
            'avg_ms': round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            'errors': len([t for t in timings if t.get('status') == 'error'])
        }
    }


def _benchmark_module(module_name: str, iterations: int) -> Dict:
    """Benchmark module health check performance"""
    import requests as req

    timings = []
    base_url = 'http://localhost:3000'

    for i in range(iterations):
        start = time.time()
        try:
            response = req.get(f"{base_url}/tools/{module_name}/api/status", timeout=30)
            duration = (time.time() - start) * 1000
            timings.append({
                'iteration': i + 1,
                'duration_ms': round(duration, 2),
                'status': response.status_code
            })
        except Exception as e:
            timings.append({
                'iteration': i + 1,
                'duration_ms': 0,
                'status': 'error',
                'error': str(e)
            })

    valid_timings = [t['duration_ms'] for t in timings if t.get('status') != 'error']

    return {
        'type': 'module',
        'target': module_name,
        'iterations': iterations,
        'timings': timings,
        'summary': {
            'min_ms': min(valid_timings) if valid_timings else 0,
            'max_ms': max(valid_timings) if valid_timings else 0,
            'avg_ms': round(sum(valid_timings) / len(valid_timings), 2) if valid_timings else 0,
            'errors': len([t for t in timings if t.get('status') == 'error'])
        }
    }
