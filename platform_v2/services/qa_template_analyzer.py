"""P.R.O.B.E. Template Analyzer — static inline CSS/JS + duplicate-block scan.

Detects templates that carry too much inline styling or scripting (should be
extracted to ``/static/css/`` or ``/static/js/``) and ``<style>`` blocks that
appear in two or more templates (extract to a shared stylesheet).

Design doc: docs/superpowers/specs/2026-04-16-probe-capability-upgrade-design.md
Task: #2028 — follow-up to research task #2022.

YAML test spec::

    - name: ac-template-health
      type: template_analysis
      targets:
        - "templates/tools/account_center.html"
        - "templates/tools/account_center_includes/*.html"
      thresholds:
        max_inline_css_lines: 50
        max_inline_js_lines: 100
        max_duplicate_block_members: 1   # 2+ members fails

The analyzer is synchronous — BeautifulSoup reads files directly from disk,
no HTTP / browser needed. Results fit in the existing ``qa_test_results.details``
JSONB column; no new DB table.
"""

import glob
import hashlib
import logging
import os
import re

from bs4 import BeautifulSoup

logger = logging.getLogger("probe.template")


# Default repo root if the test spec doesn't override. Inside the platform
# container `platform_v2` is mounted at `/app`; on the host (where the MCP
# server runs) it lives at `<repo>/platform_v2`. Detect both so YAML targets
# like `templates/tools/account_center.html` resolve in either context.
def _detect_repo_root():
    if os.path.isdir("/app/templates/tools"):
        return "/app"
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.dirname(here)  # platform_v2/
    if os.path.isdir(os.path.join(candidate, "templates", "tools")):
        return candidate
    return "/app"


DEFAULT_REPO_ROOT = _detect_repo_root()

DEFAULT_THRESHOLDS = {
    "max_inline_css_lines": 50,
    "max_inline_js_lines": 100,
    # Hash group with (members > max_duplicate_block_members) fails.
    # Default 1 means: a block appearing in 2+ templates is a failure.
    "max_duplicate_block_members": 1,
    # Minimum block size (chars after normalization) to be considered for
    # duplicate detection — filters out trivial single-selector rules.
    "min_block_chars_for_dedup": 60,
}


def _normalize_block(text):
    """Collapse whitespace and strip comments for hash comparison."""
    if not text:
        return ""
    # CSS comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # HTML comments (safe even inside <style> — some templates have them)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _hash_block(text):
    return hashlib.sha256(_normalize_block(text).encode("utf-8")).hexdigest()[:16]


def _count_lines(text):
    if not text or not text.strip():
        return 0
    return text.count("\n") + 1


def _expand_targets(targets, repo_root):
    """Resolve glob patterns relative to repo_root and return absolute paths."""
    files = []
    for pattern in targets or []:
        abs_pat = pattern if os.path.isabs(pattern) else os.path.join(repo_root, pattern)
        files.extend(glob.glob(abs_pat))
    return sorted(set(files))


