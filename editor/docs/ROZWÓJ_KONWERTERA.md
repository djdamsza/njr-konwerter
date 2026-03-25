# Rozwój konwertera – zadania na później

---

## Część 1: Analiza przepływu danych (round-trip)

### VDJ → VDJ (bez konwersji)

```
ZIP/database.xml → load_database → _songs (dict)
       ↓
[edycja w pamięci]
       ↓
save_database → database.xml / ZIP
```

**Zachowanie:** Pełna spójność. `song_to_dict` i `dict_to_song` zachowują wszystkie atrybuty `Tags.*`, `Infos.*` oraz `_children_xml` (Poi, Comment, Scan, Link itd.) jako surowy XML. Brak utraty danych.

**Linked tracks (VDJ):** Powiązania między utworami (`<Link>`) są przechowywane w `_children_xml` i przy zapisie VDJ (load → edycja → save) są zachowane. Konwerter nie uszkadza linked tracks w database.xml. Uwaga: ręcznie dodane powiązania w VDJ mogą być także w pliku `extra.db` – tego pliku edytor nie modyfikuje.

---

### Serato → Serato (przez Unified)

```
database V2 + Subcrates → load_serato_folder → UnifiedDatabase
       ↓
unified_to_vdj_songs → _songs (VDJ-style dict)
       ↓
[edycja w pamięci]
       ↓
save_serato_database_v2(_songs) → database V2
save_serato_crate(track_ids) → Subcrates/*.crate
```

**Potencjalna utrata/zmiana danych:**

| Aspekt | Import (Serato) | Eksport (Serato) | Uwaga |
|--------|-----------------|------------------|-------|
| **Date Added** | Nie odczytujemy `tadd`/`uadd` | Zawsze `now` (aktualny czas) | **Utrata** – oryginalna data dodania jest tracona |
| **Album, Year** | Nie odczytujemy `talb`, `ttyr` | Nie zapisujemy | Serato ma te pola (rzadko), my ich nie obsługujemy |
| **Tagi Genre** | `tgen` → genre + tags | Genre + User1 + User2 → `tgen` | **Duplikacja** – przy Serato→VDJ→Serato tagi mogą się powielić (Genre + User1 + User2 łączone bez deduplikacji) |
| **Cue points, Beatgrid** | Nie ma w Database V2 | Nie zapisujemy | Serato trzyma je w plikach audio – Database V2 ich nie zawiera |
| **Pola binarne Serato** | `bbgl`, `bcrt`, `bply` itd. | Tylko `bmis` | Nie odtwarzamy pełnego zestawu flag Serato |

---

## Część 2: Mapowanie baz VDJ ↔ RB ↔ Serato

### Pola utworu – mapowanie

