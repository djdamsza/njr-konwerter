#!/usr/bin/env python3
"""
Flask test client script for VDJ Database Editor API.
Tests all major endpoints and reports errors.
"""
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

# Ensure we can import app
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Use test client - don't start server
os.environ.setdefault('FLASK_ENV', 'testing')

from app import app

# Backup ZIP paths to try (in order)
BACKUP_PATHS = [
    Path(__file__).resolve().parent.parent.parent / "virtualdj" / "2026-03-01 20-23 Database Backup.zip",
    Path(__file__).resolve().parent / "test-backup-vdj.zip",
]

def find_backup():
    for p in BACKUP_PATHS:
        if p.exists():
            return str(p)
    return None

def run_test(name, fn):
    """Run a test and capture exceptions."""
    try:
        result = fn()
        return result
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }

def main():
    client = app.test_client()
    errors = []
    loaded = False
    first_file_path = None
    song_count = 0

    # 0. Test API without load (should return 400 with error, not 500)
    search_no_load = client.post("/api/search", json={"query": "", "limit": 10})
    if search_no_load.status_code not in (200, 400):
        errors.append(f"api/search without load: {search_no_load.status_code}")
    else:
        try:
            d = search_no_load.get_json()
            if search_no_load.status_code == 400 and d and d.get("error"):
                print("OK api/search (no load - 400 with error)")
            elif search_no_load.status_code == 200:
                loaded = True  # app had data from previous run
                print("OK api/search (no load - had data)")
            else:
                print("OK api/search (no load)")
        except Exception:
            print("OK api/search (no load)")

    # 1. Load database
    backup_path = find_backup()
    if not backup_path:
        errors.append("No backup ZIP found. Create test-backup-vdj.zip or place backup in virtualdj/")
        print("ERROR: No backup ZIP found")
        for p in BACKUP_PATHS:
            print(f"  Tried: {p}")
        return errors

    print(f"Loading from: {backup_path}")

    # Load via /api/load (POST JSON with path)
    load_res = client.post("/api/load", json={"path": backup_path})
    if load_res.status_code != 200:
        try:
            body = load_res.get_json()
            err = body.get("error", str(load_res.data))
        except Exception:
            err = str(load_res.data)
        errors.append(f"api/load: {load_res.status_code} - {err}")
        print(f"FAIL api/load: {load_res.status_code}")
    else:
        try:
            data = load_res.get_json()
            if not data:
                errors.append("api/load: Empty or invalid JSON response")
            elif data.get("error"):
                errors.append(f"api/load: {data['error']}")
            else:
                loaded = True
                song_count = data.get("count", 0)
                print(f"OK api/load: {song_count} songs")
        except Exception as e:
            errors.append(f"api/load: Invalid JSON - {e}")

    if not loaded:
        # Try load-file as fallback
        with open(backup_path, "rb") as f:
            load_res = client.post("/api/load-file", data={"file": (f, Path(backup_path).name)})
        if load_res.status_code == 200:
            data = load_res.get_json()
            if data and not data.get("error"):
                loaded = True
                song_count = data.get("count", 0)
                print(f"OK api/load-file (fallback): {song_count} songs")

    if not loaded:
        print("Cannot proceed without loaded database")
        return errors

    # 2. Search
    search_res = client.post("/api/search", json={"query": "", "limit": 10})
    if search_res.status_code != 200:
        errors.append(f"api/search: {search_res.status_code}")
    else:
        try:
            data = search_res.get_json()
            if data is None:
                errors.append("api/search: Invalid JSON")
            elif "songs" in data and data["songs"]:
                first_file_path = data["songs"][0].get("FilePath")
            print("OK api/search")
        except Exception as e:
            errors.append(f"api/search: {e}")

    # 3. Tags
    tags_res = client.get("/api/tags?field=User1")
    if tags_res.status_code != 200:
        errors.append(f"api/tags: {tags_res.status_code}")
    else:
        try:
            data = tags_res.get_json()
            if data is None:
                errors.append("api/tags: Invalid JSON")
            else:
                print("OK api/tags")
        except Exception as e:
            errors.append(f"api/tags: {e}")

    # 4. Update-song (need FilePath from search)
    if first_file_path:
        update_res = client.post("/api/update-song", json={
            "FilePath": first_file_path,
            "updates": {"Tags.User1": "#test"}
        })
        if update_res.status_code not in (200, 404):
            errors.append(f"api/update-song: {update_res.status_code}")
        else:
            try:
                data = update_res.get_json()
                if data and data.get("error") and update_res.status_code == 404:
                    pass  # expected if path not found
                print("OK api/update-song")
            except Exception as e:
                errors.append(f"api/update-song: {e}")
    else:
        print("SKIP api/update-song (no FilePath)")

    # 5. Duplicates (focus)
    for method in ["path", "similar"]:
        dup_res = client.get(f"/api/duplicates?method={method}")
        if dup_res.status_code != 200:
            errors.append(f"api/duplicates method={method}: {dup_res.status_code}")
            try:
                body = dup_res.get_json()
                if body:
                    errors.append(f"  -> {body.get('error', body)}")
            except Exception:
                pass
        else:
            try:
                data = dup_res.get_json()
                if data is None:
                    errors.append(f"api/duplicates method={method}: Invalid JSON")
                else:
                    print(f"OK api/duplicates method={method}")
            except Exception as e:
                errors.append(f"api/duplicates method={method}: {e}")

    # 6. Relocate-scan (focus)
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        rel_scan_res = client.post("/api/relocate-scan", json={"searchPaths": [tmpdir]})
    if rel_scan_res.status_code != 200:
        errors.append(f"api/relocate-scan: {rel_scan_res.status_code}")
        try:
            body = rel_scan_res.get_json()
            if body:
                errors.append(f"  -> {body.get('error', body)}")
        except Exception:
            pass
    else:
        try:
            data = rel_scan_res.get_json()
            if data is None:
                errors.append("api/relocate-scan: Invalid JSON")
            else:
                print("OK api/relocate-scan")
        except Exception as e:
            errors.append(f"api/relocate-scan: {e}")

    # 7. Relocate-apply (empty updates - should return 400)
    rel_apply_res = client.post("/api/relocate-apply", json={"updates": []})
    if rel_apply_res.status_code not in (200, 400):
        errors.append(f"api/relocate-apply (empty): {rel_apply_res.status_code}")
    else:
        try:
            data = rel_apply_res.get_json()
            if data is None and rel_apply_res.status_code == 200:
                errors.append("api/relocate-apply: Invalid JSON")
            else:
                print("OK api/relocate-apply (empty)")
        except Exception as e:
            errors.append(f"api/relocate-apply: {e}")

    # 8. Problematic-missing
    pm_res = client.get("/api/problematic-missing")
    if pm_res.status_code != 200:
        errors.append(f"api/problematic-missing: {pm_res.status_code}")
    else:
        try:
            data = pm_res.get_json()
            if data is None:
                errors.append("api/problematic-missing: Invalid JSON")
            else:
                print("OK api/problematic-missing")
        except Exception as e:
            errors.append(f"api/problematic-missing: {e}")

    # 9. Merge-duplicate (need two indices - use 0,1 if we have 2+ songs)
    if song_count >= 2:
        merge_res = client.post("/api/merge-duplicate", json={"removeIdx": 1, "keepIdx": 0})
        if merge_res.status_code not in (200, 400):
            errors.append(f"api/merge-duplicate: {merge_res.status_code}")
        else:
            try:
                data = merge_res.get_json()
                if data and data.get("error") and "duplicate" in data.get("error", "").lower():
                    pass  # may require actual duplicates
                print("OK api/merge-duplicate")
            except Exception as e:
                errors.append(f"api/merge-duplicate: {e}")
    else:
        print("SKIP api/merge-duplicate (need 2+ songs)")

    # 10. Remove-duplicates (empty - should work)
    rem_dup_res = client.post("/api/remove-duplicates", json={"indicesToRemove": []})
    if rem_dup_res.status_code != 200:
        errors.append(f"api/remove-duplicates: {rem_dup_res.status_code}")
    else:
        try:
            data = rem_dup_res.get_json()
            if data is None:
                errors.append("api/remove-duplicates: Invalid JSON")
            else:
                print("OK api/remove-duplicates")
        except Exception as e:
            errors.append(f"api/remove-duplicates: {e}")

    # 11. Export VDJ (download)
    dl_res = client.get("/api/download")
    if dl_res.status_code != 200:
        errors.append(f"api/download: {dl_res.status_code}")
    else:
        ct = dl_res.headers.get("Content-Type", "")
        if "xml" in ct or "zip" in ct or "octet" in ct:
            print("OK api/download (VDJ)")
        else:
            errors.append(f"api/download: unexpected Content-Type {ct}")

    # 12. Export RB
    rb_res = client.get("/api/export-rb")
    if rb_res.status_code != 200:
        errors.append(f"api/export-rb: {rb_res.status_code}")
        try:
            body = rb_res.get_json()
            if body:
                errors.append(f"  -> {body.get('error', body)}")
        except Exception:
            pass
    else:
        ct = rb_res.headers.get("Content-Type", "")
        if "xml" in ct or "octet" in ct:
            print("OK api/export-rb")
        else:
            errors.append(f"api/export-rb: unexpected Content-Type {ct}")

    # 13. Export Serato
    ser_res = client.get("/api/export-serato")
    if ser_res.status_code != 200:
        errors.append(f"api/export-serato: {ser_res.status_code}")
        try:
            body = ser_res.get_json()
            if body:
                errors.append(f"  -> {body.get('error', body)}")
        except Exception:
            pass
    else:
        ct = ser_res.headers.get("Content-Type", "")
        if "zip" in ct or "octet" in ct:
            print("OK api/export-serato")
        else:
            errors.append(f"api/export-serato: unexpected Content-Type {ct}")

    # 14. Export RB (DJXML-style - export-djxml)
    djxml_res = client.get("/api/export-djxml")
    if djxml_res.status_code != 200:
        errors.append(f"api/export-djxml: {djxml_res.status_code}")
    else:
        ct = djxml_res.headers.get("Content-Type", "")
        if "xml" in ct or "octet" in ct:
            print("OK api/export-djxml")
        else:
            errors.append(f"api/export-djxml: unexpected Content-Type {ct}")

    # 15. Backup (focus)
    backup_res = client.get("/api/backup")
    if backup_res.status_code != 200:
        errors.append(f"api/backup: {backup_res.status_code}")
    else:
        ct = backup_res.headers.get("Content-Type", "")
        if "zip" in ct or "octet" in ct:
            print("OK api/backup")
        else:
            errors.append(f"api/backup: unexpected Content-Type {ct}")

    # 16. Encoding fixes
    enc_res = client.get("/api/encoding-fixes?field=both")
    if enc_res.status_code != 200:
        errors.append(f"api/encoding-fixes: {enc_res.status_code}")
    else:
        try:
            data = enc_res.get_json()
            if data is None:
                errors.append("api/encoding-fixes: Invalid JSON")
            else:
                print("OK api/encoding-fixes")
        except Exception as e:
            errors.append(f"api/encoding-fixes: {e}")

    # 17. Apply encoding fixes (empty changes)
    enc_apply_res = client.post("/api/apply-encoding-fixes", json={"changes": []})
    if enc_apply_res.status_code != 200:
        errors.append(f"api/apply-encoding-fixes: {enc_apply_res.status_code}")
    else:
        try:
            data = enc_apply_res.get_json()
            if data is None or "applied" not in data:
                errors.append("api/apply-encoding-fixes: Invalid JSON")
            else:
                print("OK api/apply-encoding-fixes")
        except Exception as e:
            errors.append(f"api/apply-encoding-fixes: {e}")

    # 18. Clean title suggestions
    clean_res = client.get("/api/clean-title-suggestions?pattern=all&field=title")
    if clean_res.status_code != 200:
        errors.append(f"api/clean-title-suggestions: {clean_res.status_code}")
    else:
        try:
            data = clean_res.get_json()
            if data is None:
                errors.append("api/clean-title-suggestions: Invalid JSON")
            else:
                print("OK api/clean-title-suggestions")
        except Exception as e:
            errors.append(f"api/clean-title-suggestions: {e}")

    # 19. Remixes (same title, different artists)
    rem_res = client.get("/api/remixes")
    if rem_res.status_code != 200:
        errors.append(f"api/remixes: {rem_res.status_code}")
    else:
        try:
            data = rem_res.get_json()
            if data is None:
                errors.append("api/remixes: Invalid JSON")
            else:
                print("OK api/remixes")
        except Exception as e:
            errors.append(f"api/remixes: {e}")

    # 20. Normalize suggestions
    norm_res = client.get("/api/normalize-suggestions")
    if norm_res.status_code != 200:
        errors.append(f"api/normalize-suggestions: {norm_res.status_code}")
    else:
        try:
            data = norm_res.get_json()
            if data is None:
                errors.append("api/normalize-suggestions: Invalid JSON")
            else:
                print("OK api/normalize-suggestions")
        except Exception as e:
            errors.append(f"api/normalize-suggestions: {e}")

    # 21. Split author-title suggestions
    split_res = client.get("/api/split-author-title-suggestions")
    if split_res.status_code != 200:
        errors.append(f"api/split-author-title-suggestions: {split_res.status_code}")
    else:
        try:
            data = split_res.get_json()
            if data is None:
                errors.append("api/split-author-title-suggestions: Invalid JSON")
            else:
                print("OK api/split-author-title-suggestions")
        except Exception as e:
            errors.append(f"api/split-author-title-suggestions: {e}")

    # 22. Playlists
    pl_res = client.get("/api/playlists")
    if pl_res.status_code != 200:
        errors.append(f"api/playlists: {pl_res.status_code}")
    else:
        try:
            data = pl_res.get_json()
            if data is None:
                errors.append("api/playlists: Invalid JSON")
            else:
                pl_names = [p["name"] for p in data.get("playlists", [])[:3]]
                print("OK api/playlists")
                if pl_names:
                    # 23. Playlist tracks (first playlist)
                    pt_res = client.get(f"/api/playlist-tracks?name={quote(pl_names[0])}")
                    if pt_res.status_code not in (200, 404):
                        errors.append(f"api/playlist-tracks: {pt_res.status_code}")
                    else:
                        print("OK api/playlist-tracks")
        except Exception as e:
            errors.append(f"api/playlists: {e}")

    # 24. Tags-all
    tags_all_res = client.get("/api/tags-all")
    if tags_all_res.status_code != 200:
        errors.append(f"api/tags-all: {tags_all_res.status_code}")
    else:
        try:
            data = tags_all_res.get_json()
            if data is None:
                errors.append("api/tags-all: Invalid JSON")
            else:
                print("OK api/tags-all")
        except Exception as e:
            errors.append(f"api/tags-all: {e}")

    # 25. Tracks-by-tags
    tbt_res = client.post("/api/tracks-by-tags", json={"tags": ["#test"], "field": "User1"})
    if tbt_res.status_code != 200:
        errors.append(f"api/tracks-by-tags: {tbt_res.status_code}")
    else:
        try:
            data = tbt_res.get_json()
            if data is None:
                errors.append("api/tracks-by-tags: Invalid JSON")
            else:
                print("OK api/tracks-by-tags")
        except Exception as e:
            errors.append(f"api/tracks-by-tags: {e}")

    # 26. Status
    status_res = client.get("/api/status")
    if status_res.status_code != 200:
        errors.append(f"api/status: {status_res.status_code}")
    else:
        try:
            data = status_res.get_json()
            if data is None:
                errors.append("api/status: Invalid JSON")
            else:
                print("OK api/status")
        except Exception as e:
            errors.append(f"api/status: {e}")

    # --- Edge cases (should not crash, may return 400/404) ---
    # 27. relocate-apply with invalid idx
    rel_bad = client.post("/api/relocate-apply", json={"updates": [{"idx": 999999, "newPath": "/tmp/x.mp3"}]})
    if rel_bad.status_code not in (200, 400):
        errors.append(f"api/relocate-apply invalid idx: {rel_bad.status_code}")
    else:
        print("OK api/relocate-apply (invalid idx)")

    # 28. apply-clean-title with invalid idx
    clean_apply = client.post("/api/apply-clean-title", json={"changes": [{"idx": 999999, "field": "title", "newValue": "x"}]})
    if clean_apply.status_code not in (200, 400):
        errors.append(f"api/apply-clean-title invalid: {clean_apply.status_code}")
    else:
        print("OK api/apply-clean-title (edge)")

    # 29. apply-normalize with invalid idx
    norm_apply = client.post("/api/apply-normalize", json={"changes": [{"idx": 999999, "field": "title", "newValue": "x"}]})
    if norm_apply.status_code not in (200, 400):
        errors.append(f"api/apply-normalize invalid: {norm_apply.status_code}")
    else:
        print("OK api/apply-normalize (edge)")

    # 30. apply-split-author-title with invalid idx
    split_apply = client.post("/api/apply-split-author-title", json={"changes": [{"idx": 999999, "author": "A", "title": "T"}]})
    if split_apply.status_code not in (200, 400):
        errors.append(f"api/apply-split-author-title invalid: {split_apply.status_code}")
    else:
        print("OK api/apply-split-author-title (edge)")

    # 31. playlist-tracks with non-existent name
    pt_404 = client.get("/api/playlist-tracks?name=NonExistentPlaylistXYZ123")
    if pt_404.status_code not in (200, 404):
        errors.append(f"api/playlist-tracks 404: {pt_404.status_code}")
    else:
        print("OK api/playlist-tracks (404)")

    # 32. load with invalid path
    load_bad = client.post("/api/load", json={"path": "/nonexistent/path/xyz.zip"})
    if load_bad.status_code not in (200, 400, 404, 500):
        errors.append(f"api/load invalid path: {load_bad.status_code}")
    else:
        try:
            d = load_bad.get_json()
            if d and d.get("error"):
                print("OK api/load (invalid path)")
            elif load_bad.status_code in (400, 404, 500):
                print("OK api/load (invalid path)")
            else:
                errors.append("api/load invalid path: expected error response")
        except Exception:
            print("OK api/load (invalid path)")

    return errors

if __name__ == "__main__":
    errors = main()
    print("\n" + "=" * 50)
    if errors:
        print("ERRORS FOUND:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("OK - All tests passed")
        sys.exit(0)
