"""
Workflow Automator for A.R.C.H.I.E.
Orchestrates end-to-end automation of improvement proposals

Features:
- Auto-status progression
- Stuck proposal detection
- Auto-escalation for failures
- Auto-completion on success
- Workflow state tracking
"""
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

sys.path.insert(0, '/mnt/archie_brain/platform_v2')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')

try:
    from escalation_handler import EscalationHandler
except ImportError:
    EscalationHandler = None


class WorkflowAutomator:
    """
    Orchestrates automated workflow progression for improvement proposals.

    Status Transitions:
    proposed → pending_approval → approved → in_progress →
    ready_for_test → tested → ready_for_deployment → deploying →
    deployed → monitoring → completed

    Auto-Actions:
    - Detect stuck proposals (timeout triggers)
    - Auto-progress when conditions met
    - Auto-escalate on failures
    - Auto-complete on success
    """

    def __init__(self):
        self.escalation_handler = EscalationHandler() if EscalationHandler else None

        # Timeout thresholds (in hours)
        self.timeouts = {
            'proposed': 48,              # Must be reviewed within 48hrs
            'pending_approval': 72,      # Must be approved/rejected within 72hrs
            'in_progress': 168,          # Must make progress within 7 days
            'ready_for_test': 24,        # Must be tested within 24hrs
            'tested': 12,                # Must deploy within 12hrs (if approved)
            'deploying': 2,              # Deployment should complete in 2hrs
            'monitoring': 24             # Monitoring completes after 24hrs
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv('DB_HOST', 'archie_database'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'archie'),
            user=os.getenv('DB_USER', 'archie'),
            password=os.getenv('DB_PASSWORD', '')
        )

    def run_workflow_automation(self) -> Dict:
        """
        Main workflow automation cycle.
        Run this periodically (e.g., every hour) to check all proposals.

        Returns:
            {
                'success': True,
                'proposals_processed': 25,
                'actions_taken': {
                    'auto_progressed': 10,
                    'escalated': 3,
                    'completed': 2
                },
                'stuck_proposals': [...]
            }
        """
        actions_taken = {
            'auto_progressed': 0,
            'escalated': 0,
            'completed': 0,
            'stuck_detected': 0
        }

        stuck_proposals = []

        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get all active proposals (not completed/rejected/failed)
            cur.execute("""
                SELECT * FROM improvement_proposals
                WHERE status NOT IN ('completed', 'rejected', 'cancelled', 'deployment_failed')
                ORDER BY priority DESC, created_at ASC
            """)

            proposals = cur.fetchall()

            for proposal in proposals:
                # Check if stuck
                if self._is_stuck(proposal):
                    stuck_proposals.append({
                        'id': proposal['id'],
                        'title': proposal['title'],
                        'status': proposal['status'],
                        'stuck_duration': self._get_stuck_duration(proposal)
                    })
                    actions_taken['stuck_detected'] += 1

                    # Escalate stuck proposals
                    if self.escalation_handler:
                        escalate_result = self.escalation_handler.escalate_stuck_proposal(
                            proposal['id'],
                            reason=f"Stuck in '{proposal['status']}' status for too long"
                        )
                        if escalate_result.get('success'):
                            actions_taken['escalated'] += 1

                # Check for auto-progression opportunities
                progression = self._check_auto_progression(proposal)
                if progression['can_progress']:
                    progress_result = self._progress_proposal(
                        proposal['id'],
                        progression['next_status'],
                        progression['reason']
                    )
                    if progress_result['success']:
                        actions_taken['auto_progressed'] += 1

                # Check for auto-completion
                if self._can_complete(proposal):
                    complete_result = self._complete_proposal(proposal['id'])
                    if complete_result['success']:
                        actions_taken['completed'] += 1

            cur.close()
            conn.close()

            return {
                'success': True,
                'proposals_processed': len(proposals),
                'actions_taken': actions_taken,
                'stuck_proposals': stuck_proposals,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }

    def _is_stuck(self, proposal: Dict) -> bool:
        """
        Check if proposal is stuck in current status.

        Args:
            proposal: Proposal dict

        Returns:
            True if stuck, False otherwise
        """
        status = proposal['status']

        # Get timeout threshold for this status
        timeout_hours = self.timeouts.get(status, 168)  # Default 7 days

        # Get last status change
        created_at = proposal.get('created_at')
        approved_at = proposal.get('approved_at')
        deployed_at = proposal.get('deployed_at')

        # Determine reference time based on status
        if status == 'proposed':
            ref_time = created_at
        elif status in ['pending_approval', 'approved', 'in_progress', 'ready_for_test', 'tested']:
            ref_time = approved_at or created_at
        elif status in ['deploying', 'deployed', 'monitoring']:
            ref_time = deployed_at or created_at
        else:
            ref_time = created_at

        if not ref_time:
            return False

        # Check if exceeded timeout
        time_in_status = datetime.now() - ref_time
        return time_in_status > timedelta(hours=timeout_hours)

    def _get_stuck_duration(self, proposal: Dict) -> str:
        """Get human-readable stuck duration"""
        status = proposal['status']
        created_at = proposal.get('created_at')

        if not created_at:
            return 'Unknown'

        duration = datetime.now() - created_at

        days = duration.days
        hours = duration.seconds // 3600

        if days > 0:
            return f"{days} days, {hours} hours"
        else:
            return f"{hours} hours"

    def _check_auto_progression(self, proposal: Dict) -> Dict:
        """
        Check if proposal can auto-progress to next status.

        Returns:
            {
                'can_progress': True,
                'next_status': 'approved',
                'reason': 'Auto-approved: low risk + tests passed'
            }
        """
        status = proposal['status']
        proposal_id = proposal['id']

        # proposed → pending_approval (if team assigned)
        if status == 'proposed':
            if proposal.get('team_assigned_at'):
                return {
                    'can_progress': True,
                    'next_status': 'pending_approval',
                    'reason': 'Team assigned, ready for approval'
                }

        # pending_approval → approved (if low risk and tests passed)
        elif status == 'pending_approval':
            # Check if already has sandbox tests
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("""
                SELECT test_results FROM sandbox_instances
                WHERE proposal_id = %s
                AND status = 'tested'
                ORDER BY created_at DESC
                LIMIT 1
            """, (proposal_id,))

            sandbox = cur.fetchone()
            cur.close()
            conn.close()

            if sandbox and sandbox.get('test_results', {}).get('success'):
                # Check risk level
                try:
                    sys.path.insert(0, '/mnt/archie_brain/platform_v2')
                    from deployment_decision import DeploymentDecisionEngine

                    engine = DeploymentDecisionEngine()
                    decision = engine.can_auto_deploy(proposal_id)

                    if decision.get('can_auto_deploy') and decision.get('risk_level') == 'low':
                        return {
                            'can_progress': True,
                            'next_status': 'approved',
                            'reason': 'Auto-approved: low risk + tests passed'
                        }
                except:
                    pass

        # tested → ready_for_deployment (if tests passed)
        elif status == 'tested':
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("""
                SELECT test_results FROM sandbox_instances
                WHERE proposal_id = %s
                AND status = 'tested'
                ORDER BY created_at DESC
                LIMIT 1
            """, (proposal_id,))

            sandbox = cur.fetchone()
            cur.close()
            conn.close()

            if sandbox and sandbox.get('test_results', {}).get('success'):
                pass_rate = sandbox['test_results'].get('pass_rate', 0)
                if pass_rate >= 95:  # 95% or higher
                    return {
                        'can_progress': True,
                        'next_status': 'ready_for_deployment',
                        'reason': f'Tests passed with {pass_rate}% success rate'
                    }

        # deployed → monitoring (immediately after deployment)
        elif status == 'deployed':
            if proposal.get('deployed_at'):
                return {
                    'can_progress': True,
                    'next_status': 'monitoring',
                    'reason': 'Deployment complete, starting monitoring'
                }

        return {
            'can_progress': False,
            'next_status': None,
            'reason': 'No auto-progression criteria met'
        }

    def _progress_proposal(
        self,
        proposal_id: int,
        next_status: str,
        reason: str
    ) -> Dict:
        """
        Progress proposal to next status.

        Args:
            proposal_id: Proposal ID
            next_status: New status
            reason: Reason for progression

        Returns:
            {'success': True, 'old_status': '...', 'new_status': '...'}
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get current status
            cur.execute("""
                SELECT status FROM improvement_proposals
                WHERE id = %s
            """, (proposal_id,))

            result = cur.fetchone()
            if not result:
                cur.close()
                conn.close()
                return {'success': False, 'error': 'Proposal not found'}

            old_status = result['status']

            # Update status
            cur.execute("""
                UPDATE improvement_proposals
                SET status = %s
                WHERE id = %s
            """, (next_status, proposal_id))

            # Record in workflow states
            cur.execute("""
                INSERT INTO improvement_workflow_states
                (proposal_id, from_status, to_status, reason, automated, changed_at)
                VALUES (%s, %s, %s, %s, true, NOW())
            """, (proposal_id, old_status, next_status, reason))

            conn.commit()
            cur.close()
            conn.close()

            return {
                'success': True,
                'proposal_id': proposal_id,
                'old_status': old_status,
                'new_status': next_status,
                'reason': reason
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }

    def _can_complete(self, proposal: Dict) -> bool:
        """
        Check if proposal can be marked as completed.

        Criteria:
        - Status is 'monitoring'
        - Deployed >24 hours ago
        - No rollbacks
        """
        if proposal['status'] != 'monitoring':
            return False

        deployed_at = proposal.get('deployed_at')
        if not deployed_at:
            return False

        # Check if 24 hours have passed
        time_since_deploy = datetime.now() - deployed_at
        if time_since_deploy < timedelta(hours=24):
            return False

        # Check if not rolled back
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT status FROM improvement_deployments
            WHERE proposal_id = %s
            ORDER BY deployed_at DESC
            LIMIT 1
        """, (proposal['id'],))

        deployment = cur.fetchone()
        cur.close()
        conn.close()

        if deployment and deployment['status'] == 'rolled_back':
            return False

        return True

    def _complete_proposal(self, proposal_id: int) -> Dict:
        """
        Mark proposal as completed.

        Args:
            proposal_id: Proposal ID

        Returns:
            {'success': True, 'completed_at': '...'}
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                UPDATE improvement_proposals
                SET status = 'completed',
                    completed_at = NOW()
                WHERE id = %s
                RETURNING completed_at
            """, (proposal_id,))

            result = cur.fetchone()
            completed_at = result['completed_at']

            # Record in workflow states
            cur.execute("""
                INSERT INTO improvement_workflow_states
                (proposal_id, from_status, to_status, reason, automated, changed_at)
                VALUES (%s, 'monitoring', 'completed', 'Auto-completed: 24hr monitoring passed', true, NOW())
            """, (proposal_id,))

            conn.commit()
            cur.close()
            conn.close()

            return {
                'success': True,
                'proposal_id': proposal_id,
                'completed_at': completed_at.isoformat()
            }

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }

    def get_workflow_stats(self) -> Dict:
        """
        Get workflow statistics and metrics.

        Returns:
            {
                'total_proposals': 100,
                'by_status': {'proposed': 10, 'approved': 15, ...},
                'avg_completion_time': '3 days',
                'stuck_count': 5
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Total proposals
            cur.execute("SELECT COUNT(*) as total FROM improvement_proposals")
            total = cur.fetchone()['total']

            # By status
            cur.execute("""
                SELECT status, COUNT(*) as count
                FROM improvement_proposals
                GROUP BY status
            """)
            by_status = {row['status']: row['count'] for row in cur.fetchall()}

            # Average completion time
            cur.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM (completed_at - created_at))/86400) as avg_days
                FROM improvement_proposals
                WHERE status = 'completed'
            """)
            avg_result = cur.fetchone()
            avg_days = avg_result['avg_days'] if avg_result and avg_result['avg_days'] else 0

            # Stuck count
            cur.execute("""
                SELECT COUNT(*) as stuck
                FROM improvement_proposals
                WHERE status NOT IN ('completed', 'rejected', 'cancelled')
            """)
            stuck = cur.fetchone()['stuck']

            cur.close()
            conn.close()

            return {
                'success': True,
                'total_proposals': total,
                'by_status': by_status,
                'avg_completion_time_days': round(avg_days, 1),
                'stuck_count': stuck,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }


