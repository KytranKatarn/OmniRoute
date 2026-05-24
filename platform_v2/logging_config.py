"""
Centralized JSON Logging Configuration for A.R.C.H.I.E. Platform
Provides structured logging with 30-day retention

Purpose:
- JSON-formatted logs for easy parsing and analysis
- Automatic log rotation with 30-day retention
- Context injection (user_id, request_id, module)
- Separate files for different log levels
- Integration with Flask request context

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import logging
import logging.handlers
import json
import os
from datetime import datetime
from pathlib import Path
import traceback
from typing import Any, Dict, Optional

try:
    from flask import has_request_context, request, g
    from flask_login import current_user

    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

    def has_request_context():
        return False

    request = None
    current_user = None


# ============================================================================
# LOGGING DIRECTORIES
# ============================================================================

_default_log_dir = Path(os.getenv("ARCHIE_LOG_DIR", "/mnt/archie_brain/logs"))
try:
    _default_log_dir.mkdir(exist_ok=True, parents=True)
    LOG_DIR = _default_log_dir
except OSError:
    # Fallback for read-only environments (e.g. sandbox container)
    LOG_DIR = Path("/tmp/archie_logs")
    LOG_DIR.mkdir(exist_ok=True, parents=True)

# Separate log files by level
LOG_FILES = {
    "debug": LOG_DIR / "debug.log",
    "info": LOG_DIR / "info.log",
    "warning": LOG_DIR / "warning.log",
    "error": LOG_DIR / "error.log",
    "critical": LOG_DIR / "critical.log",
    "audit": LOG_DIR / "audit.log",  # Special audit log
}


# ============================================================================
# JSON FORMATTER
# ============================================================================


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter with context injection
    Outputs structured JSON logs with metadata
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        # Base log data
        # Use timezone-aware UTC timestamp
        from datetime import timezone

        timestamp = datetime.now(timezone.utc).isoformat()

        log_data = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Add Flask request context if available
        if FLASK_AVAILABLE and has_request_context():
            try:
                log_data["request"] = {
                    "method": request.method if request else None,
                    "path": request.path if request else None,
                    "endpoint": request.endpoint if request else None,
                    "remote_addr": request.remote_addr if request else None,
                    "user_agent": (request.headers.get("User-Agent") if request else None),
                }

                # Add request ID if available
                if hasattr(g, "request_id"):
                    log_data["request_id"] = g.request_id

                # Add user info if authenticated
                if current_user and hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
                    log_data["user"] = {
                        "id": current_user.id if hasattr(current_user, "id") else None,
                        "username": (current_user.username if hasattr(current_user, "username") else None),
                    }
            except Exception:
                # Don't fail logging if context extraction fails
                pass

        # Add custom fields from record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                log_data[key] = value

        return json.dumps(log_data, default=str)


# ============================================================================
# LOGGING SETUP
# ============================================================================


def setup_logging(app_name: str = "archie_platform", debug: bool = False) -> logging.Logger:
    """
    Setup centralized logging for the application

    Args:
        app_name: Name of the application (for logger name)
        debug: Enable debug level logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(app_name)

    # Set base level
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Remove existing handlers to avoid duplicates
    logger.handlers = []

    # JSON Formatter
    json_formatter = JSONFormatter()

    # Console handler (human-readable for development)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handlers with rotation (30-day retention)
    # Rotate logs daily, keep 30 days
    for level_name, log_file in LOG_FILES.items():
        if level_name == "audit":
            # Audit log gets all levels
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_file,
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
        else:
            # Regular logs by level
            level = getattr(logging, level_name.upper())
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_file,
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            # Only log this level and above
            file_handler.addFilter(lambda record, lvl=level: record.levelno >= lvl)

        file_handler.setFormatter(json_formatter)
        logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    # -----------------------------------------------------------------------
    # Silence noisy third-party loggers
    # httpx/httpcore: Telegram long-poll logs every ~11s at INFO — mute to WARNING
    # apscheduler: scheduler heartbeat + executor noise — mute to WARNING
    # -----------------------------------------------------------------------
    _NOISY_LOGGERS = [
        "httpx",
        "httpcore",
        "httpcore.http11",
        "httpcore.connection",
        "apscheduler.scheduler",
        "apscheduler.executors.default",
        "apscheduler.executors.asyncio",
    ]
    for _name in _NOISY_LOGGERS:
        logging.getLogger(_name).setLevel(logging.WARNING)

    return logger


# ============================================================================
# AUDIT LOGGING
# ============================================================================


