# A.R.C.H.I.E. Backup & Restore Runbook

**Spec:** `docs/superpowers/specs/2026-04-16-backup-system-design.md`
**Pipeline:** `scripts/backup/run_backup.sh daily|weekly|monthly` (fired by `/etc/cron.d/archie-backup`)
**Source of truth:** `backup_log` table

---

## TL;DR — Full Rebuild After Catastrophic Loss

1. Fresh Ubuntu 22.04+ host. Install: `docker docker-compose postgresql-client openssl git rsync`
2. Clone repo: `git clone git@github.com:KytranKatarn/archie-platform.git /mnt/archie_brain`
3. Retrieve 3 passphrases from paper safe:
   - `BACKUP_CONFIG_PASSPHRASE`
   - `BACKUP_GDRIVE_PASSPHRASE`
   - `BACKUP_VPS_PASSPHRASE`
4. Decrypt config archive: `scripts/backup/decrypt_restore.sh <config_tier_archive>.enc BACKUP_CONFIG_PASSPHRASE`
5. Put decrypted `.env` at `/mnt/archie_brain/.env`
6. Boot DB only: `docker compose up -d archie_database`
7. Restore DB: `pg_restore -h localhost -U archie -d archie -Fc <latest_database.dump>`
8. Boot rest: `docker compose up -d`
9. Verify: `curl -s http://localhost:3000/api/health | jq`
10. Install cron: `sudo /mnt/archie_brain/scripts/install_backup_cron.sh`

---

## Recovery Time Objectives

| Scenario                         | RTO       | Blocker                                    |
|----------------------------------|-----------|--------------------------------------------|
| Single container crash           | 5 min     | `docker restart <container>`               |
| Host disk fail, USB intact       | 3 h       | Restore DB + config + code from USB        |
| Host + USB both lost             | 6–8 h     | Download from GDrive cold; decrypt         |
| Hub fire/theft                   | 12–24 h   | VPS Outpost rsync survives geographically  |
| All tiers lost                   | ∞         | Catastrophic — matches every safe fails    |

**Recovery Point Objective (RPO): 24 h.** Daily `pg_dump` at 02:00 UTC.

---

## Passphrase Recovery

Three distinct passphrases protect distinct tiers:

| Passphrase | Tier | If lost |
|-----------|------|---------|
| `BACKUP_CONFIG_PASSPHRASE` | USB config archive | Cannot recover `.env`/secrets from USB or VPS |
| `BACKUP_GDRIVE_PASSPHRASE` | Every GDrive upload | Cannot decrypt any cold-tier backup |
| `BACKUP_VPS_PASSPHRASE` | VPS rsync payload | Cannot decrypt geographic tier |

**Mandatory handling:**
- Printed on paper
- Stored in a physical safe
- Off-site (different building from the hub)
- Rotated **only** when no legacy encrypted backup must remain valid

Losing a passphrase = losing every encrypted backup in that tier. Do NOT skip.

---

## Operations

### Decrypt one file

```bash
scripts/backup/decrypt_restore.sh <encrypted_file>.enc BACKUP_GDRIVE_PASSPHRASE
```

(Use whichever passphrase env var matches the source tier.)

### Verify latest backup integrity

```bash
scripts/backup/verify_backups.sh
```

Writes `verification_status` rows to `backup_log`. Run weekly via cron; safe to invoke manually.

### Force a fresh full backup (ad-hoc)

```bash
/mnt/archie_brain/scripts/backup/run_backup.sh daily
```

### Check backup freshness from the platform

```sql
SELECT component, tier, status, file_path,
       ROUND(EXTRACT(EPOCH FROM (NOW() - created_at))/3600, 1) AS hours_ago
FROM backup_log
ORDER BY created_at DESC
LIMIT 30;
```

Watchdog alerts:
- **No successful primary backup in 36 h** → Telegram error
- **Offsite tier stale >14 days** → Telegram warning
- **Any backup tier disk <20% free** → Telegram warning

---

## Quarterly DR Drill

Run on the 1st of each quarter (January, April, July, October):

```bash
scripts/backup/dr_drill.sh
```

The drill:
1. Takes the latest daily DB dump from primary tier
2. Restores it into a disposable `postgres:15` container on a random high port
3. Compares row counts against production `knowledge_base`
4. Writes a report to `scripts/backup/dr_reports/YYYY-MM-DD.md`
5. Exits 0 on PASS (<1% delta), 1 on FAIL

**PASS criteria:** Restored row count within 1% of production.

If drill fails, file a `mistake_learned` entry, investigate the restore path, and open a follow-up task BEFORE the next scheduled run.

---

## Tier Map

| Tier       | Path / Endpoint                  | What Lives There                               | Encryption                |
|------------|----------------------------------|------------------------------------------------|---------------------------|
| Primary    | `/mnt/data2/backups/`            | Everything — current + rolling retention       | None (filesystem ACL)     |
| USB Hot    | `/mnt/external-backup/`          | DB, code, gitbundles, config, volumes          | Config tier: AES-256-CBC  |
| GDrive Cold| Work Suite OAuth Drive           | DB, code, gitbundles, config, kb_export, monthly | AES-256-CBC client-side |
| VPS Geo    | `kytran@100.64.0.1:/var/backups/archie/` | DB, gitbundles, config            | AES-256-CBC client-side   |

---

## Known Runtime Blockers (track until resolved)

- **GDrive tier:** OAuth refresh token stale — reconnect at `/tools/google-work-suite`. Until then, gdrive rows log `skipped: oauth not configured`.
- **VPS tier:** Mesh `100.64.0.1` unreachable (Headscale dark); public `76.13.107.109` SSH key not deployed. Until fixed, vps rows log `skipped: mesh/ssh unreachable`.
- **Primary path:** Still `/mnt/data2/backups/` (873 GB unused on `/mnt/data/` blocked by root perms).

See `backup_log` for live status. Watchdog alerts at 14 d of skipping per tier.
