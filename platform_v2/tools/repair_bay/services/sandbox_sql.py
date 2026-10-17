"""Safe identifier composition for sandbox schema removal (never execute here)."""

import re

from psycopg2 import sql


def drop_sandbox_schema_statement(schema_name: str) -> sql.Composed:
    """Refuse non-sandbox namespaces and quote the entire identifier, not SQL text."""
    if not isinstance(schema_name, str) or not re.fullmatch(r"sandbox(?:_[A-Za-z0-9_]+)?", schema_name):
        raise ValueError("Refusing to drop a non-sandbox schema")
    if len(schema_name.encode("utf-8")) > 63:
        raise ValueError("Sandbox schema identifier exceeds PostgreSQL's limit")
    return sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
