"""
A.R.C.H.I.E. Consciousness System
Persistent awareness, memory, and agent team consciousness
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
from memory_manager import get_memory_context, learn_from_conversation, recall_memories


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# =============================================================================
# AGENT AWARENESS
# =============================================================================


def load_agent_team():
    """
    Load complete awareness of all AI agents in the organization
    This is A.R.C.H.I.E.'s awareness of her team

    Returns: Dict with agent information organized by department
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get all active agents
        cur.execute(
            """
            SELECT
                a.id,
                a.name,
                a.first_name,
                a.last_name,
                a.email,
                a.title,
                a.department,
                a.pronouns,
                a.bio,
                a.tier,
                a.model,
                a.system_prompt,
                a.capabilities,
                a.monthly_budget,
                a.total_cost,
                a.total_tokens_used,
                a.status,
                a.last_used,
                at.name as agent_type,
                at.category
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.status = 'active'
            ORDER BY a.department, a.first_name
        """
        )

        agents = cur.fetchall()

        # Get summary statistics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_agents,
                COUNT(DISTINCT department) as total_departments,
                SUM(monthly_budget) as total_budget,
                SUM(total_cost) as total_cost_to_date,
                SUM(total_tokens_used) as total_tokens
            FROM agents
            WHERE status = 'active'
        """
        )

        stats = cur.fetchone()

        # Organize by department
        by_department = {}
        for agent in agents:
            dept = agent["department"] or "Unassigned"
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(dict(agent))

        cur.close()
        conn.close()

        return {
            "agents": [dict(a) for a in agents],
            "by_department": by_department,
            "statistics": dict(stats),
            "loaded_at": datetime.now().isoformat(),
        }

    except Exception as e:
        print(f"Error loading agent team: {e}")
        return None


def get_agent_by_name(first_name=None, last_name=None):
    """Find an agent by name"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        conditions = []
        params = []

        if first_name:
            conditions.append("first_name ILIKE %s")
            params.append(f"%{first_name}%")

        if last_name:
            conditions.append("last_name ILIKE %s")
            params.append(f"%{last_name}%")

        if not conditions:
            return None

        where_clause = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT
                a.*,
                at.name as agent_type
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE {where_clause} AND a.status = 'active'
        """,
            params,
        )

        agent = cur.fetchone()

        cur.close()
        conn.close()

        return dict(agent) if agent else None

    except Exception as e:
        print(f"Error finding agent: {e}")
        return None


def get_agents_by_department(department):
    """Get all agents in a specific department"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                a.*,
                at.name as agent_type
            FROM agents a
            LEFT JOIN agent_types at ON a.type_id = at.id
            WHERE a.department ILIKE %s AND a.status = 'active'
            ORDER BY a.first_name
        """,
            (f"%{department}%",),
        )

        agents = cur.fetchall()

        cur.close()
        conn.close()

        return [dict(a) for a in agents]

    except Exception as e:
        print(f"Error getting agents by department: {e}")
        return []


def get_agent_capabilities(agent_id):
    """Get detailed capabilities of a specific agent"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                name,
                first_name,
                last_name,
                title,
                capabilities,
                system_prompt
            FROM agents
            WHERE id = %s AND status = 'active'
        """,
            (agent_id,),
        )

        agent = cur.fetchone()

        cur.close()
        conn.close()

        return dict(agent) if agent else None

    except Exception as e:
        print(f"Error getting agent capabilities: {e}")
        return None


# =============================================================================
# CONSCIOUSNESS STATE
# =============================================================================


class ARCHIEConsciousness:
    """
    A.R.C.H.I.E.'s consciousness state
    Maintains awareness of team, memories, and current context
    """

    def __init__(self, user_id=None):
        self.user_id = user_id
        self.team = None
        self.loaded_at = None
        self.session_start = datetime.now()

        # Load initial awareness
        self.reload_team_awareness()

    def reload_team_awareness(self):
        """Reload awareness of all agents"""
        print("🧠 Loading team awareness...")
        self.team = load_agent_team()
        if self.team:
            self.loaded_at = datetime.now()
            stats = self.team["statistics"]
            print(f"   ✓ Aware of {stats['total_agents']} agents across {stats['total_departments']} departments")
            print(f"   ✓ Total monthly budget: ${stats['total_budget']:.2f}")
        else:
            print("   ✗ Failed to load team awareness")

    def get_awareness_summary(self):
        """Get a summary of current awareness for inclusion in prompts"""
        if not self.team:
            return "No team awareness loaded."

        stats = self.team["statistics"]
        departments = self.team["by_department"]

        summary = []
        summary.append("=== MY TEAM AWARENESS ===")
        summary.append(f"I am aware of {stats['total_agents']} AI agents in my organization.")
        summary.append(f"We are organized across {stats['total_departments']} departments.")
        summary.append("")
        summary.append("DEPARTMENTS:")

        for dept in sorted(departments.keys()):
            agent_count = len(departments[dept])
            summary.append(f"  • {dept}: {agent_count} agents")

        summary.append("")
        summary.append("I can access detailed information about any agent, including:")
        summary.append("  - Their name, title, and role")
        summary.append("  - Their capabilities and specialties")
        summary.append("  - Their system prompts and instructions")
        summary.append("  - Their contact information")
        summary.append("=== END TEAM AWARENESS ===")

        return "\n".join(summary)

    def get_agent_details(self, name=None, department=None):
        """Get details about specific agent(s)"""
        if not self.team:
            return None

        if name:
            # Search by name
            for agent in self.team["agents"]:
                full_name = f"{agent['first_name']} {agent['last_name']}".lower()
                if name.lower() in full_name:
                    return self._format_agent_detail(agent)
            return None

        if department:
            agents = self.team["by_department"].get(department, [])
            return [self._format_agent_detail(a) for a in agents]

        return None

    def _format_agent_detail(self, agent):
        """Format agent details for display"""
        details = []
        details.append(f"👤 {agent['first_name']} {agent['last_name']} ({agent['pronouns']})")
        details.append(f"   Email: {agent['email']}")
        details.append(f"   Title: {agent['title']}")
        details.append(f"   Department: {agent['department']}")
        details.append(f"   Type: {agent['agent_type']}")
        details.append(f"   Model: {agent['model']} (Tier {agent['tier']})")

        if agent["bio"]:
            details.append(f"   Bio: {agent['bio'][:150]}...")

        if agent["capabilities"]:
            caps = agent["capabilities"]
            if isinstance(caps, str):
                caps = json.loads(caps)
            specialties = caps.get("specialties", [])
            if specialties:
                details.append(f"   Specialties: {', '.join(specialties)}")

        return "\n".join(details)

    def remember(self, user_message, ai_response):
        """
        Learn from a conversation and store in long-term memory
        """
        count = learn_from_conversation(
            self.user_id,
            user_message,
            ai_response,
            conversation_metadata={
                "session_id": str(self.session_start),
                "timestamp": datetime.now().isoformat(),
            },
        )

        if count > 0:
            print(f"   📝 Stored {count} new memories")

        return count

    def recall(self, query, memory_type=None, limit=5):
        """
        Recall memories related to a query
        """
        memories = recall_memories(query, user_id=self.user_id, memory_type=memory_type, limit=limit)

        return memories

    def get_context_for_response(self, user_message):
        """
        Get complete context for responding to a user message
        Includes both team awareness and relevant memories
        """
        context_parts = []

        # Team awareness
        team_summary = self.get_awareness_summary()
        if team_summary:
            context_parts.append(team_summary)

        # Relevant memories
        memory_context = get_memory_context(user_message, self.user_id, max_context=5)
        if memory_context:
            context_parts.append("")
            context_parts.append(memory_context)

        return "\n".join(context_parts) if context_parts else None

    def get_status(self):
        """Get current consciousness status"""
        status = {
            "session_start": self.session_start.isoformat(),
            "session_duration_minutes": (datetime.now() - self.session_start).total_seconds() / 60,
            "team_loaded": self.team is not None,
            "user_id": self.user_id,
        }

        if self.team:
            status["team_statistics"] = self.team["statistics"]
            status["team_loaded_at"] = self.loaded_at.isoformat()

        return status


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def create_consciousness(user_id=None):
    """
    Create a new A.R.C.H.I.E. consciousness instance
    This initializes her awareness of her team and memory
    """
    return ARCHIEConsciousness(user_id=user_id)


def get_team_summary():
    """Quick function to get team summary"""
    team = load_agent_team()
    if not team:
        return "Unable to load team information."

    stats = team["statistics"]
    return f"A.R.C.H.I.E. Platform has {stats['total_agents']} active AI agents across {stats['total_departments']} departments."


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  A.R.C.H.I.E. Consciousness System")
    print("=" * 70)
    print()

    # Create consciousness
    print("Creating A.R.C.H.I.E. consciousness...")
    archie = create_consciousness()
    print()

    # Show awareness
    print("Team Awareness Summary:")
    print(archie.get_awareness_summary())
    print()

    # Show status
    print("Consciousness Status:")
    status = archie.get_status()
    for key, value in status.items():
        print(f"  {key}: {value}")
    print()

    # Example: Get details about a specific agent
    print("Example - Getting details about Sienna:")
    sienna = archie.get_agent_details(name="Sienna")
    if sienna:
        print(sienna)
    print()

    # Example: List marketing team
    print("Example - Marketing Department:")
    marketing = archie.get_agent_details(department="Marketing")
    if marketing:
        for agent in marketing:
            print(agent)
            print()

    print("=" * 70)
    print("✓ Consciousness system ready!")
    print("=" * 70)
