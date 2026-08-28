"""
Backend Generator Agent - Phase 2: App Builder
Generates production-ready backend code (Flask/FastAPI) from technical plans

Purpose:
- Generate API routes and endpoints
- Generate database models (SQLAlchemy)
- Generate authentication logic (JWT/Session)
- Generate middleware (CORS, error handling, rate limiting)
- Generate configuration files
- Generate requirements.txt
- Proper project structure

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import re
from typing import Dict, Any
from datetime import datetime

# Try to import database for file storage
DB_AVAILABLE = False
try:
    import sys

    sys.path.append("/mnt/archie_brain/platform_v2")
    from tools.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class BackendGenerator:
    """
    Backend Generator Agent - Generates backend code from plans

    Supports:
    - Flask (Python web framework)
    - FastAPI (Python async API framework)

    Generates:
    - API routes with CRUD operations
    - Database models (SQLAlchemy)
    - Authentication (JWT/Session)
    - Middleware (CORS, error handling)
    - Configuration files
    - requirements.txt
    """

    def __init__(self, project_id: int, plan: Dict[str, Any], architecture: Dict[str, Any]):
        """
        Initialize Backend Generator

        Args:
            project_id: Project ID from app_builder_projects
            plan: Technical plan from PlannerAgent
            architecture: Architecture details from ArchitectAgent
        """
        self.project_id = project_id
        self.plan = plan
        self.architecture = architecture
        self.generated_files = []

    async def generate_backend(self) -> Dict[str, Any]:
        """
        Main method to generate backend code

        Returns:
            Dict containing all generated files and metadata
        """
        print(f"\n[Backend Generator] Generating backend for project {self.project_id}...")

        tech_stack = self.plan.get("tech_stack", {})
        backend_framework = tech_stack.get("backend", "Flask")

        # Determine which generator to use
        if "Flask" in backend_framework:
            result = await self._generate_flask_backend()
        elif "FastAPI" in backend_framework:
            result = await self._generate_fastapi_backend()
        else:
            raise ValueError(f"Unsupported backend framework: {backend_framework}")

        print(f"[Backend Generator] ✅ Generated {len(result['files'])} backend files\n")
        return result

    # ========================================================================
    # FLASK BACKEND GENERATION
    # ========================================================================

    async def _generate_flask_backend(self) -> Dict[str, Any]:
        """Generate complete Flask backend"""
        print("[Backend Generator] Generating Flask backend...")

        files = {}

        # 1. Generate requirements.txt
        files["backend/requirements.txt"] = self._generate_flask_requirements()
        print("  ✓ Generated requirements.txt")

        # 2. Generate config.py
        files["backend/config.py"] = self._generate_flask_config()
        print("  ✓ Generated config.py")

        # 3. Generate app.py (main application)
        files["backend/app.py"] = self._generate_flask_app()
        print("  ✓ Generated app.py")

        # 4. Generate database models
        model_files = self._generate_flask_models()
        files.update(model_files)
        print(f"  ✓ Generated {len(model_files)} model files")

        # 5. Generate API routes
        route_files = self._generate_flask_routes()
        files.update(route_files)
        print(f"  ✓ Generated {len(route_files)} route files")

        # 6. Generate authentication
        if self._has_authentication():
            auth_files = self._generate_flask_auth()
            files.update(auth_files)
            print(f"  ✓ Generated authentication files")

        # 7. Generate middleware
        middleware_files = self._generate_flask_middleware()
        files.update(middleware_files)
        print(f"  ✓ Generated middleware files")

        # 8. Generate database initialization
        files["backend/init_db.py"] = self._generate_flask_db_init()
        print("  ✓ Generated init_db.py")

        # 9. Generate .env.example
        files["backend/.env.example"] = self._generate_env_file()
        print("  ✓ Generated .env.example")

        # 10. Generate README
        files["backend/README.md"] = self._generate_backend_readme("Flask")
        print("  ✓ Generated README.md")

        # Store files for database persistence
        self.generated_files = [
            {
                "file_path": path,
                "content": content,
                "file_type": self._get_file_type(path),
            }
            for path, content in files.items()
        ]

        return {
            "framework": "Flask",
            "files": self.generated_files,
            "file_count": len(files),
            "structure": self._get_file_structure(files),
            "generated_at": datetime.now().isoformat(),
        }

    def _generate_flask_requirements(self) -> str:
        """Generate requirements.txt for Flask"""
        schema = self.plan.get("database_schema", {})
        db_type = schema.get("database_type", "PostgreSQL")
        has_auth = self._has_authentication()

        requirements = [
            "# Flask Framework",
            "Flask==3.0.0",
            "Flask-CORS==4.0.0",
            "",
            "# Database",
            "SQLAlchemy==2.0.23",
            "Flask-SQLAlchemy==3.1.1",
        ]

        if "PostgreSQL" in db_type:
            requirements.extend(
                [
                    "psycopg2-binary==2.9.9",
                ]
            )
        elif "MySQL" in db_type:
            requirements.extend(
                [
                    "pymysql==1.1.0",
                ]
            )
        else:  # SQLite
            requirements.extend(
                [
                    "# SQLite is built into Python",
                ]
            )

        if has_auth:
            requirements.extend(
                [
                    "",
                    "# Authentication",
                    "PyJWT==2.8.0",
                    "bcrypt==4.1.2",
                    "Flask-Login==0.6.3",
                ]
            )

        requirements.extend(
            [
                "",
                "# Validation & Security",
                "python-dotenv==1.0.0",
                "marshmallow==3.20.1",
                "",
                "# Utilities",
                "python-dateutil==2.8.2",
                "requests==2.31.0",
            ]
        )

        return "\n".join(requirements)

    def _generate_flask_config(self) -> str:
        """Generate config.py with environment configurations"""
        schema = self.plan.get("database_schema", {})
        db_type = schema.get("database_type", "PostgreSQL")

        if "PostgreSQL" in db_type:
            db_uri = "postgresql://user:password@localhost:5432/dbname"
        elif "MySQL" in db_type:
            db_uri = "mysql+pymysql://user:password@localhost:3306/dbname"
        else:
            db_uri = "sqlite:///app.db"

        return f'''"""
