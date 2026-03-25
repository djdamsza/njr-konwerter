# Testowa baza RB – diagnostyka problemu z czerwonymi ikonami

## Zalecany workflow (gdy Sync/Export dają czerwone ikony)

1. **W RB:** File → Add to collection (lub przeciągnij folder z plikami) – utwory mają zielone ikony
2. **W RB:** File → Export – zapisz plik XML
3. **W konwerterze:** Załaduj backup VDJ, kliknij „Eksport playlist do RB”, wybierz plik XML z kroku 2
4. **Pobierz** rekordbox-playlists.xml
5. **W RB:** Preferences → Advanced → Database → rekordbox xml → Imported Library → Browse → wybierz rekordbox-playlists.xml
6. **W RB:** W drzewie Media Browser rozwiń „rekordbox xml” → „Playlists”, przeciągnij playlisty do głównej sekcji Playlists

(Jeśli nie widzisz „rekordbox xml”: Preferences → View → Layout → zaznacz [rekordbox xml] w Media Browser.)

---

## Cel (diagnostyka)

Stworzenie minimalnej bazy z **znanymi danymi** (ścieżki do plików VoteBattle, tytuły TEST_RB_001, TEST_RB_002…) – aby porównać, co zapisujemy vs co pokazuje Rekordbox.

## Skrypty testowe

### 1. `create_test_rb_db.py` – bezpośrednia generacja master.db

**Tryb wariantów ścieżki** (zalecany do diagnostyki):
```bash
python3 scripts/create_test_rb_db.py --variants --sync
```
Ten sam plik zapisany 4× z różnymi formatami:
- `TEST_PATH_01_absolute` – /Users/test/...
- `TEST_PATH_02_file_localhost` – file://localhost/Users/...
- `TEST_PATH_03_file_triple` – file:///Users/...
- `TEST_PATH_04_file_no_leading` – file://Users/... (bez / na początku ścieżki)

Sprawdź w RB, który wiersz ma **zieloną ikonę** – ten format działa.

**Tryb standardowy** (5 plików):
```bash
python3 scripts/create_test_rb_db.py [--template backup.zip] [--output test-output] [--sync]
```

- **--template** – backup RB (ZIP) lub master.db; domyślnie: ~/Library/Pioneer/rekordbox/master.db
- **--output** – folder wyjściowy (domyślnie: test-output/)
- **--sync** – skopiuj master.db do folderu RB

**Wynik:** `test-output/master.db` + `test-output/MANIFEST.txt`

### 2. `create_test_vdj_zip.py` – pełny pipeline VDJ → RB

Tworzy backup VDJ (ZIP) z database.xml + TestList.vdjfolder. Testuje cały łańcuch konwersji.

```bash
python3 scripts/create_test_vdj_zip.py [--output test-backup-vdj.zip]
```

**W konwerterze:**
1. Załaduj ten ZIP (VDJ: plik ZIP)
2. Szablon RB: wybierz backup RB
3. Sync do RB (bez pathFrom/pathTo – ścieżki są bezwzględne)
4. Porównaj RB z MANIFEST.txt w ZIP

## Procedura diagnostyczna

### Krok 1: Wygeneruj testową bazę

```bash
cd tools/vdj-database-editor
python3 scripts/create_test_rb_db.py --output test-output --sync
```

### Krok 2: Zamknij Rekordbox, uruchom ponownie

### Krok 3: Porównaj z manifestem

Otwórz `test-output/MANIFEST.txt`. Zawiera:
- Ścieżki, tytuły, artist – co zapisaliśmy
- Odczyt z djmdContent – co jest w bazie
- contentFile – ścieżki (pełne, bez obcinania)
- **djmdContent FolderPath** – RB oczekuje PEŁNEJ ścieżki do pliku (włącznie z nazwą), nie samego folderu
- Czy pliki istnieją (Exists: True/False)

### Krok 4: Sprawdź w RB

| Co sprawdzić | Oczekiwane | Jeśli inaczej |
|--------------|------------|---------------|
| Liczba utworów | 5 | Błąd w zapisie |
| Tytuły | TEST_RB_001 … TEST_RB_005 | Błąd w djmdContent |
| Artist | VoteBattle_Zar, VoteBattle_Muminki… | RB może czytać z plików |
| Ikony | Zielone (plik znaleziony) | Czerwone = RB nie znajduje pliku |
| Playlisty | TestList (przy VDJ ZIP) | Problem z vdjfolder |

### Odkrycie z rekordbox_bak_3.zip (2026-02)

Porównanie backupu RB (po imporcie folderu) z naszą bazą wykazało:
- **RB w djmdContent:** `FolderPath` = PEŁNA ścieżka do pliku (np. `/Users/.../Cypis - Mamy Moc.mp3`), `FileNameL` = nazwa pliku
- **My wcześniej:** `FolderPath` = tylko folder, `FileNameL` = nazwa pliku
- **Poprawka:** generator zapisuje teraz `FolderPath` = pełna ścieżka (jak RB)

### Alternatywa: Import XML (gdy master.db nie działa)

Jeśli bezpośredni zapis do master.db nie działa, spróbuj importu XML:

```bash
python3 scripts/create_test_rb_xml.py
```

W RB: **File → Import → Rekordbox** → wybierz `test-output/rekordbox-import-test.xml`.

- **Zielona ikona** → import XML działa; problem leży w strukturze master.db
- **Czerwona ikona** → RB nie akceptuje tej ścieżki także przez XML

**Ważne:** RB wymaga Size, TotalTime, BitRate, SampleRate z pliku – bez tych wartości (gdy są 0) może pokazywać czerwone ikony. Generator XML odczytuje je z plików (mutagen).

### Krok 5: Zwrot informacji

Jeśli RB nadal pokazuje czerwone ikony mimo że MANIFEST potwierdza `Exists: True`:
- RB używa innego mechanizmu wyszukiwania plików
- Możliwy problem z formatem ścieżek (encoding, separator)
- Możliwy problem z DeviceID / rb_data_status

## Pliki testowe (VoteBattle)

- `public/uploads/1770813410399-zar_tropikow.mp3`
- `public/uploads/1770812911057-muminki.mp3`
- `public/uploads/sfx/seabattle.mp3`
- `public/familiada/sounds/jingle.mp3`
- `public/familiada/sounds/correct.mp3`
