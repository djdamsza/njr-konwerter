#!/usr/bin/env python3
"""Przebudowa crate LINKI w Serato z HTML + path-first mapping."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

LINKI_STEM = "MyLists%%kreatywne listy%%LINKI"
HTML_PATH = Path("/Users/test/Downloads/LINKI.html")
VDJ_LINKI = (
    Path.home()
    / "Library/Application Support/VirtualDJ/MyLists/kreatywne listy.subfolders/LINKI.vdjfolder"
)


def _count_sqlite_assets(stem: str) -> dict:
    out: dict[str, int] = {}
    lib = Path.home() / "Library/Application Support/Serato/Library"
    leaf = stem.split("%%")[-1]
    for name in ("root.sqlite", "tidal.sqlite"):
        db = lib / name
        if not db.is_file():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            total = 0
            for (cid,) in con.execute(
                "SELECT id FROM container WHERE name = ?",
                (leaf,),
            ):
                n = con.execute(
                    "SELECT COUNT(*) FROM container_asset WHERE container_id=?",
                    (cid,),
                ).fetchone()[0]
                total += int(n)
            if total:
                out[name] = total
        finally:
            con.close()
    return out


def main() -> int:
    import shutil

    from serato_offline import build_serato_offline_substitutes
    from serato_parser import (
        install_serato_playlists_from_tree,
        keep_existing_local_crate_paths,
        load_serato_crate,
    )
    from serato_library_sqlite import clear_container_assets_for_crate_stem, sync_grow_crate_flat_alias
    from unified_model import Playlist
    from vdj_parser import load_database
    from vdj_linked_tracks import (
        match_html_rows_to_local_paths,
        parse_vdj_library_html_export,
    )
    from vdjfolder import create_vdjfolder_playlist, normalize_path
    from vdj_streaming import is_serato_tidal_path

    errors: list[str] = []

    if not HTML_PATH.is_file():
        errors.append(f"Brak HTML: {HTML_PATH}")
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1

    rows = parse_vdj_library_html_export(HTML_PATH)
    songs, version = load_database(
        Path.home() / "Library/Application Support/VirtualDJ/database.xml"
    )
    subs, sub_stats = build_serato_offline_substitutes(songs)
    paths, match_stats = match_html_rows_to_local_paths(
        rows,
        songs,
        path_substitutes=subs,
        include_tidal=True,
    )

    local_paths = [p for p in paths if not is_serato_tidal_path(p)]
    tidal_paths = [p for p in paths if is_serato_tidal_path(p)]
    local_existing = keep_existing_local_crate_paths(local_paths)

    missing_local = len(local_paths) - len(local_existing)
    if missing_local:
        errors.append(f"{missing_local} ścieżek lokalnych nie istnieje na dysku")

    # Backup + zapis vdjfolder (snapshot jak w VDJ)
    if VDJ_LINKI.is_file():
        bak = VDJ_LINKI.with_suffix(".vdjfolder.rebuild-bak")
        shutil.copy2(VDJ_LINKI, bak)
    vdj_xml = create_vdjfolder_playlist(paths, name="LINKI")
    VDJ_LINKI.parent.mkdir(parents=True, exist_ok=True)
    VDJ_LINKI.write_text(vdj_xml, encoding="utf-8")

    serato_dir = Path.home() / "Music" / "_Serato_"
    crate_path = serato_dir / "Subcrates" / f"{LINKI_STEM}.crate"
    stale_flat = serato_dir / "Subcrates" / "LINKI.crate"
    if stale_flat.is_file():
        try:
            stale_flat.unlink()
        except OSError as e:
            errors.append(f"Nie usunięto starego LINKI.crate: {e}")

    before_sqlite = _count_sqlite_assets(LINKI_STEM)
    if crate_path.is_file():
        try:
            crate_path.unlink()
        except OSError as e:
            errors.append(f"Nie usunięto starego crate: {e}")

    clear_stats = clear_container_assets_for_crate_stem(LINKI_STEM)

    linki_pl = Playlist(
        name="LINKI",
        track_ids=paths,
        is_folder=False,
        filter_text="Has Links = 1",
    )
    kreatywne = Playlist(
        name="kreatywne listy",
        track_ids=[],
        is_folder=True,
        children=[linki_pl],
    )
    root = Playlist(
        name="MyLists",
        track_ids=[],
        is_folder=True,
        children=[kreatywne],
    )

    install_stats = install_serato_playlists_from_tree(
        [root],
        serato_dir,
        drive_root="/",
        path_style="relative",
        songs=songs,
        merge_database=True,
        remove_smart_crates=False,
    )
    flat_alias_stats = sync_grow_crate_flat_alias(
        LINKI_STEM,
        local_existing + tidal_paths,
        serato_dir=serato_dir,
        drive_root="/",
        path_style="relative",
        path_substitutes=subs,
    )
    if install_stats.get("error"):
        errors.append(str(install_stats["error"]))

    after_sqlite = _count_sqlite_assets(LINKI_STEM)

    crate_local = 0
    crate_all = 0
    crate_missing: list[str] = []
    if crate_path.is_file():
        pl = load_serato_crate(crate_path.read_bytes(), "LINKI", drive_root="/")
        for tp in pl.track_ids or []:
            crate_all += 1
            if is_serato_tidal_path(tp):
                continue
            if Path(tp).is_file() or (tp.startswith("/") and Path(tp).is_file()):
                crate_local += 1
            else:
                crate_missing.append(tp)

    report = {
        "ok": not errors,
        "vdj_version": version,
        "html_rows": len(rows),
        "match_stats": match_stats,
        "substitute_stats": {
            k: sub_stats[k]
            for k in (
                "mapping",
                "tidal_njr_download",
                "tidal_link_local",
                "tidal_streaming",
                "cache_njr_download",
                "manifest_entries",
                "tid_link_index",
            )
            if k in sub_stats
        },
        "paths_total": len(paths),
        "paths_local": len(local_paths),
        "paths_local_existing": len(local_existing),
        "paths_tidal": len(tidal_paths),
        "crate_file": str(crate_path),
        "crate_tracks_in_file": crate_all,
        "crate_local_in_file": crate_local,
        "crate_tidal_in_file": crate_all - crate_local,
        "sqlite_before": before_sqlite,
        "sqlite_after": after_sqlite,
        "clear_stats": clear_stats,
        "install_ok": install_stats.get("ok"),
        "grow_merged": install_stats.get("grow_crates_merged"),
        "flat_alias": flat_alias_stats,
        "errors": errors,
        "missing_local_samples": crate_missing[:10],
        "unmatched_html": match_stats.get("unmatched", 0),
    }

    out = EDITOR / "linki_rebuild_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nRaport: {out}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
