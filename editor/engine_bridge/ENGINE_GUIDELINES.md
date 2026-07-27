# Engine DJ — wytyczne dla NJR Konwerter

Źródła: [Engine DJ v3.0 — Third-Party Database Tools](https://enginedj.com),
[Mixxx Engine Library Format](https://github.com/mixxxdj/mixxx/wiki/Engine-Library-Format),
[Mixxx Serato Database Format](https://github.com/mixxxdj/mixxx/wiki/Serato-Database-Format).

## Zasady (obowiązujące w NJR)

| Zasada Engine DJ | Implementacja NJR |
|------------------|-------------------|
| Nie edytować schematu `.db` | Merge przez **libdjinterop** (`njr-engine-export`); brak `CREATE/ALTER TABLE` w produkcji |
| Nie pracować równolegle z Engine DJ | `is_engine_running()` / `dj_apps_guard.py` → błąd 409 przed merge/naprawą |
| Nie pracować równolegle z VDJ / Serato | `sync_guard_blockers()` — pgrep + WAL database V2 |
| Tożsamość utworu: `originTrackId` + `originDatabaseUuid` | Remap `PlaylistEntity` przez `originTrackId` (`repair_engine_playlist_entity_refs`) |
| Backup przed migracją | `backup_engine_database2()` → `_njr-backup-{data}-pre-merge/` |
| Własne dane w oddzielnej bazie + ATTACH | *Nie dotyczy merge* — używamy oficjalnego API libdjinterop na `m.db` |
| Nie kasować `hm.db` / `stm.db` / `sm.db` | Przy resecie biblioteki: **tylko** konfliktujący root `m.db` lub pełna kopia zapasowa całego `Database2/` |

## Serato

- Format **nieoficjalny** — parser oparty na reverse engineering + testy na kopiach `_Serato_/`.
- Zapis do Serato: zawsze z backupem (`Export Backups/`).
- Testować na kopii biblioteki, nie na produkcji.

## Checklist przed merge Engine

1. **VirtualDJ zamknięty** (sync VDJ → Engine)
2. **Serato DJ zamknięty** (sync Serato → Engine; brak świeżego WAL/SHM przy `database V2`)
3. Engine DJ **zamknięty** (Cmd+Q)
4. Brak **legacy `m.db`** w korzeniu przy istniejącym `Database2/m.db`
5. **Walidacja schematu** — `validate_engine_schema()`: 2.18.0…3.0.2, `PRAGMA integrity_check`, ostrzeżenie o brakujących `hm.db`/`sm.db`/`stm.db`
6. Automatyczna **kopia zapasowa** `Database2/` (wbudowana w sync)
7. Po merge: **post-merge repair** (orphan PE, PerformanceData, isAnalyzed)
8. Po aktualizacji playlist na Patriot: **„Sync playlisty → Patriot”** w NJR (bez kopiowania plików) — **nie** „Export to Drive” w Sync Manager gdy Patriot ma już `Music/`
9. Po błędnym Export to Drive: `GET /api/diagnose-patriot-library` — wykrywa duplikaty; sync Patriot w NJR jest blokowany do czasu naprawy

## Loops (PerformanceData.loops)

- JSON eksportu: `"loops": [{slot, label, start_sample_offset, end_sample_offset, pad}]` (max 8).
- Parser VDJ: `Poi Type="loop"` (`Size` w beatach).
- Parser Serato: Markers_ entries 5–12 (`EntryType.LOOP`).
- `njr-engine-export` zapisuje przez libdjinterop `track_snapshot.loops`.

API diagnostyczne: `GET /api/validate-engine-library` (opcjonalnie `?engineDir=/Volumes/Patriot/Engine Library`).

## Znane ograniczenia (poza NJR)

- **Engine Sync Manager** kopiuje `PlaylistEntity` z ID Maca → wymaga remap na Patriot/Rane.
- **Engine DJ** synchronizuje `stm.db`/`sm.db` przy starcie — mogą powstać osierocone PE ze starej bazy; NJR czyści przy starcie (Engine zamknięty).
| Forward migrations schematu Engine | `validate_engine_schema()` blokuje merge gdy schemat > 3.0.2 lub < 2.18.0; ostrzeżenie przy starszym schemacie w zakresie |
