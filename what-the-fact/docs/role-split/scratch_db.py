"""Shared scratch-PostgreSQL setup for the role workload harnesses (NOT for production).

`with scratch(schema_dump, bootstrap_sql, login_roles) as (port, op)`: a new pgvector/pg16 container bound to
127.0.0.1 on an ephemeral port (trust auth, synthetic data only), loaded with the reviewed schema, migration 107
and the rendered restricted grants; `op()` returns an autocommit operator connection. Removed on exit.
"""
import contextlib
import json
import subprocess
import time
import uuid
from pathlib import Path

import psycopg2

from render_grants import HERE, render

DB = "wtf_role_rehearsal"


def _sh(argv, check=True):
    return subprocess.run(argv, text=True, capture_output=True, check=check)


@contextlib.contextmanager
def scratch(schema_path, bootstrap_path, login_roles):
    schema = "\n".join(l for l in Path(schema_path).read_text().splitlines() if not l.startswith("\\"))
    bootstrap = Path(bootstrap_path).read_text()
    manifest = json.loads((HERE / "permissions.json").read_text())
    name = "wtf-workload-" + uuid.uuid4().hex[:12]
    try:
        _sh(["docker", "run", "-d", "--name", name, "--memory", "768m", "--cpus", "1", "-p", "127.0.0.1::5432",
             "--tmpfs", "/var/lib/postgresql/data:rw,size=512m", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
             "-e", f"POSTGRES_DB={DB}", "pgvector/pgvector:pg16"])
        port = _sh(["docker", "port", name, "5432/tcp"]).stdout.split(":")[-1].strip()

        def op():
            c = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", dbname=DB)
            c.autocommit = True
            return c

        for _ in range(60):
            try:
                op().close()
                break
            except psycopg2.OperationalError:
                time.sleep(1)
        else:
            raise RuntimeError("scratch db not ready")
        o = op()
        cur = o.cursor()
        cur.execute(schema)
        cur.execute("BEGIN;\n" + bootstrap + "\nCOMMIT;")
        cur.execute(render(manifest))
        for r in login_roles:
            cur.execute(f'ALTER ROLE "{r}" LOGIN;')
        o.close()
        yield port, op
    finally:
        _sh(["docker", "rm", "-f", name], check=False)


def url(port, role):
    return f"postgresql+psycopg2://{role}@127.0.0.1:{port}/{DB}"
