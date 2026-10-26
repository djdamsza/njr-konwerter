"""
Aktualizacje Imprezja Playlist Pro ze strony Nowa Jakość Rozrywki.

Jak fotobudka: przy starcie pyta GET /api/konwerter/update, bez logowania.
Kartę pokazuje tylko gdy numer na stronie jest wyższy. Plik musi leżeć
na https://nowajakoscrozrywki.pl/. Po pobraniu liczy SHA-256. Instalatora
nie uruchamia.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ssl_utils import configure_ssl_env, urlopen

configure_ssl_env()

SITE = "https://nowajakoscrozrywki.pl"
UPDATE_URL = SITE + "/api/konwerter/update"
MANUAL_URL = SITE + "/pobierz"
USER_AGENT = "ImprezjaPlaylistPro-Updater"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
SLOT_SUFFIX = {
    "windows": "windows-x64.exe",
    "macArm": "macos-arm64.dmg",
    "macIntel": "macos-intel-x64.dmg",
}

_lock = threading.Lock()
_status: dict[str, Any] = {
    "status": "idle",  # idle | downloading | ready | installing | error
    "version": "",
    "currentVersion": "",
    "assetName": "",
    "downloadUrl": "",
    "sha256": "",
    "path": "",
    "message": "",
    "progress": 0,
    "error": "",
}


def _set_status(**kwargs: Any) -> None:
    with _lock:
        _status.update(kwargs)


def get_status() -> dict[str, Any]:
    with _lock:
        return dict(_status)


def platform_slot() -> str:
    """Który plik ze strony pasuje do tego komputera."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "macArm"
        return "macIntel"
    raise RuntimeError(f"Aktualizacje nieobsługiwane na platformie: {sys.platform}")


def platform_asset_suffix() -> str:
    """Nazwa sufiksu pliku dla bieżącego OS/arch."""
    return SLOT_SUFFIX[platform_slot()]


def asset_name(version: str, slot: str) -> str:
    return f"Imprezja-Playlist-Pro-{version}-{SLOT_SUFFIX[slot]}"


def accepted_asset_names(version: str, slot: str) -> set[str]:
    """1.0.16 szuka Imprezja-Playlist-Pro. Strona wgrywa też NJR-konwerter."""
    suffix = SLOT_SUFFIX[slot]
    return {
        f"Imprezja-Playlist-Pro-{version}-{suffix}",
        f"NJR-konwerter-{version}-{suffix}",
    }


def parse_version(raw: str) -> tuple[int, ...]:
    s = (raw or "").strip().lstrip("vV")
    parts: list[int] = []
    for p in s.split("."):
        m = re.match(r"^(\d+)", p)
        if not m:
            break
        parts.append(int(m.group(1)))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def version_gt(a: str, b: str) -> bool:
    return parse_version(a) > parse_version(b)


