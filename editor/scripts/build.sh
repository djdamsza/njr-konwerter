#!/bin/bash
# Budowanie Imprezja Playlist Pro do testów
# Wynik: dist/Imprezja Playlist Pro.app (macOS) lub dist/Imprezja Playlist Pro.exe (Windows)

set -e
cd "$(dirname "$0")/.."

echo "=== Imprezja Playlist Pro – build do testów ==="

# Wirtualne środowisko (opcjonalnie)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Zależności
python3 -m pip install -q -r requirements.txt
python3 -m pip install -q pyinstaller

# Build
echo "Budowanie z PyInstaller..."
python3 -m PyInstaller njr.spec

echo ""
echo "Gotowe: dist/Imprezja Playlist Pro.app albo dist/Imprezja Playlist Pro.exe"
echo ""
