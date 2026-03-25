"""Application configuration."""
import os


class Config:
    SECRET_KEY = os.environ.get("KSM_SECRET_KEY", "change-me-in-production")
    # Use /var/lib for system installs, ~/.kytran-server-manager for user installs
    _default_data = os.environ.get(
        "KSM_DATA_DIR",
        "/var/lib/kytran-server-manager" if os.getuid() == 0
        else os.path.join(os.path.expanduser("~"), ".kytran-server-manager")
    )
    DATA_DIR = _default_data
    DB_PATH = os.path.join(DATA_DIR, "data.db")
    THEME = os.environ.get("KSM_THEME", "kytran")
    HOST = os.environ.get("KSM_HOST", "0.0.0.0")
    PORT = int(os.environ.get("KSM_PORT", "8080"))
    DEBUG = os.environ.get("KSM_DEBUG", "false").lower() == "true"
    BASE_DIR = os.environ.get("KSM_BASE_DIR", "/")
