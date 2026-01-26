# Backup Manager Redesign - Comprehensive Backup System

**Created**: 2025-12-29
**Status**: Proposal
**Priority**: HIGH

---

## 🚨 Current Backup System Issues

### What's Currently Backed Up:
1. **Database** ❌ INCOMPLETE
   - Uses custom text format (not proper SQL dump)
   - Won't restore properly
   - Missing schema information

2. **Platform Files** ⚠️ PARTIAL
   - Only backs up: `tools`, `templates`, `static`
   - Missing: root files, configs, scripts

### What's Missing:
- ❌ Environment variables (.env file)
- ❌ Docker configuration (docker-compose.yml)
- ❌ Documentation (/docs)
- ❌ AI Bridge (/ai_bridge)
- ❌ Database migrations
- ❌ Scripts
- ❌ n8n workflows
- ❌ User uploads/data
- ❌ Consciousness/agent data (if stored separately)
- ❌ SSL certificates (if any)
- ❌ Custom configurations

---

## 📋 What Should Be Backed Up

### Critical Components (Must Have):

#### 1. **Database** 🗄️
**What**: Complete PostgreSQL database
**Method**: `pg_dump` with proper SQL format
**Tables Include**:
- agents (58 agents)
- long_term_memory (178+ memories)
- conversations
- users
- agent_types
- improvements
- improvement_conversations

**Backup Command**:
```bash
pg_dump -U archie -h archie_database archie > database_backup.sql
```

**Size**: ~5-20 MB (grows over time)
**Criticality**: ⭐⭐⭐ CRITICAL (all data lost if corrupted)

---

#### 2. **Environment Configuration** ⚙️
**What**: Secret keys and environment variables
**Files**:
- `.env` (SECRET_KEY, DB_PASSWORD, API keys)
- `docker-compose.yml` (container configuration)

**Security**: ⚠️ Contains secrets, must be encrypted or restricted access

