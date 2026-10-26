# VDJ → Rekordbox: migracja i ograniczenia

## Metoda sprawdzona (Rekordbox 7.2.10, 16 października 2026)

Tak wchodzi biblioteka do kolekcji. Potwierdzone eksportem kolekcji `xml 3.xml`: 12809 utworów, artysta przy 12615, 414 playlist z utworami w folderze Serato. Konwerter nie zapisuje `master.db`.

### Plik z konwertera

Eksport zapisuje `~/Downloads/Imprezja-Playlist-Pro-rekordbox.xml`.

- `Location`: `file://localhost/Users/...`, spacja jako `%20`, `&` jako `%26`, przecinek i nawiasy bez zmian.
- Folder to `NODE Type="0"`. Lista to `Type="1" KeyType="1"`. `TRACK Key` to ten sam `Location` co w kolekcji.
- Ocena: 0 / 51 / 102 / 153 / 204 / 255.
- Drzewo jest w folderze `Serato`. Obok jest playlista `wszystkie pliki`.

### Co klika użytkownik

1. Jeśli te pliki już są w kolekcji ze starymi danymi, usuń je z kolekcji razem ze starymi playlistami. Plików muzycznych nie kasuj. Rekordbox rozpoznaje utwór po ścieżce i zostawia stare tagi.
2. **Preferences → Advanced → Database → rekordbox xml** i wklej ścieżkę pliku z Pobranych. Poczekaj na „Loading XML library”. To jest osobna biblioteka XML, nie kolekcja.
3. W drzewie `rekordbox xml` przeciągnij folder `Serato` na **Playlists** w kolekcji. Poczekaj na „Importing”.
4. W kolekcji wypełnione listy są w folderze **Serato na dole**. Nazwa z datą (na przykład `25.09.26 Dorota Mikołaj`) to folder. Utwory są poziom niżej: `muzyka`, `tort`, `wejscie`. `wszystkie pliki` jest playlistą i utwory ma od razu.
5. Stare puste nazwy nad folderem Serato (`automix`, `tidal top` i reszta) to poprzednia kolekcja. Można je usunąć.

### Czego nie brać za wynik

- **File → Export collection** zapisuje kolekcję (`master.db`), nie bibliotekę XML. `xml.xml` i `xml2.xml` były tym starym zapisem, zanim przeciągnięto folder.
- Log braków jest w `~/Documents/rekordbox/Import Log - ….txt`. To pliki, których nie ma na dysku. Ostatni log (80 plików) nie był Tidalem ani cache.

### Decyzja dla użytkownika

- **Wgraj od nowa.** Usuń stare utwory z kolekcji, wklej XML, przeciągnij folder Serato.
- **Dopisz listy.** Nie usuwaj kolekcji. Przeciągnij tylko wybrane listy z widoku XML. Tagi utworów, które już są w kolekcji, zostaną stare.

# VDJ → Rekordbox: migracja i ograniczenia (starsze notatki)

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

## Zalecany workflow

Użyj sekcji „Metoda sprawdzona” na górze tego pliku. Samo wklejenie ścieżki ładuje bibliotekę XML. Do kolekcji wchodzi dopiero przeciągnięcie folderu Serato na Playlists.

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
