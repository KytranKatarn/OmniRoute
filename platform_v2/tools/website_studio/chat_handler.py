"""
Website Designer Chat Handler
=============================
Chat-to-code pipeline for natural language website editing.

Provides:
- Site-aware context building
- AI response parsing for file changes
- Diff generation and preview
- Auto-commit on apply

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
"""

import os
import re
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger('archie_platform')

# Repository configuration
WEBSITE_REPO_PATH = '/tmp/website-repo'
ADMIN_WEBSITE_REPO = 'KytranKatarn/kytranempowerment-site'

# System prompt for website editing
WEBSITE_EDITOR_SYSTEM_PROMPT = """You are A.R.C.H.I.E., an AI website designer assistant.
You help users modify their website through natural language commands.

CURRENT SITE STRUCTURE:
{file_tree}

CURRENT FILE CONTENTS:
{file_contents}

When the user requests changes, you MUST:
1. Identify which file(s) need modification
2. Generate the exact code changes needed
3. Return changes in this EXACT format:

<file_changes>
<file path="relative/path/to/file.html">
<change type="replace">
<old_content>
<!-- EXACT content to find and replace - must match exactly -->
</old_content>
<new_content>
<!-- The new content to replace it with -->
</new_content>
</change>
</file>
</file_changes>

For adding new content, use type="insert" with a location:
<change type="insert" location="after" target="</header>">
<new_content>
<!-- Content to insert -->
</new_content>
</change>

For new files, use type="create":
<file path="new-page.html">
<change type="create">
<new_content>
<!-- Full file content -->
</new_content>
</change>
</file>

IMPORTANT RULES:
- Always preserve existing functionality
- Make minimal, targeted changes
- Match whitespace and indentation exactly in old_content
- Explain what you're changing before the <file_changes> block
- If you can't make a change, explain why
"""


