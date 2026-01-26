# 📁 A.R.C.H.I.E. FILE STRUCTURE MASTER
**Last Updated:** December 26, 2025  
**Version:** 1.0

---

## 🗂️ COMPLETE DIRECTORY STRUCTURE

```
/mnt/archie_brain/
├── platform_v2/                      # Main Flask application
│   ├── app.py                        # Flask app entry point
│   ├── requirements.txt              # Python dependencies
│   ├── .env                          # Environment variables (NEVER commit!)
│   │
│   ├── ai_bridge/                    # AI integration layer
│   │   ├── __init__.py
│   │   └── archie_bridge.py          # Ollama integration
│   │
│   ├── templates/                    # Jinja2 templates
│   │   ├── base.html                 # Base layout (Matrix theme)
│   │   ├── login.html                # Login page
│   │   ├── signup.html               # Signup page
│   │   ├── dashboard.html            # Main dashboard
│   │   │
│   │   └── tools/                    # Tool templates
│   │       ├── chat.html             # A.R.C.H.I.E. Chat
│   │       ├── code_editor.html      # Monaco Code Editor
│   │       ├── text_summarizer.html  # Text Summarizer
│   │       ├── document_qa.html      # Document Q&A
│   │       └── admin.html            # Admin Panel
│   │
│   ├── static/                       # Static files
│   │   ├── css/
│   │   │   └── style.css             # Custom styles
│   │   ├── js/
│   │   │   ├── dashboard.js
│   │   │   ├── chat.js
│   │   │   └── code_editor.js
│   │   └── images/
│   │       └── logo.png
│   │
│   └── tools/                        # Tool modules
│       ├── chat/
│       │   ├── __init__.py
│       │   └── routes.py             # Chat routes
│       │
│       ├── code_editor/
│       │   ├── __init__.py
│       │   └── routes.py             # Code editor routes
│       │
│       ├── text_summarizer/
│       │   ├── __init__.py
│       │   └── routes.py
│       │
│       ├── document_qa/
│       │   ├── __init__.py
│       │   └── routes.py
│       │
│       └── admin/
│           ├── __init__.py
│           └── routes.py             # Admin panel routes
│
├── backups/                          # System backups
│   ├── 20251227_005213/             # Latest working backup ✅
│   │   ├── database_backup.sql
│   │   ├── platform_v2/
│   │   └── .env
│   │
│   └── backup_YYYYMMDD_HHMMSS/      # Timestamped backups
│
├── docs/                             # Documentation
│   ├── PLATFORM_DOCUMENTATION.md
│   ├── SESSION_HANDOFF.md
│   ├── TODO_LIST.md
│   ├── BACKUP_RECOVERY_GUIDE.md
│   ├── ADMIN_REFERENCE.md
│   ├── QUICK_REFERENCE.md
│   ├── FILE_STRUCTURE_MASTER.md     # This file
│   ├── AI_POWERED_CODE_EDITOR.md
│   ├── AI_POWERED_APPS.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   └── README.md                     # Documentation index
│
├── docker-compose.yml                # Docker orchestration
├── Dockerfile                        # Platform container build
└── .gitignore                        # Git ignore patterns
```

---

## 📦 DOCKER VOLUMES

```
archie_database                       # PostgreSQL data volume
├── data/                            # Database files
└── backups/                         # Automatic DB backups (future)
```

---

## 🗄️ DATABASE SCHEMA (PostgreSQL)

### **Core Tables (26+ tables):**

```
Authentication & Users:
├── users                    # User accounts
├── active_sessions          # Login sessions
└── failed_logins            # Security tracking

Analytics:
├── audit_log                # System activity
└── tool_usage               # Feature usage stats

Projects:
├── projects                 # User projects
└── ai_conversations         # Chat history

System:
├── improvement_proposals    # Self-improvement (placeholder)
├── system_config            # Platform settings
└── service_status           # Health monitoring

... and 15+ more tables
```

---

## 🔧 CONFIGURATION FILES

### **.env (Environment Variables)**
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
```

**Security:** 
- Permissions: `600` (owner read/write only)
- **NEVER commit to git!**
- Listed in `.gitignore`

### **requirements.txt**
```txt
Flask==3.0.0
Flask-Login==0.6.3
psycopg2-binary==2.9.9
werkzeug==3.0.1
requests==2.31.0
python-dotenv==1.0.0
gunicorn==21.2.0
```

### **docker-compose.yml**
```yaml
services:
  archie_platform:
    build: .
    container_name: archie_platform
    ports:
      - "3000:3000"
    depends_on:
      - archie_database
    networks:
      - archie_network
    environment:
      - DB_HOST=archie_database
    volumes:
      - ./platform_v2:/app

  archie_database:
    image: postgres:16-alpine
    container_name: archie_database
    ports:
      - "127.0.0.1:5432:5432"  # Localhost only!
    networks:
      - archie_network
    volumes:
      - archie_database:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=archie
      - POSTGRES_USER=archie
      - POSTGRES_PASSWORD=${DB_PASSWORD}

networks:
  archie_network:
    driver: bridge

volumes:
  archie_database:
```

---

## 📝 KEY FILES EXPLAINED

### **app.py (Main Application)**
```python
# Entry point for Flask application
# Initializes:
# - Flask app
# - Database connection
# - Session management
# - Blueprint registration (tools)
# - Error handlers
# - Health check endpoint
```

### **archie_bridge.py (AI Integration)**
```python
# Ollama integration layer
# Functions:
# - chat_with_ollama(prompt, model)
# - generate_code(description, language)
# - explain_code(code)
# - stream_response(prompt)  # Future
```

### **routes.py (Per Tool)**
```python
# Each tool has its own routes.py
# Example structure:
# - Blueprint definition
# - Route decorators (@bp.route)
# - Authentication checks (@login_required)
# - Database queries
# - AI integration calls
# - Template rendering
```

---

## 🎨 TEMPLATE STRUCTURE

### **base.html (Base Template)**
```html
<!DOCTYPE html>
<html>
<head>
    <!-- Matrix theme CSS -->
    <!-- Common scripts -->
