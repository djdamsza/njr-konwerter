# Model migracji VDJ / Serato → Engine DJ

NJR Konwerter używa `unified_model.py` jako warstwy pośredniej. Poniżej: co jest przenoszone do Engine DJ Desktop (`~/Music/Engine Library`).

| Pole / funkcja | VirtualDJ | Serato DJ | Engine DJ | Uwagi |
|----------------|-----------|-----------|-----------|-------|
| **Utwory (ścieżki)** | `FilePath` | database V2 + crates | `Track.path` → `Music/Artist/Album/…` | Symlinki, bez kopiowania |
| **Tytuł / artysta / album** | Tags.* | database V2 | Track metadata | Fallback z ID3 gdy puste w VDJ |
| **Genre + tagi User** | Genre, User1, User2 | tgen (kotwice §tag§) | `genre` jako `#tagi` | Smartlisty Engine po `#tag` |
| **Comment** | `<Comment>` | — | `comment` | Nie mylić z tagami |
| **BPM** | beatgrid Poi / Tags.Bpm | plik / V2 | `bpm` + beatgrid | Preferowany beatgrid VDJ |
| **Key (Camelot)** | Tags.Key / Scan.Key | — | `key_camelot` | Mapowanie OpenKey → Camelot |
| **Rating** | Stars 0–5 | — | 0–100 | VDJ gwiazdki ×20 |
| **Play count** | Infos.PlayCount | — | — | Nie eksportowane do Engine |
| **Duration** | Infos.SongLength | — | `duration_sec` | |
| **Beatgrid** | Poi Type=beatgrid | — (w pliku czasem) | `beatgrid` markery | libdjinterop index -4…N |
| **Hot cues** | Poi Type=cue Num 1–8 | Markers2 + Markers_ 0–4 | `hot_cues` slot 0–7 | Serato: tagi w pliku |
| **Loops** | Poi Type=loop Size=beats | Markers_ wpisy 5–12 | `loops` slot 0–7 | Max 8 loopów Engine |
| **Playlisty statyczne** | .vdjfolder / listy | Subcrates `.crate` | PlaylistEntity | Drzewo VDJ / folder Serato |
| **Smartlisty / filtry** | filter list | smart crates | Smartlist (ograniczone) | VDJ filter → reguły Engine |
| **Streaming (Tidal)** | netsearch / cache | streaming:// | pomijane / NJR offline | Wymaga lokalnego pliku |

## Źródła danych cue / loop

| Źródło | Hot cues | Loops |
|--------|----------|-------|
| **VDJ** | `_children_xml` Poi cue | `_children_xml` Poi loop (Size w beatach) |
| **Serato** | GEOB Markers2 (+ Markers_ 0–4) | GEOB / atom Markers_ wpisy 5–12 |
| **Engine** | `PerformanceData.quickCues` | `PerformanceData.loops` |

## Ograniczenia

- **8 hot cues** i **8 loopów** (sloty 0–7) — zgodnie z Engine DJ / libdjinterop `MAX_LOOPS=8`.
- Serato Markers_ ma 9. slot loop (index 13) — ignorowany przy eksporcie do Engine.
- VDJ loop `Size` to długość w **beatach**, nie sekundach — konwersja przez BPM utworu.
- Merge Engine wymaga **zamkniętych** VDJ / Serato / Engine (patrz `dj_apps_guard.py`).
- Waveformy Engine nie są migrowane z VDJ/Serato — Engine analizuje pliki po sync.

## API sync

- `POST /api/sync-engine-desktop` — VDJ → Engine (blokuje gdy VDJ lub Engine działają).
- `POST /api/sync-serato-to-engine` — Serato → Engine (blokuje gdy Serato, WAL bazy lub Engine).

`UnifiedDatabase.source`: `"vdj"` | `"rb"` | `"serato"` | `"engine"`.
