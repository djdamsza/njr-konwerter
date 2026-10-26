# Budowanie NJR Konwertera 1.0

Build odbywa się w katalogu **`editor/`** za pomocą **PyInstaller** i pliku `njr.spec`. Wynik to **`Imprezja Playlist Pro.app`** (macOS) albo **`Imprezja Playlist Pro.exe`** (Windows). Plik do strony nazywa się `Imprezja-Playlist-Pro-1.0.14-windows-x64.exe`, `Imprezja-Playlist-Pro-1.0.14-macos-arm64.dmg` albo `Imprezja-Playlist-Pro-1.0.14-macos-intel-x64.dmg`.

## Wymagania

- **Python 3** (na macOS zwykle `python3`)
- `editor/requirements.txt`
- **PyInstaller** (`pip install pyinstaller`)

Na Windows uruchamiaj polecenia w **cmd** lub PowerShell z katalogu `editor/`.

## Kroki (ręcznie)

```bash
cd /ścieżka/do/njr-konwerter/editor
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller
python3 -m PyInstaller njr.spec --clean --noconfirm
```

Artefakt: `editor/dist/Imprezja Playlist Pro.app` albo `editor/dist/Imprezja Playlist Pro.exe`.

Skrypt `scripts/build-local.sh` kopiuje go do `releases/` z nazwą zawierającą wersję z pliku `VERSION`.

## Skrypt z korzenia repozytorium

```bash
./scripts/build-local.sh
```

Jeśli źródła nie są w `editor/`, wskaż katalog zawierający `njr.spec`:

```bash
export NJR_APP_DIR="/ścieżka/do/katalogu-z-njr.spec"
./scripts/build-local.sh
```

## Uwagi

- W `njr.spec` zwykle **UPX jest wyłączony** — mniej fałszywych alarmów AV na Windows.
- **Konsola** w specu: przy błędzie startu widzisz log w terminalu.
- Podpisywanie kodu i notaryzacja — według własnej polityki release.