Application Configuration
Load settings from environment variables
"""
import os
from datetime import timedelta, timezone
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration"""
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = False
    TESTING = False

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', '{db_uri}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')

    # JWT Authentication
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = "100 per hour"

    # Pagination
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    # Use environment variables for sensitive data
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL must be set in production")


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Configuration dictionary
config = {{
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}}


def get_config(env=None):
    """Get configuration based on environment"""
    if env is None:
        env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
'''

    def _generate_flask_app(self) -> str:
        """Generate main app.py file"""
        has_auth = self._has_authentication()
        tables = self.plan.get("database_schema", {}).get("tables", [])

        # Get resource names (exclude users table)
        resources = [t["table_name"] for t in tables if t["table_name"] != "users"]

        imports = [
            "from flask import Flask, jsonify",
            "from flask_cors import CORS",
            "from flask_sqlalchemy import SQLAlchemy",
            "from config import get_config",
            "import os",
        ]

        if has_auth:
            imports.append("from flask_login import LoginManager")

        # Blueprint imports
        blueprint_imports = []
        if has_auth:
            blueprint_imports.append("from routes.auth import auth_bp")
        for resource in resources:
            blueprint_imports.append(f"from routes.{resource} import {resource}_bp")

        return f'''"""
Main Application Entry Point
Initializes Flask app, database, and registers blueprints
"""
{chr(10).join(imports)}

# Initialize extensions
db = SQLAlchemy()
{'login_manager = LoginManager()' if has_auth else ''}


