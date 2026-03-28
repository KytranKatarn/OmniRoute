import os

# Force test DB connection to KBS's own postgres container
os.environ["KBS_DB_HOST"] = "kbs-postgres"
os.environ["KBS_DB_NAME"] = "kbs"
os.environ["KBS_DB_USER"] = "kbs"
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("KBS_DB_PASSWORD", ""))
