#!/usr/bin/env bash
# Build Imprezja Playlist Pro (PyInstaller) i kopiuj artefakt do releases/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -n "${NJR_APP_DIR:-}" ]; then
  APP="$(cd "$NJR_APP_DIR" && pwd)"
elif [ -d "$REPO_ROOT/editor" ] && [ -f "$REPO_ROOT/editor/njr.spec" ]; then
  APP="$REPO_ROOT/editor"
else
  echo "Brak źródeł konwertera." >&2
  exit 1
fi

VERSION_FILE="$REPO_ROOT/VERSION"
OUT_DIR="$REPO_ROOT/releases"

VERSION="$(tr -d ' \t\r\n' < "$VERSION_FILE" 2>/dev/null || echo "0.0.0")"
echo "Repozytorium: $REPO_ROOT"
echo "Wersja: $VERSION"

cd "$APP"
python3 -m pip install -q -r requirements-dev.txt
python3 -m PyInstaller njr.spec --clean --noconfirm

mkdir -p "$OUT_DIR"
copied=0

if [ -d "$APP/dist/Imprezja Playlist Pro.app" ]; then
  APP_BUNDLE="$OUT_DIR/Imprezja Playlist Pro-${VERSION}.app"
  rm -rf "$APP_BUNDLE"
  cp -R "$APP/dist/Imprezja Playlist Pro.app" "$APP_BUNDLE"
  echo "Skopiowano: $APP_BUNDLE"
  copied=1

  if [ -n "${NJR_DMG_SUFFIX:-}" ]; then
    DMG_SUFFIX="$NJR_DMG_SUFFIX"
  else
    case "$(uname -m)" in
      arm64|aarch64) DMG_SUFFIX="macos-arm64" ;;
      x86_64) DMG_SUFFIX="macos-intel-x64" ;;
      *) DMG_SUFFIX="macos-$(uname -m)" ;;
    esac
  fi
  DMG="$OUT_DIR/Imprezja-Playlist-Pro-${VERSION}-${DMG_SUFFIX}.dmg"
  bash "$REPO_ROOT/scripts/macos/style-dmg.sh" "$APP_BUNDLE" "$DMG"
fi

for src in "$APP/dist/Imprezja Playlist Pro.exe"; do
  [ -f "$src" ] || continue
  dest="$OUT_DIR/Imprezja-Playlist-Pro-${VERSION}-windows-x64.exe"
  cp -f "$src" "$dest"
  echo "Skopiowano: $dest"
  copied=$((copied + 1))
done

if [ "$copied" -eq 0 ]; then
  echo "Brak artefaktów w $APP/dist" >&2
  exit 1
fi

echo "Gotowe."
