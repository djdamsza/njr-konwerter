# Windows — co się zmieniło, 20 października 2026

Kod na udziale `\\192.168.18.170\share\projekt` jest z tego wieczora. `VERSION` zostaje `1.0.15`. Składanie: `docs\BUILD-WINDOWS-1.0.14.md`. Stary exe w `releases` zastąp nowym plikiem o tej samej nazwie.

Każdy zapis do Engine kopiuje cały folder `Database2`. W żywej bazie leży też stary plik `m.db.bak-njr-przerwa3-…` (około 700 MB). Wcześniej wchodził do każdej kopii, więc jeden zapis zabierał około 1,4 GB. Teraz ten plik zostaje na miejscu i nie jest kopiowany, a zostają najwyżej dwie kopie.

## Engine DJ

To jest ta zmiana, którą warto sprawdzić.

- Zapis VirtualDJ → Engine dokłada utwory i podmienia skład list. Utworów, które już są w Engine, nie kasuje.
- Serato → Engine nadal usuwa z bazy utwory spoza Serato.
- Duża biblioteka VirtualDJ nie otwiera każdego nagrania drugi raz przy listach. Wcześniej synchronizacja przez to wisiała.
- Ten sam plik zostaje pod starym skrótem `Music\…`, nawet gdy w bazie zmieni się artysta. Analiza i waveform zostają przy tym utworze.
- Ścieżka z dysku Rane, która nie zaczyna się od `Music\`, nie przerywa już całego zapisu.
- Jeśli choć jedna ścieżka eksportu nie jest w `Music\`, `m.db` nie jest zapisywane.
- Ten sam plik na dysku dostaje jeden wpis. Wcześniej druga ścieżka `Music\` (inna nazwa folderu albo inny zapis polskich liter) dokładała drugi utwór i biblioteka się podwajała. Kolejny zapis ma zaktualizować stary wpis.
- Streaming i pliki `.vdjcache` do Engine nie wchodzą. Zwykłe pliki na dysku dostają skrót, bez kopiowania muzyki.

Przed PyInstallerem nadal złóż `njr-engine-export.exe`. Bez tego synchronizacja Engine kończy się brakiem narzędzia. Komendy są w `docs/BUILD-WINDOWS-1.0.14.md`. Binarka z Maca na Windows nie działa i na udziale jej nie ma.

Zamknij Engine DJ przed zapisem. Program robi kopię `Database2` i dopisuje do istniejącej biblioteki. Nie podmienia całego `m.db`.

## Inne poprawki w tym samym kodzie

- Tagi: 100 utworów za 1 token. Drugi przycisk taguje resztę, partiami po 100.
- Analiza tytułów: jedna paczka to 120 poprawek i 120 braków za 1 token.
- Pimp my list: idzie cała lista. Odczyt liczy się jako 1 token za każde 300 utworów.
- Eksport do Serato pomija plik, gdy punkty cue w nagraniu są już takie same. Przy zapisie widać, ile plików zostało zapisanych.

## Składanie

Ikona jest w `editor\static\brand\app-icon.ico`. `njr.spec` wpinają ją w exe.

Skrótów menu Start i pulpitu ten kod nadal nie tworzy. Zostało to z `docs/WINDOWS-SKROTY.md`: przy instalacji mają powstać skróty o nazwie `Imprezja Playlist Pro`, wskazujące zainstalowany program, nie kopię z Pobranych.

Kolejność:

1. Visual Studio 2022, vcpkg i `njr-engine-export.exe` — jak w `docs/BUILD-WINDOWS-1.0.14.md`.
2. Potem PyInstaller z `editor`.
3. Nowy exe nie zastępuj w ciemno pliku, który już leży w `releases\`. Najpierw sprawdź synchronizację Engine na kopii biblioteki.
