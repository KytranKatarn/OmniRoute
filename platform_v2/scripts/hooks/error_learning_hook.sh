#!/bin/bash
# Error Learning Hook - Auto-capture errors to A.R.C.H.I.E. mistake_learned
# Analyzes command failures and stores patterns for future prevention

PLATFORM_URL="http://localhost:3000"
LOG_FILE="/mnt/archie_brain/logs/error_learning.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Input: error output from failed command
ERROR_OUTPUT="${1:-}"
COMMAND="${2:-}"
EXIT_CODE="${3:-1}"

if [ -z "$ERROR_OUTPUT" ]; then
    exit 0
fi

log "Error detected in command: $COMMAND (exit: $EXIT_CODE)"

# Analyze error and create mistake entry
analyze_and_learn() {
    python3 << 'PYTHON_SCRIPT'
import json
import sys
import os
import re
import requests
from datetime import datetime

ERROR_OUTPUT = os.environ.get('ERROR_OUTPUT', '')
COMMAND = os.environ.get('COMMAND', '')
PLATFORM_URL = "http://localhost:3000"

# Common error patterns and their solutions
ERROR_PATTERNS = {
    r"could not translate host name.*archie_database": {
        "pattern": "Docker hostname resolution",
        "solution": "Run command inside Docker container: docker exec archie_platform python3 script.py",
        "category": "docker"
    },
    r"connection.*refused.*5432|connection to server.*failed": {
        "pattern": "PostgreSQL connection refused",
        "solution": "Check DB_HOST - use 192.168.1.200 instead of localhost for external access",
        "category": "database"
    },
    r"TemplateNotFound": {
        "pattern": "Flask template not found",
        "solution": "Include 'tools/' prefix in template path: render_template('tools/module.html')",
        "category": "flask"
    },
    r"ModuleNotFoundError|ImportError": {
        "pattern": "Python import error",
        "solution": "Check if running in correct environment (Docker vs host), verify package installed",
        "category": "python"
    },
    r"PermissionError|Permission denied": {
        "pattern": "File permission error",
        "solution": "Check file permissions with ls -la, use chmod if needed",
        "category": "filesystem"
    },
    r"column.*does not exist": {
        "pattern": "PostgreSQL column missing",
        "solution": "Check database schema, run migration if needed",
        "category": "database"
    },
    r"relation.*does not exist": {
        "pattern": "PostgreSQL table missing",
        "solution": "Table not created - check migrations in database/migrations/",
        "category": "database"
    },
    r"SyntaxError|IndentationError": {
        "pattern": "Python syntax error",
        "solution": "Check code syntax, especially indentation and brackets",
        "category": "python"
    },
    r"KeyError|IndexError": {
        "pattern": "Python key/index error",
        "solution": "Add defensive checks: dict.get() or try/except, verify data structure",
        "category": "python"
    },
    r"TypeError.*NoneType": {
        "pattern": "NoneType error",
        "solution": "Add null check before operation, trace where None is coming from",
        "category": "python"
    },
    r"ENOENT|No such file or directory": {
        "pattern": "File not found",
        "solution": "Verify file path exists, check for typos, use absolute paths",
        "category": "filesystem"
    },
    r"ECONNREFUSED|Connection refused": {
        "pattern": "Service connection refused",
        "solution": "Check if service is running: docker ps, systemctl status",
        "category": "network"
    },
    r"401.*Unauthorized|403.*Forbidden": {
        "pattern": "Authentication/authorization error",
        "solution": "Check credentials, API keys, or user permissions",
        "category": "auth"
    },
    r"rate limit|429": {
        "pattern": "Rate limit exceeded",
        "solution": "Add delay between requests, implement backoff strategy",
        "category": "api"
    },
    r"timeout|timed out": {
        "pattern": "Operation timeout",
        "solution": "Increase timeout value, check network, optimize query",
        "category": "performance"
    }
}

def analyze_error():
    matched_pattern = None
    matched_info = None

    for pattern, info in ERROR_PATTERNS.items():
        if re.search(pattern, ERROR_OUTPUT, re.IGNORECASE):
            matched_pattern = pattern
            matched_info = info
            break

    if not matched_info:
        # Generic error
        matched_info = {
            "pattern": "Unknown error",
            "solution": "Review error output and check logs",
            "category": "unknown"
        }

    return matched_info

def store_mistake(error_info):
    """Store mistake in knowledge_base via API"""

    # Create mistake entry
    mistake_data = {
        "title": f"Error: {error_info['pattern']}",
        "content": f"""## Error Pattern
{error_info['pattern']}

## Command
```
{COMMAND[:500] if COMMAND else 'N/A'}
```

## Error Output
```
{ERROR_OUTPUT[:1000]}
```

## Solution
{error_info['solution']}

## Category
{error_info['category']}

## Learned
{datetime.now().isoformat()}
""",
        "entry_type": "mistake_learned",
        "importance": 0.9,
        "tags": ["error", error_info['category'], "auto-learned"],
        "source_type": "error_hook",
        "source_id": f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    }

    try:
        # Try API first
        response = requests.post(
            f"{PLATFORM_URL}/tools/consciousness/api/knowledge/add",
            json=mistake_data,
            timeout=5
        )
        if response.status_code == 200:
            print(f"Learned: {error_info['pattern']}")
            return True
    except:
        pass

    # Fallback: log for manual review
    print(f"Pattern detected: {error_info['pattern']} - {error_info['solution']}")
    return False

# Main execution
error_info = analyze_error()
store_mistake(error_info)
PYTHON_SCRIPT
}

export ERROR_OUTPUT
export COMMAND

analyze_and_learn

log "Error analysis complete"
