# Windows — złóż nowy program, 21 października 2026

Kod bierz z `\\192.168.18.170\share\projekt`, nie z GitHuba. GitHub nie ma tych poprawek. Użytkownik udziału: `projekt`.

`VERSION` to `1.0.16`. Exe 1.0.15 ze strony nie ma poprawek z 21 października. Złóż nowy plik i wgraj go w panelu wtyczki jako Windows. DMG 1.0.16 leżą w `releases` na udziale. Jeśli Mac jest już wgrany na stronie, pola Mac zostaw puste.

## Co jest nowego w tym kodzie

- Serato czyta ścieżki `Users\…` od korzenia dysku. Wcześniej program doklejał je do folderu `Music` i prawie każdy utwór wyglądał jak brakujący (`Music\Users\…`).
- Szukanie brakujących plików przechodzi listy raz. Wcześniej wisiało na „Chwileczkę”.
- Duplikaty w cache VirtualDJ: metoda Tidal ID łączy cache ze streamingiem, gdy czas trwania zgadza się w granicach 2 sekund. Autor i tytuł też widzi pliki `.vdjcache`.
- W kolumnie odsłuchu cache bez numeru Tidal ma pauzę, nie krzyżyk. To nie jest uszkodzony plik.

Poprawki Engine z 20 października są w tym samym kodzie. Zostają.

## Złożenie

Cały folder `projekt`, nie sam `editor`. Kroki, Visual Studio i `njr-engine-export.exe` są w `docs\BUILD-WINDOWS-1.0.14.md`. Binarki Engine z Maca na Windows nie ma.

W `cmd` albo PowerShell, po złożeniu narzędzia Engine:

```bat
cd C:\ścieżka\do\projekt\editor
py -3 -m pip install -r requirements-dev.txt
py -3 -m PyInstaller njr.spec --clean --noconfirm
cd ..
mkdir releases
copy /Y "editor\dist\Imprezja Playlist Pro.exe" releases\NJR-konwerter-1.0.16-windows-x64.exe
```

Ta nazwa jest tą, którą przyjmuje wtyczka na stronie. Inna nazwa nie wejdzie do aktualizacji.

Suma, gdy będzie potrzebna przy wgraniu:

```powershell
Get-FileHash .\releases\NJR-konwerter-1.0.16-windows-x64.exe -Algorithm SHA256
```

Program otwiera własne okno. Jak Windows nie ma WebView2, doinstaluj Edge WebView2 Runtime. Plik nie jest podpisany, SmartScreen może pytać przy pierwszym uruchomieniu.

## DMG na stronie

Te dwa pliki są już złożone. Nie składaj ich na Windowsie.

| Plik | SHA-256 |
| --- | --- |
| `NJR-konwerter-1.0.16-macos-arm64.dmg` | `27582a7741548e13be6ccf5c109421c91bebc5931f501e8ab4b234100401edc9` |
| `NJR-konwerter-1.0.16-macos-intel-x64.dmg` | `e8ef1637d98f2764a06e6b5c4e155193093a80e6c1294faad8a1221dbb693cbe` |

W panelu wtyczki ustaw wersję `1.0.16`. Jeśli DMG Maca już są wgrane, wgraj tylko exe i zostaw oba pola Mac puste. Puste pole Mac przy braku pliku 1.0.16 skopiuje stary DMG.

## Po złożeniu

Otwórz bibliotekę Serato w nowym programie. Brakujące pliki mają być prawdziwymi brakami, nie całą kolekcją. Nie zapisuj starej listy „nowych ścieżek”, która powstała w poprzednim buildzie.
