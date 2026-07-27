"""
Automatyczny render stemów Engine DJ + migracja na Patriot.

Engine DJ nie ma publicznego API CLI do stemów. Ten moduł:
1. przygotowuje playlistę partii (engine_stems.prepare_stems_batch_playlist),
2. uruchamia Engine DJ i próbuje wywołać „Create stems” (AppleScript / ręcznie),
3. czeka na pliki ``{trackId} {uuid}.stems`` w ``Stems/``,
4. zamyka Engine i woła migrate_stems_to_patriot.

Wymaga jednorazowego nadania Terminalowi/Cursorowi dostępu
„Dostępność” (System Events) dla trybu --auto-ui.
"""
from __future__ import annotations

import platform
import sqlite3
import subprocess
import time
from pathlib import Path

from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running
from engine_stems import (
    DEFAULT_PATRIOT_ENGINE,
    STEMS_BATCH_PARENT,
    STEMS_BATCH_PLAYLIST,
    get_library_uuid,
    infer_library_uuid_from_stems,
    list_stem_files,
    match_mac_to_patriot_tracks,
    migrate_stems_to_patriot,
    prepare_stems_batch_playlist,
    stems_migration_status,
)

ENGINE_APP_NAME = "Engine DJ"
MIN_STEM_BYTES = 100_000
STEM_SIZE_STABLE_CHECKS = 3
STEM_SIZE_STABLE_INTERVAL_SEC = 4.0
CREATE_STEMS_MENU_CANDIDATES = [
    ("Track", "Create Stems"),
    ("Track", "Create stems"),
    ("Ścieżka", "Utwórz stemy"),
    ("Ścieżka", "Create Stems"),
    ("Utwór", "Utwórz stemy"),
]


STEM_HEADROOM_GB = 3.0
AVG_STEM_GB = 0.022  # ~22 MB na utwór (średnia + margines)


def compute_auto_batch_size(free_gb: float | None) -> int:
    """Heurystyka partii wg wolnego miejsca na Macu (GB)."""
    if free_gb is None:
        return 10
    usable = max(0.0, free_gb - STEM_HEADROOM_GB)
    by_formula = int(usable / AVG_STEM_GB)
    by_formula = max(3, min(25, by_formula))
    if free_gb >= 28:
        return min(25, by_formula)
    if free_gb >= 20:
        return min(20, by_formula)
    if free_gb >= 14:
        return min(15, by_formula)
    if free_gb >= 10:
        return min(10, by_formula)
    if free_gb >= 6:
        return min(5, by_formula)
    return min(3, by_formula)


def resolve_batch_size(
    requested: int | None,
    free_gb: float | None,
    *,
    cap: int = 250,
    force: bool = False,
) -> int:
    """Partia z limitem dysku — ``--batch 250`` nie może przekroczyć tego, co zmieści Mac."""
    auto = compute_auto_batch_size(free_gb)
    want = requested if requested is not None else min(cap, auto)
    if force:
        return max(1, want)
    return max(1, min(want, auto, cap))


def watcher_poll_sec(free_gb: float | None, default: float = 20.0) -> float:
    """Krótszy poll watchera przy małym wolnym miejscu na Macu."""
    if free_gb is None:
        return default
    if free_gb < 6:
        return 5.0
    if free_gb < 10:
        return 10.0
    return default


def _auto_clean_engine_cache(mac_engine: Path, log_fn: callable, *, force: bool = False) -> None:
    """
    Workaround: Engine DJ nie czyści temp po stemach (bug od 12/2024).
    https://community.enginedj.com/t/engine-desktop-not-cleaning-temp-files-after-stem-processing-on-mac/60940
    """
    from engine_disk_cleanup import clean_engine_hidden_cache, scan_engine_disk_usage
    from engine_stems import _disk_free_gb

    free = _disk_free_gb(mac_engine)
    scan = scan_engine_disk_usage(mac_engine)
    cache_gb = scan.get("cache_gb") or 0
    if not force and cache_gb < 0.25 and free is not None and free >= 12:
        return
    try:
        out = clean_engine_hidden_cache(
            mac_engine,
            quit_engine=False,
            remove_library_backup=False,
            empty_trash=False,
        )
        freed = out.get("removed_gb") or 0
        if freed > 0.01:
            log_fn(
                f"🧹 Cache Engine DJ (bug Denon): −{freed} GB "
                f"(wolne {out.get('mac_free_gb_after')} GB)"
            )
    except OSError as ex:
        log_fn(f"⚠ Czyszczenie cache Engine: {ex}")


