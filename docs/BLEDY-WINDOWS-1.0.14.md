# Błędy Windows — Imprezja Playlist Pro 1.0.14

Sprawdzone na złożonym `releases/Imprezja-Playlist-Pro-1.0.14-windows-x64.exe` (Python 3.12, WebView2 jest). Program wstaje, `/` i `/api/version` zwracają 1.0.14. Poniższe wychodzi dopiero przy pracy z bibliotekami.

Poprawione w kodzie pod wersję 1.0.15. Następny plik Windows bierze te ścieżki przy składaniu. Binarkę Engine nadal trzeba złożyć na Windowsie przed PyInstallerem.

Ścieżki, które na sprawdzonym komputerze są dobre:

| Program | Folder |
| --- | --- |
| VirtualDJ | `Documents\VirtualDJ` |
| Serato SQLite | `%LOCALAPPDATA%\Serato\Library` (`master.sqlite`, `root.sqlite`, `tidal.sqlite`) |
| Serato database V2 | `Music\_Serato_` |
| Engine DJ | `Music\Engine Library` |
| Rekordbox | `%APPDATA%\Pioneer\rekordbox` |

`editor/dj_libraries.py` te miejsca już znajduje. Reszta kodu często ich nie używa.

## 1. Zapis playlisty VirtualDJ pada błędem 500

`editor/app.py`, `_get_vdj_folders_path` (około 6769).

Na Windowsie funkcja woła `os.environ`, a plik nie importuje `os`. Gałąź Maca tego nie tyka, więc tam działa. Na Windowsie `/api/vdj-folders-path`, `/api/vdj-cache-path` i zapis „Online na Offline” do folderu VDJ kończą się `NameError`.

Po dodaniu importu ścieżka nadal jest zła: kod bierze `%LOCALAPPDATA%\VirtualDJ\Folders`. VirtualDJ trzyma bazę w `Documents\VirtualDJ`. Tak już szuka `dj_libraries._locate_vdj`. Cache to `Documents\VirtualDJ\Cache`, nie LocalAppData.

## 2. Zapis list Serato do SQLite idzie w folder z Maca

`editor/serato_library_sqlite.py`, stała `SERATO_LIBRARY_DIR` (około 22):

`Path.home() / "Library/Application Support/Serato/Library"`

Ta sama stała jest w `editor/dj_apps_guard.py` (około 13). Na Windowsie biblioteka jest w `%LOCALAPPDATA%\Serato\Library`.

Wywołania w `editor/serato_parser.py` nie podają `library_dir`, więc zostaje ścieżka Maca:

- `clear_container_assets_for_crate_stem` (około 3081)
- `install_local_tracks_into_root_library` (około 3154) — brak `root.sqlite`, lokalne utwory nie wchodzą do biblioteki
- `install_tidal_streaming_into_serato_library` (około 3164) — dostaje `serato_dir`, nie dostaje `library_dir`, więc `tidal.sqlite` też jest szukany w złym miejscu
- `remove_vdj_serato_library_tree` (około 3131)
- `finalize_serato_sqlite_after_install` (około 3245)

Skutek: crate’y w `Music\_Serato_` mogą powstać, a `root.sqlite`, `tidal.sqlite` i `master.sqlite` prawdziwej biblioteki zostają nietknięte. Użytkownik widzi „Brak …\root.sqlite”.

To samo założenie Maca jest w skryptach naprawczych, nie w oknie programu: `repair_serato_master_sqlite.py`, `repair_serato_root_sqlite.py`, `repair_serato_tidal_metadata.py`, `scripts/fix_serato_paths_with_backup.py`, `rebuild_linki_serato.py`.

W `serato_library_sqlite.py` około 1492 domyślna baza VDJ to znowu `Library/Application Support/VirtualDJ/database.xml`. Na Windowsie ma być `Documents\VirtualDJ\database.xml`.

## 3. Ten plik Windows nie ma eksportu Engine

W `releases\Imprezja-Playlist-Pro-1.0.14-windows-x64.exe` nie ma `njr-engine-export.exe`. Biblioteka Engine na dysku jest, synchronizacja kończy się brakiem narzędzia.

