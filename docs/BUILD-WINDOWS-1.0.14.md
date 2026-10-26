# Windows — złożyć Imprezja Playlist Pro 1.1.1

Na tym komputerze powstaje tylko plik Windows. DMG 1.1.1 powstają na Macu. Tych DMG nie składaj i nie podmieniaj.

Po złożeniu i pierwszym uruchomieniu exe sam zakłada skrót „Imprezja Playlist Pro” w menu Start i na pulpicie. Wskazuje plik, z którego program został otwarty, więc nie zostawiaj go tylko w Pobranych, jeśli ma leżeć gdzie indziej: przenieś exe i uruchom jeszcze raz.

AI nie ma klucza w tym pliku ani w programie na Macu. Jeden klucz jest na stronie. Po wgraniu wtyczki 1.9.12 korzysta z niego każda instalacja, Windows i każdy Mac. Klucza nie wklejaj i nie szukaj go na dysku.

Eksport Engine jest osobno, niżej. Bez Visual Studio 2022 i vcpkg program i tak wstanie. Synchronizacja Engine napisze tylko, że brakuje narzędzia. Na komputerze bez tych programów ten krok pomiń.

Kod bierz z `\\192.168.18.170\share\projekt`, nie z GitHuba. Użytkownik udziału: `projekt`. Co jest w tym wydaniu i jak nazwać plik: `docs/ZMIANY-WINDOWS-1.1.1.md`. Krótka komenda jest w `ZLOZ-NA-WINDOWS.txt`.

Wersja w pliku `VERSION` w korzeniu:

```text
1.1.1
```

## Pliki na stronę

Wtyczka przyjmuje tylko te nazwy. Na stronę nic nie wgrywaj, dopóki nie ma o to prośby. Plik zostaje w `releases\`.

| Slot | Plik |
| --- | --- |
| Mac Apple Silicon | `Imprezja-Playlist-Pro-1.1.1-macos-arm64.dmg` |
| Mac Intel | `Imprezja-Playlist-Pro-1.1.1-macos-intel-x64.dmg` |
| Windows | `Imprezja-Playlist-Pro-1.1.1-windows-x64.exe` |

Na Windowsie DMG nie składaj. Zostaw exe w `releases`. Wersji 1.1.1 w panelu wtyczki nie zapisuj, dopóki nie ma trzech nowych plików.

## Co ma być na tym komputerze

Cały folder `projekt`, nie sam `editor`. Potrzebne są `VERSION`, `scripts/build-local.sh` i `editor/`.

W `editor\engine_bridge\build` nie ma gotowej binarki. Tę z Maca trzeba złożyć u siebie od nowa. Bez niej program wstanie, ale zapis do Engine napisze, że brakuje narzędzia.

## Programy

- Windows 10 albo 11, 64 bity
- Python 3.11 albo 3.12, z zaznaczonym „Add python.exe to PATH”
- W terminalu `py -3 --version` albo `python --version` pokazuje tę wersję

Python 3.9 nie składa tego programu: brakuje do niego gotowych bibliotek okna.

## Eksport Engine, przed PyInstallerem

Bez tego plik wstanie, ale synchronizacja Engine DJ napisze, że brakuje narzędzia. `njr.spec` pakuje binarkę tylko wtedy, gdy już leży w jednym z tych miejsc:

- `editor\engine_bridge\build\Release\njr-engine-export.exe`
- `editor\engine_bridge\build\njr-engine-export.exe`

Na Windowsie, w `editor\engine_bridge`, po zainstalowaniu Visual Studio 2022 i vcpkg:

```bat
vcpkg install zlib sqlite3 date sqlite-modern-cpp --triplet x64-windows-static
cmake -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_TOOLCHAIN_FILE=%VCPKG_INSTALLATION_ROOT%\scripts\buildsystems\vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows-static -DSYSTEM_SQLITE=ON -DSYSTEM_DATE_H=ON -DSYSTEM_SQLITE_MODERN_CPP=ON
cmake --build build --config Release
```

Potem dopiero PyInstaller. Reszta różnic względem Maca jest w `docs/BLEDY-WINDOWS-1.0.14.md`.

## Złożenie

W `cmd` albo PowerShell:

```bat
cd C:\ścieżka\do\njr-konwerter\editor
py -3 -m pip install -r requirements-dev.txt
py -3 -m PyInstaller njr.spec --clean --noconfirm
```

Powstaje `editor\dist\Imprezja Playlist Pro.exe`. To jest program, który się uruchamia. Kopia pod nazwę wtyczki:

```bat
cd C:\ścieżka\do\projekt
mkdir releases
copy /Y "editor\dist\Imprezja Playlist Pro.exe" releases\Imprezja-Playlist-Pro-1.1.1-windows-x64.exe
```

Jeśli na tym Windowsie jest Git Bash, z korzenia repozytorium `./scripts/build-local.sh` zapisze od razu `releases/Imprezja-Playlist-Pro-1.1.1-windows-x64.exe`. Tej nazwy nie zmieniaj. `NJR-konwerter-…` zainstalowany program 1.0.16 i 1.1.0 odrzuca i pokazuje „Masz najnowszą wersję”.

## Suma pliku

W PowerShell, z korzenia repozytorium:

```powershell
Get-FileHash .\releases\Imprezja-Playlist-Pro-1.1.1-windows-x64.exe -Algorithm SHA256
```

Tę sumę wpisuje się we wtyczce przy pliku Windows, gdy plik będzie wgrywany na stronę. Teraz pliku nie wgrywaj.

## Po uruchomieniu

Program otwiera własne okno, nie kartę przeglądarki. Windows 10 i 11 mają do tego WebView2. Jak go nie ma, instalator Edge WebView2 Runtime jest na stronie Microsoftu.

Plik nie jest podpisany certyfikatem. Windows SmartScreen może przy pierwszym uruchomieniu pytać o zgodę.

Skrypt nie wgrywa pliku na stronę. Plik zostaje w `releases/` na tym komputerze, a na stronę wchodzi przez panel wtyczki.
