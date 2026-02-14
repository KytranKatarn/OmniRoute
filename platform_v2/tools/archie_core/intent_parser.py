"""
A.R.C.H.I.E. Intent Parser
NLP-based intent classification using local Ollama models
Determines what the user wants and how to route their request
"""

import requests
import json
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime


class IntentParser:
    """Parse natural language into structured intents using local Ollama"""

    INTENT_TYPES = [
        "code_task",  # Write/fix/review code
        "team_task",  # Assign agents, manage stations
        "team_management",  # Create/update/delete agents, manage team
        "station_management",  # Assign/unassign agents to stations, check station status
        "status_query",  # Who's on duty, team overview, workload check
        "business_task",  # Invoices, emails, scheduling
        "knowledge_query",  # What do we know about X?
        "workflow",  # Multi-step automated tasks
        "file_operation",  # Read/write/edit files
        "creative_task",  # Generate images, content
        "system_status",  # Health checks, stats
        "contractor_request",  # Explicit Claude escalation
        "conversation",  # General chat, greetings
    ]

    def __init__(self):
        ollama_host = os.getenv("OLLAMA_PRIMARY", "host.docker.internal:11434")
        # Ensure http:// prefix
        self.ollama_url = ollama_host if ollama_host.startswith("http") else f"http://{ollama_host}"
        self.classification_model = "qwen2.5:7b"  # Installed locally, good for classification
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": os.getenv("DB_PASSWORD", ""),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def parse(self, user_input: str, context: dict = None) -> dict:
        """
        Parse user input into structured intent

        Args:
            user_input: Raw user message
            context: Optional context (conversation history, user preferences)

        Returns:
            {
                'type': 'code_task',
                'confidence': 0.95,
                'entities': {'language': 'python', 'action': 'write'},
                'parameters': {...},
                'complexity': {...},
                'requires_contractor': False,
                'raw_input': '...'
            }
        """
        # Step 1: Quick pattern matching for obvious intents
        quick_result = self._quick_classify(user_input)
        if quick_result and quick_result.get("confidence", 0) > 0.9:
            return quick_result

        # Step 2: Assess complexity using database patterns
        complexity = self._assess_complexity(user_input)

        # Step 3: Use LLM for nuanced classification
        llm_result = self._llm_classify(user_input, context)

        # Step 4: Merge results
        result = self._merge_results(quick_result, llm_result, complexity)
        result["raw_input"] = user_input
        result["complexity"] = complexity

        # Step 5: Detect multi-agent requirement (Phase 63)
        multi_agent_config = self._detect_multi_agent_requirement(user_input, result)
        result["requires_multi_agent"] = multi_agent_config["requires_multi_agent"]
        result["participating_stations"] = multi_agent_config["participating_stations"]
        result["discussion_mode"] = multi_agent_config["discussion_mode"]
        result["domains_detected"] = multi_agent_config["domains_detected"]

        return result

    def _quick_classify(self, text: str) -> dict:
        """Quick pattern-based classification for obvious intents"""
        text_lower = text.lower().strip()

        # Greeting patterns
        if re.match(r"^(hi|hello|hey|good morning|good afternoon|good evening|howdy|sup|yo)\b", text_lower):
            return {"type": "conversation", "confidence": 0.95, "entities": {"subtype": "greeting"}}

        # Explicit Claude/contractor request
        if any(word in text_lower for word in ["claude", "need help from claude", "escalate", "contractor"]):
            return {"type": "contractor_request", "confidence": 0.95, "entities": {"explicit": True}}

        # Status checks
        if any(
            phrase in text_lower for phrase in ["system status", "health check", "what's running", "are you online"]
        ):
            return {"type": "system_status", "confidence": 0.9, "entities": {"subtype": "health"}}

        # Self-referential questions (about ARCHIE itself) — treat as conversation
        # Be specific to avoid catching knowledge queries like "what do you know about X"
        if re.search(r"\b(you|your|yourself)\b", text_lower) and any(
            phrase in text_lower
            for phrase in [
                "who are you",
                "what are you",
                "tell me about you",
                "are you assigned",
                "what station are you",
                "what can you do",
                "how are you",
                "how do you feel",
                "what do you do",
                "what do you think",
            ]
        ):
            return {"type": "conversation", "confidence": 0.95, "entities": {"subtype": "self_query"}}

        # Station management — assign/unassign agents to stations (check BEFORE team_management
        # since station phrases like "put agent on X station" also contain "agent" keywords)
        station_management_keywords = [
            "assign to station",
            "assign station",
            "put on station",
            "move to station",
            "station assignment",
            "unassign",
            "engineering station",
            "command station",
            "operations station",
            "security station",
            "creative station",
            "consciousness station",
        ]
        # Also match "put/assign/move ... on/to ... station" patterns
        station_mgmt_patterns = [
            r"\b(put|assign|move|place)\b.*\b(on|to|at)\b.*\bstation\b",
        ]
        if any(phrase in text_lower for phrase in station_management_keywords) or any(
            re.search(p, text_lower) for p in station_mgmt_patterns
        ):
            action = "unassign" if "unassign" in text_lower else "assign"
            station_match = re.search(
                r"(engineering|command|operations|security|creative|consciousness)\s+station",
                text_lower,
            )
            entities = {"action": action}
            if station_match:
                entities["station"] = station_match.group(1)
            return {"type": "station_management", "confidence": 0.9, "entities": entities}

        # Team management — create/update/delete agents
        team_management_keywords = [
            "create agent",
            "new agent",
            "spawn agent",
            "hire",
            "recruit",
            "retire agent",
            "deactivate agent",
            "pause agent",
            "remove agent",
            "update agent",
            "change agent",
            "modify agent",
            "agent capabilities",
            "agent skills",
            "agent model",
            "sub-agent",
            "subagent",
            "team member",
        ]
        # Also match "create/spawn a [new] ... agent" patterns via regex
        team_mgmt_patterns = [
            r"\b(create|spawn|build|add)\b.*\bagent\b",
            r"\bagent\b.*\b(retire|deactivate|pause|remove)\b",
        ]
        if any(phrase in text_lower for phrase in team_management_keywords) or any(
            re.search(p, text_lower) for p in team_mgmt_patterns
        ):
            action = "create"
            if any(w in text_lower for w in ["retire", "deactivate", "pause", "remove"]):
                action = "deactivate"
            elif any(w in text_lower for w in ["update", "change", "modify"]):
                action = "update"
            elif any(w in text_lower for w in ["capabilities", "skills", "model"]):
                action = "query"
            return {"type": "team_management", "confidence": 0.9, "entities": {"action": action}}

        # Status query — who's on duty, team overview, workload
        status_query_keywords = [
            "who's on duty",
            "who is on duty",
            "team status",
            "station status",
            "who is assigned",
            "show team",
            "show roster",
            "how busy",
            "workload",
            "active agents",
            "agent performance",
            "leaderboard",
        ]
        if any(phrase in text_lower for phrase in status_query_keywords):
            subtype = "roster"
            if any(w in text_lower for w in ["performance", "leaderboard"]):
                subtype = "performance"
            elif any(w in text_lower for w in ["busy", "workload"]):
                subtype = "workload"
            elif any(w in text_lower for w in ["station status"]):
                subtype = "station"
            return {"type": "status_query", "confidence": 0.9, "entities": {"subtype": subtype}}

        # Team operations (generic fallback for unmatched team keywords)
        if any(word in text_lower for word in ["assign", "station", "roster", "agent", "team"]):
            if any(action in text_lower for action in ["move", "assign", "put", "switch"]):
                return {"type": "team_task", "confidence": 0.85, "entities": {"action": "assignment"}}
            return {"type": "team_task", "confidence": 0.75, "entities": {"action": "query"}}

        # Code tasks
        code_keywords = ["write", "code", "function", "class", "implement", "fix", "bug", "debug", "refactor"]
        if any(word in text_lower for word in code_keywords):
            # Detect language
            language = None
            for lang in ["python", "javascript", "typescript", "rust", "go", "java", "sql", "html", "css"]:
                if lang in text_lower:
                    language = lang
                    break
            return {"type": "code_task", "confidence": 0.8, "entities": {"language": language}}

        # Business tasks
        if any(word in text_lower for word in ["invoice", "email", "schedule", "meeting", "customer", "payment"]):
            return {"type": "business_task", "confidence": 0.8, "entities": {}}

        # File operations
        if any(word in text_lower for word in ["read file", "open file", "edit file", "create file", "show me"]):
            return {"type": "file_operation", "confidence": 0.85, "entities": {}}

        # Workflow patterns (multi-step)
        if any(
            phrase in text_lower for phrase in ["and then", "after that", "workflow", "pipeline", "review and deploy"]
        ):
            return {"type": "workflow", "confidence": 0.75, "entities": {"multi_step": True}}

        # Creative tasks
        if any(word in text_lower for word in ["generate image", "create picture", "design", "make a logo"]):
            return {"type": "creative_task", "confidence": 0.8, "entities": {"media_type": "image"}}

        # Knowledge queries
        if any(
            phrase in text_lower for phrase in ["what is", "how does", "explain", "tell me about", "what do we know"]
        ):
            return {"type": "knowledge_query", "confidence": 0.75, "entities": {}}

        return None

    def _assess_complexity(self, text: str) -> dict:
        """Assess command complexity using database patterns"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Use the database function
            cur.execute("SELECT * FROM assess_command_complexity(%s::TEXT, NULL::VARCHAR)", (text,))
            result = cur.fetchone()

            cur.close()
            conn.close()

            if result:
                return {
                    "score": result["complexity_score"],
                    "requires_contractor": result["requires_contractor"],
                    "matching_patterns": [],
                    "recommended_action": result.get("suggested_model", "use_fast_local_model"),
                }
        except Exception as e:
            print(f"Complexity assessment error: {e}")

        # Default medium complexity
        return {
            "score": 5,
            "requires_contractor": False,
            "matching_patterns": [],
            "recommended_action": "use_fast_local_model",
        }

    def _llm_classify(self, text: str, context: dict = None) -> dict:
        """Use LLM for nuanced intent classification"""
        prompt = f"""Classify this user request into exactly one category.

