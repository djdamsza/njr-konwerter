# Windows — złóż 1.1.0

Kod bierz z `\\192.168.18.170\share\projekt`, nie z GitHuba. Użytkownik udziału: `projekt`.

`VERSION` to `1.1.0`. Exe ze strony (1.0.16 i starsze) nie ma tego wydania. Złóż nowy plik i zostaw go w `releases`. Na stronę wgrywa się ręcznie, z panelu wtyczki, dopiero gdy będą wszystkie trzy pliki.

DMG Maca są już w `releases` na udziale. Na Windowsie ich nie składaj.

## Nazwy plików

Program 1.0.16 szuka pliku `Imprezja-Playlist-Pro-`, nie `NJR-konwerter-`. Zła nazwa kończy się komunikatem „Masz najnowszą wersję”, mimo że na stronie jest 1.1.0.

| System | Nazwa |
| --- | --- |
| Windows | `Imprezja-Playlist-Pro-1.1.0-windows-x64.exe` |
| Mac Apple Silicon | `Imprezja-Playlist-Pro-1.1.0-macos-arm64.dmg` |
| Mac Intel | `Imprezja-Playlist-Pro-1.1.0-macos-intel-x64.dmg` |

Exe złóż pod tą nazwą. Nie zmieniaj go na `NJR-konwerter-…`.

## Co jest w 1.1.0

- Bez konta Nowa Jakość Rozrywki program nie otwiera narzędzi. Logowanie jest na starcie.
- Przy logowaniu jest „Utwórz konto”. Otwiera `https://nowajakoscrozrywki.pl/moje-konto/` w przeglądarce.
- AI działa tylko po zalogowaniu, przez stronę. Klucza modelu w programie nie ma.
- Eksport do Serato dopisuje brakujące utwory do listy, którą pokazuje Serato DJ. Serato ma być zamknięte przed zapisem.

Poprawki z 20 i 21 października zostają w tym samym kodzie.

## Złożenie

Cały folder `projekt`, nie sam `editor`. Visual Studio, vcpkg i `njr-engine-export.exe` są w `docs\BUILD-WINDOWS-1.0.14.md`. Binarki Engine z Maca na Windows nie ma.

W `cmd` albo PowerShell, po złożeniu narzędzia Engine:

```bat
cd C:\ścieżka\do\projekt\editor
py -3 -m pip install -r requirements-dev.txt
py -3 -m PyInstaller njr.spec --clean --noconfirm
cd ..
mkdir releases
copy /Y "editor\dist\Imprezja Playlist Pro.exe" releases\Imprezja-Playlist-Pro-1.1.0-windows-x64.exe
```

Ta nazwa jest tą, której szuka zainstalowany program. `NJR-konwerter-1.1.0-windows-x64.exe` nie podawaj.

Suma:

```powershell
Get-FileHash .\releases\Imprezja-Playlist-Pro-1.1.0-windows-x64.exe -Algorithm SHA256
```

Program otwiera własne okno. Jak Windows nie ma WebView2, doinstaluj Edge WebView2 Runtime. Plik nie jest podpisany, SmartScreen może pytać przy pierwszym uruchomieniu.

## Pliki na stronę

W panelu wtyczki ustaw wersję `1.1.0` i wgraj trzy pliki. Puste pole zostawia stary plik tego systemu, więc przy 1.1.0 pole Mac nie może zostać puste.

| Plik | SHA-256 |
| --- | --- |
| `Imprezja-Playlist-Pro-1.1.0-macos-arm64.dmg` | `0c13285b7712fa3b1d4c48ebf2bd4d1e999998e21defdd1a567245b9f9bbb04a` |
| `Imprezja-Playlist-Pro-1.1.0-macos-intel-x64.dmg` | `0235b03be4c4529d25af83f61446470b9934d41ea15e64a424033d7a99361c20` |
| `Imprezja-Playlist-Pro-1.1.0-windows-x64.exe` | po złożeniu na Windowsie |
