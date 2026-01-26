"""CodeRabbit Routes - AI-Powered Code Review & Security"""
from flask import render_template, jsonify, request, session
from flask_login import login_required
from . import coderabbit_bp
import os
import re
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain/platform_v2')

# Import Bridge routing functions for proper team member routing
try:
    from ai_bridge.archie_bridge import route_task_to_station, execute_agent_task, get_available_agent_for_station
    BRIDGE_ROUTING_AVAILABLE = True
except ImportError:
    BRIDGE_ROUTING_AVAILABLE = False
    logger.warning("Bridge routing not available, falling back to direct calls")

# GitHub configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
# Multiple repos support - comma-separated in env var or default list
GITHUB_REPOS_ENV = os.getenv('GITHUB_REPOS', '')
GITHUB_REPOS = [r.strip() for r in GITHUB_REPOS_ENV.split(',') if r.strip()] if GITHUB_REPOS_ENV else [
    'KytranKatarn/archie-platform',
    'KytranKatarn/kytranempowerment-site'
]
# Legacy single repo for backwards compatibility
GITHUB_REPO = GITHUB_REPOS[0] if GITHUB_REPOS else 'KytranKatarn/archie-platform'

# Ollama configuration
OLLAMA_PRIMARY = os.getenv('OLLAMA_PRIMARY', '192.168.1.246:11434')
OLLAMA_SECONDARY = os.getenv('OLLAMA_SECONDARY', '192.168.1.245:11434')


def check_ollama_status():
    """Check if Ollama is available and return status"""
    for host in [OLLAMA_PRIMARY, OLLAMA_SECONDARY]:
        try:
            r = requests.get(f'http://{host}/api/tags', timeout=2)
            if r.status_code == 200:
                models = [m['name'] for m in r.json().get('models', [])]
                return {
                    'available': True,
                    'host': host,
                    'models': models[:5],
                    'model_count': len(models)
                }
        except Exception:
            continue
    return {'available': False, 'host': None, 'models': [], 'model_count': 0}


def basic_static_analysis(code_content, file_path):
    """Perform basic static analysis without AI"""
    issues = []
    lines = code_content.split('\n')
    file_ext = os.path.splitext(file_path)[1].lower()

    # Python-specific checks
    if file_ext == '.py':
        for i, line in enumerate(lines, 1):
            # Security: Hardcoded passwords/secrets
            if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', line, re.I):
                if 'getenv' not in line and 'environ' not in line:
                    issues.append({
                        'line': i,
                        'type': 'security',
                        'severity': 'high',
                        'message': 'Potential hardcoded secret detected',
                        'suggestion': 'Use environment variables instead'
                    })

            # Security: SQL injection risk
            if re.search(r'execute\s*\(\s*["\'].*%s|execute\s*\(\s*f["\']', line):
                if 'parameterized' not in line.lower():
                    issues.append({
                        'line': i,
                        'type': 'security',
                        'severity': 'high',
                        'message': 'Potential SQL injection vulnerability',
                        'suggestion': 'Use parameterized queries'
                    })

            # Quality: Bare except
            if re.search(r'except\s*:', line):
                issues.append({
                    'line': i,
                    'type': 'quality',
                    'severity': 'medium',
                    'message': 'Bare except clause catches all exceptions',
                    'suggestion': 'Specify exception type (e.g., except ValueError:)'
                })

            # Quality: TODO/FIXME comments
            if re.search(r'#\s*(TODO|FIXME|XXX|HACK)', line, re.I):
                issues.append({
                    'line': i,
                    'type': 'quality',
                    'severity': 'low',
                    'message': 'TODO/FIXME comment found',
                    'suggestion': 'Address or track this item'
                })

            # Style: Line too long
            if len(line) > 120:
                issues.append({
                    'line': i,
                    'type': 'style',
                    'severity': 'low',
                    'message': f'Line exceeds 120 characters ({len(line)})',
                    'suggestion': 'Break into multiple lines'
                })

            # Performance: Print statements in production code
            if re.search(r'^\s*print\s*\(', line) and 'debug' not in file_path.lower():
                issues.append({
                    'line': i,
                    'type': 'performance',
                    'severity': 'low',
                    'message': 'Print statement found (use logging instead)',
                    'suggestion': 'Replace with logger.info() or logger.debug()'
                })

    # JavaScript/HTML checks
    elif file_ext in ['.js', '.html']:
        for i, line in enumerate(lines, 1):
            # Security: innerHTML usage
            if 'innerHTML' in line and '=' in line:
                issues.append({
                    'line': i,
                    'type': 'security',
                    'severity': 'medium',
                    'message': 'innerHTML usage may be XSS vulnerable',
                    'suggestion': 'Use textContent or sanitize input'
                })

            # Security: eval usage
            if re.search(r'\beval\s*\(', line):
                issues.append({
                    'line': i,
                    'type': 'security',
                    'severity': 'critical',
                    'message': 'eval() is dangerous and should be avoided',
                    'suggestion': 'Use JSON.parse() or safer alternatives'
                })

            # Quality: console.log
            if 'console.log' in line:
                issues.append({
                    'line': i,
                    'type': 'quality',
                    'severity': 'low',
                    'message': 'console.log found',
                    'suggestion': 'Remove or use proper logging'
                })

    # Calculate quality score based on issues
    critical_count = len([i for i in issues if i['severity'] == 'critical'])
    high_count = len([i for i in issues if i['severity'] == 'high'])
    medium_count = len([i for i in issues if i['severity'] == 'medium'])
    low_count = len([i for i in issues if i['severity'] == 'low'])

    # Scoring: start at 100, deduct based on severity
    score = 100 - (critical_count * 25) - (high_count * 15) - (medium_count * 5) - (low_count * 2)
    score = max(0, min(100, score))  # Clamp between 0-100

    return {
        'quality_score': score,
        'issues': issues,
        'summary': f'Static analysis found {len(issues)} issues' if issues else 'No issues found',
        'analysis_type': 'static'
    }

# Database connection
def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


def init_code_health_tables():
    """Initialize code health tracking tables"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS code_scans (
                id SERIAL PRIMARY KEY,
                file_path VARCHAR(500) NOT NULL,
                scan_type VARCHAR(50) DEFAULT 'manual',
                issues_found INTEGER DEFAULT 0,
                security_issues INTEGER DEFAULT 0,
                quality_score DECIMAL(5,2),
                scan_result JSONB,
                scanned_by VARCHAR(100),
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS code_issues (
                id SERIAL PRIMARY KEY,
                scan_id INTEGER REFERENCES code_scans(id),
                file_path VARCHAR(500) NOT NULL,
                line_number INTEGER,
                issue_type VARCHAR(50),
                severity VARCHAR(20),
                message TEXT,
                suggestion TEXT,
                status VARCHAR(20) DEFAULT 'open',
                fixed_by VARCHAR(100),
                fixed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS code_fixes (
                id SERIAL PRIMARY KEY,
                issue_id INTEGER REFERENCES code_issues(id),
                file_path VARCHAR(500) NOT NULL,
                fixed_by VARCHAR(100) NOT NULL,
                fix_description TEXT,
                pr_number INTEGER,
                pr_url VARCHAR(500),
                commit_sha VARCHAR(100),
                fixed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Local PR tracking table for historical data
            CREATE TABLE IF NOT EXISTS pull_requests (
                id SERIAL PRIMARY KEY,
                pr_number INTEGER NOT NULL,
                repo VARCHAR(200) NOT NULL,
                title VARCHAR(500),
                state VARCHAR(20) DEFAULT 'open',
                author VARCHAR(100),
                url VARCHAR(500),
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                merged_at TIMESTAMP,
                closed_at TIMESTAMP,
                additions INTEGER DEFAULT 0,
                deletions INTEGER DEFAULT 0,
                changed_files INTEGER DEFAULT 0,
                labels JSONB,
                metadata JSONB,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(repo, pr_number)
            );

            CREATE INDEX IF NOT EXISTS idx_code_scans_file ON code_scans(file_path);
            CREATE INDEX IF NOT EXISTS idx_code_issues_status ON code_issues(status);
            CREATE INDEX IF NOT EXISTS idx_code_fixes_file ON code_fixes(file_path);
            CREATE INDEX IF NOT EXISTS idx_pull_requests_repo ON pull_requests(repo);
            CREATE INDEX IF NOT EXISTS idx_pull_requests_state ON pull_requests(state);
        """)
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error initializing tables: {e}")
        return False
    finally:
        cur.close()
        conn.close()


# Initialize tables on module load
init_code_health_tables()


@coderabbit_bp.route('/')
def index():
    """Main CodeRabbit dashboard"""
    return render_template('tools/coderabbit.html')


@coderabbit_bp.route('/api/status')
def status():
    """Health check for CodeRabbit module"""
    ai_status = check_ollama_status()
    return jsonify({
        'module': 'coderabbit',
        'status': 'active',
        'healthy': True,
        'message': 'CodeRabbit integration active - reviewing PRs on GitHub',
        'features': {
            'pr_reviews': True,
            'security_scans': True,
            'code_quality': True,
            'best_practices': True,
            'code_health_scanner': True
        },
        'github_repo': GITHUB_REPO,
        'ai_status': ai_status
    })


@coderabbit_bp.route('/api/ai-status')
def ai_status():
    """Check AI/Ollama availability for code scanning"""
    ollama = check_ollama_status()
    return jsonify({
        'ollama': ollama,
        'archie_bridge': {
            'available': True,  # archie_bridge is part of the platform
            'path': '/mnt/archie_brain/ai_bridge'
        },
        'analysis_modes': {
            'ai_powered': ollama['available'],
            'static_analysis': True  # Always available
        },
        'recommended_mode': 'ai_powered' if ollama['available'] else 'static'
    })


@coderabbit_bp.route('/api/config')
def get_config():
    """Get CodeRabbit configuration"""
    return jsonify({
        'configured': True,
        'github_connected': bool(GITHUB_TOKEN),
        'repositories': GITHUB_REPOS,
        'primary_repo': GITHUB_REPO,
        'scan_settings': {
            'auto_review_prs': True,
            'security_scan_enabled': True,
            'code_style_check': True
        }
    })


@coderabbit_bp.route('/api/repos', methods=['GET'])
def get_repos():
    """Get list of configured GitHub repositories"""
    return jsonify({
        'success': True,
        'repositories': GITHUB_REPOS,
        'count': len(GITHUB_REPOS)
    })


@coderabbit_bp.route('/api/repos', methods=['POST'])
@login_required
def add_repo():
    """Add a new GitHub repository to track"""
    global GITHUB_REPOS
    data = request.get_json() or {}
    repo = data.get('repo', '').strip()

    if not repo:
        return jsonify({'error': 'repo is required'}), 400

    # Validate repo format (owner/repo)
    if '/' not in repo or len(repo.split('/')) != 2:
        return jsonify({'error': 'Invalid repo format. Use owner/repo'}), 400

    if repo in GITHUB_REPOS:
        return jsonify({'error': 'Repository already tracked'}), 400

    # Test if repo exists and is accessible
    if GITHUB_TOKEN:
        try:
            headers = {
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            }
            response = requests.get(
                f'https://api.github.com/repos/{repo}',
                headers=headers,
                timeout=10
            )
            if response.status_code == 404:
                return jsonify({'error': 'Repository not found or not accessible'}), 404
            elif response.status_code != 200:
                return jsonify({'error': f'GitHub API error: {response.status_code}'}), 500
        except Exception as e:
            return jsonify({'error': f'Failed to verify repo: {str(e)}'}), 500

    GITHUB_REPOS.append(repo)

    return jsonify({
        'success': True,
        'message': f'Repository {repo} added',
        'repositories': GITHUB_REPOS
    })


@coderabbit_bp.route('/api/repos/<path:repo>', methods=['DELETE'])
@login_required
def remove_repo(repo):
    """Remove a GitHub repository from tracking"""
    global GITHUB_REPOS

    if repo not in GITHUB_REPOS:
        return jsonify({'error': 'Repository not found in tracked list'}), 404

    if len(GITHUB_REPOS) <= 1:
        return jsonify({'error': 'Cannot remove the last repository'}), 400

    GITHUB_REPOS.remove(repo)

    return jsonify({
        'success': True,
        'message': f'Repository {repo} removed',
        'repositories': GITHUB_REPOS
    })


