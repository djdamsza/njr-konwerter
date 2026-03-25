# Narzędzia do dodania – analiza z forów i konkurencji

*Na podstawie przeszukania forów DJ (VirtualDJ, Rekordbox, Serato, MIXO, Lexicon), GitHub i dokumentacji konkurencyjnych narzędzi.*

---

## 1. Naprawa przesunięcia cue points / beatgrid (MP3 offset, „26ms problem”)

### Problem
Przy konwersji między Traktor, Rekordbox, Serato i VDJ cue points i beatgrid często przesuwają się o 10–60 ms. DJ-om przeszkadza to przy miksowaniu. Dotyczy głównie plików MP3 i MP4.

**Przyczyna:** Różna interpretacja tagów LAME w nagłówku MP3 – np. Traktor traktuje pewne ramki jako muzykę (26 ms śmieci), a Rekordbox je pomija.

### Rozwiązania na rynku
- **Lexicon** – automatyczna korekcja „beatshift” przy imporcie
- **dj-data-converter** (open-source) – dekoder nagłówka LAME, korekcja 0 lub 26 ms w zależności od typu pliku
- **MIXO** – opcja „MP3 Offset Fix”

### Co potrzeba do wdrożenia
- Dekoder nagłówka MP3 (Xing/INFO, LAME) – np. `digital-dj-tools/mp3-parser` lub `mutagen`
- Reguły korekcji: brak Xing → 0 ms; Xing bez LAME → 26 ms; LAME z błędnym CRC → 26 ms; LAME z poprawnym CRC → 0 ms
- Opcjonalnie: korekcja pozycji cue points w bazie przed eksportem (dodanie/odjęcie offsetu)
- UI: opcja „Korekcja offsetu MP3” przy eksporcie do RB/Serato

