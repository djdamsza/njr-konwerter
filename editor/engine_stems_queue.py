"""
Kolejka stemów: utwory 1–10 min bez stemów na Patriot → playlista partii w Engine.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running
from file_analyzer import get_audio_channels
from engine_stems import (
    DEFAULT_PATRIOT_ENGINE,
    STEMS_BATCH_PARENT,
    STEMS_BATCH_PLAYLIST,
    _upsert_batch_playlist,
    get_library_uuid,
    list_stem_files,
    match_mac_to_patriot_tracks,
)
from engine_stems_render import batch_playlist_track_ids, resolve_batch_size

DEFAULT_MIN_LENGTH_SEC = 60
DEFAULT_MAX_LENGTH_SEC = 600
MIN_MAC_FREE_GB = 3.0


def _mac_track_meta(mac_engine: Path) -> dict[int, dict]:
    mdb = mac_engine.resolve() / "Database2" / "m.db"
    conn = sqlite3.connect(f"file:{mdb.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        rows = conn.execute(
            """
            SELECT id, path, title, artist, length, isAvailable, isAnalyzed, bitrate, fileBytes
            FROM Track
            """
        ).fetchall()
    finally:
        conn.close()

    out: dict[int, dict] = {}
    for tid, path, title, artist, length, avail, analyzed, br, fb in rows:
        out[int(tid)] = {
            "path": (path or "").replace("\\", "/"),
            "title": title or "",
            "artist": artist or "",
            "length": int(length or 0),
            "is_available": bool(avail),
            "is_analyzed": bool(analyzed),
            "bitrate": br or 0,
            "file_bytes": fb or 0,
        }
    return out


def list_eligible_stem_queue(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    min_length_sec: int = DEFAULT_MIN_LENGTH_SEC,
    max_length_sec: int = DEFAULT_MAX_LENGTH_SEC,
    require_stereo: bool = True,
) -> list[dict]:
    """
    Utwory do kolejnego renderu: dopasowane Mac→Patriot, 1–10 min, brak stemów na Patriot.
    Engine DJ wymaga stereo — mono są pomijane (require_stereo=True).
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    mac_uuid = get_library_uuid(mac_engine)
    mac_stems = set(list_stem_files(mac_engine, library_uuid=mac_uuid))
    pat_stems = set(list_stem_files(patriot_engine, library_uuid=mac_uuid))
    if not pat_stems:
        pat_stems = set(
            list_stem_files(
                patriot_engine, library_uuid=get_library_uuid(patriot_engine)
            )
        )

    id_map = match_mac_to_patriot_tracks(mac_engine, patriot_engine)
    meta = _mac_track_meta(mac_engine)
    eligible: list[dict] = []

    for mac_id, pat_id in id_map.items():
        if pat_id in pat_stems:
            continue
        if mac_id in mac_stems:
            continue
        m = meta.get(mac_id)
        if not m or not m["is_available"]:
            continue
        if not m["is_analyzed"] or not m["bitrate"] or not m["file_bytes"]:
            continue
        length = m["length"]
        if length < min_length_sec or length > max_length_sec:
            continue
        rel = m["path"]
        if not rel:
            continue
        low = rel.lower()
        if any(x in low for x in ("soundcloud", "tidal", "beatport", "beatsource", "://")):
            continue
        abs_path = (mac_engine / rel).resolve()
        if not abs_path.is_file():
            continue
        channels = get_audio_channels(abs_path)
        if require_stereo and channels is not None and channels < 2:
            continue
        eligible.append(
            {
                "mac_track_id": mac_id,
                "patriot_track_id": pat_id,
                "title": m["title"],
                "artist": m["artist"],
                "length_sec": length,
                "channels": channels,
            }
        )

    eligible.sort(key=lambda x: (x["title"].lower(), x["mac_track_id"]))
    return eligible


def list_mono_stem_candidates(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    min_length_sec: int = DEFAULT_MIN_LENGTH_SEC,
    max_length_sec: int = DEFAULT_MAX_LENGTH_SEC,
) -> list[dict]:
    """Mono w kolejce 1–10 min (Engine ich nie renderuje na stemy)."""
    all_candidates = list_eligible_stem_queue(
        mac_engine,
        patriot_engine,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
        require_stereo=False,
    )
    stereo_ids = {
        e["mac_track_id"]
        for e in list_eligible_stem_queue(
            mac_engine,
            patriot_engine,
            min_length_sec=min_length_sec,
            max_length_sec=max_length_sec,
            require_stereo=True,
        )
    }
    return [e for e in all_candidates if e["mac_track_id"] not in stereo_ids]


