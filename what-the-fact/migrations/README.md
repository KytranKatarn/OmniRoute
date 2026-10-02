# What The Fact — migrations

## ⚠️ These apply to CITADEL, not to the hub

**Do not run these against `archie_database` on the hub.** On 2026-10-02 this
happened: migrations 085–087 were applied to a hub-local `wtf` database before
anyone established where WTF actually runs. It was reverted by hand, and the
database was later dropped entirely (see below).

**As of 2026-10-02 the hub has no `wtf` database at all**, so this class of
mistake now fails loudly instead of succeeding silently. Citadel's
`wtf-postgres` is the LIVE PRIMARY — all four WTF services read and write it
(~62M writes on `parliament.ec_contributions`). It is not a replica:
`pg_is_in_recovery()` is false.

## The correct target

| | |
|---|---|
| Host | Citadel — United States, `citadel-us`, mesh `100.64.0.10`, public `2.25.133.122` |
| Container | `what-the-fact-wtf-postgres-1` |
| Credentials | `POSTGRES_USER=wtfuser`, `POSTGRES_DB=wtf` |
| Path | `/opt/archie-products/what-the-fact` (**not** a git checkout — it is an rsync'd deploy artifact) |

```bash
cat what-the-fact/migrations/0NN_xxx.sql | \
  ssh root@100.64.0.10 \
  "docker exec -i what-the-fact-wtf-postgres-1 psql -U wtfuser -d wtf -v ON_ERROR_STOP=1"
```

## Why the general rule misleads here

`.claude/rules/database.md` gives one command for all migrations:

```
docker exec archie_database psql -U archie -d archie -f <path>
```

That is correct for **platform** migrations (`database/migrations/`), which live
in the hub's `archie` database. It is **wrong for WTF**, which is a separate
product with a separate Postgres on a separate host. The two databases have
overlapping table names (`parliament.*`, `wtf.*`), so a wrong target does not
error — it just writes to a database nobody serves from.

## Ordering

1. Migrations first — the consumer queries tables these create.
2. **Then** rebuild the images. The code that populates them
   (`ingest/elections/calendar.py`, `wiki_history.py`, `shared/election_calendar.py`)
   only exists in a rebuilt image, so a `--dry-run` ingest before the rebuild
   fails with `ModuleNotFoundError`.
3. Rebuild: `what-the-fact/deploy.sh` — `rsync --delete` from the hub, then
   `docker compose up --build`. `.env` is excluded; Citadel keeps its own secrets.

## These migrations are not re-runnable

085 and 086 both `INSERT` into `parliament.election_calendar` and **neither has
`ON CONFLICT`**, so a second run violates the `jurisdiction_code` primary key.
The `CREATE TABLE` / `ADD COLUMN` statements are guarded with `IF NOT EXISTS`;
the seed rows are not. If a migration fails partway, check what landed before
retrying.

## Seeding policy

Curated dates are seeded **unverified** (`verified_at IS NULL`) and
`shared/election_calendar.py` withholds the date of any such row from the page.
This is deliberate — a design prototype is not a checked source. To verify a row
after reading the statute or the election agency's page:

```sql
UPDATE parliament.election_calendar
   SET last_election = '<date>', next_latest_date = '<date>',
       rule = '<statute + section, in words>', source_url = '<url>',
       verified_at = now()
 WHERE jurisdiction_code = '<code>';
```