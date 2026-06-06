#!/bin/sh
# Export the read-only DB password from the mounted secret into DB_PASSWORD so that
# both credential paths work (database._get_db_password() reads DB_PASSWORD_FILE first,
# but the knowledge handlers may read DB_PASSWORD directly). DB_USER=codex_ro and
# DB_HOST=archie_database are set in the compose environment.
set -e
if [ -f /run/secrets/codex_db_ro ]; then
  DB_PASSWORD="$(cat /run/secrets/codex_db_ro)"
  export DB_PASSWORD
fi
exec uvicorn gateway:app --host 0.0.0.0 --port 7800
