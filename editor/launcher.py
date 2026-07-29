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

from ssl_utils import configure_ssl_env

configure_ssl_env()


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
    from app import app
    port = _find_free_port()
    url = f'http://127.0.0.1:{port}'
    open_browser = os.environ.get('NJR_NO_BROWSER', '').strip().lower() not in (
        '1', 'true', 'yes', 'on',
    )
    if open_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
    if port != 5050:
        print(f'NJR konwerter: {url} (port 5050 zajęty)')
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