def stems_queue_status(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int = 250,
    min_length_sec: int = DEFAULT_MIN_LENGTH_SEC,
    max_length_sec: int = DEFAULT_MAX_LENGTH_SEC,
) -> dict:
    eligible = list_eligible_stem_queue(
        mac_engine,
        patriot_engine,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
    )
    mono = list_mono_stem_candidates(
        mac_engine,
        patriot_engine,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
    )
    n = len(eligible)
    batches = (n + batch_size - 1) // batch_size if n else 0
    return {
        "ok": True,
        "eligible_count": n,
        "mono_skipped_count": len(mono),
        "mono_skipped_sample": mono[:10],
        "batch_size": batch_size,
        "batches_remaining": batches,
        "min_length_sec": min_length_sec,
        "max_length_sec": max_length_sec,
        "length_filter": "1–10 min",
        "sample_next": eligible[:5],
    }


def prepare_duration_stems_batch(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int = 250,
    min_length_sec: int = DEFAULT_MIN_LENGTH_SEC,
    max_length_sec: int = DEFAULT_MAX_LENGTH_SEC,
) -> dict:
    """Tworzy playlistę NJR / NJR Stems Batch z kolejną partią (1–10 min)."""
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    if is_engine_desktop_running():
        raise RuntimeError(
            "Zamknij Engine DJ (Cmd+Q) na chwilę — skrypt zapisze playlistę partii w m.db."
        )

    if not patriot_engine.is_dir():
        return {"ok": False, "error": f"Brak Patriot: {patriot_engine}"}

    eligible = list_eligible_stem_queue(
        mac_engine,
        patriot_engine,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
    )
    if not eligible:
        return {
            "ok": True,
            "message": "Kolejka pusta — wszystkie utwory 1–10 min mają stemy na Patriot.",
            "track_count": 0,
        }

    batch = eligible[: max(1, batch_size)]
    batch_ids = [e["mac_track_id"] for e in batch]
    pl = _upsert_batch_playlist(mac_engine, STEMS_BATCH_PLAYLIST, batch_ids)
    status = stems_queue_status(
        mac_engine,
        patriot_engine,
        batch_size=batch_size,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
    )

    return {
        "ok": True,
        "playlist": f"{STEMS_BATCH_PARENT} / {STEMS_BATCH_PLAYLIST}",
        "track_count": len(batch_ids),
        "track_ids": batch_ids,
        "queue_after_this_batch": max(status["eligible_count"] - len(batch_ids), 0),
        "batches_remaining_after": max(status["batches_remaining"] - 1, 0),
        **pl,
        "next_steps": [
            "Upewnij się, że działa: python3 scripts/auto_stems_to_patriot.py watch",
            "Otwórz Engine DJ → „NJR / NJR Stems Batch”.",
            "Cmd+A → Create stems (tylko ta playlista, nie cała kolekcja!).",
            f"Po renderze: python3 scripts/stems_batch_queue.py prepare (następne {batch_size}).",
        ],
    }


def batch_complete_on_patriot(
    mac_engine: Path,
    patriot_engine: Path,
    mac_track_ids: list[int],
) -> dict:
    """True gdy wszystkie utwory partii mają .stems na Patriot."""
    if not mac_track_ids:
        return {"complete": True, "done": 0, "total": 0, "missing_mac_ids": []}

    mac_engine = mac_engine.resolve()
    patriot_engine = patriot_engine.resolve()
    id_map = match_mac_to_patriot_tracks(mac_engine, patriot_engine)
    mac_uuid = get_library_uuid(mac_engine)
    pat_stems = list_stem_files(patriot_engine, library_uuid=mac_uuid)
    if not pat_stems:
        pat_stems = list_stem_files(
            patriot_engine, library_uuid=get_library_uuid(patriot_engine)
        )

    done = 0
    missing: list[int] = []
    for mac_id in mac_track_ids:
        pat_id = id_map.get(mac_id)
        if pat_id is not None and pat_id in pat_stems:
            done += 1
        else:
            missing.append(mac_id)

    return {
        "complete": len(missing) == 0,
        "done": done,
        "total": len(mac_track_ids),
        "missing_mac_ids": missing[:20],
    }


