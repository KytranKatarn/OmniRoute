"""
A.R.C.H.I.E. Command Router
Routes parsed intents to appropriate subsystems:
- archie_bridge for AI tasks
- Team Management for agent operations
- Goose/MCP for tool calls and workflows
- Consciousness for knowledge queries
- Contractors for complex tasks requiring escalation
"""

import os
import sys
import json
import logging
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import uuid

# Setup logging
logger = logging.getLogger("archie.command.router")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Add paths for imports
sys.path.insert(0, "/mnt/archie_brain")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

# BridgeDispatcher for centralized model selection
try:
    from ai_bridge.bridge_dispatcher import get_dispatcher as _get_dispatcher

    _dispatcher = _get_dispatcher()
except Exception:
    _dispatcher = None


class CommandRouter:
    """Route parsed intents to appropriate handlers"""

    def __init__(self):
        ollama_host = os.getenv("OLLAMA_PRIMARY", "host.docker.internal:11434")
        self.ollama_url = ollama_host if ollama_host.startswith("http") else f"http://{ollama_host}"
        self.platform_url = "http://localhost:3000"
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": os.getenv("DB_PASSWORD", ""),
        }

        # Model selection based on task complexity (via BridgeDispatcher)
        def _model(capability, fallback):
            if _dispatcher:
                m = _dispatcher.get_model_for_capability(capability)
                if m:
                    return m
            return fallback

        self.model_map = {
            "fast": _model("conversation", "dolphin3-8k:latest"),
            "standard": _model("conversation", "dolphin3-8k:latest"),
            "powerful": _model("code_analysis", "qwen3-coder-cpu:latest"),
            "code": _model("code", "qwen3-coder-cpu:latest"),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    async def _handle_multi_agent_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """
        Handle tasks requiring multi-agent collaboration (Phase 63)

        Uses the team_discussion_engine and archie_bridge to get real AI
        contributions from multiple agents.

        Args:
            intent: Parsed intent with multi-agent config
            context: Conversation context
            user_id: Current user ID

        Returns:
            Result dict with synthesized response and discussion thread
        """
        raw_input = intent.get("raw_input", "")
        stations = intent.get("participating_stations", [])
        domains = intent.get("domains_detected", [])

        try:
            # Import team discussion engine
            from ai_bridge.team_discussion_engine import TeamDiscussionEngine
            from ai_bridge.archie_bridge import archie_bridge

            engine = TeamDiscussionEngine()

            # Start ad-hoc discussion (not linked to a proposal)
            discussion_id = engine.start_adhoc_discussion(topic=raw_input[:200], stations=stations, user_id=user_id)

            if not discussion_id:
                logger.warning("Failed to start multi-agent discussion, falling back to single agent")
                return await self._handle_conversation(intent, context, user_id)

            # Get primary agent for each station
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            contributions = []
            for station in stations[:4]:  # Max 4 stations
                # Get primary agent for this station
                cur.execute(
                    """
                    SELECT a.id, a.name, a.department, a.title, a.model,
                           a.system_prompt, a.communication_style
                    FROM station_assignments sa
                    JOIN bridge_stations bs ON sa.station_id = bs.id
                    JOIN agents a ON sa.agent_id = a.id
                    WHERE UPPER(bs.name) = %s
                    AND sa.role = 'primary'
                    AND a.status = 'active'
                    LIMIT 1
                """,
                    (station.upper(),),
                )

                agent = cur.fetchone()
                if not agent:
                    # Try getting any agent from matching department
                    dept_map = {
                        "ENGINEERING": "Engineering",
                        "SECURITY": "Security",
                        "QA": "QA",
                        "OPERATIONS": "Operations",
                        "CREATIVE": "Creative",
                    }
                    dept = dept_map.get(station, "Engineering")
                    cur.execute(
                        """
                        SELECT id, name, department, title, model,
                               system_prompt, communication_style
                        FROM agents
                        WHERE department = %s AND status = 'active'
                        LIMIT 1
                    """,
                        (dept,),
                    )
                    agent = cur.fetchone()

                if agent:
                    # Build agent-specific prompt
                    comm_style = agent.get("communication_style", "professional and analytical")

                    agent_system = f"""You are {agent['name']}, a {agent['title']} in the {agent['department']} department.
Your communication style: {comm_style}

You are participating in a multi-agent discussion. Other experts from different departments are also contributing.

Provide your expert perspective on the topic. Be concise (2-3 paragraphs max) but insightful.
Focus on aspects relevant to your expertise in {agent['department']}."""

                    # Get agent's contribution via archie_bridge
                    result = archie_bridge(
                        prompt=f"""Topic for discussion: {raw_input}

Domains involved: {', '.join(domains) if domains else 'general'}

Please provide your expert analysis and recommendations from your perspective as {agent['title']} in {agent['department']}.""",
                        system_prompt=agent_system,
                        agent_id=agent["id"],
                        user_id=user_id,
                        force_model=agent.get("model"),
                        try_local_first=True,
                        enable_memory=False,
                    )

                    if result.get("success"):
                        contribution = {
                            "agent_id": agent["id"],
                            "agent_name": agent["name"],
                            "station": station,
                            "department": agent["department"],
                            "title": agent["title"],
                            "response": result.get("response", ""),
                            "model": result.get("model", agent.get("model")),
                            "real_ai": True,
                        }
                        contributions.append(contribution)

                        # Log contribution to discussion
                        engine.agent_contribute(
                            discussion_id=discussion_id,
                            agent_id=agent["id"],
                            message=result.get("response", ""),
                            message_type="analysis",
                            confidence_score=0.8,
                        )

            cur.close()
            conn.close()

            if not contributions:
                logger.warning("No agents contributed to multi-agent discussion")
                return await self._handle_conversation(intent, context, user_id)

            # Synthesize final response
            synthesis_prompt = f"""You are A.R.C.H.I.E., synthesizing a multi-agent discussion.

Original request: {raw_input}

The following experts have contributed their perspectives:

"""
            for c in contributions:
                synthesis_prompt += f"""**{c['agent_name']}** ({c['title']}, {c['department']}):
{c['response']}

---

"""
            synthesis_prompt += """Please synthesize these perspectives into a cohesive response that:
1. Addresses the original request
2. Incorporates key insights from each expert
3. Highlights any areas of agreement or important considerations
4. Provides actionable recommendations

Keep your synthesis concise but comprehensive."""

            synthesis_result = archie_bridge(
                prompt=synthesis_prompt,
                system_prompt="You are A.R.C.H.I.E., a collaborative AI assistant synthesizing expert opinions.",
                user_id=user_id,
                try_local_first=True,
                enable_memory=False,
            )

            final_response = synthesis_result.get("response", "")
            if not final_response:
                # Fallback: combine contributions directly
                final_response = "**Multi-Agent Analysis**\n\n"
                for c in contributions:
                    final_response += f"**{c['agent_name']}** ({c['station']}):\n{c['response']}\n\n"

            # Close discussion
            engine.close_discussion(discussion_id, consensus_reached=True)

            return {
                "success": True,
                "response": final_response,
                "multi_agent": True,
                "discussion_id": discussion_id,
                "participants": [c["agent_name"] for c in contributions],
                "contributions": contributions,
                "stations": stations,
                "domains": domains,
                "model": "multi-agent",
                "agent_used": "Multi-Agent Team",
                "station": "COMMAND",
                "cost": 0.00,
            }

        except Exception as e:
            logger.error(f"Multi-agent task error: {e}")
            import traceback

            traceback.print_exc()
            # Fallback to single agent conversation
            return await self._handle_conversation(intent, context, user_id)

    async def route(self, intent: dict, context: dict, user_id: int) -> dict:
        """
        Route intent to appropriate handler

        Args:
            intent: Parsed intent from IntentParser
            context: Conversation context
            user_id: Current user ID

        Returns:
            Result dict with response and metadata
        """
        intent_type = intent.get("type", "conversation")
        start_time = datetime.now()

        try:
            # Phase 63: Check for multi-agent requirement FIRST
            if intent.get("requires_multi_agent") and intent.get("participating_stations"):
                logger.info(f"Multi-agent task detected: stations={intent.get('participating_stations')}")
                result = await self._handle_multi_agent_task(intent, context, user_id)
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                result["duration_ms"] = duration_ms
                result["intent_type"] = intent_type
                return result

            # Route to appropriate single-agent handler
            if intent_type == "code_task":
                result = await self._handle_code_task(intent, context, user_id)

            elif intent_type == "team_task":
                result = await self._handle_team_task(intent, context, user_id)

            elif intent_type == "business_task":
                result = await self._handle_business_task(intent, context, user_id)

            elif intent_type == "knowledge_query":
                result = await self._handle_knowledge_query(intent, context, user_id)

            elif intent_type == "workflow":
                result = await self._handle_workflow(intent, context, user_id)

            elif intent_type == "file_operation":
                result = await self._handle_file_operation(intent, context, user_id)

            elif intent_type == "creative_task":
                result = await self._handle_creative_task(intent, context, user_id)

            elif intent_type == "system_status":
                result = await self._handle_system_status(intent, context, user_id)

            elif intent_type == "contractor_request":
                result = await self._handle_contractor_request(intent, context, user_id)

            else:
                result = await self._handle_conversation(intent, context, user_id)

            # Add timing
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            result["duration_ms"] = duration_ms
            result["intent_type"] = intent_type

            return result

        except Exception as e:
            logger.error(f"Route error: {e}, intent_type={intent_type}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "routing_error",
                "intent_type": intent_type,
                "duration_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                "fallback_available": True,
                "suggested_modules": ["improvements_lab", "blueprint", "sandbox"],
            }

    async def _handle_code_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Route code tasks to Engineering Station via archie_bridge"""
        raw_input = intent.get("raw_input", "")
        complexity = intent.get("complexity", {})

        # Check if needs contractor escalation
        if complexity.get("requires_contractor") or intent.get("requires_contractor"):
            return await self._request_contractor_escalation(
                intent,
                context,
                user_id,
                reason="Complex code task requiring advanced reasoning",
            )

        # Select model based on complexity
        if complexity.get("score", 5) >= 7:
            model = self.model_map["code"]
        elif complexity.get("score", 5) >= 5:
            model = self.model_map["powerful"]
        else:
            model = self.model_map["standard"]

        # Build coding prompt
        language = intent.get("entities", {}).get("language", "python")
        action = intent.get("entities", {}).get("action", "write")

        system_prompt = f"""You are ARCHIE's Engineering Station, an expert software developer.
You specialize in {language} and are helping with: {action}

Guidelines:
- Write clean, well-documented code
- Follow best practices for {language}
- Explain your reasoning briefly
- If the request is unclear, ask for clarification"""

        # Call Ollama
        response = self._call_ollama(model, system_prompt, raw_input)

        if response["success"]:
            return {
                "success": True,
                "response": response["content"],
                "agent_used": "Engineering Station",
                "model": model,
                "station": "Engineering",
                "cost": 0.00,
                "tokens": response.get("tokens", 0),
            }
        else:
            logger.warning(f"Code task failed: {response.get('error', 'Unknown')}")
            return {
                "success": False,
                "error": response.get("error", "Code generation failed"),
                "error_type": response.get("error_type", "unknown"),
                "escalation_available": True,
                "fallback_available": True,
                "suggested_modules": response.get("suggested_modules", ["improvements_lab", "blueprint", "sandbox"]),
                "suggested_action": "Try creating a proposal or using the Blueprint to break this into smaller tasks.",
            }

    async def _handle_team_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle team management operations"""
        raw_input = intent.get("raw_input", "")
        entities = intent.get("entities", {})

        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            action = entities.get("action", "query")

            if action == "assignment":
                # Handle agent assignment
                agent_name = entities.get("agent_name")
                station = entities.get("station")

                if agent_name and station:
                    # Look up agent
                    cur.execute(
                        "SELECT id, name FROM agents WHERE name ILIKE %s",
                        (f"%{agent_name}%",),
                    )
                    agent = cur.fetchone()

                    if agent:
                        # Look up station
                        cur.execute(
                            "SELECT id, name FROM bridge_stations WHERE name ILIKE %s",
                            (f"%{station}%",),
                        )
                        station_row = cur.fetchone()

                        if station_row:
                            # Create assignment
                            cur.execute(
                                """
                                INSERT INTO station_assignments (station_id, agent_id, role, assigned_by)
                                VALUES (%s, %s, 'primary', %s)
                                ON CONFLICT (station_id, agent_id) DO UPDATE SET role = 'primary'
                            """,
                                (station_row["id"], agent["id"], user_id),
                            )
                            conn.commit()

                            response = f"Done! I've assigned {agent['name']} to {station_row['name']}."
                        else:
                            response = f"I couldn't find a station matching '{station}'. Available stations include: Command, Engineering, Creative, Operations, Security, Medical, HR, R&D, Consciousness, and Away Team."
                    else:
                        response = f"I couldn't find an agent matching '{agent_name}'. Would you like me to show you the current roster?"
                else:
                    # Need more info - use LLM to help
                    response = await self._ask_for_clarification(
                        "I'd be happy to help with that assignment! Could you tell me which agent you'd like to assign and to which station?",
                        context,
                    )
            else:
                # Query team status
                cur.execute(
                    """
                    SELECT bs.name as station, a.name as agent, sa.role
                    FROM station_assignments sa
                    JOIN bridge_stations bs ON sa.station_id = bs.id
                    JOIN agents a ON sa.agent_id = a.id
                    WHERE sa.role = 'primary'
                    ORDER BY bs.name
                """
                )
                assignments = cur.fetchall()

                if assignments:
                    response = "Here's the current station roster:\n\n"
                    for a in assignments:
                        response += f"**{a['station']}**: {a['agent']}\n"
                else:
                    response = "No station assignments found. Would you like me to set some up?"

            cur.close()
            conn.close()

            return {
                "success": True,
                "response": response,
                "agent_used": "ARCHIE (Team Management)",
                "station": "Command",
                "cost": 0.00,
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Team operation failed: {str(e)}",
                "response": f"I ran into an issue with that team operation: {str(e)}",
            }

    async def _handle_business_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle business operations via MCP tools"""
        raw_input = intent.get("raw_input", "").lower()

        # Determine specific business task
        if "invoice" in raw_input:
            return await self._handle_invoice_task(intent, context, user_id)
        elif "email" in raw_input:
            return await self._handle_email_task(intent, context, user_id)
        elif "schedule" in raw_input or "meeting" in raw_input:
            return await self._handle_scheduling_task(intent, context, user_id)
        else:
            # Generic business response
            response = self._call_ollama(
                self.model_map["standard"],
                "You are ARCHIE's Operations Station, handling business tasks.",
                raw_input,
            )

            return {
                "success": True,
                "response": response.get(
                    "content",
                    "I can help with business tasks! I can create invoices, send emails, and manage scheduling. What would you like to do?",
                ),
                "agent_used": "Operations Station",
                "station": "Operations",
                "cost": 0.00,
            }

    async def _handle_knowledge_query(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle knowledge queries via Consciousness system"""
        raw_input = intent.get("raw_input", "")

        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Search knowledge base
            cur.execute(
                """
                SELECT title, content, source_type, importance_score,
                       ts_rank(search_vector, plainto_tsquery('english', %s)) as rank
                FROM knowledge_base
                WHERE search_vector @@ plainto_tsquery('english', %s)
                ORDER BY importance_score * 0.3 + ts_rank(search_vector, plainto_tsquery('english', %s)) * 0.7 DESC
                LIMIT 5
            """,
                (raw_input, raw_input, raw_input),
            )

            results = cur.fetchall()
            cur.close()
            conn.close()

            if results:
                # Synthesize response using LLM
                context_text = "\n\n".join(
                    [f"**{r['title']}** ({r['source_type']}):\n{r['content'][:500]}" for r in results[:3]]
                )

                synthesis_prompt = f"""Based on our knowledge base, answer this question: "{raw_input}"

Relevant knowledge:
{context_text}

Provide a helpful, conversational answer. If the knowledge doesn't fully answer the question, say so."""

                response = self._call_ollama(
                    self.model_map["standard"],
                    "You are ARCHIE's Consciousness, with access to our knowledge base.",
                    synthesis_prompt,
                )

                return {
                    "success": True,
                    "response": response.get(
                        "content",
                        "I found some relevant information but had trouble synthesizing it.",
                    ),
                    "agent_used": "Consciousness",
                    "station": "Consciousness",
                    "sources": [{"title": r["title"], "type": r["source_type"]} for r in results[:3]],
                    "cost": 0.00,
                }
            else:
                return {
                    "success": True,
                    "response": f"I don't have specific information about that in my knowledge base. Would you like me to search online or ask Claude for help?",
                    "agent_used": "Consciousness",
                    "station": "Consciousness",
                    "escalation_available": True,
                    "cost": 0.00,
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "response": f"I had trouble searching my knowledge base: {str(e)}",
            }

    async def _handle_workflow(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle multi-step workflow requests via Goose"""
        raw_input = intent.get("raw_input", "")

        # Parse workflow steps (simplified - would use LLM in production)
        response = f"""I can help set up that workflow! Here's what I understand:

**Requested Workflow**: {raw_input}

To proceed, I'll need to:
1. Break this down into individual steps
2. Assign each step to the appropriate team member
3. Set up the automation

Would you like me to create this workflow? I'll keep you updated on each step."""

        return {
            "success": True,
            "response": response,
            "agent_used": "ARCHIE (Workflow)",
            "station": "Command",
            "workflow_ready": True,
            "cost": 0.00,
        }

    async def _handle_file_operation(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle file read/write operations"""
        raw_input = intent.get("raw_input", "")
        file_path = intent.get("entities", {}).get("file_path")

        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                # Truncate if too long
                if len(content) > 5000:
                    content = content[:5000] + f"\n\n... (truncated, {len(content)} total characters)"

                return {
                    "success": True,
                    "response": f"Here's the content of `{file_path}`:\n\n```\n{content}\n```",
                    "agent_used": "ARCHIE (Files)",
                    "file_path": file_path,
                    "cost": 0.00,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "response": f"I couldn't read that file: {str(e)}",
                }
        else:
            return {
                "success": True,
                "response": "I'd be happy to help with file operations. Could you provide the file path?",
                "agent_used": "ARCHIE (Files)",
                "cost": 0.00,
            }

    async def _handle_creative_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle creative tasks (images, content)"""
        raw_input = intent.get("raw_input", "")

        # For image generation, would integrate with Fooocus/Media Studio
        return {
            "success": True,
            "response": f"I can help with that creative task! For image generation, I'll use our Media Studio with Fooocus.\n\nDescribe what you'd like to create, and I'll generate it for you.",
            "agent_used": "Creative Station",
            "station": "Creative",
            "cost": 0.00,
        }

    async def _handle_system_status(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle system status checks with REAL hardware specs"""
        try:
            import platform
            import socket
            import subprocess

            # Get real hardware specs
            try:
                import psutil

                cpu_count = psutil.cpu_count(logical=True)
                cpu_physical = psutil.cpu_count(logical=False)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                cpu_percent = psutil.cpu_percent(interval=0.5)

                ram_total = memory.total // (1024**3)
                ram_used = memory.used // (1024**3)
                ram_percent = memory.percent
                disk_total = disk.total // (1024**3)
                disk_used = disk.used // (1024**3)
                disk_percent = disk.percent
            except ImportError:
                # Fallback if psutil not available
                cpu_count = os.cpu_count() or "Unknown"
                cpu_physical = "Unknown"
                ram_total = ram_used = ram_percent = "N/A"
                disk_total = disk_used = disk_percent = "N/A"
                cpu_percent = "N/A"

            # Get CPU model
            cpu_model = "Unknown CPU"
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            cpu_model = line.split(":")[1].strip()
                            break
            except:
                cpu_model = platform.processor() or "Unknown CPU"

            # Check for GPU
            gpu_info = "None detected"
            try:
                # Try NVIDIA first
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    gpu_data = result.stdout.strip().split(",")
                    gpu_name = gpu_data[0].strip()
                    gpu_vram = gpu_data[1].strip() if len(gpu_data) > 1 else "Unknown"
                    gpu_info = f"{gpu_name} ({gpu_vram}MB VRAM)"
            except:
                # Check for AMD GPU
                try:
                    result = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
                    for line in result.stdout.split("\n"):
                        if "VGA" in line or "Display" in line:
                            if "AMD" in line or "Radeon" in line:
                                gpu_info = line.split(":")[-1].strip()[:50]
                            elif "Intel" in line:
                                gpu_info = "Intel Integrated Graphics"
                            break
                except:
                    pass

            # Get hostname and IP
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
                if local_ip.startswith("127."):
                    # Get actual IP
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()
            except:
                local_ip = "Unable to determine"

            # Get OS info
            os_info = f"{platform.system()} {platform.release()}"
            try:
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            os_info = line.split("=")[1].strip().strip('"')
                            break
            except:
                pass

            # Check Ollama
            ollama_status = "offline"
            model_count = 0
            try:
                resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_count = len(models)
                    ollama_status = f"online ({model_count} models)"
            except:
                pass

            # Check database
            db_status = "online"
            try:
                conn = self.get_db()
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                conn.close()
            except:
                db_status = "offline"

            # Check remote nodes
            node_count = 0
            online_nodes = 0
            try:
                conn = self.get_db()
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'online') FROM remote_nodes WHERE is_active = true"
                )
                result = cur.fetchone()
                node_count = result[0] or 0
                online_nodes = result[1] or 0
                cur.close()
                conn.close()
            except:
                pass

            response = f"""**A.R.C.H.I.E. System Status**

**Hardware:**
- **CPU**: {cpu_model}
- **Cores**: {cpu_physical} physical / {cpu_count} logical ({cpu_percent}% usage)
- **RAM**: {ram_used}GB / {ram_total}GB ({ram_percent}% used)
- **Disk**: {disk_used}GB / {disk_total}GB ({disk_percent}% used)
- **GPU**: {gpu_info}

**Network:**
- **Hostname**: {hostname}
- **IP Address**: {local_ip}
- **OS**: {os_info}

**Services:**
- **Ollama LLM Server**: {ollama_status}
- **Database**: {db_status}
- **Remote Nodes**: {online_nodes}/{node_count} online
- **Platform**: online

All systems operational!"""

            return {
                "success": True,
                "response": response,
                "agent_used": "ARCHIE (Status)",
                "station": "Command",
                "cost": 0.00,
                "hardware": {
                    "cpu": cpu_model,
                    "cpu_cores": cpu_count,
                    "ram_gb": ram_total,
                    "disk_gb": disk_total,
                    "gpu": gpu_info,
                    "hostname": hostname,
                    "ip": local_ip,
                },
            }

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": f"I had trouble checking system status: {str(e)}",
            }

    async def _handle_contractor_request(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle explicit contractor (Claude) escalation request"""
        return await self._request_contractor_escalation(
            intent,
            context,
            user_id,
            reason="User explicitly requested Claude/contractor assistance",
        )

    async def _handle_conversation(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle general conversation"""
        raw_input = intent.get("raw_input", "")

        # Build conversational response
        system_prompt = """You are A.R.C.H.I.E. (Adaptive Responsive Cognitive Helper & Intelligent Executor),
a warm, supportive AI assistant and business partner.

Key traits:
- Supportive and caring
- Professional but friendly
- Enthusiastic about helping
- Honest about your capabilities

You're having a natural conversation. Be personable and helpful."""

        response = self._call_ollama(self.model_map["fast"], system_prompt, raw_input)

        return {
            "success": True,
            "response": response.get("content", "I'm here to help! What would you like to work on?"),
            "agent_used": "ARCHIE",
            "station": "Command",
            "cost": 0.00,
            "tokens": response.get("tokens", 0),
        }

    async def _request_contractor_escalation(self, intent: dict, context: dict, user_id: int, reason: str) -> dict:
        """Request contractor (Claude) escalation with approval workflow"""
        raw_input = intent.get("raw_input", "")

        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Find Claude contractor agent
            cur.execute("SELECT id, name FROM agents WHERE model ILIKE '%claude%' AND worker_type = 'contract' LIMIT 1")
            contractor = cur.fetchone()

            if contractor:
                # Create approval request
                cur.execute(
                    """
                    INSERT INTO contractor_approval_requests
                    (agent_id, requested_by, task_type, task_description, estimated_cost, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending')
                    RETURNING id
                """,
                    (
                        contractor["id"],
                        user_id,
                        intent.get("type", "complex_task"),
                        raw_input[:500],
                        0.05,  # Estimated cost
                    ),
                )
                request_id = cur.fetchone()["id"]
                conn.commit()

                response = f"""This task would benefit from Claude's advanced capabilities.

**Reason**: {reason}

I've submitted an escalation request (ID: {request_id}) for admin approval. Once approved, Claude will assist with this task.

In the meantime, would you like me to try handling it with our local models? I might be able to help with parts of it."""

            else:
                response = "I'd like to escalate this to Claude, but I couldn't find the contractor configuration. Please check with the admin."

            cur.close()
            conn.close()

            return {
                "success": True,
                "response": response,
                "agent_used": "ARCHIE",
                "station": "Command",
                "escalation_requested": True,
                "cost": 0.00,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "response": f"I had trouble processing the escalation request: {str(e)}",
            }

    def _call_ollama(self, model: str, system_prompt: str, user_message: str) -> dict:
        """Call Ollama API with detailed error handling"""
        endpoint = f"{self.ollama_url}/api/chat"
        start_time = datetime.now()

        try:
            logger.debug(f"Calling Ollama: model={model}, endpoint={endpoint}")

            response = requests.post(
                endpoint,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "stream": False,
                },
                timeout=120,
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    f"Ollama success: model={model}, tokens={data.get('eval_count', 0)}, duration={duration_ms}ms"
                )
                return {
                    "success": True,
                    "content": data["message"]["content"],
                    "model": model,
                    "tokens": data.get("eval_count", 0),
                    "duration_ms": duration_ms,
                }
            else:
                error_msg = f"Ollama returned {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", error_msg)
                except:
                    pass
                logger.error(f"Ollama error: {error_msg}, model={model}, endpoint={endpoint}")
                return {
                    "success": False,
                    "error": error_msg,
                    "error_type": "api_error",
                    "status_code": response.status_code,
                    "model": model,
                    "endpoint": endpoint,
                    "content": "",
                    "fallback_available": True,
                    "suggested_modules": ["improvements_lab", "blueprint", "sandbox"],
                }

        except requests.exceptions.Timeout:
            logger.error(f"Ollama timeout: model={model}, endpoint={endpoint}")
            return {
                "success": False,
                "error": f"Request timed out after 120s (model: {model})",
                "error_type": "timeout",
                "model": model,
                "endpoint": endpoint,
                "content": "",
                "fallback_available": True,
                "suggested_modules": ["improvements_lab", "blueprint", "sandbox"],
            }

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ollama connection error: {e}, endpoint={endpoint}")
            return {
                "success": False,
                "error": f"Could not connect to Ollama at {self.ollama_url}",
                "error_type": "connection_error",
                "model": model,
                "endpoint": endpoint,
                "content": "",
                "fallback_available": True,
                "suggested_modules": ["improvements_lab", "blueprint", "sandbox"],
            }

        except Exception as e:
            logger.error(f"Ollama unexpected error: {e}, model={model}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "unexpected",
                "model": model,
                "content": "",
                "fallback_available": True,
                "suggested_modules": ["improvements_lab", "blueprint", "sandbox"],
            }

    async def _ask_for_clarification(self, question: str, context: dict) -> str:
        """Generate a clarification question"""
        return question

    # Business task helpers
    async def _handle_invoice_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle invoice creation"""
        return {
            "success": True,
            "response": "I can help create an invoice! Please provide:\n- Client name\n- Amount\n- Description of services\n\nOr I can open the Invoice module for you.",
            "agent_used": "Operations Station",
            "station": "Operations",
            "cost": 0.00,
        }

    async def _handle_email_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle email operations"""
        return {
            "success": True,
            "response": "I can help with emails! Would you like me to:\n- Draft an email\n- Check your inbox\n- Send a follow-up\n\nJust let me know what you need.",
            "agent_used": "Operations Station",
            "station": "Operations",
            "cost": 0.00,
        }

    async def _handle_scheduling_task(self, intent: dict, context: dict, user_id: int) -> dict:
        """Handle scheduling tasks"""
        return {
            "success": True,
            "response": "I can help with scheduling! Tell me:\n- What kind of event/meeting\n- Preferred date and time\n- Who should attend\n\nI'll take care of the rest.",
            "agent_used": "Operations Station",
            "station": "Operations",
            "cost": 0.00,
        }


# Singleton instance
_router = None


def get_command_router() -> CommandRouter:
    """Get singleton CommandRouter instance"""
    global _router
    if _router is None:
        _router = CommandRouter()
    return _router