**Źródła:** [digital-dj-tools/dj-data-converter](https://github.com/digital-dj-tools/dj-data-converter), [Lexicon Beatshift Correction](https://lexicondj.com/manual/beatshift-correction)

---

## 2. Wykrywanie duplikatów

### Problem
Te same utwory w bibliotece pod różnymi nazwami, w różnych playlistach, w różnych folderach – utrudnia to porządkowanie i przygotowanie setów.

### Rozwiązania na rynku
- **Rekordbox Library Fixer** – audio fingerprinting + porównanie metadanych (Artist, Title, BPM, Key)
- **Lexicon** – Audio Match (fingerprint) + Tag Match (metadane)
- **Music Library Doctor** – wykrywanie duplikatów z natywną integracją RB/Serato/VDJ

### Co potrzeba do wdrożenia
- **Audio fingerprinting** – np. `chromaprint`/`pyacoustid` (AcoustID) – wymaga API key lub lokalnego modelu
- **Porównanie metadanych** – już mamy (wykrywanie duplikatów po ścieżce/similar) – rozszerzyć o porównanie Artist+Title
- **Reguły rozstrzygania** – zachować wyższą jakość (bitrate), nowszy plik, preferowany folder
- UI: lista grup duplikatów, wybór „zostaw”/„usuń z bazy”, batch operacje

**Źródła:** [rekordbox-library-fixer](https://github.com/koraysels/rekordbox-library-fixer), [Lexicon Find Duplicates](https://lexicondj.com/manual/find-duplicates)

---

## 3. Relokacja brakujących plików („!”)

### Problem
„!” – brak pliku. Pliki przeniesione, dysk zmieniony, zmiana struktury folderów – biblioteka ma stare ścieżki.

### Rozwiązania na rynku
- **Rekordbox Library Fixer** – skanowanie folderów, dopasowanie po nazwie (similarity)
- **Lexicon** – Find Broken Tracks, Relocate Missing Files
- **Music Library Doctor** – wykrywanie brakujących, relokacja

### Co potrzeba do wdrożenia
- Skanowanie folderów wskazanych przez użytkownika
- Dopasowanie: po ścieżce (np. `stem`), po nazwie pliku, opcjonalnie po metadanych
- Aktualizacja ścieżek w `_songs` / `FilePath`
- UI: lista brakujących, wybór folderów do skanowania, podgląd dopasowań, „Zastosuj”

**Źródła:** [rekordbox-library-fixer Track Relocation](https://github.com/koraysels/rekordbox-library-fixer)

---

## 4. Backup i przywracanie biblioteki

### Problem
Utrata bazy (crash, reinstalacja, uszkodzenie) – brak prostego backupu i przywracania.

### Rozwiązania na rynku
- **Lexicon** – cloud backup bazy
- **Rekordbox Library Fixer** – automatyczny backup XML przed operacjami
- **rekord.cloud** – subskrypcja, backup i sync

### Co potrzeba do wdrożenia
- **Backup:** eksport ZIP z database.xml + vdjfolders + opcjonalnie lista ścieżek
- **Przywracanie:** import z backupu, walidacja ścieżek
- **Harmonogram:** opcjonalnie cron/scheduled backup (wymaga integracji z systemem)
- UI: „Utwórz backup”, „Przywróć z backupu”

---

## 5. Eksport cue points do plików audio (Serato Markers2)

### Problem
Serato trzyma cue points w plikach audio, nie w Database V2. Przy migracji VDJ → Serato cue points nie trafiają do Serato.

### Rozwiązania na rynku
- **Lexicon** – pełna konwersja z cue points do Serato
- **MIXO:BRIDGE** – import VDJ z cue points, eksport do RB XML (subskrypcja GOLD)
- Brak darmowego, open-source narzędzia do zapisu Serato Markers2

### Co potrzega do wdrożenia
- Parser/generator formatu binarnego Serato Markers2 (serato32, struktura cue)
- Zapis do MP3 (GEOB), FLAC (Vorbis comment), M4A (MP4 atom)
- Mapowanie kolorów VDJ ↔ Serato
- Endpoint + UI: „Zapisz cue points do plików (Serato)” – batch dla wybranych utworów

**Źródła:** [ROZWÓJ_KONWERTERA.md](./ROZWÓJ_KONWERTERA.md), [Holzhaus/serato-tags](https://github.com/Holzhaus/serato-tags)

---

## 6. Weryfikacja integralności po imporcie

### Problem
Po imporcie XML do Rekordbox (5.6.1+) istniejące utwory nie są aktualizowane – Rekordbox ma bug. Użytkownik nie wie, czy import się powiódł.

### Rozwiązania na rynku
- **MIXO** – workaround: „Import To Collection” na playlistę, potem Ctrl+A → „Import To Collection” na utwory
- **Rekordbox 5.6.0** – starsza wersja bez buga

### Co potrzeba do wdrożenia
- **Raport po eksporcie:** lista utworów wyeksportowanych, liczba cue points, playlisty
- **Instrukcja w UI:** „Po imporcie do Rekordbox: prawy przycisk na playlistę → Import To Collection, potem zaznacz wszystkie utwory → Import To Collection”
- Opcjonalnie: wykrywanie wersji RB (jeśli dostępna) i wyświetlanie ostrzeżenia

**Źródła:** [MIXO Rekordbox XML Import Bug](https://www.mixo.dj/guides/rekordbox-xml-import-bug)

---

## 7. Konwersja smart playlists

### Problem
VDJ ma listy z filtrami (vdjfolder), RB ma smart playlists, Serato ma crates. Reguły nie są przenoszone 1:1.

### Rozwiązania na rynku
- **Lexicon** – konwersja smart playlists; nieobsługiwane reguły → zwykła playlist
- **Rexato** – konwersja playlist RB ↔ Serato (bez analizy)

### Co potrzeba do wdrożenia
- Mapowanie reguł VDJ (np. „User1 has #PARTY”) na format RB/Serato
- Fallback: smart playlist → zwykła playlist (wyliczona lista utworów)
- Rozszerzenie `SmartPlaylist` w `unified_model` o więcej typów reguł

**Źródła:** [Lexicon DJ Library Conversion](https://lexicondj.com/blog/dj-library-conversion), [Rexato](https://github.com/winson0123/Rexato)

---

## 8. Wykrywanie i naprawa mojibake (już mamy)

### Status
Już zaimplementowane – naprawa znaków UTF-8 odczytanych jako Latin-1/CP1250.

---

## 9. Podsumowanie – priorytety wdrożenia

| # | Narzędzie | Problem | Złożoność | Zależności |
|---|-----------|---------|-----------|------------|
| 1 | **MP3 offset / beatshift** | Przesunięcie cue przy konwersji | Średnia | mutagen / mp3-parser |
| 2 | **Relokacja brakujących** | „!” – brak plików | Niska | brak |
| 3 | **Backup/restore** | Utrata bazy | Niska | brak |
| 4 | **Serato Markers2** | Cue points do Serato | Wysoka | mutagen, format binarny |
| 5 | **Duplikaty (metadata)** | Bałagan w bibliotece | Niska | rozszerzenie istniejącego |
| 6 | **Duplikaty (audio fingerprint)** | Identyczne pliki pod innymi nazwami | Wysoka | chromaprint / AcoustID |
| 7 | **Instrukcja RB import** | Bug Rekordbox 5.6.1+ | Bardzo niska | dokumentacja w UI |
| 8 | **Smart playlists** | Reguły nie przenoszone | Średnia | mapowanie reguł |

---

## 10. Konkurencja – co oferują

| Narzędzie | Cena | VDJ | Serato | RB | Traktor | Engine | Duplikaty | Relokacja | Cue/Beatgrid |
|-----------|------|-----|--------|-----|---------|--------|-----------|------------|--------------|
| **Lexicon** | Subskrypcja / Lifetime | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (beatshift) |
| **Music Library Doctor** | $49 lifetime | ✓ | ✓ | ✓ | — | — | ✓ | ✓ | — |
| **Rexato** | Free, open-source | — | ✓ | ✓ | — | — | — | — | — |
| **Rekordbox Library Fixer** | Free | — | — | ✓ | — | — | ✓ | ✓ | — |
| **MIXO:BRIDGE** | GOLD subskrypcja | ✓ | ✓ | ✓ | — | — | — | — | ✓ |
| **rekord.cloud** | Subskrypcja | ✓ | ✓ | ✓ | — | — | — | — | — |
| **Nasz edytor** | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (path/similar) | — | Częściowo |

---

*Dokument utworzony na podstawie przeszukania forów VirtualDJ, Rekordbox, Serato, MIXO, Lexicon oraz repozytoriów GitHub.*
