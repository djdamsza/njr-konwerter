# VDJ → Rekordbox: migracja i ograniczenia

## Kompatybilność z Rekordbox 5, 6, 7

**Eksportujemy do formatu Rekordbox XML** – kompatybilnego z **Rekordbox 6 i 7**.

Jeśli używasz **Rekordbox 5**, możesz bezpłatnie przekonwertować bazę do RB6 w samym Rekordbox:
- W Rekordbox 5: **File → Library → Convert database for Rekordbox 6**
- Po konwersji otwórz bibliotekę w RB6 – eksport XML będzie działał tak samo
- RB6 i RB7 mają ten sam format XML – pełna kompatybilność

Nie musimy ręcznie konwertować RB5→RB6 – Rekordbox robi to wbudowanym narzędziem.

---

## Co wiemy

### VirtualDJ czyta master.db
VDJ ma opcję `rekordBoxFolder` – wskazuje na folder RB (z master.db). VDJ **odczytuje master.db bezpośrednio** i wyświetla metadane. Źródło: [VDJ Forums](https://virtualdj.com/forums/250950/), [VDJ Wiki](https://www.virtualdj.com/wiki/VDJ_database.html).

### Rekordbox ma inne wymagania
Ta sama baza (master.db), którą VDJ poprawnie wyświetla, w RB często pokazuje:
- puste playlisty (0 utworów),
- brakujące metadane (BPM 0.00, puste kolumny),
- częściowe dane (np. Date Added się wypełnia, reszta nie).

RB nie udostępnia dokumentacji formatu master.db – tylko XML (rekordbox.com/support/developer/).

---

## Zalecany workflow: **Import XML** (zamiast Restore)

Import XML jest oficjalnym formatem RB i zwykle działa stabilniej niż Restore Library.

### Krok po kroku

1. **W RB:** File → Add to collection (lub przeciągnij folder z plikami muzycznymi)
   - RB zaimportuje pliki i odczyta metadane z ID3.
   - Utwory będą miały zielone ikony.

2. **W RB:** File → Export – zapisz `rekordbox.xml`.

3. **W konwerterze:** Załaduj backup VDJ → kliknij **„Eksport playlist do RB”** → wybierz plik XML z kroku 2.

4. Pobierz wygenerowany `rekordbox-playlists.xml`.

5. **W RB:** Preferences → Advanced → Database → rekordbox xml → Imported Library → Browse → wybierz `rekordbox-playlists.xml`.

6. **W RB:** W drzewie Media Browser rozwiń „rekordbox xml” → „Playlists” → przeciągnij playlisty do głównej sekcji Playlists.

(Jeśli nie widzisz „rekordbox xml”: Preferences → View → Layout → zaznacz [rekordbox xml] w Media Browser.)

---

## Restore Library – kiedy używać

Restore (master.db) ma sens, gdy:
- potrzebujesz pełnej migracji (cue points, beatgrid, hot cues),
- masz szablon RB (backup ZIP) i poprawne pathFrom/pathTo.

Jeśli Restore daje puste metadane lub puste playlisty, przejdź na workflow XML powyżej.

---

## Ograniczenia (VDJ, MIXO, inne konwertery)

- **Smart lists / Filter Folders** – reguły VDJ; większość konwerterów ich nie obsługuje (MIXO też nie). Eksportuj je jako playlisty (m3u) do MyLists.
- **Tagi** – różne programy mapują User1/User2/Genre inaczej; możliwe rozjazdy.
- **VDJ czyta master.db** – jeśli RB nie wyświetla metadanych, a VDJ tak, to RB ma inne wewnętrzne wymagania, których nie udokumentowano.
