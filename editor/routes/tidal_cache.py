"""API: Tidal Cache → Serato (skan, pobieranie, manifest)."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

import app_state as st
from native_dialogs import pick_folder_native
from tidal_download import (
    delete_manifest_tracks,
    load_config,
    manifest_tracks,
    output_dir,
    queue_status,
    save_config,
    start_download_batch_async,
    tiddl_tool_status,
)
from tidal_vdj_metadata import (
    apply_vdj_metadata_batch,
    metadata_status,
    start_metadata_batch_async,
)
from vdj_tidal_cache import default_vdj_cache_dir, scan_tidal_cache_entries

bp = Blueprint("tidal_cache", __name__)


def _cache_path_from_request() -> str:
    return (
        (request.args.get("vdjCachePath") or "").strip()
        or (request.get_json(silent=True) or {}).get("vdjCachePath", "").strip()
        or str(default_vdj_cache_dir())
    )


@bp.route("/api/tidal-cache/tool-status", methods=["GET"])
def api_tidal_cache_tool_status():
    return jsonify(tiddl_tool_status())


@bp.route("/api/tidal-cache/config", methods=["GET", "POST"])
def api_tidal_cache_config():
    if request.method == "GET":
        cfg = load_config()
        cfg["manifest_path"] = str(Path.home() / ".config" / "njr" / "tidal-serato" / "manifest.json")
        return jsonify(cfg)
    data = request.get_json() or {}
    out_dir = (data.get("outputDir") or data.get("output_dir") or "").strip()
    if not out_dir:
        return jsonify({"error": "Podaj outputDir"}), 400
    cfg = save_config({"output_dir": out_dir})
    return jsonify({"ok": True, **cfg})


@bp.route("/api/tidal-cache/pick-output", methods=["GET"])
def api_tidal_cache_pick_output():
    path = pick_folder_native()
    if not path:
        return jsonify({"error": "Nie wybrano folderu"}), 400
    cfg = save_config({"output_dir": path})
    return jsonify({"ok": True, "path": path, **cfg})


@bp.route("/api/tidal-cache/scan", methods=["GET"])
def api_tidal_cache_scan():
    st.ensure_loaded()
    vdj_cache = _cache_path_from_request()
    manifest = manifest_tracks()
    result = scan_tidal_cache_entries(
        st.songs,
        vdj_cache_path=vdj_cache,
        manifest_tracks=manifest,
    )
    result["tool"] = tiddl_tool_status()
    result["config"] = load_config()
    result["output_dir"] = str(output_dir())
    return jsonify(result)


@bp.route("/api/tidal-cache/download", methods=["POST"])
def api_tidal_cache_download():
    st.ensure_loaded()
    data = request.get_json() or {}
    tidal_ids = [str(x).strip() for x in (data.get("tidalIds") or []) if str(x).strip()]
    all_cached = bool(data.get("allCached"))

    if queue_status().get("running"):
        return jsonify({"error": "Pobieranie już trwa"}), 409

    vdj_cache = (data.get("vdjCachePath") or "").strip() or str(default_vdj_cache_dir())
    scan = scan_tidal_cache_entries(
        st.songs,
        vdj_cache_path=vdj_cache,
        manifest_tracks=manifest_tracks(),
    )
    entries = scan.get("entries") or []

    if all_cached:
        items = [
            {"tidalId": e["tidalId"], "author": e["author"], "title": e["title"]}
            for e in entries
            if e.get("cached")
            and e.get("downloadStatus") != "downloaded"
            and str(e.get("tidalId") or "").strip().isdigit()
        ]
    elif tidal_ids:
        by_id = {e["tidalId"]: e for e in entries if str(e.get("tidalId") or "").strip()}
        items = []
        for tid in tidal_ids:
            tid = str(tid).strip()
            if not tid.isdigit():
                continue
            e = by_id.get(tid)
            if e and e.get("cached"):
                items.append({"tidalId": tid, "author": e["author"], "title": e["title"]})
    else:
        return jsonify({"error": "Podaj tidalIds lub allCached: true"}), 400

    if not items:
        return jsonify({"ok": True, "queued": 0, "message": "Brak utworów do pobrania"})

    tool = tiddl_tool_status()
    if not tool.get("installed"):
        return jsonify({"error": tool.get("hint")}), 400
    if not tool.get("logged_in"):
        return jsonify({"error": tool.get("hint")}), 400

    start_download_batch_async(items, songs=st.songs)
    return jsonify({"ok": True, "queued": len(items)})


@bp.route("/api/tidal-cache/download-status", methods=["GET"])
def api_tidal_cache_download_status():
    return jsonify(queue_status())


@bp.route("/api/tidal-cache/delete", methods=["POST"])
def api_tidal_cache_delete():
    data = request.get_json() or {}
    ids = [str(x).strip() for x in (data.get("tidalIds") or []) if str(x).strip()]
    if not ids:
        return jsonify({"error": "Podaj tidalIds"}), 400
    stats = delete_manifest_tracks(ids)
    return jsonify({"ok": True, **stats})


@bp.route("/api/tidal-cache/apply-metadata", methods=["POST"])
def api_tidal_cache_apply_metadata():
    """Uzupełnia tagi / BPM / key / rating / hot cues VDJ we wszystkich pobranych plikach."""
    st.ensure_loaded()
    data = request.get_json(silent=True) or {}
    if metadata_status().get("running"):
        return jsonify({"error": "Uzupełnianie metadanych już trwa"}), 409
    if queue_status().get("running"):
        return jsonify({"error": "Poczekaj aż zakończy się pobieranie"}), 409

    async_mode = str(data.get("async", "1")).strip().lower() not in ("0", "false", "no")
    only_missing = str(data.get("onlyMissing", "0")).strip().lower() not in ("0", "false", "no")

    if async_mode:
        total = start_metadata_batch_async(st.songs, only_missing=only_missing)
        return jsonify({
            "ok": True,
            "started": True,
            "total": total,
            "message": f"Uzupełnianie metadanych w tle — {total} pobranych plików",
        })

    stats = apply_vdj_metadata_batch(st.songs, only_missing=only_missing)
    return jsonify(stats)


@bp.route("/api/tidal-cache/apply-metadata-status", methods=["GET"])
def api_tidal_cache_apply_metadata_status():
    return jsonify(metadata_status())


@bp.route("/api/tidal-cache/manifest", methods=["GET"])
def api_tidal_cache_manifest():
    return jsonify({"tracks": manifest_tracks(), "config": load_config()})
