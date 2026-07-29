"""
Aktualizacje NJR Konwerter z GitHub Releases (jak Imprezja Quiz, ale dla PyInstaller).

Flow:
  1. check_for_updates() — skanuje assets w release'ach, wybiera właściwy plik Mac/Win
  2. start_download() — pobiera w tle do ~/Downloads/NJR-updates/
  3. install_update() — instaluje (Mac: DMG→/Applications; Win: podmiana .exe + restart)
"""
from __future__ import annotations

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
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ssl_utils import configure_ssl_env, urlopen

configure_ssl_env()

GITHUB_OWNER = "djdamsza"
GITHUB_REPO = "njr-konwerter"
MANUAL_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
USER_AGENT = "NJR-Konwerter-Updater"

# NJR-konwerter-1.0.3-macos-arm64.dmg / windows-x64.exe / macos-intel-x64.dmg
ASSET_RE = re.compile(
    r"^NJR-konwerter-(\d+(?:\.\d+){1,3})-(windows-x64\.exe|macos-arm64\.dmg|macos-intel-x64\.dmg)$",
    re.IGNORECASE,
)

_lock = threading.Lock()
_status: dict[str, Any] = {
    "status": "idle",  # idle | downloading | ready | installing | error
    "version": "",
    "currentVersion": "",
    "assetName": "",
    "downloadUrl": "",
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


def platform_asset_suffix() -> str:
    """Nazwa sufiksu assetu dla bieżącego OS/arch."""
    if sys.platform.startswith("win"):
        return "windows-x64.exe"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "macos-arm64.dmg"
        return "macos-intel-x64.dmg"
    raise RuntimeError(f"Aktualizacje nieobsługiwane na platformie: {sys.platform}")


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


def _http_json(url: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        d = base / "NJR-Konwerter" / "updates"
    else:
        d = home / "Downloads" / "NJR-updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_latest_asset(
    current_version: str,
    *,
    suffix: Optional[str] = None,
    force_newer_than: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Przeszukuje release'y GitHub i wybiera najnowszy asset dla platformy
    nowszy niż current_version (lub force_newer_than).
    """
    suffix = suffix or platform_asset_suffix()
    baseline = force_newer_than or current_version
    releases = _http_json(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=20"
    )
    best: Optional[dict[str, Any]] = None
    best_ver = ""
    for rel in releases or []:
        if rel.get("draft"):
            continue
        for asset in rel.get("assets") or []:
            name = asset.get("name") or ""
            m = ASSET_RE.match(name)
            if not m:
                continue
            ver, suf = m.group(1), m.group(2).lower()
            if suf != suffix.lower():
                continue
            if not version_gt(ver, baseline):
                continue
            if best is None or version_gt(ver, best_ver):
                best_ver = ver
                best = {
                    "version": ver,
                    "name": name,
                    "url": asset.get("browser_download_url") or "",
                    "size": int(asset.get("size") or 0),
                    "tag": rel.get("tag_name") or "",
                    "releaseUrl": rel.get("html_url") or MANUAL_URL,
                    "suffix": suf,
                }
    return best


def check_for_updates(current_version: str) -> dict[str, Any]:
    """Sprawdza GitHub i opcjonalnie uruchamia pobieranie."""
    force = (os.environ.get("NJR_FORCE_UPDATE_BASELINE") or "").strip() or None
    try:
        suffix = platform_asset_suffix()
    except RuntimeError as e:
        return {
            "available": False,
            "error": "unsupported_platform",
            "message": str(e),
            "manualUrl": MANUAL_URL,
            "currentVersion": current_version,
        }

    try:
        asset = find_latest_asset(current_version, suffix=suffix, force_newer_than=force)
    except urllib.error.HTTPError as e:
        return {
            "available": False,
            "error": "github_http",
            "message": f"GitHub API: HTTP {e.code}",
            "manualUrl": MANUAL_URL,
            "currentVersion": current_version,
        }
    except Exception as e:
        err = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err:
            msg = (
                "Błąd certyfikatów SSL w tej wersji aplikacji. "
                "Automatyczna aktualizacja nie zadziała — pobierz najnowszą wersję ręcznie (link poniżej)."
            )
        else:
            msg = f"Nie udało się sprawdzić aktualizacji: {e}"
        return {
            "available": False,
            "error": "github_error",
            "message": msg,
            "manualUrl": MANUAL_URL,
            "currentVersion": current_version,
        }

    if not asset:
        return {
            "available": False,
            "message": "Masz najnowszą wersję.",
            "manualUrl": MANUAL_URL,
            "currentVersion": current_version,
            "platform": suffix,
        }

    _set_status(
        status="idle",
        version=asset["version"],
        currentVersion=current_version,
        assetName=asset["name"],
        downloadUrl=asset["url"],
        path="",
        message=f"Dostępna wersja {asset['version']}",
        progress=0,
        error="",
    )
    # Auto-download (jak Imprezja Quiz autoDownload)
    start_download(asset["url"], asset["version"], asset["name"])
    return {
        "available": True,
        "version": asset["version"],
        "currentVersion": current_version,
        "assetName": asset["name"],
        "downloadUrl": asset["url"],
        "size": asset["size"],
        "message": f"Dostępna aktualizacja {asset['version']} (masz {current_version}). Pobieranie…",
        "manualUrl": asset.get("releaseUrl") or MANUAL_URL,
        "platform": suffix,
    }


def start_download(url: str, version: str, asset_name: str) -> None:
    dest = updates_dir() / asset_name

    def _run() -> None:
        try:
            _set_status(
                status="downloading",
                version=version,
                assetName=asset_name,
                downloadUrl=url,
                path="",
                progress=0,
                message=f"Pobieranie {asset_name}…",
                error="",
            )

            def on_prog(p: int) -> None:
                _set_status(progress=p, message=f"Pobieranie {asset_name}… {p}%")

            _download_file(url, dest, progress_cb=on_prog)
            _set_status(
                status="ready",
                path=str(dest),
                progress=100,
                message=f"Pobrano {asset_name}. Możesz zainstalować.",
            )
        except Exception as e:
            _set_status(
                status="error",
                error=str(e),
                message=f"Błąd pobierania: {e}",
            )

    t = threading.Thread(target=_run, name="njr-updater-download", daemon=True)
    t.start()


def _mac_installed_app() -> Path:
    return Path("/Applications/NJR Konwerter.app")


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
        return local / "NJR-Konwerter" / "NJR-konwerter.exe"
    return updates_dir() / "NJR-konwerter"


def _mac_find_payload_in_dmg(mount: Path) -> tuple[Path, str]:
    apps = sorted(p for p in mount.glob("*.app") if p.is_dir())
    if apps:
        return apps[0], "app"
    candidates = list(mount.rglob("NJR-konwerter"))
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
        raise RuntimeError("W DMG nie znaleziono NJR Konwerter.app ani pliku NJR-konwerter")
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
            out_app = out_bin if str(out_bin).endswith(".app") else out_bin.with_name("NJR Konwerter.app")
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
            staging = updates_dir() / f"NJR-konwerter-{st.get('version') or 'new'}"
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