def create_app(config_name=None):
    """Application factory pattern"""
    # Create Flask app
    app = Flask(__name__)

    # Load configuration
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')
    app.config.from_object(get_config(config_name))

    # Initialize extensions
    db.init_app(app)
    CORS(app, origins=app.config['CORS_ORIGINS'])
    {'login_manager.init_app(app)' if has_auth else ''}

    # Register blueprints
{chr(10).join(f'    app.register_blueprint({resource}_bp)' for resource in ([f'auth_bp'] if has_auth else []) + [f'{r}_bp' for r in resources])}

    # Error handlers
    register_error_handlers(app)

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return jsonify({{'status': 'healthy', 'message': 'API is running'}}), 200

    return app


def register_error_handlers(app):
    """Register global error handlers"""

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({{'error': 'Resource not found'}}), 404

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({{'error': 'Bad request', 'message': str(error)}}), 400

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({{'error': 'Internal server error'}}), 500

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({{'error': 'Forbidden', 'message': 'You do not have permission to access this resource'}}), 403

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({{'error': 'Unauthorized', 'message': 'Authentication required'}}), 401


if __name__ == '__main__':
    app = create_app()

    # Create tables if they don't exist
    with app.app_context():
        db.create_all()

    # Run the app
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=app.config['DEBUG'])
'''

    def _generate_flask_models(self) -> Dict[str, str]:
        """Generate SQLAlchemy models for all database tables"""
        files = {}
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])

        # Generate models/__init__.py
        model_imports = [
            f"from .{table['table_name']} import {self._to_class_name(table['table_name'])}" for table in tables
        ]

        files[
            "backend/models/__init__.py"
        ] = f'''"""
Database Models
"""
from app import db

{chr(10).join(model_imports)}

__all__ = [{', '.join([f"'{self._to_class_name(t['table_name'])}'" for t in tables])}]
'''

        # Generate individual model files
        for table in tables:
            table_name = table["table_name"]
            class_name = self._to_class_name(table_name)

            files[f"backend/models/{table_name}.py"] = self._generate_model_file(table)

        return files

    def _generate_model_file(self, table: Dict) -> str:
        """Generate a single SQLAlchemy model file"""
        table_name = table["table_name"]
        class_name = self._to_class_name(table_name)
        columns = table.get("columns", [])

        # Generate column definitions
        column_defs = []
        for col in columns:
            col_name = col["name"]
            col_type = col["type"].upper()

            # Convert SQL type to SQLAlchemy type
            sa_type = self._sql_to_sqlalchemy_type(col_type)

            # Build column definition
            col_def = f"    {col_name} = db.Column({sa_type}"

            # Add constraints
            if "PRIMARY KEY" in col_type:
                col_def += ", primary_key=True"
            if "UNIQUE" in col_type:
                col_def += ", unique=True"
            if "NOT NULL" in col_type and "PRIMARY KEY" not in col_type:
                col_def += ", nullable=False"
            if "DEFAULT" in col_type:
                # Extract default value
                match = re.search(r"DEFAULT\s+([^\s,)]+)", col_type)
                if match:
                    default_val = match.group(1)
                    if default_val == "NOW()" or default_val == "CURRENT_TIMESTAMP":
                        col_def += ", default=datetime.utcnow"
                    elif default_val.lower() in ["true", "false"]:
                        col_def += f", default={default_val.title()}"
                    else:
                        col_def += f", default={default_val}"

            # Foreign key
            if "REFERENCES" in col_type:
                match = re.search(r"REFERENCES\s+(\w+)\((\w+)\)", col_type)
                if match:
                    ref_table = match.group(1)
                    ref_col = match.group(2)
                    col_def += f", db.ForeignKey('{ref_table}.{ref_col}')"

            col_def += ")"
            column_defs.append(col_def)

        # Add timestamps if not present
        has_created_at = any(col["name"] == "created_at" for col in columns)
        has_updated_at = any(col["name"] == "updated_at" for col in columns)

        if not has_created_at:
            column_defs.append("    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)")
        if not has_updated_at:
            column_defs.append(
                "    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)"
            )

        # Generate relationships if foreign keys exist
        relationships = []
        for col in columns:
            if "REFERENCES" in col["type"]:
                match = re.search(r"REFERENCES\s+(\w+)", col["type"])
                if match:
                    ref_table = match.group(1)
                    ref_class = self._to_class_name(ref_table)
                    rel_name = ref_table if ref_table != "users" else "user"
                    relationships.append(f"    {rel_name} = db.relationship('{ref_class}', backref='{table_name}')")

        return f'''"""
{class_name} Model
"""
from app import db
from datetime import datetime, timezone


