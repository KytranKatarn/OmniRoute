# Create/Modify A.R.C.H.I.E. Module

Scaffold or modify a tool module following A.R.C.H.I.E. patterns.

## Arguments
$ARGUMENTS - Module name (e.g., "new_feature" or existing module to modify)

## Instructions

### For NEW modules:

1. Check if module exists: `ls /mnt/archie_brain/platform_v2/tools/$ARGUMENTS/`

2. If new, create structure:
   ```
   /platform_v2/tools/$ARGUMENTS/
   ├── __init__.py
   └── routes.py
   ```

3. Follow the Blueprint pattern from `/platform_v2/tools/blueprint/routes.py`:
   - Create Flask Blueprint
   - Add `@login_required` and `@admin_required` decorators
   - Return JSON with `{'success': True/False, ...}`

4. Register in `/platform_v2/module_registry.py`

5. Add permissions in `/platform_v2/rbac.py`

6. Create template at `/platform_v2/templates/tools/$ARGUMENTS.html`

### For EXISTING modules:

1. Read current implementation first
2. Follow existing patterns in the file
3. Update related files if needed (registry, permissions)

IMPORTANT: Always read `module_registry.py` and `rbac.py` before making changes.
