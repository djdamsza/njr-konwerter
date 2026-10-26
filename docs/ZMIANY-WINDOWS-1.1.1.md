# Windows — złóż 1.1.1

Kod bierz z `\\192.168.18.170\share\projekt`, nie z GitHuba. Użytkownik udziału: `projekt`.

`VERSION` to `1.1.1`. Kto ma 1.1.0, dostanie aktualizację dopiero po zapisie tej wersji w panelu wtyczki. Złóż exe i zostaw go w `releases`. Wersji w panelu nie zapisuj i pliku na stronę nie wgrywaj, dopóki nie ma też obu DMG 1.1.1. Puste pole przy zapisie kopiuje poprzedni plik pod nową nazwą.

DMG Maca powstają na Macu. Na Windowsie ich nie składaj.

## Nazwy plików

Program 1.0.16 i złożony 1.1.0 szukają pliku `Imprezja-Playlist-Pro-`. Zła nazwa kończy się komunikatem „Masz najnowszą wersję”.

| System | Nazwa |
| --- | --- |
| Windows | `Imprezja-Playlist-Pro-1.1.1-windows-x64.exe` |
| Mac Apple Silicon | `Imprezja-Playlist-Pro-1.1.1-macos-arm64.dmg` |
| Mac Intel | `Imprezja-Playlist-Pro-1.1.1-macos-intel-x64.dmg` |

## Co jest w 1.1.1

To samo co w 1.1.0 (logowanie, konto, AI przez stronę, dopisywanie do listy Serato) oraz:

- Dysk Rane jest szukany po etykiecie woluminu Patriot, na przykład `E:\Engine Library`. Bez dysku komunikat brzmi „Brak dysku Patriot. Podłącz dysk Rane.”
- Okno na Windowsie nie pokazuje `Cmd+Q`, `~/Music/_Serato_/` ani `/Volumes/Patriot`.

Eksport Engine nadal wymaga `njr-engine-export.exe`. Bez Visual Studio 2022 i vcpkg ten plik nie powstanie. Program wstanie. Synchronizacja Engine napisze, że brakuje narzędzia.

## Złożenie

```bat
cd C:\ścieżka\do\projekt\editor
py -3 -m pip install -r requirements-dev.txt
py -3 -m PyInstaller njr.spec --clean --noconfirm
cd ..
mkdir releases
copy /Y "editor\dist\Imprezja Playlist Pro.exe" releases\Imprezja-Playlist-Pro-1.1.1-windows-x64.exe
```

Suma:

```powershell
Get-FileHash .\releases\Imprezja-Playlist-Pro-1.1.1-windows-x64.exe -Algorithm SHA256
```

DMG 1.1.1 są w `releases` na udziale. Na stronę wchodzą razem z exe, w jednym zapisie panelu, z wersją `1.1.1`.

| Plik | SHA-256 |
| --- | --- |
| `Imprezja-Playlist-Pro-1.1.1-macos-arm64.dmg` | `af851fb4801dc8dbcc6c6e0c50ff2363ee5af1a6b828c240f7b618c84d11c47b` |
| `Imprezja-Playlist-Pro-1.1.1-macos-intel-x64.dmg` | `c50ae842d4cd82cf371f1a9cbd2af3b9338481f25f81f0d3db1a994ee832b775` |
| `Imprezja-Playlist-Pro-1.1.1-windows-x64.exe` | po złożeniu na Windowsie |
