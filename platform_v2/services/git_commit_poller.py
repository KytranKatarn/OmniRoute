"""
Git Commit Polling Service
Fallback mechanism for detecting commits when Git hooks fail

Purpose:
- Polls sandbox branches every 30 seconds
- Detects new commits that weren't caught by webhook
- Triggers workflows for unprocessed commits
- Provides reliability when Git hooks are unavailable

Author: A.R.C.H.I.E. Platform
Date: 2026-01-06
"""

import time
import subprocess
import threading
from typing import Dict, List
from datetime import datetime


class GitCommitPoller:
    """Polls Git repository for new commits on sandbox branches"""

    def __init__(
        self,
        repo_path: str = "/mnt/archie_brain",
        poll_interval: int = 30,
        enabled: bool = True,
    ):
        self.repo_path = repo_path
        self.poll_interval = poll_interval
        self.enabled = enabled
        self.running = False
        self.thread = None
        self.last_poll_time = None
        self.commits_detected = 0
        self.webhooks_triggered = 0

    def start(self):
        """Start the polling service in background thread"""
        if self.running:
            print("[Git Poller] Already running")
            return

        if not self.enabled:
            print("[Git Poller] Disabled, not starting")
            return

        print(f"[Git Poller] Starting (interval: {self.poll_interval}s)")
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the polling service"""
        print("[Git Poller] Stopping...")
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[Git Poller] Stopped")

    def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                self.last_poll_time = datetime.now()
                self._check_for_commits()
            except Exception as e:
                print(f"[Git Poller] Error in poll loop: {e}")

            # Sleep for poll interval
            time.sleep(self.poll_interval)

    def _check_for_commits(self):
        """Check all sandbox branches for new commits"""
        try:
            # Get all sandbox branches
            branches = self._get_sandbox_branches()

            if not branches:
                return

            # Check each branch for new commits
            for branch in branches:
                try:
                    self._check_branch_commits(branch)
                except Exception as e:
                    print(f"[Git Poller] Error checking branch {branch}: {e}")

        except Exception as e:
            print(f"[Git Poller] Error checking for commits: {e}")

    def _get_sandbox_branches(self) -> List[str]:
        """Get list of all sandbox branches"""
        try:
            result = subprocess.run(
                ["git", "branch", "--list", "sandbox-proposal-*"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return []

            # Parse branch names (remove leading spaces and asterisk)
            branches = []
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line:
                    # Remove asterisk if current branch
                    branch = line.lstrip("* ")
                    if branch.startswith("sandbox-proposal-"):
                        branches.append(branch)

            return branches

        except Exception as e:
            print(f"[Git Poller] Error getting sandbox branches: {e}")
            return []

    def _check_branch_commits(self, branch_name: str):
        """Check a specific branch for new commits"""
        try:
            # Extract proposal ID from branch name
            proposal_id = self._extract_proposal_id(branch_name)
            if not proposal_id:
                return

            # Get commits on this branch that aren't in main
            commits = self._get_branch_commits(branch_name)

            if not commits:
                return

            # Check which commits are already processed
            processed_commits = self._get_processed_commits(proposal_id)

            # Find new commits
            new_commits = [c for c in commits if c["hash"] not in processed_commits]

            if not new_commits:
                return

            print(f"[Git Poller] Found {len(new_commits)} new commit(s) on {branch_name}")

            # Process each new commit
            for commit in new_commits:
                self._process_commit(proposal_id, branch_name, commit)

        except Exception as e:
            print(f"[Git Poller] Error checking branch {branch_name}: {e}")

    def _extract_proposal_id(self, branch_name: str) -> int:
        """Extract proposal ID from branch name"""
        try:
            # Format: sandbox-proposal-123
            if not branch_name.startswith("sandbox-proposal-"):
                return None

            proposal_id_str = branch_name.replace("sandbox-proposal-", "")
            return int(proposal_id_str)

        except ValueError:
            return None

    def _get_branch_commits(self, branch_name: str) -> List[Dict]:
        """Get commits on a branch that aren't in main"""
        try:
            # Get commits: main..branch
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"main..{branch_name}",
                    "--pretty=format:%H|%an|%ae|%at|%s",
                    "-10",  # Limit to last 10 commits
                ],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return []

            commits = []
            for line in result.stdout.split("\n"):
                if not line.strip():
                    continue

                parts = line.split("|")
                if len(parts) >= 5:
                    commits.append(
                        {
                            "hash": parts[0],
                            "author_name": parts[1],
                            "author_email": parts[2],
                            "timestamp": int(parts[3]),
                            "message": parts[4],
                        }
                    )

            return commits

        except Exception as e:
            print(f"[Git Poller] Error getting commits for {branch_name}: {e}")
            return []

    def _get_processed_commits(self, proposal_id: int) -> List[str]:
        """Get list of commit hashes already processed for a proposal"""
        try:
            from tools.database import db
            import sqlalchemy

            query = """
                SELECT commit_hash
                FROM git_commits
                WHERE proposal_id = %s
            """

            with db.engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(query), (proposal_id,))

                return [row[0] for row in result]

        except Exception as e:
            print(f"[Git Poller] Error getting processed commits: {e}")
            return []

    def _process_commit(self, proposal_id: int, branch_name: str, commit: Dict):
        """Process a new commit by calling the webhook"""
        try:
            import requests

            webhook_url = "http://localhost:3000/api/cursor/commit-webhook"

            payload = {
                "proposal_id": proposal_id,
                "commit_hash": commit["hash"],
                "commit_message": commit["message"],
                "author_name": commit["author_name"],
                "author_email": commit["author_email"],
                "branch": branch_name,
                "timestamp": commit["timestamp"],
            }

            headers = {
                "Content-Type": "application/json",
                "X-Git-Hook": "true",
                "X-Git-Poller": "true",  # Indicate this came from poller
            }

            response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                self.commits_detected += 1
                self.webhooks_triggered += 1
                print(f"[Git Poller] Triggered workflow for commit {commit['hash'][:8]} (proposal #{proposal_id})")
            else:
                print(f"[Git Poller] Webhook failed: HTTP {response.status_code}")

        except Exception as e:
            print(f"[Git Poller] Error processing commit: {e}")

    def get_status(self) -> Dict:
        """Get current status of the poller"""
        return {
            "running": self.running,
            "enabled": self.enabled,
            "poll_interval": self.poll_interval,
            "last_poll_time": (self.last_poll_time.isoformat() if self.last_poll_time else None),
            "commits_detected": self.commits_detected,
            "webhooks_triggered": self.webhooks_triggered,
            "thread_alive": self.thread.is_alive() if self.thread else False,
        }


# Global poller instance
_poller_instance = None


def get_poller() -> GitCommitPoller:
    """Get or create the global poller instance"""
    global _poller_instance

    if _poller_instance is None:
        _poller_instance = GitCommitPoller()

    return _poller_instance


def start_poller():
    """Start the global poller"""
    poller = get_poller()
    poller.start()


def stop_poller():
    """Stop the global poller"""
    poller = get_poller()
    poller.stop()


def get_poller_status() -> Dict:
    """Get status of the global poller"""
    poller = get_poller()
    return poller.get_status()
