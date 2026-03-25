# Edytor bazy danych VirtualDJ

Narzędzie do przeglądania, wyszukiwania i edycji bazy `database.xml` programu VirtualDJ. Przydatne przy porządkowaniu tagów (User1, User2, Genre) w bibliotece liczącej tysiące utworów.

## Instalacja

```bash
cd tools/vdj-database-editor
pip install -r requirements.txt
```

## Uruchomienie

```bash
python app.py
```

Następnie otwórz w przeglądarce: **http://127.0.0.1:5050**

Na Macu możesz też dwukrotnie kliknąć `run.command`.

## Testy automatyczne

**Na macOS** w terminalu zwykle jest tylko **`python3`** – polecenie `python` bywa niedostępne (`command not found`). Użyj `python3` we wszystkich komendach poniżej.

- **API (Flask):** `python3 test_api.py` – wymaga `test-backup-vdj.zip` lub ścieżki w `BACKUP_PATHS` w skrypcie.  
  **Szybko na Macu:** dow z `~/Documents/backup.zip` (plik nie trafia do gita):
  `ln -sf "$HOME/Documents/backup.zip" "$(pwd)/test-backup-vdj.zip"` *(wykonaj w katalogu `vdj-database-editor`)*.
- **Round-trip formatów (bez serwera):** sprawdza VDJ → DJXML / Rekordbox XML → VDJ oraz zapis `database.xml`. **Musisz być w katalogu** `vdj-database-editor`:
  ```bash
  cd /ścieżka/do/VoteBattle/tools/vdj-database-editor
  python3 -m unittest test_roundtrip_formats -v
  ```
  Opcjonalnie z prawdziwym backupem ZIP (podaj **prawdziwą** ścieżkę do pliku `.zip`, nie przykładową):
  ```bash
  NJR_TEST_BACKUP="$HOME/Documents/backup.zip" python3 -m unittest test_roundtrip_formats.TestRoundtripWithRealBackup -v
  ```
  Uwaga: trasa **Rekordbox XML** w teście nie weryfikuje zachowania `<Comment>` (ograniczenie eksportu RB). DJXML może przenosić tagi między polami – test porównuje **zbiór** tokenów (Genre + User1/2 + Comment).

## Przygotowanie bazy

1. Kliknij **Wybierz folder z database.xml** i wskaż folder, w którym znajduje się plik `database.xml`.
2. VirtualDJ przechowuje bazę w `~/Documents/VirtualDJ/` – możesz wybrać ten folder.
3. Jeśli masz backup w ZIP, najpierw rozpakuj (np. do `virtualdj/`):
   ```bash
   unzip "2026-02-20 20-30 Database Backup.zip" -d virtualdj/
   ```
4. Po wyborze folderu kliknij **Załaduj**.
5. Aby zapisać zmiany, użyj **Pobierz database.xml** – zapisz plik i zastąp nim oryginał w folderze VirtualDJ.

## Edytowalne parametry

