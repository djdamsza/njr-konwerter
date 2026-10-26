# Windows — do poprawy po buildzie 1.1.0

Sprawdzone 21 października 2026 na kodzie z udziału. Plik `NJR-konwerter-1.1.0-windows-x64.exe` wstaje. Ścieżki VirtualDJ, Serato i konta są dobre. Logowanie i „Utwórz konto” też. Zostają trzy rzeczy.

Kod po tej notatce jest na udziale. Złóż exe jeszcze raz według `docs/BUILD-WINDOWS-1.0.14.md`. Numer zostaje 1.1.0, więc strona sama tej podmiany nie poda: uruchom nowy plik.

## 1. AI przez stronę nie odpowiada

Tak ma działać. Klucza modelu w programie nie ma.

Pimp my list („Pokaż 20”) kręci kółkiem i nie pokazuje propozycji. Z tego Windowsu:

`POST https://nowajakoscrozrywki.pl/api/konwerter/ai`

wraca w około sekundę: HTTP 503, `{"error":"no_key"}`.

Program pokazuje „AI na stronie nie jest jeszcze włączone.” Token urządzenia jest, konto jest zalogowane. Brakuje klucza modelu po stronie wtyczki, nie w exe.

## 2. Windows nie widzi programu jak aplikacji

Nie ma skrótu „Imprezja Playlist Pro” w menu Start (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\`) ani ikony na pulpicie. Wyszukiwarka bierze nazwę skrótu, a plik leży tylko w Pobranych. Ikona w exe jest (`editor/static/brand/app-icon.ico`). Quiz i fotobudka mają takie skróty.

## 3. Eksport Engine

W pliku nie ma `njr-engine-export.exe`. Na tym komputerze nie ma Visual Studio 2022 ani vcpkg, a binarki z Maca nie da się użyć. Synchronizacja Engine napisze, że brakuje narzędzia. Kroki są w `docs/BUILD-WINDOWS-1.0.14.md`.

## Teksty z Maca

Nie wywalają programu.

- `editor/serato_parser.py`, instrukcja eksportu: „Cmd+Q” i `~/Music/_Serato_/`. Na Windowsie zwykłe zamknięcie programu i `Music\_Serato_`.
- `editor/static/index.html`, opis kosza: Finder i kosz macOS. Na Windowsie kosz systemowy.
- `editor/engine_stems.py`, `editor/engine_stems_render.py`, `editor/engine_stems_queue.py`: „Cmd+Q” bez `plain_quit`.
