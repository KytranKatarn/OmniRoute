# A.R.C.H.I.E. Backup Manager - Migration & Node Integration Plan

**Phase**: 31 - System Migration & Distributed Backup
**Status**: Planning
**Last Updated**: 2026-01-21

## Overview

Enhance the existing Backup Manager to support:
1. **Full System Migration** - Move ARCHIE from one machine to another
2. **Cloning/Mirroring** - Create identical instances on nodes
3. **Node Integration** - Push/pull backups to/from remote nodes
4. **Docker Deployment Packages** - Self-contained deployable archives

## Current State (What Exists)

The Backup Manager (`/tools/backup-manager`) already has:
- 11 component backup (database, platform, docs, ai_bridge, n8n, etc.)
- Full system restore with auto-generated rollback scripts
- Module-level backup/restore for testing
- Sandbox deployment (schema isolation + Docker containers)
- GFS retention policy (7 daily / 4 weekly / 6 monthly)
- Programmatic API for automation
- 65 existing backups totaling 3.2GB

**What's Missing for Migration:**
- Remote node backup targets
- Incremental/differential sync
- Migration wizard UI
- Deployment package generator
- Node-to-node replication
- Health verification after restore

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CENTRAL ARCHIE (192.168.1.200)                   │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Backup Manager (Enhanced)                                    │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐  │  │
│  │  │ Local       │ │ Node        │ │ Migration               │  │  │
│  │  │ Backups     │ │ Targets     │ │ Wizard                  │  │  │
│  │  │ /backups/   │ │ Push/Pull   │ │ Full system transfer    │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │ Local              │ Node API           │ SCP/rsync
         │ Storage            │ Integration        │ Direct Transfer
         ▼                    ▼                    ▼
    ┌─────────┐         ┌─────────┐         ┌─────────────────┐
    │ /backups│         │ Node    │         │ Target Machine  │
    │ folder  │         │ 109     │         │ (New ARCHIE)    │
    └─────────┘         └─────────┘         └─────────────────┘
```

---

## Feature 1: Migration Wizard

### Purpose
Guide admin through moving ARCHIE to a new machine with step-by-step process.

### UI Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  MIGRATION WIZARD                                    [Step 1/5] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ● Step 1: Pre-Flight Check                                    │
│  ○ Step 2: Create Migration Backup                             │
│  ○ Step 3: Transfer to Target                                  │
│  ○ Step 4: Deploy on Target                                    │
│  ○ Step 5: Verify & Switch                                     │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  PRE-FLIGHT CHECKLIST:                                         │
│                                                                 │
│  [✓] Database connection healthy                               │
│  [✓] All services running                                      │
│  [✓] Sufficient disk space for backup (need: 500MB, have: 20GB)│
│  [✓] No active improvement deployments                         │
│  [ ] Target machine reachable: _______________                 │
│  [ ] Target has Docker installed                               │
│  [ ] Target has sufficient resources                           │
│                                                                 │
│  [Check Target]                    [Next: Create Backup →]     │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Steps

1. **Pre-Flight Check** (`/api/migration/preflight`)
   - Verify all services healthy
   - Check disk space
   - Verify no pending deployments
   - Test target machine connectivity (SSH/API)

2. **Create Migration Backup** (`/api/migration/create-package`)
   - Full backup with all 11 components
   - Include Docker images list
   - Generate deployment script
   - Create checksums for verification

3. **Transfer to Target** (`/api/migration/transfer`)
   - SCP/rsync to target machine
   - Progress tracking
   - Resume capability for large transfers

4. **Deploy on Target** (`/api/migration/deploy`)
   - SSH to target and run deployment script
   - Pull Docker images
   - Restore database
   - Start services

5. **Verify & Switch** (`/api/migration/verify`)
   - Health check on target
   - Compare data integrity
   - DNS/IP switch instructions
   - Decommission old instance option

---

## Feature 2: Deployment Package Generator

### Purpose
Create self-contained archives that can deploy ARCHIE on any Docker-capable machine.

### Package Contents

```
archie-deployment-v5.37.0-20260121.tar.gz
├── deploy.sh                    # One-command deployment script
├── docker-compose.yml           # Container orchestration
├── .env.template                # Environment template
├── database.sql                 # Full database dump
├── platform_v2/                 # Application code
├── ai_bridge/                   # AI integration
├── docs/                        # Documentation
├── nginx/                       # Reverse proxy config
├── scripts/                     # Utility scripts
├── DEPLOY_README.md             # Instructions
└── checksums.sha256             # File integrity verification
```

### deploy.sh Script

```bash
#!/bin/bash
# A.R.C.H.I.E. Deployment Script
# Usage: ./deploy.sh [target_dir] [db_password]

