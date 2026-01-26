# 💾 A.R.C.H.I.E. BACKUP & RECOVERY GUIDE
**Last Updated:** December 26, 2025

## 📋 OVERVIEW

This guide covers backup strategies, recovery procedures, and disaster recovery for the A.R.C.H.I.E. platform.

---

## 🎯 BACKUP STRATEGY

### **What to Backup:**
1. **Database** - PostgreSQL (all user data, configs)
2. **Platform Files** - Application code
3. **Environment Variables** - .env file
4. **User Uploads** - Uploaded files (future)

### **Backup Schedule:**
- **Before deployments** - Always!
- **Daily** - Automated (future feature)
- **Before major changes** - Manual
- **After important updates** - Manual

---

## 💾 MANUAL BACKUP

### **Full System Backup:**
```bash
#!/bin/bash
# Create timestamped backup directory
BACKUP_DIR="/mnt/archie_brain/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup database
echo "📦 Backing up database..."
docker exec archie_database pg_dump -U archie archie > "$BACKUP_DIR/database_backup.sql"

# Backup platform files
echo "📦 Backing up platform files..."
cp -r /mnt/archie_brain/platform_v2 "$BACKUP_DIR/platform_v2"

# Backup environment
echo "📦 Backing up environment..."
cp /mnt/archie_brain/.env "$BACKUP_DIR/.env"

# Create backup info file
cat > "$BACKUP_DIR/backup_info.txt" << EOF
Backup Created: $(date)
Database Size: $(ls -lh "$BACKUP_DIR/database_backup.sql" | awk '{print $5}')
Platform Files: $(du -sh "$BACKUP_DIR/platform_v2" | awk '{print $1}')
EOF

echo "✅ Backup complete: $BACKUP_DIR"
```

### **Quick Database Backup:**
```bash
docker exec archie_database pg_dump -U archie archie > backup_$(date +%Y%m%d).sql
```

### **Platform Files Only:**
```bash
cp -r /mnt/archie_brain/platform_v2 /mnt/archie_brain/backups/platform_$(date +%Y%m%d)
```

---

## 🔄 MANUAL RECOVERY

### **Full System Restore:**
```bash
#!/bin/bash
# Set backup directory
BACKUP_DIR="/mnt/archie_brain/backups/20251227_005213"  # Change to your backup

# Stop platform
cd /mnt/archie_brain
docker-compose down

# Restore database
echo "🔄 Restoring database..."
docker-compose up -d archie_database
sleep 5
docker exec -i archie_database psql -U archie -d archie < "$BACKUP_DIR/database_backup.sql"

# Restore platform files
echo "🔄 Restoring platform files..."
rm -rf /mnt/archie_brain/platform_v2
cp -r "$BACKUP_DIR/platform_v2" /mnt/archie_brain/platform_v2

# Restore environment (if needed)
cp "$BACKUP_DIR/.env" /mnt/archie_brain/.env

# Fix permissions
chown -R 1000:1000 /mnt/archie_brain/platform_v2

# Restart platform
docker-compose up -d

echo "✅ Recovery complete!"
echo "🔍 Check logs: docker logs archie_platform"
```

### **Database Only:**
```bash
# Restore from backup
docker exec -i archie_database psql -U archie -d archie < backup_20251227.sql

# Restart platform
docker-compose restart archie_platform
```

### **Platform Files Only:**
```bash
# Stop platform
docker-compose down

# Restore files
rm -rf /mnt/archie_brain/platform_v2
cp -r /mnt/archie_brain/backups/platform_20251227 /mnt/archie_brain/platform_v2

# Fix permissions
chown -R 1000:1000 /mnt/archie_brain/platform_v2

# Restart
docker-compose up -d
```

---

## 🚨 EMERGENCY RECOVERY

### **Platform Won't Start:**

**Step 1:** Check logs
```bash
docker logs archie_platform
```

**Step 2:** If import errors, restore from last good backup
```bash
# Find latest backup
ls -lt /mnt/archie_brain/backups/ | head -5

# Restore (use commands above)
```

**Step 3:** If database issues
```bash
# Restore database
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/backups/LATEST/database_backup.sql

# Restart
docker-compose restart archie_platform
```

### **Database Corrupted:**

