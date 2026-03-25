#!/usr/bin/env bash
# Przykład: skopiuj zawartość releases/ na serwer. Skopiuj ten plik do deploy-to-server.sh,
# uzupełnij zmienne i NIE commituj sekretów (albo użyj ssh-config / zmiennych środowiska).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NJROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_RELEASES="$NJROOT/releases"

# --- uzupełnij ---
REMOTE_USER="twoj_user"
REMOTE_HOST="twoj-serwer.pl"
REMOTE_DIR="/var/www/twoja-domena/downloads/njr"
# --- koniec ---

if [ ! -d "$LOCAL_RELEASES" ]; then
  echo "Brak katalogu: $LOCAL_RELEASES" >&2
  exit 1
fi

echo "rsync: $LOCAL_RELEASES/ -> ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"
rsync -avz --progress "$LOCAL_RELEASES/" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo "Gotowe. Sprawdź nginx i linki HTTPS (patrz DEPLOY-SERVER.md)."