def audit_log(
    action: str,
    details: Dict[str, Any],
    user_id: Optional[int] = None,
    success: bool = True,
    metadata: Optional[Dict] = None,
):
    """
    Create an audit log entry

    Args:
        action: Action being audited (e.g., "USER_LOGIN", "PERMISSION_CHECK")
        details: Dictionary of details about the action
        user_id: User ID performing the action (if applicable)
        success: Whether the action succeeded
        metadata: Additional metadata
    """
    logger = logging.getLogger("archie_platform.audit")

    # Get user info from current_user if not provided
    if user_id is None and FLASK_AVAILABLE and current_user:
        if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
            user_id = current_user.id if hasattr(current_user, "id") else None

    audit_entry = {
        "action": action,
        "details": details,
        "user_id": user_id,
        "success": success,
        "metadata": metadata or {},
    }

    logger.info(
        f"AUDIT: {action}",
        extra={
            "audit": True,
            "audit_action": action,
            "audit_details": details,
            "audit_user_id": user_id,
            "audit_success": success,
            "audit_metadata": metadata or {},
        },
    )


# ============================================================================
# PERFORMANCE LOGGING
# ============================================================================


def log_performance(operation: str, duration_ms: float, metadata: Optional[Dict] = None):
    """
    Log performance metrics

    Args:
        operation: Name of the operation
        duration_ms: Duration in milliseconds
        metadata: Additional metadata
    """
    logger = logging.getLogger("archie_platform.performance")

    logger.info(
        f"PERFORMANCE: {operation} took {duration_ms:.2f}ms",
        extra={
            "performance": True,
            "operation": operation,
            "duration_ms": duration_ms,
            "metadata": metadata or {},
        },
    )


# ============================================================================
# CONTEXTUAL LOGGING HELPERS
# ============================================================================


class LogContext:
    """Context manager for adding extra logging context"""

    def __init__(self, **kwargs):
        self.context = kwargs
        self.old_factory = None

    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.setLogRecordFactory(self.old_factory)


# ============================================================================
# FLASK INTEGRATION
# ============================================================================


def init_flask_logging(app):
    """
    Initialize logging for Flask application

    Args:
        app: Flask application instance
    """
    import uuid

    # Setup logger
    logger = setup_logging("archie_platform", debug=app.debug)
    app.logger = logger

    @app.before_request
    def before_request_logging():
        """Add request ID and log request start"""
        # Generate unique request ID
        g.request_id = str(uuid.uuid4())

        # Log request start
        logger.info(
            f"REQUEST START: {request.method} {request.path}",
            extra={"request_id": g.request_id, "event": "request_start"},
        )

    @app.after_request
    def after_request_logging(response):
        """Log request completion"""
        if hasattr(g, "request_id"):
            logger.info(
                f"REQUEST END: {request.method} {request.path} - {response.status_code}",
                extra={
                    "request_id": g.request_id,
                    "event": "request_end",
                    "status_code": response.status_code,
                },
            )
        return response

    @app.teardown_request
    def teardown_request_logging(exception=None):
        """Log request errors"""
        if exception:
            logger.error(
                f"REQUEST ERROR: {request.method} {request.path}",
                exc_info=exception,
                extra={
                    "request_id": g.get("request_id", "unknown"),
                    "event": "request_error",
                },
            )

    return logger


# ============================================================================
# TESTING & EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Test logging setup
    print("=" * 80)
    print("LOGGING CONFIGURATION TEST")
    print("=" * 80)

    # Setup logger
    logger = setup_logging("test_app", debug=True)

    # Test different log levels
    logger.debug("Debug message - detailed information")
    logger.info("Info message - general information")
    logger.warning("Warning message - something unexpected")
    logger.error("Error message - something failed")
    logger.critical("Critical message - system failure")

    # Test exception logging
    try:
        1 / 0
    except Exception:
        logger.exception("Exception occurred during division")

    # Test audit logging
    audit_log(
        action="TEST_ACTION",
        details={"test": "value", "count": 42},
        user_id=1,
        success=True,
        metadata={"source": "test"},
    )

    # Test performance logging
    log_performance(
        operation="database_query",
        duration_ms=125.5,
        metadata={"query": "SELECT * FROM users", "rows": 100},
    )

    # Test context manager
    with LogContext(module="test_module", version="1.0"):
        logger.info("Message with context")

    print(f"\n✅ Logs written to: {LOG_DIR}")
    print(f"✅ Log files created: {list(LOG_FILES.keys())}")
    print("\n" + "=" * 80)
