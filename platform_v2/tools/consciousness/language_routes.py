"""Consciousness module -- Language/Translation routes.

Extracted from routes.py as part of the Consciousness module refactor.
Handles:
- Translation scanning, seeding, generation
- Translation jobs, coverage, review, approval
- Background translation workers
- Translation memory CRUD
"""

import logging
import os
import re
import threading

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

from database import _get_db_password
from rbac import require_permission, Permission
from ai_bridge.translation_service import (
    get_translation_stats,
    batch_translate,
    SUPPORTED_LANGUAGES,
    BATCH_SIZE,
)
from module_registry import get_all_modules, ModuleCategory
import json as _json

logger = logging.getLogger(__name__)

# Single-flight guard for /api/translations/full-scan — prevents parallel scans
# from racing on translation_gaps upserts (see migration 322).
_full_scan_lock = threading.Lock()

# External sites/products with data-i18n attributes to scan
# Each entry: (source_label, directory_path, bundle_output_path_or_None)
EXTERNAL_SCAN_SOURCES = [
    (
        "website_kytranempowerment",
        "/mnt/archie_brain/website/kytranempowerment.com",
        "/mnt/archie_brain/website/kytranempowerment.com/data/translations.json",
    ),
    (
        "website_kso",
        "/mnt/archie_brain/kytran-server-manager",
        None,  # KSO doesn't have a static bundle yet
    ),
    (
        "website_creed",
        "/mnt/archie_brain/website/creed-ai.org",
        "/mnt/archie_brain/website/creed-ai.org/data/translations.json",
    ),
    # ── Watch products (VPS-hosted, scanned from hub filesystem mirror) ──
    (
        "product_civic_watch",
        "/mnt/standalone/kytran-civic-watch",
        "/mnt/standalone/kytran-civic-watch/static/data/translations.json",
    ),
    (
        "product_gov_watch",
        "/mnt/standalone/kytran-gov-watch",
        "/mnt/standalone/kytran-gov-watch/static/data/translations.json",
    ),
    (
        "product_legal_watch",
        "/mnt/standalone/kytran-legal-watch",
        "/mnt/standalone/kytran-legal-watch/static/data/translations.json",
    ),
    (
        "product_market_watch",
        "/mnt/standalone/kytran-market-watch",
        "/mnt/standalone/kytran-market-watch/static/data/translations.json",
    ),
    # ── What The Fact (brand) — frontend + backend ──
    # NO BUNDLE (#5750). This entry used to export to
    # /mnt/standalone/websites/what-the-fact.com/data/translations.json — a static
    # marketing site frozen 2026-04-14, from before WTF became a Flask app. Nothing
    # serves that directory, and the DB held no rows for these keys, so the nightly
    # translation_coverage_scan wrote a 2-byte "{}" there and reported SUCCESS. The
    # verify step passed because it fetched the LIVE url, which serves the file baked
    # into the wtf-consumer image — a different artifact the export never touched.
    #
    # WTF's translations are HAND-MAINTAINED in the repo at
    # consumer/static/data/translations.json (en/fr/es, the three the switcher offers).
    # Do NOT point the export at that file: the DB set and the file set are not
    # supersets of one another (DB = 8 keys x 8 langs; file = 18 keys x 3 langs), so an
    # export would silently drop 10 keys per live language. Scanned for coverage,
    # exported by nobody — same as website_kso / product_business_suite below.
    ("website_what_the_fact", "/mnt/standalone/websites/what-the-fact.com", None),
    ("product_what_the_fact", "/mnt/archie_brain/what-the-fact", None),
    # ── KBS ──
    # Live KBS code is /mnt/archie_brain/kytran-business-suite -- that is what the running
    # kbs_app container mounts (-> /app). The /mnt/standalone spelling is a SEPARATE stale
    # clone, not a symlink (unlike kytran-creed, where both names are the same inode).
    # Scanning it found 42 js/html files against the live tree's 81, so coverage was
    # computed against code that is not what ships. Repointed 2026-10-02.
    ("product_business_suite", "/mnt/archie_brain/kytran-business-suite", None),
    # ── C.R.E.E.D. Governance (AI wellness standalone, creed.kytranempowerment.com:8086) ──
    ("product_creed_governance", "/mnt/standalone/kytran-creed", None),
]


def _get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _is_scanner_artifact(key: str) -> bool:
    """True when a scraped ``data-i18n`` value is JS/HTML syntax, not a translation key.

    The scanners read templates with a regex over ``data-i18n="..."``. That happily
    matches values the template assembles at RENDER time in JavaScript, because the
    concatenation fragments are inside the attribute as written:

        platform_v2/static/js/dashboard.js:1451
            '<div class="featured-card-name" data-i18n="' + nameKey + '">' + ...

    ``nameKey`` is itself built at line 1442 as ``'module.' + mod.id + '.name'``, so
    there is no literal key in the file to find. The regex captures the *fragments*
    as if they were keys, and the coverage scan then approves them: the ``translations``
    table carried 8 rows whose key is literally ``' + nameKey + '`` and 8 more for
    ``' + descKey + '``. A bare JS call such as ``getInvolved()`` lands the same way.

    These are not untranslated strings — they are not strings at all. They cannot be
    translated, they cannot be rendered, and every one of them silently inflates the
    denominator that the Languages tab's coverage matrix and Gap Feed report. That is
    the number a human trusts when deciding whether to ship a language, so the noise
    has to be rejected at the scrape, not filtered out of the report later.

    Rejects, in order:
      * empty / whitespace-only
      * JS or template interpolation (``+``, ``${``, ``{{``, ``%s``-style braces) —
        the concatenation fragments above
      * a call — ``name(...)`` — matched by balanced-free trailing ``()``
      * an HTML tag (``<div>``)
      * a leading quote/bracket, which is what a captured fragment starts with
    """
    if not key or not key.strip():
        return True
    k = key.strip()
    # Interpolation and concatenation fragments: "' + nameKey + '", "${t('x')}"
    if any(tok in k for tok in ("+", "${", "{{", "}}", "{%", "%s", "%(")):
        return True
    # A call expression: getInvolved(), computeTotal()
    if k.endswith(")") and "(" in k:
        return True
    # An HTML tag rather than a key.
    if k.startswith("<") and k.endswith(">"):
        return True
    # A captured fragment keeps the quote/bracket it was delimited by.
    if k[0] in "\"'`([{":
        return True
    return False