def run_stems_batch_loop(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int = 250,
    min_length_sec: int = DEFAULT_MIN_LENGTH_SEC,
    max_length_sec: int = DEFAULT_MAX_LENGTH_SEC,
    poll_sec: float = 45.0,
    max_batches: int = 0,
    auto_create_stems: bool = True,
    force_batch: bool = False,
    on_progress: callable | None = None,
) -> dict:
    """
    Pętla: czekaj na koniec partii na Patriot → przygotuj następną → Engine Create stems.

    Uruchom w osobnym terminalu (watcher może być w tym samym procesie przez ensure).
  Ctrl+C = stop.
    """
    import time

    from engine_stems import _disk_free_gb, stems_migration_status
    from engine_stems_render import (
        launch_engine_desktop,
        quit_engine_desktop,
        resolve_batch_size,
        trigger_create_stems_ui,
    )

    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    requested_batch = batch_size
    batch_size = resolve_batch_size(
        batch_size, _disk_free_gb(mac_engine), force=force_batch
    )

    batches_done = 0
    history: list[dict] = []

    def _log(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        else:
            print(msg, flush=True)

    _log(
        "Pętla partii stemów: czekam na Patriot → kolejna partia → Create stems. Ctrl+C = stop."
    )
    if requested_batch != batch_size:
        _log(
            f"Partia {requested_batch} → {batch_size} "
            f"(limit wg wolnego miejsca na Macu)."
        )

    try:
        while True:
            if max_batches > 0 and batches_done >= max_batches:
                break

            if not patriot_engine.is_dir():
                _log(f"⚠ Brak Patriot — czekam {poll_sec}s…")
                time.sleep(poll_sec)
                continue

            free_gb = _disk_free_gb(mac_engine)
            if free_gb is not None and free_gb < MIN_MAC_FREE_GB:
                _log(
                    f"⚠ Za mało miejsca na Macu ({free_gb} GB wolne, min {MIN_MAC_FREE_GB} GB) "
                    f"— czekam na watcher…"
                )
                time.sleep(poll_sec)
                continue

            batch_size = resolve_batch_size(
                requested_batch, free_gb, force=force_batch
            )

            status = stems_queue_status(
                mac_engine,
                patriot_engine,
                batch_size=batch_size,
                min_length_sec=min_length_sec,
                max_length_sec=max_length_sec,
            )
            if status["eligible_count"] == 0:
                _log("Kolejka pusta — wszystkie stereo 1–10 min mają stemy na Patriot.")
                break

            current_ids = batch_playlist_track_ids(mac_engine)
            if current_ids:
                comp = batch_complete_on_patriot(
                    mac_engine, patriot_engine, current_ids
                )
                if not comp["complete"]:
                    _log(
                        f"Bieżąca partia: {comp['done']}/{comp['total']} na Patriot "
                        f"(czekam na watcher + Engine)…"
                    )
                    time.sleep(poll_sec)
                    continue

            quit_engine_desktop()
            prep = prepare_duration_stems_batch(
                mac_engine,
                patriot_engine,
                batch_size=batch_size,
                min_length_sec=min_length_sec,
                max_length_sec=max_length_sec,
            )
            if not prep.get("track_count"):
                break

            batch_ids = prep.get("track_ids") or []
            batches_done += 1
            _log(
                f"\n=== Partia {batches_done}: {len(batch_ids)} utworów "
                f"(zostaje w kolejce ~{prep.get('queue_after_this_batch', '?')}) ==="
            )

            launch_engine_desktop()
            time.sleep(5)

            if auto_create_stems:
                ui = trigger_create_stems_ui(manual=False)
                if ui.get("ok"):
                    _log(f"Create stems: {ui.get('mode', 'ok')}")
                else:
                    _log(
                        "⚠ Auto Create stems nie zadziałało — kliknij ręcznie: "
                        "NJR / NJR Stems Batch → Cmd+A → Create stems"
                    )
                    if ui.get("error"):
                        _log(f"  ({ui['error']})")
            else:
                _log("→ NJR / NJR Stems Batch → Cmd+A → Create stems")

            while True:
                comp = batch_complete_on_patriot(
                    mac_engine, patriot_engine, batch_ids
                )
                if comp["complete"]:
                    _log(
                        f"✓ Partia {batches_done} na Patriot ({comp['total']} stemów)"
                    )
                    from engine_disk_cleanup import clean_engine_hidden_cache

                    try:
                        cc = clean_engine_hidden_cache(
                            mac_engine,
                            quit_engine=True,
                            remove_library_backup=False,
                        )
                        if (cc.get("removed_gb") or 0) > 0:
                            _log(
                                f"🧹 Cache Engine po partii: −{cc['removed_gb']} GB "
                                f"(wolne {cc.get('mac_free_gb_after')} GB)"
                            )
                    except OSError as ex:
                        _log(f"⚠ Czyszczenie cache Engine: {ex}")
                    history.append(
                        {
                            "batch": batches_done,
                            "track_count": comp["total"],
                            "track_ids": batch_ids[:10],
                        }
                    )
                    break
                _log(
                    f"  Render/migracja: {comp['done']}/{comp['total']} na Patriot…"
                )
                time.sleep(poll_sec)

    except KeyboardInterrupt:
        _log("\nZatrzymano pętlę (Ctrl+C).")

    final = stems_queue_status(
        mac_engine,
        patriot_engine,
        batch_size=batch_size,
        min_length_sec=min_length_sec,
        max_length_sec=max_length_sec,
    )
    return {
        "ok": True,
        "batches_completed": batches_done,
        "history": history,
        "queue_remaining": final.get("eligible_count"),
        "batches_remaining": final.get("batches_remaining"),
    }
