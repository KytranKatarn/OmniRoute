"""Mechanical evidence is bounded and never silently becomes an LLM approval."""

from unittest import mock

import pytest

from services.review_assets import prepare_review_assets, _inspect
from tools.repair_bay.services import pr_diff_analyzer as pda


def addition(path, content):
    lines = content.splitlines()
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + line + "\n" for line in lines)
    )


def large_svg(extra=""):
    return '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 ' + "L1 1 " * 2000 + '"/>' + extra + "</svg>\n"


def test_large_svg_is_checked_without_coordinate_model_input():
    diff = addition("maps/canada.svg", large_svg())
    remaining, reports = prepare_review_assets(diff)
    assert remaining == ""
    assert reports[0]["status"] == "passive_svg_subset"
    assert reports[0]["bytes"] == len(large_svg().encode())
    assert reports[0]["human_review_required"] is True
    assert len(reports[0]["sha256"]) == 64


@pytest.mark.parametrize(
    "extra",
    [
        "<script>alert(1)</script>",
        '<image href="https://example.com/x"/>',
        "<foreignObject/>",
        '<g onload="alert(1)"/>',
        '<style>@import "x";</style>',
    ],
)
def test_active_or_external_svg_is_never_validated(extra):
    _, reports = prepare_review_assets(addition("maps/canada.svg", large_svg(extra)))
    assert reports[0]["status"] == "unvalidated"
    assert reports[0]["human_review_required"] is True


def test_entity_declarations_and_encoded_style_urls_are_rejected():
    for content in ('<!DOCTYPE svg [<!ENTITY e "x">]>' + large_svg(), large_svg('<path fill="u&#114;l(https://x)"/>')):
        _, reports = prepare_review_assets(addition("maps/a.svg", content))
        assert reports[0]["status"] == "unvalidated"


def test_partial_or_modified_file_is_not_mistaken_for_complete_bytes():
    full = addition("maps/canada.svg", large_svg())
    modified = full.replace("--- /dev/null", "--- a/maps/canada.svg")
    remaining, reports = prepare_review_assets(modified)
    assert remaining == modified and not reports
    partial = full.replace("@@ -0,0 +1,1 @@", "@@ -0,0 +1,2 @@")
    assert prepare_review_assets(partial) == (partial, [])


def test_large_data_json_is_structure_only_and_config_stays_verbatim():
    import json

    content = json.dumps({"events": [{"draft": True, "text": "x" * 20000}]}) + "\n"
    _, reports = prepare_review_assets(addition("consumer/data/history/events.json", content))
    assert reports[0]["status"] == "json_structure_only"
    assert reports[0]["collections"] == {"events": 1}
    diff = addition("config/settings.json", content)
    assert prepare_review_assets(diff) == (diff, [])


def test_duplicate_keys_and_nonfinite_numbers_fail_structure_check():
    for content in ('{"x":1,"x":2,"padding":"' + "x" * 20000 + '"}', '{"x":NaN,"padding":"' + "x" * 20000 + '"}'):
        _, reports = prepare_review_assets(addition("data/events.json", content))
        assert reports[0]["status"] == "unvalidated"


def test_cached_validation_invalidates_when_bytes_change():
    _inspect.cache_clear()
    prepare_review_assets(addition("maps/a.svg", large_svg()))
    prepare_review_assets(addition("maps/a.svg", large_svg()))
    assert _inspect.cache_info().hits == 1
    prepare_review_assets(addition("maps/a.svg", large_svg("<script/>")))
    assert _inspect.cache_info().misses == 2


def test_asset_only_review_never_dispatches_or_approves():
    with mock.patch.object(pda, "_obtain_text_review_summary") as review:
        summary = pda._obtain_review_summary({"title": "maps"}, addition("maps/a.svg", large_svg()))
    review.assert_not_called()
    assert "NOT read by the LLM" in summary
    assert pda.parse_verdict(summary) == "NEEDS REVIEW"


def test_code_review_keeps_original_diff_grounding_and_blocking_findings():
    code = "diff --git a/a.py b/a.py\n+x = 1\n"
    full = code + addition("maps/a.svg", large_svg())
    with mock.patch.object(pda, "_obtain_text_review_summary", return_value="VERDICT: REQUEST CHANGES") as review:
        summary = pda._obtain_review_summary({"title": "mixed"}, full, 42, "o/r")
    assert review.call_args.args[1] == code
    assert review.call_args.kwargs["ground_diff"] == full
    assert pda.parse_verdict(summary) == "REQUEST CHANGES"
