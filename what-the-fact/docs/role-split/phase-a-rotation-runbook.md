# Phase A runbook — rotate the exposed `wtfuser` password (containment)

**Status: written, NOT executed.** Operator-run (the owner, in a terminal on the hub). Nothing here changes the role split;
that is Phase B. This only replaces a password that was exposed on 2026-10-20 with a new one, everywhere it is used.

**Why now:** `wtfuser` is a PostgreSQL superuser with bypass-RLS that owns every table, and its password was printed into an
AI-session transcript. The DB port is published on the mesh (`100.64.0.10:5434`). Phase B (per-service least-privilege roles)
needs more work (production grants migration, per-service secret injection, the `upgrade-tier2` decision), so contain first.

**Cost:** one short gap (about 1–2 minutes) in which *new* DB connections fail, then 10–30 s per service while it is recreated.
Existing pooled connections keep working until the old sessions are terminated at the end.

## Ground rules (every step)

- The new password exists only in a shell variable and in the two target files. **Never** `echo` it, `set -x`, put it in
  `argv`, a commit, a PR, a chat, or a log. Failures print an exception *class name*, never the connection string
  (psycopg2 errors embed the whole DSN — that is how the old password leaked).
- The password is set on the server as a **SCRAM verifier** computed on the hub (`scram_verifier.py`), so the plaintext never
  reaches PostgreSQL's statement log. Round trip proven 2026-10-20 on PG16 with `POSTGRES_HOST_AUTH_METHOD=md5` (production's
  setting): verifier logs in over TCP, a wrong password is rejected, plaintext absent from the server log.
