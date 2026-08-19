#!/usr/bin/env python3
"""Build the publishable extension zip. Payload is DERIVED FROM manifest.json.

Task #5752. The packaged zip drifted 9 days behind source because it was built by
hand ("the same files zipped", per the old README) with no recipe and no check.
The stale artifact was missing the #4671 fix entirely, so an upload would have
shipped an extension that badges nothing at all on X/Twitter — the site the
extension mainly exists for.

Two properties, both deliberate:

* **The file list is read out of `manifest.json`, never hardcoded.** A hardcoded
  list is how an asset gets added to the manifest and left out of the package;
  Chrome then fails to load the extension for a file the developer can plainly
  see on disk. Adding a new content script or icon needs no change here.

* **The archive is byte-reproducible** — fixed timestamps, fixed order, stored
  permissions. Two builds of identical sources produce an identical file, so
  "is the artifact current?" is answerable by comparison rather than by trusting
  an mtime. mtimes are what made the drift invisible for six weeks.

`tests/`, `README.md`, `.gitignore` and any prior `.zip` are excluded by
construction: they are not reachable from the manifest.

Usage:  python3 build.py [--check]
        --check  exit 1 if the on-disk zip differs from a fresh build; writes nothing.
"""
import hashlib
import json
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
OUT = HERE / "wtf-bias-extension.zip"

# Fixed epoch for reproducibility. Zip cannot store pre-1980 dates.
_FIXED_DT = (1980, 1, 1, 0, 0, 0)


def payload_files(manifest: dict) -> list[str]:
    """Every file the manifest references, plus the manifest itself.

    Ordered and de-duplicated so the archive is stable across runs.
    """
    files: list[str] = ["manifest.json"]

    for size_map in (manifest.get("icons") or {},
                     (manifest.get("action") or {}).get("default_icon") or {}):
        files.extend(size_map.values())

    for cs in manifest.get("content_scripts") or []:
        files.extend(cs.get("js") or [])
        files.extend(cs.get("css") or [])

    sw = (manifest.get("background") or {}).get("service_worker")
    if sw:
        files.append(sw)

    popup = (manifest.get("action") or {}).get("default_popup")
    if popup:
        files.append(popup)

    for res in manifest.get("web_accessible_resources") or []:
        files.extend(res.get("resources") or [])

    seen, ordered = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return sorted(ordered)


def build(dest: pathlib.Path) -> list[str]:
    manifest = json.loads(MANIFEST.read_text())
    files = payload_files(manifest)

    missing = [f for f in files if not (HERE / f).is_file()]
    if missing:
        # Fail loudly. A manifest entry with no file on disk makes Chrome refuse
        # the whole extension, and packaging it anyway just moves the discovery
        # to the store review.
        raise SystemExit(f"manifest references files that do not exist: {missing}")

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in files:
            info = zipfile.ZipInfo(name, date_time=_FIXED_DT)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (HERE / name).read_bytes())
    return files


def main() -> int:
    check = "--check" in sys.argv
    tmp = OUT.with_suffix(".zip.tmp")
    files = build(tmp)

    if check:
        fresh = hashlib.sha256(tmp.read_bytes()).hexdigest()
        tmp.unlink()
        if not OUT.exists():
            print(f"STALE: {OUT.name} does not exist — run: python3 build.py")
            return 1
        on_disk = hashlib.sha256(OUT.read_bytes()).hexdigest()
        if on_disk != fresh:
            print(f"STALE: {OUT.name} does not match its sources.")
            print(f"  on disk {on_disk[:16]}  != fresh {fresh[:16]}")
            print("  run: python3 build.py")
            return 1
        print(f"CURRENT: {OUT.name} matches its sources ({len(files)} files).")
        return 0

    tmp.replace(OUT)
    print(f"built {OUT.name} — {len(files)} files, "
          f"sha256 {hashlib.sha256(OUT.read_bytes()).hexdigest()[:16]}")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
