#!/usr/bin/env python3
"""
Launcher NJR konwerter – uruchamia serwer Flask i otwiera przeglądarkę.
Użycie: python launcher.py

Zmienne środowiska:
  NJR_NO_BROWSER=1  – nie otwieraj karty (restart z terminala / agenta)

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


def main():
    open_browser = os.environ.get('NJR_NO_BROWSER', '').strip().lower() not in (
        '1', 'true', 'yes', 'on',
    )
    existing = _find_running_njr_url()
    if existing:
        if open_browser:
            webbrowser.open(existing)
        print(f'NJR konwerter już działa: {existing}')
        return

    from app import app
    port = _find_free_port()
    url = f'http://127.0.0.1:{port}'
    if open_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    if port != 5050:
        print(f'NJR konwerter: {url} (port 5050 zajęty)')
        print('UWAGA Tidal OAuth: dodaj w developer.tidal.com Redirect URI:')
        print(f'  {url}/tidal-callback')
        print('(błąd 11102 na stronie logowania = brak tego URI w aplikacji Tidal)')
    else:
        print(f'NJR konwerter: {url}')
    if not open_browser:
        print('(bez otwierania przeglądarki – NJR_NO_BROWSER=1)')
    app.run(
        host='127.0.0.1',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        import numpy  # noqa: F401 — pyrekordbox; musi działać w .exe na Windows

        from app import app  # noqa: F401

        print('NJR smoke-test OK')
        raise SystemExit(0)
    main()
