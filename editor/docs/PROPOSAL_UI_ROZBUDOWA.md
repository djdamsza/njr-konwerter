# 3 propozycje graficznej rozbudowy konwertera NJR

Inspiracje: Lexicon DJ, Rekordbox, Serato, VirtualDJ – profesjonalne narzędzia dla DJ-ów.

---

## Propozycja 1: „Lexicon-style” – pełny dashboard DJ

**Filozofia:** Aplikacja wygląda jak dedykowane narzędzie do zarządzania biblioteką DJ – ciemny, spójny interfejs z wyraźną hierarchią i ikonami.

### Główne zmiany

1. **Header z logo i statusem**
   - Logo/branding po lewej (np. „NJR” lub „Imprezja Konwerter”)
   - Pasek statusu: liczba utworów, źródło (VDJ/RB/Serato), ikona licencji
   - Przycisk „Otwórz bazę” jako główny CTA (zielony/akcentowy)
   - Tryb ciemny/jasny (opcjonalnie)

2. **Sidebar z ikonami i grupami**
   - Każda sekcja ma ikonę (np. folder, lista, tag, duplikat, eksport)
   - Grupowanie: **Import** | **Narzędzia** (brakujące, duplikaty, bitrate…) | **Edycja** (tagi, playlisty, tytuły…) | **Eksport**
   - Aktywna sekcja: podświetlony pasek + ikona w kolorze akcentu
   - Zwijany sidebar na mobile (hamburger)

3. **Karty narzędzi – layout „kafelkowy”**
   - Każda karta ma nagłówek z ikoną, krótki opis i przyciski akcji
   - Tło karty: lekki gradient lub obramowanie
   - Wyniki (np. brakujące pliki) w tabeli z możliwością rozwijania wierszy

4. **Tabela utworów – styl DJ**
   - Nagłówki kolumn: ikony (np. nutka dla tytułu, zegar dla długości)
   - Alternatywne tło wierszy dla lepszej czytelności
   - Hover: delikatne podświetlenie
   - Rating jako gwiazdki (już jest)
   - Camelot/Key w kolorze (np. A=niebieski, B=zielony)

5. **Kolorystyka**
   - Ciemny: `#0d1117` (tło), `#161b22` (karty), `#238636` (akcent/sukces), `#58a6ff` (linki)
   - Alternatywa: fioletowo-granatowa (jak Lexicon) – `#1e1b4b`, `#312e81`, `#6366f1`

### Szacowany nakład
- 2–3 dni (CSS, ikony, reorganizacja HTML)

---

## Propozycja 2: „Rekordbox-style” – dwukolumnowy browser

**Filozofia:** Główny widok to przeglądarka utworów z panelem bocznym (playlisty/filtry), jak w Rekordbox.

### Główne zmiany

1. **Layout 3-kolumnowy**
   - **Lewa kolumna (ok. 200px):** drzewo playlist / filtrów / grup (Genre, User1, User2)
   - **Środkowa kolumna:** lista utworów (tabela)
   - **Prawa kolumna (ok. 280px, opcjonalnie zwijana):** szczegóły wybranego utworu (metadata, tagi, lista playlist)

2. **Lewy panel – drzewo**
   - Foldery/playlisty jako drzewo z ikonami
   - Kliknięcie = filtrowanie listy utworów
   - Grupowanie po Genre/User1/User2 jako „smart folders”
   - Wyszukiwarka na górze panelu

3. **Główna tabela**
   - Zawsze widoczna (bez przełączania kart dla podstawowego przeglądania)
   - Kolumny: checkbox, #, play, Artist, Title, BPM, Key, Rating, Genre, User1, User2, Path
   - Sortowanie i paginacja jak obecnie

4. **Panel szczegółów (prawy)**
   - Po zaznaczeniu utworu: tytuł, artysta, okładka (jeśli dostępna), BPM, Key, tagi
   - Szybka edycja tagów (chips do dodania/usunięcia)
   - Lista playlist, do których należy utwór

5. **Górny pasek**
   - Import (przeciągnij i upuść + przycisk)
   - Statystyki (utwory, playlisty)
   - Undo
   - Eksport (dropdown lub przyciski)

### Szacowany nakład
- 3–4 dni (nowy layout, panel szczegółów, logika filtrowania po drzewie)

---

## Propozycja 3: „Minimal Pro” – czysty, nowoczesny design

**Filozofia:** Prosty, czytelny interfejs – mniej elementów, więcej przestrzeni. Skupienie na treści, nie na dekoracjach.

### Główne zmiany

1. **Minimalistyczny header**
   - Tytuł „NJR Konwerter” + krótki opis
   - Jedna linia: [Otwórz bazę] [Cofnij] [Status: X utworów]
   - Bez zbędnych elementów

2. **Sidebar – tylko tekst**
   - Bez ikon (lub bardzo subtelne)
   - Sekcje oddzielone cienką linią
   - Aktywna pozycja: pogrubiona czcionka + kolor akcentu

3. **Karty – płaskie, czytelne**
   - Białe lub bardzo ciemne tło (zależnie od trybu)
   - Nagłówki H3 z opisem
   - Przyciski w jednej linii, bez ramek

4. **Tabela – „spreadsheet-like”**
   - Czyste linie, bez gradientów
   - Hover: lekki szary/czerwony odcień
   - Kolumny z wyraźnymi separatorami

5. **Kolorystyka**
   - Ciemny: `#18181b` (zinc-900), `#27272a` (zinc-800), `#3f3f46` (obramowania)
   - Akcent: `#22c55e` (zielony) lub `#0ea5e9` (niebieski)
   - Tekst: `#fafafa` / `#a1a1aa`

6. **Typografia**
   - Font: Inter, Geist lub system-ui
   - Nagłówki: 600–700, body: 400
   - Większe odstępy między sekcjami

### Szacowany nakład
- 1–2 dni (głównie CSS, mało zmian w strukturze)

---

## Porównanie

| Aspekt            | Propozycja 1 (Lexicon) | Propozycja 2 (Rekordbox) | Propozycja 3 (Minimal) |
|-------------------|------------------------|---------------------------|-------------------------|
| Złożoność         | Średnia                | Wysoka                    | Niska                   |
| Nakład pracy      | 2–3 dni                | 3–4 dni                   | 1–2 dni                 |
| Wygląd            | „DJ app”               | „DJ app”                  | „Narzędzie”             |
| Nowe funkcje UI   | Ikony, grupowanie      | Panel szczegółów, drzewo  | Brak                    |
| Mobile            | Zwijany sidebar        | Trudniejszy               | Prosty                  |

---

## Rekomendacja

- **Szybki efekt:** Propozycja 3 – mały nakład, duża poprawa czytelności.
- **Maksymalny „wow”:** Propozycja 1 – wygląd jak profesjonalna aplikacja DJ.
- **Najbardziej funkcjonalna:** Propozycja 2 – lepszy workflow przy dużej bibliotece.

Można też łączyć: np. Propozycja 3 jako baza + elementy z 1 (ikony, kolory).
