# A.R.C.H.I.E. Code Patterns & Conventions

Reference patterns for writing code that matches A.R.C.H.I.E. style.

## Database Connection Pattern

```python
from database import get_db
from psycopg2.extras import RealDictCursor

conn = get_db()
cur = conn.cursor(cursor_factory=RealDictCursor)
try:
    cur.execute("SELECT * FROM table WHERE id = %s", (param,))
    result = cur.fetchall()
    conn.commit()
finally:
    cur.close()
    conn.close()
```

## Flask Route Pattern

```python
from flask import Blueprint, jsonify, request
from functools import wraps
from flask_login import current_user

module_bp = Blueprint('module_name', __name__, url_prefix='/tools/module-name')

@module_bp.route('/api/action', methods=['POST'])
@login_required
@admin_required
def api_action():
    try:
        data = request.get_json()
        # logic here
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

## Module Registration

In `module_registry.py`:
```python
ModuleInfo(
    id='module_name',
    name='Module Name',
    category=ModuleCategory.ADMIN,  # or CREATION, DEVELOPMENT, BUSINESS_TOOLS
    icon='icon-name',
    url='/tools/module-name',
    description='What this module does',
    status=ModuleStatus.LIVE
)
```

In `rbac.py`:
```python
PERMISSIONS = {
    'module_name': ['admin'],  # or ['user', 'admin']
}
```

## Git Commit Format

```
<type>: <description>

Types: feat, fix, refactor, docs, test, chore

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

## Template Pattern

```html
{% extends "base.html" %}
{% block title %}Module Name{% endblock %}
{% block content %}
<div class="module-container">
    <!-- Content -->
</div>
{% endblock %}
```

## API Response Pattern

Success:
```json
{"success": true, "data": {...}, "message": "Action completed"}
```

Error:
```json
{"success": false, "error": "Error message"}
```

## Module Categories

| Category | Use For |
|----------|---------|
| CREATION | Building apps, media, games |
| DEVELOPMENT | Code tools, debugging |
| BUSINESS_TOOLS | CRM, invoicing, email |
| STANDALONE_APPS | Independent tools |
| ADMIN | System management |
