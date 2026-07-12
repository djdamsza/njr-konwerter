#!/usr/bin/env bash
# Kopiuj artefakty NJR na udział SMB Home Assistant (Pi4: 192.168.18.170/share).
# Użycie:
#   SMB_PASS='haslo' ./scripts/deploy-to-ha-share.sh
#   lub: ./scripts/deploy-to-ha-share.sh /ścieżka/do/NJR-konwerter-1.0.2-windows-x64.exe
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RELEASES="$REPO_ROOT/releases"
MOUNT="/tmp/njr-ha-share"
SMB_HOST="${SMB_HOST:-192.168.18.170}"
SMB_USER="${SMB_USER:-homeassistant}"
SMB_SHARE="${SMB_SHARE:-share}"

VERSION="$(tr -d ' \t\r\n' < "$REPO_ROOT/VERSION" 2>/dev/null || echo "0.0.0")"

cleanup() {
  if mount | grep -q "$MOUNT"; then
    umount "$MOUNT" 2>/dev/null || diskutil unmount "$MOUNT" 2>/dev/null || true
  fi
}
trap cleanup EXIT

mkdir -p "$MOUNT"
if ! mount | grep -q "$MOUNT"; then
  if [ -z "${SMB_PASS:-}" ]; then
    echo "Ustaw SMB_PASS (hasło z HA → Dodatek Samba share) lub zamontuj ręcznie:" >&2
    echo "  Finder → Połącz z serwerem → smb://${SMB_HOST}/${SMB_SHARE}" >&2
    exit 1
  fi
  mount_smbfs "//${SMB_USER}:${SMB_PASS}@${SMB_HOST}/${SMB_SHARE}" "$MOUNT"
fi

DEST="$MOUNT"
echo "Kopiuję do ${SMB_HOST}/${SMB_SHARE} …"

copied=0
if [ $# -gt 0 ]; then
  for src in "$@"; do
    [ -f "$src" ] || continue
    cp -f "$src" "$DEST/"
    echo "  → $(basename "$src")"
    copied=$((copied + 1))
  done
else
  for src in \
    "$RELEASES/NJR-konwerter-${VERSION}-windows-x64.exe" \
    "$RELEASES/NJR-konwerter-${VERSION}.exe" \
    "$RELEASES/NJR-konwerter-${VERSION}" \
    "$RELEASES/NJR-konwerter-${VERSION}-windows-x64.zip" \
    ; do
    [ -f "$src" ] || continue
    cp -f "$src" "$DEST/"
    echo "  → $(basename "$src")"
    copied=$((copied + 1))
  done
fi

if [ "$copied" -eq 0 ]; then
  echo "Brak plików w releases/ — zbuduj najpierw (GitHub Actions lub build-local.sh)." >&2
  exit 1
fi

# Krótka instrukcja na share
cat > "$DEST/NJR-konwerter-${VERSION}-WINDOWS-README.txt" <<EOF
NJR Konwerter ${VERSION} — Windows

1. Skopiuj na PC: NJR-konwerter-${VERSION}-windows-x64.exe
2. Uruchom (SmartScreen: Więcej informacji → Uruchom mimo to)
3. Otworzy się przeglądarka: http://127.0.0.1:5050
4. Zakładka RB Beta — porządek duplikatów na dysku bez bazy Rekordbox

Źródło: njr-konwerter $(date +%Y-%m-%d)
EOF
echo "Gotowe. Na Windows: \\\\${SMB_HOST}\\${SMB_SHARE}"