class {class_name}(db.Model):
    """
    {class_name} database model
    Table: {table_name}
    """
    __tablename__ = '{table_name}'

{chr(10).join(column_defs)}

{chr(10).join(relationships) if relationships else ''}

    def to_dict(self):
        """Convert model to dictionary"""
        return {{
{chr(10).join(f"            '{col['name']}': self.{col['name']}," for col in columns)}
            'created_at': self.created_at.isoformat() if hasattr(self, 'created_at') else None,
            'updated_at': self.updated_at.isoformat() if hasattr(self, 'updated_at') else None,
        }}

    def __repr__(self):
        return f'<{class_name} {{self.id}}>'
'''

    def _generate_flask_routes(self) -> Dict[str, str]:
        """Generate Flask API routes for all resources"""
        files = {}
        schema = self.plan.get("database_schema", {})
        tables = schema.get("tables", [])

        # Generate routes/__init__.py
        files["backend/routes/__init__.py"] = '"""API Routes"""'

        # Generate route files for each table (except users, handled by auth)
        for table in tables:
            table_name = table["table_name"]
            if table_name == "users":
                continue  # Users handled by auth routes

            files[f"backend/routes/{table_name}.py"] = self._generate_route_file(table)

        return files

    def _generate_route_file(self, table: Dict) -> str:
        """Generate a single route file with CRUD operations"""
        table_name = table["table_name"]
        class_name = self._to_class_name(table_name)
        singular = self._singularize(table_name)

        # Determine primary key column
        pk_col = next(
            (col["name"] for col in table["columns"] if "PRIMARY KEY" in col["type"]),
            "id",
        )

        return f'''"""
{class_name} Routes
CRUD API endpoints for {table_name}
"""
from flask import Blueprint, request, jsonify
from app import db
from models.{table_name} import {class_name}

{table_name}_bp = Blueprint('{table_name}', __name__, url_prefix='/api/{table_name}')


@{table_name}_bp.route('', methods=['GET'])
def get_all_{table_name}():
    """
    Get all {table_name}

    Query Parameters:
        - page: Page number (default: 1)
        - per_page: Items per page (default: 20, max: 100)

    Returns:
        200: List of {table_name}
        500: Server error
    """
    try:
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)

        # Query
        pagination = {class_name}.query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        return jsonify({{
            'success': True,
            'data': [item.to_dict() for item in pagination.items],
            'pagination': {{
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }}
        }}), 200

    except Exception as e:
        return jsonify({{'success': False, 'error': str(e)}}), 500


@{table_name}_bp.route('/<int:{pk_col}>', methods=['GET'])
def get_{singular}({pk_col}):
    """
    Get a single {singular} by ID

    Args:
        {pk_col}: {class_name} ID

    Returns:
        200: {class_name} data
        404: {class_name} not found
    """
    {singular} = {class_name}.query.get_or_404({pk_col})
    return jsonify({{'success': True, 'data': {singular}.to_dict()}}), 200


