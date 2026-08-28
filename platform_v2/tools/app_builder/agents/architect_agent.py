"""
Architect Agent - Phase 2: App Builder
Enhances technical plans with detailed architecture documentation

Purpose:
- Design Entity-Relationship diagrams
- Define component hierarchy
- Recommend state management patterns
- Create API contracts
- Generate architecture diagrams
- Define security architecture

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import json
import re
from typing import Dict, List, Any
from datetime import datetime

# Try to import AI bridge for enhanced architecture suggestions
AI_AVAILABLE = False
try:
    import sys

    sys.path.append("/mnt/archie_brain")
    from ai_bridge.archie_bridge import chat_with_archie

    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


# State management patterns by tech stack
STATE_MANAGEMENT_PATTERNS = {
    "React": {
        "simple": {
            "name": "React Context API",
            "description": "Built-in state management for small to medium apps",
            "files": ["src/contexts/AppContext.js"],
            "advantages": [
                "No external dependencies",
                "Simple API",
                "Good for small apps",
            ],
            "disadvantages": ["Can cause re-renders", "Not ideal for complex state"],
        },
        "medium": {
            "name": "Redux Toolkit",
            "description": "Industry-standard state management with Redux simplified",
            "files": ["src/store/store.js", "src/store/slices/*.js"],
            "advantages": [
                "Predictable state",
                "Time-travel debugging",
                "Large ecosystem",
            ],
            "disadvantages": ["More boilerplate", "Learning curve"],
        },
        "complex": {
            "name": "Redux + Redux Saga",
            "description": "Advanced state management with side effects handling",
            "files": [
                "src/store/store.js",
                "src/store/sagas/*.js",
                "src/store/actions/*.js",
            ],
            "advantages": ["Handles complex async flows", "Testable side effects"],
            "disadvantages": ["Significant complexity", "Steep learning curve"],
        },
    },
    "Vue": {
        "simple": {
            "name": "Vue Composition API",
            "description": "Built-in reactive state management",
            "files": ["src/composables/*.js"],
            "advantages": ["Native to Vue 3", "Simple and reactive"],
            "disadvantages": ["Limited for very complex apps"],
        },
        "medium": {
            "name": "Pinia",
            "description": "Official Vue state management (replaces Vuex)",
            "files": ["src/stores/*.js"],
            "advantages": ["TypeScript support", "DevTools integration", "Simple API"],
            "disadvantages": ["Newer library", "Smaller ecosystem than Redux"],
        },
    },
    "Flask": {
        "simple": {
            "name": "Flask Session",
            "description": "Server-side session management",
            "files": ["app/session.py"],
            "advantages": ["Simple", "Built-in"],
            "disadvantages": ["Not scalable across instances"],
        },
        "medium": {
            "name": "Redis Session Store",
            "description": "Distributed session storage",
            "files": ["app/session.py", "docker-compose.yml (Redis)"],
            "advantages": ["Scalable", "Fast", "Persistent"],
            "disadvantages": ["External dependency"],
        },
    },
}


# Security patterns by app type
SECURITY_PATTERNS = {
    "authentication": {
        "jwt": {
            "name": "JWT (JSON Web Tokens)",
            "description": "Stateless authentication with signed tokens",
            "implementation": [
                "Install PyJWT or similar library",
                "Create /api/auth/login endpoint returning JWT",
                "Middleware to validate JWT on protected routes",
                "Token expiration and refresh logic",
            ],
            "security_considerations": [
                "Store tokens in httpOnly cookies or localStorage",
                "Use strong secret keys (min 256 bits)",
                "Implement token refresh mechanism",
                "Add rate limiting to auth endpoints",
            ],
        },
        "session": {
            "name": "Session-based Authentication",
            "description": "Server-side session storage",
            "implementation": [
                "Use Flask-Login or similar",
                "Store sessions in Redis or database",
                "CSRF protection on forms",
                "Secure session cookies (httpOnly, secure flags)",
            ],
            "security_considerations": [
                "Regenerate session IDs after login",
                "Set appropriate session timeouts",
                "Use secure cookies in production",
                "Implement CSRF protection",
            ],
        },
        "oauth": {
            "name": "OAuth 2.0 (Social Login)",
            "description": "Third-party authentication via Google, GitHub, etc.",
            "implementation": [
                "Install OAuth library (Authlib, Flask-Dance)",
                "Register app with OAuth providers",
                "Create callback endpoints",
                "Store OAuth tokens securely",
            ],
            "security_considerations": [
                "Validate state parameter to prevent CSRF",
                "Use HTTPS for all OAuth flows",
                "Store client secrets securely",
                "Implement proper token refresh",
            ],
        },
    },
    "data_protection": {
        "encryption_at_rest": [
            "Encrypt sensitive fields (passwords with bcrypt)",
            "Use database-level encryption if available",
            "Encrypt backups",
            "Secure key management (environment variables, secrets manager)",
        ],
        "encryption_in_transit": [
            "Use HTTPS (TLS 1.2+) for all connections",
            "Enable HSTS headers",
            "Use secure WebSocket connections (wss://)",
            "Validate SSL certificates",
        ],
        "input_validation": [
            "Validate all user input server-side",
            "Use parameterized queries (prevent SQL injection)",
            "Sanitize HTML inputs (prevent XSS)",
            "Implement rate limiting",
            "Use CORS properly",
        ],
    },
}


class ArchitectAgent:
    """
    Architect Agent - Enhances technical plans with detailed architecture

    Takes a plan from PlannerAgent and adds:
    - ER diagrams (Mermaid format)
    - Component hierarchy
    - State management recommendations
    - API contracts (OpenAPI spec)
    - Architecture diagrams
    - Security architecture
    """

    def __init__(self, project_id: int, plan: Dict[str, Any]):
        """
        Initialize Architect Agent

        Args:
            project_id: Project ID from app_builder_projects
            plan: Technical plan from PlannerAgent
        """
        self.project_id = project_id
        self.plan = plan
        self.architecture = {}

    async def enhance_plan(self) -> Dict[str, Any]:
        """
        Main method to enhance plan with architectural details

        Returns:
            Dict containing enhanced architecture documentation
        """
        print(f"\n[Architect Agent] Enhancing plan for project {self.project_id}...")

        # 1. Generate ER diagram
        er_diagram = self._generate_er_diagram()
        print(f"  ✓ Generated ER diagram with {len(self.plan.get('database_schema', {}).get('tables', []))} tables")

        # 2. Define component hierarchy
        component_hierarchy = self._define_component_hierarchy()
        print(f"  ✓ Defined component hierarchy with {len(component_hierarchy.get('components', []))} components")

        # 3. Recommend state management
        state_management = self._recommend_state_management()
        print(f"  ✓ Recommended state management: {state_management.get('pattern', {}).get('name', 'N/A')}")

        # 4. Create API contracts
        api_contracts = self._create_api_contracts()
        print(f"  ✓ Created API contracts for {len(api_contracts.get('endpoints', []))} endpoints")

        # 5. Generate architecture diagram
        architecture_diagram = self._generate_architecture_diagram()
        print("  ✓ Generated architecture diagram")

        # 6. Define security architecture
        security_architecture = self._define_security_architecture()
        print(f"  ✓ Defined security architecture with {len(security_architecture.get('layers', []))} layers")

        # 7. Add deployment architecture
        deployment_architecture = self._define_deployment_architecture()
        print("  ✓ Defined deployment architecture")

        # 8. AI enhancement (if available)
        ai_insights = {}
        if AI_AVAILABLE:
            ai_insights = await self._enhance_with_ai()
            print("  ✓ Enhanced with AI insights")

        self.architecture = {
            "er_diagram": er_diagram,
            "component_hierarchy": component_hierarchy,
            "state_management": state_management,
            "api_contracts": api_contracts,
            "architecture_diagram": architecture_diagram,
            "security_architecture": security_architecture,
            "deployment_architecture": deployment_architecture,
            "ai_insights": ai_insights,
            "generated_at": datetime.now().isoformat(),
            "version": "1.0",
        }

        print("[Architect Agent] ✅ Architecture enhancement complete\n")
        return self.architecture

    def _generate_er_diagram(self) -> Dict[str, Any]:
        """
        Generate Entity-Relationship diagram in Mermaid format

        Returns:
            Dict with mermaid code and table relationships
        """
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])

        if not tables:
            return {
                "mermaid": "",
                "relationships": [],
                "message": "No database tables defined",
            }

        # Start Mermaid ER diagram
        mermaid_lines = ["erDiagram"]
        relationships = []

        # Add tables and columns
        for table in tables:
            table_name = table.get("table_name", "unknown")
            columns = table.get("columns", [])

            # Add table definition
            for col in columns:
                col_name = col.get("name", "")
                col_type = col.get("type", "").upper()

                # Simplify type for Mermaid
                simple_type = self._simplify_type(col_type)

                # Check if primary key
                is_pk = "PRIMARY KEY" in col_type or col_name == "id"
                pk_marker = " PK" if is_pk else ""

                # Check if foreign key
                is_fk = "REFERENCES" in col_type or col_name.endswith("_id")
                fk_marker = " FK" if is_fk else ""

                mermaid_lines.append(f"    {table_name} {{")
                mermaid_lines.append(f"        {simple_type} {col_name}{pk_marker}{fk_marker}")
                mermaid_lines.append("    }")

                # Extract relationships from foreign keys
                if "REFERENCES" in col_type:
                    # Parse: INTEGER REFERENCES users(id)
                    match = re.search(r"REFERENCES\s+(\w+)", col_type)
                    if match:
                        referenced_table = match.group(1)
                        relationships.append(
                            {
                                "from": table_name,
                                "to": referenced_table,
                                "type": "many-to-one",
                                "foreign_key": col_name,
                            }
                        )
                        mermaid_lines.append(f'    {table_name} }}o--|| {referenced_table} : "belongs to"')

        mermaid_code = "\n".join(mermaid_lines)

        return {
            "mermaid": mermaid_code,
            "relationships": relationships,
            "table_count": len(tables),
            "relationship_count": len(relationships),
        }

    def _simplify_type(self, col_type: str) -> str:
        """Simplify database type for Mermaid diagram"""
        col_type_upper = col_type.upper()

        if "SERIAL" in col_type_upper or "INT" in col_type_upper:
            return "int"
        elif "VARCHAR" in col_type_upper or "TEXT" in col_type_upper or "CHAR" in col_type_upper:
            return "string"
        elif "BOOLEAN" in col_type_upper or "BOOL" in col_type_upper:
            return "boolean"
        elif "TIMESTAMP" in col_type_upper or "DATE" in col_type_upper or "TIME" in col_type_upper:
            return "datetime"
        elif "DECIMAL" in col_type_upper or "FLOAT" in col_type_upper or "REAL" in col_type_upper:
            return "float"
        elif "JSON" in col_type_upper:
            return "json"
        else:
            return "string"

    def _define_component_hierarchy(self) -> Dict[str, Any]:
        """
        Define frontend component hierarchy and relationships

        Returns:
            Dict with component tree and data flow
        """
        tech_stack = self.plan.get("tech_stack", {})
        frontend = tech_stack.get("frontend", "React")
        self.plan.get("components", [])

        # Build component hierarchy based on common patterns
        hierarchy = {
            "root": {
                "name": "App",
                "type": "container",
                "file": "src/App.js" if "React" in frontend else "src/App.vue",
                "children": [],
            }
        }

        # Layout components
        layout_components = {
            "name": "Layout",
            "type": "container",
            "file": f"src/components/Layout.{self._get_extension(frontend)}",
            "children": [
                {
                    "name": "Header",
                    "type": "presentational",
                    "file": f"src/components/Header.{self._get_extension(frontend)}",
                    "responsibilities": ["Navigation", "Logo", "User menu"],
                },
                {
                    "name": "Sidebar",
                    "type": "presentational",
                    "file": f"src/components/Sidebar.{self._get_extension(frontend)}",
                    "responsibilities": ["Navigation links", "Menu items"],
                },
                {
                    "name": "Footer",
                    "type": "presentational",
                    "file": f"src/components/Footer.{self._get_extension(frontend)}",
                    "responsibilities": ["Copyright", "Links"],
                },
            ],
        }

        # Feature components based on database tables
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])

        feature_components = []
        for table in tables:
            table_name = table.get("table_name", "")
            if table_name and table_name != "users":
                # Create CRUD components for each table
                singular = self._singularize(table_name)
                plural = table_name

                feature_component = {
                    "name": f"{singular.capitalize()}Management",
                    "type": "container",
                    "file": f"src/components/{singular.capitalize()}Management.{self._get_extension(frontend)}",
                    "children": [
                        {
                            "name": f"{singular.capitalize()}List",
                            "type": "presentational",
                            "file": f"src/components/{singular.capitalize()}List.{self._get_extension(frontend)}",
                            "responsibilities": [
                                f"Display list of {plural}",
                                "Pagination",
                                "Search",
                            ],
                        },
                        {
                            "name": f"{singular.capitalize()}Form",
                            "type": "presentational",
                            "file": f"src/components/{singular.capitalize()}Form.{self._get_extension(frontend)}",
                            "responsibilities": [
                                f"Create/edit {singular}",
                                "Validation",
                                "Submit",
                            ],
                        },
                        {
                            "name": f"{singular.capitalize()}Detail",
                            "type": "presentational",
                            "file": f"src/components/{singular.capitalize()}Detail.{self._get_extension(frontend)}",
                            "responsibilities": [
                                f"Display {singular} details",
                                "Actions (edit, delete)",
                            ],
                        },
                    ],
                }
                feature_components.append(feature_component)

        # Auth components if needed
        has_auth = any(t.get("table_name") == "users" for t in tables)
        if has_auth:
            auth_components = {
                "name": "Auth",
                "type": "container",
                "file": f"src/components/Auth.{self._get_extension(frontend)}",
                "children": [
                    {
                        "name": "Login",
                        "type": "presentational",
                        "file": f"src/components/Login.{self._get_extension(frontend)}",
                        "responsibilities": [
                            "Login form",
                            "Validation",
                            "Error handling",
                        ],
                    },
                    {
                        "name": "Signup",
                        "type": "presentational",
                        "file": f"src/components/Signup.{self._get_extension(frontend)}",
                        "responsibilities": [
                            "Signup form",
                            "Validation",
                            "Error handling",
                        ],
                    },
                ],
            }
            feature_components.insert(0, auth_components)

        # Assemble full hierarchy
        hierarchy["root"]["children"] = [layout_components] + feature_components

        # Add data flow description
        data_flow = {
            "pattern": "Unidirectional Data Flow",
            "description": "Data flows from parent to child via props, child communicates to parent via callbacks",
            "layers": [
                {
                    "layer": "Container Components",
                    "responsibility": "Manage state, fetch data, handle business logic",
                    "examples": ["App", "UserManagement"],
                },
                {
                    "layer": "Presentational Components",
                    "responsibility": "Display UI, receive props, emit events",
                    "examples": ["Header", "UserList", "UserForm"],
                },
                {
                    "layer": "Services",
                    "responsibility": "API calls, data transformation",
                    "examples": ["api.js", "authService.js"],
                },
            ],
        }

        return {
            "hierarchy": hierarchy,
            "data_flow": data_flow,
            "component_count": self._count_components(hierarchy["root"]),
            "container_count": self._count_by_type(hierarchy["root"], "container"),
            "presentational_count": self._count_by_type(hierarchy["root"], "presentational"),
        }

    def _get_extension(self, frontend: str) -> str:
        """Get file extension based on frontend framework"""
        if "Vue" in frontend:
            return "vue"
        elif "React" in frontend:
            return "jsx"
        else:
            return "js"

    def _singularize(self, word: str) -> str:
        """Simple singularize (remove trailing 's')"""
        if word.endswith("ies"):
            return word[:-3] + "y"
        elif word.endswith("ses"):
            return word[:-2]
        elif word.endswith("s"):
            return word[:-1]
        return word

    def _count_components(self, node: Dict) -> int:
        """Count total components in hierarchy"""
        count = 1
        for child in node.get("children", []):
            count += self._count_components(child)
        return count

    def _count_by_type(self, node: Dict, comp_type: str) -> int:
        """Count components of specific type"""
        count = 1 if node.get("type") == comp_type else 0
        for child in node.get("children", []):
            count += self._count_by_type(child, comp_type)
        return count

    def _recommend_state_management(self) -> Dict[str, Any]:
        """
        Recommend state management pattern based on complexity

        Returns:
            Dict with recommended pattern and justification
        """
        tech_stack = self.plan.get("tech_stack", {})
        frontend = tech_stack.get("frontend", "React")
        complexity = self.plan.get("complexity", {})
        complexity_level = complexity.get("level", "medium")

        # Get patterns for this frontend
        patterns = STATE_MANAGEMENT_PATTERNS.get(frontend, STATE_MANAGEMENT_PATTERNS["React"])

        # Choose pattern based on complexity
        if complexity_level == "low":
            pattern = patterns.get("simple", {})
            justification = "Simple app with minimal state - built-in state management is sufficient"
        elif complexity_level == "medium":
            pattern = patterns.get("medium", patterns.get("simple", {}))
            justification = "Medium complexity app - recommended state management library for maintainability"
        else:  # high
            pattern = patterns.get("complex", patterns.get("medium", {}))
            justification = "Complex app with many features - advanced state management required"

        return {
            "pattern": pattern,
            "justification": justification,
            "complexity_level": complexity_level,
            "alternative_patterns": [p for k, p in patterns.items() if k != complexity_level],
        }

    def _create_api_contracts(self) -> Dict[str, Any]:
        """
        Create OpenAPI-style API contracts for all endpoints

        Returns:
            Dict with OpenAPI specification
        """
        tech_stack = self.plan.get("tech_stack", {})
        tech_stack.get("backend", "Flask")
        endpoints = self.plan.get("api_endpoints", [])
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])

        # Build OpenAPI spec
        openapi_spec = {
            "openapi": "3.0.0",
            "info": {
                "title": f'{self.plan.get("name", "App")} API',
                "version": "1.0.0",
                "description": f'API documentation for {self.plan.get("name", "App")}',
            },
            "servers": [
                {"url": "http://localhost:5000", "description": "Development server"},
                {"url": "https://api.example.com", "description": "Production server"},
            ],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {
                    "BearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    }
                },
            },
        }

        # Create schemas from database tables
        for table in tables:
            table_name = table.get("table_name", "")
            schema_obj = {"type": "object", "properties": {}}

            for col in table.get("columns", []):
                col_name = col.get("name", "")
                col_type = col.get("type", "").upper()

                # Convert DB type to OpenAPI type
                if "INT" in col_type or "SERIAL" in col_type:
                    openapi_type = "integer"
                elif "BOOL" in col_type:
                    openapi_type = "boolean"
                elif "TIMESTAMP" in col_type or "DATE" in col_type:
                    openapi_type = "string"
                    schema_obj["properties"][col_name] = {
                        "type": openapi_type,
                        "format": "date-time",
                    }
                    continue
                else:
                    openapi_type = "string"

                schema_obj["properties"][col_name] = {"type": openapi_type}

            openapi_spec["components"]["schemas"][table_name.capitalize()] = schema_obj

        # Create endpoint definitions
        for endpoint in endpoints:
            method = endpoint.get("method", "GET").lower()
            path = endpoint.get("path", "/")

            if path not in openapi_spec["paths"]:
                openapi_spec["paths"][path] = {}

            # Determine operation details
            operation = self._create_operation_spec(endpoint, tables)
            openapi_spec["paths"][path][method] = operation

        return {
            "openapi_spec": openapi_spec,
            "endpoint_count": len(endpoints),
            "schema_count": len(tables),
            "export_formats": ["JSON", "YAML"],
        }

    def _create_operation_spec(self, endpoint: Dict, tables: List[Dict]) -> Dict:
        """Create OpenAPI operation specification for an endpoint"""
        method = endpoint.get("method", "GET")
        path = endpoint.get("path", "/")

        # Extract resource name from path (e.g., /api/users -> users)
        match = re.search(r"/api/(\w+)", path)
        resource = match.group(1).capitalize() if match else "Resource"

        operation = {
            "summary": f"{method} {resource}",
            "tags": [resource],
            "responses": {
                "200": {
                    "description": "Successful operation",
                    "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{resource}"}}},
                },
                "400": {"description": "Bad request"},
                "401": {"description": "Unauthorized"},
                "404": {"description": "Not found"},
                "500": {"description": "Server error"},
            },
        }

        # Add parameters for GET, PUT, DELETE with {id}
        if "{id}" in path:
            operation["parameters"] = [
                {
                    "name": "id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                }
            ]

        # Add request body for POST, PUT
        if method in ["POST", "PUT"]:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{resource}"}}},
            }

        # Add security for protected endpoints
        if "/api/" in path and "/auth/" not in path:
            operation["security"] = [{"BearerAuth": []}]

        return operation

    def _generate_architecture_diagram(self) -> Dict[str, Any]:
        """
        Generate high-level architecture diagram in Mermaid format

        Returns:
            Dict with mermaid code for architecture diagram
        """
        tech_stack = self.plan.get("tech_stack", {})
        frontend = tech_stack.get("frontend", "React")
        backend = tech_stack.get("backend", "Flask")
        database = tech_stack.get("database", "PostgreSQL")

        # Build Mermaid flowchart
        mermaid_lines = [
            "graph TB",
            '    subgraph "Frontend"',
            f"        A[{frontend} App]",
            "        B[Components]",
            "        C[State Management]",
            "    end",
            "    ",
            '    subgraph "Backend"',
            f"        D[{backend} Server]",
            "        E[API Routes]",
            "        F[Business Logic]",
            "        G[Authentication]",
            "    end",
            "    ",
            '    subgraph "Data Layer"',
            f"        H[{database}]",
            "        I[ORM/Query Builder]",
            "    end",
            "    ",
            "    A --> D",
            "    B --> C",
            "    C --> A",
            "    D --> E",
            "    E --> F",
            "    E --> G",
            "    F --> I",
            "    G --> I",
            "    I --> H",
        ]

        # Add external services if any
        external_services = []
        if any(t.get("table_name") == "users" for t in self.plan.get("database_schema", {}).get("tables", [])):
            external_services.append("J[Auth Service]")
            mermaid_lines.extend(
                [
                    "    ",
                    '    subgraph "External"',
                    "        J[Auth Provider]",
                    "    end",
                    "    ",
                    "    G -.-> J",
                ]
            )

        mermaid_code = "\n".join(mermaid_lines)

        return {
            "mermaid": mermaid_code,
            "layers": ["Frontend", "Backend", "Data Layer"],
            "tech_stack": tech_stack,
            "external_services": external_services,
        }

    def _define_security_architecture(self) -> Dict[str, Any]:
        """
        Define security architecture with best practices

        Returns:
            Dict with security layers and implementation details
        """
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])
        has_auth = any(t.get("table_name") == "users" for t in tables)

        security_layers = []

        # Layer 1: Authentication
        if has_auth:
            auth_pattern = SECURITY_PATTERNS["authentication"]["jwt"]  # Default to JWT
            security_layers.append(
                {
                    "layer": "Authentication",
                    "pattern": auth_pattern["name"],
                    "description": auth_pattern["description"],
                    "implementation": auth_pattern["implementation"],
                    "security_considerations": auth_pattern["security_considerations"],
                }
            )

        # Layer 2: Authorization
        security_layers.append(
            {
                "layer": "Authorization",
                "pattern": "Role-Based Access Control (RBAC)",
                "description": "Control access based on user roles",
                "implementation": [
                    "Define user roles (user, admin, etc.)",
                    "Create permissions table",
                    "Middleware to check permissions",
                    "Decorator functions for route protection",
                ],
                "security_considerations": [
                    "Principle of least privilege",
                    "Check permissions on every request",
                    "Log authorization failures",
                    "Separate admin routes",
                ],
            }
        )

        # Layer 3: Data Protection
        security_layers.append(
            {
                "layer": "Data Protection",
                "patterns": [
                    "Encryption at Rest",
                    "Encryption in Transit",
                    "Input Validation",
                ],
                "implementation": SECURITY_PATTERNS["data_protection"]["encryption_at_rest"]
                + SECURITY_PATTERNS["data_protection"]["encryption_in_transit"]
                + SECURITY_PATTERNS["data_protection"]["input_validation"],
            }
        )

        # Layer 4: API Security
        security_layers.append(
            {
                "layer": "API Security",
                "measures": [
                    "Rate limiting (10-100 requests/minute)",
                    "CORS configuration (whitelist domains)",
                    "Content Security Policy headers",
                    "API key validation for external access",
                    "Request size limits",
                    "Timeout configuration",
                ],
                "implementation": [
                    "Use Flask-Limiter or similar",
                    "Configure CORS middleware",
                    "Add security headers (X-Frame-Options, X-Content-Type-Options)",
                    "Implement API key middleware",
                ],
            }
        )

        # Security checklist
        security_checklist = [
            {"item": "Password hashing with bcrypt", "priority": "CRITICAL"},
            {"item": "HTTPS in production", "priority": "CRITICAL"},
            {
                "item": "SQL injection prevention (parameterized queries)",
                "priority": "CRITICAL",
            },
            {"item": "XSS prevention (input sanitization)", "priority": "CRITICAL"},
            {"item": "CSRF protection on forms", "priority": "HIGH"},
            {"item": "Rate limiting on auth endpoints", "priority": "HIGH"},
            {"item": "Secure session management", "priority": "HIGH"},
            {"item": "Environment variable protection", "priority": "HIGH"},
            {"item": "Security headers (HSTS, CSP)", "priority": "MEDIUM"},
            {"item": "Logging and monitoring", "priority": "MEDIUM"},
            {"item": "Regular dependency updates", "priority": "MEDIUM"},
            {"item": "Error message sanitization", "priority": "LOW"},
        ]

        return {
            "layers": security_layers,
            "checklist": security_checklist,
            "has_authentication": has_auth,
            "compliance_notes": [
                "Ensure GDPR compliance if handling EU user data",
                "Implement data retention policies",
                "Add privacy policy and terms of service",
                "Enable audit logging for sensitive operations",
            ],
        }

    def _define_deployment_architecture(self) -> Dict[str, Any]:
        """
        Define deployment architecture and infrastructure

        Returns:
            Dict with deployment strategy and infrastructure requirements
        """
        self.plan.get("tech_stack", {})
        complexity = self.plan.get("complexity", {})

        # Deployment strategy based on complexity
        if complexity.get("level") == "low":
            strategy = "Simple Deployment"
            infrastructure = {
                "hosting": "Vercel / Netlify (Frontend) + Heroku (Backend)",
                "database": "Managed PostgreSQL (Heroku Postgres, Supabase)",
                "estimated_cost": "$0-25/month",
                "scalability": "Limited, suitable for small apps",
            }
        elif complexity.get("level") == "medium":
            strategy = "Containerized Deployment"
            infrastructure = {
                "hosting": "Railway / Render / DigitalOcean App Platform",
                "database": "Managed PostgreSQL (AWS RDS, DigitalOcean Managed DB)",
                "containerization": "Docker + docker-compose",
                "estimated_cost": "$25-100/month",
                "scalability": "Good, can handle moderate traffic",
            }
        else:  # high
            strategy = "Cloud-Native Deployment"
            infrastructure = {
                "hosting": "AWS (ECS/EKS) / Google Cloud (GKE) / Azure (AKS)",
                "database": "AWS RDS / Cloud SQL with read replicas",
                "containerization": "Kubernetes",
                "cdn": "CloudFront / CloudFlare",
                "load_balancer": "Application Load Balancer",
                "estimated_cost": "$100-500+/month",
                "scalability": "Excellent, auto-scaling enabled",
            }

        # Docker configuration
        docker_config = {
            "frontend_dockerfile": """FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]""",
            "backend_dockerfile": """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]""",
            "docker_compose": """version: '3.8'
