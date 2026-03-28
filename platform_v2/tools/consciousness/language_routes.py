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

logger = logging.getLogger(__name__)


def _get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


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
                        if key not in keys:
                            keys[key] = {
                                "source": "template",
                                "file": rel_path,
                                "english": text_map.get(key, ""),
                            }
                except Exception as read_err:
                    logger.warning(f"Scan: could not read {rel_path}: {read_err}")

    by_source["template"] = sum(1 for v in keys.values() if v["source"] == "template")

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

        for key, info in keys_dict.items():
            english = info.get("english", "")
            source_type = info.get("source", "")
            if not english:
                skipped += 1
                continue

            context = context_map.get(source_type, source_type)

            cur.execute(
                """
                INSERT INTO translations (key, language, text, source, status, context,
                                          created_at, updated_at)
                VALUES (%s, 'en', %s, 'imported', 'approved', %s, NOW(), NOW())
                ON CONFLICT (key, language) DO NOTHING
                """,
                (key, english, context),
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
    from ai_bridge.bridge_dispatcher import get_dispatcher

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
                        model="qwen3-coder-cpu",
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
                attr_dict = dict(attrs)
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
                for key, text in all_keys:
                    try:
                        cur.execute(
                            """INSERT INTO translations (key, language, text, source, status)
                               VALUES (%s, 'en', %s, 'ai_generated', 'approved')
                               ON CONFLICT (key, language) DO NOTHING""",
                            (key, text),
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
                       COUNT(t.id) AS translated,
                       COUNT(t.id) FILTER (WHERE t.status = 'approved') AS approved,
                       COUNT(t.id) FILTER (WHERE t.status = 'pending_review') AS pending,
                       %s - COUNT(t.id) AS missing
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
            model = data.get("model", "qwen3-coder-cpu")
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
            from ai_bridge.bridge_dispatcher import get_dispatcher

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
                    """,
                    (current_user.id, translation_id),
                )
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
                    RETURNING key, language
                    """,
                    (new_text, current_user.id, translation_id),
                )
                updated = cur.fetchone()
                if updated:
                    # Save correction to translation_memory
                    cur.execute(
                        "SELECT text FROM translations WHERE key = %s AND language = 'en'",
                        (updated["key"],),
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