**Size**: ~5 KB
**Criticality**: ⭐⭐⭐ CRITICAL (system won't start without it)

---

#### 3. **Platform Code** 💻
**What**: Complete platform_v2 directory
**Directories**:
- `tools/` (all admin tools, routes)
- `templates/` (HTML templates)
- `static/` (CSS, JS, images)
- `consciousness/` (memory manager, awareness system)
- `app.py` (main application)
- `*.py` files (root Python files)

**Size**: ~10-50 MB
**Criticality**: ⭐⭐⭐ CRITICAL (entire platform)

---

#### 4. **Documentation** 📚
**What**: All documentation files
**Directory**: `/docs`
**Files**:
- CHANGELOG.md
- ARCHIE_CONSCIOUSNESS.md
- AGENT_DIRECTORY.md
- API_REFERENCE.md (when created)
- All other .md files

**Size**: ~5 MB
**Criticality**: ⭐⭐ HIGH (knowledge preservation)

---

#### 5. **AI Bridge** 🤖
**What**: AI integration layer
**Directory**: `/ai_bridge`
**Purpose**: Connection to Claude API, Ollama, etc.

**Size**: ~5 MB
**Criticality**: ⭐⭐ HIGH (AI functionality)

---

#### 6. **Database Migrations** 🔄
**What**: Schema change history
**Directory**: `/database/migrations`
**Files**: All migration scripts
**Purpose**: Recreate database structure if needed

**Size**: ~1 MB
**Criticality**: ⭐⭐ HIGH (database schema)

---

### Important Components (Should Have):

#### 7. **Scripts** 📜
**What**: Utility and maintenance scripts
**Directory**: `/scripts`
**Examples**:
- `generate_secrets.py`
- `ingest_all_docs.py`
- Backup scripts
- Maintenance scripts

**Size**: ~2 MB
**Criticality**: ⭐⭐ HIGH (automation)

---

#### 8. **n8n Workflows** 🔗
**What**: Workflow automation definitions
**Directory**: `/n8n_workflows`
**Purpose**: Automation workflows, integrations

**Size**: ~5-10 MB
**Criticality**: ⭐⭐ HIGH (if used for critical automation)

---

#### 9. **n8n Persistence** 💾
**What**: n8n data and configurations
**Directory**: `/persistence/n8n`
**Contents**: Workflow executions, credentials, settings

**Size**: ~10-50 MB
**Criticality**: ⭐ MEDIUM (can be recreated)

---

### Optional Components (Nice to Have):

#### 10. **Logs** 📊
**What**: Application logs (if stored)
**Purpose**: Debugging, audit trail
**Size**: Varies greatly
**Criticality**: ⭐ LOW (regenerated)

#### 11. **User Uploads** 📁
**What**: Any user-uploaded files
**Directory**: TBD (if exists)
**Size**: Varies
**Criticality**: ⭐⭐ (depends on content)

#### 12. **Custom Nginx Config** 🌐
**What**: Custom nginx configurations
**File**: `/nginx/nginx.conf`
**Size**: ~5 KB
**Criticality**: ⭐ MEDIUM

---

## 🎯 Proposed Backup System Design

### Backup Types:

#### 1. **Full Backup** (Everything)
**Components**:
- ✅ Database (pg_dump)
- ✅ Environment config (.env, docker-compose.yml)
- ✅ Platform code (platform_v2/)
- ✅ Documentation (docs/)
- ✅ AI Bridge (ai_bridge/)
- ✅ Database migrations (database/migrations/)
- ✅ Scripts (scripts/)
- ✅ n8n workflows (n8n_workflows/)
- ✅ n8n persistence (persistence/n8n/)
- ✅ Nginx config (nginx/)

**Size**: ~100-200 MB
**Time**: ~30-60 seconds
**Use Case**: Before major updates, weekly scheduled backups

---

#### 2. **Critical Backup** (Essential Only)
**Components**:
- ✅ Database (pg_dump)
- ✅ Environment config (.env)
- ✅ Platform code (platform_v2/)
- ✅ Documentation (docs/)

**Size**: ~30-50 MB
**Time**: ~10-15 seconds
**Use Case**: Daily scheduled backups, before code changes

---

#### 3. **Database Only**
**Components**:
- ✅ Database (pg_dump)

**Size**: ~5-20 MB
**Time**: ~5 seconds
**Use Case**: Before database migrations, hourly if needed

---

#### 4. **Custom Backup** (User Selects)
**Components**: User chooses from checklist:
- [ ] Database
- [ ] Environment Config
- [ ] Platform Code
- [ ] Documentation
- [ ] AI Bridge
- [ ] Database Migrations
- [ ] Scripts
- [ ] n8n Workflows
- [ ] n8n Persistence
- [ ] Nginx Config
- [ ] Logs

**Size**: Varies
**Time**: Varies
**Use Case**: Specific component updates, testing

---

## 🖥️ Interface Design

### Backup Manager Interface:

```
╔═══════════════════════════════════════════════════════════════════════╗
║                        💾 BACKUP MANAGER                              ║
╚═══════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────┐
│ 📊 BACKUP STATISTICS                                                │
├─────────────────────────────────────────────────────────────────────┤
│  Total Backups: 12          Latest: 2025-12-29 21:00:00            │
│  Total Size: 1.2 GB         Oldest: 2025-12-15 10:30:00            │
│  Current Build: #45         Space Used: 1.2 GB / 100 GB            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ ⚡ QUICK BACKUP                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [🔵 FULL BACKUP]    [🟢 CRITICAL ONLY]    [🟡 DATABASE ONLY]      │
│                                                                      │
│  Description: [_____________________________________________]        │
│                                                                      │
│  [ ] Set as current build                                           │
│  [ ] Schedule automated backups                                     │
│                                                                      │
│                     [+ CREATE BACKUP]                               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 🎯 CUSTOM BACKUP (Select Components)                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  CRITICAL COMPONENTS:                                                │
│   [✓] Database (PostgreSQL dump)                    ~10 MB          │
│   [✓] Environment Config (.env, docker-compose)     ~5 KB           │
│   [✓] Platform Code (platform_v2/)                  ~30 MB          │
│   [✓] Documentation (docs/)                         ~5 MB           │
│                                                                      │
│  IMPORTANT COMPONENTS:                                               │
│   [✓] AI Bridge (ai_bridge/)                        ~5 MB           │
│   [✓] Database Migrations (database/migrations/)    ~1 MB           │
│   [✓] Scripts (scripts/)                            ~2 MB           │
│   [ ] n8n Workflows (n8n_workflows/)                ~5 MB           │
│   [ ] n8n Persistence (persistence/n8n/)            ~20 MB          │
│                                                                      │
│  OPTIONAL COMPONENTS:                                                │
│   [ ] Nginx Config (nginx/)                         ~5 KB           │
│   [ ] Logs (if available)                           ~50 MB          │
│                                                                      │
│  Estimated Size: ~58 MB   Estimated Time: ~15 seconds               │
│                                                                      │
│  Description: [_____________________________________________]        │
│                                                                      │
│                  [+ CREATE CUSTOM BACKUP]                           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ 📋 EXISTING BACKUPS                                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Build #45 | 2025-12-29 21:00 | Full Backup | 95 MB                │
│  ├─ Components: Database, Config, Platform, Docs, AI Bridge...     │
│  └─ [⬇ Download] [🔄 Restore] [🗑️ Delete] [ℹ️ Details]            │
│                                                                      │
│  Build #44 | 2025-12-29 06:00 | Critical Only | 45 MB              │
│  ├─ Components: Database, Config, Platform, Docs                   │
│  └─ [⬇ Download] [🔄 Restore] [🗑️ Delete] [ℹ️ Details]            │
│                                                                      │
│  Build #43 | 2025-12-28 21:00 | Database Only | 12 MB              │
│  ├─ Components: Database                                            │
│  └─ [⬇ Download] [🔄 Restore] [🗑️ Delete] [ℹ️ Details]            │
│                                                                      │
│                        [Show More...]                               │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ ⏰ SCHEDULED BACKUPS                                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [ Enable Automatic Backups ]                                       │
│                                                                      │
│  Daily Full Backup:         [02:00 AM] ▼   [✓ Enabled]            │
│  Hourly Database Backup:    [Every hour]   [✓ Enabled]            │
│  Weekly Archive:            [Sunday 03:00] [✓ Enabled]            │
│                                                                      │
│  Retention Policy:                                                   │
│   Keep last 7 daily backups                                         │
│   Keep last 4 weekly backups                                        │
│   Keep monthly backups for 6 months                                 │
│                                                                      │
│                       [💾 Save Schedule]                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Technical Implementation

### Backend Route Structure:

```python
# /tools/ (now split into standalone modules)

@admin_bp.route('/backups/api/create-full', methods=['POST'])
def create_full_backup():
    """Create full system backup (all components)"""

@admin_bp.route('/backups/api/create-critical', methods=['POST'])
def create_critical_backup():
    """Create critical components backup"""

@admin_bp.route('/backups/api/create-database', methods=['POST'])
def create_database_backup():
    """Create database-only backup"""

@admin_bp.route('/backups/api/create-custom', methods=['POST'])
def create_custom_backup():
    """Create custom backup with selected components"""
    # Request body: { "components": ["database", "platform", "docs", ...], "description": "..." }

@admin_bp.route('/backups/api/restore', methods=['POST'])
def restore_backup():
    """Restore from backup (with component selection)"""

@admin_bp.route('/backups/api/schedule', methods=['POST'])
def set_backup_schedule():
    """Configure automatic backup schedule"""
```

### Backup Function Structure:

```python
def create_backup(components: list, description: str, user: User):
    """
    Create backup with selected components

    Args:
        components: List of component names to backup
        description: Backup description
        user: User creating the backup

    Returns:
        Backup metadata and path
    """
    backup_path = generate_backup_path()
    metadata = {
        'build_number': get_next_build_number(),
        'timestamp': datetime.now().isoformat(),
        'description': description,
        'created_by': user.username,
        'components': {}
    }

    if 'database' in components:
        backup_database(backup_path)
        metadata['components']['database'] = get_database_stats()

    if 'environment' in components:
        backup_environment(backup_path)
        metadata['components']['environment'] = {'files': ['.env', 'docker-compose.yml']}

    if 'platform' in components:
        backup_platform_code(backup_path)
        metadata['components']['platform'] = get_platform_stats()

    # ... more components

    save_metadata(backup_path, metadata)
    return metadata
```

### Component Backup Functions:

```python
def backup_database(backup_path):
    """Backup database using pg_dump"""
    import subprocess
    output_file = os.path.join(backup_path, 'database.sql')
    cmd = [
        'docker', 'exec', 'archie_database',
        'pg_dump', '-U', 'archie', '-d', 'archie'
    ]
    with open(output_file, 'w') as f:
        subprocess.run(cmd, stdout=f, check=True)

def backup_environment(backup_path):
    """Backup environment configuration"""
    import shutil
    env_dir = os.path.join(backup_path, 'config')
    os.makedirs(env_dir, exist_ok=True)

    # Copy .env (encrypt if needed)
    shutil.copy('/mnt/archie_brain/.env', env_dir)
    shutil.copy('/mnt/archie_brain/docker-compose.yml', env_dir)

def backup_platform_code(backup_path):
    """Backup complete platform_v2 directory"""
    import shutil
    platform_backup = os.path.join(backup_path, 'platform_v2')
    shutil.copytree('/mnt/archie_brain/platform_v2', platform_backup)

def backup_documentation(backup_path):
    """Backup all documentation"""
    import shutil
    docs_backup = os.path.join(backup_path, 'docs')
    shutil.copytree('/mnt/archie_brain/docs', docs_backup)

# ... more component backup functions
```

---

## 📊 Metadata Format

Each backup includes a `metadata.json` file:

```json
{
  "backup_name": "20251229_210000_full_backup",
  "build_number": 45,
  "backup_type": "full",
  "timestamp": "2025-12-29T21:00:00",
  "description": "Full system backup before major update",
  "created_by": "admin",
  "created_at": "2025-12-29T21:00:15",
  "platform_version": "1.2.0",
  "components": {
    "database": {
      "method": "pg_dump",
      "size_mb": 12.5,
      "tables": 15,
      "records": 5420,
      "file": "database.sql"
    },
    "environment": {
      "files": [".env", "docker-compose.yml"],
      "size_kb": 5.2,
      "path": "config/"
    },
    "platform": {
      "size_mb": 28.3,
      "files": 245,
      "path": "platform_v2/"
    },
    "documentation": {
      "size_mb": 4.8,
      "files": 20,
      "path": "docs/"
    },
    "ai_bridge": {
      "size_mb": 3.2,
      "path": "ai_bridge/"
    },
    "database_migrations": {
      "size_mb": 0.8,
      "path": "database/migrations/"
    },
    "scripts": {
      "size_mb": 1.5,
      "path": "scripts/"
    }
  },
  "total_size_mb": 51.1,
  "backup_duration_seconds": 18.5,
  "status": "completed",
  "checksum": "sha256:abc123..."
}
```

---

## 🤖 Agent Integration

### For Backup Agent:

The backup agent will use the same API endpoints:

```python
# Agent can call:
POST /tools/backup-manager//api/create-full
POST /tools/backup-manager//api/create-critical
POST /tools/backup-manager//api/create-database
POST /tools/backup-manager//api/create-custom

# With authentication token
# And component selection for custom backups
```

**Agent Capabilities**:
- Schedule automated backups
- Monitor backup health
- Alert on backup failures
- Clean up old backups based on retention policy
- Verify backup integrity

---

## 🎯 Implementation Plan

### Phase 1: Core Improvements (2-3 hours)
1. ✅ Fix database backup to use proper pg_dump
2. ✅ Add environment config backup
3. ✅ Add all platform_v2 files to backup
4. ✅ Add documentation backup
5. ✅ Update metadata format

### Phase 2: Component Selection (2-3 hours)
1. ✅ Create component selection UI
2. ✅ Implement custom backup function
3. ✅ Add preset backup types (Full, Critical, Database)
4. ✅ Add size estimation before backup

### Phase 3: Enhanced Features (3-4 hours)
1. ✅ Add AI bridge backup
2. ✅ Add migrations backup
3. ✅ Add scripts backup
4. ✅ Add n8n workflows backup
5. ✅ Add progress indicator
6. ✅ Add backup verification

### Phase 4: Scheduling & Automation (2-3 hours)
1. ✅ Implement scheduled backups
2. ✅ Add retention policy
3. ✅ Add backup rotation
4. ✅ Add email/notification on completion

**Total Estimated Time**: 9-13 hours

---

## 🔒 Security Considerations

1. **Encrypt .env File**: Contains secrets
2. **Access Control**: Only admins can create/download/restore
3. **Audit Log**: Track who creates/restores backups
4. **Backup Encryption**: Optional encryption for full backups
5. **Secure Storage**: Backups stored outside web root
6. **Download Security**: Temporary download links with expiration

---

## 📝 Recommendations

### Immediate:
1. **Fix pg_dump**: Current database backup won't restore properly
2. **Add .env backup**: System won't start without it
3. **Component selection**: Allow custom backups

### Short-term:
1. **Scheduled backups**: Daily full, hourly database
2. **Retention policy**: Auto-delete old backups
3. **Progress indicator**: Show backup progress

### Long-term:
1. **Remote backup**: S3, Google Drive, etc.
2. **Backup verification**: Test restore periodically
3. **Incremental backups**: Faster backups, less storage

---

**Created**: 2025-12-29
**Author**: Claude (Sonnet 4.5)
**Status**: Proposal - Ready for Implementation
**Priority**: HIGH
