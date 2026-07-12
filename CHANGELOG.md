# Changelog — NJR Konwerter

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
- Duplikaty: hash pliku, rozmiar+czas, Author+Title (reuse `/api/duplicates`).
- Remiksy/wersje: tryb `versions` (ten sam artysta + tytuł, Radio/Remix/Edit) obok `covers`.
- Usuwanie zaznaczonych plików fizycznie z dysku; RB posprząta puste wpisy sam.

- `verify.yml` — testy `test_roundtrip_formats` + sprawdzenie spójności wersji.
- Pin `pyinstaller==6.12.0` w `editor/requirements-dev.txt`.
- Zaktualizowany `editor/README.md` (ścieżki standalone repo).

## 1.0.0

- Pierwsza publiczna wersja standalone (`editor/`).
