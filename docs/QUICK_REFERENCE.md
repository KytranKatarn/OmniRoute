# ⚡ A.R.C.H.I.E. QUICK REFERENCE CARD

**Platform:** http://192.168.1.200:3000  
**Version:** 1.0 ✅  
**Status:** OPERATIONAL

---

## 🚀 START/STOP
```bash
cd /mnt/archie_brain
docker-compose up -d              # Start
docker-compose down               # Stop
docker-compose restart archie_platform  # Restart
docker logs archie_platform -f    # View logs
```

---

## 💾 BACKUP (Before ANY deployment!)
```bash
# Quick backup
BACKUP_DIR="/mnt/archie_brain/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker exec archie_database pg_dump -U archie archie > "$BACKUP_DIR/database_backup.sql"
cp -r /mnt/archie_brain/platform_v2 "$BACKUP_DIR/platform_v2"
echo "Backup: $BACKUP_DIR"
```

---

## 🔄 RESTORE
```bash
# Set your backup directory
BACKUP_DIR="/mnt/archie_brain/backups/20251227_005213"

# Restore
docker-compose down
docker-compose up -d archie_database && sleep 5
docker exec -i archie_database psql -U archie -d archie < "$BACKUP_DIR/database_backup.sql"
rm -rf /mnt/archie_brain/platform_v2
cp -r "$BACKUP_DIR/platform_v2" /mnt/archie_brain/platform_v2
chown -R 1000:1000 /mnt/archie_brain/platform_v2
docker-compose up -d
```

---

## 🔐 DEFAULT ADMIN LOGIN (Fresh Install)
```
Username: admin
Password: admin123
```
**Important:** Change this password after first login!

---

## 👤 CREATE/MAKE ADMIN
```bash
# Create admin user (fresh install)
docker exec archie_platform python3 -c "
from werkzeug.security import generate_password_hash
import psycopg2
conn = psycopg2.connect(host='archie_database', database='archie', user='archie', password='archie_secure_2024')
cur = conn.cursor()
cur.execute('''INSERT INTO users (username, email, password_hash, role, is_active, is_admin)
VALUES (%s, %s, %s, %s, %s, %s)''', ('admin', 'admin@archie.local', generate_password_hash('admin123'), 'ADMIN', True, True))
conn.commit()
print('Admin user created')
"

# Promote existing user to admin
docker exec -it archie_database psql -U archie -d archie
UPDATE users SET is_admin = TRUE, role = 'ADMIN' WHERE username = 'your_username';
\q
```

---

## 🗄️ DATABASE
```bash
# Connect
docker exec -it archie_database psql -U archie -d archie

# Useful queries
\dt                           # List tables
SELECT * FROM users;          # View users
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 20;  # Recent activity
\q                            # Exit
```

---

## 🔍 TROUBLESHOOT
```bash
# Check status
docker ps | grep archie

# View logs
docker logs archie_platform --tail 100

# Restart if needed
docker-compose restart archie_platform

# Check AI
curl http://192.168.1.246:11434/api/tags
```

---

## 📁 KEY LOCATIONS
- Platform: `/mnt/archie_brain/platform_v2/`
- Backups: `/mnt/archie_brain/backups/`
- Docs: `/mnt/archie_brain/docs/`
- Latest Backup: `/mnt/archie_brain/backups/20251227_005213/`

---

## 🔗 URLs
- Dashboard: http://localhost:3000/dashboard
- Blueprint: http://localhost:3000/tools/blueprint
- Consciousness: http://localhost:3000/tools/consciousness
- Chat: http://localhost:3000/tools/archie-chat
- Code Editor: http://localhost:3000/tools/code-editor

---

## 🆘 EMERGENCY
```bash
# Platform broken? Restore from backup!
cd /mnt/archie_brain/backups/
ls -lat  # Find latest backup
# Then use RESTORE commands above
```

---

## 📚 FULL DOCS
- `ADMIN_REFERENCE.md` - All admin commands
- `BACKUP_RECOVERY_GUIDE.md` - Detailed backup guide
- `PLATFORM_DOCUMENTATION.md` - Complete docs
- `SESSION_HANDOFF.md` - Latest session summary

---

**Remember:** ALWAYS backup before deploying! 💾

**Last Updated:** December 26, 2025
