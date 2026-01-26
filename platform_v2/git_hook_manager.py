"""
Git Hook Manager
Manages Git hooks for automatic commit detection in sandbox branches

Author: A.R.C.H.I.E. Platform
Date: 2026-01-06
"""
import os
import stat
from typing import Dict


class GitHookManager:
    """Manages Git hooks for automatic commit detection"""

    def __init__(self, repo_path: str = '/mnt/archie_brain/platform_v2'):
        self.repo_path = repo_path
        self.hooks_dir = os.path.join(repo_path, '.git', 'hooks')
        self.webhook_url = 'http://localhost:3000/api/cursor/commit-webhook'

    def install_post_commit_hook(self) -> Dict:
        """
        Install post-commit hook that detects commits and triggers workflow

        The hook will:
        1. Check if commit is on a sandbox branch
        2. Extract proposal ID from branch name
        3. Call webhook to trigger workflow
        4. Run asynchronously (non-blocking)

        Returns:
            {
                'success': bool,
                'hook_path': str,
                'message': str
            }
        """
        try:
            # Ensure hooks directory exists
            os.makedirs(self.hooks_dir, exist_ok=True)

            hook_path = os.path.join(self.hooks_dir, 'post-commit')

            # Create hook script
            hook_content = f'''#!/bin/bash
# A.R.C.H.I.E. Post-Commit Hook
# Auto-detects commits on sandbox branches and triggers workflow

# Get current branch
BRANCH=$(git branch --show-current)

# Only process sandbox branches
if [[ $BRANCH == sandbox-proposal-* ]]; then
    # Extract proposal ID from branch name
    PROPOSAL_ID=$(echo $BRANCH | sed 's/sandbox-proposal-//')

    # Get commit details
    COMMIT_HASH=$(git rev-parse HEAD)
    COMMIT_MSG=$(git log -1 --pretty=format:%s)
    AUTHOR_NAME=$(git log -1 --pretty=format:%an)
    AUTHOR_EMAIL=$(git log -1 --pretty=format:%ae)
    TIMESTAMP=$(git log -1 --pretty=format:%ct)

    # Call webhook asynchronously (non-blocking)
    curl -s -X POST {self.webhook_url} \\
        -H "Content-Type: application/json" \\
        -H "X-Git-Hook: true" \\
        -H "X-Git-Hook-Version: 1.0" \\
        -d "{{
            \\"proposal_id\\": $PROPOSAL_ID,
            \\"commit_hash\\": \\"$COMMIT_HASH\\",
            \\"commit_message\\": \\"$COMMIT_MSG\\",
            \\"author_name\\": \\"$AUTHOR_NAME\\",
            \\"author_email\\": \\"$AUTHOR_EMAIL\\",
            \\"branch\\": \\"$BRANCH\\",
            \\"timestamp\\": $TIMESTAMP
        }}" > /dev/null 2>&1 &

    # Log for debugging
    echo "[A.R.C.H.I.E. Hook] Triggered workflow for proposal #$PROPOSAL_ID (commit: ${{COMMIT_HASH:0:8}})"
fi

# Always exit successfully (don't block commit)
exit 0
'''

            # Write hook file
            with open(hook_path, 'w') as f:
                f.write(hook_content)

            # Make executable
            os.chmod(hook_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

            return {
                'success': True,
                'hook_path': hook_path,
                'message': 'Post-commit hook installed successfully',
                'webhook_url': self.webhook_url
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'hook_path': hook_path
            }

    def remove_post_commit_hook(self) -> Dict:
        """
        Remove post-commit hook

        Returns:
            {
                'success': bool,
                'message': str
            }
        """
        try:
            hook_path = os.path.join(self.hooks_dir, 'post-commit')

            if os.path.exists(hook_path):
                os.remove(hook_path)
                return {
                    'success': True,
                    'message': 'Post-commit hook removed',
                    'hook_path': hook_path
                }
            else:
                return {
                    'success': True,
                    'message': 'Hook does not exist (already removed)',
                    'hook_path': hook_path
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def is_hook_installed(self) -> bool:
        """Check if post-commit hook is installed"""
        hook_path = os.path.join(self.hooks_dir, 'post-commit')
        return os.path.exists(hook_path) and os.access(hook_path, os.X_OK)

    def get_hook_info(self) -> Dict:
        """
        Get information about installed hook

        Returns:
            {
                'installed': bool,
                'path': str,
                'executable': bool,
                'size': int (bytes),
                'modified_at': str
            }
        """
        hook_path = os.path.join(self.hooks_dir, 'post-commit')

        if not os.path.exists(hook_path):
            return {
                'installed': False,
                'path': hook_path
            }

        stat_info = os.stat(hook_path)

        return {
            'installed': True,
            'path': hook_path,
            'executable': os.access(hook_path, os.X_OK),
            'size': stat_info.st_size,
            'modified_at': stat_info.st_mtime
        }

    def test_hook(self) -> Dict:
        """
        Test hook by simulating a webhook call

        Returns:
            {
                'success': bool,
                'message': str
            }
        """
        try:
            import requests

            test_data = {
                'proposal_id': 999,
                'commit_hash': 'test1234567890abcdef',
                'commit_message': '[TEST] Hook test commit',
                'author_name': 'Hook Tester',
                'author_email': 'test@kytranempowerment.com',
                'branch': 'sandbox-proposal-999',
                'timestamp': 1234567890
            }

            response = requests.post(
                self.webhook_url,
                json=test_data,
                headers={
                    'X-Git-Hook': 'true',
                    'X-Git-Hook-Test': 'true'
                },
                timeout=5
            )

            if response.status_code == 200:
                return {
                    'success': True,
                    'message': 'Hook test successful',
                    'response': response.json()
                }
            else:
                return {
                    'success': False,
                    'message': f'Hook test failed: HTTP {response.status_code}',
                    'response': response.text
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


# Convenience functions
def install_commit_hook() -> Dict:
    """Install post-commit hook"""
    manager = GitHookManager()
    return manager.install_post_commit_hook()


def is_commit_hook_installed() -> bool:
    """Check if commit hook is installed"""
    manager = GitHookManager()
    return manager.is_hook_installed()


def test_commit_hook() -> Dict:
    """Test commit hook"""
    manager = GitHookManager()
    return manager.test_hook()
