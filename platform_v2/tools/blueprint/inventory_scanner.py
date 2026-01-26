"""Platform Inventory Scanner - Filesystem scanning for platform inventory snapshots."""
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Platform directories to scan
# Note: Inside Docker, /mnt/archie_brain has docs/ai_bridge, /app has tools/templates
PLATFORM_ROOT = '/mnt/archie_brain'
APP_ROOT = '/app'  # platform_v2 code inside Docker
DOCS_DIR = os.path.join(PLATFORM_ROOT, 'docs')
TOOLS_DIR = os.path.join(APP_ROOT, 'tools')
MIGRATIONS_DIR = os.path.join(PLATFORM_ROOT, 'database', 'migrations')
AI_BRIDGE_DIR = os.path.join(PLATFORM_ROOT, 'ai_bridge')
TEMPLATES_DIR = os.path.join(APP_ROOT, 'templates')


def get_file_size(path: str) -> int:
    """Get file size in bytes."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def get_dir_size(path: str) -> int:
    """Get directory size in bytes (recursive)."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def scan_directory(path: str, extensions: List[str] = None) -> Dict[str, Any]:
    """Scan a directory and return file listing with sizes."""
    result = {
        'path': path,
        'total_files': 0,
        'total_size_bytes': 0,
        'files': [],
        'subdirs': []
    }

    if not os.path.exists(path):
        return result

    try:
        for item in sorted(os.listdir(path)):
            item_path = os.path.join(path, item)

            if os.path.isfile(item_path):
                # Check extension filter
                if extensions:
                    ext = os.path.splitext(item)[1].lower()
                    if ext not in extensions:
                        continue

                size = get_file_size(item_path)
                mtime = os.path.getmtime(item_path)

                result['files'].append({
                    'name': item,
                    'size_bytes': size,
                    'modified': datetime.fromtimestamp(mtime).isoformat()
                })
                result['total_files'] += 1
                result['total_size_bytes'] += size

            elif os.path.isdir(item_path):
                # Skip hidden dirs and __pycache__
                if item.startswith('.') or item == '__pycache__':
                    continue

                subdir_size = get_dir_size(item_path)
                file_count = sum(1 for _ in os.walk(item_path) for _ in _[2])

                result['subdirs'].append({
                    'name': item,
                    'size_bytes': subdir_size,
                    'file_count': file_count
                })

    except OSError as e:
        logger.error(f"Error scanning {path}: {e}")

    return result


def scan_docs() -> Dict[str, Any]:
    """Scan documentation files."""
    return scan_directory(DOCS_DIR, extensions=['.md'])


def scan_tools() -> Dict[str, Any]:
    """Scan tool modules with detailed breakdown.

    Returns:
        - Total modules count
        - Active modules (have routes.py with significant code)
        - Stub modules (less than 100 lines total)
        - Per-module stats (files, lines, size)
    """
    result = {
        'path': TOOLS_DIR,
        'total_modules': 0,
        'active_modules': 0,
        'stub_modules': 0,
        'modules': []
    }

    if not os.path.exists(TOOLS_DIR):
        return result

    try:
        for item in sorted(os.listdir(TOOLS_DIR)):
            item_path = os.path.join(TOOLS_DIR, item)

            if os.path.isdir(item_path) and not item.startswith('_'):
                # Count Python files and lines
                py_files = []
                total_lines = 0

                for f in os.listdir(item_path):
                    if f.endswith('.py'):
                        fp = os.path.join(item_path, f)
                        file_size = get_file_size(fp)

                        # Count lines
                        line_count = 0
                        try:
                            with open(fp, 'r') as file:
                                line_count = sum(1 for _ in file)
                        except:
                            pass

                        total_lines += line_count

                        py_files.append({
                            'name': f,
                            'size_bytes': file_size,
                            'lines': line_count
                        })

                total_size = sum(f['size_bytes'] for f in py_files)

                # Check for routes.py (indicates active module)
                has_routes = any(f['name'] == 'routes.py' for f in py_files)

                # Determine if this is a stub module (< 100 lines total)
                is_stub = total_lines < 100

                # Track active vs stub
                if has_routes and not is_stub:
                    result['active_modules'] += 1
                    status = 'active'
                elif is_stub:
                    result['stub_modules'] += 1
                    status = 'stub'
                else:
                    status = 'orphaned'

                result['modules'].append({
                    'name': item,
                    'python_files': len(py_files),
                    'total_lines': total_lines,
                    'total_size_bytes': total_size,
                    'has_routes': has_routes,
                    'is_stub': is_stub,
                    'status': status,
                    'files': py_files
                })
                result['total_modules'] += 1

    except OSError as e:
        logger.error(f"Error scanning tools: {e}")

    # Add summary
    result['summary'] = {
        'total': result['total_modules'],
        'active': result['active_modules'],
        'stub': result['stub_modules'],
        'orphaned': result['total_modules'] - result['active_modules'] - result['stub_modules']
    }

    return result


def scan_migrations() -> Dict[str, Any]:
    """Scan database migrations."""
    return scan_directory(MIGRATIONS_DIR, extensions=['.sql', '.py'])


def scan_ai_bridge() -> Dict[str, Any]:
    """Scan AI bridge files."""
    return scan_directory(AI_BRIDGE_DIR, extensions=['.py'])