</head>
<body>
    <!-- Navigation bar -->
    <!-- Flash messages -->
    {% block content %}{% endblock %}
    <!-- Footer -->
</body>
</html>
```

### **dashboard.html (Extends base.html)**
```html
{% extends "base.html" %}
{% block content %}
    <!-- Tool cards -->
    <!-- User info -->
    <!-- Analytics (future) -->
{% endblock %}
```

---

## 🔐 PERMISSIONS & SECURITY

### **File Permissions:**
```bash
/mnt/archie_brain/           755 (drwxr-xr-x)
platform_v2/                 755
platform_v2/.env             600 (rw-------)  # IMPORTANT!
platform_v2/app.py           644
docs/                        755
docs/*.md                    644
backups/                     700 (drwx------)  # Secure!
```

### **.gitignore:**
```
.env
*.pyc
__pycache__/
*.db
*.sqlite
backups/
venv/
.DS_Store
*.log
```

---

## 📊 STATIC ASSETS

### **CSS (Matrix Theme):**
```
static/css/
└── style.css
    ├── Colors: #00ff41 (matrix green)
    ├── Fonts: JetBrains Mono, Orbitron
    ├── Dark backgrounds
    └── Glowing effects
```

### **JavaScript:**
```
static/js/
├── dashboard.js      # Dashboard functionality
├── chat.js           # AI chat interface
├── code_editor.js    # Monaco editor integration
└── admin.js          # Admin panel features
```

---

## 🔄 DEVELOPMENT WORKFLOW

### **Local Changes:**
```bash
# 1. Edit files in /mnt/archie_brain/platform_v2/

# 2. Restart platform
docker-compose restart archie_platform

# 3. Check logs
docker logs archie_platform -f

# 4. Test changes in browser
```

### **Database Changes:**
```bash
# 1. Create SQL file
nano /tmp/new_table.sql

# 2. Execute
docker exec -i archie_database psql -U archie -d archie < /tmp/new_table.sql

# 3. Verify
docker exec archie_database psql -U archie -d archie -c "\dt"

# 4. Restart platform
docker-compose restart archie_platform
```

---

## 💾 BACKUP STRUCTURE

```
/mnt/archie_brain/backups/20251227_005213/
├── database_backup.sql              # Full database dump
├── platform_v2/                     # Complete platform copy
│   ├── app.py
│   ├── templates/
│   ├── tools/
│   └── .env
└── backup_info.txt                  # Backup metadata (future)
```

---

## 🚀 DEPLOYMENT FILES

### **Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY platform_v2/ .

EXPOSE 3000

CMD ["gunicorn", "--bind", "0.0.0.0:3000", "app:app"]
```

---

## 📈 LOG FILES (Future)

```
/mnt/archie_brain/logs/              # Planned
├── platform.log
├── database.log
├── error.log
└── access.log
```

---

## 🎯 IMPORTANT PATHS

### **Platform:**
- Root: `/mnt/archie_brain/`
- App: `/mnt/archie_brain/platform_v2/`
- Templates: `/mnt/archie_brain/platform_v2/templates/`
- Static: `/mnt/archie_brain/platform_v2/static/`

### **Backups:**
- Location: `/mnt/archie_brain/backups/`
- Latest: `/mnt/archie_brain/backups/20251227_005213/`

### **Documentation:**
- Location: `/mnt/archie_brain/docs/`

### **Inside Container:**
- App: `/app/`
- Templates: `/app/templates/`
- Database: archie_database volume

---

## 🔍 FINDING FILES

### **Find by name:**
```bash
find /mnt/archie_brain -name "*.py"
find /mnt/archie_brain -name "app.py"
```

### **Find by type:**
```bash
find /mnt/archie_brain -type f  # Files
find /mnt/archie_brain -type d  # Directories
```

### **Find recently modified:**
```bash
find /mnt/archie_brain -mtime -7  # Last 7 days
```

---

## 📚 DOCUMENTATION FILES

All documentation in `/mnt/archie_brain/docs/`:

```
PLATFORM_DOCUMENTATION.md        # Main overview
SESSION_HANDOFF.md              # Latest session summary
TODO_LIST.md                    # Feature roadmap
BACKUP_RECOVERY_GUIDE.md        # Backup procedures
ADMIN_REFERENCE.md              # Admin commands
QUICK_REFERENCE.md              # One-page cheat sheet
FILE_STRUCTURE_MASTER.md        # This file
AI_POWERED_CODE_EDITOR.md       # Code editor details
AI_POWERED_APPS.md              # AI capabilities
DEPLOYMENT_CHECKLIST.md         # Deployment guide
README.md                       # Documentation index
```

---

## 🎯 FILE NAMING CONVENTIONS

- **Documentation:** UPPERCASE_WITH_UNDERSCORES.md
- **Python:** lowercase_with_underscores.py
- **Templates:** lowercase_with_underscores.html
- **Config:** lowercase or .extension (.env, .gitignore)
- **Backups:** YYYYMMDD_HHMMSS format

---

**Last Updated:** December 26, 2025  
**Platform Version:** 1.0  
**Total Files:** 100+  
**Total Directories:** 20+  
**Database Tables:** 26+