- Use **`up -d --force-recreate`**, never `restart`: `restart` does not re-read `env_file` (KB #268829).
- **Roll forward only.** The old password is compromised: never restore it as a "rollback".
- Do **not** run on a Sunday (the weekly Elections Canada refresh) or during a scheduled hub job (Step 1a).

```bash
# Run this block once per terminal session, BEFORE anything else.
set +o history 2>/dev/null; umask 077
KEY="$HOME/.ssh/id_ed25519"; CIT="root@100.64.0.10"
DIR=/opt/archie-products/what-the-fact; PGC=what-the-fact-wtf-postgres-1
SSH() { ssh -i "$KEY" -o BatchMode=yes "$CIT" "$@"; }
cd /mnt/archie_brain/what-the-fact/docs/role-split    # needs this PR merged and `git pull --ff-only` on the hub
```

## Step 1 — Pre-flight (read-only; abort on any surprise)

```bash
# 1a. Quiet window? No WTF-touching hub job due in the next ~20 min; not Sunday.
date +%A; crontab -l 2>/dev/null | grep -Ei 'senate|lobby|gic|wtf|elections' ; systemctl list-timers --all 2>/dev/null | grep -Ei 'senate|lobby|gic|wtf'

# 1b. The URL shape on Citadel (password masked) — must show exactly ONE wtfuser line.
SSH "grep -c '^WTF_DATABASE_URL=' $DIR/.env; grep '^WTF_DATABASE_URL=' $DIR/.env | sed -E 's#(://[^:]+:)[^@]*@#\1***@#'"

# 1c. Where the Docker secret file really is (path only, not contents).
SSH "cd $DIR && docker compose config 2>/dev/null | sed -n '/^secrets:/,/^[a-z]/p'"
#     -> note the `file:` path. If it is not $DIR/secrets/wtf_db_password.txt, set SECRET_FILE to it in Step 3.

# 1d. Who is connected (counts only) and what is published.
SSH "docker exec $PGC psql -U wtfuser -d wtf -Atc \"select coalesce(client_addr::text,'local-socket'), count(*) from pg_stat_activity where usename='wtfuser' group by 1 order by 2 desc\""
SSH "ss -ltn | grep 5434; ufw status 2>/dev/null | grep 5434"
#     -> 5434 must be bound to the mesh IP 100.64.0.10, not 0.0.0.0. If it is not, STOP and fix that first.

# 1e. A fresh logical backup, verified readable (stays on Citadel, root-only). Check disk first.
SSH "df -h /root | tail -1"
SSH "set -e; umask 077; mkdir -p /root/backups; F=/root/backups/wtf-pre-rotation-\$(date +%Y%m%d-%H%M).dump; docker exec $PGC pg_dump -U wtfuser -d wtf -Fc > \$F; ls -l \$F; docker exec -i $PGC pg_restore --list < \$F | head -3"

# 1f. Fingerprint of the CURRENT stored hash (the hash, not the password) — compared after.
SSH "docker exec $PGC psql -U wtfuser -d wtf -Atc \"select left(md5(rolpassword),12) from pg_authid where rolname='wtfuser'\"" | tee /dev/shm/wtf-fp-before >/dev/null; cat /dev/shm/wtf-fp-before
```

**Go / no-go:** exactly one URL line; 5434 mesh-only; backup file exists and lists tables; window is quiet. Otherwise stop.

## Step 2 — Generate the password and the verifier (hub, in memory)

```bash
PW="$(openssl rand -hex 24)"                       # 48 hex chars: URL-safe, SASLprep-safe
VERIFIER="$(printf '%s' "$PW" | python3 scram_verifier.py)"   # prints SCRAM-SHA-256$... only
case "$VERIFIER" in SCRAM-SHA-256\$4096:*) echo "verifier ok";; *) echo "verifier BAD"; false;; esac
```

## Step 3 — Stage the new password into the config files (does not affect running services yet)

Back up the two files first (they hold the OLD password; deleted in Step 8).

```bash
SECRET_FILE="$DIR/secrets/wtf_db_password.txt"     # <- the path from Step 1c
SSH "set -e; umask 077; cd $DIR; cp -p .env .env.bak-pre-rotation; cp -p '$SECRET_FILE' '$SECRET_FILE.bak-pre-rotation'"

# The password travels on STDIN; the code (shipped base64, so no shell-quoting hazards) contains no secret.
cat > /dev/shm/wtf_remote_edit.py <<'PY'
import os, re, sys
pw = sys.stdin.readline().strip()
assert re.fullmatch(r"[0-9a-f]{48}", pw), "bad password shape"
def atomic_write(path, text):
    st = os.stat(path); tmp = path + ".tmp"
    with open(tmp, "w") as f: f.write(text)
    os.chmod(tmp, st.st_mode & 0o7777); os.chown(tmp, st.st_uid, st.st_gid); os.replace(tmp, path)
env = os.environ["DIR"] + "/.env"
new, n = re.subn(r"^(WTF_DATABASE_URL=[^\n]*?://wtfuser:)[^@\n]*(@)", lambda m: m.group(1) + pw + m.group(2),
                 open(env).read(), flags=re.M)
assert n == 1, "expected exactly one WTF_DATABASE_URL wtfuser line, got %d" % n
atomic_write(env, new)
atomic_write(os.environ["SECRET_FILE"], pw)
print("staged")
PY
B64="$(base64 -w0 /dev/shm/wtf_remote_edit.py)"
printf '%s\n' "$PW" | SSH "DIR='$DIR' SECRET_FILE='$SECRET_FILE' python3 -c \"import base64;exec(base64.b64decode('$B64'))\""
shred -u /dev/shm/wtf_remote_edit.py
# Check the shape WITHOUT printing the password:
SSH "grep '^WTF_DATABASE_URL=' $DIR/.env | sed -E 's#(://[^:]+:)[^@]*@#\1***@#'; wc -c < '$SECRET_FILE'"   # expect 48
```

If Step 3 fails, nothing has changed on the server: restore with `SSH "cd $DIR && mv .env.bak-pre-rotation .env && mv '$SECRET_FILE.bak-pre-rotation' '$SECRET_FILE'"` and stop.

## Step 4 — Change the role password (the gap starts here)

```bash
T0="$(SSH "docker exec $PGC psql -U wtfuser -d wtf -Atc 'select now()'")"; echo "T0=$T0"
printf "ALTER ROLE wtfuser PASSWORD '%s';\n" "$VERIFIER" | SSH "docker exec -i $PGC psql -U wtfuser -d wtf -v ON_ERROR_STOP=1"
#     -> prints: ALTER ROLE
SSH "docker exec $PGC psql -U wtfuser -d wtf -Atc \"select left(md5(rolpassword),12), rolpassword like 'SCRAM-SHA-256\$%' from pg_authid where rolname='wtfuser'\""
#     -> first field must DIFFER from /dev/shm/wtf-fp-before; second must be t
```

## Step 5 — Recreate the four services onto the new password (end of the gap)

Smallest blast radius first; `wtf-ingest` last (an interrupted run is safe — ingest is idempotent).

```bash
for S in wtf-ingest-api wtf-tech wtf-consumer wtf-ingest; do
  echo "== $S"; SSH "cd $DIR && docker compose up -d --no-deps --force-recreate $S 2>&1 | tail -2"
done
SSH "docker ps --format '{{.Names}} | {{.Status}}' | grep what-the-fact"
```

## Step 6 — Update the hub copy used by the senate cron

```bash
cat > /dev/shm/wtf_hub_edit.py <<'PY'
import os, re, shutil, sys
pw = sys.stdin.readline().strip(); assert re.fullmatch(r"[0-9a-f]{48}", pw)
p = os.environ.get("HUB_ENV", "/mnt/archie_brain/.env"); t = open(p).read()
new, n = re.subn(r"^(WTF_POSTGRES_PASSWORD=)[^\n]*", lambda m: m.group(1) + pw, t, flags=re.M)
assert n == 1, "expected exactly one WTF_POSTGRES_PASSWORD line, got %d" % n
shutil.copy2(p, p + ".bak-pre-wtf-rotation")
with open(p + ".tmp", "w") as f: f.write(new)
shutil.copymode(p, p + ".tmp"); os.replace(p + ".tmp", p); print("hub staged")
PY
printf '%s\n' "$PW" | python3 /dev/shm/wtf_hub_edit.py
shred -u /dev/shm/wtf_hub_edit.py
```

Do not overwrite or copy `.env` files between locations (CLAUDE.md rule 2): this edits one line only.

## Step 7 — Verify (all must pass)

```bash
# 7a. Each service connects with the NEW login. Prints the role name or FAIL + exception class only.
for S in wtf-ingest-api wtf-tech wtf-consumer wtf-ingest; do
  printf '%s: ' "$S"
  SSH "docker exec what-the-fact-$S-1 python3 -c \"
import os, sys, sqlalchemy as sa
try:
    c = sa.create_engine(os.environ['WTF_DATABASE_URL']).connect()
    print(c.execute(sa.text('select current_user')).scalar())
except Exception as x:
    print('FAIL', type(x).__name__); sys.exit(1)\""
done

# 7b. Public site answers and the apps' own health.
for U in https://what-the-fact.com/ https://what-the-fact.tech/version; do curl -fsS -o /dev/null -w "$U %{http_code}\n" "$U"; done

# 7c. The hub script's path works (mesh endpoint, new hub-side value). Class name only on failure.
python3 - <<'PY'
import re, psycopg2, sys
pw = re.search(r"^WTF_POSTGRES_PASSWORD=(.*)$", open("/mnt/archie_brain/.env").read(), re.M).group(1).strip()
try:
    c = psycopg2.connect(host="100.64.0.10", port=5434, user="wtfuser", password=pw, dbname="wtf", connect_timeout=8)
    cur = c.cursor(); cur.execute("select current_user"); print("hub->mesh:", cur.fetchone()[0]); c.close()
except Exception as x:
    print("hub->mesh FAIL", type(x).__name__); sys.exit(1)
PY

# 7d. The OLD password no longer works. The old value is in the two .bak files; read it in-process, never print it.
SSH "python3 - <<'PY'
import re, sys
t = open('$DIR/.env.bak-pre-rotation').read()
open('/dev/shm/.old', 'w').write(re.search(r'://wtfuser:([^@\s]+)@', t).group(1))
PY"
SSH "python3 - <<'PY'
import psycopg2, sys
old = open('/dev/shm/.old').read().strip()
try:
    psycopg2.connect(host='100.64.0.10', port=5434, user='wtfuser', password=old, dbname='wtf', connect_timeout=6)
    print('OLD PASSWORD STILL WORKS  <-- BAD'); sys.exit(1)
except psycopg2.OperationalError as x:
    print('old password rejected:', 'password authentication failed' in str(x))
PY
shred -u /dev/shm/.old"

# 7e. End the old sessions (those opened before the change, over TCP; local docker-exec callers are untouched).
SSH "docker exec $PGC psql -U wtfuser -d wtf -Atc \"select count(pg_terminate_backend(pid)) from pg_stat_activity where usename='wtfuser' and client_addr is not null and backend_start < '$T0'::timestamptz and pid <> pg_backend_pid()\""
```

Then wait for the next scheduled senate/lobbying/GIC run and confirm it wrote rows (`select max(...)` on its table) — a clean
exit with no rows is not proof (DB rule: an empty result is not a PASS).

## Step 8 — Clean up (only after Step 7 fully passes)

```bash
SSH "cd $DIR && shred -u .env.bak-pre-rotation '$SECRET_FILE.bak-pre-rotation'"
shred -u /mnt/archie_brain/.env.bak-pre-wtf-rotation /dev/shm/wtf-fp-before
unset PW VERIFIER B64; set -o history 2>/dev/null
# Keep /root/backups/wtf-pre-rotation-*.dump until Phase B is done, then remove it.
```

## If something fails

| Where | Symptom | Do |
|---|---|---|
| Step 3 | edit assertion fails | Nothing on the server changed. Restore the `.bak` files if they were made; stop. |
| Step 4 | `ALTER ROLE` errors | Role unchanged. Restore the two files from `.bak` (old password still valid), stop, report the error class. |
| Step 5 | a service will not start / FAIL in 7a | The new password is already in `.env`. Read that service's logs (`docker logs --tail 40`), fix the cause, recreate it again. **Do not restore the old password.** |
| Step 7c | hub->mesh fails | Check the Step 6 edit and that 5434 is reachable from the hub; the services are unaffected. |
| Any | unsure whether the role changed | `select left(md5(rolpassword),12) from pg_authid where rolname='wtfuser'` vs `/dev/shm/wtf-fp-before`. |

## After Phase A

- **Not done by this runbook:** the DR fallback (`WTF_DATABASE_URL_FALLBACK`), any other hub cron/systemd unit, and any saved operator connection
  string. Step 1 only found what `grep` could see; these remain in `rotation-checklist.md` → "Not yet inventoried". Check them now.
- `wtfuser` is still a superuser that owns everything. Phase A removes the *known exposure*, not the *blast radius*. That is Phase B.
- **The old password is still in an AI-session transcript** (`~/.claude/projects/-mnt-archie-brain/9dbe8958-…jsonl`). It is dead after
  Step 7d, but delete or redact that file if the transcripts are retained or shared.
- Record it: `mcp store_memory` (`mistake_learned`: psycopg2 error text embeds the DSN) and update the task note.
