# 🤖 A.R.C.H.I.E. PLATFORM - COMPLETE DOCUMENTATION
**Last Updated:** December 27, 2025
**Version:** 1.0 ✅ FULLY OPERATIONAL

---

## 📋 PROJECT OVERVIEW

**A.R.C.H.I.E.** (Adaptive Reasoning & Cognitive Heuristic Intelligence Engine)  
AI-powered productivity platform with code editing, chat, and document processing.

**Live URL:** http://192.168.1.200:3000  
**Dashboard:** http://192.168.1.200:3000/tools/ standalone modules  
**Status:** ✅ OPERATIONAL

---

## ✅ CURRENT FEATURES (v1.0)

### **Core Platform:**
- User authentication (login/signup/logout)
- Admin panel with user management (all 14 sections working)
- **Backup Manager module** - integrated and fully functional ✅
- Role-based access control (user, admin)
- PostgreSQL database (26+ tables)
- Docker containerization
- Session management
- Audit logging
- Matrix green theme (#00ff41)

### **AI Tools (Working):**
1. **A.R.C.H.I.E. Chat** - Conversational AI (qwen2.5-coder:7b via Ollama)
2. **Code Editor** - Monaco-based editor with AI assistance
3. **Text Summarizer** - Extract key insights from documents
4. **Document Q&A** - Ask questions about uploaded documents

### **AI Integration:**
- **Ollama** (Local AI): http://192.168.1.246:11434
- **Model:** qwen2.5-coder:7b
- **Response Time:** 10-20 seconds
- **Benefits:** 100% private, no API costs, fast responses

### **Technical Stack:**
- **Backend:** Flask + Python 3.11
- **Database:** PostgreSQL 16
- **AI:** Ollama (qwen2.5-coder:7b)
- **Frontend:** Jinja2 templates, vanilla JavaScript
- **Deployment:** Docker Compose
- **Editor:** Monaco (VS Code engine)

---

## 🗄️ DATABASE SCHEMA

### **Core Tables (v1.0):**
```
users                   - User accounts with role management
active_sessions         - Login session tracking  
audit_log              - System activity logging
failed_logins          - Security monitoring
projects               - User projects
tool_usage             - Feature analytics
improvement_proposals  - Self-improvement tracking (placeholder)
ai_conversations       - Chat history
```

**Total Tables:** 26+

### **Planned Tables (v2.0 - Future):**
```
user_websites          - Website management
project_files          - File system for IDE
project_chat_history   - AI chat per project
website_deployments    - Deployment tracking
subscription_plans     - Billing tiers
managed_dns_records    - DNS automation
```

---

## 🔌 INTEGRATIONS

### **Current (Active):**

#### **Ollama (Local AI)**
- **Status:** ✅ ACTIVE
- **URL:** http://192.168.1.246:11434
- **Model:** qwen2.5-coder:7b
- **Features:**
  - Code generation & explanation
  - Debugging assistance
  - Fast responses (10-20s)
  - 100% private (no external API)
  - No costs

#### **Docker**
- **Status:** ✅ ACTIVE
- **Containers:**
  - `archie_platform` - Main Flask app
  - `archie_database` - PostgreSQL 16
- **Network:** archie_network
- **Volumes:** Persistent database storage

### **Planned (v2.0 - Future):**
- GitHub (Website deployment)
- Hostinger DNS (Domain automation)
- Stripe (Billing - optional)
- Printful (Merchandise store - optional)

---

## 📁 FILE STRUCTURE

```
/mnt/archie_brain/
├── platform_v2/                # Main application
│   ├── app.py                  # Flask application
│   ├── ai_bridge/
│   │   └── archie_bridge.py    # AI integration layer
│   ├── templates/
│   │   ├── base.html           # Base template
│   │   ├── dashboard.html      # Main dashboard
│   │   ├── login.html          # Login page
│   │   └── tools/
│   │       ├── chat.html       # A.R.C.H.I.E. chat
│   │       ├── code_editor.html # Code editor
│   │       ├── text_summarizer.html
│   │       ├── document_qa.html
│   │       └── modular templates      # Admin panel
│   ├── tools/                  # Tool modules
│   │   ├── chat/
│   │   ├── code_editor/
│   │   └── admin/
│   └── requirements.txt        # Python dependencies
├── backups/                    # System backups
│   └── 20251227_005213/       # Latest backup (working state)
├── docs/                       # Documentation
│   ├── PLATFORM_DOCUMENTATION.md
│   ├── SESSION_HANDOFF.md
│   ├── TODO_LIST.md
│   ├── BACKUP_RECOVERY_GUIDE.md
│   ├── ADMIN_REFERENCE.md
│   └── QUICK_REFERENCE.md
├── docker-compose.yml          # Docker configuration
└── .env                        # Environment variables
```

---

## 🚀 DEPLOYMENT & MANAGEMENT

### **Start Platform:**
```bash
cd /mnt/archie_brain
docker-compose up -d
```

### **Stop Platform:**
```bash
docker-compose down
```

### **View Logs:**
```bash
docker logs archie_platform -f
```

### **Restart:**
```bash
docker-compose restart archie_platform
```

### **Database Access:**
```bash
docker exec -it archie_database psql -U archie -d archie
```

### **Backup (IMPORTANT - Do before any changes!):**
```bash
# Quick backup
BACKUP_DIR="/mnt/archie_brain/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
docker exec archie_database pg_dump -U archie archie > "$BACKUP_DIR/database_backup.sql"
cp -r /mnt/archie_brain/platform_v2 "$BACKUP_DIR/platform_v2"
echo "Backup created: $BACKUP_DIR"
```

### **Restore from Backup:**
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

## 🔧 CONFIGURATION

### **Environment Variables (.env):**
```env
# Database
DB_HOST=archie_database
DB_PORT=5432
DB_NAME=archie
DB_USER=archie
DB_PASSWORD=your_secure_password

# Flask
SECRET_KEY=your_secret_key_here
FLASK_ENV=production

# AI (Ollama)
OLLAMA_HOST=http://192.168.1.246:11434
OLLAMA_MODEL=qwen2.5-coder:7b

# Future integrations (optional)
GITHUB_TOKEN=ghp_...
HOSTINGER_API_TOKEN=...
STRIPE_SECRET_KEY=sk_...
```

---

## 👤 USER MANAGEMENT

### **Create Admin User:**
```bash
docker exec -it archie_database psql -U archie -d archie

UPDATE users SET is_admin = TRUE WHERE username = 'your_username';

\q
```

### **User Roles:**
- **User:** Basic access to all tools
- **Admin:** Full platform access + dashboard

---

## 📊 CURRENT TOOLS

### **1. A.R.C.H.I.E. Chat** ✅
**Location:** `/tools/chat`  
**Features:**
- Real-time AI conversations with qwen2.5-coder
- Fast responses (10-20s)
- Code generation capability
- Context-aware responses
- Conversation history

### **2. Code Editor** ✅
**Location:** `/tools/code-editor`  
**Features:**
- Monaco editor (VS Code engine)
- Syntax highlighting
- AI chat sidebar
- File management
- Code generation assistance
- Multi-language support

### **3. Text Summarizer** ✅
**Location:** `/tools/text-summarizer`  
**Features:**
- Extract key insights from text
- Document summarization
- Quick analysis

### **4. Document Q&A** ✅
**Location:** `/tools/document-qa`  
**Features:**
- Upload documents
- Ask questions
- AI-powered answers
- Context extraction

---

## 🛡️ SECURITY

### **Implemented:**
- ✅ Password hashing (Werkzeug)
- ✅ Session management (Flask-Login)
- ✅ Failed login tracking
- ✅ Admin-only routes
- ✅ Audit logging
- ✅ CSRF protection
- ✅ Database localhost-only (not exposed)

### **Best Practices:**
- Keep .env file secure (600 permissions)
- Regular backups (especially before changes!)
- Monitor failed login attempts
- Review audit logs
- Update dependencies regularly

---

## 🐛 TROUBLESHOOTING

### **Platform Won't Start:**
```bash
# Check logs
docker logs archie_platform

# Common issues:
# - Import errors → Check Python dependencies
# - Database connection → Verify .env settings
# - Port conflicts → Check port 3000 availability

# Rebuild if needed
docker-compose down
docker-compose build archie_platform
docker-compose up -d
```

### **Can't Login:**
```bash
# Check if user exists and is active
docker exec -it archie_database psql -U archie -d archie

SELECT username, is_active, is_admin FROM users;

# Activate user if needed
UPDATE users SET is_active = TRUE WHERE username = 'username';
```

### **AI Not Responding:**
```bash
# Check Ollama server
curl http://192.168.1.246:11434/api/tags

# Should return list of models including qwen2.5-coder:7b
```

### **Database Issues:**
```bash
# Check database status
docker exec archie_database pg_isready -U archie

# View tables
docker exec archie_database psql -U archie -d archie -c "\dt"

# Check connections
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM pg_stat_activity;"
```

---

## 📈 ANALYTICS

### **Available Metrics:**
- User registrations
- Tool usage by type
- Failed login attempts
- Session activity
- System health (CPU, RAM, Disk)

### **View Analytics:**
- Navigate to `/tools/consciousness` for knowledge analytics
- Use `/tools/blueprint` for system overview
- Export data from individual modules

---

## 🔄 VERSION HISTORY

### **v1.0 (Current) - December 26, 2025** ✅
- Stable platform with 4 working tools
- Ollama AI integration (qwen2.5-coder:7b)
- Matrix green theme
- Admin panel
- User management
- Code editor with AI
- Backup/restore tested ✅

### **v2.0 (Planned) - Future**
- Website Manager tool
- GitHub integration
- Hostinger DNS automation
- Docker app hosting
- A.R.C.H.I.E. Core (admin code management)
- Subscription billing (optional)
- Enhanced backup UI

---

## 📞 QUICK REFERENCE

### **URLs:**
- Platform: http://localhost:3000
- Dashboard: http://localhost:3000/dashboard
- Blueprint: http://localhost:3000/tools/blueprint
- Chat: http://localhost:3000/tools/archie-chat
- Code Editor: http://localhost:3000/tools/code-editor

### **Common Commands:**
```bash
# Platform status
docker ps | grep archie

# Restart
docker-compose restart archie_platform

# Logs
docker logs archie_platform -f

# Backup
docker exec archie_database pg_dump -U archie archie > backup.sql

# System health
docker stats archie_platform archie_database
```

---

## 🎯 NEXT STEPS

See `TODO_LIST.md` for detailed roadmap.

**Immediate Priorities:**
1. Build backup management UI in dashboard ⭐
2. Add documentation viewer in dashboard ⭐
3. Plan v2.0 deployment strategy carefully
4. Test backup/restore workflow thoroughly

---

## 📚 ADDITIONAL DOCUMENTATION

- **SESSION_HANDOFF.md** - Latest session summary
- **BACKUP_RECOVERY_GUIDE.md** - Complete backup procedures
- **ADMIN_REFERENCE.md** - All admin commands
- **QUICK_REFERENCE.md** - One-page cheat sheet
- **TODO_LIST.md** - Feature roadmap
- **FILE_STRUCTURE_MASTER.md** - Complete file structure
- **AI_POWERED_CODE_EDITOR.md** - Code editor details
- **AI_POWERED_APPS.md** - AI capabilities
- **DEPLOYMENT_CHECKLIST.md** - Deployment guide

---

**Last Updated:** December 27, 2025
**Platform Version:** 1.0
**Status:** ✅ FULLY OPERATIONAL
**AI Model:** qwen2.5-coder:7b (Ollama)
**Database:** PostgreSQL 16
**Recent Fix:** Backup Manager navigation handler (December 27, 2025)
**Next Version:** 1.1 (Enhanced features + Docs Viewer)
**Next Major:** 2.0 (Website Manager + DNS)

**Remember:** Always backup before making changes! 💾