def _scan_all_sources():
    """Scan all discoverable translation key sources.

    Returns a dict of key -> {"source": str, "file": str, "english": str}
    and a by_source count dict.
    """
    platform_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    keys = {}
    by_source = {}

    # -- Source 1: HTML Templates --
    # Scan both templates/ and all tools/*/templates/ directories
    # Pattern extracts key and optionally the element's text content
    i18n_key_pattern = re.compile(r'data-i18n(?:-\w+)?="([^"]+)"')
    # For extracting text: data-i18n="key">text content<
    i18n_text_pattern = re.compile(r'data-i18n="([^"]+)"[^>]*>([^<]+)<')
    # For placeholder/title: match either order within a tag (may span lines)
    # Returns (key, text) tuples
    i18n_attr_extractors = []
    for attr in ("placeholder", "title"):
        # data-i18n-attr="key" ... attr="text"
        i18n_attr_extractors.append(re.compile(rf'data-i18n-{attr}="([^"]+)"[^>]*{attr}="([^"]+)"', re.DOTALL))
        # attr="text" ... data-i18n-attr="key" (reversed order)
        i18n_attr_extractors.append(re.compile(rf'{attr}="([^"]+)"[^>]*data-i18n-{attr}="([^"]+)"', re.DOTALL))
    template_dirs = [os.path.join(platform_root, "templates")]

    tools_root = os.path.join(platform_root, "tools")
    if os.path.isdir(tools_root):
        for tool_name in os.listdir(tools_root):
            tool_tpl = os.path.join(tools_root, tool_name, "templates")
            if os.path.isdir(tool_tpl):
                template_dirs.append(tool_tpl)

    for tpl_dir in template_dirs:
        for root, _dirs, files in os.walk(tpl_dir):
            for fname in files:
                if not fname.endswith(".html"):
                    continue
                filepath = os.path.join(root, fname)
                rel_path = os.path.relpath(filepath, platform_root)
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        content = fh.read()

                    # First pass: extract text content for data-i18n="key">text<
                    text_map = {}
                    for m in i18n_text_pattern.finditer(content):
                        text_map[m.group(1)] = m.group(2).strip()
                    # Extract attribute variants (placeholder, title)
                    for i, pat in enumerate(i18n_attr_extractors):
                        for m in pat.finditer(content):
                            if i % 2 == 0:  # data-i18n-X first: (key, text)
                                text_map[m.group(1)] = m.group(2).strip()
                            else:  # attr first: (text, key)
                                text_map[m.group(2)] = m.group(1).strip()

                    # Second pass: register all keys
                    for match in i18n_key_pattern.finditer(content):
                        key = match.group(1)
                        if "{{" in key or "}}" in key:
                            continue
                        if _is_scanner_artifact(key):
                            continue
                        if key not in keys:
                            keys[key] = {
                                "source": "template",
                                "file": rel_path,
                                "english": text_map.get(key, ""),
                            }
                except Exception as read_err:
                    logger.warning(f"Scan: could not read {rel_path}: {read_err}")

    by_source["template"] = sum(1 for v in keys.values() if v["source"] == "template")

    # -- Source 1b: External Sites (websites, standalone products) --
    for ext_label, ext_dir, _bundle_path in EXTERNAL_SCAN_SOURCES:
        if not os.path.isdir(ext_dir):
            logger.warning(f"Scan: external dir not found: {ext_dir}")
            continue
        ext_count = 0
        for root, _dirs, files in os.walk(ext_dir):
            # Skip hidden dirs, node_modules, __pycache__, virtualenvs, build artifacts
            if any(
                skip in root
                for skip in (
                    "/.git",
                    "/node_modules",
                    "/__pycache__",
                    "/.venv",
                    "/venv",
                    "/site-packages",
                    "/dist",
                    "/build",
                )
            ):
                continue
            for fname in files:
                if not fname.endswith(".html") or fname.startswith("_"):
                    continue
                filepath = os.path.join(root, fname)
                rel_path = os.path.relpath(filepath, ext_dir)
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    text_map = {}
                    for m in i18n_text_pattern.finditer(content):
                        text_map[m.group(1)] = m.group(2).strip()
                    for i, pat in enumerate(i18n_attr_extractors):
                        for m in pat.finditer(content):
                            if i % 2 == 0:
                                text_map[m.group(1)] = m.group(2).strip()
                            else:
                                text_map[m.group(2)] = m.group(1).strip()
                    for match in i18n_key_pattern.finditer(content):
                        key = match.group(1)
                        if "{{" in key or "}}" in key:
                            continue
                        if _is_scanner_artifact(key):
                            continue
                        if key not in keys:
                            keys[key] = {
                                "source": ext_label,
                                "file": f"{ext_label}:{rel_path}",
                                "english": text_map.get(key, ""),
                            }
                            ext_count += 1
                except Exception as read_err:
                    logger.warning(f"Scan: external {ext_label}/{rel_path}: {read_err}")
        by_source[ext_label] = ext_count
        logger.info(f"Scan: {ext_label} contributed {ext_count} new keys")

    # -- Source 2: Module Registry --
    try:
        modules = get_all_modules()
        for mod in modules:
            name_key = f"module.{mod.id}.name"
            keys[name_key] = {
                "source": "module_name",
                "file": "module_registry.py",
                "english": mod.name,
            }

            desc_text = (mod.description or "")[:120]
            # Strip simple HTML tags
            desc_text = re.sub(r"<[^>]+>", "", desc_text).strip()
            desc_key = f"module.{mod.id}.desc"
            keys[desc_key] = {
                "source": "module_desc",
                "file": "module_registry.py",
                "english": desc_text,
            }
    except Exception as e:
        logger.warning(f"Scan: module registry error: {e}")

    by_source["module_name"] = sum(1 for v in keys.values() if v["source"] == "module_name")
    by_source["module_desc"] = sum(1 for v in keys.values() if v["source"] == "module_desc")

    # -- Source 3: Categories --
    try:
        for member in ModuleCategory:
            cat_key = f"cat.{member.value}"
            english_name = member.value.replace("_", " ").title()
            keys[cat_key] = {
                "source": "category",
                "file": "module_registry.py",
                "english": english_name,
            }
    except Exception as e:
        logger.warning(f"Scan: category enum error: {e}")

    by_source["category"] = sum(1 for v in keys.values() if v["source"] == "category")

    # -- Source 4: JS Translation Keys --
    js_path = os.path.join(platform_root, "static", "js", "archie-i18n.js")
    js_key_pattern = re.compile(r"""'([^']+)':\s*(['"])(.*?)\2""", re.DOTALL)
    try:
        with open(js_path, "r", encoding="utf-8") as fh:
            js_content = fh.read()
        for match in js_key_pattern.finditer(js_content):
            js_key = match.group(1)
            js_val = match.group(3)
            # Decode JS unicode escapes (\uXXXX) to actual characters
            if "\\u" in js_val:
                try:
                    js_val = (
                        js_val.encode("raw_unicode_escape")
                        .decode("unicode_escape")
                        .encode("utf-16", "surrogatepass")
                        .decode("utf-16")
                    )
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass  # keep raw value if decode fails
            if _is_scanner_artifact(js_key):
                continue
            # Only capture keys that look like translation keys (contain a dot)
            if "." in js_key:
                keys[js_key] = {
                    "source": "js",
                    "file": "archie-i18n.js",
                    "english": js_val,
                }
    except Exception as e:
        logger.warning(f"Scan: archie-i18n.js read error: {e}")

    by_source["js"] = sum(1 for v in keys.values() if v["source"] == "js")

    return keys, by_source


def _seed_keys(keys_dict):
    """Seed English source strings for discovered keys not yet in DB.

    Args:
        keys_dict: dict of key -> {"english": str, "source": str, ...}

    Returns:
        tuple: (seeded_count, skipped_count)
    """
    conn = None
    cur = None
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()

        seeded = 0
        skipped = 0

        context_map = {
            "module_name": "module_registry",
            "module_desc": "module_registry",
            "category": "module_registry",
            "js": "js_manifest",
            "template": "template",
        }
        # Add external source labels to context map
        for ext_label, _, _ in EXTERNAL_SCAN_SOURCES:
            context_map[ext_label] = ext_label

        # External labels like "website_kso" map 1:1 to source_label; internal
        # key sources (template/js/module_*/category) bucket under 'platform'.
        external_labels = {s[0] for s in EXTERNAL_SCAN_SOURCES}

        for key, info in keys_dict.items():
            english = info.get("english", "")
            source_type = info.get("source", "")
            if not english:
                skipped += 1
                continue

            context = context_map.get(source_type, source_type)
            source_label = source_type if source_type in external_labels else "platform"

            cur.execute(
                """
                INSERT INTO translations (key, language, text, source, source_label,
                                          status, context, created_at, updated_at)
                VALUES (%s, 'en', %s, 'imported', %s, 'approved', %s, NOW(), NOW())
                ON CONFLICT (source_label, key, language) DO NOTHING
                """,
                (key, english, source_label, context),
            )
            if cur.rowcount > 0:
                seeded += 1
            else:
                skipped += 1

        conn.commit()
        return seeded, skipped
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def scan_and_seed_keys():
    """Scan all sources and seed missing English keys. Callable from startup hook or API.

    Returns:
        dict: {"total": int, "seeded": int, "skipped": int, "by_source": dict}
    """
    keys, by_source = _scan_all_sources()
    seeded, skipped = _seed_keys(keys)
    return {
        "total": len(keys),
        "seeded": seeded,
        "skipped": skipped,
        "by_source": by_source,
    }


