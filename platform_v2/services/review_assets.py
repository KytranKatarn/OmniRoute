"""Bounded mechanical review of large added assets; never an approval oracle."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from services.review_coverage import split_blocks

POLICY_VERSION = "passive-assets-v1"
MAX_BYTES = 2 * 1024 * 1024
_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "title", "desc"}
_ATTRS = {
    "viewBox",
    "width",
    "height",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "d",
    "points",
    "fill",
    "fill-rule",
    "fill-opacity",
    "stroke",
    "stroke-opacity",
    "stroke-dasharray",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "opacity",
    "transform",
    "font-size",
    "font-family",
    "font-weight",
    "text-anchor",
    "id",
    "class",
    "role",
    "aria-label",
}


def _complete_addition(block):
    """Only a complete new-file hunk can establish the bytes actually checked."""
    if "--- /dev/null\n" not in block:
        return None
    hunks = list(re.finditer(r"^@@ -0,0 \+1(?:,(\d+))? @@[^\n]*\n", block, re.M))
    if len(hunks) != 1 or len(re.findall(r"^@@", block, re.M)) != 1:
        return None
    lines = block[hunks[0].end() :].splitlines()
    no_newline = bool(lines and lines[-1] == "\\ No newline at end of file")
    if no_newline:
        lines.pop()
    if len(lines) != int(hunks[0].group(1) or 1) or any(not line.startswith("+") for line in lines):
        return None
    return "\n".join(line[1:] for line in lines) + ("" if no_newline else "\n")


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate_json_key")
        out[key] = value
    return out


@lru_cache(maxsize=32)
def _inspect(kind, content):
    """Cache exact bytes + policy in this process, not model verdicts."""
    raw = content.encode("utf-8")
    result = {
        "policy": POLICY_VERSION,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "kind": kind,
        "status": "unvalidated",
        "human_review_required": True,
    }
    if len(raw) > MAX_BYTES:
        return {**result, "reason": "asset_size_limit"}
    try:
        if kind == "svg":
            if re.search(r"<!\s*(DOCTYPE|ENTITY)", content, re.I):
                raise ValueError("xml_declaration_forbidden")
            root = ET.fromstring(content)
            if root.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
                raise ValueError("not_svg")
            count = 0
            for node in root.iter():
                count += 1
                if count > 50000:
                    raise ValueError("svg_node_limit")
                if node.tag not in _TAGS and node.tag not in {"{http://www.w3.org/2000/svg}" + t for t in _TAGS}:
                    raise ValueError("active_or_unknown_svg_element")
                for name, value in node.attrib.items():
                    if name not in _ATTRS or any(
                        token in value.casefold() for token in ("url(", "javascript:", "://", "@import")
                    ):
                        raise ValueError("active_or_unknown_svg_attribute")
            result.update(status="passive_svg_subset", nodes=count)
        else:
            value = json.loads(
                content,
                object_pairs_hook=_unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite_json")),
            )
            result.update(status="json_structure_only", root_type=type(value).__name__)
            if isinstance(value, dict):
                result["collections"] = {
                    str(k)[:60]: len(v) for k, v in list(value.items())[:10] if isinstance(v, (list, dict))
                }
            elif isinstance(value, list):
                result["items"] = len(value)
    except (ValueError, ET.ParseError, RecursionError):
        result.update(status="unvalidated", reason="invalid_or_unsupported_asset")
    return result


def prepare_review_assets(diff):
    """Remove only large COMPLETE additions; keep modified/partial assets verbatim.

    Returned reports must be exposed with a human-review gate. Structural checks
    do not establish licensing, visual correctness, factual truth or model coverage.
    """
    kept, reports = [], []
    for path, block in split_blocks(diff):
        kind = None
        if re.fullmatch(r"[A-Za-z0-9_./-]+", path or ""):
            if path.lower().endswith(".svg") and len(block) > 8192:
                kind = "svg"
            elif path.lower().endswith(".json") and len(block) > 16384 and re.search(r"(^|/)(data|fixtures)/", path):
                kind = "json"
        content = _complete_addition(block) if kind else None
        if content is None:
            kept.append(block)
        else:
            inspect = _inspect if len(content.encode("utf-8")) <= MAX_BYTES else _inspect.__wrapped__
            reports.append({"path": path, **inspect(kind, content)})
    return "".join(kept), reports


def asset_review_note(reports):
    if not reports:
        return ""
    return (
        "[deterministic-assets] Mechanical checks only; these files were NOT read by the LLM. "
        "Visual, provenance/licensing and factual review remain human responsibilities.\n"
        + "\n".join(json.dumps(row, sort_keys=True) for row in reports)
    )
