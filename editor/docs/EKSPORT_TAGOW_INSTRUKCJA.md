# Eksport tagów – instrukcja

## Eksport tagów do ID3 (pliki MP3)

Przycisk **Eksport tagów do ID3** w sekcji Eksport zapisuje wszystkie tagi (Genre, User1, User2) **bezpośrednio do plików audio**. Tagi są wpisywane do pola Genre w pliku – zmiany są trwałe.

- **Obsługiwane formaty:** MP3, FLAC, M4A, OGG, OPUS, WAV, AIFF
- **Co jest zapisywane:** Title, Artist, Album, Genre (wszystkie tagi łącznie), Year
- **WAŻNE:** ZAMKNIJ VirtualDJ przed zapisem – zapis do tysięcy plików przy włączonym VDJ może spowodować zawieszenie programu

Edycja plików MP3 jest dodatkową funkcją przy eksporcie – umożliwia przeniesienie tagów do plików, co ułatwia wyszukiwanie w Serato, Traktor, Engine DJ i innych programach, które czytają metadane z plików.

## Mapowanie tagów przy eksporcie do formatów DJ

| Format | Jak tagi są zapisywane |
|--------|------------------------|
| **Rekordbox XML** | Tagi trafiają do pola Comments (aby nie przepadły). RB ma też oddzielne pole Genre – Comments służy jako zapas. |
| **Serato** | Genre + User1 + User2 łączone w pole Genre – umożliwia wyszukiwanie tagów. |
| **Traktor** | (brak eksportu – przy imporcie z VDJ/RB tagi w Genre) |
| **DJXML** | Genre + KeywordTags |
| **ID3 (MP3)** | Wszystkie tagi w polu Genre pliku |

## Rekordbox – Comments vs tagi

W Rekordbox sekcja Comments i tagi (My Tags) to różne pola. RB może wpisać tagi w Comments, ale ma też oddzielne pole. Aby tagi nie przepadły przy eksporcie do RB XML, zapisujemy je w Comments.

## Serato – błąd „Could not sync Serato library for the main drive”

Serato wymaga **ścieżek względnych** do roota dysku (np. `Music/song.mp3`), nie absolutnych. Przy eksporcie:

1. **Podaj root dysku** w polu obok przycisku Serato:
   - Mac (dysk główny): `/Users/TwojaNazwa/` (gdzie są pliki muzyczne)
   - Mac (dysk zewnętrzny): `/Volumes/NazwaDysku/`
   - Windows: `C:\` lub `D:\` (litera dysku z muzyką)

2. **Rozpakuj ZIP** do folderu Music:
   - Mac: `~/Music/` (powinna powstać `~/Music/_Serato_/`)
   - Windows: `C:\Users\TwojaNazwa\Music\`

3. **Zamknij Serato** przed rozpakowaniem. Jeśli jest już folder `_Serato_`, zmień nazwę starego na `_Serato_old` i rozpakuj nowy.

4. Uruchom Serato – biblioteka powinna się załadować.