def _run_translate_bg(languages, module_id, parent_job_id):
    """Background worker: translate missing keys for each language sequentially.

    Uses a single bridge job for the entire pipeline. batch_translate() updates
    the parent job's progress at batch level so only one agent slot is consumed.
    """
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    completed_langs = 0
    failed_langs = 0
    total_inserted = 0
    total_failed = 0
    batch_offset = 0  # cumulative batches completed across languages

    # Pre-scan: count total batches across all languages so job has accurate total_steps
    total_batches = 0
    lang_strings = {}  # lang -> list of (key, english_text, context)
    conn = None
    cur = None
    try:
        for lang in languages:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            module_filter = ""
            params = [lang]
            if module_id:
                module_filter = "AND t1.key LIKE %s"
                params.append(f"{module_id}.%")
            cur.execute(
                f"""
                SELECT DISTINCT t1.key, t1.text AS english_text, t1.context
                FROM translations t1
                WHERE t1.language = 'en'
                  AND NOT EXISTS (
                      SELECT 1 FROM translations t2
                      WHERE t2.key = t1.key AND t2.language = %s
                  )
                  {module_filter}
                """,
                params,
            )
            rows = cur.fetchall()
            strings = [(r["key"], r["english_text"], r.get("context") or "") for r in rows]
            lang_strings[lang] = strings
            total_batches += (len(strings) + BATCH_SIZE - 1) // BATCH_SIZE if strings else 0
            if cur:
                cur.close()
            if conn:
                conn.close()
    except Exception as e:
        logger.error(f"[TranslateBG] Pre-scan failed: {e}")

    # Update parent job with accurate total
    if total_batches > 0:
        try:
            dispatcher.update_job_progress(
                job_id=parent_job_id,
                completed_steps=0,
                metadata_update={"total_batches": total_batches},
            )
            # Also update total_steps in DB directly
            conn2 = _get_db()
            cur2 = conn2.cursor()
            cur2.execute(
                "UPDATE bridge_jobs SET total_steps = %s WHERE id = %s",
                (total_batches, parent_job_id),
            )
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception:
            pass

    try:
        for lang in languages:
            lang_name = SUPPORTED_LANGUAGES.get(lang, lang)
            strings = lang_strings.get(lang, [])
            logger.info(
                f"[TranslateBG] Job #{parent_job_id}: starting {lang_name} "
                f"({completed_langs + 1}/{len(languages)}, {len(strings)} keys)"
            )

            try:
                if strings:
                    # batch_translate now stores each batch to DB immediately
                    # (crash-resilient -- no progress lost on job restart)
                    results = batch_translate(
                        strings,
                        lang,
                        parent_job_id=parent_job_id,
                        batch_offset=batch_offset,
                    )
                    lang_batches = (len(strings) + BATCH_SIZE - 1) // BATCH_SIZE
                    batch_offset += lang_batches
                    inserted = sum(1 for r in results if r.get("success"))
                    failed = sum(1 for r in results if not r.get("success"))
                    total_inserted += inserted
                    total_failed += failed
                    logger.info(f"[TranslateBG] {lang_name}: {inserted} " f"inserted, {failed} failed")
                else:
                    logger.info(f"[TranslateBG] {lang_name}: no missing keys")

                completed_langs += 1

            except Exception as lang_err:
                logger.error(f"[TranslateBG] {lang_name} failed: {lang_err}")
                failed_langs += 1

    except Exception as e:
        logger.error(f"[TranslateBG] Job #{parent_job_id} error: {e}")
    finally:
        try:
            dispatcher.complete_job(parent_job_id)
        except Exception:
            pass

        logger.info(
            f"[TranslateBG] Job #{parent_job_id} finished: "
            f"{completed_langs}/{len(languages)} languages, "
            f"{total_inserted} inserted, {total_failed} failed"
        )


ALL_LANGS_ORDERED = ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"]


def _build_coverage_matrix(
    domains: list[dict],
    gap_counts: dict[str, int],
    total_keys: dict[str, int],
) -> dict:
    """Return {domain_name: {lang: {status, coverage_pct, gap_count}}}."""
    matrix: dict = {}
    for domain in domains:
        name = domain["name"]
        active_langs = domain.get("active_languages") or []
        total = total_keys.get(name, 0)
        matrix[name] = {}
        for lang in ALL_LANGS_ORDERED:
            if lang not in active_langs:
                matrix[name][lang] = {"status": "roadmap", "coverage_pct": None, "gap_count": None}
                continue
            if lang == "en":
                matrix[name][lang] = {"status": "source", "coverage_pct": 100, "gap_count": 0}
                continue
            gaps = gap_counts.get(f"{name}:{lang}", 0)
            pct = round(((total - gaps) / total) * 100) if total > 0 else 0
            status = "green" if pct >= 95 else ("yellow" if pct >= 70 else "red")
            matrix[name][lang] = {"status": status, "coverage_pct": pct, "gap_count": gaps}
    return matrix


