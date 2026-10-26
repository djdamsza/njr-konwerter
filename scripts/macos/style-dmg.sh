#!/usr/bin/env bash
# Okno DMG jak w Imprezja Quiz: program po lewej, Aplikacje po prawej, bez paska narzędzi.
set -euo pipefail

APP_SRC="${1:?brak .app}"
DMG_OUT="${2:?brak ścieżki dmg}"
VOLNAME="Imprezja Playlist Pro"
HERE="$(cd "$(dirname "$0")" && pwd)"
BG="$HERE/dmg-background.png"

if [ ! -d "$APP_SRC" ]; then
  echo "Nie ma programu: $APP_SRC" >&2
  exit 1
fi
if [ ! -f "$BG" ]; then
  python3 "$HERE/make_dmg_background.py"
fi

WORK="$(mktemp -d /tmp/njr-dmg.XXXXXX)"
RW="$WORK/rw.dmg"
STAGE="$WORK/stage"
mkdir -p "$STAGE/.background"
cp -R "$APP_SRC" "$STAGE/Imprezja Playlist Pro.app"
cp "$BG" "$STAGE/.background/background.png"
ln -s /Applications "$STAGE/Applications"

if [ -d "/Volumes/$VOLNAME" ]; then
  hdiutil detach "/Volumes/$VOLNAME" -force >/dev/null 2>&1 || diskutil unmount force "/Volumes/$VOLNAME" >/dev/null 2>&1 || true
fi
hdiutil create -size 400m -fs HFS+ -volname "$VOLNAME" -ov "$RW" >/dev/null
MOUNT="/Volumes/$VOLNAME"
hdiutil attach "$RW" -mountpoint "$MOUNT" >/dev/null
cp -R "$STAGE/." "$MOUNT/"
chflags hidden "$MOUNT/.background" || true
sync

osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "$VOLNAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 740, 500}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 80
    set text size of viewOptions to 12
    set background picture of viewOptions to POSIX file "$MOUNT/.background/background.png"
    set position of item "Imprezja Playlist Pro.app" of container window to {130, 200}
    set position of item "Applications" of container window to {410, 200}
    close
    open
    update without registering applications
    delay 2
    close
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MOUNT" >/dev/null
rm -f "$DMG_OUT"
hdiutil convert "$RW" -format UDZO -ov -o "$DMG_OUT" >/dev/null
rm -rf "$WORK"
echo "DMG: $DMG_OUT"