User request: "{text}"

Categories:
1. code_task - Writing, fixing, reviewing, or refactoring code
2. team_task - Managing agents, stations, assignments, roster (generic)
3. team_management - Create, update, delete, or configure agents (hire, recruit, retire, deactivate, modify agent capabilities)
4. station_management - Assign or unassign agents to/from stations, station assignments
5. status_query - Who's on duty, team status, station status, workload, agent performance, roster overview
6. business_task - Invoices, emails, scheduling, CRM, store operations
7. knowledge_query - Questions about documentation, how things work
8. workflow - Multi-step automated tasks (review -> test -> deploy)
9. file_operation - Reading, writing, editing specific files
10. creative_task - Generating images, designs, creative content
11. system_status - Health checks, status reports, what's running
12. contractor_request - Explicit request for advanced AI help (Claude)
13. conversation - General chat, greetings, small talk

Respond with ONLY a JSON object in this exact format:
{{"type": "category_name", "confidence": 0.85, "entities": {{"key": "value"}}}}

JSON:"""

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.classification_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=30,
            )

            if response.status_code == 200:
                result_text = response.json().get("response", "").strip()
                # Extract JSON from response
                json_match = re.search(r"\{[^{}]+\}", result_text)
                if json_match:
                    result = json.loads(json_match.group())
                    if result.get("type") in self.INTENT_TYPES:
                        return result
        except Exception as e:
            print(f"LLM classification error: {e}")

        # Fallback
        return {"type": "conversation", "confidence": 0.5, "entities": {}}

    def _merge_results(self, quick: dict, llm: dict, complexity: dict) -> dict:
        """Merge quick, LLM, and complexity results"""
        # Start with LLM result
        result = llm.copy() if llm else {"type": "conversation", "confidence": 0.5, "entities": {}}

        # Override with quick result if higher confidence
        if quick and quick.get("confidence", 0) > result.get("confidence", 0):
            result = quick.copy()

        # Add complexity-based contractor flag
        if complexity.get("requires_contractor"):
            result["requires_contractor"] = True
        elif result.get("type") == "contractor_request":
            result["requires_contractor"] = True
        else:
            result["requires_contractor"] = False

        # Ensure all fields exist
        result.setdefault("confidence", 0.5)
        result.setdefault("entities", {})
        result.setdefault("parameters", {})

        return result

    def extract_entities(self, text: str, intent_type: str) -> dict:
        """Extract relevant entities based on intent type"""
        entities = {}

        if intent_type == "code_task":
            # Extract language
            for lang in ["python", "javascript", "typescript", "rust", "go", "java", "sql"]:
                if lang in text.lower():
                    entities["language"] = lang
                    break

            # Extract action
            if "fix" in text.lower() or "bug" in text.lower():
                entities["action"] = "fix"
            elif "refactor" in text.lower():
                entities["action"] = "refactor"
            elif "review" in text.lower():
                entities["action"] = "review"
            else:
                entities["action"] = "write"

        elif intent_type == "team_task":
            # Try to extract agent name
            name_match = re.search(r"(?:assign|move)\s+(\w+)", text, re.IGNORECASE)
            if name_match:
                entities["agent_name"] = name_match.group(1)

            # Try to extract station
            station_match = re.search(r"(?:to|at)\s+(\w+)\s+station", text, re.IGNORECASE)
            if station_match:
                entities["station"] = station_match.group(1)

        elif intent_type == "team_management":
            # Extract agent name
            name_match = re.search(
                r"(?:create|spawn|hire|recruit|retire|deactivate|pause|remove|update|change|modify)\s+(?:agent\s+)?(\w+)",
                text,
                re.IGNORECASE,
            )
            if name_match:
                entities["agent_name"] = name_match.group(1)

            # Extract action
            if any(w in text.lower() for w in ["create", "new", "spawn", "hire", "recruit"]):
                entities["action"] = "create"
            elif any(w in text.lower() for w in ["retire", "deactivate", "pause", "remove"]):
                entities["action"] = "deactivate"
            elif any(w in text.lower() for w in ["update", "change", "modify"]):
                entities["action"] = "update"

        elif intent_type == "station_management":
            # Extract agent name
            name_match = re.search(r"(?:assign|move|put)\s+(\w+)", text, re.IGNORECASE)
            if name_match:
                entities["agent_name"] = name_match.group(1)

            # Extract station
            station_match = re.search(
                r"(engineering|command|operations|security|creative|consciousness)\s+station",
                text,
                re.IGNORECASE,
            )
            if station_match:
                entities["station"] = station_match.group(1).lower()

            # Extract action
            if "unassign" in text.lower():
                entities["action"] = "unassign"
            else:
                entities["action"] = "assign"

        elif intent_type == "status_query":
            # Extract what kind of status query
            text_lower = text.lower()
            if any(w in text_lower for w in ["performance", "leaderboard"]):
                entities["subtype"] = "performance"
            elif any(w in text_lower for w in ["busy", "workload"]):
                entities["subtype"] = "workload"
            elif "station" in text_lower:
                entities["subtype"] = "station"
            else:
                entities["subtype"] = "roster"

        elif intent_type == "file_operation":
            # Extract file path
            path_match = re.search(r"[/\\][\w./\\-]+\.\w+", text)
            if path_match:
                entities["file_path"] = path_match.group()

        return entities

    def _detect_multi_agent_requirement(self, text: str, intent: dict) -> dict:
        """
        Detect if task requires multi-agent collaboration

        Args:
            text: User input
            intent: Parsed intent dict

        Returns:
            Multi-agent configuration dict
        """
        text_lower = text.lower()

        # Patterns suggesting multi-agent discussion
        multi_agent_patterns = [
            r"review.*(code|design|architecture|plan)",
            r"(design|build|implement).*with.*(security|performance|testing)",
            r"(complex|comprehensive|full-stack|end-to-end)",
            r"multiple\s+(teams?|agents?|perspectives?|experts?)",
            r"(collaborate|discussion|consensus|debate)",
            r"get.*opinions?\s+from",
            r"what\s+does\s+everyone\s+think",
            r"team\s+(review|discussion|meeting)",
            r"cross-?(functional|team|department)",
        ]

        # Domain combinations that benefit from multi-agent discussion
        domain_keywords = {
            "security": ["security", "auth", "permission", "encrypt", "vulnerability", "attack", "protect"],
            "performance": ["performance", "optimize", "speed", "latency", "cache", "scale"],
            "architecture": ["architecture", "design pattern", "structure", "system design", "microservice"],
            "code": ["code", "implement", "function", "class", "api", "endpoint", "backend", "frontend"],
            "testing": ["test", "qa", "quality", "coverage", "regression", "integration"],
            "operations": ["deploy", "infrastructure", "devops", "monitor", "logging", "ci/cd"],
            "business": ["business", "revenue", "customer", "market", "product", "requirements"],
            "creative": ["design", "ui", "ux", "visual", "brand", "creative"],
        }

        # Detect domains mentioned
        domains_found = []
        for domain, keywords in domain_keywords.items():
            if any(kw in text_lower for kw in keywords):
                domains_found.append(domain)

        # Check for explicit multi-agent patterns
        requires_multi = False
        matching_patterns = []

        for pattern in multi_agent_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                requires_multi = True
                matching_patterns.append(pattern)

        # High complexity also suggests multi-agent
        complexity_score = intent.get("complexity", {}).get("score", 5)
        if complexity_score >= 7:
            requires_multi = True

        # Multiple domains suggest multi-agent discussion
        if len(domains_found) >= 2:
            requires_multi = True

        # Map domains to Bridge stations
        domain_to_station = {
            "security": "SECURITY",
            "performance": "ENGINEERING",
            "architecture": "ENGINEERING",
            "code": "ENGINEERING",
            "testing": "QA",
            "operations": "OPERATIONS",
            "business": "OPERATIONS",
            "creative": "CREATIVE",
        }

        participating_stations = list(set(domain_to_station.get(d, "ENGINEERING") for d in domains_found))

        # Ensure at least 2 stations for multi-agent
        if requires_multi and len(participating_stations) < 2:
            # Add complementary stations
            if "ENGINEERING" in participating_stations:
                participating_stations.append("QA")
            elif "SECURITY" in participating_stations:
                participating_stations.append("ENGINEERING")
            else:
                participating_stations.append("ENGINEERING")

        return {
            "requires_multi_agent": requires_multi,
            "participating_stations": participating_stations[:4],  # Max 4 stations
            "domains_detected": domains_found,
            "matching_patterns": matching_patterns,
            "discussion_mode": "collaborative" if requires_multi else "single",
        }


# Singleton instance
_parser = None


def get_intent_parser() -> IntentParser:
    """Get singleton IntentParser instance"""
    global _parser
    if _parser is None:
        _parser = IntentParser()
    return _parser
