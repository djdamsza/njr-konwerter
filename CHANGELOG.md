# Changelog — NJR Konwerter

Historia zmian. Na GitHub Releases (tag `1.0`) trzymane są **dwie ostatnie wersje** buildów do pobrania.

---

## 1.1.15 (2026-10-26)

Okno aktualizacji pokaże się ludziom ze starszej wersji, gdy w panelu wtyczki będzie wersja 1.1.15 i komplet trzech plików: Windows, Mac Apple Silicon i Mac Intel.

### Tidal i Pimp my list

- Eksport CSV i TXT z listy niedostępnych utworów Tidal oraz z Pimp my list zapisuje plik do Pobranych. Okno programu zostaje na swoim miejscu.
- Lista w zakładce Tidal przewija się razem ze stroną. Nagłówki kolumn zostają u góry.

---

## 1.1.14 (2026-10-25)

Okno aktualizacji pokaże się ludziom ze starszej wersji, gdy w panelu wtyczki będzie wersja 1.1.14 i komplet trzech plików: Windows, Mac Apple Silicon i Mac Intel.

### Logowanie Google

- Na ekranie konta jest **Zaloguj przez Google**, obok e-maila i hasła.
- To samo konto co na stronie, w quizie i w fotobudce. Program zapisuje tylko zgodę tej instalacji, nie hasło.
- Konto Google, którego nie było w sklepie, powstaje od razu. Hasła do strony ten sposób nie ustawia. Jak będzie potrzebne na stronie, zostaje przypomnienie hasła.

### Serato

- Zapis list nie zostawia już pustego wpisu, który przy następnym starcie Serato kasuje artystę, tytuł, BPM i tonację. Utwór nie znika z wyszukiwania, choć plik leży na dysku.
- Punkty cue zostają w pliku. Serato czyta je po wczytaniu utworu.
- Plik znaleziony jako brakujący wskazuje na kopię, która się odtwarza. Nie powstaje druga, martwa pozycja obok starej ścieżki.
- Kilka kopii tego samego pliku, także ze skrótu albo z kosza, składa się do tej, która gra. Program nie podpina pliku o innym tytule tylko dlatego, że nazwa jest podobna.
- Przy scaleniu wygrywa wpis z artystą i tytułem, nie pusta ścieżka.
- VirtualDJ, Engine DJ i Rekordbox tego czyszczenia tagów nie robią.

### Konto w panelu klienta

- Tokeny Playlist Pro są na koncie, nie na komputerze. Drugie konto zalogowane na tej samej instalacji dostaje własne saldo i nie przejmuje poprzedniego.
- Na stronie konta widać jedno saldo konta. Komputery są tylko listą miejsc, z których to konto się loguje.
- Zakup, kod na start i zużycie AI zmieniają saldo zalogowanego konta. Kod na start nadal jest raz na komputer.
- Zakup nie dzieli tokenów na komputery. Cała paczka wchodzi na konto i działa na każdym komputerze tego e-maila.

### Poza tym programem

- Żeby Google i saldo na koncie działały, na stronie ma być wtyczka konta 1.9.22.
- Nazwa „Moje Kursy” na stronie nie została zmieniona. Wejście do konta nadal jest osobną sprawą od kursów.

---

## 1.0.13 (2026-09-21)

### Otwieranie bazy Serato
- Dialog **Otwórz bazę** pokazuje wszystkie pliki (w tym `database V2` bez rozszerzenia), nie tylko ZIP.
- Przycisk **Otwórz folder Serato** — `_Serato_` albo katalog nadrzędny (np. `Music`).
- Ścieżka do pliku, folderu `_Serato_` i ZIP-a z zagnieżdżonym `_Serato_` ładuje utwory + crate’y.
- Natywny dialog obsługuje też VDJ/RB XML, Engine `m.db`, Traktor, DJXML i `.njr` (nie tylko Serato/ZIP).

---

## 1.0.12 (2026-07-30)