# ============================================================================
# BACKGROUND SERVICE
# ============================================================================

def run_automation_loop(check_interval: int = 3600):
    """
    Background service that continuously runs workflow automation.

    Args:
        check_interval: Seconds between automation runs (default: 3600 = 1 hour)
    """
    import time

    automator = WorkflowAutomator()

    print(f"Starting workflow automation service (check interval: {check_interval}s)")

    while True:
        try:
            print(f"\n{'='*60}")
            print(f"Running workflow automation at {datetime.now().isoformat()}")
            print(f"{'='*60}")

            result = automator.run_workflow_automation()

            if result['success']:
                print(f"✓ Processed {result['proposals_processed']} proposals")
                print(f"  Actions taken:")
                for action, count in result['actions_taken'].items():
                    if count > 0:
                        print(f"    - {action}: {count}")

                if result['stuck_proposals']:
                    print(f"\n⚠️  {len(result['stuck_proposals'])} stuck proposals detected:")
                    for stuck in result['stuck_proposals'][:5]:  # Show first 5
                        print(f"    - #{stuck['id']}: {stuck['title']} (stuck {stuck['stuck_duration']})")
            else:
                print(f"✗ Automation failed: {result.get('error')}")

            # Sleep until next run
            print(f"\nSleeping for {check_interval}s...")
            time.sleep(check_interval)

        except KeyboardInterrupt:
            print("\nWorkflow automation service stopped")
            break
        except Exception as e:
            print(f"Error in automation loop: {e}")
            time.sleep(check_interval)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def run_once() -> Dict:
    """Quick function to run automation once"""
    automator = WorkflowAutomator()
    return automator.run_workflow_automation()