@{table_name}_bp.route('', methods=['POST'])
def create_{singular}():
    """
    Create a new {singular}

    Request Body:
        JSON object with {singular} data

    Returns:
        201: {class_name} created
        400: Invalid data
        500: Server error
    """
    try:
        data = request.get_json()

        # Validation (add more as needed)
        if not data:
            return jsonify({{'success': False, 'error': 'No data provided'}}), 400

        # Create new instance
        {singular} = {class_name}(**data)

        # Save to database
        db.session.add({singular})
        db.session.commit()

        return jsonify({{
            'success': True,
            'message': '{class_name} created successfully',
            'data': {singular}.to_dict()
        }}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({{'success': False, 'error': str(e)}}), 500


@{table_name}_bp.route('/<int:{pk_col}>', methods=['PUT'])
def update_{singular}({pk_col}):
    """
    Update a {singular}

    Args:
        {pk_col}: {class_name} ID

    Request Body:
        JSON object with fields to update

    Returns:
        200: {class_name} updated
        404: {class_name} not found
        500: Server error
    """
    try:
        {singular} = {class_name}.query.get_or_404({pk_col})
        data = request.get_json()

        # Update fields
        for key, value in data.items():
            if hasattr({singular}, key):
                setattr({singular}, key, value)

        db.session.commit()

        return jsonify({{
            'success': True,
            'message': '{class_name} updated successfully',
            'data': {singular}.to_dict()
        }}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({{'success': False, 'error': str(e)}}), 500


@{table_name}_bp.route('/<int:{pk_col}>', methods=['DELETE'])
def delete_{singular}({pk_col}):
    """
    Delete a {singular}

    Args:
        {pk_col}: {class_name} ID

    Returns:
        200: {class_name} deleted
        404: {class_name} not found
        500: Server error
    """
    try:
        {singular} = {class_name}.query.get_or_404({pk_col})

        db.session.delete({singular})
        db.session.commit()

        return jsonify({{
            'success': True,
            'message': '{class_name} deleted successfully'
        }}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({{'success': False, 'error': str(e)}}), 500
'''

    def _generate_flask_auth(self) -> Dict[str, str]:
        """Generate authentication routes and utilities"""
        files = {}

        # Auth routes
        files[
            "backend/routes/auth.py"
        ] = '''"""
Authentication Routes
User registration, login, logout, token refresh
"""
from flask import Blueprint, request, jsonify
from app import db
from models.users import User
import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
import bcrypt
from config import get_config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

config = get_config()


def create_token(user_id):
    """Create JWT access token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + config.JWT_ACCESS_TOKEN_EXPIRES,
        'iat': datetime.now(timezone.utc)
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm='HS256')


def create_refresh_token(user_id):
    """Create JWT refresh token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + config.JWT_REFRESH_TOKEN_EXPIRES,
        'iat': datetime.now(timezone.utc),
        'type': 'refresh'
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm='HS256')


def token_required(f):
    """Decorator to require JWT authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Check for token in Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(' ')[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401

        if not token:
            return jsonify({'error': 'Authentication token missing'}), 401

        try:
            # Decode token
            payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=['HS256'])
            current_user_id = payload['user_id']
            current_user = User.query.get(current_user_id)

            if not current_user:
                return jsonify({'error': 'User not found'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        return f(current_user, *args, **kwargs)

    return decorated


@auth_bp.route('/signup', methods=['POST'])
def signup():
    """
    User registration

    Request Body:
        - username: string (required)
        - email: string (required)
        - password: string (required, min 8 chars)

    Returns:
        201: User created
        400: Invalid data
        409: User already exists
    """
    try:
        data = request.get_json()

        # Validation
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        if not all([username, email, password]):
            return jsonify({'error': 'Missing required fields'}), 400

        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        # Check if user exists
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 409

        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already taken'}), 409

        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Create user
        user = User(
            username=username,
            email=email,
            password_hash=password_hash
        )

        db.session.add(user)
        db.session.commit()

        # Generate tokens
        access_token = create_token(user.id)
        refresh_token = create_refresh_token(user.id)

        return jsonify({
            'success': True,
            'message': 'User created successfully',
            'user': user.to_dict(),
            'access_token': access_token,
            'refresh_token': refresh_token
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    User login

    Request Body:
        - email: string (required)
        - password: string (required)

    Returns:
        200: Login successful
        401: Invalid credentials
    """
    try:
        data = request.get_json()

        email = data.get('email')
        password = data.get('password')

        if not all([email, password]):
            return jsonify({'error': 'Missing email or password'}), 400

        # Find user
        user = User.query.filter_by(email=email).first()

        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401

        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        # Generate tokens
        access_token = create_token(user.id)
        refresh_token = create_refresh_token(user.id)

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'user': user.to_dict(),
            'access_token': access_token,
            'refresh_token': refresh_token
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """
    Refresh access token using refresh token

    Request Body:
        - refresh_token: string (required)

    Returns:
        200: New access token
        401: Invalid refresh token
    """
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token')

        if not refresh_token:
            return jsonify({'error': 'Refresh token required'}), 400

        # Decode refresh token
        payload = jwt.decode(refresh_token, config.JWT_SECRET_KEY, algorithms=['HS256'])

        if payload.get('type') != 'refresh':
            return jsonify({'error': 'Invalid token type'}), 401

        user_id = payload['user_id']

        # Generate new access token
        access_token = create_token(user_id)

        return jsonify({
            'success': True,
            'access_token': access_token
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Refresh token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid refresh token'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """
    Get current user info

    Returns:
        200: User data
        401: Not authenticated
    """
    return jsonify({
        'success': True,
        'user': current_user.to_dict()
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    """
    Logout (client should discard tokens)

    Returns:
        200: Logout successful
    """
    return jsonify({
        'success': True,
        'message': 'Logout successful'
    }), 200
'''

        return files

    def _generate_flask_middleware(self) -> Dict[str, str]:
        """Generate middleware files"""
        files = {}

        files["backend/middleware/__init__.py"] = '"""Middleware"""'

        files[
            "backend/middleware/error_handler.py"
        ] = '''"""
Global Error Handler Middleware
"""
from flask import jsonify
import traceback


class ErrorHandler:
    """Global error handler"""

    @staticmethod
    def handle_validation_error(error):
        """Handle validation errors"""
        return jsonify({
            'success': False,
            'error': 'Validation error',
            'details': str(error)
        }), 400

    @staticmethod
    def handle_database_error(error):
        """Handle database errors"""
        return jsonify({
            'success': False,
            'error': 'Database error',
            'message': 'An error occurred while accessing the database'
        }), 500

    @staticmethod
    def handle_generic_error(error):
        """Handle generic errors"""
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'message': str(error)
        }), 500
'''

        return files

    def _generate_flask_db_init(self) -> str:
        """Generate database initialization script"""
        return '''"""
Database Initialization Script
Creates all tables and optionally seeds data
"""
from app import create_app, db

def init_database():
    """Initialize database tables"""
    app = create_app()

    with app.app_context():
        # Drop all tables (use with caution!)
        # db.drop_all()

        # Create all tables
        db.create_all()

        print("✅ Database tables created successfully")

        # Optional: Seed data
        # seed_data()


def seed_data():
    """Seed initial data (optional)"""
    # Add your seed data here
    pass


if __name__ == '__main__':
    init_database()
'''

    # ========================================================================
    # FASTAPI BACKEND GENERATION
    # ========================================================================

    async def _generate_fastapi_backend(self) -> Dict[str, Any]:
        """Generate complete FastAPI backend"""
        print("[Backend Generator] FastAPI backend generation not yet implemented")
        print("[Backend Generator] ℹ️  Falling back to Flask generation")
        return await self._generate_flask_backend()

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def _has_authentication(self) -> bool:
        """Check if authentication is needed"""
        tables = self.plan.get("database_schema", {}).get("tables", [])
        return any(t["table_name"] == "users" for t in tables)

    def _generate_env_file(self) -> str:
        """Generate .env.example file"""
        schema = self.plan.get("database_schema", {})
        db_type = schema.get("database_type", "PostgreSQL")

        if "PostgreSQL" in db_type:
            db_url = "postgresql://user:password@localhost:5432/dbname"
        elif "MySQL" in db_type:
            db_url = "mysql+pymysql://user:password@localhost:3306/dbname"
        else:
            db_url = "sqlite:///app.db"

        return f"""# Flask Configuration
FLASK_ENV=development
SECRET_KEY=your-secret-key-change-in-production

# Database
DATABASE_URL={db_url}

# JWT
JWT_SECRET_KEY=your-jwt-secret-key

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:3001

# Server
PORT=5000
"""

    def _generate_backend_readme(self, framework: str) -> str:
        """Generate README for backend"""
        project_name = self.plan.get("name", "App")

        return f"""# {project_name} - Backend

{framework} backend API for {project_name}.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and update the values:

```bash
cp .env.example .env
```

### 3. Initialize Database

```bash
python init_db.py
```

### 4. Run the Server

**Development:**
```bash
python app.py
```

**Production:**
```bash
gunicorn -w 4 -b 0.0.0.0:5000 'app:create_app()'
```

## API Endpoints

### Health Check
- `GET /health` - Check if API is running

### Authentication
- `POST /api/auth/signup` - User registration
- `POST /api/auth/login` - User login
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - Logout

### Resources
{self._generate_endpoint_docs()}

## Project Structure

```
backend/
├── app.py              # Main application
├── config.py           # Configuration
├── requirements.txt    # Python dependencies
├── init_db.py         # Database initialization
├── models/            # Database models
├── routes/            # API routes
└── middleware/        # Middleware
```

## Testing

```bash
pytest tests/
```

## Deployment

See deployment guide in main README.
"""

    def _generate_endpoint_docs(self) -> str:
        """Generate endpoint documentation for README"""
        tables = self.plan.get("database_schema", {}).get("tables", [])
        docs = []

        for table in tables:
            if table["table_name"] == "users":
                continue

            table_name = table["table_name"]
            singular = self._singularize(table_name)

            docs.append(
                f"""
#### {table_name.title()}
- `GET /api/{table_name}` - Get all {table_name}
- `GET /api/{table_name}/<id>` - Get {singular} by ID
- `POST /api/{table_name}` - Create {singular}
- `PUT /api/{table_name}/<id>` - Update {singular}
- `DELETE /api/{table_name}/<id>` - Delete {singular}"""
            )

        return "\n".join(docs)

    def _sql_to_sqlalchemy_type(self, sql_type: str) -> str:
        """Convert SQL type to SQLAlchemy type"""
        sql_type_upper = sql_type.upper()

        if "SERIAL" in sql_type_upper:
            return "db.Integer"
        elif "INTEGER" in sql_type_upper or "INT" in sql_type_upper:
            return "db.Integer"
        elif "VARCHAR" in sql_type_upper:
            # Extract length
            match = re.search(r"VARCHAR\((\d+)\)", sql_type_upper)
            length = match.group(1) if match else "255"
            return f"db.String({length})"
        elif "TEXT" in sql_type_upper:
            return "db.Text"
        elif "BOOLEAN" in sql_type_upper or "BOOL" in sql_type_upper:
            return "db.Boolean"
        elif "TIMESTAMP" in sql_type_upper or "DATETIME" in sql_type_upper:
            return "db.DateTime"
        elif "DATE" in sql_type_upper:
            return "db.Date"
        elif "DECIMAL" in sql_type_upper or "NUMERIC" in sql_type_upper:
            return "db.Numeric"
        elif "FLOAT" in sql_type_upper or "REAL" in sql_type_upper:
            return "db.Float"
        elif "JSON" in sql_type_upper:
            return "db.JSON"
        else:
            return "db.String"

    def _to_class_name(self, table_name: str) -> str:
        """Convert table name to class name (PascalCase)"""
        # Remove trailing 's' for singular
        singular = self._singularize(table_name)
        # Convert to PascalCase
        return "".join(word.capitalize() for word in singular.split("_"))

    def _singularize(self, word: str) -> str:
        """Simple singularize (remove trailing 's')"""
        if word.endswith("ies"):
            return word[:-3] + "y"
        elif word.endswith("ses"):
            return word[:-2]
        elif word.endswith("s"):
            return word[:-1]
        return word

    def _get_file_type(self, path: str) -> str:
        """Get file type from path"""
        if path.endswith(".py"):
            return "python"
        elif path.endswith(".txt"):
            return "text"
        elif path.endswith(".md"):
            return "markdown"
        elif path.endswith(".env") or path.endswith(".example"):
            return "config"
        else:
            return "text"

    def _get_file_structure(self, files: Dict[str, str]) -> Dict:
        """Generate file structure tree"""
        structure = {}
        for path in files.keys():
            parts = path.split("/")
            current = structure
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        return structure

    async def save_to_database(self, db_connection=None) -> bool:
        """
        Save generated files to database

        Args:
            db_connection: Optional database connection

        Returns:
            bool: True if saved successfully
        """
        if not self.generated_files:
            print("[Backend Generator] ⚠️ No files to save")
            return False

        if db_connection is None and not DB_AVAILABLE:
            print("[Backend Generator] ⚠️ Database not available, skipping save")
            return False

        if db_connection is None:
            db_connection = db

        try:
            with db_connection.engine.connect() as conn:
                for file_data in self.generated_files:
                    # Insert file record
                    insert_query = """
                        INSERT INTO app_builder_files
                        (project_id, file_path, content, file_type, version, is_latest, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """

                    conn.execute(
                        db_connection.text(insert_query),
                        (
                            self.project_id,
                            file_data["file_path"],
                            file_data["content"],
                            file_data["file_type"],
                            1,  # version
                            True,  # is_latest
                        ),
                    )

                conn.commit()
                print(f"[Backend Generator] ✅ Saved {len(self.generated_files)} files to database")
                return True

        except Exception as e:
            print(f"[Backend Generator] ❌ Failed to save to database: {e}")
            return False


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 80)
    print("BACKEND GENERATOR TEST")
    print("=" * 80)

    # Mock plan
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
                        {"name": "username", "type": "VARCHAR(100) UNIQUE NOT NULL"},
                        {"name": "email", "type": "VARCHAR(255) UNIQUE NOT NULL"},
                        {"name": "password_hash", "type": "VARCHAR(255) NOT NULL"},
                    ],
                },
                {
                    "table_name": "tasks",
                    "columns": [
                        {"name": "id", "type": "SERIAL PRIMARY KEY"},
                        {
                            "name": "user_id",
                            "type": "INTEGER REFERENCES users(id) NOT NULL",
                        },
                        {"name": "title", "type": "VARCHAR(255) NOT NULL"},
                        {"name": "description", "type": "TEXT"},
                        {"name": "completed", "type": "BOOLEAN DEFAULT FALSE"},
                    ],
                },
            ],
        },
    }

    mock_architecture = {}

    async def test_backend():
        print("\nTest 1: Flask Backend Generation")
        print("-" * 80)

        generator = BackendGenerator(project_id=1, plan=mock_plan, architecture=mock_architecture)
        result = await generator.generate_backend()

        print(f"\n📊 Generation Summary:")
        print(f"  - Framework: {result['framework']}")
        print(f"  - Files Generated: {result['file_count']}")
        print(f"  - Generated At: {result['generated_at']}")

        print(f"\n📁 File Structure:")
        for file in result["files"][:10]:  # Show first 10 files
            print(f"  - {file['file_path']} ({file['file_type']})")

        if len(result["files"]) > 10:
            print(f"  ... and {len(result['files']) - 10} more files")

        print(f"\n✅ Backend Generator test complete")

    asyncio.run(test_backend())

    print("\n" + "=" * 80)
