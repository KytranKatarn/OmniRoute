"""
Rate Limiting Middleware for A.R.C.H.I.E. Platform
Prevents abuse and ensures fair resource usage

Purpose:
- Rate limit API requests per user/IP
- Different limits based on user role
- Protection against DDoS and abuse
- Graceful degradation

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import time
from typing import Optional, Dict, Tuple
from functools import wraps
from collections import defaultdict
import threading

try:
    from flask import request, jsonify, g
    from flask_login import current_user

    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    request = None
    current_user = None

try:
    from rbac import get_user_role, Role

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    Role = None

try:
    from logging_config import audit_log

    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False
    audit_log = None


# ============================================================================
# RATE LIMIT CONFIGURATION
# ============================================================================

# Rate limits per role (requests per minute)
RATE_LIMITS = {
    "PUBLIC": 20,  # Anonymous users: 20 req/min
    "USER": 60,  # Authenticated users: 60 req/min
    "PREMIUM": 120,  # Premium users: 120 req/min
    "ADMIN": 300,  # Admins: 300 req/min
    "SUPER_ADMIN": 1000,  # Super admins: 1000 req/min
}

# Window duration (seconds)
WINDOW_DURATION = 60  # 1 minute

# Cleanup interval (seconds)
CLEANUP_INTERVAL = 300  # 5 minutes


# ============================================================================
# IN-MEMORY RATE LIMITER
# ============================================================================


class InMemoryRateLimiter:
    """
    In-memory rate limiter using sliding window algorithm
    Thread-safe implementation
    """

    def __init__(self):
        self.requests: Dict[str, list] = defaultdict(list)
        self.lock = threading.RLock()
        self.last_cleanup = time.time()

    def _cleanup_old_requests(self, key: str, current_time: float):
        """Remove requests older than the window"""
        cutoff_time = current_time - WINDOW_DURATION
        self.requests[key] = [req_time for req_time in self.requests[key] if req_time > cutoff_time]

    def _cleanup_all(self):
        """Periodic cleanup of all keys"""
        current_time = time.time()

        with self.lock:
            # Only cleanup every CLEANUP_INTERVAL seconds
            if current_time - self.last_cleanup < CLEANUP_INTERVAL:
                return

            # Cleanup all keys
            cutoff_time = current_time - WINDOW_DURATION
            keys_to_delete = []

            for key, timestamps in list(self.requests.items()):
                # Remove old timestamps
                self.requests[key] = [t for t in timestamps if t > cutoff_time]

                # Mark empty keys for deletion
                if not self.requests[key]:
                    keys_to_delete.append(key)

            # Delete empty keys
            for key in keys_to_delete:
                del self.requests[key]

            self.last_cleanup = current_time

    def check_rate_limit(self, key: str, limit: int) -> Tuple[bool, int, int]:
        """
        Check if request is within rate limit

        Args:
            key: Unique identifier (user_id or IP)
            limit: Maximum requests allowed in window

        Returns:
            Tuple of (allowed: bool, current_count: int, limit: int)
        """
        current_time = time.time()

        with self.lock:
            # Cleanup old requests for this key
            self._cleanup_old_requests(key, current_time)

            # Periodic global cleanup
            self._cleanup_all()

            # Count requests in current window
            request_count = len(self.requests[key])

            # Check limit
            if request_count >= limit:
                return False, request_count, limit

            # Add current request
            self.requests[key].append(current_time)

            return True, request_count + 1, limit

    def reset(self, key: str):
        """Reset rate limit for a specific key"""
        with self.lock:
            if key in self.requests:
                del self.requests[key]

    def get_stats(self) -> Dict:
        """Get statistics about rate limiter"""
        with self.lock:
            return {
                "total_keys": len(self.requests),
                "total_requests": sum(len(timestamps) for timestamps in self.requests.values()),
                "window_duration": WINDOW_DURATION,
                "cleanup_interval": CLEANUP_INTERVAL,
            }


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


# ============================================================================
# RATE LIMIT HELPERS
# ============================================================================


def get_rate_limit_key() -> str:
    """
    Get unique key for rate limiting

    Returns:
        Unique key (user_id or IP address)
    """
    if FLASK_AVAILABLE and current_user and hasattr(current_user, "is_authenticated"):
        if current_user.is_authenticated:
            return f"user_{current_user.id}"

    # Fall back to IP address
    if FLASK_AVAILABLE and request:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        # Take first IP if multiple (proxy chain)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        return f"ip_{ip}"

    return "unknown"


def get_user_rate_limit() -> int:
    """
    Get rate limit for current user based on role

    Returns:
        Rate limit (requests per minute)
    """
    if not RBAC_AVAILABLE or not FLASK_AVAILABLE:
        return RATE_LIMITS["PUBLIC"]

    if not current_user or not hasattr(current_user, "is_authenticated"):
        return RATE_LIMITS["PUBLIC"]

    if not current_user.is_authenticated:
        return RATE_LIMITS["PUBLIC"]

    # Get user role
    try:
        role = get_user_role(current_user)
        return RATE_LIMITS.get(role.name, RATE_LIMITS["USER"])
    except Exception:
        return RATE_LIMITS["USER"]


# ============================================================================
# FLASK DECORATORS
# ============================================================================


def rate_limit(limit: Optional[int] = None):
    """
    Decorator to apply rate limiting to a route

    Args:
        limit: Custom rate limit (requests per minute). If None, uses role-based limit.

    Usage:
        @app.route('/api/resource')
        @rate_limit()  # Uses role-based limit
        def get_resource():
            ...

        @app.route('/api/expensive')
        @rate_limit(limit=10)  # Custom limit: 10 req/min
        def expensive_operation():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get rate limit
            if limit is not None:
                user_limit = limit
            else:
                user_limit = get_user_rate_limit()

            # Get rate limit key
            key = get_rate_limit_key()

            # Check rate limit
            allowed, current_count, max_limit = rate_limiter.check_rate_limit(key, user_limit)

            # Add rate limit headers
            if FLASK_AVAILABLE and hasattr(g, "request_id"):
                g.rate_limit_limit = max_limit
                g.rate_limit_remaining = max(0, max_limit - current_count)
                g.rate_limit_reset = int(time.time()) + WINDOW_DURATION

            if not allowed:
                # Log rate limit exceeded
                if LOGGING_AVAILABLE and audit_log:
                    audit_log(
                        "RATE_LIMIT_EXCEEDED",
                        {
                            "key": key,
                            "limit": user_limit,
                            "endpoint": (request.endpoint if FLASK_AVAILABLE and request else "unknown"),
                        },
                        success=False,
                    )

                # Return 429 Too Many Requests
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Rate limit exceeded",
                            "limit": max_limit,
                            "window_seconds": WINDOW_DURATION,
                            "retry_after": WINDOW_DURATION,
                        }
                    ),
                    429,
                )

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def rate_limit_exempt(f):
    """
    Decorator to exempt a route from rate limiting

    Usage:
        @app.route('/health')
        @rate_limit_exempt
        def health_check():
            return {'status': 'healthy'}
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)

    # Mark function as exempt
    decorated_function._rate_limit_exempt = True
    return decorated_function


# ============================================================================
# FLASK MIDDLEWARE
# ============================================================================


def init_rate_limiting(app):
    """
    Initialize rate limiting for Flask application

    Args:
        app: Flask application instance

    Usage:
        from rate_limiting import init_rate_limiting
        init_rate_limiting(app)
    """
    if not FLASK_AVAILABLE:
        return

    @app.after_request
    def add_rate_limit_headers(response):
        """Add rate limit headers to response"""
        # Check if endpoint is exempt
        endpoint_func = app.view_functions.get(request.endpoint)
        if endpoint_func and hasattr(endpoint_func, "_rate_limit_exempt"):
            return response

        # Add headers if rate limit info is available
        if hasattr(g, "rate_limit_limit"):
            response.headers["X-RateLimit-Limit"] = str(g.rate_limit_limit)
            response.headers["X-RateLimit-Remaining"] = str(g.rate_limit_remaining)
            response.headers["X-RateLimit-Reset"] = str(g.rate_limit_reset)

        return response

    # Store rate limiter in app config
    app.config["RATE_LIMITER"] = rate_limiter

    print(f"[Rate Limiting] Initialized with limits: {RATE_LIMITS}")


# ============================================================================
# ADMIN API - Rate Limit Management
# ============================================================================


def get_rate_limit_stats() -> Dict:
    """Get current rate limiter statistics"""
    stats = rate_limiter.get_stats()
    stats["rate_limits"] = RATE_LIMITS
    stats["window_duration"] = WINDOW_DURATION
    return stats


def reset_rate_limit(key: str) -> bool:
    """
    Reset rate limit for a specific key (admin only)

    Args:
        key: Rate limit key to reset

    Returns:
        True if reset successful
    """
    try:
        rate_limiter.reset(key)
        return True
    except Exception:
        return False


# ============================================================================
# TESTING & EXAMPLES
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("RATE LIMITING TEST")
    print("=" * 80)

    # Test rate limiter directly
    limiter = InMemoryRateLimiter()

    # Test with 5 req/min limit
    test_key = "test_user_123"
    limit = 5

    print(f"\nTesting rate limiter with key: {test_key}, limit: {limit}/min")

    # Make requests
    for i in range(7):
        allowed, count, max_limit = limiter.check_rate_limit(test_key, limit)

        if allowed:
            print(f"  Request {i+1}: ✅ ALLOWED ({count}/{max_limit})")
        else:
            print(f"  Request {i+1}: ❌ DENIED ({count}/{max_limit})")

    # Test cleanup
    print("\nTesting cleanup...")
    stats = limiter.get_stats()
    print(f"  Stats: {stats}")

    # Test reset
    print(f"\nResetting rate limit for {test_key}...")
    limiter.reset(test_key)
    allowed, count, max_limit = limiter.check_rate_limit(test_key, limit)
    print(f"  After reset: ✅ ALLOWED ({count}/{max_limit})")

    # Test rate limits by role
    print("\n📊 Rate Limits by Role:")
    for role, limit in RATE_LIMITS.items():
        print(f"  {role:12} → {limit:4} requests/min")

    print("\n" + "=" * 80)
    print("✅ Rate limiting test complete")
    print("=" * 80)
