# 👑 A.R.C.H.I.E. ADMIN REFERENCE
**Last Updated:** December 26, 2025

## 📋 ADMIN QUICK REFERENCE

Essential commands and procedures for A.R.C.H.I.E. platform administration.

---

## 🔑 ADMIN ACCESS

### **Admin Panel:**
**URL:** http://192.168.1.200:3000/tools/admin

### **Make User Admin:**
```bash
docker exec -it archie_database psql -U archie -d archie

UPDATE users SET is_admin = TRUE WHERE username = 'username';

\q
```

### **Check Who's Admin:**
```sql
SELECT username, is_admin, is_active FROM users WHERE is_admin = TRUE;
```

---

## 🚀 PLATFORM MANAGEMENT

### **Start/Stop/Restart:**
```bash
# Start
cd /mnt/archie_brain && docker-compose up -d

# Stop
docker-compose down

# Restart platform only
docker-compose restart archie_platform

# Restart database only
docker-compose restart archie_database

# Restart all
docker-compose restart
```

### **View Logs:**
```bash
# Platform logs (live)
docker logs archie_platform -f

# Last 100 lines
docker logs archie_platform --tail 100

# Database logs
docker logs archie_database

# All containers
docker-compose logs -f
```

### **Check Status:**
```bash
# Container status
docker ps

# Resource usage
docker stats archie_platform archie_database

# Health check
curl http://localhost:3000/health
```

---

## 💾 DATABASE MANAGEMENT

### **Connect to Database:**
```bash
# Interactive terminal
docker exec -it archie_database psql -U archie -d archie

# Run single command
docker exec archie_database psql -U archie -d archie -c "SELECT COUNT(*) FROM users;"
```

### **Useful Queries:**
```sql
-- List all tables
\dt

-- Table structure
\d users

-- All users
SELECT username, email, is_active, is_admin, created_at FROM users;

-- Recent logins
SELECT u.username, s.login_time, s.ip_address 
FROM active_sessions s 
JOIN users u ON s.user_id = u.id 
ORDER BY s.login_time DESC LIMIT 10;

-- Failed login attempts
SELECT username, ip_address, attempted_at 
FROM failed_logins 
ORDER BY attempted_at DESC LIMIT 20;

-- Audit log (recent activity)
SELECT action, username, details, timestamp 
FROM audit_log 
ORDER BY timestamp DESC LIMIT 50;

-- Tool usage stats
SELECT tool_name, COUNT(*) as uses, MAX(used_at) as last_used 
FROM tool_usage 
GROUP BY tool_name;
```

### **User Management:**
```sql
-- Activate user
UPDATE users SET is_active = TRUE WHERE username = 'username';

-- Deactivate user
UPDATE users SET is_active = FALSE WHERE username = 'username';

-- Make admin
UPDATE users SET is_admin = TRUE WHERE username = 'username';

-- Remove admin
UPDATE users SET is_admin = FALSE WHERE username = 'username';

-- Delete user (careful!)
DELETE FROM users WHERE username = 'username';

-- Reset password (user must login to set new one)
UPDATE users SET password_hash = NULL WHERE username = 'username';
```

---

## 📊 MONITORING

### **System Health:**
```bash
# CPU/Memory usage
docker stats --no-stream archie_platform archie_database

# Disk usage
df -h /mnt/archie_brain

# Platform directory size
du -sh /mnt/archie_brain/*

# Backup size
du -sh /mnt/archie_brain/backups/*
```

### **Check AI (Ollama):**
```bash
# Test connection
curl http://192.168.1.246:11434/api/tags

# Should return models including qwen2.5-coder:7b
```

### **Database Size:**
```sql
-- Total database size
SELECT pg_size_pretty(pg_database_size('archie'));

-- Table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## 🛡️ SECURITY

### **View Failed Logins:**
```sql
-- Recent failed attempts
SELECT * FROM failed_logins ORDER BY attempted_at DESC LIMIT 50;

-- Failed attempts by IP
SELECT ip_address, COUNT(*) as attempts
FROM failed_logins
WHERE attempted_at > NOW() - INTERVAL '24 hours'
GROUP BY ip_address
ORDER BY attempts DESC;
```

### **Block IP (Future Feature):**
```sql
-- Add to IP blocklist
INSERT INTO ip_access_control (ip_address, action, reason)
VALUES ('1.2.3.4', 'deny', 'Multiple failed login attempts');
```

### **Audit Log:**
```sql
-- Recent admin actions
SELECT * FROM audit_log 
WHERE action IN ('user_created', 'user_deleted', 'permission_changed')
ORDER BY timestamp DESC;

-- Activity by user
SELECT username, action, COUNT(*) as count
FROM audit_log
GROUP BY username, action
ORDER BY count DESC;
```

---

## 💾 BACKUP & RECOVERY

### **Create Backup:**
```bash
# Full backup
BACKUP_DIR="/mnt/archie_brain/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

docker exec archie_database pg_dump -U archie archie > "$BACKUP_DIR/database_backup.sql"
cp -r /mnt/archie_brain/platform_v2 "$BACKUP_DIR/platform_v2"
cp /mnt/archie_brain/.env "$BACKUP_DIR/.env"

echo "Backup created: $BACKUP_DIR"
```

### **Restore Backup:**
```bash
# Set backup directory
BACKUP_DIR="/mnt/archie_brain/backups/20251227_005213"

