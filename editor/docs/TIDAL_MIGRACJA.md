# Migracja utworów Tidal VDJ → Rekordbox

## Format ścieżek

| Źródło | Format | Przykład |
|--------|--------|----------|
| **VirtualDJ** | `td` + Tidal track ID | `td252147049` |
| **VirtualDJ** (netsearch) | `netsearch://td` + ID | `netsearch://td330964` |
| **Rekordbox** | `file://localhosttidal:tracks:` + ID | `file://localhosttidal:tracks:252147049` |

Tidal track ID jest identyczny w VDJ i RB – to ten sam numer z API Tidal.

## Wymagania

1. **Rekordbox** – subskrypcja Tidal (Premium lub HiFi) + zalogowanie w Media Browser
2. **Internet** – utwory Tidal wymagają połączenia

## Workflow (Eksport playlist do RB)

1. **VDJ:** backup (ZIP) z playlistami zawierającymi utwory Tidal
2. **RB:** File → Add to collection (folder z plikami lokalnymi) + File → Export (XML)
3. **Konwerter:** Eksport playlist do RB – wybierz XML z RB + backup VDJ
4. **Wynik:** XML z playlistami – utwory lokalne (dopasowane z RB) + utwory Tidal (w formacie RB)

Utwory Tidal są dodawane do COLLECTION z konwersją `td123` → `file://localhosttidal:tracks:123`.

5. **RB:** Preferences → Imported Library → wybierz plik, przeciągnij playlisty z drzewa
6. **RB:** Zaloguj się do Tidal (Media Browser), aby odtworzyć utwory Tidal

## Ograniczenia

- **Tidal zmienia ID** – Tidal czasem „upgraduje” utwory i przypisuje nowe ID. Stare referencje mogą przestać działać („Unknown stream type” w VDJ).
- **MIXO:** MIXO nie importuje utworów Tidal – nie ma lokalnego pliku do analizy.
- **Sprawdzanie dostępności** (panel „Tidal – utwory niedostępne"): używa nieoficjalnego API Tidal – wyniki mogą być niepełne przy limitach lub braku dostępu.