services:
  backend:
    build: ./backend
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/appdb
    depends_on:
      - db

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=appdb
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:""",
        }

        # CI/CD pipeline
        cicd_pipeline = {
            "recommended_tool": "GitHub Actions",
            "stages": [
                "Lint and format code",
                "Run unit tests",
                "Run integration tests",
                "Build Docker images",
                "Push to container registry",
                "Deploy to staging",
                "Run smoke tests",
                "Deploy to production",
            ],
            "github_actions_example": """.github/workflows/deploy.yml:
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: pytest
      - name: Build and push
        run: docker build -t app:latest .
      - name: Deploy
        run: ./deploy.sh""",
        }

        # Monitoring and observability
        monitoring = {
            "tools": [
                "Application Performance Monitoring (APM): Sentry, New Relic",
                "Logging: CloudWatch, Papertrail, Logtail",
                "Metrics: Prometheus + Grafana",
                "Uptime monitoring: UptimeRobot, Pingdom",
            ],
            "key_metrics": [
                "Response time (p50, p95, p99)",
                "Error rate",
                "Request throughput",
                "Database query performance",
                "Memory and CPU usage",
                "User session duration",
            ],
        }

        return {
            "strategy": strategy,
            "infrastructure": infrastructure,
            "docker_config": docker_config,
            "cicd_pipeline": cicd_pipeline,
            "monitoring": monitoring,
            "estimated_deployment_time": "2-4 hours (initial setup)",
        }

    async def _enhance_with_ai(self) -> Dict[str, Any]:
        """
        Use A.R.C.H.I.E. to provide additional architectural insights

        Returns:
            Dict with AI-generated insights
        """
        if not AI_AVAILABLE:
            return {}

        try:
            # Prepare context for AI
            context = f"""
            I'm designing the architecture for an application with:
            - Tech Stack: {self.plan.get('tech_stack', {})}
            - Database Tables: {len(self.plan.get('database_schema', {}).get('tables', []))}
            - API Endpoints: {len(self.plan.get('api_endpoints', []))}
            - Complexity: {self.plan.get('complexity', {}).get('level', 'medium')}

            Can you suggest:
            1. Potential architectural risks or bottlenecks
            2. Performance optimization opportunities
            3. Scalability considerations
            4. Best practices specific to this tech stack
            """

            response = chat_with_archie(
                user_message=context,
                context={"task": "architecture_review", "project_id": self.project_id},
            )

            return {
                "ai_suggestions": response.get("response", ""),
                "confidence": response.get("confidence", 0.7),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            print(f"[Architect Agent] AI enhancement failed: {e}")
            return {}

    async def save_to_database(self, db_connection=None) -> bool:
        """
        Save architecture documentation to database

        Args:
            db_connection: Optional database connection

        Returns:
            bool: True if saved successfully
        """
        if db_connection is None:
            try:
                from tools.database import db

                db_connection = db
            except ImportError:
                print("[Architect Agent] ⚠️ Database not available, skipping save")
                return False

        try:
            with db_connection.engine.connect() as conn:
                # Update project with architecture details
                update_query = """
                    UPDATE app_builder_projects
                    SET architecture_plan = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """

                conn.execute(
                    db_connection.text(update_query),
                    (json.dumps(self.architecture), self.project_id),
                )
                conn.commit()

                print(f"[Architect Agent] ✅ Architecture saved to database (project {self.project_id})")
                return True

        except Exception as e:
            print(f"[Architect Agent] ❌ Failed to save to database: {e}")
            return False


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 80)
    print("ARCHITECT AGENT TEST")
    print("=" * 80)

    # Mock plan from PlannerAgent
    mock_plan = {
        "name": "Todo App",
        "tech_stack": {
            "backend": "Flask",
            "frontend": "React",
            "database": "PostgreSQL",
        },
        "database_schema": {
            "database_type": "PostgreSQL",
            "tables": [
                {
                    "table_name": "users",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {"name": "username", "type": "VARCHAR(100) UNIQUE"},
                        {"name": "email", "type": "VARCHAR(255) UNIQUE"},
                    ],
                },
                {
                    "table_name": "tasks",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {"name": "user_id", "type": "INTEGER REFERENCES users(id)"},
                        {"name": "title", "type": "VARCHAR(255)"},
                        {"name": "completed", "type": "BOOLEAN DEFAULT FALSE"},
                    ],
                },
            ],
        },
        "api_endpoints": [
            {"method": "POST", "path": "/api/auth/login"},
            {"method": "GET", "path": "/api/tasks"},
            {"method": "POST", "path": "/api/tasks"},
            {"method": "PUT", "path": "/api/tasks/{id}"},
            {"method": "DELETE", "path": "/api/tasks/{id}"},
        ],
        "components": ["TaskList", "TaskForm", "Login"],
        "complexity": {"level": "medium", "score": 150},
    }

    async def test_architect():
        print("\nTest 1: Todo App Architecture")
        print("-" * 80)

        architect = ArchitectAgent(project_id=1, plan=mock_plan)
        architecture = await architect.enhance_plan()

        print("\n📊 Architecture Summary:")
        print(
            f"  - ER Diagram: {architecture['er_diagram']['table_count']} tables, {architecture['er_diagram']['relationship_count']} relationships"
        )
        print(f"  - Components: {architecture['component_hierarchy']['component_count']} total")
        print(f"  - State Management: {architecture['state_management']['pattern'].get('name', 'N/A')}")
        print(f"  - API Endpoints: {architecture['api_contracts']['endpoint_count']} documented")
        print(f"  - Security Layers: {len(architecture['security_architecture']['layers'])}")
        print(f"  - Deployment Strategy: {architecture['deployment_architecture']['strategy']}")

        print("\n📝 ER Diagram (Mermaid):")
        print(architecture["er_diagram"]["mermaid"][:500] + "...")

        print("\n🏗️ Architecture Diagram (Mermaid):")
        print(architecture["architecture_diagram"]["mermaid"][:500] + "...")

        print("\n✅ Architect Agent test complete")

    asyncio.run(test_architect())

    print("\n" + "=" * 80)
