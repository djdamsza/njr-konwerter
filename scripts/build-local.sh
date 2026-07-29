#!/usr/bin/env bash
# Build NJR-konwerter (PyInstaller) i kopiuj artefakt do releases/
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

if [ -d "$APP/dist/NJR Konwerter.app" ]; then
  APP_BUNDLE="$OUT_DIR/NJR Konwerter-${VERSION}.app"
  rm -rf "$APP_BUNDLE"
  cp -R "$APP/dist/NJR Konwerter.app" "$APP_BUNDLE"
  echo "Skopiowano: $APP_BUNDLE"
  copied=1

  STAGING="_dmg_staging_$$"
  rm -rf "$STAGING"
  mkdir -p "$STAGING"
  cp -R "$APP_BUNDLE" "$STAGING/NJR Konwerter.app"
  cp "$REPO_ROOT/scripts/macos/Instaluj-NJR-Konwerter.command" "$STAGING/Instaluj NJR Konwerter.command"
  chmod +x "$STAGING/Instaluj NJR Konwerter.command"
  ln -sf /Applications "$STAGING/Applications"
  DMG="$OUT_DIR/NJR-konwerter-${VERSION}-macos-arm64.dmg"
  hdiutil create -volname "NJR Konwerter" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
  rm -rf "$STAGING"
  echo "DMG: $DMG"
fi

for src in "$APP/dist/NJR-konwerter.exe"; do
  [ -f "$src" ] || continue
  dest="$OUT_DIR/NJR-konwerter-${VERSION}.exe"
  cp -f "$src" "$dest"
  echo "Skopiowano: $dest"
  copied=$((copied + 1))
done

if [ "$copied" -eq 0 ]; then
  echo "Brak artefaktów w $APP/dist" >&2
  exit 1
fi

echo "Gotowe."
