# NJR Engine Export (libdjinterop)

Most C++ bridge between NJR Konwerter and [libdjinterop](https://github.com/xsco/libdjinterop).

## Build

```bash
cd editor/engine_bridge
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

Binary: `build/njr-engine-export` (or `.exe` on Windows).

## Runtime

Python (`engine_libdjinterop.py`) writes JSON and calls:

```bash
njr-engine-export /tmp/export.json
```

JSON schema is produced by `engine_generator.py` from `UnifiedDatabase`.

## Engine DJ import

### Sync do Engine DJ Desktop (zalecane)

1. Zamknij **Engine DJ Desktop** (Cmd+Q).
2. W NJR: **Sync Engine Desktop** (merge do `~/Music/Engine Library`).
3. Otwórz Engine DJ → podłącz Rane → **Pack/Sync** na dysk kontrolera.

Ustaw `libraryRoot` na folder nadrzędny ścieżek VDJ (np. `/Users/nazwa/Desktop`).
Playlisty trafiają do folderu **VDJ** z zachowaniem drzewa z backupu
(`MyLists` → `gatunki` → `DISCO-POLO` itd.). Filter listy → statyczne playlisty.

Merge aktualizuje istniejące utwory po ścieżce względnej (beatgrid, cue, tagi)
i playlisty po nazwie — **nie podmienia** całego `m.db` i nie psuje `hm.db` / `stm.db`.

### Eksport ZIP (pendrive / osobny folder)

1. Export **Engine ZIP** from NJR.
2. Unzip on USB or a **new** folder — **not** into `~/Music/Engine Library`.

Filter lists from VirtualDJ are expanded to static playlists before export.
