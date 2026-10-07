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

Prefer the guarded runner, which hard-codes this target and refuses a wrong one:

```bash
python3 what-the-fact/scripts/migrations_apply.py plan       # what is pending (read-only)
python3 what-the-fact/scripts/migrations_apply.py rehearse   # ALL pending in ONE transaction, then ROLLBACK
python3 what-the-fact/scripts/migrations_apply.py apply --yes
```

It refuses a pending file that does not log itself in `schema_migrations` or that carries its own
BEGIN/COMMIT, and `apply` only reports success once the ledger row exists.

Then check what the database thinks it has, rather than assuming the pipe landed:

```bash
WTF_DATABASE_URL=... python3 what-the-fact/scripts/migrations_admin.py status
```

## Migration ledger (from 088 onward)

As of **088** there is a `public.schema_migrations` table on Citadel recording which
migrations have been applied. Until then nothing did, so the only way to check was to
look for the tables each file creates — which is how the wrong-target incident above
slipped through.

| | |
|---|---|
| 001–087 | **Not in the ledger.** A single `000-baseline` row records that they were applied before it existed, with `applied_at` deliberately NULL. Treat as *unverified*, not as a record of 87 applications. |
| 088+ | Log themselves in the same transaction as their DDL, so "recorded" and "applied" cannot drift. |

Each new migration must end with its own log line, or it will be reported as
`NOT APPLIED`:

```sql
INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('0NN', '0NN_xxx.sql', 'One line saying what it did', now())
ON CONFLICT (version) DO NOTHING;
```

That `ON CONFLICT DO NOTHING` is what keeps 088 itself re-runnable, matching the
verified behaviour of 085–087 described below.

`migrations_admin.py status` is **read-only** and exits non-zero in the two cases where a
report would mislead you: the ledger is the platform's rather than WTF's, or the ledger
disagrees with the files on disk.

⚠️ **Do not "fix" the error you will get if you apply 088 to the hub.** The hub's
`archie` database also has a `public.schema_migrations` — the platform's own history.
`CREATE TABLE IF NOT EXISTS` no-ops there and the INSERT then fails on the unknown
`filename` column, aborting the file under `ON_ERROR_STOP=1` before writing anything.
That is the wrong-target guard firing. It leaves the platform's ledger untouched, which
was verified: misapplying 088 to a platform-shaped ledger exits non-zero and writes zero
rows. Dropping `filename` to silence it would destroy that protection.

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

## These migrations ARE re-runnable

An earlier version of this file claimed 085/086 could not be re-run because
their `INSERT`s into `parliament.election_calendar` lacked `ON CONFLICT` and
would violate the `jurisdiction_code` primary key. **That was wrong** — both
statements end in `ON CONFLICT (jurisdiction_code) DO NOTHING`. The claim was
false when it was written; the SQL has never lacked the guard.

085, 086 and 087 are idempotent. Every statement is guarded:

| Statement | Guard |
|---|---|
| `CREATE TABLE` (085, 086) | `IF NOT EXISTS` |
| `CREATE INDEX` (086) | `IF NOT EXISTS` |
| `ADD COLUMN` (086 ×3, 087) | `IF NOT EXISTS` |
| `INSERT` seeds (085, 086) | `ON CONFLICT (jurisdiction_code) DO NOTHING` |
| `level` CHECK swap (086) | `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT` |
| `GRANT`s (085, 086) | wrapped in `DO $$ IF EXISTS (role) $$` |

Verified by running all three **three times** against a clean
`postgres:16-alpine` with `ON_ERROR_STOP=1`: no errors, and
`election_calendar` held steady at 39 rows across every pass. As a control, the
same test with 085's `ON CONFLICT` stripped out *does* fail, with
`duplicate key value violates unique constraint "election_calendar_pkey"` —
so the test is capable of detecting the failure it claims is absent.

So a failed migration can simply be re-run. Note what re-running does *not*
fix: if a run died partway, re-running replays the whole file from the top,
and the `GRANT`s are conditional on the `wtfuser` role existing at that moment.

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
