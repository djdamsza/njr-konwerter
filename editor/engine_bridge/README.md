# NJR Engine Export (libdjinterop)

Most C++ bridge between NJR Konwerter and [libdjinterop](https://github.com/xsco/libdjinterop).

## Build

```bash
cd editor/engine_bridge
cmake -B build -DCMAKE_BUILD_TYPE=Release -DSYSTEM_SQLITE=OFF
cmake --build build --config Release
```

Na **Windows** (CI / lokalnie) — jak upstream libdjinterop, przez vcpkg + Visual Studio:

```bat
vcpkg install zlib sqlite3 date sqlite-modern-cpp --triplet x64-windows-static
cmake -B build -G "Visual Studio 17 2022" -A x64 ^
  -DCMAKE_TOOLCHAIN_FILE=%VCPKG_INSTALLATION_ROOT%\scripts\buildsystems\vcpkg.cmake ^
  -DVCPKG_TARGET_TRIPLET=x64-windows-static ^
  -DSYSTEM_SQLITE=ON -DSYSTEM_DATE_H=ON -DSYSTEM_SQLITE_MODERN_CPP=ON
cmake --build build --config Release
```

Binary: `build/njr-engine-export` (lub `build/Release/njr-engine-export.exe` na Windows).

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