# Stop platform
cd /mnt/archie_brain && docker-compose down

# Restore database
docker-compose up -d archie_database && sleep 5
docker exec -i archie_database psql -U archie -d archie < "$BACKUP_DIR/database_backup.sql"

# Restore files
rm -rf /mnt/archie_brain/platform_v2
cp -r "$BACKUP_DIR/platform_v2" /mnt/archie_brain/platform_v2
chown -R 1000:1000 /mnt/archie_brain/platform_v2

# Restart
docker-compose up -d
```

See: `BACKUP_RECOVERY_GUIDE.md` for full details

---

## 🔧 MAINTENANCE

### **Clean Docker:**
```bash
# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune

# Remove unused networks
docker network prune

# Clean everything (careful!)
docker system prune -a
```

### **Clean Old Backups:**
```bash
# List backups by age
ls -lat /mnt/archie_brain/backups/

# Keep last 7 days
find /mnt/archie_brain/backups/ -type d -mtime +7 -exec rm -rf {} \;
```

### **Rebuild Platform:**
```bash
cd /mnt/archie_brain

# Stop platform
docker-compose down

# Rebuild
docker-compose build archie_platform

# Start
docker-compose up -d

# Check logs
docker logs archie_platform -f
```

---

## 📈 ANALYTICS

### **User Stats:**
```sql
-- Total users
SELECT COUNT(*) FROM users;

-- Active users
SELECT COUNT(*) FROM users WHERE is_active = TRUE;

-- Admins
SELECT COUNT(*) FROM users WHERE is_admin = TRUE;

-- New users (last 7 days)
SELECT COUNT(*) FROM users 
WHERE created_at > NOW() - INTERVAL '7 days';

-- Users by registration date
SELECT DATE(created_at) as date, COUNT(*) as new_users
FROM users
GROUP BY DATE(created_at)
ORDER BY date DESC
LIMIT 30;
```

### **Tool Usage:**
```sql
-- Most used tools
SELECT tool_name, COUNT(*) as uses
FROM tool_usage
GROUP BY tool_name
ORDER BY uses DESC;

-- Usage by user
SELECT u.username, t.tool_name, COUNT(*) as uses
FROM tool_usage t
JOIN users u ON t.user_id = u.id
GROUP BY u.username, t.tool_name
ORDER BY uses DESC;

-- Usage over time
SELECT DATE(used_at) as date, tool_name, COUNT(*) as uses
FROM tool_usage
GROUP BY DATE(used_at), tool_name
ORDER BY date DESC, uses DESC;
```

---

## 🐛 TROUBLESHOOTING

### **Platform Won't Start:**
```bash
# Check logs for errors
docker logs archie_platform

# Common fixes:
# 1. Database not ready
docker-compose restart archie_database
sleep 10
docker-compose restart archie_platform

# 2. Port conflict
netstat -tulpn | grep 3000

# 3. Permission issues
chown -R 1000:1000 /mnt/archie_brain/platform_v2

# 4. Rebuild
docker-compose down
docker-compose build archie_platform
docker-compose up -d
```

### **Database Connection Failed:**
```bash
# Check database is running
docker ps | grep archie_database

# Check database health
docker exec archie_database pg_isready -U archie

# Restart database
docker-compose restart archie_database

# Check .env settings
cat /mnt/archie_brain/.env | grep DB_
```

### **AI Not Responding:**
```bash
# Check Ollama server
curl http://192.168.1.246:11434/api/tags

# If fails, check Ollama server status on 192.168.1.246
```

---

## 📁 FILE LOCATIONS

**Platform:** `/mnt/archie_brain/platform_v2/`
**Backups:** `/mnt/archie_brain/backups/`
**Docs:** `/mnt/archie_brain/docs/`
**Logs:** `docker logs archie_platform`
**Database:** Docker volume `archie_database`
**Environment:** `/mnt/archie_brain/.env`

---

## 🔑 ENVIRONMENT VARIABLES

**Edit environment:**
```bash
nano /mnt/archie_brain/.env
```

**Required variables:**
```env
DB_HOST=archie_database
DB_PORT=5432
DB_NAME=archie
DB_USER=archie
DB_PASSWORD=your_secure_password
SECRET_KEY=your_secret_key
FLASK_ENV=production
OLLAMA_HOST=http://192.168.1.246:11434
OLLAMA_MODEL=qwen2.5-coder:7b
```

**After changing .env:**
```bash
docker-compose restart archie_platform
```

---

## 📞 QUICK HELP

### **Platform not accessible:**
```bash
# 1. Check containers
docker ps | grep archie

# 2. Check logs
docker logs archie_platform --tail 50

# 3. Restart
docker-compose restart archie_platform
```

### **Database issues:**
```bash
# Connect and check
docker exec -it archie_database psql -U archie -d archie -c "SELECT 1;"

# If fails, restore from backup
```

### **Need to reset everything:**
```bash
# Nuclear option (loses all data!)
docker-compose down
docker volume rm archie_database
docker-compose up -d

# Better: Restore from backup instead
```

---

## 📚 MORE INFO

- `PLATFORM_DOCUMENTATION.md` - Complete platform docs
- `BACKUP_RECOVERY_GUIDE.md` - Backup procedures
- `SESSION_HANDOFF.md` - Latest session summary
- `TODO_LIST.md` - Feature roadmap

---

**Last Updated:** December 26, 2025
**Platform Version:** 1.0
**Status:** Operational ✅
