"""
Planner Agent - Technical Plan Generation
Creates detailed implementation plans from requirements

Purpose:
- Analyze user requirements and clarifications
- Choose appropriate tech stack
- Design file structure and architecture
- Define database schema
- Create implementation roadmap
- Estimate complexity and timeline

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

from typing import Dict, List, Any
import json
import re

from tools.department_hq.services.department_dispatcher import dispatch_json

AI_AVAILABLE = True


# ============================================================================
# TECH STACK TEMPLATES
# ============================================================================

TECH_STACKS = {
    "python_web": {
        "name": "Python Web Stack",
        "backend": "Flask",
        "frontend": "React",
        "database": "PostgreSQL",
        "description": "Modern Python web application with React frontend",
        "dependencies": {
            "python": [
                "flask",
                "flask-cors",
                "flask-login",
                "psycopg2-binary",
                "python-dotenv",
                "werkzeug",
            ],
            "javascript": ["react", "react-dom", "axios", "react-router-dom"],
        },
        "files": [
            "app.py",
            "config.py",
            "models.py",
            "routes.py",
            "database.py",
            "frontend/src/App.js",
            "frontend/src/index.js",
            "frontend/package.json",
            "requirements.txt",
            ".env.example",
            "README.md",
        ],
    },
    "python_api": {
        "name": "Python API Stack",
        "backend": "FastAPI",
        "database": "PostgreSQL",
        "description": "High-performance REST API with FastAPI",
        "dependencies": {
            "python": [
                "fastapi",
                "uvicorn",
                "sqlalchemy",
                "psycopg2-binary",
                "pydantic",
                "python-jose",
                "passlib",
            ]
        },
        "files": [
            "main.py",
            "models.py",
            "schemas.py",
            "database.py",
            "crud.py",
            "auth.py",
            "requirements.txt",
            ".env.example",
            "README.md",
            "Dockerfile",
        ],
    },
    "node_web": {
        "name": "Node.js Web Stack",
        "backend": "Express.js",
        "frontend": "React",
        "database": "PostgreSQL",
        "description": "Full-stack JavaScript application",
        "dependencies": {
            "javascript": [
                "express",
                "react",
                "react-dom",
                "pg",
                "bcryptjs",
                "jsonwebtoken",
                "cors",
                "dotenv",
            ]
        },
        "files": [
            "server/index.js",
            "server/routes.js",
            "server/models.js",
            "server/auth.js",
            "client/src/App.js",
            "client/src/index.js",
            "client/package.json",
            "package.json",
            ".env.example",
            "README.md",
        ],
    },
    "python_cli": {
        "name": "Python CLI Stack",
        "backend": "Python",
        "database": "SQLite",
        "description": "Command-line tool with Python",
        "dependencies": {"python": ["click", "rich", "sqlalchemy", "pydantic"]},
        "files": [
            "cli.py",
            "commands.py",
            "database.py",
            "models.py",
            "requirements.txt",
            "README.md",
            "setup.py",
        ],
    },
}


# ============================================================================
# DATABASE SCHEMA TEMPLATES
# ============================================================================


def generate_users_table(has_auth: bool) -> Dict:
    """Generate users table schema if authentication needed"""
    if not has_auth:
        return None

    return {
        "table_name": "users",
        "columns": [
            {"name": "id", "type": "SERIAL PRIMARY KEY"},
            {"name": "username", "type": "VARCHAR(100) UNIQUE NOT NULL"},
            {"name": "email", "type": "VARCHAR(255) UNIQUE NOT NULL"},
            {"name": "password_hash", "type": "VARCHAR(255) NOT NULL"},
            {"name": "created_at", "type": "TIMESTAMP DEFAULT NOW()"},
            {"name": "is_active", "type": "BOOLEAN DEFAULT TRUE"},
        ],
        "indexes": ["username", "email"],
    }


# ============================================================================
# PLANNER AGENT
# ============================================================================


class PlannerAgent:
    """
    Intelligent planning agent that creates detailed technical plans
    Analyzes requirements and generates implementation roadmap
    """

    def __init__(self, project_id: int, clarifications: Dict[str, Any]):
        self.project_id = project_id
        self.clarifications = clarifications

    async def generate_plan(self, user_prompt: str, clarifications: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate comprehensive technical plan

        Args:
            user_prompt: Original user request
            clarifications: Answers to clarification questions

        Returns:
            Complete project plan dictionary
        """
        # 1. Choose tech stack
        tech_stack = self._choose_tech_stack(user_prompt, clarifications)

        # 2. Design database schema
        database_schema = await self._design_database_schema(user_prompt, clarifications, tech_stack)

        # 3. Define API endpoints (if applicable)
        api_endpoints = await self._define_api_endpoints(user_prompt, clarifications, database_schema)

        # 4. Plan file structure
        file_structure = self._plan_file_structure(tech_stack, database_schema, api_endpoints)

        # 5. Identify components
        components = await self._identify_components(user_prompt, clarifications, tech_stack)

        # 6. Create implementation steps
        implementation_steps = self._create_implementation_steps(tech_stack, database_schema, api_endpoints, components)

        # 7. Estimate complexity
        complexity = self._estimate_complexity(database_schema, api_endpoints, components)

        # 8. Generate detailed plan using AI
        if AI_AVAILABLE:
            ai_enhancements = await self._enhance_plan_with_ai(
                user_prompt, clarifications, tech_stack, database_schema, api_endpoints
            )
        else:
            ai_enhancements = {}

        # Compile full plan
        plan = {
            "project_name": clarifications.get("app_type", "Application"),
            "description": user_prompt,
            "tech_stack": tech_stack,
            "database_schema": database_schema,
            "api_endpoints": api_endpoints,
            "file_structure": file_structure,
            "components": components,
            "implementation_steps": implementation_steps,
            "complexity": complexity,
            "estimated_files": len(file_structure["files"]),
            "estimated_lines": self._estimate_lines(complexity, len(file_structure["files"])),
            "recommended_timeline": self._estimate_timeline(complexity),
            "ai_recommendations": ai_enhancements.get("recommendations", []),
            "security_considerations": self._generate_security_considerations(tech_stack, clarifications),
            "deployment_strategy": self._plan_deployment(clarifications.get("deployment", "Cloud")),
        }

        return plan

    def _choose_tech_stack(self, user_prompt: str, clarifications: Dict) -> Dict[str, Any]:
        """
        Choose appropriate tech stack based on requirements

        Args:
            user_prompt: Original request
            clarifications: User answers

        Returns:
            Tech stack configuration
        """
        app_type = clarifications.get("app_type", "Web Application")
        tech_prefs = clarifications.get("tech_preferences", [])

        # User has explicit preferences
        if tech_prefs and tech_prefs != ["No preference (let A.R.C.H.I.E. decide)"]:
            # Parse preferences
            has_python = any("Python" in pref for pref in tech_prefs)
            has_node = any("Node" in pref or "JavaScript" in pref for pref in tech_prefs)
            any("React" in pref for pref in tech_prefs)
            has_vue = any("Vue" in pref for pref in tech_prefs)

            if has_python:
                stack = TECH_STACKS["python_web"].copy()
                if has_vue:
                    stack["frontend"] = "Vue.js"
            elif has_node:
                stack = TECH_STACKS["node_web"].copy()
            else:
                stack = TECH_STACKS["python_web"].copy()
        else:
            # Choose based on app type
            if "CLI" in app_type or "command line" in app_type.lower():
                stack = TECH_STACKS["python_cli"].copy()
            elif "API" in app_type or "backend" in app_type.lower():
                stack = TECH_STACKS["python_api"].copy()
            else:
                # Default to Python web stack (most versatile)
                stack = TECH_STACKS["python_web"].copy()

        return stack

    async def _design_database_schema(self, user_prompt: str, clarifications: Dict, tech_stack: Dict) -> Dict[str, Any]:
        """
        Design database schema based on requirements

        Args:
            user_prompt: Original request
            clarifications: User answers
            tech_stack: Chosen tech stack

        Returns:
            Database schema definition
        """
        schema = {
            "database_type": tech_stack.get("database", "PostgreSQL"),
            "tables": [],
        }

        # Add users table if authentication needed
        has_auth = clarifications.get("authentication", "No") != "No"
        if has_auth:
            users_table = generate_users_table(has_auth)
            if users_table:
                schema["tables"].append(users_table)

        # Parse database requirements from clarifications
        database_info = clarifications.get("database", "")

        # Use AI to design schema from requirements
        if AI_AVAILABLE and database_info:
            ai_schema = await self._ai_design_schema(user_prompt, database_info, has_auth)
            if ai_schema:
                schema["tables"].extend(ai_schema)

        # If no tables designed yet, create basic table
        if len(schema["tables"]) == 0:
            # Default table based on app type
            schema["tables"].append(
                {
                    "table_name": "items",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {"name": "name", "type": "VARCHAR(255) NOT NULL"},
                        {"name": "description", "type": "TEXT"},
                        {"name": "created_at", "type": "TIMESTAMP DEFAULT NOW()"},
                    ],
                }
            )

        return schema

    async def _ai_design_schema(self, user_prompt: str, database_info: str, has_auth: bool) -> List[Dict]:
        """Use AI to design database schema from natural language"""
        try:
            ai_prompt = f"""Design a PostgreSQL database schema for this application:

Application Description: {user_prompt}

Data Requirements: {database_info}

Authentication: {'Yes - users table already designed' if has_auth else 'No'}

Generate a JSON schema for additional tables needed (excluding users table if auth is enabled).

Format as JSON array:
[
    {{
        "table_name": "table_name",
        "columns": [
            {{"name": "id", "type": "SERIAL PRIMARY KEY"}},
            {{"name": "column_name", "type": "VARCHAR(100)"}}
        ],
        "indexes": ["column_name"],
        "foreign_keys": [
            {{"column": "user_id", "references": "users(id)"}}
        ]
    }}
]

Keep it simple and normalized. Include appropriate indexes and foreign keys."""

            result = dispatch_json(capability="research", prompt=ai_prompt, module_id="app_builder")

            if result.get("success") and result.get("response"):
                # Extract JSON from response
                response = result["response"]
                json_match = re.search(r"\[.*\]", response, re.DOTALL)
                if json_match:
                    tables = json.loads(json_match.group(0))
                    return tables

        except Exception as e:
            print(f"[PlannerAgent] AI schema design failed: {e}")

        return []

    async def _define_api_endpoints(self, user_prompt: str, clarifications: Dict, database_schema: Dict) -> List[Dict]:
        """
        Define API endpoints based on schema and requirements

        Args:
            user_prompt: Original request
            clarifications: User answers
            database_schema: Database design

        Returns:
            List of API endpoint definitions
        """
        endpoints = []

        # Add auth endpoints if needed
        has_auth = clarifications.get("authentication", "No") != "No"
        if has_auth:
            endpoints.extend(
                [
                    {
                        "method": "POST",
                        "path": "/api/auth/signup",
                        "description": "User registration",
                        "request_body": {
                            "username": "string",
                            "email": "string",
                            "password": "string",
                        },
                        "response": {
                            "success": "boolean",
                            "user_id": "integer",
                            "token": "string",
                        },
                    },
                    {
                        "method": "POST",
                        "path": "/api/auth/login",
                        "description": "User login",
                        "request_body": {"username": "string", "password": "string"},
                        "response": {"success": "boolean", "token": "string"},
                    },
                    {
                        "method": "POST",
                        "path": "/api/auth/logout",
                        "description": "User logout",
                        "requires_auth": True,
                    },
                ]
            )

        # Generate CRUD endpoints for each table (except users)
        for table in database_schema.get("tables", []):
            if table["table_name"] != "users":
                table_name = table["table_name"]
                singular = table_name.rstrip("s")  # Simple pluralization

                endpoints.extend(
                    [
                        {
                            "method": "GET",
                            "path": f"/api/{table_name}",
                            "description": f"List all {table_name}",
                            "requires_auth": has_auth,
                            "response": {"success": "boolean", "data": "array"},
                        },
                        {
                            "method": "GET",
                            "path": f"/api/{table_name}/{{id}}",
                            "description": f"Get single {singular}",
                            "requires_auth": has_auth,
                            "response": {"success": "boolean", "data": "object"},
                        },
                        {
                            "method": "POST",
                            "path": f"/api/{table_name}",
                            "description": f"Create new {singular}",
                            "requires_auth": has_auth,
                            "request_body": {
                                col["name"]: col["type"] for col in table["columns"] if col["name"] != "id"
                            },
                        },
                        {
                            "method": "PUT",
                            "path": f"/api/{table_name}/{{id}}",
                            "description": f"Update {singular}",
                            "requires_auth": has_auth,
                        },
                        {
                            "method": "DELETE",
                            "path": f"/api/{table_name}/{{id}}",
                            "description": f"Delete {singular}",
                            "requires_auth": has_auth,
                        },
                    ]
                )

        return endpoints

    def _plan_file_structure(self, tech_stack: Dict, database_schema: Dict, api_endpoints: List[Dict]) -> Dict:
        """
        Plan complete file structure

        Args:
            tech_stack: Chosen stack
            database_schema: Database design
            api_endpoints: API endpoints

        Returns:
            File structure definition
        """
        base_files = tech_stack.get("files", [])

        structure = {"root": "/", "files": base_files, "directories": []}

        # Add directories based on backend framework
        backend = tech_stack.get("backend", "Flask")

        if backend == "Flask":
            structure["directories"] = [
                "static",
                "templates",
                "models",
                "routes",
                "utils",
            ]
        elif backend == "FastAPI":
            structure["directories"] = ["api", "models", "schemas", "services", "utils"]
        elif backend == "Express.js":
            structure["directories"] = [
                "server",
                "client",
                "server/routes",
                "server/models",
                "server/middleware",
            ]

        # Add frontend directories if applicable
        if tech_stack.get("frontend"):
            structure["directories"].extend(
                [
                    "frontend",
                    "frontend/src",
                    "frontend/src/components",
                    "frontend/src/pages",
                    "frontend/src/utils",
                ]
            )

        # Add test directory
        structure["directories"].append("tests")

        # Add config files
        structure["files"].extend([".gitignore", "docker-compose.yml", "Dockerfile"])

        return structure

    async def _identify_components(self, user_prompt: str, clarifications: Dict, tech_stack: Dict) -> List[Dict]:
        """
        Identify frontend/backend components needed

        Args:
            user_prompt: Original request
            clarifications: User answers
            tech_stack: Tech stack

        Returns:
            List of components to build
        """
        components = []

        # Backend components (always needed)
        components.extend(
            [
                {
                    "name": "App",
                    "type": "backend",
                    "file": "app.py",
                    "description": "Main application",
                },
                {
                    "name": "Database",
                    "type": "backend",
                    "file": "database.py",
                    "description": "Database connection",
                },
                {
                    "name": "Models",
                    "type": "backend",
                    "file": "models.py",
                    "description": "Data models",
                },
                {
                    "name": "Routes",
                    "type": "backend",
                    "file": "routes.py",
                    "description": "API routes",
                },
            ]
        )

        # Auth components if needed
        has_auth = clarifications.get("authentication", "No") != "No"
        if has_auth:
            components.append(
                {
                    "name": "Auth",
                    "type": "backend",
                    "file": "auth.py",
                    "description": "Authentication logic",
                }
            )

        # Frontend components if applicable
        if tech_stack.get("frontend"):
            components.extend(
                [
                    {
                        "name": "App",
                        "type": "frontend",
                        "file": "App.js",
                        "description": "Root component",
                    },
                    {
                        "name": "Home",
                        "type": "frontend",
                        "file": "pages/Home.js",
                        "description": "Home page",
                    },
                ]
            )

            if has_auth:
                components.extend(
                    [
                        {
                            "name": "Login",
                            "type": "frontend",
                            "file": "pages/Login.js",
                            "description": "Login page",
                        },
                        {
                            "name": "Signup",
                            "type": "frontend",
                            "file": "pages/Signup.js",
                            "description": "Signup page",
                        },
                    ]
                )

        return components

    def _create_implementation_steps(
        self,
        tech_stack: Dict,
        database_schema: Dict,
        api_endpoints: List[Dict],
        components: List[Dict],
    ) -> List[Dict]:
        """
        Create ordered implementation steps

        Args:
            tech_stack: Tech stack
            database_schema: Database design
            api_endpoints: API endpoints
            components: Components

        Returns:
            Ordered list of implementation steps
        """
        steps = [
            {
                "step": 1,
                "name": "Initialize Project",
                "description": "Set up project structure and install dependencies",
                "tasks": [
                    "Create directory structure",
                    "Initialize Git repository",
                    "Create requirements.txt / package.json",
                    "Set up virtual environment",
                    "Create configuration files",
                ],
            },
            {
                "step": 2,
                "name": "Database Setup",
                "description": "Create database schema and models",
                "tasks": [
                    "Design database schema",
                    "Create migration files",
                    "Implement data models",
                    "Set up database connection",
                    "Create seed data (optional)",
                ],
            },
            {
                "step": 3,
                "name": "Backend Implementation",
                "description": "Build backend API and business logic",
                "tasks": [
                    "Create Flask/FastAPI app",
                    "Implement API routes",
                    "Add authentication middleware",
                    "Implement CRUD operations",
                    "Add error handling",
                ],
            },
            {
                "step": 4,
                "name": "Frontend Implementation",
                "description": "Build user interface",
                "tasks": [
                    "Set up React/Vue project",
                    "Create component structure",
                    "Implement pages",
                    "Connect to backend API",
                    "Add styling",
                ],
            },
            {
                "step": 5,
                "name": "Testing",
                "description": "Write and run tests",
                "tasks": [
                    "Write unit tests",
                    "Write integration tests",
                    "Test API endpoints",
                    "Test frontend components",
                    "Fix bugs",
                ],
            },
            {
                "step": 6,
                "name": "Deployment",
                "description": "Deploy application",
                "tasks": [
                    "Create Docker containers",
                    "Set up environment variables",
                    "Configure production database",
                    "Deploy to cloud platform",
                    "Set up monitoring",
                ],
            },
        ]

        return steps

    def _estimate_complexity(self, database_schema: Dict, api_endpoints: List[Dict], components: List[Dict]) -> Dict:
        """
        Estimate project complexity

        Returns:
            Complexity metrics
        """
        table_count = len(database_schema.get("tables", []))
        endpoint_count = len(api_endpoints)
        component_count = len(components)

        # Calculate complexity score
        score = 0
        score += table_count * 10
        score += endpoint_count * 5
        score += component_count * 8

        if score < 100:
            level = "low"
            description = "Simple application with basic features"
        elif score < 300:
            level = "medium"
            description = "Moderate complexity with multiple features"
        else:
            level = "high"
            description = "Complex application with many features"

        return {
            "level": level,
            "score": score,
            "description": description,
            "metrics": {
                "tables": table_count,
                "endpoints": endpoint_count,
                "components": component_count,
            },
        }

    def _estimate_lines(self, complexity: Dict, file_count: int) -> int:
        """Estimate total lines of code"""
        base_lines = file_count * 50  # Average 50 lines per file

        if complexity["level"] == "low":
            return base_lines * 2
        elif complexity["level"] == "medium":
            return base_lines * 4
        else:
            return base_lines * 6

    def _estimate_timeline(self, complexity: Dict) -> Dict:
        """Estimate development timeline"""
        level = complexity["level"]

        if level == "low":
            return {
                "generation_time": "5-10 minutes",
                "testing_time": "2-5 minutes",
                "total_time": "7-15 minutes",
                "human_equivalent": "2-4 hours",
            }
        elif level == "medium":
            return {
                "generation_time": "10-20 minutes",
                "testing_time": "5-10 minutes",
                "total_time": "15-30 minutes",
                "human_equivalent": "8-16 hours",
            }
        else:
            return {
                "generation_time": "20-40 minutes",
                "testing_time": "10-20 minutes",
                "total_time": "30-60 minutes",
                "human_equivalent": "24-48 hours",
            }

    def _generate_security_considerations(self, tech_stack: Dict, clarifications: Dict) -> List[str]:
        """Generate security recommendations"""
        considerations = [
            "Use environment variables for sensitive configuration",
            "Implement HTTPS/TLS in production",
            "Validate and sanitize all user input",
            "Use parameterized queries to prevent SQL injection",
        ]

        has_auth = clarifications.get("authentication", "No") != "No"
        if has_auth:
            considerations.extend(
                [
                    "Hash passwords with bcrypt or similar",
                    "Implement JWT tokens with expiration",
                    "Add rate limiting to prevent brute force attacks",
                    "Implement CORS properly for API security",
                ]
            )

        return considerations

    def _plan_deployment(self, deployment_preference: str) -> Dict:
        """Plan deployment strategy"""
        if "Cloud" in deployment_preference or "Vercel" in deployment_preference:
            return {
                "platform": "Vercel/Railway",
                "method": "Git-based deployment",
                "steps": [
                    "Connect GitHub repository",
                    "Configure environment variables",
                    "Deploy with automatic builds",
                    "Set up custom domain (optional)",
                ],
            }
        elif "Docker" in deployment_preference:
            return {
                "platform": "Docker",
                "method": "Container deployment",
                "steps": [
                    "Build Docker image",
                    "Push to container registry",
                    "Deploy to Docker host",
                    "Set up reverse proxy",
                ],
            }
        else:
            return {
                "platform": "Cloud (Recommended)",
                "method": "Automatic deployment",
                "steps": [
                    "Choose cloud platform",
                    "Connect repository",
                    "Configure settings",
                    "Deploy",
                ],
            }

    async def _enhance_plan_with_ai(
        self,
        user_prompt: str,
        clarifications: Dict,
        tech_stack: Dict,
        database_schema: Dict,
        api_endpoints: List[Dict],
    ) -> Dict:
        """Use AI to enhance and validate the plan"""
        try:
            ai_prompt = f"""Review and enhance this application plan:

User Request: {user_prompt}

Clarifications: {json.dumps(clarifications, indent=2)}

Proposed Tech Stack: {tech_stack['name']}

Database Tables: {len(database_schema.get('tables', []))}

API Endpoints: {len(api_endpoints)}

Provide:
1. Additional recommendations (3-5 suggestions)
2. Potential issues or challenges
3. Best practices to follow

Format as JSON:
{{
    "recommendations": ["recommendation 1", "recommendation 2", ...],
    "challenges": ["challenge 1", "challenge 2", ...],
    "best_practices": ["practice 1", "practice 2", ...]
}}"""

            result = dispatch_json(capability="research", prompt=ai_prompt, module_id="app_builder")

            if result.get("success") and result.get("response"):
                response = result["response"]
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))

        except Exception as e:
            print(f"[PlannerAgent] AI enhancement failed: {e}")

        return {"recommendations": [], "challenges": [], "best_practices": []}

    async def save_to_database(self, plan: Dict):
        """Save generated plan to database"""
        try:
            from app import get_db

            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                UPDATE app_builder_projects
                SET project_plan = %s,
                    tech_stack = %s,
                    dependencies = %s,
                    status = 'plan_approval',
                    updated_at = NOW()
                WHERE id = %s
            """,
                (
                    json.dumps(plan),
                    json.dumps(plan["tech_stack"]),
                    json.dumps(plan["tech_stack"].get("dependencies", {})),
                    self.project_id,
                ),
            )

            # Add to chat history
            cur.execute(
                """
                INSERT INTO app_builder_chat_history
                (project_id, user_id, role, message, message_type, step, agent, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    self.project_id,
                    1,  # System user
                    "assistant",
                    f"Generated technical plan with {plan['estimated_files']} files and {len(plan['implementation_steps'])} implementation steps.",
                    "plan",
                    "planning",
                    "planner_agent",
                    json.dumps({"complexity": plan["complexity"]["level"]}),
                ),
            )

            conn.commit()

        except Exception as e:
            print(f"[PlannerAgent] Failed to save plan: {e}")
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("PLANNER AGENT TEST")
    print("=" * 80)

    # Test plan generation
    clarifications = {
        "app_type": "Web Application",
        "core_features": "User authentication, task management, due dates",
        "target_users": "General public",
        "authentication": "Yes, with login/signup",
        "database": "User accounts, tasks with title, description, due date, priority",
        "tech_preferences": ["No preference (let A.R.C.H.I.E. decide)"],
        "deployment": "Cloud (Vercel, Railway, etc.) - Recommended",
    }

    agent = PlannerAgent(project_id=1, clarifications=clarifications)

    # Test tech stack selection
    tech_stack = agent._choose_tech_stack("Build a todo app", clarifications)
    print(f"\n✅ Tech Stack: {tech_stack['name']}")
    print(f"   Backend: {tech_stack['backend']}")
    print(f"   Frontend: {tech_stack['frontend']}")
    print(f"   Database: {tech_stack['database']}")

    # Test complexity estimation
    mock_schema = {"tables": [{"table_name": "users"}, {"table_name": "tasks"}]}
    mock_endpoints = [{"path": "/api/auth/login"}, {"path": "/api/tasks"}]
    mock_components = [{"name": "App"}, {"name": "Login"}]

    complexity = agent._estimate_complexity(mock_schema, mock_endpoints, mock_components)
    print(f"\n✅ Complexity: {complexity['level']} (score: {complexity['score']})")

    # Test timeline estimation
    timeline = agent._estimate_timeline(complexity)
    print(f"   Generation: {timeline['generation_time']}")
    print(f"   Total: {timeline['total_time']}")

    print("\n" + "=" * 80)
    print("✅ Planner agent test complete")
    print("=" * 80)
