#!/usr/bin/env bash
# Wgrywa lokalne buildy 1.0.9 na GitHub Release (tag 1.0).
# Wymaga: GITHUB_TOKEN (classic) z scope repo — export GITHUB_TOKEN=ghp_...
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-djdamsza/njr-konwerter}"
TAG="${1:-1.0}"
RELEASES="${2:-$(cd "$(dirname "$0")/.." && pwd)/releases}"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Ustaw GITHUB_TOKEN (scope: repo)." >&2
  exit 1
fi

upload() {
  local file="$1"
  local name
  name="$(basename "$file")"
  echo "Upload: $name"
  curl -sfSL -X POST \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$file" \
    "https://uploads.github.com/repos/${REPO}/releases/tags/${TAG}/${name}"
  echo
}

for f in \
  "$RELEASES/NJR-konwerter-1.0.9-windows-x64.exe" \
  "$RELEASES/NJR-konwerter-1.0.9-macos-arm64.dmg" \
  "$RELEASES/NJR-konwerter-1.0.9-macos-intel-x64.dmg"; do
  [ -f "$f" ] || { echo "Brak: $f" >&2; exit 1; }
  upload "$f"
done

echo "Gotowe — sprawdź: https://github.com/${REPO}/releases/tag/${TAG}"
