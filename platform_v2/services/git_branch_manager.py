"""
Git Branch Manager
Manages Git branches for complete sandbox file isolation

Author: A.R.C.H.I.E. Platform
Date: 2026-01-05
"""

import subprocess
from typing import Dict, List
from datetime import datetime


class GitBranchManager:
    """Manages Git branches for sandbox isolation"""

    def __init__(self, repo_path: str = "/mnt/archie_brain"):
        self.repo_path = repo_path
        self.production_branch = "main"
        self.sandbox_prefix = "sandbox-proposal-"

    def _run_git_command(self, command: List[str], check: bool = True) -> Dict:
        """
        Run a Git command and return result

        Args:
            command: List of command parts (e.g., ['git', 'status'])
            check: Raise exception on non-zero exit code

        Returns:
            {
                'success': bool,
                'stdout': str,
                'stderr': str,
                'returncode': int
            }
        """
        try:
            result = subprocess.run(command, cwd=self.repo_path, capture_output=True, text=True, check=check)

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "stdout": e.stdout.strip() if e.stdout else "",
                "stderr": e.stderr.strip() if e.stderr else "",
                "returncode": e.returncode,
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "error": str(e),
            }

    def get_current_branch(self) -> str:
        """Get the currently active Git branch"""
        result = self._run_git_command(["git", "branch", "--show-current"])
        if result["success"]:
            return result["stdout"]
        return self.production_branch  # Default to main if error

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a branch exists"""
        result = self._run_git_command(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            check=False,
        )
        return result["returncode"] == 0

    def create_sandbox_branch(self, proposal_id: int) -> Dict:
        """
        Create isolated Git branch for proposal

        Args:
            proposal_id: Improvement proposal ID

        Returns:
            {
                'success': bool,
                'branch_name': str,
                'created_from': str (base branch),
                'message': str
            }
        """
        branch_name = f"{self.sandbox_prefix}{proposal_id}"

        try:
            # Check if branch already exists
            if self.branch_exists(branch_name):
                return {
                    "success": False,
                    "error": f"Branch {branch_name} already exists",
                    "branch_name": branch_name,
                }

            # Ensure we're on production branch
            current_branch = self.get_current_branch()
            if current_branch != self.production_branch:
                checkout_result = self._run_git_command(["git", "checkout", self.production_branch])
                if not checkout_result["success"]:
                    return {
                        "success": False,
                        "error": f"Could not checkout {self.production_branch}: {checkout_result['stderr']}",
                        "branch_name": branch_name,
                    }

            # Create new branch from production
            result = self._run_git_command(["git", "checkout", "-b", branch_name])

            if result["success"]:
                return {
                    "success": True,
                    "branch_name": branch_name,
                    "created_from": self.production_branch,
                    "message": f"Created sandbox branch {branch_name} from {self.production_branch}",
                    "created_at": datetime.now().isoformat(),
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create branch: {result['stderr']}",
                    "branch_name": branch_name,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "branch_name": branch_name}

    def switch_to_branch(self, branch_name: str) -> Dict:
        """
        Switch to a specific branch

        Args:
            branch_name: Name of branch to switch to

        Returns:
            {
                'success': bool,
                'previous_branch': str,
                'current_branch': str,
                'message': str
            }
        """
        try:
            previous_branch = self.get_current_branch()

            # Check if branch exists
            if not self.branch_exists(branch_name):
                return {
                    "success": False,
                    "error": f"Branch {branch_name} does not exist",
                    "current_branch": previous_branch,
                }

            # Switch to branch
            result = self._run_git_command(["git", "checkout", branch_name])

            if result["success"]:
                return {
                    "success": True,
                    "previous_branch": previous_branch,
                    "current_branch": branch_name,
                    "message": f"Switched from {previous_branch} to {branch_name}",
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to switch branch: {result['stderr']}",
                    "current_branch": previous_branch,
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def apply_changes_and_commit(self, proposal_id: int, changes: List[Dict], commit_message: str) -> Dict:
        """
        Apply code changes to sandbox branch and commit

        Args:
            proposal_id: Proposal ID
            changes: List of file changes to apply
            commit_message: Git commit message

        Returns:
            {
                'success': bool,
                'commit_hash': str,
                'files_changed': int,
                'branch_name': str
            }
        """
        branch_name = f"{self.sandbox_prefix}{proposal_id}"

        try:
            # Ensure we're on the sandbox branch
            current_branch = self.get_current_branch()
            if current_branch != branch_name:
                switch_result = self.switch_to_branch(branch_name)
                if not switch_result["success"]:
                    return {
                        "success": False,
                        "error": f"Could not switch to branch {branch_name}",
                        "branch_name": branch_name,
                    }

            # Note: File changes should be applied by code_application_system.py
            # This function just commits them

            # Stage all changes
            add_result = self._run_git_command(["git", "add", "."])
            if not add_result["success"]:
                return {
                    "success": False,
                    "error": f"Failed to stage changes: {add_result['stderr']}",
                    "branch_name": branch_name,
                }

            # Check if there are changes to commit
            status_result = self._run_git_command(["git", "status", "--porcelain"])
            if not status_result["stdout"]:
                return {
                    "success": True,
                    "message": "No changes to commit",
                    "branch_name": branch_name,
                    "files_changed": 0,
                }

            # Commit changes
            commit_result = self._run_git_command(["git", "commit", "-m", commit_message])

            if commit_result["success"]:
                # Get commit hash
                hash_result = self._run_git_command(["git", "rev-parse", "HEAD"])
                commit_hash = hash_result["stdout"] if hash_result["success"] else "unknown"

                # Count files changed
                files_changed = len(status_result["stdout"].split("\n"))

                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "files_changed": files_changed,
                    "branch_name": branch_name,
                    "message": f"Committed {files_changed} file(s) to {branch_name}",
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to commit: {commit_result['stderr']}",
                    "branch_name": branch_name,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "branch_name": branch_name}

    def get_diff(self, proposal_id: int, context_lines: int = 3) -> Dict:
        """
        Get diff between sandbox branch and production

        Args:
            proposal_id: Proposal ID
            context_lines: Number of context lines in diff

        Returns:
            {
                'success': bool,
                'diff': str,
                'files_changed': List[str],
                'stats': str
            }
        """
        branch_name = f"{self.sandbox_prefix}{proposal_id}"

        try:
            # Check if branch exists
            if not self.branch_exists(branch_name):
                return {
                    "success": False,
                    "error": f"Branch {branch_name} does not exist",
                }

            # Get diff
            diff_result = self._run_git_command(
                [
                    "git",
                    "diff",
                    f"--unified={context_lines}",
                    f"{self.production_branch}...{branch_name}",
                ]
            )

            # Get stats
            stats_result = self._run_git_command(["git", "diff", "--stat", f"{self.production_branch}...{branch_name}"])

            # Get list of changed files
            files_result = self._run_git_command(
                [
                    "git",
                    "diff",
                    "--name-only",
                    f"{self.production_branch}...{branch_name}",
                ]
            )

            files_changed = (
                files_result["stdout"].split("\n") if files_result["success"] and files_result["stdout"] else []
            )

            return {
                "success": True,
                "diff": diff_result["stdout"] if diff_result["success"] else "",
                "stats": stats_result["stdout"] if stats_result["success"] else "",
                "files_changed": files_changed,
                "num_files": len(files_changed),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def merge_to_production(self, proposal_id: int) -> Dict:
        """
        Merge sandbox branch to production (deployment)

        Args:
            proposal_id: Proposal ID

        Returns:
            {
                'success': bool,
                'merge_commit': str,
                'files_merged': int,
                'message': str
            }
        """
        branch_name = f"{self.sandbox_prefix}{proposal_id}"

        try:
            # Check if branch exists
            if not self.branch_exists(branch_name):
                return {
                    "success": False,
                    "error": f"Branch {branch_name} does not exist",
                }

            # Switch to production branch
            switch_result = self.switch_to_branch(self.production_branch)
            if not switch_result["success"]:
                return {
                    "success": False,
                    "error": f"Could not switch to {self.production_branch}",
                    "branch_name": branch_name,
                }

            # Merge sandbox branch (no fast-forward to preserve history)
            merge_result = self._run_git_command(
                [
                    "git",
                    "merge",
                    "--no-ff",
                    "-m",
                    f"Merge proposal #{proposal_id}: Deploy to production",
                    branch_name,
                ]
            )

            if merge_result["success"]:
                # Get merge commit hash
                hash_result = self._run_git_command(["git", "rev-parse", "HEAD"])
                merge_commit = hash_result["stdout"] if hash_result["success"] else "unknown"

                # Get number of files merged
                diff_result = self.get_diff(proposal_id)
                files_merged = diff_result.get("num_files", 0) if diff_result["success"] else 0

                return {
                    "success": True,
                    "merge_commit": merge_commit,
                    "files_merged": files_merged,
                    "branch_name": branch_name,
                    "message": f"Successfully merged {branch_name} to {self.production_branch}",
                }
            else:
                return {
                    "success": False,
                    "error": f"Merge failed: {merge_result['stderr']}",
                    "branch_name": branch_name,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "branch_name": branch_name}

    def delete_sandbox_branch(self, proposal_id: int, force: bool = False) -> Dict:
        """
        Delete sandbox branch (after merge or rejection)

        Args:
            proposal_id: Proposal ID
            force: Force delete even if not merged

        Returns:
            {
                'success': bool,
                'branch_name': str,
                'message': str
            }
        """
        branch_name = f"{self.sandbox_prefix}{proposal_id}"

        try:
            # Check if branch exists
            if not self.branch_exists(branch_name):
                return {
                    "success": True,  # Already deleted is success
                    "message": f"Branch {branch_name} does not exist (already deleted)",
                    "branch_name": branch_name,
                }

            # Ensure we're not on the branch we're deleting
            current_branch = self.get_current_branch()
            if current_branch == branch_name:
                switch_result = self.switch_to_branch(self.production_branch)
                if not switch_result["success"]:
                    return {
                        "success": False,
                        "error": f"Could not switch away from {branch_name}",
                        "branch_name": branch_name,
                    }

            # Delete branch
            delete_flag = "-D" if force else "-d"
            delete_result = self._run_git_command(["git", "branch", delete_flag, branch_name])

            if delete_result["success"]:
                return {
                    "success": True,
                    "branch_name": branch_name,
                    "message": f"Deleted branch {branch_name}",
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to delete branch: {delete_result['stderr']}",
                    "branch_name": branch_name,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "branch_name": branch_name}

    def list_sandbox_branches(self) -> Dict:
        """
        List all active sandbox branches

        Returns:
            {
                'success': bool,
                'branches': List[str],
                'count': int
            }
        """
        try:
            result = self._run_git_command(["git", "branch", "--list", f"{self.sandbox_prefix}*"])

            if result["success"]:
                # Parse branch names (remove leading whitespace and asterisk)
                branches = [line.strip().lstrip("* ") for line in result["stdout"].split("\n") if line.strip()]

                return {"success": True, "branches": branches, "count": len(branches)}
            else:
                return {
                    "success": False,
                    "error": result["stderr"],
                    "branches": [],
                    "count": 0,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "branches": [], "count": 0}


# Convenience functions
def create_sandbox_branch(proposal_id: int) -> Dict:
    """Create sandbox branch for proposal"""
    manager = GitBranchManager()
    return manager.create_sandbox_branch(proposal_id)


def switch_to_sandbox(proposal_id: int) -> Dict:
    """Switch to sandbox branch"""
    manager = GitBranchManager()
    return manager.switch_to_branch(f"sandbox-proposal-{proposal_id}")


def switch_to_production() -> Dict:
    """Switch back to production"""
    manager = GitBranchManager()
    return manager.switch_to_branch("main")


def deploy_to_production(proposal_id: int) -> Dict:
    """Deploy sandbox to production (merge + delete branch)"""
    manager = GitBranchManager()

    # Merge to production
    merge_result = manager.merge_to_production(proposal_id)
    if not merge_result["success"]:
        return merge_result

    # Delete sandbox branch
    delete_result = manager.delete_sandbox_branch(proposal_id)

    return {**merge_result, "branch_deleted": delete_result["success"]}