set -e

TARGET_DIR="${1:-/mnt/archie_brain}"
DB_PASSWORD="${2:-$(openssl rand -base64 32)}"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║       A.R.C.H.I.E. Deployment Package Installer           ║"
echo "╚═══════════════════════════════════════════════════════════╝"

# Check prerequisites
check_docker() { ... }
check_disk_space() { ... }

# Create directory structure
mkdir -p "$TARGET_DIR"
cp -r platform_v2 ai_bridge docs nginx scripts "$TARGET_DIR/"

# Configure environment
cp .env.template "$TARGET_DIR/.env"
sed -i "s/DB_PASSWORD=.*/DB_PASSWORD=$DB_PASSWORD/" "$TARGET_DIR/.env"

# Start containers
cd "$TARGET_DIR"
docker-compose up -d archie_database
sleep 10  # Wait for database

# Restore database
docker exec -i archie_database psql -U archie -d archie < database.sql

# Start platform
docker-compose up -d

# Verify
curl -f http://localhost:3000/health || echo "Warning: Health check failed"

echo "Deployment complete! Access at http://localhost:3000"
```

### API Endpoints

```python
# Generate deployment package
@backup_manager_bp.route('/api/create-deployment-package', methods=['POST'])
def create_deployment_package():
    """Create self-contained deployment archive"""
    # Options: include_docker_images, target_platform, version_tag

# Download deployment package
@backup_manager_bp.route('/api/download-deployment/<package_name>')
def download_deployment_package(package_name):
    """Stream deployment package download"""
```

---

## Feature 3: Node Backup Integration

### Purpose
Push backups to nodes for redundancy, or pull backups from nodes for central storage.

### Node Backup Targets

```python
# Database schema addition
CREATE TABLE backup_targets (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id),
    target_type VARCHAR(20),  -- 'push', 'pull', 'mirror'
    target_path VARCHAR(500),
    enabled BOOLEAN DEFAULT TRUE,
    last_sync TIMESTAMP,
    sync_frequency VARCHAR(20),  -- 'hourly', 'daily', 'manual'
    retention_days INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Sync Operations

```python
# Push backup to node
@backup_manager_bp.route('/api/nodes/<node_id>/push-backup', methods=['POST'])
def push_backup_to_node(node_id):
    """Transfer backup archive to remote node"""
    # Uses node's API key for authentication
    # Streams via HTTP or uses SCP if SSH available

# Pull backup from node
@backup_manager_bp.route('/api/nodes/<node_id>/pull-backup', methods=['POST'])
def pull_backup_from_node(node_id):
    """Retrieve backup from remote node to central"""

# Set up mirror relationship
@backup_manager_bp.route('/api/nodes/<node_id>/setup-mirror', methods=['POST'])
def setup_node_mirror(node_id):
    """Configure node as backup mirror with auto-sync"""
```

### Node Client Enhancement

Add to `archie_node.py`:

```python
# Receive backup from central
@app.route('/api/receive-backup', methods=['POST'])
def receive_backup():
    """Accept backup upload from central ARCHIE"""
    # Verify API key
    # Stream to local backup directory
    # Verify checksum

# Serve backup to central
@app.route('/api/serve-backup/<backup_name>')
def serve_backup(backup_name):
    """Stream backup archive to central"""
```

---

## Feature 4: Mirror Mode (Hot Standby)

### Purpose
Keep a node synchronized as a hot standby that can take over if central fails.

### Architecture

```
┌─────────────────────┐         ┌─────────────────────┐
│  CENTRAL (Primary)  │ ──────► │  NODE (Mirror)      │
│  192.168.1.200      │  Sync   │  192.168.1.200      │
│                     │         │                     │
│  - Full ARCHIE      │         │  - Full ARCHIE      │
│  - PostgreSQL       │         │  - PostgreSQL       │
│  - All services     │         │  - All services     │
│                     │         │  (standby mode)     │
└─────────────────────┘         └─────────────────────┘
         │                               │
         │ Health fails                  │ Promoted
         ▼                               ▼
    [Failover trigger]  ───────►  [Becomes Primary]
```

### Sync Strategy

1. **Database Replication** - PostgreSQL streaming replication or periodic dumps
2. **File Sync** - rsync with incremental transfer
3. **Config Sync** - Environment variables (excluding secrets)
4. **Docker State** - Container configuration sync

### Failover Process

