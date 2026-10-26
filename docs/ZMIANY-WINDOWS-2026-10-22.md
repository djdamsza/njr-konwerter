# Windows — złóż program 1.1.3, 22 października 2026

To jest stara instrukcja z 22 października. Aktualne złożenie to 1.1.15 i plik `docs/ZLOZ-NA-WINDOWS.txt`.

Kod bierz z `\\192.168.18.170\share\projekt`, nie z GitHuba. GitHub nie ma tych poprawek. Użytkownik udziału: `projekt`.

`VERSION` to `1.1.3`. Na stronie zostaje `1.1.2`, dopóki nie ma trzech plików: Windows, Mac Apple Silicon i Mac Intel. Samo wgranie DMG i podbicie numeru wyłącza aktualizację, bo wtyczka oddaje ją dopiero przy komplecie.

Nazwa pliku Windows, dokładnie:

`Imprezja-Playlist-Pro-1.1.3-windows-x64.exe`

Inna nazwa nie wejdzie do aktualizacji. Nie zmieniaj jej na `NJR-konwerter-…`.

## Co jest nowego

- Serato: dopisanie utworu z dysku i z Tidal tworzy go w bibliotece i dokłada na listę. Eksport nie przepisuje całej bazy ani plików cue, gdy biblioteka jest z Serato.
- VirtualDJ: utwór z Tidal zapisuje się jako `netsearch://td…`. Lista wraca do swojego pliku, na przykład `MyLists\techniawka.vdjfolder`. Nie powstaje druga kopia w `VDJ.subfolders`.
- Pimp my list: drzewo playlist, pobranie CSV i TXT. Lista filtrów nie przyjmuje wklejonego utworu, bo bierze go z tagów. Po dodaniu znika zaznaczenie, także przy wersjach pod utworem.
- Engine DJ: plik z dysku wchodzi na listę. Utwór z Tidal nie. Przy zaznaczeniu Tidal program mówi o tym wprost. Na Windowsie wybór dysku pokazuje literę i etykietę, na przykład `Patriot (E:)`. Brakującą literę widać jako dysk niepodpięty. Ścieżkę folderu wkleja się jako `D:\Muzyka`, bo okno wyboru folderu bywa zablokowane.
- Rekordbox: plik z dysku i utwór z Tidal wchodzą do XML jako `file://localhosttidal:tracks:ID`. Wgranie jest przez XML w Pobranych, nie przez podmianę `master.db`.

## Złożenie

Cały folder `projekt`, nie sam `editor`. Kroki, Visual Studio i `njr-engine-export.exe` są w `docs\BUILD-WINDOWS-1.0.14.md`. Binarki Engine z Maca na Windows nie przenoś.

W `cmd` albo PowerShell, po złożeniu narzędzia Engine:

```bat
cd C:\ścieżka\do\projekt\editor
py -3 -m pip install -r requirements-dev.txt
py -3 -m PyInstaller njr.spec --clean --noconfirm
cd ..
mkdir releases
copy /Y "editor\dist\Imprezja Playlist Pro.exe" releases\Imprezja-Playlist-Pro-1.1.3-windows-x64.exe
```

Suma przy wgraniu:

```powershell
Get-FileHash .\releases\Imprezja-Playlist-Pro-1.1.3-windows-x64.exe -Algorithm SHA256
```

Program otwiera własne okno. Jak Windows nie ma WebView2, doinstaluj Edge WebView2 Runtime. Plik nie jest podpisany. SmartScreen może pytać przy pierwszym uruchomieniu.

## Po złożeniu

W panelu wtyczki wgraj exe razem z dwoma DMG `Imprezja-Playlist-Pro-1.1.3-macos-arm64.dmg` i `Imprezja-Playlist-Pro-1.1.3-macos-intel-x64.dmg`. Wersja `1.1.3`. Puste pole zostawia stary plik tego systemu, ale numer i tak wymaga kompletu trzech plików tej wersji.

DMG złożone 22 października 2026, już na udziale w `releases`:

- `Imprezja-Playlist-Pro-1.1.3-macos-arm64.dmg` SHA-256 `18763e4bcd68f665c40d3d3ddff4b07f1826e9f27fb8267fb185544fdf07160c`
- `Imprezja-Playlist-Pro-1.1.3-macos-intel-x64.dmg` SHA-256 `6d200fcda72f1bbd101c0aa2e7b29e2936c3a5266856f4faf4cc9fabc28ef831`

Stary `Imprezja-Playlist-Pro-1.1.3-windows-x64.exe` na udziale jest sprzed tych poprawek. Zastąp go nowym złożeniem i dopiero wtedy wgrywaj komplet na stronę.

Przed zapisem do VirtualDJ i Serato zamknij ten program DJ. Engine nie dostanie utworu z Tidal. Dostanie plik, który leży na dysku.

## Następny build programu

Na koncie, w Programach przy Imprezja Playlist Pro, jest pole kodu. Domyślnie `START` daje 5 tokenów, raz na komputer. W programie, przy tokenach na karcie logowania, dołóż takie samo pole. Po zalogowaniu wyślij `POST /api/konwerter/promo` z tym samym nagłówkiem co zużycie tokenu i treścią `{"code":"START"}`. Saldo weź z odpowiedzi. Nie buduj tego w 1.1.3.