def get_stats() -> Dict:
    """Quick function to get workflow stats"""
    automator = WorkflowAutomator()
    return automator.get_workflow_stats()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Workflow Automator')
    parser.add_argument('--service', action='store_true', help='Run as background service')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    parser.add_argument('--stats', action='store_true', help='Show workflow statistics')
    parser.add_argument('--interval', type=int, default=3600, help='Check interval in seconds')

    args = parser.parse_args()

    if args.service:
        run_automation_loop(check_interval=args.interval)
    elif args.once:
        result = run_once()
        print(json.dumps(result, indent=2, default=str))
    elif args.stats:
        stats = get_stats()
        print(json.dumps(stats, indent=2, default=str))
    else:
        print("Workflow Automator - Test Mode")
        print("=" * 60)

        automator = WorkflowAutomator()

        print("\n1. TIMEOUT CONFIGURATION:")
        print("-" * 60)
        for status, hours in automator.timeouts.items():
            print(f"{status}: {hours} hours")

        print("\n2. WORKFLOW STATISTICS:")
        print("-" * 60)
        stats = automator.get_workflow_stats()
        if stats['success']:
            print(f"Total proposals: {stats['total_proposals']}")
            print(f"Average completion time: {stats['avg_completion_time_days']} days")
            print(f"Stuck proposals: {stats['stuck_count']}")
            print(f"\nBy status:")
            for status, count in stats['by_status'].items():
                print(f"  {status}: {count}")

        print("\n✅ Workflow Automator loaded successfully!")
        print("\nRun with --service to start automation service")
        print("Run with --once to run automation once")
        print("Run with --stats to show statistics")
