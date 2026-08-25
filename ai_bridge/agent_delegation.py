"""
A.R.C.H.I.E. Agent Delegation System
Shows which employee (agent) is handling each task
Includes audit trail for HR and Finance

PERFORMANCE: Agent selection optimized with caching and indexed queries
- Delegation decision: <10ms (keyword matching + cached SQL)
- No LLM call for routing (pure keyword logic)
- Only the delegated agent makes LLM calls
"""

import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import time
from functools import lru_cache

sys.path.insert(0, "/app/ai_bridge")

# Simple in-memory cache for agent selection
# Cache expires when process restarts (which is fine - agent availability changes)
_agent_cache = {}
_cache_timestamp = time.time()


from archie_bridge import archie_bridge
from db import get_db


def check_api_key_configured(model: str) -> dict:
    """
    Check if required API key is configured for CONTRACT agents

    Returns:
        {
            'configured': bool,
            'provider': str,
            'error': str (if not configured)
        }
    """
    # Map models to their API providers
    model_lower = model.lower()

    provider_map = {
        "claude": ["claude", "anthropic"],
        "openai": ["gpt", "openai"],
        "mistral": ["mistral"],
        "gemini": ["gemini", "google"],
        "cohere": ["cohere"],
    }

    # Ollama models don't need API keys (local)
    if any(
        ollama_keyword in model_lower
        for ollama_keyword in [
            "ollama",
            "llama",
            "qwen",
            "deepseek",
            "phi",
            "mistral:latest",
        ]
    ):
        return {"configured": True, "provider": "ollama", "error": None}

    # Detect provider from model name
    detected_provider = None
    for provider, keywords in provider_map.items():
        if any(keyword in model_lower for keyword in keywords):
            detected_provider = provider
            break

    if not detected_provider:
        return {
            "configured": False,
            "provider": "unknown",
            "error": f"Unknown model provider for: {model}",
        }

    # Check if API key is configured in database
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT provider, api_key, enabled
            FROM archie_api_settings
            WHERE provider = %s
        """,
            (detected_provider,),
        )

        provider_config = cur.fetchone()

        if not provider_config:
            return {
                "configured": False,
                "provider": detected_provider,
                "error": f"{detected_provider.upper()} provider not configured in API Settings",
            }

        if not provider_config["enabled"]:
            return {
                "configured": False,
                "provider": detected_provider,
                "error": f"{detected_provider.upper()} is disabled in API Settings",
            }

        if not provider_config.get("api_key"):
            return {
                "configured": False,
                "provider": detected_provider,
                "error": f"{detected_provider.upper()} API key not set in API Settings",
            }

        return {"configured": True, "provider": detected_provider, "error": None}

    except Exception as e:
        return {
            "configured": False,
            "provider": detected_provider,
            "error": f"Error checking API key: {str(e)}",
        }
    finally:
        try:
            cur.close()
        except Exception:
            pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def select_best_agent_for_task(
    task_description: str,
    department_preference: str = None,
    prefer_contractor: bool = False,
):
    """
    FAST agent selection with caching (typically <10ms)

    Select the best agent to handle a task based on:
    - Task description (keywords matching agent expertise)
    - Department preference
    - Agent availability and performance
    - Worker type (prefer internal/free first, unless prefer_contractor=True)

    Args:
        task_description: Description of the task to delegate
        department_preference: Preferred department (e.g., 'Engineering')
        prefer_contractor: If True, prefer contractors (external AI like Claude/GPT-4)
                          for complex tasks requiring higher accuracy

    PERFORMANCE: No LLM calls - pure keyword matching + indexed SQL query

    Returns:
        {
            'agent_id': int,
            'name': str,
            'department': str,
            'worker_type': str,  # 'internal' or 'contract'
            'model': str,
            'tier': str,
            'bio': str,
            'reason': str  # Why this agent was selected
        }
    """
    global _agent_cache, _cache_timestamp

    # Cache invalidation: expire after 60 seconds
    if time.time() - _cache_timestamp > 60:
        _agent_cache = {}
        _cache_timestamp = time.time()

    # Extract keywords from task for matching (FAST - no LLM)
    task_lower = task_description.lower()

    # Department keyword mapping (instant keyword lookup)
    department_keywords = {
        "Engineering": [
            "code",
            "bug",
            "develop",
            "implement",
            "refactor",
            "api",
            "backend",
            "frontend",
        ],
        "Quality Assurance": ["test", "qa", "quality", "bug", "verify", "validate"],
        "Documentation": ["document", "readme", "guide", "explain", "write"],
        "Infrastructure": ["deploy", "server", "database", "infrastructure", "devops"],
        "Security": ["security", "auth", "permission", "vulnerability", "encrypt"],
        "Data Science": ["data", "analysis", "ml", "model", "analytics", "predict"],
        "Marketing": ["marketing", "content", "campaign", "seo", "social"],
        "Customer Support": ["support", "help", "customer", "issue", "ticket"],
        "Operations": ["optimize", "process", "efficiency", "workflow", "improve"],
        "Finance": ["cost", "budget", "revenue", "financial", "accounting"],
    }

    # Detect department from keywords (INSTANT)
    detected_department = department_preference
    if not detected_department:
        for dept, keywords in department_keywords.items():
            if any(keyword in task_lower for keyword in keywords):
                detected_department = dept
                break

    # Check cache first (INSTANT - no database query)
    # Include prefer_contractor in cache key to differentiate
    cache_key = f"{detected_department or 'general'}_{prefer_contractor}"
    if cache_key in _agent_cache:
        cached_agent = _agent_cache[cache_key].copy()
        cached_agent["reason"] = f"Selected for {detected_department or 'general'} expertise (cached)"
        if cached_agent["worker_type"] == "internal":
            cached_agent["reason"] += " (Internal Staff - FREE)"
        else:
            cached_agent["reason"] += " (Contractor - PAID)"
        return cached_agent

    # Query for best agent (with optimized indexed lookup)
    # Prefer internal (free) agents, then by last_used (least recently used gets priority)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                a.id, a.name, a.first_name, a.last_name, a.title,
                a.department, a.worker_type, a.model,
                a.tier, a.bio, a.total_cost, a.last_used, a.status
            FROM agents a
            WHERE a.status = 'active'
        """
        params = []

        if detected_department:
            query += " AND a.department = %s"
            params.append(detected_department)

        if prefer_contractor:
            query += """
                ORDER BY
                    CASE WHEN a.worker_type = 'contract' THEN 0 ELSE 1 END,
                    a.last_used ASC NULLS FIRST
                LIMIT 1
            """
        else:
            query += """
                ORDER BY
                    CASE WHEN a.worker_type = 'internal' THEN 0 ELSE 1 END,
                    a.last_used ASC NULLS FIRST
                LIMIT 1
            """

        cur.execute(query, params)
        agent = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    if not agent:
        # Fallback: get any active agent
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, name, first_name, last_name, title, department, worker_type, model, tier, bio
                FROM agents
                WHERE status = 'active'
                ORDER BY
                    CASE WHEN worker_type = 'internal' THEN 0 ELSE 1 END,
                    last_used ASC NULLS FIRST
                LIMIT 1
            """
            )
            agent = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        if not agent:
            return None

    # CRITICAL: Validate API key for CONTRACT agents
    if agent["worker_type"] == "contract":
        api_check = check_api_key_configured(agent["model"])

        if not api_check["configured"]:
            # API key not configured - fallback to internal agent in same department
            print(f"⚠️  CONTRACT agent {agent['name']} requires {api_check['provider'].upper()} API key")
            print(f"⚠️  Reason: {api_check['error']}")
            print(f"⚠️  Falling back to internal staff...")

            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Try to find internal agent in same department
                fallback_query = """
                    SELECT id, name, first_name, last_name, title, department, worker_type, model, tier, bio
                    FROM agents
                    WHERE status = 'active'
                      AND worker_type = 'internal'
                """
                fallback_params = []

                if detected_department:
                    fallback_query += " AND department = %s"
                    fallback_params.append(detected_department)

                fallback_query += " ORDER BY last_used ASC NULLS FIRST LIMIT 1"

                cur.execute(fallback_query, fallback_params)
                fallback_agent = cur.fetchone()

                if not fallback_agent:
                    # No internal agent in same department, get any internal agent
                    cur.execute(
                        """
                        SELECT id, name, first_name, last_name, title, department, worker_type, model, tier, bio
                        FROM agents
                        WHERE status = 'active' AND worker_type = 'internal'
                        ORDER BY last_used ASC NULLS FIRST
                        LIMIT 1
                    """
                    )
                    fallback_agent = cur.fetchone()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            if fallback_agent:
                agent = fallback_agent
                print(f"✓ Using internal agent: {agent['name']} ({agent['department']})")
            else:
                # No internal agents available - return error info with contract agent
                agent["api_error"] = api_check["error"]
                agent["api_provider"] = api_check["provider"]

    # Build reason
    reason = f"Selected for {detected_department or 'general'} expertise"
    if agent["worker_type"] == "internal":
        reason += " (Internal Staff - FREE)"
    else:
        reason += " (Contractor - PAID)"

    # Add API error to reason if present
    if agent.get("api_error"):
        reason += f" - WARNING: {agent['api_error']}"

    result = dict(agent) | {"reason": reason}

    # Store in cache for next time (60-second TTL)
    _agent_cache[cache_key] = dict(agent)

    return result


def quick_acknowledgment(agent_name: str, agent_title: str) -> str:
    """
    Generate a very fast acknowledgment message using minimal processing
    This runs before the full LLM call to give instant feedback

    Args:
        agent_name: Name of agent being delegated to
        agent_title: Title of agent

    Returns:
        Quick acknowledgment message
    """
    # Simple template-based acknowledgment (instant, no LLM needed)
    templates = [
        f"One moment while I connect you with {agent_name}, our {agent_title}...",
        f"Transferring your request to {agent_name} ({agent_title})...",
        f"Let me get {agent_name} to help you with this...",
    ]
    import random

    return random.choice(templates)


def execute_with_delegation(
    task: str,
    user_id: int = None,
    department: str = None,
    force_agent_id: int = None,
    return_quick_ack: bool = False,
):
    """
    Execute a task with clear employee delegation and tracking

    Args:
        task: Task description
        user_id: User ID for audit trail
        department: Preferred department
        force_agent_id: Force specific agent
        return_quick_ack: If True, return quick acknowledgment immediately

    Returns:
        {
            'success': bool,
            'response': str,
            'delegation': {
                'employee_name': str,
                'employee_title': str,
                'department': str,
                'worker_type': str,  # 'internal' or 'contract'
                'model': str,
                'reason': str
            },
            'execution_record': {
                'execution_id': int,
                'started_at': str,
                'duration_seconds': float,
                'tokens_used': int,
                'cost': float
            },
            'audit_trail': str,  # Reference for HR/Finance
            'quick_ack': str (if return_quick_ack=True)
        }
    """
    start_time = time.time()

    # Select agent
    if force_agent_id:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, name, department, worker_type, model, tier, bio
                FROM agents WHERE id = %s
            """,
                (force_agent_id,),
            )
            agent = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        if not agent:
            return {"success": False, "error": f"Agent {force_agent_id} not found"}

        agent = dict(agent)
        agent["reason"] = "Manually selected"
    else:
        agent = select_best_agent_for_task(task, department)

        if not agent:
            return {"success": False, "error": "No suitable agent available"}

    # Create execution record for audit trail
    conn = get_db()
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Validate user_id exists, otherwise use NULL
        validated_user_id = None
        if user_id:
            try:
                cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if cur.fetchone():
                    validated_user_id = user_id
            except Exception:
                pass  # Use NULL if validation fails

        cur.execute(
            """
            INSERT INTO agent_executions
            (agent_id, user_id, task_description, status, started_at, input_data)
            VALUES (%s, %s, %s, 'running', NOW(), %s)
            RETURNING id, started_at
        """,
            (
                agent["id"],
                validated_user_id,
                task,
                json.dumps({"task": task, "department": department}),
            ),
        )

        execution = cur.fetchone()
        execution_id = execution["id"]
        started_at = execution["started_at"]
        conn.commit()

        # Build delegation message with actual name
        first_name = agent.get("first_name", "")
        last_name = agent.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() if first_name or last_name else agent["name"]

        delegation_info = {
            "employee_name": full_name,
            "employee_title": agent.get("title") or agent.get("bio") or f"{agent['department']} Specialist",
            "department": agent["department"],
            "worker_type": agent["worker_type"],
            "model": agent["model"],
            "tier": agent.get("tier", "standard"),
            "reason": agent["reason"],
        }

        # Generate quick acknowledgment (INSTANT - no LLM call)
        quick_ack_msg = quick_acknowledgment(full_name, delegation_info["employee_title"])
        print(f"⚡ Fast routing complete in {(time.time() - start_time) * 1000:.1f}ms")
        print(f"📨 {quick_ack_msg}")

        # Import tools for agents
        try:
            from consciousness.archie_tools import list_available_tools, execute_tool

            tools_enabled = True
            available_tools = list_available_tools()
        except Exception:
            # Bind the name on the failure path too. `execute_tool` is called ~120 lines
            # below under `if tools_enabled and ...`, so this was correct — but only by
            # the grace of a guard far away, and an inner `except Exception` there would
            # have reported a NameError as "Tool execution error", hiding the real cause.
            # Binding it to None makes the flag the ONLY control and removes the
            # UnboundLocalError class entirely (#6022).
            execute_tool = None
            tools_enabled = False
            available_tools = {}

        # Build system prompt with delegation context AND TOOLS
        # IMPORTANT: Keep focused on the current task, avoid pulling unrelated memories
        system_prompt = f"""You are {full_name}, working as {delegation_info['employee_title']} in the {agent['department']} department.

    Role: {agent.get('bio', '')}

    Context: You have been assigned this task by A.R.C.H.I.E.'s delegation system.

    Instructions:
    - Focus ONLY on the current user request
    - Provide direct, helpful, and professional assistance
    - If you don't have enough information, ask clarifying questions
    - Do NOT reference unrelated past conversations or topics
    - Stay on topic and be concise
    """

        if tools_enabled and available_tools:
            system_prompt += f"""

    CRITICAL: You have access to TOOLS that can ACTUALLY DO THINGS (not just talk about them):

    Available Tools:
    {chr(10).join(f'  • {name}: {desc}' for name, desc in available_tools.items())}

    TOOL FORMAT (EXACT):
    TOOL_CALL: tool_name
    {{
      "parameter_name": "value"
    }}

    REAL EXAMPLES:

    Example 1 - Create a proposal:
    User: "We should improve error handling in the login function"
    You: "Great idea! Let me create an improvement proposal for this.

    TOOL_CALL: create_improvement_proposal
    {{
      "title": "Improve error handling in login function",
      "description": "Add better error handling and user feedback for login failures",
      "category": "bug_fix",
      "priority": "high"
    }}

    I've created a proposal to track this improvement!"

    Example 2 - Search code:
    User: "Find all authentication functions"
    You: "Let me search for authentication code.

    TOOL_CALL: search_code
    {{
      "pattern": "def.*auth",
      "directory": "/app"
    }}

    Found the authentication functions..."

    IMPORTANT RULES:
    1. USE TOOLS to actually complete tasks - don't just talk about doing them
    2. For improvement suggestions → use create_improvement_proposal
    3. For code questions → use search_code or read_file
    4. For database queries → use query_database
    5. Always explain what you're doing before and after using a tool
    """

        # Execute task using archie_bridge
        # NOTE: Memory disabled for agents to keep responses focused and fast
        result = archie_bridge(
            task,
            user_id=user_id,
            system_prompt=system_prompt,
            force_model=agent["model"],
            enable_memory=False,  # Disabled to prevent confusing cross-talk from unrelated memories
            agent_id=agent["id"],
        )

        # Process tool calls if present
        if tools_enabled and result.get("success") and result.get("response"):
            response_text = result["response"]

            # Check for tool calls in response
            if "TOOL_CALL:" in response_text:
                print(f"🔧 TOOL CALL DETECTED in response!")
                tool_results = []
                lines = response_text.split("\n")

                i = 0
                while i < len(lines):
                    if lines[i].startswith("TOOL_CALL:"):
                        tool_name = lines[i].replace("TOOL_CALL:", "").strip()

                        # Collect JSON args
                        json_str = ""
                        i += 1
                        brace_count = 0
                        while i < len(lines):
                            line = lines[i]
                            json_str += line + "\n"

                            if "{" in line:
                                brace_count += line.count("{")
                            if "}" in line:
                                brace_count -= line.count("}")

                            if brace_count == 0 and json_str.strip():
                                break
                            i += 1

                        # Execute tool
                        try:
                            args = json.loads(json_str)
                            print(f"🔧 Executing tool: {tool_name} with args: {args}")
                            tool_result = execute_tool(tool_name, **args)
                            print(f"✅ Tool result: {tool_result}")
                            tool_results.append({"tool": tool_name, "args": args, "result": tool_result})
                        except Exception as e:
                            print(f"❌ Tool execution error: {str(e)}")
                            tool_results.append({"tool": tool_name, "error": str(e)})

                    i += 1

                # Append tool results to response
                if tool_results:
                    result["response"] += "\n\n--- TOOL EXECUTION RESULTS ---\n"
                    for tr in tool_results:
                        if "error" in tr:
                            result["response"] += f"\n❌ {tr['tool']}: {tr['error']}"
                        else:
                            result["response"] += f"\n✓ {tr['tool']}: {json.dumps(tr['result'], indent=2)}"

                    result["tools_used"] = tool_results
            else:
                print(f"⚠️ NO TOOL CALLS detected in response (tools_enabled={tools_enabled})")

        duration = time.time() - start_time

        # Update execution record
        if result.get("success"):
            cur.execute(
                """
                UPDATE agent_executions
                SET status = 'completed',
                    completed_at = NOW(),
                    duration_seconds = %s,
                    tokens_used = %s,
                    cost = %s,
                    result = %s
                WHERE id = %s
            """,
                (
                    int(duration),
                    result.get("tokens_used", 0),
                    result.get("cost", 0.0),
                    json.dumps(result),
                    execution_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE agent_executions
                SET status = 'failed',
                    completed_at = NOW(),
                    duration_seconds = %s,
                    error = %s
                WHERE id = %s
            """,
                (int(duration), result.get("error", "Unknown error"), execution_id),
            )

            conn.commit()
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    # Just return the response without the delegation box (it's shown in UI now)
    final_response = result.get("response", "") if result.get("success") else f"ERROR: {result.get('error')}"

    return {
        "success": result.get("success", False),
        "response": final_response,
        "delegation": delegation_info,
        "execution_record": {
            "execution_id": execution_id,
            "started_at": started_at.isoformat() if started_at else None,
            "duration_seconds": round(duration, 2),
            "tokens_used": result.get("tokens_used", 0),
            "cost": result.get("cost", 0.0),
        },
        "audit_trail": f"execution_id:{execution_id}|agent:{agent['id']}|user:{user_id}|timestamp:{datetime.now().isoformat()}",
        "raw_result": result,  # Full result for debugging
    }


def get_agent_directory(include_inactive=False):
    """
    Get employee directory showing all agents

    Returns:
        {
            'internal_staff': [...],
            'contractors': [...],
            'stats': {...}
        }
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                a.id, a.name, a.department, a.worker_type, a.model,
                a.tier, a.bio, a.status, a.last_used, a.total_cost,
                a.total_tokens_used,
                COUNT(ae.id) as total_executions
            FROM agents a
            LEFT JOIN agent_executions ae ON a.id = ae.agent_id
        """

        if not include_inactive:
            query += " WHERE a.status = 'active'"

        query += """
            GROUP BY a.id
            ORDER BY
                a.worker_type ASC,
                a.department ASC,
                a.name ASC
        """

        cur.execute(query)
        agents = cur.fetchall()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    internal_staff = []
    contractors = []

    for agent in agents:
        agent_dict = dict(agent)
        if agent["worker_type"] == "internal":
            internal_staff.append(agent_dict)
        else:
            contractors.append(agent_dict)

    stats = {
        "total_employees": len(agents),
        "internal_staff_count": len(internal_staff),
        "contractors_count": len(contractors),
        "active_count": sum(1 for a in agents if a["status"] == "active"),
        "total_cost": sum(float(a.get("total_cost", 0) or 0) for a in agents),
    }

    return {
        "internal_staff": internal_staff,
        "contractors": contractors,
        "stats": stats,
    }


def get_execution_audit_trail(execution_id: int):
    """
    Get complete audit trail for an execution (for HR/Finance)

    Returns:
        {
            'execution': {...},
            'agent': {...},
            'user': {...},
            'cost_details': {...}
        }
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                ae.*,
                a.name as agent_name,
                a.department,
                a.worker_type,
                a.model,
                u.username,
                u.email
            FROM agent_executions ae
            JOIN agents a ON ae.agent_id = a.id
            LEFT JOIN users u ON ae.user_id = u.id
            WHERE ae.id = %s
        """,
            (execution_id,),
        )

        record = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    if not record:
        return {"success": False, "error": "Execution not found"}

    return {
        "success": True,
        "execution": {
            "execution_id": record["id"],
            "task_description": record["task_description"],
            "status": record["status"],
            "started_at": (record["started_at"].isoformat() if record.get("started_at") else None),
            "completed_at": (record["completed_at"].isoformat() if record.get("completed_at") else None),
            "duration_seconds": record.get("duration_seconds"),
            "error": record.get("error"),
        },
        "agent": {
            "name": record["agent_name"],
            "department": record["department"],
            "worker_type": record["worker_type"],
            "model": record["model"],
        },
        "user": {"username": record.get("username"), "email": record.get("email")},
        "cost_details": {
            "tokens_used": record.get("tokens_used", 0),
            "cost_usd": record.get("cost", 0.0),
            "billable": record["worker_type"] == "contract",
        },
    }


# Example usage
if __name__ == "__main__":
    print("=" * 80)
    print("A.R.C.H.I.E. Agent Delegation System - Test")
    print("=" * 80)

    # Test 1: Get employee directory
    print("\n📋 EMPLOYEE DIRECTORY")
    directory = get_agent_directory()
    print(f"\nInternal Staff: {directory['stats']['internal_staff_count']}")
    print(f"Contractors: {directory['stats']['contractors_count']}")
    print(f"Total Cost: ${directory['stats']['total_cost']:.2f}")

    print("\n--- Internal Staff (First 5) ---")
    for agent in directory["internal_staff"][:5]:
        print(f"  {agent['name']} - {agent['department']} ({agent['model']})")

    print("\n--- Contractors (First 5) ---")
    for agent in directory["contractors"][:5]:
        print(
            f"  ⚠️  {agent['name']} - {agent['department']} ({agent['model']}) - Cost: ${agent.get('total_cost', 0):.2f}"
        )

    # Test 2: Execute task with delegation
    print("\n\n🎯 TASK EXECUTION TEST")
    result = execute_with_delegation(
        task="How can we improve error handling in our codebase?",
        user_id=None,  # System user
        department="Quality Assurance",
    )

    if result["success"]:
        print(f"\n✅ Task executed successfully!")
        print(f"Delegated to: {result['delegation']['employee_name']}")
        print(f"Department: {result['delegation']['department']}")
        print(f"Worker Type: {result['delegation']['worker_type']}")
        print(f"Execution ID: {result['execution_record']['execution_id']}")
        print(f"Duration: {result['execution_record']['duration_seconds']}s")
        print(f"Cost: ${result['execution_record']['cost']:.4f}")
        print(f"Audit Trail: {result['audit_trail']}")
    else:
        print(f"\n❌ Task failed: {result.get('error')}")
