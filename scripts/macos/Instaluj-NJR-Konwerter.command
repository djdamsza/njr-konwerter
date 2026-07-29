#!/bin/bash
# Kopiuj NJR Konwerter.app do /Applications i usuń atrybut quarantine (Gatekeeper).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$DIR/NJR Konwerter.app"
APP_DEST="/Applications/NJR Konwerter.app"

if [ ! -d "$APP_SRC" ]; then
  osascript -e 'display alert "NJR Konwerter" message "Nie znaleziono NJR Konwerter.app w tym DMG." as critical' || true
  exit 1
fi

if [ -d "$APP_DEST" ]; then
  rm -rf "$APP_DEST"
fi
cp -R "$APP_SRC" "$APP_DEST"
xattr -cr "$APP_DEST" 2>/dev/null || true
chmod -R u+rwX "$APP_DEST"

osascript -e 'display notification "Skopiowano do Aplikacji. Uruchom NJR Konwerter z folderu Aplikacje." with title "NJR Konwerter"' || true
open -R "$APP_DEST"
