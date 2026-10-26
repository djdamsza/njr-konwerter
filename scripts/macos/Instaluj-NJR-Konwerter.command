#!/bin/bash
# Kopiuj Imprezja Playlist Pro.app do /Applications i usuń atrybut quarantine (Gatekeeper).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$DIR/Imprezja Playlist Pro.app"
APP_DEST="/Applications/Imprezja Playlist Pro.app"

if [ ! -d "$APP_SRC" ]; then
  osascript -e 'display alert "Imprezja Playlist Pro" message "Nie znaleziono Imprezja Playlist Pro.app w tym DMG." as critical' || true
  exit 1
fi

if [ -d "$APP_DEST" ]; then
  rm -rf "$APP_DEST"
fi
cp -R "$APP_SRC" "$APP_DEST"
xattr -cr "$APP_DEST" 2>/dev/null || true
chmod -R u+rwX "$APP_DEST"

osascript -e 'display notification "Skopiowano do Aplikacji. Uruchom Imprezja Playlist Pro z folderu Aplikacje." with title "Imprezja Playlist Pro"' || true
open -R "$APP_DEST"