`docs/BUILD-WINDOWS-1.0.14.md` buduje tylko PyInstaller. Binarkę libdjinterop składa workflow `.github/workflows/njr-konwerter-build.yml`, a `editor/njr.spec` pakuje ją tylko gdy leży w `editor/engine_bridge/build/Release/njr-engine-export.exe` albo `editor/engine_bridge/build/njr-engine-export.exe`.

Przy przenoszeniu na Windows trzeba złożyć tę binarkę przed PyInstallerem. Inaczej kolejny `.exe` znowu będzie bez Engine.

## 4. Konto, identyfikator instalacji i dziennik lądują w ścieżce Maca

Wszystkie trzy robią `Path.home() / "Library" / "Application Support" / "NJR Konwerter"`:

- `editor/njr_account.py`, `account_dir` (około 37) — `install-id` i `account-session.json`
- `editor/app.py`, `_converter_install_id` (około 9052) — drugi odczyt tego samego pliku, link „kup tokeny” w `_token_shop`
- `editor/app.py`, `_action_log` (około 7568) — `logs\dzialania.jsonl`

Na Windowsie powstaje `C:\Users\<nazwa>\Library\Application Support\NJR Konwerter`. Działa, tylko nie tam, gdzie reszta programu. Kopie zapasowe są już w `%APPDATA%\NJR Konwerter\backups` (`dj_libraries.backup_root`). Aktualizacje są w `%LOCALAPPDATA%\NJR-Konwerter\updates` (`updater.updates_dir`).

Jedno miejsce na Windows: `%APPDATA%\NJR Konwerter`, z podfolderami `backups`, `logs`, `updates`.

## 5. Kosz przy scalaniu duplikatów nie działa

`editor/session_trash.py`, `move_file_to_system_trash` (około 68).

Na Windowsie funkcja importuje `send2trash`. Pakietu nie ma w `editor/requirements.txt` ani w złożonym pliku. Usunięcie pliku przy scalaniu duplikatu kończy się: „Brak obsługi kosza systemowego na Windows”. Przywracanie z kosza na Windowsie i tak zwraca `False`.

## 6. Rekordbox wczytuje zły XML

`editor/dj_libraries.py`, `_locate_rekordbox` (około 151).

Bierze najnowszy `*.xml` w folderze rekordboxa. Filtr `_is_rekordbox_library_xml` (około 365) odrzuca `automixplaylist6.xml` i `masterplaylists6.xml`, ale `locate` go nie używa.

Na sprawdzonym komputerze wskazany plik to `automixPlaylist6.xml`. Pobranie bazy Rekordbox wczyta automix, nie kolekcję. `masterPlaylists3.xml` też tam leży i też nie jest kolekcją. Do importu nadaje się tylko XML z `DJ_PLAYLISTS`.

## 7. Stemy i czyszczenie Engine Prime są na sztywno pod Maca

Nie wywracają startu. Na Windowsie nie znajdą danych:

- `editor/engine_stems.py` około 533, `editor/engine_disk_cleanup.py` około 22, `editor/scripts/monitor_engine_disk.py` — `Library/Application Support/AIR Music Technology/EnginePrime`
- `editor/engine_stems_render.py` — start i zamknięcie Engine tylko przez `open` / `osascript`, na Windowsie funkcje nic nie robią

## 8. Komunikaty zamykania mówią Cmd+Q

Tekst, nie logika. Na Windowsie ma być zwykłe zamknięcie programu. Miejsca w oknie programu:

- `editor/app.py` około 3231, 3615, 3681, 3838
- `editor/engine_libdjinterop.py` około 99
- `editor/dj_apps_guard.py` około 63 i 147
- `editor/serato_parser.py` około 1648
- `editor/serato_sqlite_read.py` około 264
- `editor/serato_library_sqlite.py` około 948, 2275, 2556

`editor/mac_access.py` jest osłonięte sprawdzeniem Darwin. Zostawić.

## Co na tym pliku już działa

Okno (WebView2), serwer na `127.0.0.1:5050`, wersja, wykrycie Serato, VirtualDJ, Engine, Rekordbox i Traktora, konto (odpowiada, tylko folder z punktu 4). Plik nie jest podpisany — SmartScreen przy pierwszym uruchomieniu zostaje.
