@echo off
REM Budowanie NJR konwerter do testów (Windows)
REM Wynik: dist\NJR-konwerter.exe

cd /d "%~dp0\.."

echo === NJR konwerter - build do testow ===

REM Wirtualne środowisko (opcjonalnie)
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

python -m pip install -q -r requirements.txt
python -m pip install -q pyinstaller

echo Budowanie z PyInstaller...
python -m PyInstaller njr.spec

echo.
echo Gotowe: dist\NJR-konwerter.exe
echo Uruchom: dist\NJR-konwerter.exe
echo.