| Pole | VDJ (database.xml) | Rekordbox (XML/master.db) | Serato (Database V2) |
|------|--------------------|---------------------------|----------------------|
| **Ścieżka** | `FilePath` | `Location` (file://localhost/...) | `pfil` (względna do rootu dysku) |
| **Tytuł** | `Tags.Title` | `Name` | `tsng` |
| **Artysta** | `Tags.Author` | `Artist` | `tart` |
| **Album** | `Tags.Album` | `Album` | `talb` (nie obsługujemy) |
| **Rok** | `Tags.Year` | `Year` | `ttyr` (nie obsługujemy) |
| **Genre** | `Tags.Genre` | `Genre` | `tgen` |
| **User1/User2** | `Tags.User1`, `Tags.User2` | `Comments` (#tag) | `tgen` (łączone) |
| **Comment** | `<Comment>` w children | `Comments` (tekst bez #) | `tcom` |
| **BPM** | `Tags.Bpm` (60/bpm) | `AverageBpm` | `tbpm` |
| **Key** | `Tags.Key` / `Scan.Key` | `Tonality` | `tkey` |
| **Rating** | `Tags.Stars` (0–5) | `Rating` (0–255) | `tcom` ("Rating: N") |
| **Play count** | `Infos.PlayCount` | `PlayCount` | `utpc` |
| **Długość** | `Infos.SongLength` | `TotalTime` | `tlen` (MM:SS.ss) |
| **Bitrate** | `Infos.Bitrate` | `BitRate` | `tbit` (np. "320.0kbps") |
| **Sample rate** | `Infos.SampleRate` | `SampleRate` | `tsmp` |
| **Date Added** | — | `DateAdded` | `tadd`/`uadd` (nie zachowujemy) |
| **Cue points** | `<Poi Type="cue">` | `POSITION_MARK` | **Pliki audio** (Markers2) |
| **Beatgrid** | `<Poi Type="beatgrid">` | `TEMPO` | **Pliki audio** (BeatGrid) |

### Gdzie dane są przechowywane

| Typ danych | VDJ | Rekordbox | Serato |
|------------|-----|-----------|--------|
| Lista utworów | database.xml | master.db / XML | database V2 |
| Playlisty | vdjfolder / XML | master.db / XML | Subcrates/*.crate |
| Tagi, metadane | database.xml | master.db / XML | database V2 |
| Cue points | database.xml (Poi) | master.db (djmdCue) | **pliki audio** |
| Beatgrid | database.xml (Poi) | master.db | **pliki audio** |

---

## Część 3: Różnice do rozwiązania (rzeczy do zrobienia)

### A. Utrata danych przy round-trip

1. **Date Added (Serato, RB)**  
   - Serato: `tadd`/`uadd` nadpisywane przez `now`.  
   - RB: `DateAdded` na stałe `"2020-01-01"`.  
   - **Do zrobienia:** Odczytywać i zachowywać Date Added w modelu, przekazywać przy eksporcie.

2. **Album, Year (Serato)**  
   - Serato ma `talb`, `ttyr`, ale ich nie odczytujemy ani nie zapisujemy.  
   - **Do zrobienia:** Dodać obsługę `talb` i `ttyr` w imporcie/eksporcie Serato.

3. **Duplikacja tagów (Serato)**  
   - Eksport: `genre_str = " ".join(g, u1, u2)` bez deduplikacji.  
   - Przy Serato→VDJ→Serato tagi się powielają.  
   - **Do zrobienia:** Przed zapisem do `tgen` usuwać duplikaty (np. unikalne tagi z union).

### B. Różnice formatów – wymagane mapowania

4. **Rating**  
   - VDJ: 0–5 (Stars).  
   - RB: 0–255 (0→0, 1→51, 2→102, … 5→255).  
   - Serato: 0–5 w `tcom`.  
   - **Status:** Adapter RB↔VDJ już konwertuje. Serato używa 0–5. Sprawdzić eksport RB XML.

5. **Ścieżki**  
   - VDJ: absolutna.  
   - Serato: względna do rootu dysku.  
   - RB: `file://localhost/...` lub `tidal:tracks:...`.  
   - **Do zrobienia:** Weryfikacja `drive_root` i mapowania ścieżek przy eksporcie Serato.

6. **BPM**  
   - VDJ: `60/bpm` gdy 0.2–2.0.  
   - RB/Serato: BPM wprost.  
   - **Do zrobienia:** Upewnić się, że konwersja jest odwracalna we wszystkich kierunkach.

### C. Dane poza Database V2 (Serato)

7. **Cue points i Beatgrid**  
   - Serato trzyma je w plikach audio (Markers2, BeatGrid), nie w Database V2.  
   - **Do zrobienia:** Zapis do plików audio (zadanie 1 i 2 z listy poniżej).

8. **Flagi binarne Serato**  
   - `bbgl`, `bcrt`, `bply` itd. nie są odczytywane ani zapisywane.  
   - **Do zrobienia:** Określić, które flagi są istotne, i dodać ich obsługę.

### D. VDJ – pola tracone przy konwersji na Unified

9. **FileSize, Flag**  
   - `_track_to_vdj_dict` ustawia `FileSize=""`, `Flag=""`.  
   - **Do zrobienia:** Zachować oryginalne wartości przy round-trip VDJ→Unified→VDJ.

10. **Podział tagów Genre/User1/User2**  
    - Przy konwersji na Unified tagi są łączone, potem dzielone na User1/User2 (połowę każdemu).  
    - Oryginalny podział Genre vs User1 vs User2 jest tracony.  
    - **Do zrobienia:** Rozważyć zachowanie oryginalnego podziału (np. w rozszerzonym modelu).

---

## Potwierdzenie rozumienia

### Co działa poprawnie

W naszej aplikacji można **dowolnie edytować listy** (playlisty, crates, foldery) z:
- **Serato** (database V2, Subcrates)
- **VDJ** (VirtualDJ backup, vdjfolder)
- **Rekordbox** (XML, m.db)
- **DJXML**
- **Traktor** (collection.nml)
- **Engine DJ** (m.db)

**Jeśli nie przechodzą konwersji na inny system** – zachowują spójność i działają w 100% prawidłowo, tylko ze zmienioną treścią (np. zmiana nazwy playlisty, kolejności utworów, dodanie/usunięcie utworu z listy).

### Gdzie pojawiają się problemy

Problemy występują przy:
1. **Konwersji** między systemami (eksport z VDJ do Serato, import Serato do RB itd.)
2. **Zapisach tagów, markerów i gridów** – które są przechowywane w **różnych miejscach** dla różnych programów:

| Program   | Tagi (Genre, User1, User2) | Cue points / hot cues | Beatgrid |
|-----------|----------------------------|------------------------|----------|
| VDJ       | database.xml (Tags)        | database.xml (Poi)     | database.xml (Poi) |
| Serato    | Database V2 (tgen, tcom)   | **pliki audio** (Serato Markers2) | **pliki audio** (Serato BeatGrid) |
| Rekordbox | master.db / XML           | master.db (djmdCue)    | master.db |
| Traktor   | collection.nml            | collection.nml        | collection.nml |
| DJXML     | plik XML                  | plik XML              | plik XML |

### Wniosek

**Zewnętrzne zabiegi** – zapis do plików audio (MP3, FLAC, M4A), do baz binarnych (master.db, m.db), synchronizacja między formatami – **wymagają poszerzenia możliwości konwertera**, aby wszystko działało spójnie przy migracji między systemami.

---

## Zadania do wprowadzenia na później

### 1. Serato Markers2 – zapis cue points do plików audio

**Cel:** Cue points z naszej bazy → tag Serato Markers2 w plikach MP3/FLAC/M4A.

**Zakres:**
- Parser/generator formatu binarnego Serato Markers2
- Zapis GEOB (MP3), Vorbis comment (FLAC), MP4 atom (M4A)
- Mapowanie kolorów VDJ ↔ Serato
- Endpoint + UI: „Zapisz cue points do plików (Serato)”

**Szczegóły:** Zobacz plan w poprzedniej dyskusji (serato32, struktura cue, serato-tools / triseratops).

---

### 2. Serato BeatGrid i Autotags – zapis do plików audio

**Cel:** Beatgrid i BPM z naszej bazy → tagi Serato BeatGrid i Serato Autotags w plikach.

**Zakres:**
- Format Serato BeatGrid
- Format Serato Autotags (BPM, gain)
- Zapis do plików audio

---

### 3. Pełna konwersja tagów przy eksporcie

**Cel:** Genre, User1, User2, Comment, Rating, PlayCount – spójne mapowanie przy każdej konwersji.

**Status:** Częściowo zrobione (Serato tgen, tcom, utpc). Do uzupełnienia:
- Weryfikacja mapowania dla RB, Traktor, Engine DJ
- Eksport tagów do ID3 – rozszerzenie o wszystkie pola

---

### 4. Import cue points z plików audio (Serato)

**Cel:** Odczyt Serato Markers2 z plików → cue points w naszej bazie (przy imporcie z Serato).

**Zakres:**
- Parser Serato Markers2 (odczyt)
- Mapowanie do Track.cue_points
- Integracja przy ładowaniu biblioteki Serato

---

### 5. Synchronizacja Database V2 ↔ pliki audio

**Cel:** Gdy użytkownik eksportuje do Serato – cue points z bazy trafiają zarówno do Database V2 (jeśli możliwe) jak i do plików audio (Markers2).

**Uwaga:** Database V2 nie przechowuje cue points – tylko pliki audio. Więc eksport = zapis do plików.

---

### 6. Mapowanie reguł VDJ ↔ Serato (UI jak Lexicon)

**Cel:** Dwie pionowe listy – lewa: pola VDJ (Genre, User1, User2, Comment, Rating, PlayCount…), prawa: pola Serato (tgen, tcom, utpc, tart, tsng…). Użytkownik wybiera, gdzie która informacja ma trafić (np. Genre+User1+User2 → tgen). Zapis konfiguracji mapowania.

**Zakres:**
- UI: dwie listy z możliwością łączenia pól źródłowych z docelowymi
- Profile mapowania (np. domyślny, custom) – zapis/odczyt JSON
- Integracja z save_serato_database_v2 – użycie mapowania zamiast stałego

---

## Priorytety

1. **Wysoki:** Zapis Serato Markers2 do plików (punkt 1) – najczęstszy przypadek migracji VDJ → Serato
2. **Średni:** Serato BeatGrid/Autotags (punkt 2), import Markers2 (punkt 4)
3. **Niski:** Pełna weryfikacja mapowania tagów (punkt 3)

---

## Podsumowanie – bezpieczny transfer danych

Aby przenoszenie danych między VDJ, RB i Serato było bezpieczne, należy:

1. **Zachować Date Added** – odczytywać i zapisywać w modelu, nie nadpisywać stałą.
2. **Deduplikować tagi** przy eksporcie Serato (Genre + User1 + User2 → unikalne tgen).
3. **Obsłużyć Album i Year** w Serato (talb, ttyr).
4. **Zachować FileSize i Flag** przy round-trip VDJ.
5. **Zaimplementować zapis Serato Markers2/BeatGrid** do plików audio – inaczej cue points i beatgrid nie trafią do Serato.
6. **Zweryfikować mapowanie RB Rating** (0–255 ↔ 0–5) we wszystkich ścieżkach eksportu.

---

*Dokument utworzony na podstawie analizy konwertera, przepływu danych i dyskusji o Serato Markers2.*
