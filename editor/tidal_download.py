"""
Pobieranie utworów Tidal (cache VDJ → pliki audio dla Serato).
Wymaga zewnętrznego CLI „tiddl” (pip install tiddl) + tiddl auth login.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, Optional

from vdjfolder import normalize_path
from vdj_streaming import extract_tidal_id

_CONFIG_DIR = Path.home() / ".config" / "njr" / "tidal-serato"
_MANIFEST_NAME = "manifest.json"
_CONFIG_NAME = "config.json"

_lock = threading.Lock()
_queue_state: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "current": None,
    "errors": [],
    "started_at": None,
    "finished_at": None,
}


def config_dir() -> Path:
    d = _CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / _CONFIG_NAME


def manifest_path() -> Path:
    return config_dir() / _MANIFEST_NAME


def default_output_dir() -> Path:
    return Path.home() / "Music" / "NJR-Tidal-Serato"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {"output_dir": str(default_output_dir())}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not (data.get("output_dir") or "").strip():
            data["output_dir"] = str(default_output_dir())
        return data
    except (OSError, json.JSONDecodeError):
        return {"output_dir": str(default_output_dir())}


def save_config(data: dict) -> dict:
    cfg = load_config()
    cfg.update(data or {})
    out = (cfg.get("output_dir") or "").strip() or str(default_output_dir())
    cfg["output_dir"] = str(Path(out).expanduser())
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def output_dir() -> Path:
    p = Path(load_config().get("output_dir") or default_output_dir()).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_manifest() -> dict:
    p = manifest_path()
    if not p.exists():
        return {"version": 1, "tracks": {}}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if "tracks" not in data:
            data["tracks"] = {}
        return data
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "tracks": {}}


def save_manifest(data: dict) -> None:
    with _lock:
        with open(manifest_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def manifest_tracks() -> dict[str, dict]:
    return load_manifest().get("tracks") or {}


def manifest_substitutes() -> dict[str, str]:
    """Mapowanie aliasów VDJ → lokalna ścieżka z manifestu."""
    out: dict[str, str] = {}
    for tid, entry in manifest_tracks().items():
        path = (entry.get("path") or "").strip()
        if not path or not Path(path).is_file():
            continue
        for alias in (
            f"netsearch://td{tid}",
            f"td{tid}",
            f"streaming://tidal/{tid}",
            f"tidal:tracks:{tid}",
        ):
            out[normalize_path(alias)] = path
    return out


def _sanitize_filename(part: str) -> str:
    s = unicodedata.normalize("NFC", str(part or "").strip())
    s = re.sub(r'[<>:"/\\|?*]', "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:180] or "unknown"


def _bundled_tiddl_path() -> Optional[Path]:
    p = Path(__file__).resolve().parent / ".venv-tiddl" / "bin" / "tiddl"
    return p if p.is_file() else None


def _tiddl_auth_model_path() -> Optional[Path]:
    bundled = _bundled_tiddl_path()
    if not bundled:
        return None
    venv_root = bundled.parent.parent
    matches = list(venv_root.glob("lib/python*/site-packages/tiddl/models/auth.py"))
    return matches[0] if matches else None


def ensure_tiddl_auth_patch() -> bool:
    """
    tiddl 2.8.0 wymaga facebookUid, którego Tidal już nie zwraca (fix w tiddl 3.4.3+ / Py3.13).
    """
    p = _tiddl_auth_model_path()
    if not p:
        return False
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False
    if "facebookUid: Optional[int] = None" in text:
        return True
    if "facebookUid: int" not in text:
        return False
    try:
        p.write_text(text.replace("facebookUid: int", "facebookUid: Optional[int] = None", 1), encoding="utf-8")
        return True
    except OSError:
        return False


def _tiddl_runs(exe: str) -> bool:
    if exe.endswith(" -m tiddl"):
        cmd = [exe.replace(" -m tiddl", ""), "-m", "tiddl", "--help"]
    else:
        cmd = [exe, "--help"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=12, text=True)
        return r.returncode == 0 and "TIDDL" in (r.stdout or r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_tiddl_executable() -> Optional[str]:
    ensure_tiddl_auth_patch()
    env_exe = (os.environ.get("NJR_TIDDL_PATH") or os.environ.get("TIDDL_PATH") or "").strip()
    if env_exe and Path(env_exe).is_file() and _tiddl_runs(env_exe):
        return env_exe

    bundled = _bundled_tiddl_path()
    if bundled and _tiddl_runs(str(bundled)):
        return str(bundled)

    hit = shutil.which("tiddl")
    if hit and _tiddl_runs(hit):
        return hit

    for p in (
        Path.home() / "Library/Python/3.12/bin/tiddl",
        Path.home() / "Library/Python/3.11/bin/tiddl",
        Path.home() / "Library/Python/3.10/bin/tiddl",
        Path("/opt/homebrew/bin/tiddl"),
        Path("/usr/local/bin/tiddl"),
    ):
        if p.is_file() and _tiddl_runs(str(p)):
            return str(p)

    for py in (
        "/opt/homebrew/bin/python3.12",
        "python3.12",
        "python3.11",
        "python3.10",
    ):
        candidate = f"{py} -m tiddl"
        if _tiddl_runs(candidate):
            return candidate
    return None


def _tiddl_config_path() -> Path:
    env_home = (os.environ.get("TIDDL_PATH") or "").strip()
    base = Path(env_home) if env_home else Path.home()
    return base / "tiddl.json"


def tiddl_logged_in() -> bool:
    """Czy tiddl ma zapisany token (bez ujawniania danych auth)."""
    p = _tiddl_config_path()
    if not p.is_file():
        return False
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        auth = data.get("auth") or {}
        return bool((auth.get("token") or "").strip() and (auth.get("user_id") or "").strip())
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return False


def tiddl_tool_status() -> dict:
    exe = find_tiddl_executable()
    logged_in = bool(exe and tiddl_logged_in())
    if not exe:
        hint = (
            "Uruchom w terminalu: editor/.venv-tiddl/bin/tiddl auth login "
            "(lub: brew install python@3.12 && python3.12 -m venv .venv-tiddl && .venv-tiddl/bin/pip install tiddl)"
        )
    elif not logged_in:
        hint = f"W terminalu uruchom: {exe} auth login — bez tego pobieranie nie zadziała."
    else:
        hint = "Zalogowano — można pobierać utwory z panelu."
    return {
        "installed": bool(exe),
        "logged_in": logged_in,
        "executable": exe or "",
        "hint": hint,
        "login_command": f"{exe} auth login" if exe else "",
    }


def _tiddl_cmd(exe: str, *args: str) -> list[str]:
    if exe.endswith(" -m tiddl"):
        py = exe.replace(" -m tiddl", "")
        return [py, "-m", "tiddl", *args]
    return [exe, *args]


def _parse_tiddl_output(stderr: str, stdout: str) -> Optional[str]:
    text = f"{stderr or ''}\n{stdout or ''}"
    if "not found (404" in text or "404 - 2001" in text:
        return "Usunięty z Tidal (404) — renew DRM nie pomoże; szukaj lokalnego pliku lub pomiń"
    if "login first" in text.lower():
        return "Brak logowania tiddl — uruchom auth login"
    if "403" in text and "forbidden" in text.lower():
        return "Tidal odmówił pobrania (403/DRM)"
    return None


def _run_tiddl_download(tidal_id: str, out_dir: Path, exe: str) -> tuple[Optional[str], Optional[str]]:
    url = f"https://tidal.com/browse/track/{tidal_id}"
    cmd = _tiddl_cmd(exe, "url", url, "download", "-p", str(out_dir), "-q", "high")
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return None, "Timeout pobierania (>10 min)"
    except OSError as e:
        return None, str(e)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        parsed = _parse_tiddl_output(r.stderr or "", r.stdout or "")
        return None, (parsed or err[:500] or f"tiddl exit {r.returncode}")

    # Szukaj nowego pliku audio w out_dir (najnowszy)
    audio_ext = {".flac", ".m4a", ".mp3", ".wav", ".aac"}
    candidates = [
        f for f in out_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in audio_ext
    ]
    if not candidates:
        parsed = _parse_tiddl_output(r.stderr or "", r.stdout or "")
        return None, parsed or "tiddl zakończył się bez pliku audio w folderze docelowym"
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0]), None


def download_track_to_manifest(
    tidal_id: str,
    *,
    author: str = "",
    title: str = "",
    exe: Optional[str] = None,
    out_dir: Optional[Path] = None,
    songs: Optional[list[dict]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Pobiera utwór i aktualizuje manifest. Zwraca (path, error)."""
    tid = str(tidal_id).strip()
    if not tid.isdigit():
        return None, "Nieprawidłowe tidal ID"

    manifest = load_manifest()
    tracks = manifest.setdefault("tracks", {})
    existing = tracks.get(tid, {})
    old_path = (existing.get("path") or "").strip()
    if old_path and Path(old_path).is_file():
        return old_path, None

    exe = exe or find_tiddl_executable()
    if not exe:
        return None, "Brak narzędzia tiddl (pip install tiddl)"

    base = out_dir or output_dir()
    sub = base / _sanitize_filename(author or "Unknown")
    sub.mkdir(parents=True, exist_ok=True)

    path, err = _run_tiddl_download(tid, sub, exe)
    entry = {
        "path": path or old_path,
        "author": author,
        "title": title,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S") if path else existing.get("downloaded_at"),
        "error": err or "",
        "source": "tiddl",
    }
    if path and not err and songs:
        try:
            from tidal_vdj_metadata import apply_vdj_metadata_to_tidal_file

            meta = apply_vdj_metadata_to_tidal_file(
                path, tid, songs,
                author=author,
                title=title,
            )
            if meta.get("ok"):
                entry["metadata_applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                entry["metadata_summary"] = {
                    k: meta.get(k) for k in ("tags", "extended", "cues") if k in meta
                }
            else:
                entry["metadata_error"] = meta.get("reason") or "metadata_failed"
        except Exception as e:
            entry["metadata_error"] = str(e)
    tracks[tid] = entry
    save_manifest(manifest)
    return path, err