| Element | Pola | Opis |
|--------|------|------|
| **Tags** | Author, Title, Genre, Album, Year, Composer, Label, Remix, TrackNumber, Stars | Metadane utworu |
| **Tags** | User1, User2 | Twoje własne tagi (np. #Lata20, #PARTY, #cover) |
| **Tags** | Bpm, Key | BPM i tonacja (BPM w bazie: sekundy między bitami → wyświetlane: 1/Bpm*60) |
| **Infos** | SongLength, PlayCount, Bitrate, Cover | Informacje techniczne |
| **Poi** | Cue points, beatgrid | Punkty cue – edycja wymaga ostrożności |

**Uwaga:** VirtualDJ nie zaleca zapisywania do bazy z zewnętrznych narzędzi. Przed zapisem tworzony jest backup (`database.xml.bak`). Używaj na własną odpowiedzialność.

### Stabilność bazy po edycji

Edytor zmienia **tylko** atrybuty w elemencie `<Tags>` (Genre, User1, User2, Author, Title itd.). Zachowuje:
- strukturę XML (VirtualDJ_Database, Song, Tags, Infos, Scan, Poi, Comment)
- kodowanie UTF-8
- elementy Poi (cue points, beatgrid), Comment, Link

Baza powinna działać stabilnie w VirtualDJ, o ile nie modyfikujesz ręcznie pól systemowych (np. Flag). Zalecane: zrób kopię zapasową przed pierwszym użyciem.

## Funkcje

### Wyszukiwanie i filtrowanie
- **Szukaj** – wpisz frazę; przeszukiwane są: Author, Title, Genre, User1, User2, Album.
- **Grupuj po** – User1, User2, Genre lub Year – wyniki są grupowane.

### Tagi: Genre, User1, User2
Wszystkie trzy pola są widoczne jednocześnie. Możesz łączyć tagi z różnych pól:

- **Scal / Zmień nazwę** – wybierz tagi z dowolnych pól (Genre, User1, User2), wpisz nową nazwę, wybierz **Zapisz w** (gdzie ma trafić wynik) i kliknij **Scal**.
- **Usuń wybrane** – usuwa tag z utworów i z list (vdjfolder). Utwory pozostają.

### Listy (vdjfolder) i playlisty
Gdy wybierzesz folder zawierający `MyLists/` z plikami `.vdjfolder`, edytor:
- Ładuje je razem z bazą
- Przy scaleniu tagów – zamienia stare odniesienia na nowe (np. `#BALLADS` → `#BALLADY`)
- Przy usuwaniu – usuwa odniesienia do tagu z filtrów
- Pobieranie – zwraca ZIP z `database.xml` i zaktualizowanymi plikami `.vdjfolder`

Rozpakuj ZIP do folderu VirtualDJ, zachowując strukturę (np. `MyLists/`).

### Zapisywanie
- Kliknij **Zapisz**, aby zapisać zmiany do pliku.
- Przed zapisem tworzony jest backup `database.xml.bak`.

### Eksport tagów do ID3
Przycisk **Eksport tagów do ID3** (w sekcji Eksport) zapisuje metadane **bezpośrednio do plików audio (MP3, FLAC, M4A, OGG, WAV, AIFF)**. Tagi (Genre, User1, User2) są wpisywane do pola Genre w pliku – zmiany są trwałe. Zapewnia to wyszukiwanie tagów w programach DJ (Serato, Traktor, Engine DJ), które czytają metadane z plików.

**WAŻNE: ZAMKNIJ VirtualDJ przed zapisem.** Zapis do tysięcy plików przy włączonym VDJ może spowodować zawieszenie programu. Obsługuje zamianę ścieżki (pathFrom → pathTo), gdy pliki są na innym dysku.

### Mapowanie tagów przy eksporcie
| Format | Tagi |
|--------|------|
| **Rekordbox XML** | Tagi w Comments (aby nie przepadły). RB ma też oddzielne pole Genre. |
| **Serato, Traktor** | Genre + User1 + User2 łączone w pole Genre – umożliwia wyszukiwanie. |
| **DJXML** | Genre + KeywordTags |
| **ID3 (MP3)** | Wszystkie tagi w polu Genre |

Edycja plików MP3 (Eksport tagów do ID3) jest dodatkową funkcją przy eksporcie – zapisuje trwale do plików.

### Online na Offline
Zamiana playlist online na playlistę offline z lokalnej kolekcji. Wklej URL playlisty (Spotify, Tidal) lub listę utworów (Artist - Title, po jednym w linii). Algorytm dopasuje utwory z bazy – porównaj propozycje, odsłuchaj i utwórz playlistę.

**Spotify** – wymaga Client ID i Client Secret (rejestracja na [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)):
```bash
export SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET="..."
python app.py
```

**Tidal** – nieoficjalne API często zwraca 404 dla playlist. Alternatywa: otwórz playlistę w Tidal, skopiuj listę utworów i wklej w formacie `Artist - Title` (po jednym w linii).

### Sync do RB (jak Lexicon)
Przycisk **Sync do RB** zapisuje master.db bezpośrednio do folderu Rekordbox. **ZAMKNIJ Rekordbox** przed sync. **Zamknij też konwerter** (terminal z `python app.py`) przed użyciem Lexicon – oba programy potrzebują dostępu do master.db; działające jednocześnie powodują „database is locked”. Stary master.db zostanie zbackupowany. Obsługiwane formaty tagów: MP3, FLAC, M4A, OGG, OPUS, WAV, AIFF.

**RB pokazuje starą bazę po sync?**
1. **Backupy RB**: RB tworzy master.backup1/2/3.db. Przy starcie może „odtworzyć" starą bazę z backupu. Sync usuwa te pliki.
2. **Cloud Sync** (plan Creative/Pro): MY PAGE → CLOUD → wyłącz „Sync library to another device”. RB nadpisuje lokalną bazę z chmury przy starcie.
3. **Pliki WAL**: Sync usuwa master.db-wal i master.db-shm – stare pliki powodowały ładowanie starej zawartości.
4. **Ścieżki**: Jeśli pliki są na innym dysku niż w VDJ, wpisz pathFrom → pathTo (np. `/Users/xyz/Music` → `/Volumes/SSD/Music`). Bez tego RB pokaże czerwone ikony (brak pliku).

## Struktura bazy (VirtualDJ)

```xml
<VirtualDJ_Database Version="2026">
  <Song FilePath="..." FileSize="...">
    <Tags Author="..." Title="..." Genre="..." User1="..." User2="..." Bpm="..." Key="..." />
    <Infos SongLength="..." PlayCount="..." />
    <Scan ... />
    <Poi ... />
    <Comment>...</Comment>
  </Song>
  ...
</VirtualDJ_Database>
```

- **User1 / User2** – tagi oddzielone spacjami, np. `#Lata20 #PARTY #Taneczne`.
- **Genre** – podobnie, np. `#House #EDM`.
