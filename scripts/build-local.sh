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
  echo "  • Utwórz katalog editor/ z pełnym kodem (patrz editor/README.md), lub" >&2
  echo "  • Ustaw NJR_APP_DIR na katalog zawierający njr.spec" >&2
  exit 1
fi

VERSION_FILE="$REPO_ROOT/VERSION"
OUT_DIR="$REPO_ROOT/releases"

if [ ! -f "$APP/njr.spec" ]; then
  echo "Brak $APP/njr.spec" >&2
  exit 1
fi

VERSION="$(tr -d ' \t\r\n' < "$VERSION_FILE" 2>/dev/null || echo "0.0.0")"
echo "Repozytorium: $REPO_ROOT"
echo "Aplikacja (PyInstaller): $APP"
echo "Wersja (VERSION): $VERSION"

cd "$APP"
python3 -m pip install -q -r requirements.txt
python3 -m pip install -q pyinstaller
python3 -m PyInstaller njr.spec --clean --noconfirm

mkdir -p "$OUT_DIR"

copied=0
for src in "$APP/dist/NJR-konwerter" "$APP/dist/NJR-konwerter.exe"; do
  [ -f "$src" ] || continue
  if [[ "$src" == *.exe ]]; then
    dest_name="NJR-konwerter-${VERSION}.exe"
  else
    dest_name="NJR-konwerter-${VERSION}"
  fi
  dest="$OUT_DIR/$dest_name"
  cp -f "$src" "$dest"
  echo "Skopiowano: $dest"
  ls -la "$dest"
  copied=$((copied + 1))
done

if [ "$copied" -eq 0 ]; then
  echo "Brak pliku w $APP/dist (oczekiwano NJR-konwerter lub NJR-konwerter.exe)" >&2
  exit 1
fi

echo "Gotowe. Następny krok: DEPLOY-SERVER.md lub GitHub Releases."
