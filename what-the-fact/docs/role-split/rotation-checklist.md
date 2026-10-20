# Credential rotation and runtime cutover checklist — operator only

Status: **not executed**. No secret values belong in this file, chat, PRs,
logs, process arguments or exported review evidence. The reported exposure makes
the old `wtfuser` password compromised; splitting roles alone does not rotate it.

## Before changes

- [ ] Record the approved integrated revision, schema diff, grant/workload
  rehearsal results, verified Citadel target and actual service identities.
- [ ] Inventory every holder of the old password: Citadel product `.env`,
  `secrets/wtf_db_password.txt`, hub root `.env`, cron/systemd jobs and scripts,
  all four app containers, admin scripts, connection pools and any DR fallback.
  Inventory variable names and consumers without printing values. Do not assume
  the four container audits cover host jobs or alternate connection URLs.
- [ ] Verify a backup and tested restore path for the dedicated Citadel WTF DB.
- [ ] Establish a separately controlled migration/break-glass admin credential
  and test operator access. It must not live in an app env file or image.
- [ ] Decide a bounded cutover window and job pause/drain plan. Resolve runtime
  DDL, full-refresh ownership and ingest-api routing dependencies first.
- [ ] If exposure needs immediate containment before the role split is ready,
  handle a coordinated emergency password rotation as a separate operator change.
  Do not wait for this proposal or silently break active holders.

## Known holders of the old `wtfuser` credential (surveyed 2026-10-20; names and locations only, no values)

| Holder | How it uses `wtfuser` | Action at cutover |
|---|---|---|
| Citadel `/opt/archie-products/what-the-fact/.env` → `WTF_DATABASE_URL` | injected into ALL FOUR app containers via the shared `env_file` | replace with per-service scoped secrets; recreate each service |
| Citadel Docker secret `wtf_db_password` (`POSTGRES_PASSWORD_FILE`) | bootstrap value only; does not change an initialised role | keep in sync with the operator credential, do not reuse as a runtime password |
| Hub root `/mnt/archie_brain/.env` → `WTF_POSTGRES_PASSWORD` | read by `scripts/senate_votes_cron.sh`, which builds a `wtfuser` URL to the mesh endpoint `100.64.0.10:5434` | switch to a job-scoped login; remove the superuser value from the hub |
| `scripts/gov_contracts_bridge.sh` | `docker exec ... psql -U wtfuser` inside the Citadel DB container (no password) | **re-point to an operator/job role BEFORE `wtfuser` is set NOLOGIN, or it breaks** |
| `/opt/archie-dr/platform/scripts/backup/component_vps_pull.sh` | backup pull entry `pg|wtf|what-the-fact-wtf-postgres-1|wtfuser|wtf` | **re-point to a dedicated backup role BEFORE disabling `wtfuser`, or WTF backups silently stop** |

**Not yet inventoried (must be checked before disabling the old login):** any DR replica or `WTF_DATABASE_URL_FALLBACK` target, other hub cron/systemd units that reach port 5434, and any operator tooling or saved connection strings. The four container audits do not cover these.

## New service credentials

- [ ] Provision unique non-superuser logins `wtf_consumer`, `wtf_tech`,
  `wtf_ingest`, `wtf_ingest_api`, plus a separately scoped hub scraper/job login.
  The hub job should get only its observed senate/lobbying/GIC job permissions,
  not the full scheduler role. Inventory those jobs before granting it anything.
- [ ] Set passwords through an approved interactive/secret-management mechanism
  (for example psql `\password` in an operator-controlled session); never put
  password literals into SQL files or command arguments. Owner roles stay NOLOGIN.
- [ ] Review PostgreSQL HBA and client compatibility before choosing password
  verifier settings; do not bundle an untested authentication-method change.
- [ ] Review the production migration derived from the scratch proposal. Confirm
  no runtime owns objects or can SET ROLE to an owner/migration identity. Review
  unexpected memberships, column/PUBLIC/default grants and functions separately.

