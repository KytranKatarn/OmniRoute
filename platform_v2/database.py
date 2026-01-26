"""
Database Connection Helper
Provides get_db() function for scripts and modules outside the Flask app context.
"""

import psycopg2
import os


def get_db():
    """
    Get a database connection
    Uses environment variables for configuration
    Returns standard cursor (tuples) for compatibility with existing code
    """
    conn = psycopg2.connect(
        host=os.environ.get('DB_HOST', 'archie_database'),
        port=os.environ.get('DB_PORT', '5432'),
        database=os.environ.get('DB_NAME', 'archie'),
        user=os.environ.get('DB_USER', 'archie'),
        password=os.environ.get('DB_PASSWORD', '')
    )
    return conn