### Sync playlist po podmianie utworów
- Automatyczna synchronizacja ścieżek we **wszystkich** `.vdjfolder` po: scaleniu duplikatów (Tidal→lokalne), zamianie na Tidal, przeniesieniu pliku, Tidal→lokalne w playliście.
- Obsługa aliasów Tidal (`netsearch://td123` ↔ `td123`, `Link.NetSearch`).
- Przed eksportem ZIP — naprawa martwych referencji w playlistach względem bazy.

### CI — GitHub Release
- Przed uploadem: usuwanie starych assetów **tej samej wersji** (re-run / ponowny build nie kończy się błędem 422).
- Walidacja: release job wymaga 3 plików (Win + 2× Mac).
- `prune-github-release-assets.sh` bez `gh` CLI — tylko API + `GITHUB_TOKEN`.

## 1.0.11 (2026-07-30)

### Tidal OAuth — Online na Offline
- **Odśwież połączenie** najpierw odświeża token (bez logowania w przeglądarce); pełne logowanie tylko gdy refresh się nie uda.
- Ujednolicony scope OAuth (`user.read playlists.read`) — mniej błędów przy wymianie kodu.
- PKCE verifier zapisywany na dysk — callback działa po restarcie serwera.
- Ostrzeżenie w UI i terminalu, gdy aplikacja działa na porcie ≠ 5050 (błąd Tidal **11102** = brak Redirect URI w developer.tidal.com).

## 1.0.10 (2026-07-29)

### Mac — jedna instancja
- Drugie uruchomienie (np. z DMG gdy app już działa) otwiera istniejącą kartę zamiast startować ponownie — mniej komunikatów „aplikacja nie jest już otwarta”.
- Build `.app` bez widocznej konsoli Terminala.

## 1.0.9 (2026-07-29)

### Mac — mniej potwierdzeń Gatekeeper
- DMG zawiera **NJR Konwerter.app** (zamiast gołego pliku) + skrypt **Instaluj NJR Konwerter.command**.
- Skrypt kopiuje aplikację do `/Applications` i usuwa atrybut quarantine.
- Skrót **Applications** w oknie DMG (przeciągnij i upuść).
- Przy starcie aplikacja czyści quarantine z własnego bundle.
- **Bez konta Apple Developer** nadal wymagane jest **jedno** potwierdzenie (Ctrl+klik → Otwórz) — zero potwierdzeń wymaga notaryzacji.

## 1.0.8 (2026-07-29)

### Mac — prostsza instalacja
- Instrukcja na stronie pobierania: **skopiuj do Aplikacji → Ctrl + klik → Otwórz** (jedno potwierdzenie zamiast wielu kroków w Ustawieniach).
- Porządek na GitHub Releases: tylko buildy **1.0.8** i **1.0.7**; starsze assety usunięte.

## 1.0.7 (2026-07-29)

### Aktualizacje — wzmocnienie SSL
- Runtime hook PyInstaller (`pyi_rth_certifi.py`) — certyfikaty CA ładowane przed startem aplikacji.
- `ssl_utils` szuka `cacert.pem` także w `_MEIPASS` (onefile).
- Czytelniejszy komunikat przy błędzie SSL w „Sprawdź aktualizacje” (z linkiem do ręcznego pobrania).

---

## Wcześniejsze wersje (skrót)

| Wersja | Najważniejsze |
|--------|----------------|
| **1.0.6** | Naprawa SSL w buildzie (Tidal, aktualizacje, Online na Offline); naprawa ścieżek Serato po eksporcie. |
| **1.0.5** | Naprawa startu Windows (.exe) z NumPy 2.x / PyInstaller. |
| **1.0.4** | Auto-aktualizacja z GitHub (Mac DMG + Windows .exe). |
| **1.0.3** | API aktualizacji, UI w stopce, eksport bez klucza licencji. |
| **1.0.2–1.0.0** | Pierwsze buildy standalone, VDJ→Serato/Engine, hot cues, Smart Crates. |

Pełna historia w commitach: [github.com/djdamsza/njr-konwerter/commits/main](https://github.com/djdamsza/njr-konwerter/commits/main).