@coderabbit_bp.route('/api/recent-prs')
def get_recent_prs():
    """Get recent pull requests from all configured GitHub repositories"""
    if not GITHUB_TOKEN:
        return jsonify({'error': 'GitHub token not configured'}), 400

    # Get optional repo filter from query params
    repo_filter = request.args.get('repo', None)
    per_repo = request.args.get('per_repo', 10, type=int)

    repos_to_fetch = [repo_filter] if repo_filter else GITHUB_REPOS

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        all_prs = []
        repo_errors = []

        for repo in repos_to_fetch:
            try:
                response = requests.get(
                    f'https://api.github.com/repos/{repo}/pulls?state=all&per_page={per_repo}',
                    headers=headers,
                    timeout=10
                )

                if response.status_code == 200:
                    prs = response.json()
                    for pr in prs:
                        pr_data = {
                            'number': pr['number'],
                            'title': pr['title'],
                            'state': pr['state'],
                            'user': pr['user']['login'],
                            'created_at': pr['created_at'],
                            'url': pr['html_url'],
                            'repo': repo,
                            'repo_short': repo.split('/')[-1],  # Just the repo name
                            'coderabbit_status': 'unknown'  # Will be updated below
                        }

                        # Check for CodeRabbit review comments on this PR
                        try:
                            comments_resp = requests.get(
                                f'https://api.github.com/repos/{repo}/issues/{pr["number"]}/comments',
                                headers=headers,
                                timeout=5
                            )
                            if comments_resp.status_code == 200:
                                comments = comments_resp.json()
                                coderabbit_comments = [
                                    c for c in comments
                                    if 'coderabbit' in c.get('user', {}).get('login', '').lower()
                                ]
                                if coderabbit_comments:
                                    # Check if there's a summary comment (full review)
                                    has_summary = any(
                                        'Summary' in (c.get('body', '') or '')[:500]
                                        for c in coderabbit_comments
                                    )
                                    pr_data['coderabbit_status'] = 'reviewed' if has_summary else 'partial'
                                    pr_data['coderabbit_comments'] = len(coderabbit_comments)
                                else:
                                    pr_data['coderabbit_status'] = 'not_reviewed'
                                    pr_data['coderabbit_comments'] = 0
                        except Exception:
                            pass  # Keep status as unknown on error

                        all_prs.append(pr_data)
                elif response.status_code == 404:
                    repo_errors.append({'repo': repo, 'error': 'Not found or no access'})
                else:
                    repo_errors.append({'repo': repo, 'error': f'HTTP {response.status_code}'})
            except Exception as e:
                repo_errors.append({'repo': repo, 'error': str(e)})

        # Sort all PRs by created_at (newest first)
        all_prs.sort(key=lambda x: x['created_at'], reverse=True)

        return jsonify({
            'success': True,
            'pull_requests': all_prs,
            'total_count': len(all_prs),
            'repositories_fetched': len(repos_to_fetch),
            'errors': repo_errors if repo_errors else None
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@coderabbit_bp.route('/api/webhooks/github', methods=['POST'])
def github_webhook():
    """Handle GitHub webhook events for CodeRabbit integration"""
    event_type = request.headers.get('X-GitHub-Event', 'unknown')
    payload = request.get_json() or {}

    action = payload.get('action', 'none')
    repo = payload.get('repository', {}).get('full_name', 'unknown')

    if event_type == 'pull_request':
        pr_number = payload.get('pull_request', {}).get('number')
        return jsonify({
            'success': True,
            'event': 'pull_request',
            'action': action,
            'pr_number': pr_number,
            'message': f'PR #{pr_number} {action} event received'
        })

    elif event_type == 'push':
        commits = payload.get('commits', [])
        return jsonify({
            'success': True,
            'event': 'push',
            'commits_count': len(commits),
            'message': f'Push with {len(commits)} commits received'
        })

    return jsonify({
        'success': True,
        'event': event_type,
        'action': action,
        'repository': repo,
        'message': 'Webhook received'
    })


@coderabbit_bp.route('/api/stats')
def get_stats():
    """Get CodeRabbit review statistics from all repositories"""
    if not GITHUB_TOKEN:
        return jsonify({'error': 'GitHub token not configured'}), 400

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        total_open = 0
        total_closed = 0
        repo_stats = []

        for repo in GITHUB_REPOS:
            try:
                open_response = requests.get(
                    f'https://api.github.com/repos/{repo}/pulls?state=open&per_page=100',
                    headers=headers,
                    timeout=10
                )
                closed_response = requests.get(
                    f'https://api.github.com/repos/{repo}/pulls?state=closed&per_page=100',
                    headers=headers,
                    timeout=10
                )

                repo_open = len(open_response.json()) if open_response.status_code == 200 else 0
                repo_closed = len(closed_response.json()) if closed_response.status_code == 200 else 0

                total_open += repo_open
                total_closed += repo_closed

                repo_stats.append({
                    'repo': repo,
                    'repo_short': repo.split('/')[-1],
                    'open_prs': repo_open,
                    'closed_prs': repo_closed,
                    'total_prs': repo_open + repo_closed
                })
            except Exception as e:
                repo_stats.append({
                    'repo': repo,
                    'repo_short': repo.split('/')[-1],
                    'error': str(e)
                })

        return jsonify({
            'success': True,
            'repositories': GITHUB_REPOS,
            'repository_count': len(GITHUB_REPOS),
            'statistics': {
                'open_prs': total_open,
                'closed_prs': total_closed,
                'total_prs': total_open + total_closed,
                'coderabbit_enabled': True
            },
            'by_repository': repo_stats
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@coderabbit_bp.route('/api/pr/request-review', methods=['POST'])
@login_required
def request_coderabbit_review():
    """
    Request CodeRabbit to review a PR by posting @coderabbitai review comment.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    repo = data.get('repo')
    pr_number = data.get('pr_number')

    if not repo or not pr_number:
        return jsonify({'success': False, 'error': 'repo and pr_number required'}), 400

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        # Post a comment to trigger CodeRabbit review
        response = requests.post(
            f'https://api.github.com/repos/{repo}/issues/{pr_number}/comments',
            headers=headers,
            json={'body': '@coderabbitai review'},
            timeout=10
        )

        if response.status_code == 201:
            return jsonify({
                'success': True,
                'message': f'Review requested on PR #{pr_number}',
                'comment_url': response.json().get('html_url')
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================
# CODERABBIT REVIEW → IMPROVEMENTS INTEGRATION
# ============================================

@coderabbit_bp.route('/api/pr/<int:pr_number>/review-comments')
@login_required
def get_pr_review_comments(pr_number):
    """
    Fetch CodeRabbit review comments from a PR.
    Parses actionable suggestions that can be sent to Improvements Lab.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    repo = request.args.get('repo', GITHUB_REPOS[0] if GITHUB_REPOS else None)
    if not repo:
        return jsonify({'success': False, 'error': 'No repository specified'}), 400

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        # Get issue comments (where CodeRabbit posts summary)
        comments_resp = requests.get(
            f'https://api.github.com/repos/{repo}/issues/{pr_number}/comments',
            headers=headers,
            timeout=10
        )

        # Get review comments (inline code comments)
        review_comments_resp = requests.get(
            f'https://api.github.com/repos/{repo}/pulls/{pr_number}/comments',
            headers=headers,
            timeout=10
        )

        coderabbit_suggestions = []

        # Parse issue comments for CodeRabbit summary
        if comments_resp.status_code == 200:
            for comment in comments_resp.json():
                if 'coderabbit' in comment.get('user', {}).get('login', '').lower():
                    # Extract actionable items from summary
                    body = comment.get('body', '')
                    suggestions = parse_coderabbit_summary(body, comment['id'])
                    coderabbit_suggestions.extend(suggestions)

        # Parse inline review comments
        if review_comments_resp.status_code == 200:
            for comment in review_comments_resp.json():
                if 'coderabbit' in comment.get('user', {}).get('login', '').lower():
                    coderabbit_suggestions.append({
                        'id': comment['id'],
                        'type': 'inline',
                        'file_path': comment.get('path', ''),
                        'line': comment.get('line') or comment.get('original_line'),
                        'body': comment.get('body', ''),
                        'diff_hunk': comment.get('diff_hunk', ''),
                        'url': comment.get('html_url', ''),
                        'created_at': comment.get('created_at', '')
                    })

        return jsonify({
            'success': True,
            'pr_number': pr_number,
            'repo': repo,
            'suggestions': coderabbit_suggestions,
            'total_count': len(coderabbit_suggestions)
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def parse_coderabbit_summary(body, comment_id):
    """Parse CodeRabbit summary comment to extract actionable suggestions."""
    suggestions = []

    # Look for actionable items in the summary
    # CodeRabbit typically uses patterns like:
    # - "**file.py**: suggestion here"
    # - Sections with file-specific recommendations

    lines = body.split('\n')
    current_file = None

    for line in lines:
        # Match file references like "**path/to/file.py**:" or "`path/to/file.py`:"
        file_match = re.match(r'\*\*`?([^`*]+\.(py|js|html|ts|tsx|jsx|css|sql))`?\*\*:?\s*(.*)', line)
        if file_match:
            current_file = file_match.group(1)
            suggestion_text = file_match.group(3).strip()
            if suggestion_text:
                suggestions.append({
                    'id': f'{comment_id}-{len(suggestions)}',
                    'type': 'summary',
                    'file_path': current_file,
                    'line': None,
                    'body': suggestion_text,
                    'diff_hunk': '',
                    'url': '',
                    'created_at': ''
                })

        # Match bullet points with suggestions
        elif line.strip().startswith(('- ', '* ', '• ')) and current_file:
            suggestion_text = line.strip()[2:].strip()
            if suggestion_text and len(suggestion_text) > 10:
                suggestions.append({
                    'id': f'{comment_id}-{len(suggestions)}',
                    'type': 'summary',
                    'file_path': current_file,
                    'line': None,
                    'body': suggestion_text,
                    'diff_hunk': '',
                    'url': '',
                    'created_at': ''
                })

    return suggestions


@coderabbit_bp.route('/api/pr/suggestions-to-improvements', methods=['POST'])
@login_required
def send_pr_suggestions_to_improvements():
    """
    Send CodeRabbit PR suggestions to Improvements Lab as proposals.
    Creates proposals linked to the source PR.
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    pr_number = data.get('pr_number')
    pr_url = data.get('pr_url')
    repo = data.get('repo', GITHUB_REPOS[0] if GITHUB_REPOS else '')
    suggestions = data.get('suggestions', [])

    if not suggestions:
        return jsonify({'success': False, 'error': 'No suggestions provided'}), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        created_proposals = []

        for suggestion in suggestions:
            file_path = suggestion.get('file_path', 'unknown')
            body = suggestion.get('body', '')
            line = suggestion.get('line')
            suggestion_type = suggestion.get('type', 'review')

            # Determine category based on content
            category = 'code_quality'
            if any(word in body.lower() for word in ['security', 'injection', 'xss', 'vulnerability']):
                category = 'security'
            elif any(word in body.lower() for word in ['performance', 'slow', 'optimize', 'cache']):
                category = 'performance'
            elif any(word in body.lower() for word in ['bug', 'fix', 'error', 'crash']):
                category = 'bug_fix'

            # Create proposal title
            title = f"[CodeRabbit] {body[:80]}..." if len(body) > 80 else f"[CodeRabbit] {body}"

            # Create proposal description with PR context
            description = f"""## CodeRabbit Review Suggestion

**Source PR:** [{repo}#{pr_number}]({pr_url})
**File:** `{file_path}`
{f'**Line:** {line}' if line else ''}

### Suggestion
{body}

---
*Auto-imported from CodeRabbit review on PR #{pr_number}*
"""

            # First, create a code_issue entry for tracking (unified feedback loop)
            cur.execute("""
                INSERT INTO code_issues
                (scan_id, file_path, line_number, issue_type, severity, message, suggestion, status)
                VALUES (NULL, %s, %s, %s, %s, %s, %s, 'open')
                RETURNING id
            """, (
                file_path,
                line,
                'pr_review',  # Special type for PR reviews
                'medium',
                f"[PR #{pr_number}] {body[:200]}",
                body
            ))
            issue_result = cur.fetchone()
            issue_id = issue_result['id'] if issue_result else None

            # Create metadata for tracking (now includes issue_id for feedback loop)
            metadata = {
                'source': 'coderabbit_review',
                'issue_id': issue_id,  # Link to code_issues for feedback loop
                'pr_number': pr_number,
                'pr_url': pr_url,
                'repo': repo,
                'file_path': file_path,
                'line_number': line,
                'suggestion_type': suggestion_type,
                'original_comment_id': suggestion.get('id')
            }

            # Insert proposal
            cur.execute("""
                INSERT INTO improvement_proposals
                (title, description, category, priority, status, metadata, proposed_at)
                VALUES (%s, %s, %s, %s, 'proposed', %s, NOW())
                RETURNING id, title, category, status
            """, (
                title,
                description,
                category,
                'medium',
                json.dumps(metadata)
            ))
            proposal = cur.fetchone()

            # Update code_issue with proposal_id link
            if issue_id:
                cur.execute("""
                    UPDATE code_issues
                    SET proposal_id = %s, status = 'sent_to_improvements'
                    WHERE id = %s
                """, (proposal['id'], issue_id))

            created_proposals.append(dict(proposal))

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'{len(created_proposals)} proposal(s) created from PR review',
            'proposals': created_proposals,
            'pr_number': pr_number
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/pr/<int:pr_number>/merge', methods=['POST'])
@login_required
def merge_pr(pr_number):
    """
    Merge a PR after review suggestions have been addressed.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    data = request.get_json() or {}
    repo = data.get('repo', GITHUB_REPOS[0] if GITHUB_REPOS else None)
    merge_method = data.get('merge_method', 'merge')  # merge, squash, or rebase

    if not repo:
        return jsonify({'success': False, 'error': 'No repository specified'}), 400

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        # Merge the PR
        response = requests.put(
            f'https://api.github.com/repos/{repo}/pulls/{pr_number}/merge',
            headers=headers,
            json={'merge_method': merge_method},
            timeout=15
        )

        if response.status_code == 200:
            merge_data = response.json()
            return jsonify({
                'success': True,
                'message': f'PR #{pr_number} merged successfully',
                'sha': merge_data.get('sha'),
                'merged': True
            })
        elif response.status_code == 405:
            return jsonify({
                'success': False,
                'error': 'PR cannot be merged (conflicts or checks failing)'
            }), 405
        elif response.status_code == 409:
            return jsonify({
                'success': False,
                'error': 'Head branch was modified, review and try again'
            }), 409
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================
# LOCAL PR TRACKING ENDPOINTS
# ============================================

@coderabbit_bp.route('/api/prs/sync', methods=['POST'])
@login_required
def sync_prs():
    """Sync PRs from GitHub to local database for historical tracking"""
    if not GITHUB_TOKEN:
        return jsonify({'error': 'GitHub token not configured'}), 400

    data = request.get_json() or {}
    repos_to_sync = data.get('repos', GITHUB_REPOS)
    per_page = data.get('per_page', 30)

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        synced_count = 0
        sync_errors = []

        for repo in repos_to_sync:
            try:
                response = requests.get(
                    f'https://api.github.com/repos/{repo}/pulls?state=all&per_page={per_page}',
                    headers=headers,
                    timeout=15
                )

                if response.status_code == 200:
                    prs = response.json()
                    for pr in prs:
                        # Upsert PR data
                        cur.execute("""
                            INSERT INTO pull_requests
                            (pr_number, repo, title, state, author, url, created_at, updated_at,
                             merged_at, closed_at, additions, deletions, changed_files, labels, metadata, synced_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (repo, pr_number)
                            DO UPDATE SET
                                title = EXCLUDED.title,
                                state = EXCLUDED.state,
                                updated_at = EXCLUDED.updated_at,
                                merged_at = EXCLUDED.merged_at,
                                closed_at = EXCLUDED.closed_at,
                                additions = EXCLUDED.additions,
                                deletions = EXCLUDED.deletions,
                                changed_files = EXCLUDED.changed_files,
                                labels = EXCLUDED.labels,
                                synced_at = NOW()
                        """, (
                            pr['number'],
                            repo,
                            pr['title'][:500],
                            pr['state'],
                            pr['user']['login'],
                            pr['html_url'],
                            pr['created_at'],
                            pr['updated_at'],
                            pr.get('merged_at'),
                            pr.get('closed_at'),
                            pr.get('additions', 0),
                            pr.get('deletions', 0),
                            pr.get('changed_files', 0),
                            json.dumps([l['name'] for l in pr.get('labels', [])]),
                            json.dumps({
                                'base': pr.get('base', {}).get('ref'),
                                'head': pr.get('head', {}).get('ref'),
                                'draft': pr.get('draft', False)
                            })
                        ))
                        synced_count += 1
                else:
                    sync_errors.append({'repo': repo, 'error': f'HTTP {response.status_code}'})
            except Exception as e:
                sync_errors.append({'repo': repo, 'error': str(e)})

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'synced_count': synced_count,
            'repos_synced': len(repos_to_sync),
            'errors': sync_errors if sync_errors else None
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@coderabbit_bp.route('/api/prs/local')
def get_local_prs():
    """Get PRs from local database (faster, includes historical data)"""
    repo_filter = request.args.get('repo', None)
    state_filter = request.args.get('state', None)
    limit = request.args.get('limit', 50, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = "SELECT * FROM pull_requests WHERE 1=1"
        params = []

        if repo_filter:
            query += " AND repo = %s"
            params.append(repo_filter)

        if state_filter:
            query += " AND state = %s"
            params.append(state_filter)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        prs = cur.fetchall()

        # Get unique repos and counts
        cur.execute("""
            SELECT repo, COUNT(*) as count,
                   COUNT(*) FILTER (WHERE state = 'open') as open_count
            FROM pull_requests
            GROUP BY repo
        """)
        repo_counts = {r['repo']: {'total': r['count'], 'open': r['open_count']} for r in cur.fetchall()}

        return jsonify({
            'success': True,
            'pull_requests': [{
                **dict(pr),
                'created_at': pr['created_at'].isoformat() if pr['created_at'] else None,
                'updated_at': pr['updated_at'].isoformat() if pr['updated_at'] else None,
                'merged_at': pr['merged_at'].isoformat() if pr['merged_at'] else None,
                'closed_at': pr['closed_at'].isoformat() if pr['closed_at'] else None,
                'synced_at': pr['synced_at'].isoformat() if pr['synced_at'] else None,
                'repo_short': pr['repo'].split('/')[-1]
            } for pr in prs],
            'total_count': len(prs),
            'repo_stats': repo_counts,
            'source': 'local_database'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================
# CODE HEALTH SCANNER ENDPOINTS
# ============================================

@coderabbit_bp.route('/api/health/stats')
def get_health_stats():
    """Get code health statistics"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get scan stats
        cur.execute("""
            SELECT
                COUNT(*) as total_scans,
                COUNT(DISTINCT file_path) as files_scanned,
                SUM(issues_found) as total_issues,
                SUM(security_issues) as security_issues,
                AVG(quality_score) as avg_quality_score
            FROM code_scans
        """)
        scan_stats = cur.fetchone()

        # Get issue stats
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'open') as open_issues,
                COUNT(*) FILTER (WHERE status = 'fixed') as fixed_issues,
                COUNT(*) FILTER (WHERE severity = 'critical') as critical_issues,
                COUNT(*) FILTER (WHERE severity = 'high') as high_issues,
                COUNT(*) FILTER (WHERE severity = 'medium') as medium_issues,
                COUNT(*) FILTER (WHERE severity = 'low') as low_issues
            FROM code_issues
        """)
        issue_stats = cur.fetchone()

        # Get recent fixes
        cur.execute("""
            SELECT fixed_by, COUNT(*) as fix_count
            FROM code_fixes
            WHERE fixed_at > NOW() - INTERVAL '30 days'
            GROUP BY fixed_by
            ORDER BY fix_count DESC
            LIMIT 5
        """)
        top_fixers = cur.fetchall()

        return jsonify({
            'success': True,
            'scan_stats': {
                'total_scans': scan_stats['total_scans'] or 0,
                'files_scanned': scan_stats['files_scanned'] or 0,
                'total_issues': scan_stats['total_issues'] or 0,
                'security_issues': scan_stats['security_issues'] or 0,
                'avg_quality_score': float(scan_stats['avg_quality_score'] or 0)
            },
            'issue_stats': {
                'open': issue_stats['open_issues'] or 0,
                'fixed': issue_stats['fixed_issues'] or 0,
                'critical': issue_stats['critical_issues'] or 0,
                'high': issue_stats['high_issues'] or 0,
                'medium': issue_stats['medium_issues'] or 0,
                'low': issue_stats['low_issues'] or 0
            },
            'top_fixers': [dict(f) for f in top_fixers]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/health/scan', methods=['POST'])
def scan_file():
    """Scan a file for code quality and security issues using AI Bridge"""
    data = request.get_json() or {}
    file_path = data.get('file_path')
    full_path_provided = data.get('full_path')  # Direct path from directory listing

    if not file_path and not full_path_provided:
        return jsonify({'error': 'file_path is required'}), 400

    # Get the username and user_id from session
    scanned_by = session.get('username', 'system')
    # Get numeric user_id for Bridge routing (default to 4 for admin user)
    user_id = session.get('user_id', 4)  # 4 = admin user
    if not isinstance(user_id, int):
        user_id = 4  # Fallback to admin user

    try:
        # Resolve the full path
        if full_path_provided and os.path.exists(full_path_provided):
            full_path = full_path_provided
        elif file_path:
            # Map relative paths to container paths
            if file_path.startswith('platform_v2/'):
                full_path = f"/app/{file_path[len('platform_v2/'):]}"
            elif file_path.startswith('ai_bridge/'):
                full_path = f"/mnt/archie_brain/{file_path}"
            else:
                full_path = f"/mnt/archie_brain/{file_path}"
        else:
            return jsonify({'error': 'file_path is required'}), 400

        if not os.path.exists(full_path):
            return jsonify({'error': f'File not found: {file_path}'}), 404

        with open(full_path, 'r') as f:
            code_content = f.read()

        # STEP 1: Always run static analysis (fast baseline)
        static_result = basic_static_analysis(code_content, file_path)
        analysis_type = 'static'

        # STEP 2: Try AI analysis via Bridge routing (team member with experience)
        ai_result = None
        agent_used = None
        ollama_status = check_ollama_status()

        if BRIDGE_ROUTING_AVAILABLE:
            try:
                # Route to R&D station for code review tasks
                routing = route_task_to_station('code_review', f'Review code in {file_path}')
                agent = routing.get('agent')

                if agent:
                    agent_used = {
                        'id': agent.get('id'),
                        'name': agent.get('name'),
                        'station': routing.get('station'),
                        'model': agent.get('model')
                    }
                    logger.info(f"Code Health scan routed to {agent.get('name')} at {routing.get('station')} station")

                    # Limit content for AI analysis
                    ai_content = code_content[:10000] + "\n... (truncated)" if len(code_content) > 10000 else code_content

                    task = f"""Analyze this code for issues. Return a JSON object with:
{{
    "quality_score": 0-100,
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description of issue",
            "suggestion": "how to fix it"
        }}
    ],
    "summary": "brief summary"
}}

File: {file_path}
```
{ai_content}
```

Only return valid JSON, no other text."""

                    # Execute through Bridge with team member's context and experience
                    result = execute_agent_task(
                        agent_id=agent['id'],
                        task=task,
                        user_id=user_id,  # Numeric user ID for database tracking
                        stream=False
                    )

                    if result.get('success'):
                        # Parse AI response
                        response_text = result.get('response', '{}')
                        if '```json' in response_text:
                            response_text = response_text.split('```json')[1].split('```')[0]
                        elif '```' in response_text:
                            response_text = response_text.split('```')[1].split('```')[0]

                        ai_result = json.loads(response_text.strip())
                        analysis_type = 'ai_powered'
                        logger.info(f"AI analysis completed for {file_path} via {agent.get('name')}")
                    else:
                        logger.warning(f"Bridge execution failed: {result.get('error')}")
                else:
                    logger.warning(f"No agent available at {routing.get('station')} station")

            except Exception as e:
                logger.warning(f"Bridge routing failed, trying direct: {e}")

        # Fallback: Direct archie_bridge call if Bridge routing unavailable
        if not ai_result and ollama_status['available']:
            try:
                from ai_bridge.archie_bridge import archie_bridge

                # Limit content for AI analysis
                ai_content = code_content[:10000] + "\n... (truncated)" if len(code_content) > 10000 else code_content

                prompt = f"""Analyze this code for issues. Return a JSON object with:
{{
    "quality_score": 0-100,
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description of issue",
            "suggestion": "how to fix it"
        }}
    ],
    "summary": "brief summary"
}}

File: {file_path}
```
{ai_content}
```

Only return valid JSON, no other text."""

                ai_response = archie_bridge(prompt, try_local_first=True)

                # Parse AI response
                response_text = ai_response.get('response', '{}')
                if '```json' in response_text:
                    response_text = response_text.split('```json')[1].split('```')[0]
                elif '```' in response_text:
                    response_text = response_text.split('```')[1].split('```')[0]

                ai_result = json.loads(response_text.strip())
                analysis_type = 'ai_powered'
                agent_used = {'name': 'Direct Ollama', 'station': 'Fallback'}
                logger.info(f"AI analysis completed for {file_path} (fallback)")

            except Exception as e:
                logger.warning(f"AI analysis failed, using static: {e}")

        # STEP 3: Combine results (AI takes priority, static as supplement)
        if ai_result and ai_result.get('issues'):
            # Use AI results primarily
            analysis = {
                'quality_score': ai_result.get('quality_score', static_result['quality_score']),
                'issues': ai_result.get('issues', []),
                'summary': ai_result.get('summary', ''),
                'analysis_type': 'ai_powered'
            }
            # Add any static issues not caught by AI (by line number)
            ai_lines = {i.get('line') for i in analysis['issues'] if i.get('line')}
            for static_issue in static_result.get('issues', []):
                if static_issue.get('line') not in ai_lines:
                    analysis['issues'].append({**static_issue, 'source': 'static'})
        else:
            # Use static results
            analysis = static_result
            analysis['analysis_type'] = 'static'
            if ollama_status['available']:
                analysis['summary'] = 'AI parsing failed - showing static analysis'
            else:
                analysis['summary'] = f"Static analysis ({len(static_result['issues'])} issues found)"

        # Store scan results in database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        issues = analysis.get('issues', [])
        security_issues = len([i for i in issues if i.get('type') == 'security'])

        cur.execute("""
            INSERT INTO code_scans (file_path, scan_type, issues_found, security_issues,
                                   quality_score, scan_result, scanned_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            file_path, 'ai_scan', len(issues), security_issues,
            analysis.get('quality_score', 0), json.dumps(analysis), scanned_by
        ))
        scan_id = cur.fetchone()['id']

        # Store individual issues
        for issue in issues:
            cur.execute("""
                INSERT INTO code_issues (scan_id, file_path, line_number, issue_type,
                                        severity, message, suggestion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                scan_id, file_path, issue.get('line'),
                issue.get('type', 'quality'), issue.get('severity', 'medium'),
                issue.get('message', ''), issue.get('suggestion', '')
            ))

        # Add to knowledge_base for Consciousness learning
        critical_issues = [i for i in issues if i.get('severity') in ('critical', 'high')]
        if critical_issues:
            knowledge_content = f"""Code Health Scan: {file_path}
Quality Score: {analysis.get('quality_score', 0)}/100
Issues Found: {len(issues)} ({security_issues} security)

Critical/High Issues:
""" + '\n'.join([f"- [{i.get('severity', 'unknown').upper()}] {i.get('message', '')} (Line {i.get('line', '?')})" for i in critical_issues[:10]])

            cur.execute("""
                INSERT INTO knowledge_base (title, content, knowledge_type, file_path, file_name,
                                           importance_score, tags, category, memory_metadata, is_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                f"Code Issues: {file_path.split('/')[-1]}",
                knowledge_content,
                'code_snippet',
                file_path,
                file_path.split('/')[-1],
                0.7 if security_issues > 0 else 0.5,
                ['code-health', 'security' if security_issues > 0 else 'quality', file_path.split('/')[-1].split('.')[0]],
                'code_scan',
                json.dumps({'scan_id': scan_id, 'quality_score': analysis.get('quality_score', 0), 'issues': len(issues)}),
                True
            ))

        # Create improvement proposals for critical security issues
        security_critical = [i for i in issues if i.get('severity') == 'critical' and i.get('type') == 'security']
        for issue in security_critical[:3]:  # Max 3 proposals per scan
            cur.execute("""
                INSERT INTO improvement_proposals (title, description, category, priority, status,
                                                  risk_level, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                f"Security Fix: {issue.get('message', 'Unknown issue')[:80]}",
                f"""**File:** {file_path}
**Line:** {issue.get('line', 'Unknown')}
**Issue:** {issue.get('message', '')}
**Suggestion:** {issue.get('suggestion', 'Review and fix')}

This was detected by the Code Health Scanner and should be addressed.""",
                'security',
                'critical',
                'proposed',
                'high',
                json.dumps({'scan_id': scan_id, 'file_path': file_path, 'source': 'CodeRabbit Scanner', 'line': issue.get('line')})
            ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'scan_id': scan_id,
            'file_path': file_path,
            'quality_score': analysis.get('quality_score', 0),
            'issues_found': len(issues),
            'security_issues': security_issues,
            'issues': issues,
            'summary': analysis.get('summary', ''),
            'analysis_type': analysis.get('analysis_type', 'unknown'),
            'ollama_available': ollama_status['available'],
            'bridge_routing': BRIDGE_ROUTING_AVAILABLE,
            'agent_used': agent_used,  # Team member who performed the review
            'scanned_by': scanned_by,
            'scanned_at': datetime.now().isoformat(),
            'knowledge_added': len(critical_issues) > 0,
            'proposals_created': len(security_critical)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@coderabbit_bp.route('/api/health/batch-scan', methods=['POST'])
@login_required
def batch_scan_files():
    """
    Scan multiple files in parallel for improved performance.

    POST body:
    {
        "files": ["path/to/file1.py", "path/to/file2.py"],
        "max_workers": 4  // optional, default 4
    }
    """
    data = request.get_json() or {}
    file_paths = data.get('files', [])
    max_workers = min(data.get('max_workers', 4), 8)  # Cap at 8 workers

    if not file_paths:
        return jsonify({'error': 'No files provided'}), 400

    if len(file_paths) > 50:
        return jsonify({'error': 'Maximum 50 files per batch'}), 400

    scanned_by = session.get('username', 'system')
    results = []
    errors = []

    def scan_single_file(file_path):
        """Scan a single file - worker function"""
        try:
            # Resolve the full path
            if file_path.startswith('platform_v2/'):
                full_path = f"/app/{file_path[len('platform_v2/'):]}"
            elif file_path.startswith('ai_bridge/'):
                full_path = f"/mnt/archie_brain/{file_path}"
            else:
                full_path = f"/mnt/archie_brain/{file_path}"

            if not os.path.exists(full_path):
                return {'file_path': file_path, 'error': 'File not found', 'success': False}

            with open(full_path, 'r') as f:
                code_content = f.read()

            # Run static analysis (fast)
            static_result = basic_static_analysis(code_content, file_path)

            # Try AI analysis
            ai_result = None
            ollama_status = check_ollama_status()

            if ollama_status['available']:
                try:
                    from ai_bridge.archie_bridge import archie_bridge
                    ai_content = code_content[:8000] + "\n... (truncated)" if len(code_content) > 8000 else code_content

                    prompt = f"""Analyze this code briefly. Return JSON only:
{{"quality_score": 0-100, "issues": [{{"line": N, "type": "security|quality|style|performance", "severity": "critical|high|medium|low", "message": "issue"}}], "summary": "brief"}}

File: {file_path}
```
{ai_content}
```"""

                    ai_response = archie_bridge(prompt, try_local_first=True)
                    response_text = ai_response.get('response', '{}')
                    if '```json' in response_text:
                        response_text = response_text.split('```json')[1].split('```')[0]
                    elif '```' in response_text:
                        response_text = response_text.split('```')[1].split('```')[0]
                    ai_result = json.loads(response_text.strip())
                except Exception as e:
                    logger.warning(f"Batch AI scan failed for {file_path}: {e}")

            # Combine results
            if ai_result and ai_result.get('issues'):
                analysis = {
                    'quality_score': ai_result.get('quality_score', static_result['quality_score']),
                    'issues': ai_result.get('issues', []),
                    'summary': ai_result.get('summary', ''),
                    'analysis_type': 'ai_powered'
                }
            else:
                analysis = static_result
                analysis['analysis_type'] = 'static'

            # Store in database
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            issues = analysis.get('issues', [])
            security_issues = len([i for i in issues if i.get('type') == 'security'])

            cur.execute("""
                INSERT INTO code_scans (file_path, scan_type, issues_found, security_issues,
                                       quality_score, scan_result, scanned_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                file_path, 'batch_scan', len(issues), security_issues,
                analysis.get('quality_score', 0), json.dumps(analysis), scanned_by
            ))
            scan_id = cur.fetchone()['id']
            conn.commit()
            cur.close()
            conn.close()

            return {
                'file_path': file_path,
                'success': True,
                'scan_id': scan_id,
                'quality_score': analysis.get('quality_score', 0),
                'issues_found': len(issues),
                'security_issues': security_issues,
                'analysis_type': analysis.get('analysis_type')
            }

        except Exception as e:
            return {'file_path': file_path, 'error': str(e), 'success': False}

    # Run scans in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(scan_single_file, fp): fp for fp in file_paths}

        for future in as_completed(future_to_file):
            result = future.result()
            if result.get('success'):
                results.append(result)
            else:
                errors.append(result)

    return jsonify({
        'success': True,
        'total_files': len(file_paths),
        'scanned': len(results),
        'failed': len(errors),
        'results': results,
        'errors': errors,
        'summary': {
            'avg_quality': sum(r.get('quality_score', 0) for r in results) / max(len(results), 1),
            'total_issues': sum(r.get('issues_found', 0) for r in results),
            'security_issues': sum(r.get('security_issues', 0) for r in results)
        }
    })


@coderabbit_bp.route('/api/health/scans')
def get_scan_history():
    """Get scan history with full results"""
    limit = request.args.get('limit', 20, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id, file_path, scan_type, issues_found, security_issues,
                   quality_score, scanned_by, scanned_at, scan_result
            FROM code_scans
            ORDER BY scanned_at DESC
            LIMIT %s
        """, (limit,))
        scans = cur.fetchall()

        return jsonify({
            'success': True,
            'scans': [{
                **dict(s),
                'scanned_at': s['scanned_at'].isoformat() if s['scanned_at'] else None,
                'quality_score': float(s['quality_score']) if s['quality_score'] else None,
                'scan_result': s['scan_result'] if s['scan_result'] else {}
            } for s in scans]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/health/issues')
def get_issues():
    """Get code issues with linked proposal status"""
    status = request.args.get('status', 'all')
    limit = request.args.get('limit', 50, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Query with LEFT JOIN to improvement_proposals AND multi-agent reviews for tracking
        base_query = """
            SELECT i.*, s.scanned_by, s.scanned_at,
                   ip.id as proposal_id, ip.status as proposal_status, ip.title as proposal_title,
                   CASE WHEN mar.id IS NOT NULL THEN true ELSE false END as has_multi_agent_review,
                   mar.review_id as multi_agent_review_id,
                   (SELECT COUNT(*) FROM multi_agent_review_issues WHERE code_issue_id = i.id) as multi_agent_count
            FROM code_issues i
            JOIN code_scans s ON i.scan_id = s.id
            LEFT JOIN improvement_proposals ip ON i.proposal_id = ip.id
            LEFT JOIN multi_agent_review_issues mar ON i.id = mar.code_issue_id
        """

        if status == 'all':
            cur.execute(base_query + """
                ORDER BY
                    CASE i.severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    i.created_at DESC
                LIMIT %s
            """, (limit,))
        else:
            cur.execute(base_query + """
                WHERE i.status = %s
                ORDER BY
                    CASE i.severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    i.created_at DESC
                LIMIT %s
            """, (status, limit))

        issues = cur.fetchall()

        return jsonify({
            'success': True,
            'issues': [{
                **dict(i),
                'created_at': i['created_at'].isoformat() if i['created_at'] else None,
                'fixed_at': i['fixed_at'].isoformat() if i['fixed_at'] else None,
                'scanned_at': i['scanned_at'].isoformat() if i['scanned_at'] else None,
                'proposal_id': i.get('proposal_id'),
                'proposal_status': i.get('proposal_status'),
                'proposal_title': i.get('proposal_title'),
                'has_multi_agent_review': i.get('has_multi_agent_review', False),
                'multi_agent_review_id': i.get('multi_agent_review_id'),
                'multi_agent_count': i.get('multi_agent_count', 0)
            } for i in issues]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/health/issues/<int:issue_id>/fix', methods=['POST'])
def mark_issue_fixed(issue_id):
    """Mark an issue as fixed"""
    data = request.get_json() or {}
    fixed_by = data.get('fixed_by', session.get('username', 'unknown'))
    fix_description = data.get('description', '')
    pr_number = data.get('pr_number')
    pr_url = data.get('pr_url')
    commit_sha = data.get('commit_sha')

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get issue info
        cur.execute("SELECT file_path FROM code_issues WHERE id = %s", (issue_id,))
        issue = cur.fetchone()
        if not issue:
            return jsonify({'error': 'Issue not found'}), 404

        # Update issue status
        cur.execute("""
            UPDATE code_issues
            SET status = 'fixed', fixed_by = %s, fixed_at = NOW()
            WHERE id = %s
        """, (fixed_by, issue_id))

        # Record the fix
        cur.execute("""
            INSERT INTO code_fixes (issue_id, file_path, fixed_by, fix_description,
                                   pr_number, pr_url, commit_sha)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (issue_id, issue['file_path'], fixed_by, fix_description,
              pr_number, pr_url, commit_sha))

        fix_id = cur.fetchone()['id']
        conn.commit()

        return jsonify({
            'success': True,
            'fix_id': fix_id,
            'issue_id': issue_id,
            'fixed_by': fixed_by,
            'message': 'Issue marked as fixed'
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/health/fixes')
def get_fixes():
    """Get fix history with audit trail"""
    limit = request.args.get('limit', 30, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT f.*, i.issue_type, i.severity, i.message as issue_message
            FROM code_fixes f
            JOIN code_issues i ON f.issue_id = i.id
            ORDER BY f.fixed_at DESC
            LIMIT %s
        """, (limit,))
        fixes = cur.fetchall()

        return jsonify({
            'success': True,
            'fixes': [{
                **dict(f),
                'fixed_at': f['fixed_at'].isoformat() if f['fixed_at'] else None
            } for f in fixes]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/issues/multi-agent-status', methods=['POST'])
@login_required
def get_issues_multi_agent_status():
    """
    Check if issues have completed Multi-Agent Review.
    Required before issues can be sent to Improvements Lab.
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    issue_ids = data.get('issue_ids', [])
    if not issue_ids:
        return jsonify({'success': False, 'error': 'No issue_ids provided'}), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Check which issues have multi-agent reviews
        cur.execute("""
            SELECT DISTINCT ci.id as issue_id,
                   CASE WHEN mari.id IS NOT NULL THEN true ELSE false END as has_multi_agent,
                   mari.review_id,
                   COUNT(mari2.id) as agent_count
            FROM code_issues ci
            LEFT JOIN multi_agent_review_issues mari ON ci.id = mari.code_issue_id
            LEFT JOIN multi_agent_review_issues mari2 ON ci.id = mari2.code_issue_id
            WHERE ci.id = ANY(%s)
            GROUP BY ci.id, mari.id, mari.review_id
        """, (issue_ids,))
        results = cur.fetchall()

        status_map = {}
        for r in results:
            status_map[r['issue_id']] = {
                'has_multi_agent': r['has_multi_agent'],
                'review_id': r['review_id'],
                'agent_count': r['agent_count']
            }

        # Include issues not found (no multi-agent review)
        for issue_id in issue_ids:
            if issue_id not in status_map:
                status_map[issue_id] = {
                    'has_multi_agent': False,
                    'review_id': None,
                    'agent_count': 0
                }

        all_have_review = all(s['has_multi_agent'] for s in status_map.values())

        return jsonify({
            'success': True,
            'issues': status_map,
            'all_have_review': all_have_review,
            'can_send_to_lab': all_have_review
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/issues/send-to-improvements', methods=['POST'])
@login_required
def send_issues_to_improvements():
    """
    Send one or more CodeRabbit issues to Improvements Lab as proposals.
    Creates improvement_proposals with issue details and optional AI-generated fix.
    REQUIRES: Multi-Agent Review must be completed first.
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    issue_ids = data.get('issue_ids', [])
    include_ai_fix = data.get('include_ai_fix', False)

    if not issue_ids:
        return jsonify({'success': False, 'error': 'No issue_ids provided'}), 400

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get issue details - exclude issues that already have proposals
        cur.execute("""
            SELECT id, issue_type, severity, message, file_path, line_number,
                   suggestion, scan_id, proposal_id
            FROM code_issues
            WHERE id = ANY(%s) AND proposal_id IS NULL
        """, (issue_ids,))
        issues = cur.fetchall()

        if not issues:
            # Check if they already have proposals
            cur.execute("""
                SELECT id, proposal_id FROM code_issues WHERE id = ANY(%s) AND proposal_id IS NOT NULL
            """, (issue_ids,))
            already_sent = cur.fetchall()
            if already_sent:
                return jsonify({
                    'success': False,
                    'error': 'Issue(s) already sent to Improvements',
                    'existing_proposals': [{'issue_id': r['id'], 'proposal_id': r['proposal_id']} for r in already_sent]
                }), 400
            return jsonify({'success': False, 'error': 'No issues found'}), 404

        created_proposals = []
        skipped_no_review = []  # Track issues without multi-agent review

        for issue in issues:
            # Map issue_type to improvement category
            category_map = {
                'security': 'security',
                'performance': 'performance',
                'quality': 'code_quality',
                'maintainability': 'code_quality',
                'style': 'code_quality',
                'bug': 'bug_fix',
                'error': 'bug_fix'
            }
            category = category_map.get(issue['issue_type'], 'feature')

            # Map severity to priority
            priority_map = {
                'critical': 'critical',
                'high': 'high',
                'medium': 'medium',
                'low': 'low'
            }
            priority = priority_map.get(issue['severity'], 'medium')

            # FIRST: Check for multi-agent analysis on this issue (REQUIRED)
            multi_agent_data = None
            recommended_agent = None
            cur.execute("""
                SELECT
                    mari.review_id, mari.agent_name, mari.suggestion as agent_suggestion,
                    mari.confidence, mari.agreement_count,
                    mar.consensus, mar.agent_reviews, mar.final_issues
                FROM multi_agent_review_issues mari
                JOIN multi_agent_reviews mar ON mari.review_id = mar.review_id
                WHERE mari.code_issue_id = %s
                ORDER BY mari.agreement_count DESC, mari.confidence DESC
                LIMIT 1
            """, (issue['id'],))
            ma_result = cur.fetchone()

            if ma_result:
                # Get all agent suggestions for this issue
                cur.execute("""
                    SELECT agent_name, suggestion, confidence, agreement_count
                    FROM multi_agent_review_issues
                    WHERE code_issue_id = %s
                    ORDER BY agreement_count DESC, confidence DESC
                """, (issue['id'],))
                agent_suggestions = cur.fetchall()

                # Find best agent to recommend for the fix
                cur.execute("""
                    SELECT a.id, a.name, a.model, a.tier,
                           MAX(s.proficiency_level) as proficiency
                    FROM agents a
                    JOIN agent_skills s ON a.id = s.agent_id
                    WHERE s.skill_name IN ('bug_fixing', 'code_review', 'security_audit')
                      AND a.status = 'active'
                    GROUP BY a.id
                    ORDER BY proficiency DESC
                    LIMIT 1
                """)
                best_agent = cur.fetchone()

                multi_agent_data = {
                    'review_id': ma_result['review_id'],
                    'consensus': ma_result['consensus'] if isinstance(ma_result['consensus'], dict) else json.loads(ma_result['consensus'] or '{}'),
                    'agent_suggestions': [dict(s) for s in agent_suggestions],
                    'agents_consulted': len(agent_suggestions),
                    'highest_confidence': agent_suggestions[0]['confidence'] if agent_suggestions else None,
                    'agreement_count': agent_suggestions[0]['agreement_count'] if agent_suggestions else 0
                }

                if best_agent:
                    recommended_agent = {
                        'id': best_agent['id'],
                        'name': best_agent['name'],
                        'model': best_agent['model'],
                        'tier': best_agent['tier'],
                        'proficiency': best_agent['proficiency'],
                        'reason': f"Highest proficiency ({best_agent['proficiency']}) in relevant skills"
                    }

            # REQUIREMENT: Multi-Agent Review must be completed before sending to Lab
            if not multi_agent_data:
                # Track this issue as skipped - needs multi-agent review first
                skipped_no_review.append({
                    'issue_id': issue['id'],
                    'file_path': issue['file_path'],
                    'message': issue['message'][:50]
                })
                continue

            # Create proposal title and description (after multi-agent data is available)
            title = f"[{issue['issue_type'].upper()}] {issue['message'][:100]}"

            # Build multi-agent section
            agent_list = ", ".join([s['agent_name'] for s in multi_agent_data.get('agent_suggestions', [])[:3]])
            multi_agent_section = f"""

### Multi-Agent Analysis
**Agents Consulted:** {multi_agent_data.get('agents_consulted', 0)} ({agent_list})
**Confidence Level:** {multi_agent_data.get('highest_confidence', 'N/A')}
**Agent Agreement:** {multi_agent_data.get('agreement_count', 0)} agents agree

#### Fix Suggestions from Team:
"""
            for idx, suggestion in enumerate(multi_agent_data.get('agent_suggestions', [])[:3], 1):
                multi_agent_section += f"\n**{idx}. {suggestion['agent_name']}** (confidence: {suggestion['confidence']}):\n{suggestion['suggestion']}\n"

            recommended_section = ""
            if recommended_agent:
                recommended_section = f"""

### Recommended Assignee
**Agent:** {recommended_agent['name']} (ID: {recommended_agent['id']})
**Model:** {recommended_agent['model']}
**Tier:** {recommended_agent['tier']}
**Reason:** {recommended_agent['reason']}
"""

            description = f"""## Issue from CodeRabbit Scanner

**Type:** {issue['issue_type']}
**Severity:** {issue['severity']}
**File:** `{issue['file_path']}`
**Line:** {issue['line_number'] or 'N/A'}

### Issue Description
{issue['message']}

### Suggested Fix
{issue['suggestion'] or 'AI analysis needed'}
{multi_agent_section}{recommended_section}
---
*Auto-generated from CodeRabbit issue #{issue['id']}*
"""

            # Create metadata for tracking (includes all fields for AI code generation)
            metadata = {
                'source': 'coderabbit',
                'issue_id': issue['id'],
                'scan_id': issue['scan_id'],
                'file_path': issue['file_path'],
                'line_number': issue['line_number'],
                'issue_type': issue['issue_type'],
                'severity': issue['severity'],
                'message': issue['message'],
                'suggestion': issue['suggestion'],
                'multi_agent_analysis': multi_agent_data,
                'recommended_assignee': recommended_agent
            }

            # Insert the improvement proposal
            cur.execute("""
                INSERT INTO improvement_proposals
                (title, description, category, priority, status, metadata, proposed_at)
                VALUES (%s, %s, %s, %s, 'proposed', %s, NOW())
                RETURNING id, title, category, priority, status
            """, (
                title,
                description,
                category,
                priority,
                json.dumps(metadata)
            ))
            proposal = cur.fetchone()

            # Update the issue with the proposal_id
            cur.execute("""
                UPDATE code_issues
                SET proposal_id = %s, status = 'sent_to_improvements'
                WHERE id = %s
            """, (proposal['id'], issue['id']))

            created_proposals.append(dict(proposal))

        conn.commit()

        # Check if all issues were skipped
        if not created_proposals and skipped_no_review:
            return jsonify({
                'success': False,
                'error': 'All issues require Multi-Agent Review before sending to Improvements Lab',
                'skipped': skipped_no_review,
                'hint': 'Run Multi-Agent Review on these issues first via the Multi-Agent tab'
            }), 400

        return jsonify({
            'success': True,
            'message': f'{len(created_proposals)} proposal(s) created',
            'proposals': created_proposals,
            'skipped_no_review': skipped_no_review if skipped_no_review else None
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================
# FEEDBACK LOOP: Improvements → Code Issues
# ============================================

@coderabbit_bp.route('/api/issues/update-from-improvement', methods=['POST'])
@login_required
def update_issue_from_improvement():
    """
    Callback endpoint for Improvements Lab to update code_issues status.
    Called when a proposal is approved, deployed, or rejected.
    """
    data = request.get_json() or {}
    proposal_id = data.get('proposal_id')
    new_status = data.get('status')  # 'fixed', 'deployed', 'rejected', 'wont_fix'
    fixed_by = data.get('fixed_by', session.get('username', 'system'))

    if not proposal_id or not new_status:
        return jsonify({'success': False, 'error': 'proposal_id and status required'}), 400

    valid_statuses = ['fixed', 'deployed', 'rejected', 'wont_fix', 'in_progress']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': f'Invalid status. Use: {valid_statuses}'}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Update all code_issues linked to this proposal
        cur.execute("""
            UPDATE code_issues
            SET status = %s,
                fixed_by = %s,
                fixed_at = CASE WHEN %s IN ('fixed', 'deployed') THEN NOW() ELSE fixed_at END
            WHERE proposal_id = %s
            RETURNING id, file_path, issue_type, status
        """, (new_status, fixed_by, new_status, proposal_id))

        updated_issues = cur.fetchall()
        conn.commit()

        # Log the update for tracking
        logger.info(f"Proposal #{proposal_id} → Updated {len(updated_issues)} code_issues to '{new_status}'")

        return jsonify({
            'success': True,
            'proposal_id': proposal_id,
            'new_status': new_status,
            'issues_updated': len(updated_issues),
            'issues': [dict(i) for i in updated_issues]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ============================================
# PR REVIEW ↔ CODE HEALTH COMPARISON
# ============================================

@coderabbit_bp.route('/api/compare-reviews')
@login_required
def compare_pr_and_health_reviews():
    """
    Compare issues found by CodeRabbit PR review vs local Code Health scan.
    Helps identify correlation and validate findings.
    """
    file_path = request.args.get('file_path')
    pr_number = request.args.get('pr_number', type=int)

    if not file_path:
        return jsonify({'success': False, 'error': 'file_path required'}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        comparison = {
            'file_path': file_path,
            'pr_number': pr_number,
            'code_health_issues': [],
            'pr_review_issues': [],
            'multi_agent_issues': [],
            'correlations': [],
            'summary': {}
        }

        # Get Code Health issues for this file
        cur.execute("""
            SELECT id, line_number, issue_type, severity, message, suggestion, status, created_at
            FROM code_issues
            WHERE file_path = %s
            ORDER BY severity DESC, line_number
        """, (file_path,))
        comparison['code_health_issues'] = [dict(r) for r in cur.fetchall()]

        # Get Multi-Agent Review issues for this file
        cur.execute("""
            SELECT mari.*, mar.review_id, mar.completed_at
            FROM multi_agent_review_issues mari
            JOIN multi_agent_reviews mar ON mari.review_id = mar.review_id
            WHERE mar.file_path = %s
            ORDER BY mari.severity DESC, mari.line_number
        """, (file_path,))
        comparison['multi_agent_issues'] = [dict(r) for r in cur.fetchall()]

        # If PR number provided, fetch CodeRabbit comments from GitHub
        if pr_number and GITHUB_TOKEN:
            try:
                headers = {
                    'Authorization': f'token {GITHUB_TOKEN}',
                    'Accept': 'application/vnd.github.v3+json'
                }

                # Get PR review comments (inline)
                repo = GITHUB_REPOS[0] if GITHUB_REPOS else GITHUB_REPO
                response = requests.get(
                    f'https://api.github.com/repos/{repo}/pulls/{pr_number}/comments',
                    headers=headers,
                    timeout=10
                )

                if response.status_code == 200:
                    for comment in response.json():
                        # Check if comment is about this file
                        if file_path in comment.get('path', ''):
                            comparison['pr_review_issues'].append({
                                'line': comment.get('line') or comment.get('original_line'),
                                'body': comment.get('body', ''),
                                'user': comment.get('user', {}).get('login', ''),
                                'created_at': comment.get('created_at'),
                                'is_coderabbit': 'coderabbit' in comment.get('user', {}).get('login', '').lower()
                            })
            except Exception as e:
                logger.warning(f"Failed to fetch PR comments: {e}")

        # Find correlations (issues found by multiple sources)
        health_lines = {i['line_number'] for i in comparison['code_health_issues'] if i.get('line_number')}
        ma_lines = {i['line_number'] for i in comparison['multi_agent_issues'] if i.get('line_number')}
        pr_lines = {i['line'] for i in comparison['pr_review_issues'] if i.get('line')}

        # Issues found by all three sources
        all_three = health_lines & ma_lines & pr_lines
        # Issues found by at least two sources
        at_least_two = (health_lines & ma_lines) | (health_lines & pr_lines) | (ma_lines & pr_lines)

        for line in at_least_two:
            sources = []
            if line in health_lines:
                sources.append('code_health')
            if line in ma_lines:
                sources.append('multi_agent')
            if line in pr_lines:
                sources.append('pr_review')

            comparison['correlations'].append({
                'line': line,
                'sources': sources,
                'confidence': 'high' if len(sources) >= 2 else 'medium'
            })

        # Summary
        comparison['summary'] = {
            'code_health_count': len(comparison['code_health_issues']),
            'multi_agent_count': len(comparison['multi_agent_issues']),
            'pr_review_count': len(comparison['pr_review_issues']),
            'correlated_issues': len(comparison['correlations']),
            'high_confidence': len([c for c in comparison['correlations'] if c['confidence'] == 'high'])
        }

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'comparison': comparison
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/health/files')
def get_file_health():
    """Get health status of files in the codebase"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get latest scan for each file
        cur.execute("""
            SELECT DISTINCT ON (file_path)
                file_path, quality_score, issues_found, security_issues,
                scanned_by, scanned_at
            FROM code_scans
            ORDER BY file_path, scanned_at DESC
        """)
        files = cur.fetchall()

        # Get open issues per file
        cur.execute("""
            SELECT file_path, COUNT(*) as open_issues
            FROM code_issues
            WHERE status = 'open'
            GROUP BY file_path
        """)
        open_issues = {r['file_path']: r['open_issues'] for r in cur.fetchall()}

        return jsonify({
            'success': True,
            'files': [{
                **dict(f),
                'open_issues': open_issues.get(f['file_path'], 0),
                'quality_score': float(f['quality_score']) if f['quality_score'] else None,
                'scanned_at': f['scanned_at'].isoformat() if f['scanned_at'] else None
            } for f in files]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@coderabbit_bp.route('/api/health/files-needing-rescan')
def get_files_needing_rescan():
    """Get files that have been modified since their last scan"""
    directory = request.args.get('path', 'platform_v2')
    extensions = request.args.get('ext', '.py,.js,.html').split(',')

    try:
        # Map directory names to actual container paths
        path_mapping = {
            'platform_v2': '/app',
            'ai_bridge': '/mnt/archie_brain/ai_bridge',
            'docs': '/mnt/archie_brain/docs'
        }
        base_path = path_mapping.get(directory, f"/mnt/archie_brain/{directory}")

        if not os.path.exists(base_path):
            return jsonify({'error': f'Directory not found: {directory}'}), 404

        # Get last scan times from database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT DISTINCT ON (file_path) file_path, scanned_at
            FROM code_scans
            ORDER BY file_path, scanned_at DESC
        """)
        scan_times = {r['file_path']: r['scanned_at'] for r in cur.fetchall()}
        cur.close()
        conn.close()

        files_needing_rescan = []
        for root, dirs, filenames in os.walk(base_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules' and d != '_deprecated' and 'deprecated' not in d.lower()]

            for filename in filenames:
                if filename == '__init__.py':
                    continue
                if any(filename.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, filename)
                    if base_path == '/app':
                        rel_path = f"platform_v2/{os.path.relpath(full_path, '/app')}"
                    else:
                        rel_path = os.path.relpath(full_path, '/mnt/archie_brain')

                    stat = os.stat(full_path)
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    last_scan = scan_times.get(rel_path)

                    # File needs rescan if: never scanned OR modified after last scan
                    needs_rescan = last_scan is None or mtime > last_scan
                    if needs_rescan:
                        files_needing_rescan.append({
                            'path': rel_path,
                            'name': filename,
                            'full_path': full_path,
                            'mtime': mtime.isoformat(),
                            'last_scan': last_scan.isoformat() if last_scan else None,
                            'reason': 'never_scanned' if last_scan is None else 'modified'
                        })

        return jsonify({
            'success': True,
            'files_needing_rescan': files_needing_rescan,
            'count': len(files_needing_rescan),
            'total_scanned': len(scan_times)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@coderabbit_bp.route('/api/health/directory')
def get_directory_files():
    """Get list of files in a directory for scanning"""
    directory = request.args.get('path', 'platform_v2')
    extensions = request.args.get('ext', '.py,.js,.html').split(',')

    try:
        # Map directory names to actual container paths
        path_mapping = {
            'platform_v2': '/app',
            'ai_bridge': '/mnt/archie_brain/ai_bridge',
            'docs': '/mnt/archie_brain/docs'
        }

        base_path = path_mapping.get(directory, f"/mnt/archie_brain/{directory}")

        if not os.path.exists(base_path):
            return jsonify({'error': f'Directory not found: {directory}'}), 404

        files = []
        for root, dirs, filenames in os.walk(base_path):
            # Skip hidden, cache, and deprecated directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules' and d != '_deprecated' and 'deprecated' not in d.lower()]

            for filename in filenames:
                # Skip __init__.py files - they're boilerplate and don't need scanning
                if filename == '__init__.py':
                    continue
                if any(filename.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, filename)
                    # Create a user-friendly relative path
                    if base_path == '/app':
                        rel_path = f"platform_v2/{os.path.relpath(full_path, '/app')}"
                        folder = os.path.dirname(os.path.relpath(full_path, '/app'))
                    else:
                        rel_path = os.path.relpath(full_path, '/mnt/archie_brain')
                        folder = os.path.dirname(rel_path)
                    stat = os.stat(full_path)
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    files.append({
                        'path': rel_path,
                        'name': filename,
                        'size': size,
                        'full_path': full_path,  # Store actual path for scanning
                        'extension': os.path.splitext(filename)[1],
                        'folder': folder or 'root',  # Add folder for grouping
                        'mtime': mtime.isoformat()  # File modification time for rescan detection
                    })

        return jsonify({
            'success': True,
            'directory': directory,
            'file_count': len(files),
            'files': sorted(files, key=lambda x: x['path'])
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# LOCAL GIT MANAGEMENT ENDPOINTS
# ============================================

# Git repo path - the .git directory is mounted separately from work tree
# In Docker: .git is at /mnt/archie_brain/.git, work tree is /mnt/archie_brain
GIT_DIR = '/mnt/archie_brain/.git'
GIT_WORK_TREE = '/mnt/archie_brain'
GIT_REPO_PATH = GIT_WORK_TREE if os.path.exists(GIT_DIR) else None


def run_git_command(args, cwd=None):
    """Run a git command and return the result.

    Uses GIT_DIR and GIT_WORK_TREE environment variables to handle
    Docker volume mounts where .git and work tree are separate.
    """
    import subprocess

    if not os.path.exists(GIT_DIR):
        return {'success': False, 'error': 'Git directory not found at ' + GIT_DIR}

    try:
        # Set environment variables for git
        env = os.environ.copy()
        env['GIT_DIR'] = GIT_DIR
        env['GIT_WORK_TREE'] = GIT_WORK_TREE

        result = subprocess.run(
            ['git'] + args,
            cwd=cwd or GIT_WORK_TREE,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Git command timed out'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


@coderabbit_bp.route('/api/git/status')
def get_git_status():
    """Get local git status - branch, unpushed commits, modified files"""
    if not GIT_REPO_PATH:
        return jsonify({
            'success': False,
            'error': 'Git repository not accessible. .git directory may not be mounted.',
            'suggestion': 'Add .git to docker volume mounts'
        }), 400

    try:
        # Get current branch
        branch_result = run_git_command(['branch', '--show-current'])
        current_branch = branch_result['stdout'].strip() if branch_result['success'] else 'unknown'

        # Get status (modified files)
        status_result = run_git_command(['status', '--porcelain'])
        modified_files = []
        untracked_files = []
        if status_result['success']:
            for line in status_result['stdout'].strip().split('\n'):
                if line:
                    status_code = line[:2]
                    file_path = line[3:]
                    # Skip deleted files (they exist in git but not in container)
                    if status_code.strip() == 'D':
                        continue
                    if status_code.startswith('??'):
                        untracked_files.append(file_path)
                    else:
                        modified_files.append({'status': status_code.strip(), 'file': file_path})

        # Get unpushed commits with author and date
        unpushed_result = run_git_command([
            'log', '@{u}..HEAD',
            '--format=%H|%h|%s|%an|%ar'
        ])
        unpushed_commits = []
        if unpushed_result['success'] and unpushed_result['stdout'].strip():
            for line in unpushed_result['stdout'].strip().split('\n'):
                if line and '|' in line:
                    parts = line.split('|', 4)
                    unpushed_commits.append({
                        'full_hash': parts[0] if len(parts) > 0 else '',
                        'hash': parts[1] if len(parts) > 1 else '',
                        'message': parts[2] if len(parts) > 2 else '',
                        'author': parts[3] if len(parts) > 3 else '',
                        'date': parts[4] if len(parts) > 4 else ''
                    })
        elif not unpushed_result['success'] and 'no upstream' in unpushed_result['stderr'].lower():
            # No upstream configured
            pass

        # Get recent commits (last 10)
        log_result = run_git_command(['log', '--oneline', '-10'])
        recent_commits = []
        if log_result['success']:
            for line in log_result['stdout'].strip().split('\n'):
                if line:
                    parts = line.split(' ', 1)
                    recent_commits.append({
                        'hash': parts[0],
                        'message': parts[1] if len(parts) > 1 else ''
                    })

        # Check if ahead/behind remote
        ahead_behind = run_git_command(['rev-list', '--left-right', '--count', '@{u}...HEAD'])
        ahead = 0
        behind = 0
        if ahead_behind['success']:
            parts = ahead_behind['stdout'].strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

        return jsonify({
            'success': True,
            'repo_path': GIT_REPO_PATH,
            'branch': current_branch,
            'modified_files': modified_files,
            'untracked_files': untracked_files,
            'unpushed_commits': unpushed_commits,
            'recent_commits': recent_commits,
            'ahead': ahead,
            'behind': behind,
            'summary': {
                'modified_count': len(modified_files),
                'untracked_count': len(untracked_files),
                'unpushed_count': len(unpushed_commits)
            }
        })

    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@coderabbit_bp.route('/api/git/push', methods=['POST'])
@login_required
def git_push():
    """Push commits to remote repository"""
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not accessible'}), 400

    try:
        # First, get current branch
        branch_result = run_git_command(['branch', '--show-current'])
        if not branch_result['success']:
            return jsonify({'success': False, 'error': 'Could not determine current branch'}), 400

        current_branch = branch_result['stdout'].strip()

        # Push to origin
        push_result = run_git_command(['push', 'origin', current_branch])

        if push_result['success']:
            return jsonify({
                'success': True,
                'message': f'Successfully pushed to origin/{current_branch}',
                'output': push_result['stdout'] or push_result['stderr']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Push failed',
                'details': push_result['stderr'] or push_result['stdout']
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/pull', methods=['POST'])
@login_required
def git_pull():
    """Pull latest changes from remote repository"""
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not accessible'}), 400

    try:
        # Pull from origin
        pull_result = run_git_command(['pull', 'origin'])

        if pull_result['success']:
            return jsonify({
                'success': True,
                'message': 'Successfully pulled latest changes',
                'output': pull_result['stdout']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Pull failed',
                'details': pull_result['stderr'] or pull_result['stdout']
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/stage-all', methods=['POST'])
@login_required
def git_stage_all():
    """Stage all changes for commit"""
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not accessible'}), 400

    try:
        # Check if there are changes to stage
        status_result = run_git_command(['status', '--porcelain'])
        if not status_result['stdout'].strip():
            return jsonify({
                'success': True,
                'message': 'No changes to stage',
                'staged_count': 0
            })

        # Stage all changes
        add_result = run_git_command(['add', '-A'])
        if add_result['success']:
            # Count staged files
            staged_result = run_git_command(['diff', '--cached', '--name-only'])
            staged_count = len([f for f in staged_result['stdout'].strip().split('\n') if f]) if staged_result['success'] else 0

            return jsonify({
                'success': True,
                'message': f'Staged {staged_count} file(s)',
                'staged_count': staged_count
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to stage files',
                'details': add_result['stderr']
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/commit', methods=['POST'])
@login_required
def git_commit():
    """Create a new commit with staged changes"""
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not accessible'}), 400

    data = request.get_json() or {}
    message = data.get('message', '').strip()
    add_all = data.get('add_all', data.get('stage_all', False))  # Support both parameter names

    if not message:
        return jsonify({'success': False, 'error': 'Commit message is required'}), 400

    try:
        # Optionally add all changes
        if add_all:
            add_result = run_git_command(['add', '-A'])
            if not add_result['success']:
                return jsonify({
                    'success': False,
                    'error': 'Failed to stage changes',
                    'details': add_result['stderr']
                }), 400

        # Create commit
        commit_result = run_git_command(['commit', '-m', message])

        if commit_result['success']:
            # Get the new commit hash
            hash_result = run_git_command(['rev-parse', '--short', 'HEAD'])
            commit_hash = hash_result['stdout'].strip() if hash_result['success'] else 'unknown'

            return jsonify({
                'success': True,
                'message': 'Commit created successfully',
                'commit_hash': commit_hash,
                'output': commit_result['stdout']
            })
        else:
            # Check if nothing to commit
            if 'nothing to commit' in commit_result['stdout'].lower():
                return jsonify({
                    'success': False,
                    'error': 'Nothing to commit',
                    'details': 'No changes staged for commit'
                }), 400

            return jsonify({
                'success': False,
                'error': 'Commit failed',
                'details': commit_result['stderr'] or commit_result['stdout']
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/fetch', methods=['POST'])
@login_required
def git_fetch():
    """Fetch latest refs from remote without merging"""
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not accessible'}), 400

    try:
        fetch_result = run_git_command(['fetch', 'origin'])

        return jsonify({
            'success': fetch_result['success'],
            'message': 'Fetch completed' if fetch_result['success'] else 'Fetch failed',
            'output': fetch_result['stdout'] or fetch_result['stderr']
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/create-pr', methods=['POST'])
@login_required
def git_create_pr():
    """
    Create a Pull Request on GitHub.
    Allows creating PRs directly from the CodeRabbit interface.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    base = data.get('base', 'main')
    head = data.get('head')
    title = data.get('title')
    body = data.get('body', '')

    if not head:
        return jsonify({'success': False, 'error': 'Head branch is required'}), 400
    if not title:
        return jsonify({'success': False, 'error': 'PR title is required'}), 400

    # Get the first configured repo (or could make this selectable)
    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    repo = GITHUB_REPOS[0]

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        # Create the PR
        response = requests.post(
            f'https://api.github.com/repos/{repo}/pulls',
            headers=headers,
            json={
                'title': title,
                'head': head,
                'base': base,
                'body': body
            },
            timeout=15
        )

        if response.status_code == 201:
            pr_data = response.json()
            return jsonify({
                'success': True,
                'pr_number': pr_data['number'],
                'pr_url': pr_data['html_url'],
                'repo': repo,
                'message': f'Pull Request #{pr_data["number"]} created successfully'
            })
        elif response.status_code == 422:
            # Validation error - often means PR already exists or no commits
            error_data = response.json()
            errors = error_data.get('errors', [])
            error_msg = errors[0].get('message', 'Validation failed') if errors else 'PR already exists or no new commits'
            return jsonify({'success': False, 'error': error_msg}), 422
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code} - {response.text}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/pr-info')
@login_required
def git_pr_info():
    """
    Get all information needed to create a PR from the current branch.
    Returns branch info, commits ahead of main, diff stats, and suggested PR content.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    try:
        # Get current branch
        branch_result = run_git_command(['branch', '--show-current'])
        current_branch = branch_result['stdout'].strip() if branch_result['success'] else 'unknown'

        if current_branch in ['main', 'master']:
            return jsonify({
                'success': False,
                'error': 'Cannot create PR from main/master branch. Switch to a feature branch first.'
            }), 400

        # Determine base branch (main or master)
        base_branch = 'main'
        check_main = run_git_command(['rev-parse', '--verify', 'origin/main'])
        if not check_main['success']:
            check_master = run_git_command(['rev-parse', '--verify', 'origin/master'])
            if check_master['success']:
                base_branch = 'master'

        # Get commits ahead of base branch
        commits_result = run_git_command([
            'log', f'origin/{base_branch}..HEAD',
            '--format=%H|%h|%s|%an|%ar|%b',
            '--reverse'
        ])

        commits = []
        commit_messages = []
        if commits_result['success'] and commits_result['stdout'].strip():
            for line in commits_result['stdout'].strip().split('\n'):
                if line and '|' in line:
                    parts = line.split('|', 5)
                    msg = parts[2] if len(parts) > 2 else ''
                    commits.append({
                        'full_hash': parts[0] if len(parts) > 0 else '',
                        'hash': parts[1] if len(parts) > 1 else '',
                        'message': msg,
                        'author': parts[3] if len(parts) > 3 else '',
                        'date': parts[4] if len(parts) > 4 else '',
                        'body': parts[5] if len(parts) > 5 else ''
                    })
                    commit_messages.append(msg)

        # Get diff stats
        diff_result = run_git_command(['diff', '--stat', f'origin/{base_branch}..HEAD'])
        diff_summary = ''
        files_changed = 0
        insertions = 0
        deletions = 0
        if diff_result['success']:
            lines = diff_result['stdout'].strip().split('\n')
            if lines:
                # Last line contains summary like "388 files changed, 1012550 insertions(+), 13945 deletions(-)"
                summary_line = lines[-1] if lines else ''
                diff_summary = summary_line
                import re
                match = re.search(r'(\d+) files? changed', summary_line)
                if match:
                    files_changed = int(match.group(1))
                match = re.search(r'(\d+) insertions?', summary_line)
                if match:
                    insertions = int(match.group(1))
                match = re.search(r'(\d+) deletions?', summary_line)
                if match:
                    deletions = int(match.group(1))

        # Generate suggested PR title
        suggested_title = current_branch.replace('/', ': ').replace('-', ' ').replace('_', ' ')
        # If branch follows convention like feature/something, format nicely
        if '/' in current_branch:
            prefix, name = current_branch.split('/', 1)
            prefix_map = {
                'feature': 'feat',
                'fix': 'fix',
                'bugfix': 'fix',
                'hotfix': 'fix',
                'docs': 'docs',
                'refactor': 'refactor',
                'test': 'test',
                'chore': 'chore'
            }
            prefix = prefix_map.get(prefix.lower(), prefix)
            suggested_title = f"{prefix}: {name.replace('-', ' ').replace('_', ' ').title()}"

        # Generate suggested PR body
        body_lines = ['## Summary\n']

        # Group commits by type
        feat_commits = [c for c in commit_messages if c.lower().startswith('feat')]
        fix_commits = [c for c in commit_messages if c.lower().startswith('fix')]
        docs_commits = [c for c in commit_messages if c.lower().startswith('docs')]
        other_commits = [c for c in commit_messages if not any(c.lower().startswith(p) for p in ['feat', 'fix', 'docs', 'chore', 'refactor', 'test'])]

        if feat_commits:
            body_lines.append('### Features')
            for c in feat_commits[:10]:  # Limit to 10
                body_lines.append(f'- {c}')
            body_lines.append('')

        if fix_commits:
            body_lines.append('### Fixes')
            for c in fix_commits[:10]:
                body_lines.append(f'- {c}')
            body_lines.append('')

        if docs_commits:
            body_lines.append('### Documentation')
            for c in docs_commits[:5]:
                body_lines.append(f'- {c}')
            body_lines.append('')

        if other_commits and len(commits) < 20:
            body_lines.append('### Other Changes')
            for c in other_commits[:10]:
                body_lines.append(f'- {c}')
            body_lines.append('')

        body_lines.append(f'### Stats')
        body_lines.append(f'- **{len(commits)}** commits')
        body_lines.append(f'- **{files_changed}** files changed')
        body_lines.append(f'- **+{insertions:,}** insertions, **-{deletions:,}** deletions')
        body_lines.append('')
        body_lines.append('## Test Plan')
        body_lines.append('- [ ] Verify changes work as expected')
        body_lines.append('- [ ] Run tests')
        body_lines.append('')
        body_lines.append('🤖 Generated with [Claude Code](https://claude.com/claude-code)')

        suggested_body = '\n'.join(body_lines)

        # Check for GitHub file limit warning
        warnings = []
        if files_changed > 150:
            warnings.append({
                'type': 'file_limit',
                'severity': 'warning',
                'message': f'This PR has {files_changed} files, exceeding GitHub\'s 150 file display limit. GitHub will still accept the PR but won\'t show all diffs in the web UI. Consider splitting into smaller PRs.'
            })
        if files_changed > 300:
            warnings[0]['severity'] = 'error'
            warnings[0]['message'] = f'This PR has {files_changed} files, significantly exceeding GitHub\'s 150 file display limit. Strongly recommend splitting into multiple smaller PRs for better reviewability.'

        return jsonify({
            'success': True,
            'current_branch': current_branch,
            'base_branch': base_branch,
            'commits': commits,
            'commit_count': len(commits),
            'diff_stats': {
                'summary': diff_summary,
                'files_changed': files_changed,
                'insertions': insertions,
                'deletions': deletions
            },
            'suggested': {
                'title': suggested_title,
                'body': suggested_body
            },
            'warnings': warnings
        })

    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@coderabbit_bp.route('/api/git/suggest-splits')
@login_required
def git_suggest_splits():
    """
    Analyze changed files and suggest logical PR splits when file count > 150.
    Groups files by category (MCP, Consciousness, Node/Bridge, System Ops, etc.)
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    try:
        # Get current branch
        branch_result = run_git_command(['branch', '--show-current'])
        current_branch = branch_result['stdout'].strip() if branch_result['success'] else 'unknown'

        # Determine base branch
        base_branch = 'main'
        check_main = run_git_command(['rev-parse', '--verify', 'origin/main'])
        if not check_main['success']:
            check_master = run_git_command(['rev-parse', '--verify', 'origin/master'])
            if check_master['success']:
                base_branch = 'master'

        # Get all changed files (only Added and Modified, not Deleted)
        # --diff-filter=AM excludes deleted files that don't exist in HEAD
        files_result = run_git_command(['diff', '--name-only', '--diff-filter=AM', f'origin/{base_branch}..HEAD'])
        if not files_result['success']:
            return jsonify({'success': False, 'error': 'Failed to get changed files'}), 500

        changed_files = [f for f in files_result['stdout'].strip().split('\n') if f]

        # Exclude files that shouldn't be in PRs (filter BEFORE count check)
        exclude_patterns = [
            '__pycache__', '.pyc', '.pyo',
            'conversation_logs/', 'session_end_',
            '.log', 'logs/',
            'host_monitor_data.json',
            '.env.local', '.claude/settings.local'
        ]
        filtered_files = []
        excluded_files = []
        for f in changed_files:
            should_exclude = any(p in f for p in exclude_patterns)
            if should_exclude:
                excluded_files.append(f)
            else:
                filtered_files.append(f)
        changed_files = filtered_files
        total_files = len(changed_files)

        if total_files <= 150:
            return jsonify({
                'success': True,
                'needs_split': False,
                'total_files': total_files,
                'excluded_files': len(excluded_files),
                'message': f'File count ({total_files}) is within GitHub\'s display limit. No split needed.'
            })

        # Define category patterns for grouping (order matters - more specific first)
        categories = {
            'mcp_server': {
                'name': 'MCP Server & Goose',
                'patterns': ['mcp_server', 'goose/', '050_mcp'],
                'files': [],
                'description': 'Model Context Protocol server and Goose CLI integration'
            },
            'consciousness': {
                'name': 'Consciousness & Command',
                'patterns': ['consciousness', 'archie_core', 'command_interface', 'command_router',
                           'intent_parser', 'voice_synthesis', 'team_consensus', 'team_discussion',
                           '056_', '057_', '059_', '060_', '061_'],
                'files': [],
                'description': 'Command interface, consciousness system, multi-agent orchestration'
            },
            'node_bridge': {
                'name': 'Node Network & Bridge',
                'patterns': ['node_client', 'node_router', 'bridge/', 'pool_management', 'archie_pool',
                           'archie_bridge', '067_', '068_', '070_'],
                'files': [],
                'description': 'Distributed node network, AI bridge, mining pool'
            },
            'system_ops': {
                'name': 'System Operations',
                'patterns': ['system_operations', 'host_monitor', '071_', 'security_network'],
                'files': [],
                'description': 'Host machine administration and monitoring'
            },
            'website_figma': {
                'name': 'Website Studio & Figma',
                'patterns': ['website_studio', 'website_designer', 'figma/', 'figma.html'],
                'files': [],
                'description': 'Website designer and Figma integration'
            },
            'social_media': {
                'name': 'Social Media Module',
                'patterns': ['social_media', '025_social'],
                'files': [],
                'description': 'Social media management and analytics'
            },
            'creation_tools': {
                'name': 'Creation Tools',
                'patterns': ['game_studio', 'content_studio', 'media_studio', 'project_builder'],
                'files': [],
                'description': 'Game, content, media studios and project builder'
            },
            'dev_tools': {
                'name': 'Development Tools',
                'patterns': ['coderabbit', 'testing_suite', 'fine_tuning', 'cursor_integration',
                           'sandbox', 'ide_integration', 'code_editor'],
                'files': [],
                'description': 'CodeRabbit, testing, fine-tuning, IDE integration'
            },
            'business_tools': {
                'name': 'Business Tools',
                'patterns': ['call_center', '/crm', 'crm.html', 'email_manager', 'invoicing',
                           'scheduler', 'store_builder', 'hr_management', 'analytics.html',
                           'automations'],
                'files': [],
                'description': 'CRM, call center, email, invoicing, scheduling'
            },
            'standalone_apps': {
                'name': 'Standalone Apps',
                'patterns': ['stockbot', 'therapy', 'fitness', 'doc.html', '/doc/', 'iaae',
                           'standalone_apps_nav'],
                'files': [],
                'description': 'StockBot, therapy, fitness, DOC, IAAE compliance'
            },
            'team_blueprint': {
                'name': 'Team & Blueprint',
                'patterns': ['team_management', 'blueprint/', 'blueprint.html'],
                'files': [],
                'description': 'Team management and blueprint module'
            },
            'ai_bridge': {
                'name': 'AI Bridge Core',
                'patterns': ['ai_bridge/', 'ethics_monitor', 'smart_router', 'nl_code_generator',
                           'knowledge_retrieval', 'archie_bridge'],
                'files': [],
                'description': 'AI model routing, ethics, code generation'
            },
            'database': {
                'name': 'Database & Migrations',
                'patterns': ['database/', 'migrations/'],
                'files': [],
                'description': 'Database schemas and migration scripts'
            },
            'templates_ui': {
                'name': 'Templates & UI',
                'patterns': ['templates/base', 'templates/dashboard', 'templates/login',
                           'templates/includes', 'templates/admin'],
                'files': [],
                'description': 'Base templates, dashboard, navigation includes'
            },
            'static_assets': {
                'name': 'Static Assets',
                'patterns': ['/static/', 'platform_v2/static', 'archie-theme', 'n8n_custom_theme', 'n8n_theme_userscript'],
                'files': [],
                'description': 'CSS, JavaScript, theme files'
            },
            'backup_admin': {
                'name': 'Backup & Admin',
                'patterns': ['backup_manager', 'admin_backups', 'account_center'],
                'files': [],
                'description': 'Backup management and admin utilities'
            },
            'improvements': {
                'name': 'Improvements System',
                'patterns': ['improvements', 'improvement_'],
                'files': [],
                'description': 'Improvements lab and workflow'
            },
            'conversation': {
                'name': 'Conversation & Triage',
                'patterns': ['conversation_triage/', 'conversation_ingest', 'archie_chat'],
                'files': [],
                'description': 'Conversation handling and triage system'
            },
            'obsidian': {
                'name': 'Obsidian Integration',
                'patterns': ['obsidian'],
                'files': [],
                'description': 'Obsidian vault and note editor'
            },
            'scripts_config': {
                'name': 'Scripts & Config',
                'patterns': ['scripts/', 'docker-compose', '.gitignore', 'requirements.txt',
                           '.env', 'config.py'],
                'files': [],
                'description': 'Shell scripts, Docker, configuration files'
            },
            'docs': {
                'name': 'Documentation',
                'patterns': ['docs/', 'CHANGELOG', 'README', '.md'],
                'files': [],
                'description': 'Documentation and markdown files'
            },
            'core_platform': {
                'name': 'Core Platform',
                'patterns': ['app.py', 'rbac.py', 'module_registry', 'llm_monitor',
                           'shift_conflict', 'unified_knowledge', 'dashboard_generator'],
                'files': [],
                'description': 'Core application files (app.py, rbac, registry)'
            },
            'deprecated': {
                'name': 'Deprecated Files',
                'patterns': ['_deprecated', 'deprecated'],
                'files': [],
                'description': 'Deprecated and legacy code'
            }
        }

        # Categorize each file (check patterns in order)
        uncategorized = []
        for file_path in changed_files:
            categorized = False
            for cat_key, cat_data in categories.items():
                for pattern in cat_data['patterns']:
                    if pattern.lower() in file_path.lower():
                        cat_data['files'].append(file_path)
                        categorized = True
                        break
                if categorized:
                    break
            if not categorized:
                uncategorized.append(file_path)

        # Create miscellaneous category for truly uncategorized files
        if uncategorized:
            categories['miscellaneous'] = {
                'name': 'Miscellaneous',
                'patterns': [],
                'files': uncategorized,
                'description': 'Other files not matching specific categories'
            }

        # Build suggested splits (only include non-empty categories)
        suggested_splits = []
        for cat_key, cat_data in categories.items():
            if cat_data['files']:
                suggested_splits.append({
                    'id': cat_key,
                    'name': cat_data['name'],
                    'description': cat_data['description'],
                    'file_count': len(cat_data['files']),
                    'files': sorted(cat_data['files']),
                    'branch_name': f"feature/pr-{cat_key.replace('_', '-')}"
                })

        # Sort by file count descending
        suggested_splits.sort(key=lambda x: x['file_count'], reverse=True)

        return jsonify({
            'success': True,
            'needs_split': len(changed_files) > 150,
            'total_files': len(changed_files),
            'excluded_files': len(excluded_files),
            'current_branch': current_branch,
            'base_branch': base_branch,
            'suggested_splits': suggested_splits,
            'split_count': len([s for s in suggested_splits if s['file_count'] > 0])
        })

    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@coderabbit_bp.route('/api/git/create-split-branch', methods=['POST'])
@login_required
def git_create_split_branch():
    """
    Create a new branch with only the specified files from the current branch.
    Uses git checkout to copy specific files from the feature branch to a new branch.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    branch_name = data.get('branch_name')
    files = data.get('files', [])
    source_branch = data.get('source_branch')
    base_branch = data.get('base_branch', 'main')
    commit_message = data.get('commit_message', 'Split PR: Auto-generated branch')

    if not branch_name or not files or not source_branch:
        return jsonify({'success': False, 'error': 'branch_name, files, and source_branch are required'}), 400

    try:
        # Store current branch to return to
        current_result = run_git_command(['branch', '--show-current'])
        original_branch = current_result['stdout'].strip()

        # Create new branch from base
        run_git_command(['checkout', base_branch])
        create_result = run_git_command(['checkout', '-b', branch_name])
        if not create_result['success']:
            # Return to original branch
            run_git_command(['checkout', original_branch])
            return jsonify({'success': False, 'error': f'Failed to create branch: {create_result.get("stderr", "")}'})

        # Checkout files from source branch
        checkout_result = run_git_command(['checkout', source_branch, '--'] + files)
        if not checkout_result['success']:
            # Cleanup: delete the branch and return
            run_git_command(['checkout', original_branch])
            run_git_command(['branch', '-D', branch_name])
            return jsonify({'success': False, 'error': f'Failed to checkout files: {checkout_result.get("stderr", "")}'})

        # Stage all files
        run_git_command(['add', '-A'])

        # Commit
        commit_result = run_git_command(['commit', '-m', commit_message])
        if not commit_result['success']:
            run_git_command(['checkout', original_branch])
            run_git_command(['branch', '-D', branch_name])
            return jsonify({'success': False, 'error': f'Failed to commit: {commit_result.get("stderr", "")}'})

        # Push to remote
        push_result = run_git_command(['push', '-u', 'origin', branch_name])

        # Return to original branch
        run_git_command(['checkout', original_branch])

        return jsonify({
            'success': True,
            'branch_name': branch_name,
            'files_count': len(files),
            'pushed': push_result['success'],
            'pr_url': f'https://github.com/KytranKatarn/archie-platform/pull/new/{branch_name}'
        })

    except Exception as e:
        import traceback
        # Try to return to original branch
        try:
            run_git_command(['checkout', original_branch])
        except:
            pass
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


# =============================================================================
# BRANCH MANAGEMENT ENDPOINTS
# =============================================================================

@coderabbit_bp.route('/api/git/branches')
def get_git_branches():
    """
    List all local and remote branches.
    Returns current branch, local branches with tracking info, and remote branches.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    try:
        # Get current branch
        current_result = run_git_command(['branch', '--show-current'])
        current_branch = current_result['stdout'].strip() if current_result['success'] else 'unknown'

        # Get local branches with tracking info
        local_result = run_git_command(['branch', '-vv', '--format=%(refname:short)|%(upstream:short)|%(upstream:track)|%(objectname:short)'])
        local_branches = []
        if local_result['success'] and local_result['stdout'].strip():
            for line in local_result['stdout'].strip().split('\n'):
                if line:
                    parts = line.split('|')
                    name = parts[0] if len(parts) > 0 else ''
                    upstream = parts[1] if len(parts) > 1 else ''
                    track = parts[2] if len(parts) > 2 else ''
                    commit = parts[3] if len(parts) > 3 else ''
                    if name:
                        local_branches.append({
                            'name': name,
                            'current': name == current_branch,
                            'upstream': upstream,
                            'track': track,  # e.g., "[ahead 2]" or "[behind 1]"
                            'commit': commit
                        })

        # Get remote branches
        remote_result = run_git_command(['branch', '-r', '--format=%(refname:short)'])
        remote_branches = []
        if remote_result['success'] and remote_result['stdout'].strip():
            for line in remote_result['stdout'].strip().split('\n'):
                if line and not line.endswith('/HEAD'):
                    remote_branches.append({'name': line.strip()})

        return jsonify({
            'success': True,
            'current': current_branch,
            'local': local_branches,
            'remote': remote_branches
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/create-branch', methods=['POST'])
@login_required
def git_create_branch():
    """
    Create a new branch.
    Optionally checkout to the new branch after creation.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    data = request.get_json() or {}
    branch_name = data.get('name', '').strip()
    base_branch = data.get('base', 'HEAD')
    checkout = data.get('checkout', True)

    # Validate branch name
    if not branch_name:
        return jsonify({'success': False, 'error': 'Branch name is required'}), 400

    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9/_.-]*$', branch_name):
        return jsonify({'success': False, 'error': 'Invalid branch name. Use letters, numbers, /, _, -, .'}), 400

    # Check if branch already exists
    check_result = run_git_command(['branch', '--list', branch_name])
    if check_result['success'] and check_result['stdout'].strip():
        return jsonify({'success': False, 'error': f"Branch '{branch_name}' already exists"}), 400

    try:
        # Create the branch
        create_result = run_git_command(['branch', branch_name, base_branch])

        if not create_result['success']:
            return jsonify({
                'success': False,
                'error': create_result['stderr'] or 'Failed to create branch'
            }), 400

        message = f"Created branch '{branch_name}'"

        # Optionally checkout to the new branch
        if checkout:
            checkout_result = run_git_command(['checkout', branch_name])
            if checkout_result['success']:
                message += f" and switched to it"
            else:
                message += f" (but failed to switch: {checkout_result['stderr']})"

        return jsonify({
            'success': True,
            'message': message,
            'branch': branch_name
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/checkout', methods=['POST'])
@login_required
def git_checkout():
    """
    Switch to a different branch.
    Warns if there are uncommitted changes.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    data = request.get_json() or {}
    branch = data.get('branch', '').strip()
    force = data.get('force', False)

    if not branch:
        return jsonify({'success': False, 'error': 'Branch name is required'}), 400

    try:
        # Check for uncommitted changes (unless force)
        if not force:
            status_result = run_git_command(['status', '--porcelain'])
            if status_result['success'] and status_result['stdout'].strip():
                return jsonify({
                    'success': False,
                    'error': 'Uncommitted changes exist. Commit or stash before switching, or use force.',
                    'has_changes': True
                }), 400

        # Perform checkout
        checkout_result = run_git_command(['checkout', branch])

        if checkout_result['success']:
            return jsonify({
                'success': True,
                'message': f"Switched to branch '{branch}'",
                'branch': branch
            })
        else:
            return jsonify({
                'success': False,
                'error': checkout_result['stderr'] or 'Failed to switch branch'
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/git/delete-branch', methods=['POST'])
@login_required
def git_delete_branch():
    """
    Delete a local branch.
    Protected branches (main, master) cannot be deleted.
    Current branch cannot be deleted.
    """
    if not GIT_REPO_PATH:
        return jsonify({'success': False, 'error': 'Git repository not found'}), 400

    data = request.get_json() or {}
    branch = data.get('branch', '').strip()
    force = data.get('force', False)

    if not branch:
        return jsonify({'success': False, 'error': 'Branch name is required'}), 400

    # Protected branches
    protected_branches = ['main', 'master', 'develop', 'production']
    if branch in protected_branches:
        return jsonify({
            'success': False,
            'error': f"Cannot delete protected branch '{branch}'"
        }), 400

    try:
        # Check if it's the current branch
        current_result = run_git_command(['branch', '--show-current'])
        current_branch = current_result['stdout'].strip() if current_result['success'] else ''

        if branch == current_branch:
            return jsonify({
                'success': False,
                'error': 'Cannot delete the currently checked out branch'
            }), 400

        # Delete the branch
        flag = '-D' if force else '-d'
        delete_result = run_git_command(['branch', flag, branch])

        if delete_result['success']:
            return jsonify({
                'success': True,
                'message': f"Deleted branch '{branch}'"
            })
        else:
            error_msg = delete_result['stderr'] or 'Failed to delete branch'
            # Check if it's because the branch is not fully merged
            if 'not fully merged' in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': f"Branch '{branch}' is not fully merged. Use force delete if you're sure.",
                    'not_merged': True
                }), 400
            return jsonify({'success': False, 'error': error_msg}), 400

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# GITHUB ISSUES ENDPOINTS
# =============================================================================

@coderabbit_bp.route('/api/github/issues')
@login_required
def get_github_issues():
    """
    List repository issues from GitHub.
    Supports filtering by state (open, closed, all) and labels.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    state = request.args.get('state', 'open')  # open, closed, all
    labels = request.args.get('labels', '')
    repo = request.args.get('repo', GITHUB_REPOS[0])

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        params = {
            'state': state,
            'per_page': 50,
            'sort': 'updated',
            'direction': 'desc'
        }
        if labels:
            params['labels'] = labels

        response = requests.get(
            f'https://api.github.com/repos/{repo}/issues',
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code == 200:
            issues = response.json()
            # Filter out pull requests (GitHub API returns PRs as issues)
            issues = [i for i in issues if 'pull_request' not in i]

            # Simplify the response
            simplified_issues = []
            for issue in issues:
                simplified_issues.append({
                    'number': issue['number'],
                    'title': issue['title'],
                    'state': issue['state'],
                    'user': issue['user']['login'],
                    'labels': [l['name'] for l in issue.get('labels', [])],
                    'created_at': issue['created_at'],
                    'updated_at': issue['updated_at'],
                    'comments': issue.get('comments', 0),
                    'url': issue['html_url'],
                    'body': issue.get('body', '')[:500] if issue.get('body') else ''
                })

            return jsonify({
                'success': True,
                'issues': simplified_issues,
                'total': len(simplified_issues),
                'repo': repo
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/github/issues', methods=['POST'])
@login_required
def create_github_issue():
    """
    Create a new GitHub issue.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    data = request.get_json() or {}
    title = data.get('title', '').strip()
    body = data.get('body', '')
    labels = data.get('labels', [])
    repo = data.get('repo', GITHUB_REPOS[0])

    if not title:
        return jsonify({'success': False, 'error': 'Issue title is required'}), 400

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        payload = {'title': title, 'body': body}
        if labels:
            payload['labels'] = labels

        response = requests.post(
            f'https://api.github.com/repos/{repo}/issues',
            headers=headers,
            json=payload,
            timeout=15
        )

        if response.status_code == 201:
            issue = response.json()
            return jsonify({
                'success': True,
                'issue': {
                    'number': issue['number'],
                    'title': issue['title'],
                    'url': issue['html_url']
                },
                'message': f"Issue #{issue['number']} created successfully"
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code} - {response.text}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/github/issues/<int:issue_number>', methods=['PATCH'])
@login_required
def update_github_issue(issue_number):
    """
    Update a GitHub issue (close/reopen).
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    data = request.get_json() or {}
    state = data.get('state', 'open')  # open or closed
    repo = data.get('repo', GITHUB_REPOS[0])

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        response = requests.patch(
            f'https://api.github.com/repos/{repo}/issues/{issue_number}',
            headers=headers,
            json={'state': state},
            timeout=15
        )

        if response.status_code == 200:
            action = 'closed' if state == 'closed' else 'reopened'
            return jsonify({
                'success': True,
                'message': f"Issue #{issue_number} {action}"
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# GITHUB ACTIONS ENDPOINTS
# =============================================================================

@coderabbit_bp.route('/api/github/actions/runs')
@login_required
def get_workflow_runs():
    """
    List recent workflow runs from GitHub Actions.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    repo = request.args.get('repo', GITHUB_REPOS[0])

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        response = requests.get(
            f'https://api.github.com/repos/{repo}/actions/runs',
            headers=headers,
            params={'per_page': 20},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            runs = []
            for run in data.get('workflow_runs', []):
                runs.append({
                    'id': run['id'],
                    'name': run['name'],
                    'status': run['status'],
                    'conclusion': run.get('conclusion'),
                    'branch': run['head_branch'],
                    'event': run['event'],
                    'created_at': run['created_at'],
                    'updated_at': run['updated_at'],
                    'url': run['html_url'],
                    'workflow_id': run['workflow_id']
                })

            return jsonify({
                'success': True,
                'runs': runs,
                'total': data.get('total_count', 0),
                'repo': repo
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/github/actions/workflows')
@login_required
def get_workflows():
    """
    List available workflows in the repository.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    repo = request.args.get('repo', GITHUB_REPOS[0])

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        response = requests.get(
            f'https://api.github.com/repos/{repo}/actions/workflows',
            headers=headers,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            workflows = []
            for wf in data.get('workflows', []):
                workflows.append({
                    'id': wf['id'],
                    'name': wf['name'],
                    'path': wf['path'],
                    'state': wf['state']
                })

            return jsonify({
                'success': True,
                'workflows': workflows,
                'repo': repo
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/github/actions/runs/<int:run_id>/rerun', methods=['POST'])
@login_required
def rerun_workflow(run_id):
    """
    Re-run a failed workflow.
    """
    if not GITHUB_TOKEN:
        return jsonify({'success': False, 'error': 'GitHub token not configured'}), 400

    if not GITHUB_REPOS:
        return jsonify({'success': False, 'error': 'No GitHub repositories configured'}), 400

    data = request.get_json() or {}
    repo = data.get('repo', GITHUB_REPOS[0])

    try:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }

        response = requests.post(
            f'https://api.github.com/repos/{repo}/actions/runs/{run_id}/rerun',
            headers=headers,
            timeout=15
        )

        if response.status_code == 201:
            return jsonify({
                'success': True,
                'message': f'Workflow run #{run_id} has been re-triggered'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'GitHub API error: {response.status_code}'
            }), response.status_code

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# MULTI-AGENT CODE REVIEW SYSTEM (Phase 72 - Node Cluster Integration)
# Uses Team Management agents with Node Cluster for dynamic LLM routing
# ============================================================================

# Import node router for dynamic model routing
try:
    sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
    from node_router import get_ollama_url, log_model_request, get_nodes_with_model
    NODE_ROUTING_AVAILABLE = True
    logger.info("Node router loaded for multi-agent reviews")
except ImportError as e:
    NODE_ROUTING_AVAILABLE = False
    logger.warning(f"Node router not available: {e}")

# In-memory store for multi-agent reviews
multi_agent_reviews = {}

# Skill to specialty mapping for code review agents
REVIEW_SKILL_MAPPING = {
    'security': {
        'skills': ['security', 'cybersecurity', 'penetration_testing'],
        'focus': ['SQL injection', 'XSS', 'auth bypass', 'secrets exposure', 'OWASP top 10'],
        'prompt_prefix': 'You are a security expert reviewing code for vulnerabilities. Focus on: '
    },
    'code_review': {
        'skills': ['code_review', 'code_quality', 'best_practices'],
        'focus': ['SOLID principles', 'DRY violations', 'code smells', 'naming conventions', 'documentation'],
        'prompt_prefix': 'You are a senior developer reviewing code quality. Focus on: '
    },
    'architecture': {
        'skills': ['architecture', 'system_design', 'api_design'],
        'focus': ['design patterns', 'separation of concerns', 'modularity', 'dependencies', 'scalability'],
        'prompt_prefix': 'You are a software architect reviewing code structure. Focus on: '
    },
    'bug_fixing': {
        'skills': ['bug_fixing', 'debugging', 'testing'],
        'focus': ['edge cases', 'error handling', 'null checks', 'race conditions', 'memory leaks'],
        'prompt_prefix': 'You are a QA engineer reviewing code for potential bugs. Focus on: '
    }
}


def get_review_agents_from_team_management(specialty: str = None, limit: int = 4):
    """
    Get code review capable agents from Team Management.
    Uses agent skills to find suitable reviewers.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build skill filter
        if specialty and specialty in REVIEW_SKILL_MAPPING:
            skills = REVIEW_SKILL_MAPPING[specialty]['skills']
            skill_filter = "AND s.skill_name = ANY(%s)"
            params = [skills, limit]
        else:
            # Get agents with any code review related skills
            all_skills = []
            for spec in REVIEW_SKILL_MAPPING.values():
                all_skills.extend(spec['skills'])
            skill_filter = "AND s.skill_name = ANY(%s)"
            params = [list(set(all_skills)), limit]

        cur.execute(f"""
            SELECT DISTINCT
                a.id,
                a.name,
                a.first_name,
                a.last_name,
                a.model,
                a.system_prompt,
                a.title,
                s.skill_name,
                s.proficiency_level,
                s.skill_category
            FROM agents a
            JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
              AND a.model IS NOT NULL
              {skill_filter}
            ORDER BY s.proficiency_level DESC, a.name
            LIMIT %s
        """, params)

        agents = cur.fetchall()
        cur.close()
        conn.close()

        # Convert to review agent format
        review_agents = {}
        for agent in agents:
            agent_key = f"agent_{agent['id']}"
            skill = agent['skill_name']

            # Find matching specialty config
            specialty_config = None
            for spec_name, spec_data in REVIEW_SKILL_MAPPING.items():
                if skill in spec_data['skills']:
                    specialty_config = spec_data
                    break

            if not specialty_config:
                specialty_config = REVIEW_SKILL_MAPPING.get('code_review', {})

            review_agents[agent_key] = {
                'id': agent['id'],
                'name': agent['name'] or f"{agent['first_name']} {agent['last_name']}",
                'model': agent['model'],
                'specialty': agent['skill_category'] or 'general',
                'skill': skill,
                'proficiency': agent['proficiency_level'],
                'focus': specialty_config.get('focus', []),
                'prompt_prefix': specialty_config.get('prompt_prefix', 'You are reviewing code. Focus on: '),
                'system_prompt': agent['system_prompt']
            }

        return review_agents

    except Exception as e:
        logger.error(f"Error getting review agents from Team Management: {e}")
        return {}


def get_available_nodes_for_review():
    """Get all nodes with their available models for code review"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                n.node_id,
                n.node_name,
                n.vpn_ip,
                n.status,
                n.current_load,
                n.bridge_priority,
                n.gpu_available,
                n.gpu_model,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'model_name', m.model_name,
                            'is_available', m.is_available,
                            'avg_response_ms', m.avg_response_ms
                        )
                    ) FILTER (WHERE m.model_name IS NOT NULL),
                    '[]'
                ) as models
            FROM remote_nodes n
            LEFT JOIN node_ollama_models m ON n.node_id = m.node_id AND m.is_available = true
            WHERE n.bridge_enabled = true
              AND n.status = 'online'
              AND n.approval_status = 'approved'
            GROUP BY n.node_id, n.node_name, n.vpn_ip, n.status, n.current_load,
                     n.bridge_priority, n.gpu_available, n.gpu_model
            ORDER BY n.current_load ASC, n.bridge_priority DESC
        """)

        nodes = cur.fetchall()
        cur.close()
        conn.close()

        return nodes

    except Exception as e:
        logger.error(f"Error getting available nodes: {e}")
        return []


@coderabbit_bp.route('/api/multi-agent/nodes')
@login_required
def get_review_nodes():
    """Get available nodes and their models for code review"""
    nodes = get_available_nodes_for_review()

    # Calculate totals
    total_models = set()
    for node in nodes:
        for model in node.get('models', []):
            if model.get('is_available'):
                total_models.add(model['model_name'])

    return jsonify({
        'success': True,
        'nodes': [dict(n) for n in nodes],
        'node_count': len(nodes),
        'total_models': len(total_models),
        'model_list': sorted(list(total_models)),
        'node_routing_available': NODE_ROUTING_AVAILABLE
    })


@coderabbit_bp.route('/api/multi-agent/review', methods=['POST'])
@login_required
def start_multi_agent_review():
    """
    Start a multi-agent code review

    POST body:
    {
        "code": "code to review",
        "file_path": "path/to/file.py",
        "agents": ["security_expert", "performance_analyst"],  // optional
        "context": "optional context about the code"
    }
    """
    try:
        data = request.get_json() or {}
        code = data.get('code', '')
        file_path = data.get('file_path', 'unknown')
        selected_agents = data.get('agents', list(REVIEW_AGENTS.keys()))
        context = data.get('context', '')

        if not code:
            return jsonify({'success': False, 'error': 'No code provided'}), 400

        # Generate review ID
        import os as os_module
        review_id = f"mar_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os_module.urandom(4).hex()}"

        # Initialize review record
        review = {
            'id': review_id,
            'file_path': file_path,
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'agents_selected': selected_agents,
            'agent_reviews': {},
            'consensus': None,
            'final_issues': []
        }
        multi_agent_reviews[review_id] = review

        # Start async review
        import threading
        thread = threading.Thread(
            target=_run_multi_agent_review,
            args=(review_id, code, file_path, selected_agents, context)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'review_id': review_id,
            'message': f'Multi-agent review started with {len(selected_agents)} agents'
        })

    except Exception as e:
        logger.error(f"Multi-agent review error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@coderabbit_bp.route('/api/multi-agent/review/<review_id>')
@login_required
def get_multi_agent_review(review_id):
    """Get status and results of a multi-agent review"""
    if review_id in multi_agent_reviews:
        return jsonify({
            'success': True,
            'review': multi_agent_reviews[review_id]
        })
    return jsonify({'success': False, 'error': 'Review not found'}), 404


@coderabbit_bp.route('/api/multi-agent/agents')
@login_required
def list_review_agents():
    """Get available review agents from Team Management with their specializations"""
    specialty = request.args.get('specialty')  # Optional filter
    limit = request.args.get('limit', 8, type=int)

    # Get agents from Team Management
    team_agents = get_review_agents_from_team_management(specialty=specialty, limit=limit)

    agents = []
    for agent_key, config in team_agents.items():
        # Check if the agent's model is available on any node
        model_available = False
        if NODE_ROUTING_AVAILABLE:
            try:
                nodes = get_nodes_with_model(config['model'])
                model_available = len(nodes) > 0
            except Exception:
                model_available = False

        agents.append({
            'id': agent_key,
            'agent_id': config.get('id'),
            'name': config['name'],
            'model': config['model'],
            'specialty': config['specialty'],
            'skill': config.get('skill'),
            'proficiency': config.get('proficiency', 0),
            'focus_areas': config['focus'],
            'model_available': model_available
        })

    # Get available specialties
    specialties = list(REVIEW_SKILL_MAPPING.keys())

    return jsonify({
        'success': True,
        'agents': agents,
        'agent_count': len(agents),
        'specialties': specialties,
        'source': 'team_management',
        'node_routing': NODE_ROUTING_AVAILABLE
    })


def _run_multi_agent_review(review_id: str, code: str, file_path: str, agents: list, context: str):
    """
    Execute multi-agent review with PARALLEL agent execution.
    Uses Team Management agents and Node Cluster for dynamic LLM routing.
    """
    review = multi_agent_reviews[review_id]

    try:
        # Import AI bridge for LLM calls
        sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
        from archie_bridge import archie_bridge

        # Get all review agents from Team Management
        team_agents = get_review_agents_from_team_management(limit=10)

        all_issues = []
        review_lock = threading.Lock()

        def run_single_agent(agent_key):
            """Run a single agent's review - worker function for parallel execution"""
            # Check if agent_key is from Team Management or legacy format
            if agent_key in team_agents:
                agent_config = team_agents[agent_key]
            else:
                # Fallback for legacy agent IDs - try to find by ID
                matching = [a for a in team_agents.values() if str(a.get('id')) == agent_key.replace('agent_', '')]
                if matching:
                    agent_config = matching[0]
                else:
                    logger.warning(f"Agent {agent_key} not found in Team Management")
                    return None

            model = agent_config.get('model', 'deepseek-coder-v2:16b')
            agent_name = agent_config.get('name', 'Unknown Agent')

            # Check model availability via Node Cluster
            node_id = None
            node_name = None
            if NODE_ROUTING_AVAILABLE:
                try:
                    ollama_url, node_id = get_ollama_url(model)
                    if node_id:
                        node_name = node_id
                        logger.info(f"Agent {agent_name} using model {model} on node {node_id}")
                except Exception as e:
                    logger.warning(f"Node routing failed for {model}: {e}")

            # Build agent-specific prompt
            prompt_prefix = agent_config.get('prompt_prefix', 'You are reviewing code. Focus on: ')
            focus_areas = agent_config.get('focus', [])
            system_prompt = agent_config.get('system_prompt', '')

            prompt = f"""{prompt_prefix}
{', '.join(focus_areas)}

{f'Agent Context: {system_prompt}' if system_prompt else ''}

File: {file_path}
{f'Context: {context}' if context else ''}

Code to review:
```
{code[:4000]}
```

Analyze this code and identify issues in your area of expertise.
For each issue found, provide:
1. Line number (if applicable)
2. Issue type (from your focus areas)
3. Severity (critical/high/medium/low)
4. Description of the issue
5. Suggested fix

Format your response as JSON:
{{
    "issues": [
        {{
            "line": 10,
            "type": "security",
            "severity": "high",
            "message": "Description",
            "suggestion": "How to fix"
        }}
    ],
    "summary": "Brief summary of findings"
}}
"""

            try:
                start_time = datetime.now()

                # Call AI Bridge with the agent's model
                # CRITICAL: Pass agent_id for HR/IAAE tracking via token_usage_log
                result = archie_bridge(
                    prompt=prompt,
                    user_id=1,
                    agent_id=agent_config.get('id'),  # Track which agent did this work
                    enable_memory=False,
                    force_model=model,
                    try_local_first=True  # Use Node Cluster routing
                )

                elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Log request to node_model_requests if node routing was used
                if NODE_ROUTING_AVAILABLE and node_id:
                    try:
                        log_model_request(
                            node_id=node_id,
                            model_name=model,
                            tokens_in=len(prompt) // 4,  # Estimate
                            tokens_out=len(result.get('response', '')) // 4,
                            response_ms=elapsed_ms,
                            success=result.get('success', False)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log model request: {e}")

                agent_review = {
                    'agent': agent_name,
                    'agent_id': agent_config.get('id'),
                    'model': model,
                    'node_id': node_id,
                    'node_name': node_name,
                    'specialty': agent_config.get('specialty', 'general'),
                    'skill': agent_config.get('skill'),
                    'proficiency': agent_config.get('proficiency', 0),
                    'status': 'completed' if result.get('success') else 'failed',
                    'raw_response': result.get('response', ''),
                    'response_time_ms': elapsed_ms,
                    'issues': [],
                    'summary': ''
                }

                # Parse agent response
                if result.get('success'):
                    parsed = _parse_agent_response(result['response'])
                    agent_review['issues'] = parsed.get('issues', [])
                    agent_review['summary'] = parsed.get('summary', '')

                    # Add agent attribution to issues
                    for issue in agent_review['issues']:
                        issue['found_by'] = agent_key
                        issue['agent_name'] = agent_name
                        issue['agent_model'] = model
                        issue['node_id'] = node_id

                return agent_key, agent_review

            except Exception as e:
                logger.warning(f"Agent {agent_name} failed: {e}")
                return agent_key, {
                    'agent': agent_name,
                    'agent_id': agent_config.get('id'),
                    'model': model,
                    'specialty': agent_config.get('specialty', 'general'),
                    'status': 'failed',
                    'error': str(e),
                    'issues': [],
                    'summary': ''
                }

        # Run all agents IN PARALLEL for faster reviews
        max_workers = min(len(agents), 4)  # Cap at 4 concurrent agents
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_single_agent, agent_id): agent_id for agent_id in agents}

            for future in as_completed(futures):
                result = future.result()
                if result:
                    agent_id, agent_review = result
                    with review_lock:
                        review['agent_reviews'][agent_id] = agent_review
                        # Collect all issues
                        for issue in agent_review.get('issues', []):
                            all_issues.append(issue)

        # Build consensus from all agent findings
        consensus = _build_consensus(all_issues)
        review['consensus'] = consensus
        review['final_issues'] = consensus['confirmed_issues']
        review['status'] = 'completed'
        review['completed_at'] = datetime.now().isoformat()
        review['node_routing_used'] = NODE_ROUTING_AVAILABLE

        # Save to database
        _save_multi_agent_review(review)

    except Exception as e:
        review['status'] = 'failed'
        review['error'] = str(e)
        logger.error(f"Multi-agent review failed: {e}")


def _parse_agent_response(response: str) -> dict:
    """Parse agent's JSON response"""
    try:
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        pass

    # Fallback: extract issues manually
    issues = []
    lines = response.split('\n')

    current_issue = {}
    for line in lines:
        line = line.strip()
        if 'line' in line.lower() and ':' in line:
            if current_issue:
                issues.append(current_issue)
            current_issue = {'line': 0, 'type': 'general', 'severity': 'medium', 'message': '', 'suggestion': ''}
            try:
                current_issue['line'] = int(re.search(r'\d+', line).group())
            except Exception:
                pass
        elif 'severity' in line.lower():
            for sev in ['critical', 'high', 'medium', 'low']:
                if sev in line.lower():
                    current_issue['severity'] = sev
                    break
        elif current_issue and line:
            if not current_issue.get('message'):
                current_issue['message'] = line
            else:
                current_issue['suggestion'] = line

    if current_issue and current_issue.get('message'):
        issues.append(current_issue)

    return {'issues': issues, 'summary': ''}


def _build_consensus(all_issues: list) -> dict:
    """Build consensus from multiple agent reviews"""

    # Group issues by similarity (same line + similar message)
    issue_groups = {}

    for issue in all_issues:
        key = f"{issue.get('line', 0)}_{issue.get('type', 'general')}"

        if key not in issue_groups:
            issue_groups[key] = {
                'issues': [],
                'agents': set(),
                'severities': []
            }

        issue_groups[key]['issues'].append(issue)
        issue_groups[key]['agents'].add(issue.get('found_by', 'unknown'))
        issue_groups[key]['severities'].append(issue.get('severity', 'medium'))

    # Build confirmed issues
    confirmed_issues = []
    severity_order = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}

    for key, group in issue_groups.items():
        agreement_count = len(group['agents'])
        max_severity = max(group['severities'], key=lambda s: severity_order.get(s, 0))
        best_issue = max(group['issues'], key=lambda i: len(i.get('message', '')))

        confirmed_issue = {
            'line': best_issue.get('line', 0),
            'type': best_issue.get('type', 'general'),
            'severity': max_severity,
            'message': best_issue.get('message', ''),
            'suggestion': best_issue.get('suggestion', ''),
            'agreement_count': agreement_count,
            'agreeing_agents': list(group['agents']),
            'confidence': 'high' if agreement_count >= 2 else 'medium'
        }

        confirmed_issues.append(confirmed_issue)

    confirmed_issues.sort(
        key=lambda i: (severity_order.get(i['severity'], 0), i['agreement_count']),
        reverse=True
    )

    return {
        'total_issues': len(confirmed_issues),
        'high_confidence': len([i for i in confirmed_issues if i['confidence'] == 'high']),
        'agents_participated': len(set(a for i in all_issues for a in [i.get('found_by')])),
        'confirmed_issues': confirmed_issues
    }


def _save_multi_agent_review(review: dict):
    """Save multi-agent review to database and create code_issues"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Save to multi_agent_reviews table
        cur.execute("""
            INSERT INTO multi_agent_reviews
            (review_id, file_path, code_snippet, context, status, agents_selected,
             agent_reviews, consensus, final_issues, node_routing_used, started_at, completed_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (review_id) DO UPDATE
            SET status = EXCLUDED.status,
                completed_at = EXCLUDED.completed_at,
                agent_reviews = EXCLUDED.agent_reviews,
                consensus = EXCLUDED.consensus,
                final_issues = EXCLUDED.final_issues
            RETURNING id
        """, (
            review['id'],
            review.get('file_path', 'unknown'),
            review.get('code_snippet', '')[:5000],  # Limit code snippet size
            review.get('context', ''),
            review['status'],
            json.dumps(review.get('agents_selected', [])),
            json.dumps(review.get('agent_reviews', {})),
            json.dumps(review.get('consensus', {})),
            json.dumps(review.get('final_issues', [])),
            review.get('node_routing_used', False),
            review.get('started_at'),
            review.get('completed_at'),
            'system'
        ))

        mar_id = cur.fetchone()['id'] if cur.rowcount > 0 else None

        # Create code_issues from final_issues (high confidence ones)
        final_issues = review.get('final_issues', [])
        file_path = review.get('file_path', 'unknown')
        issues_created = 0

        for issue in final_issues:
            # Only create code_issues for high confidence issues
            if issue.get('confidence') == 'high' or issue.get('severity') in ('critical', 'high'):
                # Check if similar issue already exists
                cur.execute("""
                    SELECT id FROM code_issues
                    WHERE file_path = %s
                      AND line_number = %s
                      AND issue_type = %s
                      AND status = 'open'
                    LIMIT 1
                """, (file_path, issue.get('line', 0), issue.get('type', 'general')))

                existing = cur.fetchone()

                if not existing:
                    # Create new code_issue
                    cur.execute("""
                        INSERT INTO code_issues
                        (file_path, line_number, issue_type, severity, message, suggestion, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'open')
                        RETURNING id
                    """, (
                        file_path,
                        issue.get('line', 0),
                        issue.get('type', 'multi_agent'),
                        issue.get('severity', 'medium'),
                        f"[Multi-Agent Review] {issue.get('message', '')}",
                        issue.get('suggestion', '')
                    ))
                    code_issue_id = cur.fetchone()['id']
                    issues_created += 1

                    # Link to multi_agent_review_issues
                    cur.execute("""
                        INSERT INTO multi_agent_review_issues
                        (review_id, code_issue_id, agent_name, line_number, issue_type,
                         severity, message, suggestion, confidence, agreement_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        review['id'],
                        code_issue_id,
                        ', '.join(issue.get('agreeing_agents', ['unknown'])),
                        issue.get('line', 0),
                        issue.get('type', 'general'),
                        issue.get('severity', 'medium'),
                        issue.get('message', ''),
                        issue.get('suggestion', ''),
                        issue.get('confidence', 'medium'),
                        issue.get('agreement_count', 1)
                    ))

        conn.commit()
        cur.close()
        conn.close()

        if issues_created > 0:
            logger.info(f"Multi-agent review {review['id']}: Created {issues_created} code_issues")

    except Exception as e:
        logger.warning(f"Failed to save multi-agent review: {e}")
        import traceback
        traceback.print_exc()
