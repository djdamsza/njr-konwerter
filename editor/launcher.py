#!/usr/bin/env python3
"""
Launcher Imprezja Playlist Pro. Serwer Flask zostaje na tym komputerze.

Build otwiera własne okno. Uruchomienie z kodu otwiera przeglądarkę.

Zmienne środowiska:
  NJR_NO_BROWSER=1  – sam serwer, bez okna i bez karty
  NJR_WINDOW=1      – własne okno także przy uruchomieniu z kodu

Argumenty:
  --smoke-test      – szybki test importów (numpy, app) dla CI / PyInstaller
"""
import os
import socket
import sys
import webbrowser
import threading
import time
from typing import Optional

from ssl_utils import configure_ssl_env

configure_ssl_env()


def _strip_mac_quarantine() -> None:
    """Usuń quarantine z .app po zatwierdzeniu przez użytkownika — mniej pytań Gatekeeper przy kolejnych startach."""
    if sys.platform != 'darwin' or not getattr(sys, 'frozen', False):
        return
    import subprocess
    from pathlib import Path

    exe = Path(sys.executable).resolve()
    target = exe
    for parent in exe.parents:
        if parent.suffix == '.app':
            target = parent
            break
    subprocess.run(
        ['xattr', '-dr', 'com.apple.quarantine', str(target)],
        capture_output=True,
    )


_strip_mac_quarantine()


def _windows_shortcuts() -> None:
    from platform_paths import ensure_windows_shortcuts

    ensure_windows_shortcuts()


threading.Thread(target=_windows_shortcuts, name="njr-shortcuts", daemon=True).start()


def _find_running_njr_url(start: int = 5050, max_tries: int = 10) -> Optional[str]:
    """Jeśli NJR już działa (port 5050+), zwróć URL — unikamy drugiej instancji."""
    import urllib.error
    import urllib.request

    for port in range(start, start + max_tries):
        url = f'http://127.0.0.1:{port}'
        try:
            with urllib.request.urlopen(f'{url}/api/version', timeout=0.4) as resp:
                if resp.status == 200:
                    return url
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return None


def _find_free_port(start: int = 5050, max_tries: int = 10) -> int:
    """Zwraca pierwszy wolny port z zakresu [start, start+max_tries)."""
    for port in range(start, start + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return start  # fallback – app.run pokaże błąd


def _wait_until_up(url: str, timeout: float = 25.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'{url}/api/version', timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.15)
    return False


def _serve(port: int) -> None:
    from app import app
    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def main():
    from app_window import open_window, use_own_window

    own_window = use_own_window()
    open_browser = os.environ.get('NJR_NO_BROWSER', '').strip().lower() not in (
        '1', 'true', 'yes', 'on',
    ) and not own_window
    existing = _find_running_njr_url()
    if existing:
        if own_window:
            print(f'Imprezja Playlist Pro już działa: {existing}')
            open_window(existing)
            return
        if open_browser:
            webbrowser.open(existing)
        print(f'Imprezja Playlist Pro już działa: {existing}')
        return

    port = _find_free_port()
    url = f'http://127.0.0.1:{port}'
    if own_window:
        threading.Thread(target=_serve, args=(port,), name='njr-server', daemon=True).start()
        if not _wait_until_up(url):
            print(f'Nie udało się uruchomić serwera: {url}')
            return
        print(f'Imprezja Playlist Pro: {url}')
        try:
            open_window(url)
        except Exception as exc:
            print(f'Własne okno nie wstało ({exc}). Otwieram przeglądarkę.')
            webbrowser.open(url)
            _serve(port)
        return
    if open_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    if port != 5050:
        print(f'Imprezja Playlist Pro: {url} (port 5050 zajęty)')
        print('UWAGA Tidal OAuth: dodaj w developer.tidal.com Redirect URI:')
        print(f'  {url}/tidal-callback')
        print('(błąd 11102 na stronie logowania = brak tego URI w aplikacji Tidal)')
    else:
        print(f'Imprezja Playlist Pro: {url}')
    if not open_browser:
        print('(bez otwierania przeglądarki – NJR_NO_BROWSER=1)')
    _serve(port)


if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        import numpy  # noqa: F401 — pyrekordbox; musi działać w .exe na Windows

        from app import app  # noqa: F401

        print('NJR smoke-test OK')
        raise SystemExit(0)
    main()
