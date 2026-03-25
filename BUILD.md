# Budowanie NJR Konwertera 1.0

Build odbywa się w katalogu **`editor/`** (w korzeniu repozytorium NJR) za pomocą **PyInstaller** i pliku `njr.spec`. Wynik to jeden plik wykonywalny (**onefile**): **`NJR-konwerter`** (macOS/Linux) lub **`NJR-konwerter.exe`** (Windows).

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

Artefakt: `editor/dist/NJR-konwerter` lub `editor/dist/NJR-konwerter.exe`.

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