def scan_templates() -> Dict[str, Any]:
    """Scan HTML templates."""
    result = {
        'path': TEMPLATES_DIR,
        'total_files': 0,
        'total_size_bytes': 0,
        'categories': []
    }

    if not os.path.exists(TEMPLATES_DIR):
        return result

    try:
        for category in sorted(os.listdir(TEMPLATES_DIR)):
            cat_path = os.path.join(TEMPLATES_DIR, category)

            if os.path.isdir(cat_path):
                cat_data = scan_directory(cat_path, extensions=['.html', '.jinja', '.jinja2'])
                result['categories'].append({
                    'name': category,
                    'file_count': cat_data['total_files'],
                    'size_bytes': cat_data['total_size_bytes'],
                    'files': cat_data['files']
                })
                result['total_files'] += cat_data['total_files']
                result['total_size_bytes'] += cat_data['total_size_bytes']

    except OSError as e:
        logger.error(f"Error scanning templates: {e}")

    return result


def scan_platform() -> Dict[str, Any]:
    """Full platform inventory scan."""
    logger.info("Starting full platform inventory scan...")

    # Scan all areas
    docs = scan_docs()
    tools = scan_tools()
    migrations = scan_migrations()
    ai_bridge = scan_ai_bridge()
    templates = scan_templates()

    # Count Python files across platform
    python_files = 0
    for root, dirs, files in os.walk(APP_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        python_files += sum(1 for f in files if f.endswith('.py'))

    for root, dirs, files in os.walk(AI_BRIDGE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        python_files += sum(1 for f in files if f.endswith('.py'))

    # Calculate totals
    total_size = (
        docs['total_size_bytes'] +
        sum(m['total_size_bytes'] for m in tools.get('modules', [])) +
        migrations['total_size_bytes'] +
        ai_bridge['total_size_bytes'] +
        templates['total_size_bytes']
    )

    inventory = {
        'scan_timestamp': datetime.now().isoformat(),
        'summary': {
            'total_python_files': python_files,
            'total_docs': docs['total_files'],
            'total_tools': tools['total_modules'],
            'total_migrations': migrations['total_files'],
            'total_templates': templates['total_files'],
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        },
        'docs': docs,
        'tools': tools,
        'migrations': migrations,
        'ai_bridge': ai_bridge,
        'templates': templates
    }

    logger.info(f"Scan complete: {python_files} py files, {docs['total_files']} docs, {tools['total_modules']} tools")

    return inventory


def save_snapshot(inventory: Dict[str, Any], notes: str = None) -> int:
    """Save inventory snapshot to database."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Mark all existing as not current
        cur.execute("UPDATE platform_inventory SET is_current = FALSE WHERE is_current = TRUE")

        summary = inventory.get('summary', {})

        cur.execute("""
            INSERT INTO platform_inventory
            (snapshot_type, total_python_files, total_docs, total_tools, total_migrations,
             total_size_mb, inventory_data, is_current, notes)
            VALUES ('full', %s, %s, %s, %s, %s, %s, TRUE, %s)
            RETURNING id
        """, (
            summary.get('total_python_files', 0),
            summary.get('total_docs', 0),
            summary.get('total_tools', 0),
            summary.get('total_migrations', 0),
            summary.get('total_size_mb', 0),
            json.dumps(inventory),
            notes
        ))

        snapshot_id = cur.fetchone()['id']
        conn.commit()

        logger.info(f"Saved inventory snapshot {snapshot_id}")
        return snapshot_id

    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving inventory: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def get_current_inventory() -> Optional[Dict[str, Any]]:
    """Get the current (most recent) inventory snapshot."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT * FROM platform_inventory
            WHERE is_current = TRUE
            ORDER BY snapshot_at DESC
            LIMIT 1
        """)

        row = cur.fetchone()
        if not row:
            return None

        result = dict(row)
        result['snapshot_at'] = result['snapshot_at'].isoformat()
        return result
    finally:
        cur.close()
        conn.close()


def get_inventory_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Get history of inventory snapshots."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT id, snapshot_at, snapshot_type, total_python_files, total_docs,
                   total_tools, total_migrations, total_size_mb, is_current, notes
            FROM platform_inventory
            ORDER BY snapshot_at DESC
            LIMIT %s
        """, (limit,))

        results = []
        for row in cur.fetchall():
            r = dict(row)
            r['snapshot_at'] = r['snapshot_at'].isoformat()
            results.append(r)

        return results
    finally:
        cur.close()
        conn.close()


def get_inventory_snapshot(snapshot_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific inventory snapshot."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("SELECT * FROM platform_inventory WHERE id = %s", (snapshot_id,))

        row = cur.fetchone()
        if not row:
            return None

        result = dict(row)
        result['snapshot_at'] = result['snapshot_at'].isoformat()
        return result
    finally:
        cur.close()
        conn.close()


def delete_inventory_snapshot(snapshot_id: int) -> bool:
    """Delete an inventory snapshot (not the current one)."""
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "DELETE FROM platform_inventory WHERE id = %s AND is_current = FALSE",
            (snapshot_id,)
        )

        deleted = cur.rowcount > 0
        conn.commit()

        if deleted:
            logger.info(f"Deleted inventory snapshot {snapshot_id}")

        return deleted
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting snapshot: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def scan_and_save(notes: str = None) -> Dict[str, Any]:
    """Scan platform and save snapshot in one operation."""
    inventory = scan_platform()
    snapshot_id = save_snapshot(inventory, notes)
    return {
        'snapshot_id': snapshot_id,
        'summary': inventory['summary']
    }