def get_site_file_tree(repo_path: str = WEBSITE_REPO_PATH) -> str:
    """
    Get a tree representation of the website files.

    Returns:
        String representation of the file tree
    """
    if not os.path.exists(repo_path):
        return "Repository not cloned. Please pull the repository first."

    tree_lines = []

    def build_tree(path: str, prefix: str = ""):
        items = sorted(os.listdir(path))
        # Filter out git and hidden files
        items = [i for i in items if not i.startswith('.')]

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            item_path = os.path.join(path, item)
            connector = "└── " if is_last else "├── "

            if os.path.isdir(item_path):
                tree_lines.append(f"{prefix}{connector}{item}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                build_tree(item_path, new_prefix)
            else:
                # Add file size indicator
                size = os.path.getsize(item_path)
                size_str = f" ({size} bytes)" if size < 1000 else f" ({size//1024}KB)"
                tree_lines.append(f"{prefix}{connector}{item}{size_str}")

    try:
        build_tree(repo_path)
        return "\n".join(tree_lines) if tree_lines else "Empty repository"
    except Exception as e:
        logger.error(f"Error building file tree: {e}")
        return f"Error reading repository: {str(e)}"


def get_file_contents(repo_path: str = WEBSITE_REPO_PATH, max_files: int = 4, max_chars_per_file: int = 2000) -> str:
    """
    Get contents of key website files for context.
    Limited to keep prompt size manageable for AI models.

    Args:
        repo_path: Path to the repository
        max_files: Maximum number of files to include (default: 4)
        max_chars_per_file: Max characters per file (default: 2000)

    Returns:
        String with file contents
    """
    if not os.path.exists(repo_path):
        return "Repository not available."

    # Priority files - most commonly edited
    priority_files = ['index.html', 'style.css', 'styles.css', 'script.js', 'main.js']
    priority_extensions = ['.html', '.css', '.js']
    contents = []
    files_included = 0

    # First, try to get priority files
    for pf in priority_files:
        if files_included >= max_files:
            break
        file_path = os.path.join(repo_path, pf)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + "\n... [truncated]"
                contents.append(f"=== {pf} ===\n{content}\n")
                files_included += 1
            except Exception as e:
                logger.warning(f"Could not read {pf}: {e}")

    # Then fill remaining slots with other files
    for root, dirs, files in os.walk(repo_path):
        if files_included >= max_files:
            break
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for filename in sorted(files):
            if files_included >= max_files:
                break

            # Skip already included priority files
            rel_path = os.path.relpath(os.path.join(root, filename), repo_path)
            if rel_path in priority_files:
                continue

            # Check if it's a web file
            ext = os.path.splitext(filename)[1].lower()
            if ext not in priority_extensions:
                continue

            file_path = os.path.join(root, filename)

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Truncate large files
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + "\n... [truncated]"

                contents.append(f"=== {rel_path} ===\n{content}\n")
                files_included += 1

            except Exception as e:
                logger.warning(f"Could not read {rel_path}: {e}")

        if files_included >= max_files:
            break

    return "\n".join(contents) if contents else "No web files found."


def build_site_context(repo_path: str = WEBSITE_REPO_PATH) -> Dict:
    """
    Build complete context for AI about the current site state.

    Returns:
        Dictionary with file_tree and file_contents
    """
    return {
        'file_tree': get_site_file_tree(repo_path),
        'file_contents': get_file_contents(repo_path)
    }


def parse_file_changes(ai_response: str) -> List[Dict]:
    """
    Parse AI response to extract file changes.

    Args:
        ai_response: Raw AI response text

    Returns:
        List of change dictionaries with file, type, old_content, new_content
    """
    changes = []

    # Find all <file_changes> blocks
    file_changes_match = re.search(
        r'<file_changes>(.*?)</file_changes>',
        ai_response,
        re.DOTALL
    )

    if not file_changes_match:
        return changes

    file_changes_content = file_changes_match.group(1)

    # Parse each <file> block
    file_pattern = re.compile(
        r'<file\s+path="([^"]+)">(.*?)</file>',
        re.DOTALL
    )

    for file_match in file_pattern.finditer(file_changes_content):
        file_path = file_match.group(1)
        file_content = file_match.group(2)

        # Parse each <change> block within the file
        change_pattern = re.compile(
            r'<change\s+type="(\w+)"(?:\s+location="(\w+)")?(?:\s+target="([^"]*)")?\s*>(.*?)</change>',
            re.DOTALL
        )

        for change_match in change_pattern.finditer(file_content):
            change_type = change_match.group(1)
            location = change_match.group(2)
            target = change_match.group(3)
            change_content = change_match.group(4)

            change_dict = {
                'file': file_path,
                'type': change_type
            }

            if change_type == 'replace':
                # Extract old_content and new_content
                old_match = re.search(
                    r'<old_content>(.*?)</old_content>',
                    change_content,
                    re.DOTALL
                )
                new_match = re.search(
                    r'<new_content>(.*?)</new_content>',
                    change_content,
                    re.DOTALL
                )

                if old_match and new_match:
                    change_dict['old_content'] = old_match.group(1).strip()
                    change_dict['new_content'] = new_match.group(1).strip()

            elif change_type == 'insert':
                new_match = re.search(
                    r'<new_content>(.*?)</new_content>',
                    change_content,
                    re.DOTALL
                )
                if new_match:
                    change_dict['new_content'] = new_match.group(1).strip()
                    change_dict['location'] = location
                    change_dict['target'] = target

            elif change_type == 'create':
                new_match = re.search(
                    r'<new_content>(.*?)</new_content>',
                    change_content,
                    re.DOTALL
                )
                if new_match:
                    change_dict['new_content'] = new_match.group(1).strip()

            if 'new_content' in change_dict:
                changes.append(change_dict)

    return changes


def apply_file_changes(changes: List[Dict], repo_path: str = WEBSITE_REPO_PATH) -> Dict:
    """
    Apply parsed changes to actual files.

    Args:
        changes: List of change dictionaries from parse_file_changes
        repo_path: Path to the repository

    Returns:
        Dictionary with success status and details
    """
    results = {
        'success': True,
        'applied': [],
        'failed': [],
        'files_modified': 0
    }

    for change in changes:
        file_path = change['file']
        full_path = os.path.join(repo_path, file_path)

        # Security: prevent path traversal
        if '..' in file_path:
            results['failed'].append({
                'file': file_path,
                'error': 'Invalid path (traversal attempt)'
            })
            continue

        try:
            if change['type'] == 'create':
                # Create new file
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(change['new_content'])
                results['applied'].append({
                    'file': file_path,
                    'type': 'created'
                })

            elif change['type'] == 'replace':
                # Read current content
                if not os.path.exists(full_path):
                    results['failed'].append({
                        'file': file_path,
                        'error': 'File not found'
                    })
                    continue

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Check if old_content exists
                if change['old_content'] not in content:
                    # Try with normalized whitespace
                    normalized_old = ' '.join(change['old_content'].split())
                    normalized_content = ' '.join(content.split())

                    if normalized_old not in normalized_content:
                        results['failed'].append({
                            'file': file_path,
                            'error': 'Could not find content to replace'
                        })
                        continue
                    else:
                        # Use normalized replacement (risky, warn user)
                        logger.warning(f"Using normalized replacement for {file_path}")

                # Apply replacement
                new_content = content.replace(
                    change['old_content'],
                    change['new_content'],
                    1  # Only replace first occurrence
                )

                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)

                results['applied'].append({
                    'file': file_path,
                    'type': 'modified'
                })

            elif change['type'] == 'insert':
                # Insert content at location
                if not os.path.exists(full_path):
                    results['failed'].append({
                        'file': file_path,
                        'error': 'File not found'
                    })
                    continue

                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                target = change.get('target', '')
                location = change.get('location', 'after')

                if target and target in content:
                    if location == 'after':
                        new_content = content.replace(
                            target,
                            target + '\n' + change['new_content'],
                            1
                        )
                    else:  # before
                        new_content = content.replace(
                            target,
                            change['new_content'] + '\n' + target,
                            1
                        )

                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

                    results['applied'].append({
                        'file': file_path,
                        'type': 'inserted'
                    })
                else:
                    results['failed'].append({
                        'file': file_path,
                        'error': f'Target "{target}" not found'
                    })

        except Exception as e:
            logger.error(f"Error applying change to {file_path}: {e}")
            results['failed'].append({
                'file': file_path,
                'error': str(e)
            })

    results['files_modified'] = len(results['applied'])
    results['success'] = len(results['failed']) == 0

    return results


