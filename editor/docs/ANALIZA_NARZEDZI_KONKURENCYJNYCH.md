# Analiza narzędzi konkurencyjnych – Rexato, Rekordbox Library Fixer, Music Library Doctor

*Dokumentacja na potrzeby rozwoju konwertera – logika przenoszenia między systemami.*

---

## 1. Rexato

**Źródło:** [github.com/winson0123/Rexato](https://github.com/winson0123/Rexato)

### Czym jest
Aplikacja GUI (PyQt6) do konwersji playlist między Rekordbox a Serato. Cross-platform (Windows, Mac, Linux).

### Kluczowe funkcje
- **Bidirectional conversion** – RB ↔ Serato w obie strony
- **Auto-detection** – automatyczne wykrywanie instalacji obu programów
- **Zachowanie kolejności** – kolejność utworów w playlistach jest zachowana
- **Brak analizy** – NIE przenosi BPM, beatgrid, hot cues – te dane muszą być ponownie analizowane w docelowym programie

### Eksport do Rekordbox
- Rexato tworzy plik XML w formacie Rekordbox
- Używa ścieżek `file://localhost/...` (Location)
- Playlisty jako `<NODE Type="0">` (folder) i `<NODE Type="1">` (playlist) z `<TRACK KeyType="1" Key="file://localhost/..."/>`
- KeyType=1 = Key to Location (ścieżka pliku)

### Wnioski dla nas
- Format RB XML jest dobrze udokumentowany – Rexato go generuje
- Eksport do RB = generowanie XML z TRACK i PLAYLISTS
- Możemy inspirować się strukturą NODE/TRACK z Rexato
- **Rexato nie obsługuje VDJ** – my mamy szerszy zakres (VDJ, Serato, RB, Traktor, Engine, DJXML)

---

## 2. Rekordbox Library Fixer

**Źródło:** [github.com/koraysels/rekordbox-library-fixer](https://github.com/koraysels/rekordbox-library-fixer)

### Czym jest
Zestaw narzędzi do naprawy biblioteki Rekordbox (Electron + React). Działa na eksporcie XML – nie modyfikuje master.db bezpośrednio.

### Kluczowe funkcje
- **Duplicate Detection** – audio fingerprinting (chromaprint) + porównanie metadanych (Artist, Title, BPM, Key)
- **Track Relocation** – szuka przeniesionych plików w wskazanych folderach, dopasowanie po nazwie (similarity)
- **Resolution strategies** – zachowaj wyższą jakość (bitrate), nowszy plik, preferowany folder
- **IndexedDB** – wyniki zapisywane w przeglądarce, można wrócić do pracy

### Workflow
1. Eksportuj bibliotekę z RB do XML
2. Załaduj XML w narzędziu
3. Znajdź duplikaty / brakujące
4. Rozwiąż (usuń duplikaty, zastosuj relokację)
5. Import „cleaned” XML z powrotem do RB (File → Import → Collection)

### Wnioski dla nas
- **Relokacja** – skan folderów, dopasowanie po nazwie pliku (stem) – podobnie jak zaimplementowaliśmy
- **Duplikaty** – rozszerzyć o audio fingerprinting (wymaga chromaprint) lub metadata matching (Artist+Title już mamy)
- **RB Import** – RB ma bug (5.6.1+): istniejące utwory nie są aktualizowane. Workaround: Import To Collection na playlistę, potem Ctrl+A → Import To Collection na utwory
- Narzędzie obsługuje **tylko Rekordbox** – my mamy multi-format

---

## 3. Music Library Doctor

**Źródło:** [playlistdoctor.djkoray01.com](https://playlistdoctor.djkoray01.com/)

### Czym jest
Komercyjne narzędzie ($49 lifetime) – natywna integracja z Rekordbox, Serato, VirtualDJ (bez eksportu XML).

### Kluczowe funkcje
- **Native integration** – bezpośredni dostęp do baz (master.db, Database V2, database.xml)
- **Playlist transfer** – przenoszenie playlist między platformami
- **Duplicate detection** – wykrywanie duplikatów
- **Missing track fix** – naprawa brakujących plików (relokacja)
- **Backup** – backup bibliotek

### Wnioski dla nas
- Natywna integracja wymaga reverse engineeringu formatów binarnych (master.db, Database V2)
- My idziemy drogą XML/eksport – prostsza, bardziej przenośna
- **Relokacja** – ta sama logika: rekordy w bazie + nowe lokalizacje plików = dopasowanie

---

## 4. Mapowanie pól – Lexicon

**Źródło:** [lexicondj.com](https://www.lexicondj.com/)

### Field Mappings
Lexicon pozwala mapować pola między systemami – np. Rekordbox MyTags lub Energy/Danceability → pola docelowe z hashtagami. Dwie listy: źródło (lewa) i cel (prawa), użytkownik wybiera gdzie co trafia.

### Propozycja dla nas
**Mapowanie reguł VDJ ↔ Serato:**
- Lewa kolumna: pola VDJ (Genre, User1, User2, Comment, Rating, PlayCount, Author, Title, …)
- Prawa kolumna: pola Serato (tgen, tcom, utpc, tart, tsng, …)
- Użytkownik przeciąga/łączy: np. „Genre + User1 + User2” → „tgen”
- Zapis konfiguracji mapowania (np. JSON) – możliwość różnych profili

---

## 5. Podsumowanie – co wdrożyć

| Źródło | Funkcja | Status u nas |
|-------|---------|--------------|
| Rexato | Eksport RB XML | Mamy (rb_generator) |
| Rexato | Kolejność playlist | Zachowujemy |
| RB Library Fixer | Relokacja | **Wdrożone** |
| RB Library Fixer | Duplikaty (metadata) | Mamy (similar) |
| RB Library Fixer | Duplikaty (fingerprint) | Do rozważenia |
| RB Library Fixer | RB import workaround | Do dokumentacji |
| Music Library Doctor | Native integration | Nie – zostajemy przy XML |
| Lexicon | Field mapping UI | **Do wdrożenia** – dwie listy, wybór mapowania |

---

*Dokument utworzony na podstawie analizy repozytoriów i dokumentacji.*
