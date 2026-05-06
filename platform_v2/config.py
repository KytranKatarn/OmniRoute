"""
A.R.C.H.I.E. Platform Configuration
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Base configuration"""

    # App
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production"),
    )
    DEBUG = os.getenv("FLASK_ENV") == "development"

    # Deployment Mode: 'hub' for ARCHIE Hub, 'business_node' for business instances
    DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "hub")

    # Database
    DB_HOST = os.getenv("DB_HOST", "archie_database")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "archie")
    DB_USER = os.getenv("DB_USER", "archie")

    @staticmethod
    def _read_db_password():
        secret_file = os.getenv("DB_PASSWORD_FILE", "/run/secrets/db_password")
        try:
            with open(secret_file, "r") as f:
                pw = f.read().strip()
                if pw:
                    return pw
        except (FileNotFoundError, PermissionError):
            pass
        return os.getenv("DB_PASSWORD", "")

    DB_PASSWORD = _read_db_password.__func__()

    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG

    # Ollama AI
    # Local Ollama on ARCHIE host (host.docker.internal from inside container)
    OLLAMA_PRIMARY = os.getenv("OLLAMA_PRIMARY", "http://host.docker.internal:11434")

    # Code Server
    CODE_SERVER_URL = os.getenv("CODE_SERVER_URL", "http://192.168.1.200:8080")

    # Session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = (
        os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    )  # NPM proxy handles HTTPS termination — false is correct for internal HTTP access
    PERMANENT_SESSION_LIFETIME = 3600 * 24 * 7  # 7 days

    # A.R.C.H.I.E. Personality
    ARCHIE_NAME = "A.R.C.H.I.E."
    ARCHIE_VERSION = "2.0"
    ARCHIE_ROLE = "AI Business Partner & Assistant"
