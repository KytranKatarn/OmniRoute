# Media Hub — Standalone

Unified control plane for your media server ecosystem — Plex, Jellyfin,
Sonarr, Radarr, Prowlarr, Overseerr, SABnzbd, TMDB — behind one
LCARS-themed UI.

This is the **standalone** distribution: one `docker compose up` runs
Media Hub and its own Postgres, independent of the ARCHIE platform.

## What's inside

| File                   | Purpose                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| `Dockerfile`           | Python 3.11 slim, non-root uid 10001, pinned base, curl healthcheck  |
| `docker-compose.yml`   | `mediahub_app` + `mediahub_db` (postgres:16.4-alpine), hardened      |
| `app.py`               | Flask entry — wires blueprint, Flask-Login, `/health`                |
| `database.py`          | `DATABASE_URL`-backed shim for the Media Hub module                  |
| `users.py`             | User model + `bootstrap_admin_if_empty()`                            |
| `auth_routes.py`       | `/login`, `/logout`                                                  |
| `templates/login.html` | LCARS-styled sign-in form                                            |
| `.env.example`         | Secrets template with generation hints                               |

The Media Hub module itself is copied from
`platform_v2/tools/media_hub/` at build time — same source runs embedded
in ARCHIE and standalone.

## Install

Requires Docker ≥ 24 and Docker Compose v2.

```bash
cd standalone/media_hub
cp .env.example .env
```

Generate the three required secrets and paste them into `.env`:

```bash
# MEDIA_HUB_DB_PASSWORD + MEDIA_HUB_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# MEDIA_HUB_ENCRYPTION_KEY (Fernet — used to encrypt stored service API keys)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Optional:

- `MEDIA_HUB_ADMIN_PASSWORD` — auto-creates the `admin` user on first
  boot if the users table is empty. Leave blank if you prefer to seed
  users another way.
- `TMDB_API_KEY` — enables external metadata enrichment. Free key at
  <https://www.themoviedb.org/settings/api>.

> **Migrating from ARCHIE-embedded Media Hub?** Reuse the platform's
> existing `MEDIA_HUB_ENCRYPTION_KEY` here. If you rotate the key, every
> stored service API key needs to be re-pasted in the settings UI.

## Run

```bash
docker compose --env-file .env up -d --build
```

Stack should report healthy within ~10 s. First boot applies
`platform_v2/tools/media_hub/db/schema.sql` via
`docker-entrypoint-initdb.d` and bootstraps the admin user if
`MEDIA_HUB_ADMIN_PASSWORD` is set.

Browse to <http://localhost:8105/> — you'll be redirected to the login
page. Sign in with `admin` + your `MEDIA_HUB_ADMIN_PASSWORD`, then
configure your media services in the UI.

## Architecture

```
                ┌──────────────────────────┐
  Browser  ───► │  mediahub_app  :8105     │ ◄── probes every 10 min ───┐
                │  - Flask + gunicorn      │                            │
                │  - blueprint gate        │                            ▼
                │  - APScheduler           │      ┌───────────────────────────────┐
                │  - /auth/sso (501 stub)  │ ───► │ Plex / Jellyfin / Sonarr /    │
                └───────────┬──────────────┘      │ Radarr / Prowlarr / Overseerr │
                            │                     │ SABnzbd / TMDB                │
                            ▼                     └───────────────────────────────┘
                ┌──────────────────────────┐
                │  mediahub_db :5432       │
                │  postgres:16.4-alpine    │
                │  - media_hub_services    │
                │  - media_hub_users       │
                └──────────────────────────┘
```

Ports:

- **8105** — app (published to host)
- **5432** — db (container-internal only; not exposed to the host)

Volumes:

- `mediahub_pgdata` — Postgres data directory. **Back this up.**

## Health + observability

- `GET /health` — lightweight liveness probe (`{"status":"ok"}`)
- APScheduler runs `run_health_checks()` every 10 min — probes every
  enabled row in `media_hub_services` via the client `probe()` contract
  and persists `health_status` + `health_message` + `last_health_check`
- Container logs: `docker compose logs -f mediahub_app`

Each client exposes a two-stage `probe()` — unauthenticated reachability
first (is the server up?), then authenticated request (is the token
still valid?). Operators see actionable error messages rather than a
bare `unhealthy`.

## Auth

`current_user.is_authenticated` guards every Media Hub route via a
blueprint-wide `before_request` hook. API calls (path contains `/api/`)
return `401 {"error":"Authentication required"}`; browser routes
redirect to `/login`.

`/tools/media-hub/auth/sso` is a stub that returns **HTTP 501** with a
pointer to Project #273 Tier 2. Real Kytran SSO wiring is out of scope
for the Tier 1 release.

## Backup + restore

Database:

```bash
# Backup
docker compose exec mediahub_db pg_dump -U mediahub mediahub > mediahub.sql

# Restore into a fresh stack
docker compose exec -T mediahub_db psql -U mediahub mediahub < mediahub.sql
```

Also back up your `.env` — losing `MEDIA_HUB_ENCRYPTION_KEY` means every
stored service API key becomes unreadable and has to be re-pasted.

## Upgrading

```bash
git pull
docker compose --env-file .env build
docker compose --env-file .env up -d
```

Schema changes land in `platform_v2/tools/media_hub/db/schema.sql`.
The SQL is idempotent (`CREATE … IF NOT EXISTS`, `DROP TRIGGER IF
EXISTS`), but `docker-entrypoint-initdb.d` **only runs on fresh
volumes** — for in-place schema upgrades, apply the SQL manually:

```bash
docker compose exec -T mediahub_db psql -U mediahub mediahub \
    < ../../platform_v2/tools/media_hub/db/schema.sql
```

## Troubleshooting

| Symptom                                            | Likely cause                                                                                          |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `docker compose up` fails on `set in .env`         | A required env var is blank in `.env`. Copy `.env.example` and fill every line without a default      |
| Login page rejects `admin` / password              | Bootstrap only runs when the users table is empty. Reset: `docker compose down -v && up -d --build`   |
| Service shows `unhealthy` with no detail           | Client lacks `probe()` — check that you built from a post-#153 commit                                 |
| `401 Authentication required` on every request     | Session cookie expired or `MEDIA_HUB_SECRET_KEY` rotated. Log in again                                |
| Encrypted API keys fail to decrypt after rotation  | `MEDIA_HUB_ENCRYPTION_KEY` was changed. Restore old value, or re-paste every service API key          |
| Port 8105 already in use                           | Change the host port in `docker-compose.yml` `ports: - "<host>:8105"`                                 |

## Provenance

This standalone was extracted from ARCHIE module `tools/media_hub/`
under Project #273 following `.claude/rules/standalone-extraction.md`.
Tier 1 ship tasks: #2146–#2157. Open issues are tracked in the ARCHIE
`unified_projects` / `unified_tasks` tables.

## License

See repository root `LICENSE`.