def _http_json(url: str, timeout: float = 12.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def select_offer(payload: Any, current_version: str, slot: str) -> Optional[dict[str, Any]]:
    """Wybiera plik tego komputera. Zły adres, suma albo numer: brak oferty."""
    if not isinstance(payload, dict) or slot not in SLOT_SUFFIX:
        return None
    version = str(payload.get("version") or "").strip()
    if not VERSION_RE.match(version) or version == "0.0.0":
        return None
    if not version_gt(version, current_version):
        return None
    block = payload.get(slot)
    if not isinstance(block, dict):
        return None
    url = str(block.get("url") or "").strip()
    sha = str(block.get("sha256") or "").strip().lower()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    filename = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
    if parsed.scheme != "https" or host != "nowajakoscrozrywki.pl":
        return None
    if not parsed.path.startswith("/pobierz/") or filename not in accepted_asset_names(version, slot):
        return None
    if not SHA_RE.match(sha):
        return None
    return {
        "version": version,
        "changelog": str(payload.get("changelog") or ""),
        "name": filename,
        "url": url,
        "sha256": sha,
        "slot": slot,
    }


def _download_file(url: str, dest: Path, progress_cb=None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb and total:
                progress_cb(min(99, int(done * 100 / total)))
    tmp.replace(dest)
    if progress_cb:
        progress_cb(100)


def updates_dir() -> Path:
    """Katalog na skrypty podmiany. Pobrany instalator ląduje w Pobranych."""
    from platform_paths import app_support_dir
    d = app_support_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 256)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def check_for_updates(current_version: str) -> dict[str, Any]:
    """Pyta stronę. Nie pobiera pliku i nie przerywa startu przy błędzie sieci."""
    base = {
        "available": False,
        "manualUrl": MANUAL_URL,
        "currentVersion": current_version,
        "changelog": "",
    }
    try:
        slot = platform_slot()
    except RuntimeError as e:
        return {**base, "error": "unsupported_platform", "message": str(e)}
    url = UPDATE_URL + "?_=" + str(int(time.time() * 1000))
    try:
        payload = _http_json(url)
    except urllib.error.HTTPError:
        return {**base, "message": "Masz najnowszą wersję.", "platform": slot}
    except Exception:
        return {
            **base,
            "error": "offline",
            "message": "Nie udało się sprawdzić aktualizacji.",
            "platform": slot,
        }
    offer = select_offer(payload, current_version, slot)
    if not offer:
        return {**base, "message": "Masz najnowszą wersję.", "platform": slot}
    _set_status(
        status="idle",
        version=offer["version"],
        currentVersion=current_version,
        assetName=offer["name"],
        downloadUrl=offer["url"],
        sha256=offer["sha256"],
        path="",
        message=f"Dostępna wersja {offer['version']}",
        progress=0,
        error="",
    )
    return {
        "available": True,
        "version": offer["version"],
        "currentVersion": current_version,
        "changelog": offer["changelog"],
        "assetName": offer["name"],
        "downloadUrl": offer["url"],
        "sha256": offer["sha256"],
        "message": f"Jest nowa wersja {offer['version']}. Masz {current_version}.",
        "manualUrl": MANUAL_URL,
        "platform": slot,
    }


def start_download(url: str, version: str, asset_name: str, sha256: str = "") -> None:
    dest = downloads_dir() / asset_name
    expected = (sha256 or "").strip().lower()

    def _fail(message: str) -> None:
        if dest.is_file():
            try:
                dest.unlink()
            except OSError:
                pass
        _set_status(status="error", error=message, message=message, path="")

    def _run() -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "nowajakoscrozrywki.pl":
            _fail("Adres pliku jest spoza strony Nowa Jakość Rozrywki.")
            return
        if not SHA_RE.match(expected):
            _fail("Strona nie podała sumy pliku.")
            return
        try:
            _set_status(
                status="downloading",
                version=version,
                assetName=asset_name,
                downloadUrl=url,
                sha256=expected,
                path="",
                progress=0,
                message=f"Pobieranie {asset_name}…",
                error="",
            )

            def on_prog(p: int) -> None:
                _set_status(progress=p, message=f"Pobieranie {asset_name}… {p}%")

            _download_file(url, dest, progress_cb=on_prog)
            got = _sha256_file(dest)
            if got != expected:
                _fail("Pobrany plik się nie zgadza. Spróbuj jeszcze raz.")
                return
            _set_status(
                status="ready",
                path=str(dest),
                progress=100,
                message=f"Pobrano {asset_name}. Plik jest w Pobranych.",
            )
        except Exception as e:
            _fail(f"Błąd pobierania: {e}")

    t = threading.Thread(target=_run, name="njr-updater-download", daemon=True)
    t.start()


def _mac_installed_app() -> Path:
    return Path("/Applications/Imprezja Playlist Pro.app")


def _mac_running_app_bundle() -> Optional[Path]:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def default_install_target() -> Path:
    """Gdzie ma trafić zainstalowany pakiet ( .app na Mac )."""
    app = _mac_running_app_bundle()
    if app is not None:
        return app
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    if sys.platform == "darwin":
        return _mac_installed_app()
    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return local / "Imprezja Playlist Pro" / "Imprezja Playlist Pro.exe"
    return updates_dir() / "Imprezja Playlist Pro"


def _mac_find_payload_in_dmg(mount: Path) -> tuple[Path, str]:
    apps = sorted(p for p in mount.glob("*.app") if p.is_dir())
    if apps:
        return apps[0], "app"
    candidates = list(mount.rglob("Imprezja Playlist Pro"))
    binary = None
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            binary = c
            break
    if binary is None:
        for c in candidates:
            if c.is_file():
                binary = c
                break
    if binary is None:
        raise RuntimeError("W DMG nie znaleziono Imprezja Playlist Pro.app")
    return binary, "binary"


def _mac_extract_binary_from_dmg(dmg: Path, out_bin: Path) -> Path:
    mount = Path(tempfile.mkdtemp(prefix="njr-dmg-"))
    try:
        attach = subprocess.run(
            ["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly", "-mountpoint", str(mount)],
            capture_output=True,
            text=True,
            check=False,
        )
        if attach.returncode != 0:
            raise RuntimeError(attach.stderr.strip() or attach.stdout.strip() or "hdiutil attach failed")
        payload, kind = _mac_find_payload_in_dmg(mount)
        if kind == "app":
            out_app = out_bin if str(out_bin).endswith(".app") else out_bin.with_name("Imprezja Playlist Pro.app")
            if out_app.exists():
                shutil.rmtree(out_app, ignore_errors=True)
            shutil.copytree(payload, out_app, symlinks=True)
            subprocess.run(["xattr", "-cr", str(out_app)], capture_output=True)
            return out_app
        binary = payload
        out_bin.parent.mkdir(parents=True, exist_ok=True)
        if out_bin.exists():
            try:
                out_bin.unlink()
            except OSError:
                # Działający binary — kopiuj obok, podmiana przez skrypt
                staging = out_bin.with_name(out_bin.name + ".new")
                if staging.exists():
                    staging.unlink()
                shutil.copy2(binary, staging)
                staging.chmod(staging.stat().st_mode | 0o111)
                return staging
        shutil.copy2(binary, out_bin)
        out_bin.chmod(out_bin.stat().st_mode | 0o111)
        return out_bin
    finally:
        subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], capture_output=True)
        shutil.rmtree(mount, ignore_errors=True)


