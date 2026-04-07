#!/bin/bash
# Migrate large Ollama model blobs from /mnt/llm_drive to /mnt/data2
# Keeps symlinks so Ollama sees the same paths
# Run with: sudo bash scripts/migrate-llm-blobs.sh
set -euo pipefail

SRC="/mnt/llm_drive/ollama/models/blobs"
DST="/mnt/data2/ollama/blobs"

echo "=== LLM Blob Migration ==="
echo "Source: $SRC"
echo "Target: $DST"
echo ""

# Create target with correct ownership
mkdir -p "$DST"
chown ollama:ollama /mnt/data2/ollama "$DST"

# Blobs to move (>5GB each, sorted largest first)
BLOBS=(
  "sha256-30e51a7cb1cf1333b9e298b90b4c7790fe2572d8736b002482a0ac96328a2ffb"  # 49GB qwen3-coder-cpu
  "sha256-fd7b6731c33c57f61767612f56517460ec2d1e2e5a3f0163e0eb3d8d8cb5df20"  # 8.5GB
  "sha256-5ff0abeeac1d2dbdd5455c0b49ba3b29a9ce3c1fb181b2eef2e948689d55d046"  # 8.3GB
  "sha256-e8ad13eff07a78d89926e9e8b882317d082ef5bf9768ad7b50fcdbbcd63748de"  # 7.6GB
  "sha256-a99b7f834d754b88f122d865f32758ba9f0994a83f8363df2c1e71c17605a025"  # 5.6GB
  "sha256-ff1d1fc78170d787ee1201778e2dd65ea211654ca5fb7d69b5a2e7b123a50373"  # 5.1GB
)

for blob in "${BLOBS[@]}"; do
  if [ -L "$SRC/$blob" ]; then
    echo "SKIP (already symlinked): $blob"
    continue
  fi
  if [ ! -f "$SRC/$blob" ]; then
    echo "SKIP (not found): $blob"
    continue
  fi

  SIZE=$(du -sh "$SRC/$blob" | cut -f1)
  echo "Moving $blob ($SIZE)..."
  mv "$SRC/$blob" "$DST/$blob"
  ln -s "$DST/$blob" "$SRC/$blob"
  chown -h ollama:ollama "$SRC/$blob"
  echo "  -> Moved and symlinked"
done

echo ""
echo "=== Result ==="
df -h /mnt/llm_drive /mnt/data2
echo ""
echo "Symlinks created:"
ls -la "$SRC" | grep '^l' | wc -l
echo ""
echo "Done! Ollama should work without restart."
