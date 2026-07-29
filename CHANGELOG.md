# Changelog — NJR Konwerter

Historia zmian. Na GitHub Releases (tag `1.0`) trzymane są **dwie ostatnie wersje** buildów do pobrania.

---

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