def analyze_templates(targets, thresholds=None, repo_root=None):
    """Analyze a set of templates. Returns list of result dicts.

    Emits two result types per file (``inline-css-{path}`` and
    ``inline-js-{path}``) plus one result per duplicate block group, and
    a ``duplicate-style-blocks`` pass if no duplicates are found.
    """
    repo_root = repo_root or DEFAULT_REPO_ROOT
    merged_thresholds = dict(DEFAULT_THRESHOLDS)
    merged_thresholds.update(thresholds or {})
    max_css = int(merged_thresholds["max_inline_css_lines"])
    max_js = int(merged_thresholds["max_inline_js_lines"])
    max_dup = int(merged_thresholds["max_duplicate_block_members"])
    min_dedup_chars = int(merged_thresholds["min_block_chars_for_dedup"])

    files = _expand_targets(targets, repo_root)

    if not files:
        return [
            {
                "test_name": "template-analysis-targets",
                "test_type": "template_analysis",
                "status": "error",
                "error_message": f"No files matched targets: {targets}",
                "assertions": {"targets": targets, "repo_root": repo_root},
            }
        ]

    results = []
    # hash -> list[(rel_path, block_excerpt)]
    block_locations = {}

    for abs_path in files:
        rel = os.path.relpath(abs_path, repo_root)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            results.append(
                {
                    "test_name": f"template-read-{rel}",
                    "test_type": "template_analysis",
                    "status": "error",
                    "url": rel,
                    "error_message": f"Could not read {rel}: {e}",
                }
            )
            continue

        soup = BeautifulSoup(html, "html.parser")

        # Inline CSS
        css_lines = 0
        for style in soup.find_all("style"):
            content = style.string or ""
            css_lines += _count_lines(content)
            normalized = _normalize_block(content)
            if len(normalized) >= min_dedup_chars:
                block_locations.setdefault(_hash_block(content), []).append((rel, normalized[:120]))

        # Inline JS (only blocks without a src)
        js_lines = 0
        for script in soup.find_all("script"):
            if script.get("src"):
                continue
            content = script.string or ""
            js_lines += _count_lines(content)

        css_status = "pass" if css_lines <= max_css else "fail"
        results.append(
            {
                "test_name": f"inline-css-{rel}",
                "test_type": "template_analysis",
                "status": css_status,
                "url": rel,
                "error_message": (
                    f"{css_lines} inline CSS lines in {rel} (max {max_css}) — " "extract to /static/css/"
                    if css_status == "fail"
                    else None
                ),
                "assertions": {
                    "file": rel,
                    "inline_css_lines": css_lines,
                    "max_inline_css_lines": max_css,
                },
            }
        )

        js_status = "pass" if js_lines <= max_js else "fail"
        results.append(
            {
                "test_name": f"inline-js-{rel}",
                "test_type": "template_analysis",
                "status": js_status,
                "url": rel,
                "error_message": (
                    f"{js_lines} inline JS lines in {rel} (max {max_js}) — " "extract to /static/js/"
                    if js_status == "fail"
                    else None
                ),
                "assertions": {
                    "file": rel,
                    "inline_js_lines": js_lines,
                    "max_inline_js_lines": max_js,
                },
            }
        )

    # Duplicate-block detection across the target set
    dup_groups = [(h, locs) for h, locs in block_locations.items() if len(locs) > max_dup]
    if dup_groups:
        for h, locs in dup_groups:
            files_involved = sorted({loc[0] for loc in locs})
            results.append(
                {
                    "test_name": f"duplicate-style-{h[:8]}",
                    "test_type": "template_analysis",
                    "status": "fail",
                    "error_message": (
                        f"<style> block repeated across {len(files_involved)} "
                        f"templates: {', '.join(files_involved)} — "
                        "extract to a shared stylesheet"
                    ),
                    "assertions": {
                        "block_hash": h,
                        "files": files_involved,
                        "member_count": len(locs),
                        "excerpt": locs[0][1],
                    },
                }
            )
    else:
        results.append(
            {
                "test_name": "duplicate-style-blocks",
                "test_type": "template_analysis",
                "status": "pass",
                "assertions": {
                    "scanned_files": len(files),
                    "scanned_blocks": len(block_locations),
                    "min_block_chars_for_dedup": min_dedup_chars,
                },
            }
        )

    return results


def run_template_analysis_test(test, repo_root=None):
    """Entry point called by qa_spec_runner for a single template_analysis test."""
    targets = test.get("targets") or []
    thresholds = test.get("thresholds") or {}
    try:
        return analyze_templates(targets=targets, thresholds=thresholds, repo_root=repo_root)
    except Exception as e:
        logger.exception("template_analysis failed for %s", test.get("name"))
        return [
            {
                "test_name": test.get("name", "template_analysis"),
                "test_type": "template_analysis",
                "status": "error",
                "error_message": str(e)[:500],
            }
        ]
