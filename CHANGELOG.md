# Changelog — NJR Konwerter

## 1.0.4 (2026-07-27)

### Aktualizacje z GitHub
- Automatyczne sprawdzanie, pobieranie i instalacja nowszej wersji z GitHub Releases.
- macOS (arm64/Intel): DMG → podmiana aplikacji + restart.
- Windows: `.exe` → podmiana przez skrypt `.bat` + restart.

## 1.0.3 (2026-07-27)

### Aktualizacje z GitHub (dev)
- Sprawdzanie / pobieranie / instalacja nowszej wersji z GitHub Releases (jak w Imprezja Quiz).
- API: `POST /api/check-updates`, `GET /api/update-status`, `POST /api/install-update`.
- **macOS:** pobiera DMG (arm64 / Intel), montuje, kopiuje binary; podmiana działającej aplikacji przez skrypt + restart.
- **Windows:** pobiera `.exe`, podmiana uruchomionego pliku przez `.bat` + restart.
- UI w stopce: postęp pobierania + przycisk „Zainstaluj i uruchom ponownie”.
- Test: `editor/test_updater.py`.

### Open source / licencjonowanie
- Eksport odblokowany: brak wymogu aktywacji klucza.
- API licencji pozostawione dla kompatybilności, ale `canExport` jest zawsze `true`.
- UI pokazuje informację „open source” zamiast blokady eksportu.

### VDJ → Serato / Engine — drzewo 1:1 + smart listy
- **Serato Smart Crates** (`.scrate`): mapowalne filter listy VDJ → `SmartCrates/` z **czytelnymi nazwami** (bez `%%` — Serato nie nestuje Smart Crates).
- Przycisk **Napraw Smart Crates** + `/api/fix-serato-smart-crates` — rename zepsutych nazw, usuwanie duplikatów Subcrates.
- Niemapowalne filtry (np. rating w Serato, BPM/Key difference) → snapshot w Subcrates jak wcześniej.
- **Engine**: szersze reguły Smartlist (BPM, year, artist/title/comment) obok tagów/rating/play count.
- Drzewo folderów w **Crates** (Subcrates `%%`); Smart Crates = płaska sekcja z nazwami typu `TECHNO _1`.
- Query `includeAll=0` — bez playlisty „wszystkie pliki” (czystsze 1:1).

### Serato — martwe duble / żółte trójkąty
- Czyszczenie: remap `Inne komputery` / `G:` / `Volumes/osx` / `Mój dysk` → Desktop gdy plik istnieje.
- Usuwanie martwych dubli (ta sama nazwa pliku) i wpisów bez pliku na dysku.
- Crates aktualizowane pod zachowane ścieżki. Przycisk **Napraw ścieżki Serato**.

### Serato — eksport (dopracowany)
- Ścieżki zawsze `Users/…` (bez `/`) — bez klonów przy play.
- Domyślnie **tylko crates** gdy jest lokalna baza; pełny database V2 z potwierdzeniem.
- Dedupe utworów w DB i crate (`/Users` ≡ `Users`).
- W ZIP: `NJR-INSTALUJ.txt` z instrukcją instalacji.
- Przycisk **Napraw ścieżki Serato** (normalizacja + dedupe lokalnej biblioteki).

### Serato — klony utworów (/Users vs Users)
- Przyczyna: lokalna baza trzymała `/Users/…`, a Serato przy play dopisuje `Users/…` → klon.
- **Naprawa:** normalizacja całej biblioteki + crates do `Users/…` (bez `/`) + dedupe.

### Serato — hot cues (Markers2)
- Zapis hot cues do plików audio (`Serato Markers2`) — MP3/FLAC/M4A/AIFF/WAV.
- Eksport Serato: opcja **hot cues → pliki** (`writeCues=1`, domyślnie włączona w UI).
- Endpoint `POST /api/write-serato-cues` — sam zapis cue bez ZIP.
- Moduł `serato_markers.py` + testy `test_serato_markers.py`.
- **Skip bez zmian:** ponowny zapis pomija pliki, gdy cue (slot/ms/nazwa) są już takie same; `force` / `forceCues=1` wymusza nadpisanie.
- **Drzewo crates:** Subcrates z hierarchią `Parent%%Child.crate` (jak foldery Engine / VDJ).

## 1.0.1 (w przygotowaniu)

### Utrzymanie i bezpieczeństwo
- Wersja aplikacji czytana z pliku `VERSION` (`editor/version_info.py`).
- `.github/macos-entitlements.plist` — gotowe pod podpis i notaryzację macOS.
- Walidacja ścieżek rozszerzona na: `/api/audio-file`, `/api/open-folder`, `/api/scan-orphan-files`, `/api/write-tags`.
- Klucz testowy licencji działa tylko z `NJR_DEV=1`.
- Usunięto `debug-error.txt` i zduplikowany `njr_license.py`.

### Modularizacja (Faza C)
- Wydzielono `app_state.py` (wspólny stan sesji), `constants.py`, `native_dialogs.py`.
- Blueprinty Flask: `routes/meta`, `routes/session`, `routes/license`, `routes/files`.
- `app.py` deleguje stan do `app_state`; trasy meta/pliki/licencja/undo w blueprintach.

### RB Beta (porządek na dysku)
- Nowa zakładka **RB Beta**: skan folderów z muzyką bez bazy Rekordbox.
- Duplikaty: hash pliku, Author+Title (usunięto rozmiar+czas — złe wyniki).
- Remiksy/wersje: tryb `versions` (ten sam artysta + tytuł, Radio/Remix/Edit) obok `covers`.
- Usuwanie zaznaczonych plików fizycznie z dysku; RB posprząta puste wpisy sam.

- `verify.yml` — testy `test_roundtrip_formats` + sprawdzenie spójności wersji.
- Pin `pyinstaller==6.12.0` w `editor/requirements-dev.txt`.
- Zaktualizowany `editor/README.md` (ścieżki standalone repo).

## 1.0.0

- Pierwsza publiczna wersja standalone (`editor/`).