def register_language_routes(bp, admin_required):
    """Register all language/translation routes on the consciousness blueprint."""

    @bp.route("/api/translations/stats")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_stats():
        """Get translation statistics for all supported languages."""
        try:
            stats = {}
            for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
                if lang_code == "en":
                    continue
                stats[lang_code] = {
                    "name": lang_name,
                    **get_translation_stats(lang_code),
                }
            return jsonify({"success": True, "stats": stats})
        except Exception as e:
            logger.error(f"Translation stats error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/scan", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_scan():
        """Scan all sources for translatable keys: templates, modules, categories, JS."""
        try:
            keys, by_source = _scan_all_sources()
            return jsonify(
                {
                    "success": True,
                    "keys": keys,
                    "total": len(keys),
                    "by_source": by_source,
                }
            )
        except Exception as e:
            logger.error(f"Translation scan error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/seed", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_seed():
        """Seed English source strings for all discovered keys not yet in DB."""
        try:
            data = request.get_json() or {}
            incoming_keys = data.get("keys", {})

            if not incoming_keys:
                return jsonify({"success": False, "error": "keys dict required"}), 400

            seeded, skipped = _seed_keys(incoming_keys)
            return jsonify({"success": True, "seeded": seeded, "skipped": skipped})
        except Exception as e:
            logger.error(f"Translation seed error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/scan-and-seed", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_scan_and_seed():
        """One-click: scan all sources and seed missing English keys."""
        try:
            result = scan_and_seed_keys()
            return jsonify({"success": True, **result})
        except Exception as e:
            logger.error(f"Translation scan-and-seed error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/audit-templates", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_audit_templates():
        """Audit all module templates for hardcoded English text missing data-i18n.

        Scans HTML files for visible text nodes that aren't wrapped with i18n
        attributes.  Returns per-file counts and sample strings so admins know
        where to add tags.
        """
        import html.parser

        class _TextExtractor(html.parser.HTMLParser):
            """Lightweight HTML parser that collects bare text outside tags."""

            SKIP_TAGS = {
                "script",
                "style",
                "code",
                "pre",
                "svg",
                "path",
                "option",
            }

            def __init__(self):
                super().__init__()
                self._skip_depth = 0
                self._in_i18n = False
                self.hardcoded = []  # (line, text)
                self._line = 0

            def handle_starttag(self, tag, attrs):
                dict(attrs)
                if tag in self.SKIP_TAGS:
                    self._skip_depth += 1
                # Check for data-i18n (any variant)
                self._in_i18n = any(k.startswith("data-i18n") for k, _ in attrs)

            def handle_endtag(self, tag):
                if tag in self.SKIP_TAGS and self._skip_depth > 0:
                    self._skip_depth -= 1
                self._in_i18n = False

            def handle_data(self, data):
                if self._skip_depth > 0 or self._in_i18n:
                    return
                text = data.strip()
                # Only flag strings that look like real English words (3+ chars,
                # not just punctuation, numbers, template vars, or icons)
                if (
                    len(text) >= 3
                    and not text.startswith("{")
                    and not text.startswith("{{")
                    and not text.startswith("--")
                    and re.search(r"[a-zA-Z]{2,}", text)
                ):
                    self.hardcoded.append((self.getpos()[0], text[:120]))

        try:
            platform_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            tools_root = os.path.join(platform_root, "tools")
            templates_root = os.path.join(platform_root, "templates")

            results = []

            # Scan shared templates + module templates
            scan_dirs = [("shared", templates_root)]
            if os.path.isdir(tools_root):
                for tool_name in sorted(os.listdir(tools_root)):
                    tpl_dir = os.path.join(tools_root, tool_name, "templates")
                    if os.path.isdir(tpl_dir):
                        scan_dirs.append((tool_name, tpl_dir))

            for module_name, tpl_dir in scan_dirs:
                for root, _dirs, files in os.walk(tpl_dir):
                    for fname in files:
                        if not fname.endswith(".html"):
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                content = f.read()
                            parser = _TextExtractor()
                            parser.feed(content)
                            if parser.hardcoded:
                                results.append(
                                    {
                                        "module": module_name,
                                        "file": fname,
                                        "count": len(parser.hardcoded),
                                        "samples": [{"line": ln, "text": txt} for ln, txt in parser.hardcoded[:15]],
                                    }
                                )
                        except Exception:
                            pass

            # Sort by count descending
            results.sort(key=lambda r: r["count"], reverse=True)
            total_hardcoded = sum(r["count"] for r in results)

            return jsonify(
                {
                    "success": True,
                    "total_hardcoded": total_hardcoded,
                    "files": len(results),
                    "results": results,
                }
            )
        except Exception as e:
            logger.error(f"Template audit error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/tag-module", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_tag_module():
        """Auto-add data-i18n attributes to hardcoded text in a module's templates.

        Wraps bare English text with ``<span data-i18n="key">`` and seeds English
        translation rows so other languages can be generated afterwards.
        """
        data = request.get_json() or {}
        module_id = data.get("module_id", "").strip()
        if not module_id:
            return jsonify({"success": False, "error": "module_id required"}), 400

        SKIP_RE_OPEN = re.compile(r"<(script|style|code|pre|svg)\b", re.I)
        SKIP_RE_CLOSE = re.compile(r"</(script|style|code|pre|svg)>", re.I)
        TEXT_RE = re.compile(r"(>)([^<]+)(<)")

        def _make_key(mod, text, used):
            base = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())[:50].strip("_")
            if not base:
                base = "text"
            key = f"{mod}.{base}"
            if key in used:
                i = 2
                while f"{key}_{i}" in used:
                    i += 1
                key = f"{key}_{i}"
            return key

        def _tag_content(content, mod):
            lines = content.split("\n")
            result = []
            in_skip = 0
            keys = []
            used = set()

            # Pre-load existing keys for this module to avoid collisions
            try:
                conn2 = _get_db()
                cur2 = conn2.cursor()
                cur2.execute(
                    "SELECT key FROM translations WHERE key LIKE %s AND language='en'",
                    (f"{mod}.%",),
                )
                for row in cur2.fetchall():
                    used.add(row[0])
                cur2.close()
                conn2.close()
            except Exception:
                pass

            for line in lines:
                in_skip += len(SKIP_RE_OPEN.findall(line))
                closes = len(SKIP_RE_CLOSE.findall(line))

                if in_skip > 0:
                    in_skip = max(0, in_skip - closes)
                    result.append(line)
                    continue

                in_skip = max(0, in_skip - closes)

                if "data-i18n" in line:
                    result.append(line)
                    continue

                # Skip pure Jinja2 control lines
                stripped = line.strip()
                if stripped.startswith("{%") or stripped.startswith("{#"):
                    result.append(line)
                    continue

                def _replacer(m):
                    text = m.group(2)
                    clean = text.strip()
                    if (
                        len(clean) < 3
                        or not re.search(r"[a-zA-Z]{2,}", clean)
                        or "{{" in clean
                        or "{%" in clean
                        or clean.startswith("--")
                        or clean.startswith("//")
                    ):
                        return m.group(0)
                    key = _make_key(mod, clean, used)
                    used.add(key)
                    keys.append((key, clean))
                    return f'><span data-i18n="{key}">{text}</span><'

                new_line = TEXT_RE.sub(_replacer, line)
                result.append(new_line)

            return "\n".join(result), keys

        try:
            platform_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            files_to_tag = []

            # Shared template
            shared = os.path.join(platform_root, "templates", "tools", module_id + ".html")
            if os.path.isfile(shared):
                files_to_tag.append(shared)

            # Module-local templates
            local_tpl = os.path.join(platform_root, "tools", module_id, "templates")
            if os.path.isdir(local_tpl):
                for root, _dirs, files in os.walk(local_tpl):
                    for fname in files:
                        if fname.endswith(".html"):
                            files_to_tag.append(os.path.join(root, fname))

            if not files_to_tag:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No templates found for {module_id}",
                        }
                    ),
                    404,
                )

            total_tagged = 0
            all_keys = []
            files_modified = 0

            for fpath in files_to_tag:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                new_content, keys = _tag_content(content, module_id)
                if keys:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    total_tagged += len(keys)
                    all_keys.extend(keys)
                    files_modified += 1

            # Seed English translations
            seeded = 0
            conn = None
            cur = None
            if all_keys:
                conn = _get_db()
                cur = conn.cursor()
                module_source_label = f"module_{module_id}"
                for key, text in all_keys:
                    try:
                        cur.execute(
                            """INSERT INTO translations (key, language, text, source,
                                                         source_label, status)
                               VALUES (%s, 'en', %s, 'ai_generated', %s, 'approved')
                               ON CONFLICT (source_label, key, language) DO NOTHING""",
                            (key, text, module_source_label),
                        )
                        if cur.rowcount > 0:
                            seeded += 1
                    except Exception:
                        pass

                conn.commit()
            return jsonify(
                {
                    "success": True,
                    "module": module_id,
                    "tagged": total_tagged,
                    "keys_seeded": seeded,
                    "files_modified": files_modified,
                }
            )
        except Exception as e:
            logger.error(f"Tag module error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            if conn:
                conn.close()

    @bp.route("/api/translations/module-coverage")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_module_coverage():
        """Per-module i18n coverage -- counts data-i18n keys vs hardcoded strings."""
        import html.parser as _hp

        class _Counter(_hp.HTMLParser):
            """Count data-i18n tagged strings vs bare hardcoded text."""

            SKIP = {"script", "style", "code", "pre", "svg", "path", "option"}

            def __init__(self):
                super().__init__()
                self._skip = 0
                self._in_i18n = False
                self.tagged = 0
                self.hardcoded = 0

            def handle_starttag(self, tag, attrs):
                if tag in self.SKIP:
                    self._skip += 1
                self._in_i18n = any(k.startswith("data-i18n") for k, _ in attrs)
                if self._in_i18n:
                    self.tagged += 1

            def handle_endtag(self, tag):
                if tag in self.SKIP and self._skip > 0:
                    self._skip -= 1
                self._in_i18n = False

            def handle_data(self, data):
                if self._skip > 0 or self._in_i18n:
                    return
                text = data.strip()
                if (
                    len(text) >= 3
                    and not text.startswith("{")
                    and not text.startswith("{{")
                    and not text.startswith("--")
                    and re.search(r"[a-zA-Z]{2,}", text)
                ):
                    self.hardcoded += 1

        def _scan_file(fpath, counter):
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    counter.feed(fh.read())
            except Exception:
                pass

        try:
            platform_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            tools_root = os.path.join(platform_root, "tools")
            shared_tpl_dir = os.path.join(platform_root, "templates", "tools")

            modules = []
            try:
                all_modules = get_all_modules()
            except Exception:
                all_modules = []

            for mod in all_modules:
                counter = _Counter()

                # 1) Shared template: templates/tools/<module_id>.html
                shared_file = os.path.join(shared_tpl_dir, mod.id + ".html")
                if os.path.isfile(shared_file):
                    _scan_file(shared_file, counter)

                # 2) Module-local templates: tools/<module_id>/templates/
                mod_dir = os.path.join(tools_root, mod.id)
                tpl_dir = os.path.join(mod_dir, "templates")
                if os.path.isdir(tpl_dir):
                    for root, _dirs, files in os.walk(tpl_dir):
                        for fname in files:
                            if fname.endswith(".html"):
                                _scan_file(os.path.join(root, fname), counter)

                total = counter.tagged + counter.hardcoded
                translated = counter.tagged
                pct = round(translated * 100 / total) if total > 0 else 0

                if total == 0:
                    status = "no_templates"
                elif pct >= 90:
                    status = "done"
                elif pct > 0:
                    status = "partial"
                else:
                    status = "none"

                modules.append(
                    {
                        "id": mod.id,
                        "name": mod.name,
                        "total": total,
                        "translated": translated,
                        "hardcoded": counter.hardcoded,
                        "coverage_pct": pct,
                        "status": status,
                    }
                )

            # Sort: done first, then partial, then none
            status_order = {"done": 0, "partial": 1, "none": 2, "no_templates": 3}
            modules.sort(key=lambda m: (status_order.get(m["status"], 9), m["name"]))

            done = sum(1 for m in modules if m["status"] == "done")
            partial = sum(1 for m in modules if m["status"] == "partial")
            none_count = sum(1 for m in modules if m["status"] in ("none", "no_templates"))

            return jsonify(
                {
                    "success": True,
                    "modules": modules,
                    "summary": {
                        "total": len(modules),
                        "done": done,
                        "partial": partial,
                        "none": none_count,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Module coverage error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/coverage")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_coverage():
        """Per-source coverage stats for translations in a target language."""
        conn = None
        cur = None
        try:
            language = request.args.get("language", "fr")
            keys, _by_source = _scan_all_sources()

            if not keys:
                return jsonify(
                    {
                        "success": True,
                        "sources": {},
                        "overall": {
                            "total": 0,
                            "translated": 0,
                            "approved": 0,
                            "pending": 0,
                            "missing": 0,
                        },
                    }
                )

            # Fetch translations for discovered keys in target language
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            key_list = list(keys.keys())
            cur.execute(
                """
                SELECT key, status
                FROM translations
                WHERE language = %s AND key = ANY(%s)
                """,
                (language, key_list),
            )
            target_rows = {row["key"]: row["status"] for row in cur.fetchall()}
            # Build per-source stats
            sources = {}
            for key, info in keys.items():
                src = info["source"]
                if src not in sources:
                    sources[src] = {
                        "total": 0,
                        "translated": 0,
                        "approved": 0,
                        "pending": 0,
                        "missing": 0,
                    }
                sources[src]["total"] += 1

                status = target_rows.get(key)
                if status is None:
                    sources[src]["missing"] += 1
                else:
                    sources[src]["translated"] += 1
                    if status == "approved":
                        sources[src]["approved"] += 1
                    elif status == "pending_review":
                        sources[src]["pending"] += 1

            # Overall totals
            overall = {"total": 0, "translated": 0, "approved": 0, "pending": 0, "missing": 0}
            for stats in sources.values():
                for k in overall:
                    overall[k] += stats[k]

            return jsonify({"success": True, "sources": sources, "overall": overall})
        except Exception as e:
            logger.error(f"Translation coverage error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            if conn:
                conn.close()

    @bp.route("/api/translations/browser")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_browser():
        """Side-by-side EN/FR translation browser with filtering."""
        conn = None
        cur = None
        try:
            source_filter = request.args.get("source", "all")
            status_filter = request.args.get("status", "all")
            search_filter = request.args.get("search", "").strip().lower()
            language = request.args.get("language", "fr")

            keys, _by_source = _scan_all_sources()
            key_list = list(keys.keys())

            if not key_list:
                return jsonify({"success": True, "translations": [], "total": 0, "filtered": 0})

            # Fetch English and target language translations from DB
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT key, text
                FROM translations
                WHERE language = 'en' AND key = ANY(%s)
                """,
                (key_list,),
            )
            en_db = {row["key"]: row["text"] for row in cur.fetchall()}

            cur.execute(
                """
                SELECT id, key, text, status
                FROM translations
                WHERE language = %s AND key = ANY(%s)
                """,
                (language, key_list),
            )
            target_db = {row["key"]: row for row in cur.fetchall()}
            # Build paired list
            translations = []
            for key, info in keys.items():
                # English: prefer scan-discovered text, fall back to DB
                english_text = info.get("english") or en_db.get(key, "")

                target_row = target_db.get(key)
                if target_row:
                    target_text = target_row["text"]
                    status = target_row["status"]
                    target_id = target_row["id"]
                else:
                    target_text = None
                    status = "missing"
                    target_id = None

                translations.append(
                    {
                        "key": key,
                        "english": english_text,
                        "target": target_text,
                        "status": status,
                        "source": info["source"],
                        "file": info["file"],
                        "target_id": target_id,
                    }
                )

            total = len(translations)

            # Apply filters
            if source_filter != "all":
                translations = [t for t in translations if t["source"] == source_filter]

            if status_filter != "all":
                translations = [t for t in translations if t["status"] == status_filter]

            if search_filter:
                translations = [
                    t
                    for t in translations
                    if search_filter in t["key"].lower()
                    or search_filter in (t["english"] or "").lower()
                    or search_filter in (t["target"] or "").lower()
                ]

            return jsonify(
                {
                    "success": True,
                    "translations": translations,
                    "total": total,
                    "filtered": len(translations),
                }
            )
        except Exception as e:
            logger.error(f"Translation browser error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            if conn:
                conn.close()

    @bp.route("/api/translations/language-coverage")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_language_coverage():
        """Per-language coverage: total, approved, pending, missing counts."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Total English keys (the baseline)
            cur.execute("SELECT COUNT(DISTINCT key) AS total FROM translations WHERE language = 'en'")
            en_total = cur.fetchone()["total"]

            # Per-language stats + missing count
            cur.execute(
                """
                SELECT lang.code,
                       COUNT(DISTINCT t.key) AS translated,
                       COUNT(DISTINCT t.key) FILTER (WHERE t.status = 'approved') AS approved,
                       COUNT(DISTINCT t.key) FILTER (WHERE t.status = 'pending_review') AS pending,
                       %s - COUNT(DISTINCT t.key) AS missing
                FROM (VALUES ('fr'),('es'),('pt'),('de'),('zh'),('ar'),('he'))
                     AS lang(code)
                LEFT JOIN translations t ON t.language = lang.code
                GROUP BY lang.code
                ORDER BY lang.code
                """,
                (en_total,),
            )
            languages = []
            lang_names = {
                "fr": "French",
                "es": "Spanish",
                "pt": "Portuguese",
                "de": "German",
                "zh": "Chinese",
                "ar": "Arabic",
                "he": "Hebrew",
            }
            for row in cur.fetchall():
                languages.append(
                    {
                        "code": row["code"],
                        "name": lang_names.get(row["code"], row["code"]),
                        "total_keys": en_total,
                        "translated": row["translated"],
                        "approved": row["approved"],
                        "pending": row["pending"],
                        "missing": max(0, row["missing"]),
                        "coverage_pct": round(100 * row["translated"] / en_total, 1) if en_total > 0 else 0,
                    }
                )
            return jsonify({"success": True, "en_total": en_total, "languages": languages})
        except Exception as e:
            logger.error(f"Language coverage error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translations/generate", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_generate():
        """Generate AI translations for missing keys in a target language."""
        conn = None
        cur = None
        try:
            data = request.get_json() or {}
            language = data.get("language", "fr")
            model = data.get("model")
            if not model:
                # No hardcoded qwen3-coder-cpu (a 55GB code model translation never
                # runs). Label generated_by with the ACTUAL per-language translate
                # model so provenance is honest; inference is routed by the
                # 'translate' capability, not this label. Fail-open to a generic label.
                try:
                    from tools.consciousness.translation_scanners.generator import get_translate_routing

                    model = get_translate_routing(language)[0]
                except Exception:
                    model = None
            provided_strings = data.get("strings")

            if language == "en":
                return jsonify({"success": False, "error": "Cannot translate to English"}), 400
            if language not in SUPPORTED_LANGUAGES:
                return (
                    jsonify({"success": False, "error": f"Unsupported language: {language}"}),
                    400,
                )

            if provided_strings:
                # Use caller-supplied strings: list of {"key", "text", "context"}
                strings = [(s["key"], s["text"], s.get("context", "")) for s in provided_strings]
            else:
                # Find English keys that have no translation in the target language
                conn = _get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT DISTINCT t1.key, t1.text AS english_text, t1.context
                    FROM translations t1
                    WHERE t1.language = 'en'
                      AND NOT EXISTS (
                          SELECT 1 FROM translations t2
                          WHERE t2.key = t1.key AND t2.language = %s
                      )
                    """,
                    (language,),
                )
                rows = cur.fetchall()
                strings = [(r["key"], r["english_text"], r.get("context") or "") for r in rows]

            if not strings:
                return jsonify(
                    {
                        "success": True,
                        "message": "No missing translations found",
                        "stats": {"inserted": 0, "updated": 0, "failed": 0},
                    }
                )

            results = batch_translate(strings, language, model=model)
            # batch_translate now stores each batch incrementally
            inserted = sum(1 for r in results if r.get("success"))
            failed = sum(1 for r in results if not r.get("success"))
            stats = {"inserted": inserted, "updated": 0, "failed": failed}
            return jsonify({"success": True, "stats": stats, "total_requested": len(strings)})

        except Exception as e:
            logger.error(f"Translation generate error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                if cur:
                    cur.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    @bp.route("/api/translations/generate-async", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_generate_async():
        """Launch background translation job -- returns immediately with job_id.

        Body options:
            { "languages": ["fr"] }                -- one language
            { "languages": ["fr","es",...,"he"] }   -- all languages
            { "module_id": "bridge" }               -- module-scoped, all 7 languages
            { "module_id": "bridge", "languages": ["fr"] }  -- module + single lang
        """
        conn = None
        cur = None
        try:
            data = request.get_json() or {}
            languages = data.get("languages") or [
                "fr",
                "es",
                "pt",
                "de",
                "zh",
                "ar",
                "he",
            ]
            module_id = data.get("module_id")

            # Validate
            invalid = [l for l in languages if l not in SUPPORTED_LANGUAGES or l == "en"]
            if invalid:
                return (
                    jsonify({"success": False, "error": f"Invalid languages: {invalid}"}),
                    400,
                )

            # Build description
            scope = f" ({module_id})" if module_id else ""
            lang_label = languages[0].upper() if len(languages) == 1 else f"{len(languages)} languages"
            desc = f"Translate {lang_label}{scope}"

            # Count total missing keys across all requested languages
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            total_missing = 0
            for lang in languages:
                module_filter = ""
                params = [lang]
                if module_id:
                    module_filter = "AND t1.key LIKE %s"
                    params.append(f"{module_id}.%")
                cur.execute(
                    f"""
                    SELECT count(DISTINCT t1.key) AS cnt
                    FROM translations t1
                    WHERE t1.language = 'en'
                      AND NOT EXISTS (
                          SELECT 1 FROM translations t2
                          WHERE t2.key = t1.key AND t2.language = %s
                      )
                      {module_filter}
                    """,
                    params,
                )
                total_missing += (cur.fetchone() or {}).get("cnt", 0)
            if total_missing == 0:
                return jsonify(
                    {
                        "success": True,
                        "message": "No missing translations",
                        "job_id": None,
                        "total": 0,
                    }
                )

            # Create parent bridge job
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            job_id = dispatcher.create_job(
                job_type="translate_languages",
                module_source="consciousness",
                description=desc,
                total_steps=len(languages),
                capability="translate",
                metadata={
                    "languages": languages,
                    "module_id": module_id,
                    "total_keys": total_missing,
                },
            )

            if not job_id:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Station at capacity -- cloud approval requested via Telegram, or a job is already running",
                            "duplicate": True,
                        }
                    ),
                    409,
                )

            # Launch background thread
            thread = threading.Thread(
                target=_run_translate_bg,
                args=(languages, module_id, job_id),
                daemon=True,
            )
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "total": total_missing,
                    "languages": languages,
                    "message": f"Translation job #{job_id} started -- {total_missing} keys across {lang_label}",
                }
            )

        except Exception as e:
            logger.error(f"Async translation generate error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            try:
                if cur:
                    cur.close()
            except Exception:
                pass
            if conn:
                conn.close()

    @bp.route("/api/translations/review")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_review():
        """Get translations for review, filterable by language and status."""
        conn = None
        cur = None
        conn = None
        cur = None
        try:
            language = request.args.get("language", "fr")
            status = request.args.get("status", "pending_review")

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if status == "all":
                cur.execute(
                    """
                    SELECT id, key, language, text, source, status, context,
                           generated_by, reviewed_by, created_at, updated_at
                    FROM translations
                    WHERE language = %s
                    ORDER BY updated_at DESC
                    """,
                    (language,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, key, language, text, source, status, context,
                           generated_by, reviewed_by, created_at, updated_at
                    FROM translations
                    WHERE language = %s AND status = %s
                    ORDER BY updated_at DESC
                    """,
                    (language, status),
                )

            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for k in ("created_at", "updated_at"):
                    if d.get(k):
                        d[k] = d[k].isoformat()
                result.append(d)

            return jsonify({"success": True, "translations": result, "count": len(result)})
        except Exception as e:
            logger.error(f"Translation review error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translations/approve", methods=["PUT"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_approve():
        """Approve, reject, or edit a single translation."""
        conn = None
        cur = None
        try:
            data = request.get_json() or {}
            translation_id = data.get("id")
            action = data.get("action")

            if not translation_id or action not in ("approve", "reject", "edit"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "id and action (approve|reject|edit) required",
                        }
                    ),
                    400,
                )

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if action == "approve":
                cur.execute(
                    """
                    UPDATE translations
                    SET status = 'approved', reviewed_by = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING source_label
                    """,
                    (current_user.id, translation_id),
                )
                approved_row = cur.fetchone()
            elif action == "reject":
                cur.execute(
                    """
                    UPDATE translations
                    SET status = 'rejected', reviewed_by = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (current_user.id, translation_id),
                )
            elif action == "edit":
                new_text = data.get("text")
                if not new_text:
                    return (
                        jsonify({"success": False, "error": "text required for edit action"}),
                        400,
                    )

                cur.execute(
                    """
                    UPDATE translations
                    SET text = %s, source = 'human_edited', status = 'approved',
                        reviewed_by = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING key, language, source_label
                    """,
                    (new_text, current_user.id, translation_id),
                )
                updated = cur.fetchone()
                if updated:
                    # Save correction to translation_memory
                    cur.execute(
                        """SELECT text FROM translations
                           WHERE source_label = %s AND key = %s AND language = 'en'""",
                        (updated["source_label"], updated["key"]),
                    )
                    en_row = cur.fetchone()
                    if en_row:
                        cur.execute(
                            """
                            INSERT INTO translation_memory
                                (source_text, translated_text, language, category,
                                 created_by, created_at)
                            VALUES (%s, %s, %s, 'ui', %s, NOW())
                            """,
                            (
                                en_row["text"],
                                new_text,
                                updated["language"],
                                current_user.id,
                            ),
                        )

            conn.commit()

            # After commit, trigger async bundle export for the affected domain.
            # Determines source_label from the updated row (approve path) or the
            # RETURNING clause already captured by the edit path.
            _source_label = None
            if action == "approve" and approved_row:
                _source_label = approved_row.get("source_label")
            elif action == "edit" and updated:
                _source_label = updated.get("source_label")

            if _source_label:
                _bundle_lookup = {label: bpath for label, _dir, bpath in EXTERNAL_SCAN_SOURCES if bpath is not None}
                _bundle_path = _bundle_lookup.get(_source_label)
                if _bundle_path:

                    def _bg_export(src=_source_label, path=_bundle_path):
                        try:
                            from tools.consciousness.translation_scanners.orchestrator import (
                                _export_bundle,
                            )

                            count = _export_bundle(src, path)
                            logger.info(f"Post-approve bundle export: {src} → {path} ({count} keys)")
                        except Exception as ex:
                            logger.error(f"Post-approve bundle export failed [{src}]: {ex}")

                    threading.Thread(target=_bg_export, daemon=True).start()

            return jsonify({"success": True, "action": action, "id": translation_id})
        except Exception as e:
            logger.error(f"Translation approve error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translations/bulk-approve", methods=["PUT"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_bulk_approve():
        """Bulk-approve translations by list of IDs."""
        conn = None
        cur = None
        conn = None
        cur = None
        try:
            data = request.get_json() or {}
            ids = data.get("ids", [])
            if not ids:
                return jsonify({"success": False, "error": "ids list required"}), 400

            conn = _get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE translations
                SET status = 'approved', reviewed_by = %s, updated_at = NOW()
                WHERE id = ANY(%s)
                """,
                (current_user.id, ids),
            )
            count = cur.rowcount
            conn.commit()
            return jsonify({"success": True, "approved_count": count})
        except Exception as e:
            logger.error(f"Translation bulk approve error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translation-memory", methods=["GET", "POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_memory_api():
        """GET: list translation memory entries. POST: add a new entry."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            if request.method == "GET":
                language = request.args.get("language", "fr")
                cur.execute(
                    """
                    SELECT id, source_text, translated_text, language, category,
                           created_by, created_at
                    FROM translation_memory
                    WHERE language = %s
                    ORDER BY category, source_text
                    """,
                    (language,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    if d.get("created_at"):
                        d["created_at"] = d["created_at"].isoformat()
                    result.append(d)
                return jsonify({"success": True, "entries": result, "count": len(result)})

            # POST - add new entry
            data = request.get_json() or {}
            source_text = data.get("source_text")
            translated_text = data.get("translated_text")
            language = data.get("language", "fr")
            category = data.get("category", "ui")

            if not source_text or not translated_text:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "source_text and translated_text required",
                        }
                    ),
                    400,
                )

            cur.execute(
                """
                INSERT INTO translation_memory
                    (source_text, translated_text, language, category, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (source_text, translated_text, language, category, current_user.id),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            return jsonify({"success": True, "id": new_id})

        except Exception as e:
            logger.error(f"Translation memory error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translation-memory/<int:entry_id>", methods=["DELETE"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_memory_delete(entry_id):
        """Delete a translation memory entry by ID."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor()
            cur.execute("DELETE FROM translation_memory WHERE id = %s", (entry_id,))
            deleted = cur.rowcount
            conn.commit()
            if deleted == 0:
                return jsonify({"success": False, "error": "Entry not found"}), 404
            return jsonify({"success": True, "deleted_id": entry_id})
        except Exception as e:
            logger.error(f"Translation memory delete error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/api/translations/export-bundle", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_export_bundle():
        """Export translations from DB to a static translations.json bundle for an external site.

        Request JSON: {"source": "website_kytranempowerment"} (matches EXTERNAL_SCAN_SOURCES label)
        """
        conn = None
        cur = None
        try:
            data = request.get_json(force=True) or {}
            source_label = data.get("source", "")

            target = None
            for label, _dir, bundle_path in EXTERNAL_SCAN_SOURCES:
                if label == source_label:
                    target = (label, _dir, bundle_path)
                    break

            if not target:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Unknown source: {source_label}",
                            "available": [s[0] for s in EXTERNAL_SCAN_SOURCES],
                        }
                    ),
                    400,
                )

            label, site_dir, bundle_path = target
            if not bundle_path:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No bundle path configured for {label}",
                        }
                    ),
                    400,
                )

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Collect all data-i18n keys from the site HTML
            source_keys = set()
            i18n_pat = re.compile(r'data-i18n(?:-\w+)?="([^"]+)"')
            for root, _dirs, files in os.walk(site_dir):
                if any(skip in root for skip in ("/.git", "/node_modules", "/__pycache__")):
                    continue
                for fname in files:
                    if not fname.endswith(".html") or fname.startswith("_"):
                        continue
                    try:
                        with open(os.path.join(root, fname), "r", encoding="utf-8") as fh:
                            for m in i18n_pat.finditer(fh.read()):
                                source_keys.add(m.group(1))
                    except Exception:
                        pass

            if not source_keys:
                return jsonify({"success": False, "error": "No keys found"}), 404

            # Build bundle from DB
            bundle = {}
            for lang_code in SUPPORTED_LANGUAGES:
                cur.execute(
                    """SELECT key, text FROM translations
                       WHERE language = %s AND key = ANY(%s)
                       AND text IS NOT NULL AND text != ''""",
                    (lang_code, list(source_keys)),
                )
                bundle[lang_code] = {r["key"]: r["text"] for r in cur.fetchall()}

            # An export that resolved NO translations is a failure, not a success
            # (#5750). Writing an empty bundle overwrites a possibly-good file with
            # nothing and then reports success, which is how WTF's i18n pipeline sat
            # broken while every nightly run looked green. Refuse before writing.
            total_pairs = sum(len(v) for v in bundle.values())
            if total_pairs == 0:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                f"Refusing to write an EMPTY bundle for {label}: "
                                f"{len(source_keys)} key(s) found in {site_dir} but none "
                                f"resolved to a translation in the DB. Either the source "
                                f"directory is stale or the keys were never ingested."
                            ),
                            "source": label,
                            "source_keys": len(source_keys),
                            "bundle_path": bundle_path,
                        }
                    ),
                    409,
                )

            os.makedirs(os.path.dirname(bundle_path), exist_ok=True)
            with open(bundle_path, "w", encoding="utf-8") as f:
                _json.dump(bundle, f, indent=2, ensure_ascii=False)

            stats = {lang: len(keys) for lang, keys in bundle.items()}
            logger.info(f"Exported bundle for {label}: {len(source_keys)} keys -> {bundle_path}")

            return jsonify(
                {
                    "success": True,
                    "source": label,
                    "bundle_path": bundle_path,
                    "total_keys": len(source_keys),
                    "by_language": stats,
                }
            )
        except Exception as e:
            logger.error(f"Translation export error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # --- Full-scan trigger + coverage health query (task #232) ---

    @bp.route("/api/translations/full-scan", methods=["POST"])
    @admin_required
    def trigger_full_scan():
        """Kick off the orchestrator in a background thread.

        Single-flight: if a scan is already running, refuse instead of spawning
        a parallel one (parallel scans double DB write load and can race on
        translation_gaps upserts — see migration 322).
        """
        from tools.consciousness.translation_scanners.orchestrator import (
            run_translation_coverage_scan,
        )

        if not _full_scan_lock.acquire(blocking=False):
            return (
                jsonify({"success": False, "error": "scan already in progress"}),
                409,
            )

        def _run():
            try:
                run_translation_coverage_scan()
            except Exception:  # noqa: BLE001
                logger.exception("full-scan failed")
            finally:
                _full_scan_lock.release()

        threading.Thread(target=_run, daemon=True, name="translation-full-scan").start()
        return jsonify({"success": True, "message": "scan started"})

    @bp.route("/api/translations/coverage-health", methods=["GET"])
    @admin_required
    def coverage_health():
        """Per-source per-language coverage % + open-gap counts."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT source_label AS source, language,
                          COUNT(*) AS total,
                          SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,
                          MAX(updated_at) AS last_updated
                   FROM translations
                   WHERE source_label IS NOT NULL
                   GROUP BY source_label, language"""
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """SELECT source, gap_type, COUNT(*) AS n
                   FROM translation_gaps
                   WHERE status NOT IN ('resolved', 'dismissed')
                   GROUP BY source, gap_type"""
            )
            gap_rows = [dict(r) for r in cur.fetchall()]
            return jsonify({"coverage": rows, "open_gaps": gap_rows})
        except Exception as e:
            logger.error(f"coverage-health query error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # ── Languages Tab — Translation Command Center ────────────────────────

    @bp.route("/api/translations/coverage-matrix")
    @admin_required
    def translation_coverage_matrix():
        """9×8 coverage matrix: domain_registry × 9 languages."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT name, display_name, is_active, active_languages, last_audit_at "
                "FROM translation_domain_registry ORDER BY is_active DESC, name"
            )
            domains = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """SELECT REPLACE(source,'domain:','') AS domain_name, language,
                          COUNT(*) AS gap_count
                   FROM translation_gaps
                   WHERE status IN ('open','routed') AND source LIKE 'domain:%%'
                   GROUP BY domain_name, language"""
            )
            gap_counts = {f"{r['domain_name']}:{r['language']}": r["gap_count"] for r in cur.fetchall()}
            cur.execute(
                """SELECT REPLACE(source,'domain:','') AS domain_name,
                          COUNT(DISTINCT key) AS total_keys
                   FROM translation_gaps WHERE source LIKE 'domain:%%'
                   GROUP BY domain_name"""
            )
            total_keys = {r["domain_name"]: r["total_keys"] for r in cur.fetchall()}
            cur.close()
            conn.close()
            matrix = _build_coverage_matrix(domains, gap_counts, total_keys)
            return jsonify(
                {
                    "success": True,
                    "matrix": matrix,
                    "domains": domains,
                    "summary": {
                        "total_open_gaps": sum(gap_counts.values()),
                        "domains_active": sum(1 for d in domains if d["is_active"]),
                        "domains_total": len(domains),
                    },
                }
            )
        except Exception as e:
            logger.error(f"Coverage matrix error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/gap-feed")
    @admin_required
    def translation_gap_feed():
        """Paginated domain gap feed, filterable by domain/language/type."""
        domain = request.args.get("domain", "")
        language = request.args.get("language", "")
        gap_type = request.args.get("gap_type", "")
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 50))))
        offset = (page - 1) * per_page
        try:
            conditions = ["status IN ('open','routed')", "source LIKE 'domain:%%'"]
            params: list = []
            if domain:
                conditions.append("source = %s")
                params.append(f"domain:{domain}")
            if language:
                conditions.append("language = %s")
                params.append(language)
            if gap_type:
                conditions.append("gap_type = %s")
                params.append(gap_type)
            where = " AND ".join(conditions)
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(f"SELECT COUNT(*) AS n FROM translation_gaps WHERE {where}", params)
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT id, source, gap_type, language, key, snippet, "
                f"status, task_id, created_at "
                f"FROM translation_gaps WHERE {where} "
                f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [per_page, offset],
            )
            gaps = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return jsonify({"success": True, "gaps": gaps, "total": total, "page": page, "per_page": per_page})
        except Exception as e:
            logger.error(f"Gap feed error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/rosetta-queue")
    @admin_required
    def rosetta_work_queue():
        """R.O.S.E.T.T.A. active and pending translation tasks."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT id, title, status, priority, created_at, completed_at
                   FROM unified_tasks
                   WHERE (title ILIKE '%translate%' OR title ILIKE '%semantic_describe%')
                     AND status IN ('pending','in_progress','completed')
                   ORDER BY
                     CASE status WHEN 'in_progress' THEN 0
                                 WHEN 'pending' THEN 1 ELSE 2 END,
                     created_at DESC
                   LIMIT 30"""
            )
            tasks = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return jsonify({"success": True, "tasks": tasks})
        except Exception as e:
            logger.error(f"Rosetta queue error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/dispatch-gap", methods=["POST"])
    @admin_required
    def dispatch_translation_gap():
        """Dispatch a single gap to R.O.S.E.T.T.A. immediately."""
        from services.delegation_service import delegate_task

        body = request.get_json(silent=True) or {}
        gap_id = body.get("gap_id")
        domain = body.get("domain", "")
        language = body.get("language", "")
        key = body.get("key", "")
        if not all([gap_id, language, key]):
            return jsonify({"success": False, "error": "gap_id, language, key required"}), 400
        try:
            cap = "semantic_describe" if language == "ai" else "translate"
            result = delegate_task(
                capability=cap,
                reason=f"Manual dispatch: key='{key}' lang='{language}' domain:{domain}",
                args={"language": language, "keys": [key], "sources": [f"domain:{domain}"], "gap_ids": [gap_id]},
                delegation_source="user_cli",
                requested_by="consciousness_languages_tab",
                priority=7,
            )
            if result.get("success"):
                conn = _get_db()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id=%s",
                    (result.get("task_id"), gap_id),
                )
                conn.commit()
                cur.close()
                conn.close()
            return jsonify(result)
        except Exception as e:
            logger.error(f"dispatch-gap error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
