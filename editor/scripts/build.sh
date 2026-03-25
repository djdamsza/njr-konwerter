#!/bin/bash
# Budowanie NJR konwerter do testów
# Wynik: dist/NJR-konwerter (macOS) lub dist/NJR-konwerter.exe (Windows)

set -e
cd "$(dirname "$0")/.."

echo "=== NJR konwerter – build do testów ==="

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
echo "Gotowe: dist/NJR-konwerter"
echo "Uruchom: ./dist/NJR-konwerter"
echo ""