def delete_manifest_tracks(tidal_ids: list[str]) -> dict:
    manifest = load_manifest()
    tracks = manifest.get("tracks") or {}
    removed_files = 0
    for tid in tidal_ids:
        tid = str(tid).strip()
        entry = tracks.pop(tid, None)
        if not entry:
            continue
        p = (entry.get("path") or "").strip()
        if p:
            try:
                fp = Path(p)
                if fp.is_file():
                    fp.unlink()
                    removed_files += 1
            except OSError:
                pass
    save_manifest(manifest)
    return {"removed": len(tidal_ids), "files_deleted": removed_files}


def queue_status() -> dict:
    with _lock:
        return dict(_queue_state)


def _set_queue(**kwargs) -> None:
    with _lock:
        _queue_state.update(kwargs)


def run_download_batch(
    items: list[dict],
    *,
    songs: Optional[list[dict]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    items: [{ tidalId, author?, title? }]
    Synchroniczne pobieranie (wywoływane z wątku tła).
    """
    exe = find_tiddl_executable()
    if not exe:
        return {"ok": False, "error": "Brak tiddl — pip install tiddl && tiddl auth login"}
    if not tiddl_logged_in():
        return {"ok": False, "error": f"Brak logowania tiddl — uruchom: {exe} auth login"}

    _set_queue(
        running=True,
        total=len(items),
        done=0,
        current=None,
        errors=[],
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        finished_at=None,
    )
    ok = 0
    errors: list[dict] = []
    out_dir = output_dir()

    for it in items:
        tid = str(it.get("tidalId") or "").strip()
        if not tid.isdigit():
            continue
        _set_queue(current=tid, done=ok + len(errors))
        if on_progress:
            on_progress(queue_status())
        path, err = download_track_to_manifest(
            tid,
            author=(it.get("author") or ""),
            title=(it.get("title") or ""),
            exe=exe,
            out_dir=out_dir,
            songs=songs,
        )
        if path and not err:
            ok += 1
        else:
            errors.append({"tidalId": tid, "error": err or "unknown"})
        _set_queue(done=ok + len(errors), errors=errors)

    _set_queue(running=False, current=None, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))

    meta_stats = {}
    if songs and ok:
        try:
            from tidal_vdj_metadata import apply_vdj_metadata_batch

            meta_stats = apply_vdj_metadata_batch(
                songs,
                tidal_ids=[str(it.get("tidalId") or "").strip() for it in items],
                only_missing=True,
            )
        except Exception as e:
            meta_stats = {"error": str(e)}

    return {
        "ok": True,
        "downloaded": ok,
        "failed": len(errors),
        "errors": errors,
        "metadata": meta_stats,
    }


def start_download_batch_async(items: list[dict], *, songs: Optional[list[dict]] = None) -> None:
    if queue_status().get("running"):
        raise RuntimeError("Pobieranie już trwa")

    def _run() -> None:
        try:
            run_download_batch(items, songs=songs)
        except Exception as e:
            _set_queue(running=False, errors=[{"error": str(e)}])

    threading.Thread(target=_run, daemon=True).start()