def _mac_replace_and_relaunch(new_payload: Path, target: Path) -> None:
    """Po zamknięciu procesu podmienia .app (lub binary) i uruchamia ponownie (macOS)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    is_app = target.suffix == ".app" or new_payload.suffix == ".app"
    new_app = new_payload if new_payload.suffix == ".app" else new_payload.parent if new_payload.parent.suffix == ".app" else None
    if is_app or new_app is not None:
        dest = target if target.suffix == ".app" else _mac_installed_app()
        src_app = new_app or new_payload
        if src_app.suffix != ".app":
            src_app = new_payload.with_suffix(".app")
        script = updates_dir() / f"install-{int(time.time())}.sh"
        script.write_text(
            f"""#!/bin/bash
set -e
sleep 1
DEST="{dest}"
SRC="{src_app if src_app.suffix == '.app' else new_payload.parent}"
if [ -d "$SRC" ] && [[ "$SRC" == *.app ]]; then
  if [ -d "$DEST" ]; then mv -f "$DEST" "$DEST.old" || rm -rf "$DEST"; fi
  cp -R "$SRC" "$DEST"
  xattr -cr "$DEST" 2>/dev/null || true
  open "$DEST"
else
  if [ -f "{target}" ]; then mv -f "{target}" "{target}.old" || rm -f "{target}"; fi
  cp -f "{new_payload}" "{target}"
  chmod +x "{target}"
  xattr -dr com.apple.quarantine "{target}" 2>/dev/null || true
  nohup "{target}" >/dev/null 2>&1 &