```bash
# Stop everything
docker-compose down

# Remove corrupted database volume
docker volume rm archie_database

# Recreate and restore
docker-compose up -d archie_database
sleep 10
docker exec -i archie_database psql -U archie -d archie < backup.sql
docker-compose up -d
```

---

## 📊 BACKUP LOCATIONS

### **Current Backups:**
```
/mnt/archie_brain/backups/
├── 20251227_005213/          # Latest (successful rollback)
│   ├── database_backup.sql
│   ├── platform_v2/
│   └── app.py.backup
├── 20251226_235959/          # Previous
└── ...
```

### **Check Backup Size:**
```bash
du -sh /mnt/archie_brain/backups/*
```

### **Clean Old Backups:**
```bash
# Keep last 7 days only
find /mnt/archie_brain/backups/ -type d -mtime +7 -exec rm -rf {} \;
```

---

## 🤖 AUTOMATED BACKUPS (Future)

### **Daily Backup Cron:**
```bash
# Edit crontab
crontab -e

# Add daily backup at 3 AM
0 3 * * * /mnt/archie_brain/scripts/daily_backup.sh
```

### **Daily Backup Script:**
```bash
#!/bin/bash
# /mnt/archie_brain/scripts/daily_backup.sh

BACKUP_DIR="/mnt/archie_brain/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Database
docker exec archie_database pg_dump -U archie archie > "$BACKUP_DIR/database_backup.sql"

# Platform files
cp -r /mnt/archie_brain/platform_v2 "$BACKUP_DIR/platform_v2"

# Keep only last 7 days
find /mnt/archie_brain/backups/ -type d -mtime +7 -exec rm -rf {} \;

echo "✅ Automated backup complete: $BACKUP_DIR"
```

---

## 📝 BACKUP CHECKLIST

### **Before Deployment:**
- [ ] Create full backup
- [ ] Note backup directory name
- [ ] Verify backup files exist
- [ ] Test backup if critical

### **After Failed Deployment:**
- [ ] Identify backup directory
- [ ] Stop platform
- [ ] Restore database
- [ ] Restore platform files
- [ ] Restart platform
- [ ] Verify functionality

### **Regular Maintenance:**
- [ ] Weekly: Verify backups exist
- [ ] Monthly: Test restore procedure
- [ ] Quarterly: Clean old backups

---

## 🎯 BEST PRACTICES

### **DO:**
✅ Backup before every deployment
✅ Keep multiple backups
✅ Test restore procedures
✅ Document what changed
✅ Note backup timestamps

### **DON'T:**
❌ Deploy without backup
❌ Delete backups immediately
❌ Skip verification
❌ Assume backups work
❌ Store only one backup

---

## 🔍 VERIFY BACKUPS

### **Check Database Backup:**
```bash
# View backup file
file backup.sql
# Should show: ASCII text

# Check size
ls -lh backup.sql
# Should be reasonable (> 1MB typically)

# Preview contents
head -20 backup.sql
# Should show SQL commands
```

### **Check Platform Backup:**
```bash
# Verify files exist
ls -la /mnt/archie_brain/backups/LATEST/platform_v2/

# Check key files
test -f /mnt/archie_brain/backups/LATEST/platform_v2/app.py && echo "✅ app.py exists"
```

---

## 🆘 SUPPORT

### **Can't Find Backup:**
```bash
# List all backups
ls -lat /mnt/archie_brain/backups/

# Find by date
find /mnt/archie_brain/backups/ -type d -name "20251227*"
```

### **Backup Too Large:**
```bash
# Compress backup
tar -czf backup.tar.gz /mnt/archie_brain/backups/DIRECTORY/

# Decompress when needed
tar -xzf backup.tar.gz
```

### **Need Off-Site Backup:**
```bash
# Copy to external drive
cp -r /mnt/archie_brain/backups/LATEST /media/external_drive/

# Or upload to cloud (future)
```

---

## 📚 RELATED DOCS

- `SESSION_HANDOFF.md` - Latest session details
- `DEPLOYMENT_CHECKLIST.md` - Deployment procedures
- `PLATFORM_DOCUMENTATION.md` - Platform overview

---

**Remember:** The best backup is the one you test! 🎯

**Last Updated:** December 26, 2025
**Status:** Manual backups working ✅
**Future:** Automated backups + UI management
