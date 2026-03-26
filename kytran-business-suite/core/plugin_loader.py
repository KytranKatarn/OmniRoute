"""Plugin loader — discovers, validates, sorts, and registers plugins with Flask."""

import importlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"slug", "name", "version", "category", "tier_required", "dependencies"}


def discover_manifests(plugins_dir):
    """Scan plugins_dir for subdirectories containing manifest.json.

    Returns a list of parsed manifest dicts, each with an added ``_dir`` key
    pointing to the plugin directory path (as a string).
    """
    plugins_dir = Path(plugins_dir)
    manifests = []

    if not plugins_dir.exists():
        logger.warning("Plugins directory does not exist: %s", plugins_dir)
        return manifests

    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            manifest["_dir"] = str(entry)
            manifests.append(manifest)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load manifest at %s: %s", manifest_path, exc)

    return manifests


def validate_manifest(manifest):
    """Validate that a manifest contains all required fields.

    Raises ValueError with a descriptive message if any required fields are missing.
    """
    missing = REQUIRED_FIELDS - set(manifest.keys())
    if missing:
        slug = manifest.get("slug", "<unknown>")
        raise ValueError(
            f"Plugin manifest for '{slug}' is missing required fields: {sorted(missing)}"
        )


def sort_by_dependencies(manifests):
    """Topological sort — returns manifests ordered so dependencies come before dependents.

    Raises ValueError if a circular dependency is detected.
    """
    by_slug = {m["slug"]: m for m in manifests}
    order = []
    visited = set()   # permanently visited
    visiting = set()  # currently in DFS stack (cycle detection)

    def visit(slug):
        if slug in visited:
            return
        if slug in visiting:
            raise ValueError(f"Circular dependency detected involving plugin '{slug}'")

        visiting.add(slug)
        manifest = by_slug.get(slug)
        if manifest:
            for dep in manifest.get("dependencies", []):
                if dep in by_slug:
                    visit(dep)
        visiting.discard(slug)
        visited.add(slug)
        if manifest:
            order.append(manifest)

    for manifest in manifests:
        visit(manifest["slug"])

    return order


def register_plugins(app, plugins_dir=None):
    """Main entry point — discover, validate, sort, and register plugins with the Flask app.

    Stores metadata in ``app.extensions["kbs_plugins"]`` keyed by slug.
    If a plugin fails to load, logs the error but continues (does not crash the app).
    """
    if plugins_dir is None:
        # Default: sibling ``plugins/`` directory next to the running app
        plugins_dir = Path(app.root_path).parent / "plugins"

    plugins_dir = Path(plugins_dir)

    if "kbs_plugins" not in app.extensions:
        app.extensions["kbs_plugins"] = {}

    raw_manifests = discover_manifests(plugins_dir)

    # Validate
    valid_manifests = []
    for manifest in raw_manifests:
        try:
            validate_manifest(manifest)
            valid_manifests.append(manifest)
        except ValueError as exc:
            logger.warning("Skipping invalid plugin manifest: %s", exc)

    # Sort by dependency order
    try:
        ordered = sort_by_dependencies(valid_manifests)
    except ValueError as exc:
        logger.error("Dependency sort failed: %s — loading plugins in discovery order", exc)
        ordered = valid_manifests

    # Register each plugin
    for manifest in ordered:
        slug = manifest["slug"]
        plugin_dir = Path(manifest["_dir"])
        module_name = plugin_dir.name  # directory name under plugins/

        try:
            mod = importlib.import_module(f"plugins.{module_name}")

            if hasattr(mod, "create_blueprint"):
                bp = mod.create_blueprint(manifest)
                app.register_blueprint(bp, url_prefix=f"/plugins/{slug}")
                logger.info("Registered plugin blueprint: %s at /plugins/%s", slug, slug)
            else:
                logger.info(
                    "Plugin '%s' has no create_blueprint() — metadata tracked only", slug
                )

            app.extensions["kbs_plugins"][slug] = {
                "slug": slug,
                "name": manifest.get("name"),
                "version": manifest.get("version"),
                "category": manifest.get("category"),
                "tier_required": manifest.get("tier_required"),
                "dependencies": manifest.get("dependencies", []),
                "manifest": manifest,
            }

        except Exception as exc:
            logger.error("Failed to load plugin '%s': %s", slug, exc, exc_info=True)