def batch_playlist_track_ids(mac_engine: Path | None = None) -> list[int]:
    """Track ID z playlisty NJR / NJR Stems Batch."""
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    mdb = mac_engine / "Database2" / "m.db"
    conn = sqlite3.connect(str(mdb))
    try:
        row = conn.execute(
            """
            SELECT p.id
            FROM Playlist p
            JOIN Playlist parent ON parent.id = p.parentListId
            WHERE p.title = ? AND parent.title = ?
            LIMIT 1
            """,
            (STEMS_BATCH_PLAYLIST, STEMS_BATCH_PARENT),
        ).fetchone()
        if not row:
            return []
        list_id = int(row[0])
        rows = conn.execute(
            "SELECT trackId FROM PlaylistEntity WHERE listId = ? ORDER BY id",
            (list_id,),
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        conn.close()


def _stem_path(engine_dir: Path, track_id: int, library_uuid: str) -> Path:
    return engine_dir / "Stems" / f"{track_id} {library_uuid}.stems"


def wait_for_stems_files(
    mac_engine: Path,
    track_ids: list[int],
    *,
    library_uuid: str | None = None,
    timeout_sec: float = 7200,
    poll_sec: float = 5.0,
    min_bytes: int = MIN_STEM_BYTES,
) -> dict:
    """
    Czeka aż każdy track_id dostanie gotowy plik .stems (stabilny rozmiar).
    """
    mac_engine = mac_engine.resolve()
    library_uuid = library_uuid or get_library_uuid(mac_engine)
    pending = {int(t) for t in track_ids}
    ready: dict[int, dict] = {}
    stable_hits: dict[int, int] = {}
    last_sizes: dict[int, int] = {}
    deadline = time.time() + max(60.0, timeout_sec)
    per_track_timeout = max(300.0, timeout_sec / max(len(track_ids), 1) * 1.5)
    track_deadlines = {tid: time.time() + per_track_timeout for tid in pending}

    while pending and time.time() < deadline:
        for tid in list(pending):
            path = _stem_path(mac_engine, tid, library_uuid)
            if not path.is_file():
                stable_hits[tid] = 0
                continue
            size = path.stat().st_size
            if size < min_bytes:
                stable_hits[tid] = 0
                last_sizes[tid] = size
                continue
            if last_sizes.get(tid) == size:
                stable_hits[tid] = stable_hits.get(tid, 0) + 1
            else:
                stable_hits[tid] = 0
                last_sizes[tid] = size
            if stable_hits[tid] >= STEM_SIZE_STABLE_CHECKS:
                ready[tid] = {"path": str(path), "bytes": size}
                pending.discard(tid)
            elif time.time() > track_deadlines.get(tid, deadline):
                pending.discard(tid)
        if pending:
            time.sleep(max(1.0, poll_sec))
            if int(time.time()) % int(max(30, poll_sec * 6)) == 0:
                # co ~30s odśwież per-track deadline dla wolnych renderów
                for tid in list(pending):
                    if tid not in last_sizes:
                        track_deadlines[tid] = time.time() + per_track_timeout

    return {
        "ok": len(pending) == 0,
        "expected": len(track_ids),
        "ready_count": len(ready),
        "missing_track_ids": sorted(pending),
        "ready": ready,
        "timed_out": time.time() >= deadline,
    }


def launch_engine_desktop(*, wait_ready_sec: float = 45.0) -> dict:
    if platform.system() != "Darwin":
        return {"ok": False, "error": "Automatyczny render Engine DJ jest tylko na macOS."}
    if is_engine_desktop_running():
        return {"ok": True, "already_running": True}
    subprocess.run(["open", "-a", ENGINE_APP_NAME], check=False)
    deadline = time.time() + wait_ready_sec
    while time.time() < deadline:
        if is_engine_desktop_running():
            time.sleep(3.0)
            return {"ok": True, "already_running": False}
        time.sleep(0.5)
    return {"ok": False, "error": f"{ENGINE_APP_NAME} nie wystartował w {wait_ready_sec}s"}


def quit_engine_desktop(*, wait_sec: float = 45.0) -> dict:
    if platform.system() != "Darwin":
        return {"ok": True, "skipped": True}
    if not is_engine_desktop_running():
        return {"ok": True, "was_running": False}
    subprocess.run(
        ["osascript", "-e", f'tell application "{ENGINE_APP_NAME}" to quit'],
        check=False,
        capture_output=True,
        text=True,
    )
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not is_engine_desktop_running():
            return {"ok": True, "was_running": True}
        time.sleep(0.5)
    return {
        "ok": False,
        "error": f"{ENGINE_APP_NAME} nadal działa po {wait_sec}s — zamknij ręcznie (Cmd+Q).",
    }


def _applescript_create_stems(parent: str, playlist: str) -> str:
    menu_block = "\n".join(
        f'    try\n'
        f'      click menu bar item "{menu}" of menu bar 1\n'
        f'      click menu item "{item}" of menu 1 of menu bar item "{menu}" of menu bar 1\n'
        f'      set clickedMenu to true\n'
        f'    end try'
        for menu, item in CREATE_STEMS_MENU_CANDIDATES
    )
    return f'''
on run
  set parentName to {parent!r}
  set playlistName to {playlist!r}
  tell application "{ENGINE_APP_NAME}" to activate
  delay 2
  tell application "System Events"
    tell process "{ENGINE_APP_NAME}"
      set frontmost to true
      delay 0.8
      set clickedPlaylist to false
      try
        set rootGroups to every UI element of window 1
        repeat with g in rootGroups
          try
            set rows to every row of g
            repeat with r in rows
              try
                set rowText to value of r as text
                if rowText contains playlistName then
                  select r
                  perform action "AXPress" of r
                  set clickedPlaylist to true
                  exit repeat
                end if
              end try
            end repeat
          end try
          if clickedPlaylist then exit repeat
        end repeat
      end try
      if not clickedPlaylist then
        keystroke "f" using {{command down}}
        delay 0.3
        keystroke playlistName
        delay 0.8
        keystroke return
        delay 1.0
      end if
      keystroke "a" using command down
      delay 0.4
      set clickedMenu to false
{menu_block}
      if not clickedMenu then error "Nie znaleziono menu Create Stems"
    end tell
  end tell
end run
'''


def trigger_create_stems_ui(
    *,
    parent: str = STEMS_BATCH_PARENT,
    playlist: str = STEMS_BATCH_PLAYLIST,
    manual: bool = False,
) -> dict:
    if manual:
        return {
            "ok": True,
            "mode": "manual",
            "instructions": [
                f'Otwórz {ENGINE_APP_NAME} → „{parent} / {playlist}”.',
                "Zaznacz utwory (Cmd+A).",
                "Prawy przycisk → Create stems / Utwórz stemy.",
            ],
        }
    if platform.system() != "Darwin":
        return {"ok": False, "error": "AppleScript tylko na macOS — użyj --manual-render."}
    script = _applescript_create_stems(parent, playlist)
    proc = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "1719" in err or "wspomaganego" in err.lower() or "assistive" in err.lower():
            return {
                "ok": False,
                "error": (
                    "Brak uprawnień Dostępności dla Terminala/Cursor. "
                    "Ustawienia → Prywatność → Dostępność → włącz Terminal (lub Cursor), "
                    "albo uruchom z --manual-render."
                ),
                "stderr": err,
            }
        return {"ok": False, "error": err or "AppleScript Create Stems nie powiódł się."}
    return {"ok": True, "mode": "applescript"}


def render_stems_batch(
    mac_engine: Path | None = None,
    track_ids: list[int] | None = None,
    *,
    manual_ui: bool = False,
    launch_engine: bool = True,
    timeout_sec: float = 7200,
) -> dict:
    """Render partii: Engine DJ + (opcjonalnie) UI + oczekiwanie na pliki .stems."""
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    library_uuid = get_library_uuid(mac_engine)
    track_ids = track_ids or batch_playlist_track_ids(mac_engine)
    if not track_ids:
        return {"ok": False, "error": "Brak utworów w playliście NJR Stems Batch."}

    existing = list_stem_files(mac_engine, library_uuid=library_uuid)
    to_render = [t for t in track_ids if t not in existing or existing[t].stat().st_size < MIN_STEM_BYTES]
    if not to_render:
        return {
            "ok": True,
            "message": "Wszystkie utwory z partii mają już stemy na Macu.",
            "track_ids": track_ids,
            "skipped_render": True,
        }

    if launch_engine:
        launched = launch_engine_desktop()
        if not launched.get("ok"):
            return launched

    ui = trigger_create_stems_ui(manual=manual_ui)
    if not ui.get("ok"):
        return ui

    wait = wait_for_stems_files(
        mac_engine,
        to_render,
        library_uuid=library_uuid,
        timeout_sec=timeout_sec,
    )
    return {
        "ok": wait.get("ok", False),
        "track_ids": track_ids,
        "to_render": to_render,
        "ui": ui,
        "wait": wait,
    }


def run_auto_stems_pipeline(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int | None = None,
    max_batches: int = 0,
    manual_render: bool = False,
    delete_mac: bool = True,
    dry_run: bool = False,
    render_timeout_sec: float = 7200,
) -> dict:
    """
    Pełna pętla: prepare → render → migrate aż skończą się utwory na Patriot
    lub osiągnięto max_batches.
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    if not patriot_engine.is_dir():
        return {"ok": False, "error": f"Brak Patriot: {patriot_engine}"}

    batches: list[dict] = []
    batch_num = 0

    while True:
        status = stems_migration_status(mac_engine, patriot_engine)
        if not status.get("ok"):
            return status
        needing = int(status.get("patriot_tracks_needing_stems") or 0)
        if needing <= 0:
            break
        if max_batches > 0 and batch_num >= max_batches:
            break

        bs = batch_size or compute_auto_batch_size(status.get("mac_free_gb"))
        batch_num += 1

        if is_engine_desktop_running():
            quit = quit_engine_desktop()
            if not quit.get("ok"):
                return quit

        prep = prepare_stems_batch_playlist(
            mac_engine, patriot_engine, batch_size=max(1, bs)
        )
        if not prep.get("ok"):
            return prep
        if int(prep.get("track_count") or 0) == 0:
            break

        track_ids = prep.get("track_ids") or batch_playlist_track_ids(mac_engine)
        batch_record: dict = {
            "batch": batch_num,
            "batch_size": bs,
            "track_count": len(track_ids),
            "track_ids": track_ids,
            "prepare": prep,
        }

        if dry_run:
            mig = migrate_stems_to_patriot(
                mac_engine,
                patriot_engine,
                batch_size=bs,
                delete_mac=delete_mac,
                dry_run=True,
            )
            batch_record["migrate_dry_run"] = mig
            batches.append(batch_record)
            break

        render = render_stems_batch(
            mac_engine,
            track_ids,
            manual_ui=manual_render,
            launch_engine=True,
            timeout_sec=render_timeout_sec,
        )
        batch_record["render"] = render

        quit = quit_engine_desktop()
        batch_record["quit_engine"] = quit
        if not quit.get("ok"):
            batches.append(batch_record)
            return {
                "ok": False,
                "error": quit.get("error"),
                "batches": batches,
                "status": stems_migration_status(mac_engine, patriot_engine),
            }

        mig = migrate_stems_to_patriot(
            mac_engine,
            patriot_engine,
            batch_size=bs,
            delete_mac=delete_mac,
        )
        batch_record["migrate"] = mig
        batches.append(batch_record)

        if not render.get("ok") and not render.get("skipped_render"):
            return {
                "ok": False,
                "error": "Render partii nie zakończył się w czasie.",
                "batches": batches,
                "status": stems_migration_status(mac_engine, patriot_engine),
            }
        if not mig.get("ok"):
            return {
                "ok": False,
                "error": "Migracja stemów nie powiodła się.",
                "batches": batches,
                "status": stems_migration_status(mac_engine, patriot_engine),
            }

    final_status = stems_migration_status(mac_engine, patriot_engine)
    return {
        "ok": True,
        "batches_run": len(batches),
        "batches": batches,
        "status": final_status,
        "patriot_stems_remaining": final_status.get("patriot_tracks_needing_stems"),
        "mac_free_gb": final_status.get("mac_free_gb"),
        "suggested_next_batch": compute_auto_batch_size(final_status.get("mac_free_gb")),
    }


def watch_and_migrate_stems(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    poll_sec: float = 20.0,
    delete_mac: bool = True,
    stop_after_idle_sec: float = 0,
    max_iterations: int = 0,
    on_progress: callable | None = None,
) -> dict:
    """
  Watcher w tle: przenosi gotowe .stems z Maca na Patriot podczas renderu Engine DJ.

  Workflow użytkownika:
  1. Uruchom ``watch`` w terminalu (zostaw włączone).
  2. W Engine DJ zaznacz kolekcję / playlistę → Create stems (może trwać godziny).
  3. Watcher przenosi każdy ukończony plik na Patriot i usuwa z Maca (zwalnia miejsce).

  Ctrl+C aby zatrzymać watcher (render Engine DJ może dalej działać).
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    stable_sizes: dict[str, int] = {}
    totals = {
        "migrated": 0,
        "bytes_moved": 0,
        "errors": 0,
        "polls": 0,
        "db_lock_skips": 0,
    }
    last_migrate_at = time.time()
    iterations = 0
    id_map_loaded_at = 0.0
    ID_MAP_REFRESH_SEC = 300.0
    id_map: dict[int, int] | None = None
    mac_uuid: str | None = None

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            print(msg, flush=True)

    def _load_id_map() -> tuple[dict[int, int] | None, str | None]:
        nonlocal id_map, mac_uuid, id_map_loaded_at
        try:
            mac_u = infer_library_uuid_from_stems(mac_engine / "Stems")
            if not mac_u:
                mac_u = get_library_uuid(mac_engine)
            mapping = match_mac_to_patriot_tracks(mac_engine, patriot_engine)
            id_map = mapping
            mac_uuid = mac_u
            id_map_loaded_at = time.time()
            return mapping, mac_u
        except sqlite3.OperationalError as ex:
            if id_map is not None:
                return id_map, mac_uuid
            raise ex

    _log(
        "Watcher stemów: czekam na gotowe pliki .stems na Macu → Patriot. "
        "W Engine DJ: zaznacz utwory → Create stems. Ctrl+C = stop."
    )

    try:
        id_map, mac_uuid = _load_id_map()
        _log(f"Mapowanie Mac→Patriot: {len(id_map)} utworów.")
    except sqlite3.OperationalError:
        _log(
            "⚠ m.db zablokowane przez Engine DJ — czekam na odblokowanie "
            "(render może trwać, watcher nie padnie)."
        )
        mac_uuid = infer_library_uuid_from_stems(mac_engine / "Stems")
        id_map = None

    try:
        while True:
            iterations += 1
            if max_iterations > 0 and iterations > max_iterations:
                break

            if not patriot_engine.is_dir():
                _log(f"⚠ Brak Patriot ({patriot_engine}) — czekam {poll_sec}s…")
                time.sleep(poll_sec)
                continue

            totals["polls"] += 1

            if id_map is None or time.time() - id_map_loaded_at > ID_MAP_REFRESH_SEC:
                try:
                    id_map, mac_uuid = _load_id_map()
                    if totals["polls"] == 1 or int(time.time()) % 300 < poll_sec:
                        _log(f"Mapowanie Mac→Patriot: {len(id_map)} utworów.")
                except sqlite3.OperationalError:
                    totals["db_lock_skips"] += 1
                    if id_map is None:
                        time.sleep(poll_sec)
                        continue

            try:
                mig = migrate_stems_to_patriot(
                    mac_engine,
                    patriot_engine,
                    delete_mac=delete_mac,
                    allow_engine_running=True,
                    only_stable=True,
                    stable_sizes=stable_sizes,
                    id_map=id_map,
                    mac_library_uuid=mac_uuid,
                )
            except sqlite3.OperationalError as ex:
                totals["db_lock_skips"] += 1
                _log(f"⚠ Baza zablokowana (Engine DJ) — ponowię za {poll_sec}s…")
                time.sleep(poll_sec)
                continue
            except OSError as ex:
                totals["errors"] += 1
                _log(f"⚠ {ex}")
                time.sleep(poll_sec)
                continue

            if mig.get("migrated", 0) > 0:
                totals["migrated"] += mig["migrated"]
                totals["bytes_moved"] += mig.get("bytes_moved", 0)
                last_migrate_at = time.time()
                gb = mig.get("bytes_moved_gb", 0)
                _log(
                    f"✓ Przeniesiono {mig['migrated']} stemów "
                    f"(+{gb} GB, łącznie {totals['migrated']})"
                )
                for item in mig.get("items") or []:
                    _log(f"  → {item.get('dest', '')}")
                _auto_clean_engine_cache(mac_engine, _log, force=True)

            if mig.get("errors"):
                totals["errors"] += len(mig["errors"])
                for err in mig["errors"][:3]:
                    _log(f"⚠ {err}")

            if stop_after_idle_sec > 0:
                idle = time.time() - last_migrate_at
                unstable = int(mig.get("skipped_unstable") or 0)
                if idle >= stop_after_idle_sec and unstable == 0 and mig.get("migrated", 0) == 0:
                    _log(f"Brak aktywności przez {stop_after_idle_sec}s — koniec.")
                    break

            from engine_stems import _disk_free_gb

            free_gb = _disk_free_gb(mac_engine)
            try:
                stems_dir = mac_engine / "Stems"
                mac_stems_gb = round(
                    sum(f.stat().st_size for f in stems_dir.glob("*.stems"))
                    / (1024**3),
                    2,
                )
            except OSError:
                mac_stems_gb = 0.0
            if free_gb is not None and free_gb < 6 and mac_stems_gb > 0.3:
                _log(
                    f"⚠ Mało miejsca ({free_gb} GB wolne, {mac_stems_gb} GB stemów na Macu) "
                    "— przyspieszam migrację…"
                )
            sleep_sec = watcher_poll_sec(free_gb, default=poll_sec)
            if totals["polls"] % 3 == 0:
                _auto_clean_engine_cache(mac_engine, _log)
            time.sleep(max(3.0, sleep_sec))

    except KeyboardInterrupt:
        _log("\nZatrzymano watcher (Ctrl+C).")

    try:
        final_status = stems_migration_status(mac_engine, patriot_engine)
    except OSError:
        final_status = {}

    return {
        "ok": True,
        "totals": {
            **totals,
            "bytes_moved_gb": round(totals["bytes_moved"] / (1024**3), 3),
        },
        "status": final_status,
        "patriot_stems_count": final_status.get("patriot_stems_count"),
        "patriot_tracks_needing_stems": final_status.get("patriot_tracks_needing_stems"),
    }
