#!/usr/bin/env python3
"""Generate web-sized thumbnails for agent portraits.

Reads source PNGs from platform_v2/static/media/portraits/ and emits
400x400 JPEG thumbs (~50KB each) to website/kytranempowerment.com/assets/portraits/.

The public-roster endpoint serves avatar_thumb_url pointing at these
thumbs (relative /assets/portraits/<stem>.jpg) so public pages fetch
them same-origin from Hostinger CDN instead of cross-origin from
platform.kytranempowerment.com.

Run manually after adding/approving new portraits, or wire into
portrait_service.approve_canonical as a follow-up.

Usage:
    python3 scripts/generate_portrait_thumbnails.py
    python3 scripts/generate_portrait_thumbnails.py --force   # regenerate all
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "error: Pillow not installed. Install with `pip install Pillow`\n"
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
# Default paths assume the script runs from the repo root (or is invoked via
# absolute path). Inside the archie_platform container, the platform code
# lives at /app while the website repo is mounted at /mnt/archie_brain/...,
# so override via CLI args when needed.
DEFAULT_SRC = REPO_ROOT / "platform_v2" / "static" / "media" / "portraits"
DEFAULT_DST = REPO_ROOT / "website" / "kytranempowerment.com" / "assets" / "portraits"

THUMB_SIZE = (400, 400)
JPEG_QUALITY = 82


def generate_thumb(src: Path, dst: Path) -> tuple[int, int]:
    """Generate a single thumb. Returns (src_bytes, dst_bytes)."""
    src_bytes = src.stat().st_size
    with Image.open(src) as im:
        # Flatten alpha to white so JPEG doesn't get artifacts
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail(THUMB_SIZE, Image.LANCZOS)
        im.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    dst_bytes = dst.stat().st_size
    return src_bytes, dst_bytes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--src",
        type=Path,
        default=DEFAULT_SRC,
        help=f"Source PNG directory (default: {DEFAULT_SRC})",
    )
    ap.add_argument(
        "--dst",
        type=Path,
        default=DEFAULT_DST,
        help=f"Destination JPEG directory (default: {DEFAULT_DST})",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if destination is newer than source.",
    )
    args = ap.parse_args()

    src_dir: Path = args.src
    dst_dir: Path = args.dst

    if not src_dir.is_dir():
        sys.stderr.write(f"error: source dir not found: {src_dir}\n")
        return 1
    dst_dir.mkdir(parents=True, exist_ok=True)

    sources = sorted(src_dir.glob("*.png"))
    if not sources:
        sys.stderr.write(f"warning: no PNGs found in {SRC_DIR}\n")
        return 0

    total_src = 0
    total_dst = 0
    generated = 0
    skipped = 0
    failed: list[tuple[str, str]] = []

    for src in sources:
        dst = dst_dir / f"{src.stem}.jpg"

        # Skip if destination is newer and --force not set
        if not args.force and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            total_dst += dst.stat().st_size
            total_src += src.stat().st_size
            continue

        try:
            s_b, d_b = generate_thumb(src, dst)
            total_src += s_b
            total_dst += d_b
            generated += 1
        except Exception as e:
            failed.append((src.name, str(e)))

    print(f"sources scanned: {len(sources)}")
    print(f"generated:       {generated}")
    print(f"skipped (fresh): {skipped}")
    if failed:
        print(f"failed:          {len(failed)}")
        for name, err in failed[:5]:
            print(f"  - {name}: {err}")

    if total_src and total_dst:
        ratio = total_src / total_dst
        print(
            f"bytes: source={total_src/1024/1024:.1f}MB "
            f"thumbs={total_dst/1024/1024:.1f}MB "
            f"({ratio:.1f}x smaller)"
        )
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
