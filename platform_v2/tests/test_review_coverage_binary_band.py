"""Binary assets must not consume review passes meant for code.

`forge:review_plan=per_file` gives EVERY file its own serial dispatch, so a
binary file costs a whole dispatch to review a "Binary files differ" stub. Before
band 3 existed, a `.jpg` and a `.json` both banded 0, the sort was stable, and
GitHub's alphabetical order decided the queue — so on #3496 thirty-two portrait
JPEGs sat ahead of the two `data/*.json` files holding every reviewable byte.
At max_files=10 those JSONs (#33 and #34 of 34) could never be sent and the
verdict could never be anything but NEEDS REVIEW. A wide re-review did not
rescue it: 16m38s, zero passes completed, still on the first JPEG.

These pin the ordering AND the two byte-identity properties the change must not
break: the `max_files <= 1` killswitch, and diffs with no binary paths.
"""

import importlib

rc = importlib.import_module("services.review_coverage")


def test_bands_are_ordered_code_tests_docs_assets():
    assert rc.file_band("platform_v2/services/foo.py") == 0
    assert rc.file_band("platform_v2/tests/test_foo.py") == 1
    assert rc.file_band("docs/readme.md") == 2
    assert rc.file_band("website/assets/portraits/x.jpg") == 3


def test_binary_beats_doc_band():
    # `docs/diagram.png` matches the docs regex; the asset must still win, or a
    # diagram would be reviewed as prose.
    assert rc.file_band("docs/diagram.png") == 3
    assert rc.file_band("website/kytranempowerment.com/assets/p/1.jpeg") == 3


def test_data_json_is_code_not_asset():
    # The regression this fixes: these are the files that must reach the model.
    assert rc.file_band("website/kytranempowerment.com/data/directors.json") == 0


def test_max_files_one_killswitch_is_byte_identical():
    diff = _synthetic_diff(["a.jpg", "b.py"])
    assert rc.file_plan_detail(diff, 1) == ([diff], [])


def test_diff_with_no_binaries_is_unchanged_by_the_banding():
    paths = ["platform_v2/a.py", "platform_v2/tests/test_a.py", "docs/x.md"]
    diff = _synthetic_diff(paths)
    chunks, refused = rc.file_plan_detail(diff, 10)
    assert refused == []
    # every block still present, in band order
    assert "".join(chunks) == diff


def test_the_3496_shape_now_reaches_both_json_files():
    """32 portraits + 2 data files, max_files=10 — the exact failing case."""
    portraits = ["website/kytranempowerment.com/assets/portraits/media_%d_.jpg" % i for i in range(32)]
    data = [
        "website/kytranempowerment.com/data/directors.json",
        "website/kytranempowerment.com/data/directory-fallback.json",
    ]
    diff = _synthetic_diff(portraits + data)
    chunks, refused = rc.file_plan_detail(diff, 10)
    shown = "".join(chunks)
    for p in data:
        assert p in shown, "%s never reached the reviewer" % p
    # Assets are EXCLUDED from passes, not sorted last: the 2 JSONs take the only
    # 2 passes and all 32 portraits are reported dropped. No dispatch is spent on
    # a "Binary files differ" stub — that waste is what hung the wide re-review.
    assert len(chunks) == 2, "a pass was spent on a binary asset"
    assert len(refused) == 32
    assert all(r.endswith(".jpg") for r in refused)


def test_binary_paths_still_reported_as_dropped_not_silently_kept():
    # Honesty: skipping an asset must not hide it. A wider re-review cannot help a
    # JPEG, but the count must still be visible to the coverage note.
    diff = _synthetic_diff(["a.jpg"] * 12 + ["b.py"])
    chunks, refused = rc.file_plan_detail(diff, 10)
    # b.py bands 0 and takes the only pass; all 12 portraits are refused.
    assert "b.py" in "".join(chunks)
    assert len(chunks) == 1, "a pass was spent on a binary asset"
    assert len(refused) == 12
    assert all(r == "a.jpg" for r in refused)


def _synthetic_diff(paths):
    parts = []
    for p in paths:
        parts.append(
            "diff --git a/%s b/%s\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/%s\n"
            "@@ -0,0 +1,2 @@\n"
            "+line one for %s\n"
            "+line two\n" % (p, p, p, p)
        )
    return "".join(parts)


def test_all_binary_diff_yields_no_passes_but_reports_them():
    # Degenerate case: a PR that is ONLY images must still be reviewable rather than
    # returning [] (which a caller reads as "nothing to review"), and must not
    # dispatch anything. The caller falls back to one whole-diff pass.
    diff = _synthetic_diff(["a.jpg", "b.png"])
    chunks, refused = rc.file_plan_detail(diff, 10)
    assert chunks == []
    assert sorted(refused) == ["a.jpg", "b.png"]