fi
rm -f "{script}"
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    script = updates_dir() / f"install-{int(time.time())}.sh"
    script.write_text(
        f"""#!/bin/bash
set -e
sleep 1
if [ -f "{target}" ]; then
  mv -f "{target}" "{target}.old" || rm -f "{target}"
fi
cp -f "{new_payload}" "{target}"
chmod +x "{target}"
xattr -dr com.apple.quarantine "{target}" 2>/dev/null || true
nohup "{target}" >/dev/null 2>&1 &
rm -f "{script}"
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)


def _windows_replace_and_relaunch(new_exe: Path, target: Path) -> None:
    """Podmienia uruchomiony .exe przez skrypt .bat (Windows blokuje nadpisanie)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    bat = updates_dir() / f"install-{int(time.time())}.bat"
    bat_body = f"""@echo off
setlocal
timeout /t 2 /nobreak >nul
if exist "{target}.old" del /f /q "{target}.old"
if exist "{target}" move /y "{target}" "{target}.old" >nul
copy /y "{new_exe}" "{target}" >nul
start "" "{target}"
del /f /q "%~f0"
"""
    bat.write_text(bat_body, encoding="utf-8")
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) or 0
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        close_fds=True,
        creationflags=flags,
    )


def reveal_download(path: str) -> dict[str, Any]:
    """Pokazuje pobrany plik w Finderze albo Eksploratorze. Tylko z Pobranych."""
    target = Path(path or "").expanduser()
    try:
        folder = downloads_dir().resolve()
        resolved = target.resolve()
        resolved.relative_to(folder)
    except (OSError, ValueError):
        return {"ok": False, "error": "To nie jest plik z Pobranych."}
    if not resolved.is_file():
        return {"ok": False, "error": "Pliku już nie ma."}
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(resolved)], check=True, timeout=5)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select," + str(resolved)], check=False, timeout=5)
        else:
            subprocess.run(["xdg-open", str(resolved.parent)], check=True, timeout=5)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def install_update(
    *,
    package_path: Optional[str] = None,
    target_path: Optional[str] = None,
    relaunch: bool = True,
) -> dict[str, Any]:
    """
    Instaluje pobrany pakiet.
    Mac: montuje DMG, kopiuje binary do target (/Applications lub frozen exe).
    Windows: kopiuje .exe (przez bat jeśli target = działający proces).
    """
    st = get_status()
    pkg = Path(package_path or st.get("path") or "")
    if not pkg.is_file():
        return {"ok": False, "error": "Brak pobranego pliku aktualizacji. Sprawdź aktualizacje ponownie."}

    target = Path(target_path) if target_path else default_install_target()
    _set_status(status="installing", message=f"Instalowanie do {target}…")

    try:
        if pkg.suffix.lower() == ".dmg":
            if sys.platform != "darwin":
                return {"ok": False, "error": "Plik .dmg można zainstalować tylko na macOS."}
            # Staging w katalogu updates — unikamy kolizji z działającym plikiem
            staging = updates_dir() / f"Imprezja-Playlist-Pro-{st.get('version') or 'new'}"
            extracted = _mac_extract_binary_from_dmg(pkg, staging)
            install_dest = target if target.suffix == ".app" else (
                extracted if extracted.suffix == ".app" else target
            )
            if extracted.suffix == ".app":
                install_dest = _mac_installed_app()
            running = False
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable).resolve()
                if install_dest.suffix == ".app":
                    running = exe.is_relative_to(install_dest.resolve())
                else:
                    running = exe == install_dest.resolve()
            if running and relaunch:
                _mac_replace_and_relaunch(extracted, install_dest)
                _set_status(status="ready", path=str(pkg), message="Instalator uruchomiony — restart…")
                threading.Timer(0.8, lambda: os._exit(0)).start()
                return {
                    "ok": True,
                    "installedPath": str(install_dest),
                    "version": st.get("version") or "",
                    "relaunch": True,
                    "message": "Aktualizacja zostanie zastosowana po restarcie.",
                }
            install_dest.parent.mkdir(parents=True, exist_ok=True)
            if extracted.suffix == ".app":
                if install_dest.exists():
                    shutil.rmtree(install_dest, ignore_errors=True)
                shutil.copytree(extracted, install_dest, symlinks=True)
                subprocess.run(["xattr", "-cr", str(install_dest)], capture_output=True)
                _set_status(status="ready", path=str(pkg), message=f"Zainstalowano: {install_dest}")
                if relaunch:
                    subprocess.Popen(["open", str(install_dest)], start_new_session=True)
                    if getattr(sys, "frozen", False):
                        threading.Timer(0.8, lambda: os._exit(0)).start()
                return {
                    "ok": True,
                    "installedPath": str(install_dest),
                    "version": st.get("version") or "",
                    "relaunch": relaunch,
                    "message": f"Zainstalowano NJR {st.get('version') or ''} → {install_dest}",
                }
            if install_dest.exists() and install_dest.resolve() != extracted.resolve():
                try:
                    install_dest.unlink()
                except OSError:
                    _mac_replace_and_relaunch(extracted, install_dest)
                    _set_status(status="ready", path=str(pkg), message=f"Instalacja w toku → {install_dest}")
                    if relaunch and getattr(sys, "frozen", False):
                        threading.Timer(0.8, lambda: os._exit(0)).start()
                    return {
                        "ok": True,
                        "installedPath": str(install_dest),
                        "version": st.get("version") or "",
                        "relaunch": relaunch,
                        "message": f"Instalacja w toku → {install_dest}",
                    }
            if extracted.resolve() != install_dest.resolve():
                shutil.copy2(extracted, install_dest)
                install_dest.chmod(install_dest.stat().st_mode | 0o111)
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(install_dest)],
                capture_output=True,
            )
            _set_status(status="ready", path=str(pkg), message=f"Zainstalowano: {install_dest}")
            if relaunch:
                subprocess.Popen([str(install_dest)], start_new_session=True)
                if getattr(sys, "frozen", False):
                    threading.Timer(0.8, lambda: os._exit(0)).start()
            return {
                "ok": True,
                "installedPath": str(install_dest),
                "version": st.get("version") or "",
                "relaunch": relaunch,
                "message": f"Zainstalowano NJR {st.get('version') or ''} → {install_dest}",
            }

        if pkg.suffix.lower() == ".exe":
            if not sys.platform.startswith("win"):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pkg, target)
                return {
                    "ok": True,
                    "installedPath": str(target),
                    "message": f"Skopiowano {pkg.name} → {target} (instalacja Windows wymaga Windows)",
                    "relaunch": False,
                }
            running = getattr(sys, "frozen", False) and Path(sys.executable).resolve() == target.resolve()
            if running:
                _windows_replace_and_relaunch(pkg, target)
                _set_status(status="ready", message="Instalator uruchomiony — aplikacja zrestartuje się.")
                threading.Timer(1.0, lambda: os._exit(0)).start()
                return {
                    "ok": True,
                    "installedPath": str(target),
                    "version": st.get("version") or "",
                    "relaunch": True,
                    "message": "Aktualizacja zostanie zastosowana po restarcie.",
                }
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pkg, target)
            if relaunch:
                subprocess.Popen([str(target)], close_fds=True)
            return {
                "ok": True,
                "installedPath": str(target),
                "version": st.get("version") or "",
                "relaunch": relaunch,
                "message": f"Zainstalowano → {target}",
            }

        return {"ok": False, "error": f"Nieobsługiwany typ pakietu: {pkg.suffix}"}
    except Exception as e:
        _set_status(status="error", error=str(e), message=f"Błąd instalacji: {e}")
        return {"ok": False, "error": str(e)}
