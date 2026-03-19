# Module Scaffold — A.R.C.H.I.E. Platform

Zero-deviation starting point for new modules. Copy this folder and follow the steps below.

## Usage

### 1. Copy the scaffold

```bash
cp -r platform_v2/tools/_scaffold platform_v2/tools/my_module
```

### 2. Rename everything

Search-and-replace across all files in your new folder:

| Find           | Replace             |
|----------------|---------------------|
| `scaffold`     | `my_module`         |
| `scaffold_bp`  | `my_module_bp`      |
| `[MODULE_NAME]`| `My Module`         |
| `[DATE]`       | Today's date        |
| `[Brief description...]` | Your description |

Also rename the template file:

```bash
mv templates/tools/scaffold.html templates/tools/my_module.html
```

### 3. Register the module

**Both files must be updated or the module will not appear:**

- `platform_v2/module_registry.py` — add module definition
- `platform_v2/rbac.py` — add permission entry

### 4. Import the blueprint in app.py

```python
from tools.my_module import my_module_bp
app.register_blueprint(my_module_bp)
```

### 5. Restart

```bash
docker compose restart archie_platform
```

## File Structure

```
tools/my_module/
├── __init__.py          # Blueprint + register_*_routes (ADR-045)
├── routes.py            # Blueprint definition, index route, API endpoints
├── templates/
│   └── tools/
│       └── my_module.html   # LCARS template extending base.html
└── README.md            # (delete after setup)
```

## Patterns Included

- **ADR-045**: `register_*_routes(bp, admin_required)` for sub-route files
- **Database**: `get_db_cursor()` context manager with `with` statement
- **Auth**: `@login_required` for user routes, `@admin_required` for admin routes
- **Error handling**: `logger.exception()` + generic error messages (never `str(e)`)
- **StationOps**: Commented placeholder ready to uncomment and configure
- **LCARS tabs**: Tab switching with active state management
- **Blueprint template_folder**: Set to `"templates"` (prevents TemplateNotFound)

## Splitting Routes (ADR-045)

When your module grows, split routes into sub-files:

```python
# data_routes.py
def register_data_routes(bp, admin_required):
    @bp.route("/api/data/items")
    @admin_required
    def data_items():
        ...
```

Then in `__init__.py`:

```python
from .data_routes import register_data_routes
register_data_routes(scaffold_bp, admin_required)
```

## Checklist

- [ ] Renamed all `scaffold` references
- [ ] Renamed template file
- [ ] Added to `module_registry.py`
- [ ] Added to `rbac.py`
- [ ] Registered blueprint in `app.py`
- [ ] Restarted Docker container
- [ ] Module visible on dashboard