## Citadel product `.env` and runtime configuration

- [ ] Prepare per-service restricted connection values through the approved secret
  mechanism. The current shared `env_file: [.env]` injects the same file into all
  services: adding distinct keys to that shared file still exposes ALL of them
  to every process. Use service-scoped secret/env injection in the separately
  reviewed deployment change, not per-service aliases in a common readable file.
- [ ] Remove the old privileged URL/password and operator credential from every
  app's effective environment and readable mounts, including ingest-api and DR
  fallback. Replacing only `WTF_DATABASE_URL` while leaving another privileged
  variable readable does not close the boundary.
- [ ] Keep existing connection-key semantics if helpful; each process may still
  use `WTF_DATABASE_URL`, but its value and available secrets must be isolated.
- [ ] Recreate each affected service after the approved configuration change.
  Restart alone does not re-read Compose `env_file` configuration. Drain workers
  and pools so no old connection survives unnoticed.
- [ ] Check the actual running process's current/session role, role flags,
  effective permissions and owner paths; log only non-secret results.

## PostgreSQL Docker secret and old admin password

- [ ] Rotate the actual existing PostgreSQL `wtfuser` role password through the
  approved operator session. Editing a Docker secret does not change the password
  of a role in an already initialized PostgreSQL data directory.
- [ ] Replace Citadel `secrets/wtf_db_password.txt` (the file referenced by
  `wtf_db_password` / `POSTGRES_PASSWORD_FILE`) through the approved secret store,
  with restricted ownership/mode. Keep its intended bootstrap/admin value in sync
  with the actual role; do not repurpose it as a shared runtime password.
- [ ] Review which existing processes mount the secret and whether recreation
  is necessary to see its new contents. Do not rebuild/reset the database or
  delete/reinitialize its volume as a password-rotation technique.
- [ ] After all application/job holders have migrated, disable the old login
  (`NOLOGIN`) unless a documented operator-only dependency requires it. Never
  leave the exposed password valid. Review and terminate old sessions deliberately:
  changing a password or setting NOLOGIN does not evict existing connections.
- [ ] Verify controlled old-credential authentication fails, without printing
  the attempted value. Validate successful access with each new restricted login.

## Hub script and scheduled work

- [ ] `what-the-fact/scripts/senate_votes_cron.sh:45–50` currently reads
  `WTF_POSTGRES_PASSWORD` from `/mnt/archie_brain/.env` and constructs a `wtfuser`
  URL to the mesh endpoint. Review its callers and sibling scraper jobs.
- [ ] Replace that dependency with the approved job-scoped connection secret.
  The hub must not retain the newly rotated superuser password as a fallback.
  Update every cron/systemd caller, not just the source script.
- [ ] Verify the running job uses its restricted login and that the senate-vote,
  lobbying and GIC paths actually persist expected rows in the Citadel database.
  Do not infer successful writes from an empty output or a clean exit alone.
- [ ] Remove obsolete secret values from authorized stores after all holders are
  accounted for. Review the exposure location and access history; preserve audit
  evidence without reproducing the leaked value.

## Final acceptance and rollback

- [ ] Verify all four actual app logins are distinct, non-superuser, non-owner,
  and have exactly the reviewed privileges. Verify all required routes/jobs and
  the evidence append-only boundary. Recheck after service recreation.
- [ ] Record backup reference, approved revision, migration result, running SHAs,
  role names, successful workloads and denied rights. No secrets in the record.
- [ ] Keep evidence tables/data intact on rollback. Pause a failing workload and
  correct the restricted configuration/grants under review; an image rollback
  alone must not restore privileged credentials to long-running applications.
- [ ] Do not restore the compromised password as rollback. Maintain a tested,
  independent operator recovery path and a forward-fix plan.

References: [PostgreSQL ALTER ROLE](https://www.postgresql.org/docs/16/sql-alterrole.html),
[PostgreSQL Docker image initialization](https://hub.docker.com/_/postgres).
