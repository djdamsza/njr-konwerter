#!/usr/bin/env python3
"""
Launcher NJR konwerter – uruchamia serwer Flask i otwiera przeglądarkę.
Użycie: python launcher.py
"""
import socket
import webbrowser
import threading
import time


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
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)
    threading.Thread(target=open_browser, daemon=True).start()
    if port != 5050:
        print(f'NJR konwerter: {url} (port 5050 zajęty)')
    else:
        print(f'NJR konwerter: {url}')
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
