"""
Improvement Learning Engine for A.R.C.H.I.E.
Tracks success/failure patterns and improves system over time

Features:
- Track proposal outcomes (success/failure)
- Update agent proficiency scores
- Improve team assignment algorithm
- Learn from deployment patterns
- Store insights in long_term_memory
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json


class ImprovementLearning:
    """
    Learns from improvement proposal outcomes to improve future decisions.

    Learning Areas:
    1. Agent Performance - Track success/failure per agent
    2. Team Composition - Learn which team combinations work best
    3. Risk Assessment - Refine risk scoring based on outcomes
    4. Category Patterns - Identify patterns in proposal categories
    5. Time Estimation - Improve time estimates based on actual duration
    """

    def __init__(self):
        pass

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv('DB_HOST', 'archie_database'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'archie'),
            user=os.getenv('DB_USER', 'archie'),
            password=os.getenv('DB_PASSWORD', '')
        )

    def learn_from_completion(self, proposal_id: int) -> Dict:
        """
        Learn from a completed proposal.

        Args:
            proposal_id: Completed proposal ID

        Returns:
            {
                'success': True,
                'insights_learned': 5,
                'agents_updated': 3,
                'patterns_discovered': 2
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        insights_learned = 0
        agents_updated = 0
        patterns = []

        try:
            # Get proposal details
            cur.execute("""
                SELECT * FROM improvement_proposals
                WHERE id = %s
            """, (proposal_id,))

            proposal = cur.fetchone()

            if not proposal:
                return {'success': False, 'error': 'Proposal not found'}

            # Determine outcome
            outcome = self._determine_outcome(proposal)

            # 1. Update agent proficiency scores
            agent_updates = self._update_agent_scores(proposal_id, outcome)
            agents_updated = len(agent_updates)

            # 2. Learn team composition patterns
            team_patterns = self._learn_team_patterns(proposal_id, outcome)
            if team_patterns:
                patterns.append(team_patterns)
                insights_learned += 1

            # 3. Learn time estimation patterns
            time_insight = self._learn_time_estimation(proposal)
            if time_insight:
                insights_learned += 1

            # 4. Learn category patterns
            category_insight = self._learn_category_patterns(proposal, outcome)
            if category_insight:
                patterns.append(category_insight)
                insights_learned += 1

            # 5. Store insights in long_term_memory
            if patterns:
                self._store_insights(proposal_id, patterns)

            cur.close()
            conn.close()

            return {
                'success': True,
                'proposal_id': proposal_id,
                'outcome': outcome,
                'insights_learned': insights_learned,
                'agents_updated': agents_updated,
                'patterns_discovered': len(patterns)
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }

    def _determine_outcome(self, proposal: Dict) -> str:
        """
        Determine if proposal was a success or failure.

        Returns:
            'success', 'failure', 'partial_success', 'rolled_back'
        """
        status = proposal['status']

        if status == 'completed':
            # Check if deployed successfully without rollback
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

            if deployment:
                if deployment['status'] == 'rolled_back':
                    return 'rolled_back'
                elif deployment['status'] == 'deployed':
                    return 'success'

            return 'success'  # Completed without deployment

        elif status == 'deployment_failed':
            return 'failure'

        elif status == 'escalated':
            return 'partial_success'  # Needed escalation but might still succeed

        return 'unknown'

    def _update_agent_scores(self, proposal_id: int, outcome: str) -> List[int]:
        """
        Update agent proficiency scores based on outcome.

        Success → +0.1 proficiency
        Failure → -0.05 proficiency
        Rolled back → -0.1 proficiency

        Returns:
            List of agent IDs that were updated
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        updated_agents = []

        try:
            # Get agents on this proposal
            cur.execute("""
                SELECT DISTINCT agent_id
                FROM improvement_team_assignments
                WHERE proposal_id = %s
            """, (proposal_id,))

            agents = cur.fetchall()

            # Determine proficiency change
            if outcome == 'success':
                change = 0.1
            elif outcome == 'failure':
                change = -0.05
            elif outcome == 'rolled_back':
                change = -0.1
            else:
                change = 0.0

            if change != 0.0:
                for agent_row in agents:
                    agent_id = agent_row['agent_id']

                    # Update proficiency in agent_skills
                    cur.execute("""
                        UPDATE agent_skills
                        SET proficiency_level = GREATEST(0, LEAST(10, proficiency_level + %s))
                        WHERE agent_id = %s
                    """, (change, agent_id))

                    updated_agents.append(agent_id)

                conn.commit()

            cur.close()
            conn.close()

            return updated_agents

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return []

    def _learn_team_patterns(self, proposal_id: int, outcome: str) -> Optional[Dict]:
        """
        Learn which team compositions work best.

        Returns:
            Pattern dict or None
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get team composition
            cur.execute("""
                SELECT
                    ta.role,
                    a.department,
                    a.worker_type,
                    a.model
                FROM improvement_team_assignments ta
                JOIN agents a ON ta.agent_id = a.id
                WHERE ta.proposal_id = %s
            """, (proposal_id,))

            team = cur.fetchall()
            cur.close()
            conn.close()

            if not team:
                return None

            # Build pattern
            team_composition = {
                'size': len(team),
                'departments': list(set(t['department'] for t in team)),
                'worker_types': list(set(t['worker_type'] for t in team)),
                'outcome': outcome
            }

            return {
                'pattern_type': 'team_composition',
                'pattern': team_composition
            }

        except Exception as e:
            cur.close()
            conn.close()
            return None

    def _learn_time_estimation(self, proposal: Dict) -> Optional[Dict]:
        """
        Learn from actual vs estimated time.

        Returns:
            Insight dict or None
        """
        created_at = proposal.get('created_at')
        completed_at = proposal.get('completed_at')

        if not created_at or not completed_at:
            return None

        actual_duration = (completed_at - created_at).total_seconds() / 3600  # hours

        # Get estimated time from plan_steps
        plan_steps = proposal.get('plan_steps', {})
        if isinstance(plan_steps, str):
            plan_steps = json.loads(plan_steps)

        estimated_time = plan_steps.get('total_estimated_time', 'Unknown')

        return {
            'category': proposal['category'],
            'complexity': proposal['complexity'],
            'estimated_time': estimated_time,
            'actual_duration_hours': round(actual_duration, 1),
            'accuracy': self._calculate_accuracy(estimated_time, actual_duration)
        }

    def _calculate_accuracy(self, estimated_str: str, actual_hours: float) -> str:
        """Calculate estimation accuracy"""
        # Parse estimated time (e.g., "3h 30min" → 3.5 hours)
        try:
            if 'h' in estimated_str:
                parts = estimated_str.split('h')
                hours = float(parts[0].strip())
                mins = 0
                if len(parts) > 1 and 'min' in parts[1]:
                    mins = float(parts[1].replace('min', '').strip())
                estimated_hours = hours + (mins / 60)
            elif 'min' in estimated_str:
                mins = float(estimated_str.replace('min', '').strip())
                estimated_hours = mins / 60
            else:
                return 'unknown'

            # Calculate accuracy
            if estimated_hours > 0:
                accuracy_pct = (1 - abs(actual_hours - estimated_hours) / estimated_hours) * 100
                return f"{round(accuracy_pct, 1)}%"

        except:
            pass

        return 'unknown'

    def _learn_category_patterns(self, proposal: Dict, outcome: str) -> Optional[Dict]:
        """
        Learn patterns specific to proposal categories.

        Returns:
            Pattern dict or None
        """
        category = proposal.get('category')
        priority = proposal.get('priority')
        complexity = proposal.get('complexity')

        if not all([category, priority, complexity]):
            return None

        return {
            'pattern_type': 'category_outcome',
            'pattern': {
                'category': category,
                'priority': priority,
                'complexity': complexity,
                'outcome': outcome
            }
        }

    def _store_insights(self, proposal_id: int, patterns: List[Dict]) -> bool:
        """
        Store learned insights in long_term_memory.

        Args:
            proposal_id: Proposal ID
            patterns: List of pattern dicts

        Returns:
            True if stored successfully
        """
        conn = self.get_db()
        cur = conn.cursor()

        try:
            # Check if long_term_memory table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'long_term_memory'
                )
            """)

            table_exists = cur.fetchone()[0]

            if not table_exists:
                cur.close()
                conn.close()
                return False

            # Store each pattern as a memory
            for pattern in patterns:
                cur.execute("""
                    INSERT INTO long_term_memory
                    (memory_type, content, tags, importance_score, metadata, created_at)
                    VALUES ('learning', %s, %s, %s, %s, NOW())
                """, (
                    json.dumps(pattern),
                    ['improvement_learning', pattern['pattern_type']],
                    0.7,  # Medium importance
                    json.dumps({
                        'proposal_id': proposal_id,
                        'learned_at': datetime.now().isoformat()
                    })
                ))

            conn.commit()
            cur.close()
            conn.close()

            return True

        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return False

    def get_learning_insights(self, limit: int = 20) -> Dict:
        """
        Get recent learning insights.

        Returns:
            {
                'success': True,
                'insights': [...],
                'total': 15
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if long_term_memory exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'long_term_memory'
                )
            """)

            table_exists = cur.fetchone()[0]

            if not table_exists:
                cur.close()
                conn.close()
                return {
                    'success': True,
                    'insights': [],
                    'total': 0,
                    'message': 'No long_term_memory table found'
                }

            # Get learning memories
            cur.execute("""
                SELECT * FROM long_term_memory
                WHERE memory_type = 'learning'
                AND 'improvement_learning' = ANY(tags)
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            memories = cur.fetchall()

            insights = []
            for mem in memories:
                content = mem['content']
                if isinstance(content, str):
                    content = json.loads(content)

                insights.append({
                    'id': mem['id'],
                    'pattern_type': content.get('pattern_type'),
                    'pattern': content.get('pattern'),
                    'created_at': mem['created_at'].isoformat() if mem.get('created_at') else None
                })

            cur.close()
            conn.close()

            return {
                'success': True,
                'insights': insights,
                'total': len(insights)
            }

        except Exception as e:
            cur.close()
            conn.close()
            return {
                'success': False,
                'error': str(e)
            }

    def get_learning_stats(self) -> Dict:
        """
        Get learning statistics.

        Returns:
            {
                'success': True,
                'total_completed': 50,
                'success_rate': 85.5,
                'avg_proficiency_change': +0.3,
                'patterns_discovered': 120
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Total completed
            cur.execute("""
                SELECT COUNT(*) as total
                FROM improvement_proposals
                WHERE status = 'completed'
            """)
            total_completed = cur.fetchone()['total']

            # Success rate (not rolled back)
            cur.execute("""
                SELECT COUNT(*) as successes
                FROM improvement_proposals p
                LEFT JOIN improvement_deployments d ON p.id = d.proposal_id
                WHERE p.status = 'completed'
                AND (d.id IS NULL OR d.status != 'rolled_back')
            """)
            successes = cur.fetchone()['successes']

            success_rate = (successes / total_completed * 100) if total_completed > 0 else 0

            # Patterns discovered
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'long_term_memory'
                )
            """)
            has_memory = cur.fetchone()[0]

            patterns_count = 0
            if has_memory:
                cur.execute("""
                    SELECT COUNT(*) as patterns
                    FROM long_term_memory
                    WHERE memory_type = 'learning'
                    AND 'improvement_learning' = ANY(tags)
                """)
                patterns_count = cur.fetchone()['patterns']

            cur.close()
            conn.close()

            return {
                'success': True,
                'total_completed': total_completed,
                'total_successes': successes,
                'success_rate': round(success_rate, 1),
                'patterns_discovered': patterns_count,
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
# CONVENIENCE FUNCTIONS
# ============================================================================

def learn_from_proposal(proposal_id: int) -> Dict:
    """Quick function to learn from completed proposal"""
    learning = ImprovementLearning()
    return learning.learn_from_completion(proposal_id)


def get_insights(limit: int = 20) -> Dict:
    """Quick function to get learning insights"""
    learning = ImprovementLearning()
    return learning.get_learning_insights(limit)


def get_stats() -> Dict:
    """Quick function to get learning stats"""
    learning = ImprovementLearning()
    return learning.get_learning_stats()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    print("Improvement Learning Engine - Test Mode")
    print("=" * 60)

    learning = ImprovementLearning()

    print("\n1. LEARNING STATISTICS:")
    print("-" * 60)
    stats = learning.get_learning_stats()
    if stats['success']:
        print(f"Total completed: {stats['total_completed']}")
        print(f"Success rate: {stats['success_rate']}%")
        print(f"Patterns discovered: {stats['patterns_discovered']}")
    else:
        print(f"Error: {stats.get('error')}")

    print("\n2. RECENT INSIGHTS:")
    print("-" * 60)
    insights = learning.get_learning_insights(limit=5)
    if insights['success']:
        print(f"Total insights: {insights['total']}")
        for insight in insights['insights'][:5]:
            print(f"  - {insight['pattern_type']}: {insight.get('created_at', 'N/A')}")
    else:
        print(f"Error: {insights.get('error')}")

    print("\n✅ Improvement Learning Engine loaded successfully!")
