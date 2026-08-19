"""Guards for the packaged browser extension (task #5752).

`extension/wtf-bias-extension.zip` sat 9 days behind its sources for six weeks.
It was built by hand — the old README said only "the same files zipped" — so
there was no recipe to re-run and nothing that could notice. The stale artifact
predated #4671, the fix that reads an outlet domain out of a link's display text
because X/Twitter rewrites every external href to `t.co/...`. Uploading it would
have shipped an extension that badges **nothing at all on X**, which is the site
the extension mostly exists for. A store review would not have caught that: the
package loads fine, it just silently does nothing.

`extension/build.py` replaces the manual step. Two properties are asserted here:

  * the payload is DERIVED FROM manifest.json, so an asset added to the manifest
    cannot be left out of the package (Chrome refuses the whole extension for one
    missing file — the same failure mode as a service worker's `cache.addAll()`);
  * the build is byte-reproducible, which is what makes "is this artifact
    current?" a comparison instead of a guess about mtimes.

The zip is gitignored (`*.zip`), so it is a local build artifact and may legitimately
be absent. Absent is reported, never asserted against — an artifact that does not
exist cannot be published stale. Present-and-stale is the dangerous state, and that
is the one that fails. The manifest-coverage tests run unconditionally either way,
so this module can never degrade into a silent all-skip.
"""
import hashlib
import importlib.util
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
BUILD = EXT / "build.py"
ZIP = EXT / "wtf-bias-extension.zip"

spec = importlib.util.spec_from_file_location("_extbuild", BUILD)
build_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_mod)          # stdlib-only: this can never skip

MANIFEST = json.loads((EXT / "manifest.json").read_text())


# ── payload derivation (always runs) ─────────────────────────────────────────

def test_every_manifest_referenced_file_is_in_the_payload():
    """The whole point of deriving instead of hardcoding. Each of these is a real
    manifest slot; missing any one makes Chrome reject the extension."""
    payload = set(build_mod.payload_files(MANIFEST))
    expected = {"manifest.json"}
    expected |= set((MANIFEST.get("icons") or {}).values())
    expected |= set(((MANIFEST.get("action") or {}).get("default_icon") or {}).values())
    for cs in MANIFEST.get("content_scripts") or []:
        expected |= set(cs.get("js") or []) | set(cs.get("css") or [])
    expected.add(MANIFEST["background"]["service_worker"])
    expected.add(MANIFEST["action"]["default_popup"])
    assert expected <= payload, f"manifest files missing from the package: {expected - payload}"


def test_payload_picks_up_a_newly_added_content_script():
    """Negative half — proves derivation, not coincidence. A hardcoded list would
    pass the test above and still silently drop this."""
    fake = json.loads(json.dumps(MANIFEST))
    fake["content_scripts"][0]["js"].append("brand-new-script.js")
    assert "brand-new-script.js" in build_mod.payload_files(fake)


def test_dev_only_files_are_never_packaged():
    """`tests/`, the README and the previous zip are unreachable from the manifest,
    so exclusion is structural rather than a blocklist someone must maintain."""
    payload = build_mod.payload_files(MANIFEST)
    for junk in ("README.md", ".gitignore", "wtf-bias-extension.zip"):
        assert junk not in payload
    assert not any(p.startswith("tests/") for p in payload)


def test_every_payload_file_exists_on_disk():
    missing = [f for f in build_mod.payload_files(MANIFEST) if not (EXT / f).is_file()]
    assert not missing, f"manifest references files that do not exist: {missing}"


# ── artifact freshness (runs when the artifact is present) ───────────────────

def _fresh_bytes(tmp_path) -> bytes:
    out = tmp_path / "fresh.zip"
    build_mod.build(out)
    return out.read_bytes()


def test_build_is_byte_reproducible(tmp_path):
    """Identical sources must give an identical file, or freshness is unknowable."""
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    build_mod.build(a)
    build_mod.build(b)
    assert hashlib.sha256(a.read_bytes()).hexdigest() == \
           hashlib.sha256(b.read_bytes()).hexdigest()


def test_on_disk_zip_is_not_stale(tmp_path):
    """THE #5752 regression. Fails loudly if the committed-by-hand artifact drifts
    from source again. An absent zip is reported, not failed — nothing to publish."""
    if not ZIP.exists():
        print(f"\n[info] {ZIP.name} absent — nothing to validate (build with: python3 build.py)")
        return
    on_disk = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    fresh = hashlib.sha256(_fresh_bytes(tmp_path)).hexdigest()
    assert on_disk == fresh, (
        f"{ZIP.name} does not match its sources — it is STALE. "
        "Publishing it would ship code that is not in the tree. Run: python3 extension/build.py"
    )


def test_packaged_files_byte_match_the_working_tree(tmp_path):
    """Belt and braces: hash equality above could in principle hold with a mangled
    payload, so compare the extracted members directly."""
    if not ZIP.exists():
        print(f"\n[info] {ZIP.name} absent — nothing to validate")
        return
    with zipfile.ZipFile(ZIP) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        assert names, "package is empty"
        for name in names:
            assert z.read(name) == (EXT / name).read_bytes(), f"{name} in the zip differs from source"


def test_the_x_twitter_fix_is_actually_in_the_package(tmp_path):
    """Names the specific bug the stale artifact was missing (#4671). A generic
    freshness check would pass on a package that happens to be current for the
    wrong reason; this pins the payload that mattered."""
    if not ZIP.exists():
        print(f"\n[info] {ZIP.name} absent — nothing to validate")
        return
    with zipfile.ZipFile(ZIP) as z:
        logic = z.read("bias-logic.js").decode()
        content = z.read("content.js").decode()
    assert "SHORTENER_DOMAINS" in logic and "extractDomainFromText" in logic
    assert "SHORTENER_DOMAINS" in content, "content.js must consult the shortener fallback"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