def auto_commit_changes(
    message: str = None,
    repo_path: str = WEBSITE_REPO_PATH
) -> Dict:
    """
    Auto-commit all changes with a descriptive message.

    Args:
        message: Custom commit message (auto-generated if None)
        repo_path: Path to the repository

    Returns:
        Dictionary with commit details
    """
    if not os.path.exists(repo_path):
        return {'success': False, 'error': 'Repository not found'}

    try:
        # Stage all changes
        subprocess.run(
            ['git', 'add', '-A'],
            cwd=repo_path,
            check=True,
            capture_output=True
        )

        # Check if there are changes to commit
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        if not status_result.stdout.strip():
            return {'success': True, 'message': 'No changes to commit'}

        # Generate commit message if not provided
        if not message:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            message = f"Website update via A.R.C.H.I.E. - {timestamp}"

        # Commit
        commit_result = subprocess.run(
            ['git', 'commit', '-m', message],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        if commit_result.returncode != 0:
            return {
                'success': False,
                'error': commit_result.stderr
            }

        # Get commit SHA
        sha_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        return {
            'success': True,
            'sha': sha_result.stdout.strip()[:8],
            'message': message
        }

    except subprocess.CalledProcessError as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        logger.error(f"Error in auto_commit: {e}")
        return {'success': False, 'error': str(e)}


def generate_diff_preview(changes: List[Dict], repo_path: str = WEBSITE_REPO_PATH) -> List[Dict]:
    """
    Generate diff preview for proposed changes.

    Args:
        changes: List of change dictionaries
        repo_path: Path to the repository

    Returns:
        List of diff previews with before/after content
    """
    previews = []

    for change in changes:
        file_path = change['file']
        full_path = os.path.join(repo_path, file_path)

        preview = {
            'file': file_path,
            'type': change['type'],
            'diff': []
        }

        if change['type'] == 'create':
            preview['diff'] = [
                {'type': 'add', 'content': change['new_content']}
            ]

        elif change['type'] == 'replace':
            preview['diff'] = [
                {'type': 'remove', 'content': change.get('old_content', '')},
                {'type': 'add', 'content': change['new_content']}
            ]

        elif change['type'] == 'insert':
            preview['diff'] = [
                {'type': 'context', 'content': change.get('target', '')},
                {'type': 'add', 'content': change['new_content']}
            ]

        previews.append(preview)

    return previews


def get_chat_system_prompt(repo_path: str = WEBSITE_REPO_PATH) -> str:
    """
    Get the complete system prompt with current site context.

    Returns:
        Formatted system prompt string
    """
    context = build_site_context(repo_path)

    return WEBSITE_EDITOR_SYSTEM_PROMPT.format(
        file_tree=context['file_tree'],
        file_contents=context['file_contents']
    )


def ensure_repo_cloned(repo_path: str = WEBSITE_REPO_PATH) -> Dict:
    """
    Ensure the repository is cloned and up to date.

    Returns:
        Status dictionary
    """
    if os.path.exists(repo_path):
        # Pull latest
        try:
            result = subprocess.run(
                ['git', 'pull', 'origin', 'main'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                'success': True,
                'status': 'updated',
                'message': result.stdout
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    else:
        # Clone
        github_token = os.getenv('GITHUB_TOKEN', '')
        repo_url = f"https://{github_token}@github.com/{ADMIN_WEBSITE_REPO}.git"

        try:
            result = subprocess.run(
                ['git', 'clone', repo_url, repo_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                'success': True,
                'status': 'cloned',
                'message': 'Repository cloned successfully'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
