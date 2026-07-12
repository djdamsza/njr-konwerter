# Edytor bazy danych VirtualDJ (NJR Konwerter)

Narzędzie do przeglądania, wyszukiwania i edycji bazy `database.xml` programu VirtualDJ. Przydatne przy porządkowaniu tagów (User1, User2, Genre) w bibliotece liczącej tysiące utworów.

## Instalacja

Z **korzenia repozytorium** `njr-konwerter`:

```bash
cd editor
python3 -m pip install -r requirements.txt
```

Opcjonalnie (build binarki):

```bash
python3 -m pip install -r requirements-dev.txt
```

## Uruchomienie

**Tryb deweloperski** (z katalogu `editor/`):

```bash
cd editor
python3 app.py
```

**Binarka** (po `./scripts/build-local.sh` z korzenia repo):

```bash
./releases/NJR-konwerter-1.0.0
```

Następnie otwórz w przeglądarce adres z terminala (domyślnie **http://127.0.0.1:5050**).

Na Macu w dev możesz też dwukrotnie kliknąć `run.command`.

## Testy automatyczne

Na macOS używaj **`python3`** (nie `python`).

Z katalogu `editor/`:

```bash
cd editor
python3 -m unittest test_roundtrip_formats -v
```

- **API (Flask):** `python3 test_api.py` — wymaga `test-backup-vdj.zip` lub ścieżki w `BACKUP_PATHS`.
- **Round-trip formatów:** syntetyczne testy bez serwera (patrz wyżej).
- **Z prawdziwym backupem ZIP:**

```bash
NJR_TEST_BACKUP="$HOME/Documents/backup.zip" python3 -m unittest test_roundtrip_formats.TestRoundtripWithRealBackup -v
```

CI uruchamia `test_roundtrip_formats` przy każdym pushu.

## Wersja

Numer wersji w pliku **`VERSION`** w korzeniu repozytorium. Aplikacja odczytuje go przy starcie (`/api/version`).

## Przygotowanie bazy

1. Kliknij **Wybierz folder z database.xml** i wskaż folder z plikiem `database.xml`.
2. VirtualDJ przechowuje bazę w `~/Documents/VirtualDJ/` — możesz wybrać ten folder.
3. Jeśli masz backup w ZIP, najpierw rozpakuj (np. do `virtualdj/`):
   ```bash
   unzip "2026-02-20 20-30 Database Backup.zip" -d virtualdj/
   ```
4. Po wyborze folderu kliknij **Załaduj**.
5. Aby zapisać zmiany, użyj **Pobierz database.xml** — zapisz plik i zastąp nim oryginał w folderze VirtualDJ.

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

Edytor zmienia **tylko** atrybuty w elemencie `<Tags>` (Genre, User1, User2, Author, Title itd.). Zachowuje strukturę XML, kodowanie UTF-8 oraz elementy Poi, Comment, Link.

## Funkcje

Szczegóły eksportu (Rekordbox, Serato, DJXML, ID3), playlist online/offline i sync do RB — bez zmian względem wcześniejszej dokumentacji w `docs/` w tym katalogu.

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
</VirtualDJ_Database>
```

- **User1 / User2** – tagi oddzielone spacjami, np. `#Lata20 #PARTY #Taneczne`.
- **Genre** – podobnie, np. `#House #EDM`.