```python
# Promote mirror to primary
@backup_manager_bp.route('/api/nodes/<node_id>/promote', methods=['POST'])
def promote_node_to_primary(node_id):
    """Promote mirror node to primary ARCHIE"""
    # 1. Verify node is healthy
    # 2. Stop sync from old primary
    # 3. Update DNS/load balancer
    # 4. Notify connected nodes of new primary
```

---

## Feature 5: Backup Manager UI Enhancements

### New Tabs

```
┌─────────────────────────────────────────────────────────────────┐
│  BACKUP MANAGER                                                 │
├─────────────────────────────────────────────────────────────────┤
│  [Backups] [Retention] [Migration] [Nodes] [Deployment]        │
└─────────────────────────────────────────────────────────────────┘
```

### Migration Tab

- Migration Wizard button
- Migration history
- Active migration status
- Target machine selector (from Node Network)

### Nodes Tab

- List nodes with backup capabilities
- Configure push/pull targets
- Sync status and last sync time
- Manual sync buttons
- Mirror setup wizard

### Deployment Tab

- Create deployment package
- Package history
- Download links
- Deploy instructions
- Version tagging

---

## Database Migrations

### Migration 068: Backup Targets

```sql
-- Migration 068: Backup node integration

-- Backup targets for node sync
CREATE TABLE IF NOT EXISTS backup_targets (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    target_type VARCHAR(20) NOT NULL,  -- push, pull, mirror
    target_path VARCHAR(500) DEFAULT '/backups',
    enabled BOOLEAN DEFAULT TRUE,
    sync_frequency VARCHAR(20) DEFAULT 'daily',
    retention_days INTEGER DEFAULT 30,
    last_sync_at TIMESTAMP,
    last_sync_status VARCHAR(20),
    last_sync_error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Migration history
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    source_host VARCHAR(255),
    target_host VARCHAR(255),
    target_node_id INTEGER REFERENCES remote_nodes(id),
    backup_name VARCHAR(255),
    status VARCHAR(20),  -- pending, transferring, deploying, verifying, completed, failed
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    error_message TEXT,
    verification_result JSONB
);

-- Deployment packages
CREATE TABLE IF NOT EXISTS deployment_packages (
    id SERIAL PRIMARY KEY,
    package_name VARCHAR(255) UNIQUE,
    version_tag VARCHAR(50),
    backup_source VARCHAR(255),
    file_path VARCHAR(500),
    file_size BIGINT,
    checksum VARCHAR(64),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    download_count INTEGER DEFAULT 0
);

-- Indexes
CREATE INDEX idx_backup_targets_node ON backup_targets(node_id);
CREATE INDEX idx_migration_history_status ON migration_history(status);
CREATE INDEX idx_deployment_packages_version ON deployment_packages(version_tag);
```

---

## Implementation Order

### Phase 31.1: Deployment Package Generator
1. [ ] Create deployment package structure
2. [ ] Generate deploy.sh script
3. [ ] Add checksum verification
4. [ ] UI for package creation/download
5. [ ] Test on fresh Ubuntu VM

### Phase 31.2: Migration Wizard
6. [ ] Pre-flight check API
7. [ ] Transfer mechanism (SCP/HTTP)
8. [ ] Remote deployment execution
9. [ ] Verification and health check
10. [ ] Wizard UI with step progress

### Phase 31.3: Node Backup Integration
11. [ ] Database migration for backup_targets
12. [ ] Push backup to node API
13. [ ] Pull backup from node API
14. [ ] Node client backup endpoints
15. [ ] UI for node backup management

### Phase 31.4: Mirror Mode (Future)
16. [ ] Database replication setup
17. [ ] File sync daemon
18. [ ] Failover detection
19. [ ] Promotion mechanism
20. [ ] Load balancer integration

---

## Security Considerations

1. **Backup Encryption** - Encrypt backups before transfer
2. **API Key Verification** - All node communication authenticated
3. **SSH Key Management** - For SCP transfers
4. **Audit Logging** - Log all migration and sync activities
5. **Secret Handling** - Never include plaintext secrets in deployment packages

---

## Success Criteria

- [ ] Can create deployment package from UI
- [ ] deploy.sh works on fresh Ubuntu 22.04/24.04
- [ ] Migration wizard can move ARCHIE between machines
- [ ] Can push/pull backups to/from nodes
- [ ] Health verification after restore passes
- [ ] Admin-only access enforced throughout

---

## Related Documentation

- `/docs/NODE_MANAGEMENT_GUIDE.md` - Node Network setup
- `/docs/BACKUP_SYSTEM_REDESIGN.md` - Original backup design
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Project roadmap
